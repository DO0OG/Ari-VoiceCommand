"""이미지 생성 서비스."""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
from datetime import datetime
from typing import Any

from core.resource_manager import ResourceManager


class ImageGenerator:
    def __init__(self, provider: str = "openai"):
        self.provider = provider

    def generate_image(self, prompt: str, size: str = "1024x1024", output_dir: str | None = None) -> dict[str, Any]:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("이미지 프롬프트가 필요합니다.")
        try:
            from core.config_manager import ConfigManager
            enabled = bool(ConfigManager.get("image_generation_enabled", False))
            provider = str(ConfigManager.get("image_gen_provider", self.provider) or self.provider)
        except Exception:
            enabled = False
            provider = self.provider
        if not enabled:
            return {"enabled": False, "message": "이미지 생성 기능이 비활성화되어 있습니다."}
        if provider != "openai":
            return {"enabled": True, "provider": provider, "message": "현재 OpenAI 이미지 생성만 지원합니다."}
        from openai import OpenAI
        client = OpenAI()
        response = client.images.generate(model="dall-e-3", prompt=prompt, size=size, n=1)
        image = response.data[0]
        out_dir = output_dir or ResourceManager.get_runtime_path("generated_images")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(out_dir, f"generated_{stamp}.png")
        if getattr(image, "b64_json", None):
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(image.b64_json))
        elif getattr(image, "url", None):
            self._download_image_url(str(image.url), path)
        else:
            meta_path = path + ".json"
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump({"prompt": prompt}, handle, ensure_ascii=False, indent=2)
            path = meta_path
        return {"enabled": True, "provider": provider, "path": path, "size": size}

    def _download_image_url(self, image_url: str, path: str) -> None:
        parsed = urllib.parse.urlparse(str(image_url or ""))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("이미지 다운로드 URL은 https만 허용합니다.")

        import requests

        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        with open(path, "wb") as handle:
            handle.write(response.content)


def get_image_generator() -> ImageGenerator:
    return ImageGenerator()
