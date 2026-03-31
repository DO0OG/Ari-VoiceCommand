"""Ollama Windows 설치 및 모델 다운로드 유틸."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable


OLLAMA_WINDOWS_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_OPENAI_URL = "http://localhost:11434/v1"


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


def _download_installer(target_path: str, log: Callable[[str], None]) -> None:
    log("Ollama 설치 파일 다운로드 중...")
    urllib.request.urlretrieve(OLLAMA_WINDOWS_INSTALLER_URL, target_path)


def _run_installer(installer_path: str, install_dir: str | None, log: Callable[[str], None]) -> None:
    cmd = [installer_path]
    if install_dir:
        cmd.append(f'/DIR="{install_dir}"')
    log("Ollama 설치 프로그램을 실행합니다. 설치 창이 뜨면 계속 진행하세요.")
    subprocess.run(cmd, check=True)


def _set_models_env(models_dir: str, log: Callable[[str], None]) -> None:
    if not models_dir:
        return
    os.makedirs(models_dir, exist_ok=True)
    current = os.environ.get("OLLAMA_MODELS", "").strip()
    if os.path.normcase(current) == os.path.normcase(models_dir):
        return
    log(f"모델 저장 경로 설정: {models_dir}")
    subprocess.run(
        ["setx", "OLLAMA_MODELS", models_dir],
        check=False,
        capture_output=True,
        text=True,
    )
    os.environ["OLLAMA_MODELS"] = models_dir


def _server_ready(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2.0) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_ollama_server(ollama_exe: str, base_url: str, log: Callable[[str], None]) -> None:
    if _server_ready(base_url):
        return

    log("Ollama 서버를 시작합니다...")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [ollama_exe, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )

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
    env = os.environ.copy()
    env.setdefault("OLLAMA_HOST", base_url.replace("http://", "").replace("https://", ""))
    for model in normalize_models(models):
        log(f"모델 다운로드 중: {model}")
        subprocess.run([ollama_exe, "pull", model], check=True, env=env)
        installed.append(model)
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

