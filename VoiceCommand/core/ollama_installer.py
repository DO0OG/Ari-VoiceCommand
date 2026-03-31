"""Ollama Windows 설치 및 모델 다운로드 유틸."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import json
from dataclasses import dataclass
from typing import Callable, Iterable


OLLAMA_WINDOWS_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_OPENAI_URL = "http://localhost:11434/v1"
_LOCAL_OLLAMA_HOSTS = {"localhost", "127.0.0.1"}
_SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class OllamaModelOption:
    model: str
    label: str
    summary: str


COMMON_OLLAMA_MODELS: tuple[OllamaModelOption, ...] = (
    OllamaModelOption("llama3.2:3b", "Llama 3.2 3B", "가벼운 기본 채팅용"),
    OllamaModelOption("qwen3:4b", "Qwen 3 4B", "한국어 포함 다국어 균형형"),
    OllamaModelOption("gemma3:4b", "Gemma 3 4B", "단일 GPU/로컬 환경용 균형형"),
    OllamaModelOption("deepseek-r1:8b", "DeepSeek-R1 8B", "추론 성능 중심"),
    OllamaModelOption("nomic-embed-text", "Nomic Embed Text", "임베딩/검색용"),
)


def _default_install_dir() -> str:
    return os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "Programs",
        "Ollama",
    )


def _default_models_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".ollama", "models")


def normalize_models(models: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for model in models:
        name = str(model or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def find_ollama_executable() -> str | None:
    path = shutil.which("ollama")
    if path:
        return path
    candidate = os.path.join(_default_install_dir(), "ollama.exe")
    if os.path.exists(candidate):
        return candidate
    return None


def is_ollama_installed() -> bool:
    return find_ollama_executable() is not None


def _require_http_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in allowed_hosts:
        raise ValueError(f"허용되지 않는 URL입니다: {url}")
    return url


def _require_existing_executable(path: str, allowed_names: set[str]) -> str:
    candidate = os.path.abspath(path or "")
    if not candidate or not os.path.exists(candidate):
        raise FileNotFoundError(f"실행 파일을 찾을 수 없습니다: {path}")
    if os.path.basename(candidate).lower() not in {name.lower() for name in allowed_names}:
        raise ValueError(f"허용되지 않는 실행 파일입니다: {candidate}")
    return candidate


def _validate_model_name(model: str) -> str:
    name = str(model or "").strip()
    if not _SAFE_MODEL_RE.fullmatch(name):
        raise ValueError(f"허용되지 않는 모델 이름입니다: {model}")
    return name


def _safe_open_url(url: str, timeout: float = 2.0):
    request = urllib.request.Request(_require_http_url(url, _LOCAL_OLLAMA_HOSTS))
    return urllib.request.urlopen(request, timeout=timeout)  # nosec B310 - localhost http/https만 허용


def _post_local_json(url: str, payload: dict, timeout: float = 30.0) -> dict:
    request = urllib.request.Request(
        _require_http_url(url, _LOCAL_OLLAMA_HOSTS),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - localhost http/https만 허용
        raw = response.read().decode("utf-8", errors="replace").strip()
    return json.loads(raw) if raw else {}


def _download_installer(target_path: str, log: Callable[[str], None]) -> None:
    log("Ollama 설치 파일 다운로드 중...")
    request = urllib.request.Request(_require_http_url(OLLAMA_WINDOWS_INSTALLER_URL, {"ollama.com"}))
    with urllib.request.urlopen(request, timeout=30.0) as response:  # nosec B310 - https://ollama.com만 허용
        with open(target_path, "wb") as handle:
            shutil.copyfileobj(response, handle)


def _run_installer(installer_path: str, install_dir: str | None, log: Callable[[str], None]) -> None:
    safe_installer = _require_existing_executable(installer_path, {"OllamaSetup.exe"})
    arguments = ""
    if install_dir:
        arguments = f'/DIR="{os.path.abspath(install_dir)}"'
    log("Ollama 설치 프로그램을 실행합니다. 설치 창이 뜨면 계속 진행하세요.")
    os.startfile(safe_installer, arguments=arguments)


def _set_models_env(models_dir: str, log: Callable[[str], None]) -> None:
    if not models_dir:
        return
    os.makedirs(models_dir, exist_ok=True)
    current = os.environ.get("OLLAMA_MODELS", "").strip()
    if os.path.normcase(current) == os.path.normcase(models_dir):
        return
    log(f"모델 저장 경로 설정: {models_dir}")
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "OLLAMA_MODELS", 0, winreg.REG_EXPAND_SZ, models_dir)
    except Exception:
        pass
    os.environ["OLLAMA_MODELS"] = models_dir


def _server_ready(base_url: str) -> bool:
    try:
        with _safe_open_url(f"{base_url}/api/tags", timeout=2.0) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_ollama_server(ollama_exe: str, base_url: str, log: Callable[[str], None]) -> None:
    if _server_ready(base_url):
        return

    log("Ollama 서버를 시작합니다...")
    validated_exe = _require_existing_executable(ollama_exe, {"ollama.exe", "ollama"})
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["ollama", "serve"],
        executable=validated_exe,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )  # nosec B603

    deadline = time.time() + 30.0
    while time.time() < deadline:
        if _server_ready(base_url):
            return
        time.sleep(0.5)
    raise RuntimeError("Ollama 서버가 30초 내에 시작되지 않았습니다.")


def pull_models(
    ollama_exe: str,
    models: Iterable[str],
    base_url: str,
    log: Callable[[str], None],
) -> list[str]:
    installed: list[str] = []
    _require_existing_executable(ollama_exe, {"ollama.exe", "ollama"})
    for model in normalize_models(models):
        safe_model = _validate_model_name(model)
        log(f"모델 다운로드 중: {safe_model}")
        _post_local_json(f"{base_url}/api/pull", {"name": safe_model, "stream": False}, timeout=120.0)
        installed.append(safe_model)
    return installed


def install_ollama(
    install_dir: str | None = None,
    models_dir: str | None = None,
    models: Iterable[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Windows에서 Ollama를 설치하고 선택한 모델을 내려받는다."""
    if os.name != "nt":
        raise RuntimeError("Ollama 자동 설치는 현재 Windows만 지원합니다.")

    logger = log or print
    target_install_dir = os.path.abspath(install_dir) if install_dir else None
    target_models_dir = os.path.abspath(models_dir) if models_dir else ""
    selected_models = normalize_models(models or [])

    if target_models_dir:
        _set_models_env(target_models_dir, logger)

    if not is_ollama_installed():
        installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
        _download_installer(installer_path, logger)
        _run_installer(installer_path, target_install_dir, logger)
    else:
        logger("Ollama가 이미 설치되어 있어 설치 단계는 건너뜁니다.")

    ollama_exe = find_ollama_executable()
    if not ollama_exe:
        raise RuntimeError("설치 후에도 ollama.exe를 찾지 못했습니다.")

    ensure_ollama_server(ollama_exe, DEFAULT_OLLAMA_BASE_URL, logger)
    installed_models = pull_models(
        ollama_exe,
        selected_models,
        DEFAULT_OLLAMA_BASE_URL,
        logger,
    )

    logger("Ollama 설치 작업이 완료되었습니다.")
    return {
        "ollama_exe": ollama_exe,
        "install_dir": target_install_dir or os.path.dirname(ollama_exe),
        "models_dir": target_models_dir or os.environ.get("OLLAMA_MODELS", _default_models_dir()),
        "installed_models": installed_models,
        "base_url": DEFAULT_OLLAMA_OPENAI_URL,
    }
