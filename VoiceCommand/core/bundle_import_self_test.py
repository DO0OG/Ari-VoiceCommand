"""Runtime checks for dependencies required by the release bundle."""

import importlib
import importlib.resources
import json
import time
from pathlib import Path


_EDGE_TTS_VOICE = "en-US-AriaNeural"
_EDGE_TTS_ATTEMPTS = 3
_EDGE_TTS_TIMEOUT_SECONDS = 30


def _check_sdk_client(sdk, class_name):
    client = getattr(sdk, class_name)(api_key="bundle-import-self-test", max_retries=0)
    try:
        return {"client_created": True}
    finally:
        client.close()


# 앱의 다른 SDK 사용처와 같이 모듈 이름으로 불러온다.
def _check_openai_client():
    return _check_sdk_client(importlib.import_module("openai"), "OpenAI")


def _check_anthropic_client():
    return _check_sdk_client(importlib.import_module("anthropic"), "Anthropic")


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
    import asyncio
    import av
    import edge_tts

    av.Codec("mp3", "r")
    from audio.mp3_decoder import decode_mp3_to_pcm

    last_error = None
    audio_data = b""
    attempts = 0
    for attempts in range(1, _EDGE_TTS_ATTEMPTS + 1):
        try:
            async def synthesize_sample():
                communicate = edge_tts.Communicate(
                    "Ari release test.", _EDGE_TTS_VOICE
                )
                chunks = []
                async for item in communicate.stream():
                    if item["type"] == "audio":
                        chunks.append(item["data"])
                return b"".join(chunks)

            audio_data = asyncio.run(
                asyncio.wait_for(
                    synthesize_sample(), timeout=_EDGE_TTS_TIMEOUT_SECONDS
                )
            )
            if not audio_data:
                raise RuntimeError("Edge TTS returned no audio data")
            break
        except Exception as exc:
            last_error = exc
            if attempts < _EDGE_TTS_ATTEMPTS:
                time.sleep(attempts)
    if not audio_data:
        raise RuntimeError(
            f"Edge TTS synthesis failed after {_EDGE_TTS_ATTEMPTS} attempts: "
            f"{type(last_error).__name__}: {last_error}"
        ) from last_error

    pcm = decode_mp3_to_pcm(audio_data, 22050)
    if not pcm:
        raise RuntimeError("PyAV decoded no PCM audio from the Edge TTS sample")
    return {
        "edge_tts": getattr(edge_tts, "__version__", "available"),
        "voice": _EDGE_TTS_VOICE,
        "synthesis_attempts": attempts,
        "mp3_bytes": len(audio_data),
        "decoded_pcm_bytes": len(pcm),
    }


def _check_script_data_packages():
    import io

    import pandas as pd
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from openpyxl import load_workbook
    from reportlab.pdfgen.canvas import Canvas

    frame = pd.DataFrame({"value": [7, 11]})
    workbook_bytes = io.BytesIO()
    frame.to_excel(workbook_bytes, index=False, engine="openpyxl")
    workbook_bytes.seek(0)
    workbook = load_workbook(workbook_bytes, read_only=True, data_only=True)
    try:
        if workbook.active["A2"].value != 7:
            raise RuntimeError("pandas/openpyxl Excel round trip failed")
    finally:
        workbook.close()

    figure = Figure(figsize=(1, 1))
    FigureCanvasAgg(figure)
    figure.subplots().plot([0, 1], [7, 11])
    image = io.BytesIO()
    figure.savefig(image, format="png")
    if not image.getvalue().startswith(b"\x89PNG"):
        raise RuntimeError("matplotlib did not render a PNG image")

    pdf = io.BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(10, 10, "Ari release test")
    canvas.save()
    if not pdf.getvalue().startswith(b"%PDF"):
        raise RuntimeError("reportlab did not generate a PDF document")
    return {
        "pandas_rows": len(frame),
        "openpyxl": "xlsx round trip",
        "matplotlib": "PNG render",
        "reportlab": "PDF generation",
    }


def _check_whisper_and_vad():
    import onnxruntime
    from faster_whisper import WhisperModel

    hub = importlib.import_module("huggingface_hub")

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
        "huggingface_hub": getattr(hub, "__version__", "available"),
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
    # pandas를 먼저 불러오면 같은 프로세스의 onnxruntime DLL 초기화가 실패한다.
    # 앱에서는 스크립트가 별도 작업 프로세스에서 실행되므로 점검에서도 맨 마지막에 둔다.
    ("script_data_packages", _check_script_data_packages),
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
