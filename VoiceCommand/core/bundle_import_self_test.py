"""Runtime checks for dependencies required by the release bundle."""

import importlib.resources
import json
from pathlib import Path


def _check_openai_client():
    from openai import OpenAI

    client = OpenAI(api_key="bundle-import-self-test", max_retries=0)
    try:
        return {"client_created": True}
    finally:
        client.close()


def _check_anthropic_client():
    from anthropic import Anthropic

    client = Anthropic(api_key="bundle-import-self-test", max_retries=0)
    try:
        return {"client_created": True}
    finally:
        client.close()


def _check_http_and_validation():
    import httpx
    import pydantic
    import pydantic_core

    return {
        "httpx": getattr(httpx, "__version__", "available"),
        "pydantic": pydantic.__version__,
        "pydantic_core": getattr(pydantic_core, "__version__", "available"),
    }


def _check_edge_tts_and_mp3_decoder():
    import av
    import edge_tts

    av.Codec("mp3", "r")
    from audio.mp3_decoder import decode_mp3_to_pcm

    if not callable(decode_mp3_to_pcm):
        raise RuntimeError("PyAV MP3 decoder helper is unavailable")
    return {"edge_tts": getattr(edge_tts, "__version__", "available"), "mp3_decoder": "available"}


def _check_whisper_and_vad():
    import faster_whisper
    import huggingface_hub
    import onnxruntime
    from faster_whisper import WhisperModel

    assets = importlib.resources.files("faster_whisper").joinpath("assets")
    vad_asset = next(
        (item for item in assets.iterdir() if item.name.startswith("silero_vad") and item.name.endswith(".onnx")),
        None,
    )
    if vad_asset is None:
        raise FileNotFoundError("faster_whisper Silero VAD ONNX asset is missing")
    with importlib.resources.as_file(vad_asset) as asset_path:
        onnxruntime.InferenceSession(str(asset_path), providers=["CPUExecutionProvider"])
    return {
        "whisper_model_class": WhisperModel.__name__,
        "huggingface_hub": getattr(huggingface_hub, "__version__", "available"),
        "vad_asset": vad_asset.name,
        "onnxruntime": getattr(onnxruntime, "__version__", "available"),
    }


def _check_scipy_resampler():
    import numpy as np
    import scipy
    from scipy.signal import resample_poly

    output = resample_poly(np.asarray([0.0, 1.0, 0.0, 1.0], dtype=np.float32), 2, 1)
    if output.shape != (8,):
        raise RuntimeError("scipy.signal.resample_poly returned an unexpected result")
    return {"scipy": scipy.__version__}


def _check_web_search():
    from ddgs import DDGS
    from lxml import etree

    etree.fromstring(b"<bundle-test/>")
    with DDGS():
        pass
    return {"ddgs": "available", "lxml": str(etree.LXML_VERSION)}


def _check_screenshot_dependencies():
    import cv2
    import numpy as np
    import pyautogui
    from PIL import Image

    haystack = np.zeros((6, 6), dtype=np.uint8)
    template = np.asarray([[1, 2], [3, 7]], dtype=np.uint8)
    haystack[3:5, 2:4] = template
    match = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
    if match.shape != (5, 5) or not np.isfinite(match).any() or np.nanmax(match) < 0.99:
        raise RuntimeError("OpenCV confidence matching failed")
    if not callable(pyautogui.screenshot):
        raise RuntimeError("pyautogui.screenshot is unavailable")
    image = Image.new("RGB", (1, 1))
    if image.size != (1, 1):
        raise RuntimeError("Pillow image creation failed")
    return {"pyautogui": "available", "pillow": getattr(Image, "__version__", "available"), "opencv": cv2.__version__}


def _check_mcp_server():
    import fastapi
    import pydantic
    import uvicorn
    from agent.mcp_server import AriMCPServer

    app = AriMCPServer(token="bundle-import-self-test").create_app()
    if not isinstance(app, fastapi.FastAPI):
        raise RuntimeError("MCP server did not create a FastAPI application")
    return {
        "fastapi": fastapi.__version__,
        "pydantic": pydantic.__version__,
        "uvicorn": uvicorn.__version__,
    }


_BUNDLE_CHECKS = (
    ("openai_client", _check_openai_client),
    ("anthropic_client", _check_anthropic_client),
    ("http_and_validation", _check_http_and_validation),
    ("edge_tts_mp3_decoder", _check_edge_tts_and_mp3_decoder),
    ("whisper_huggingface_vad", _check_whisper_and_vad),
    ("scipy_resampler", _check_scipy_resampler),
    ("ddgs_lxml", _check_web_search),
    ("pyautogui_pillow", _check_screenshot_dependencies),
    ("fastapi_mcp", _check_mcp_server),
)


def run_bundle_import_self_test(report_path: str) -> int:
    """Run each release dependency check and always write a JSON report."""
    checks = {}
    for name, check in _BUNDLE_CHECKS:
        try:
            details = check()
            checks[name] = {"ok": True, "details": details}
        except Exception as exc:
            checks[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    report = {"ok": all(item["ok"] for item in checks.values()), "checks": checks}
    try:
        output = Path(report_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return 1
    return 0 if report["ok"] else 1