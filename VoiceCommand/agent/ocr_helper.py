"""
화면 또는 지정 영역에서 텍스트를 추출하는 경량 OCR 헬퍼.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Optional

log = logging.getLogger(__name__)

_reader: Optional[Any] = None
_reader_lock = threading.Lock()
_warned_unavailable: bool = False


def _try_import_easyocr():
    try:
        import easyocr
        return easyocr
    except ImportError:
        return None


def _try_import_pytesseract():
    try:
        import pytesseract
        return pytesseract
    except ImportError:
        return None


def _get_easyocr_reader():
    global _reader
    easyocr = _try_import_easyocr()
    if easyocr is None:
        return None
    if _reader is None:
        with _reader_lock:
            if _reader is None:
                try:
                    _reader = easyocr.Reader(["ko", "en"], gpu=False)
                except Exception as exc:
                    log.warning("[OCR] easyocr 초기화 실패: %s", exc)
                    return None
    return _reader


def _warn_unavailable_once():
    global _warned_unavailable
    if _warned_unavailable:
        return
    _warned_unavailable = True
    log.warning("[OCR] easyocr/pytesseract 미설치로 OCR 기능이 비활성화됩니다.")


def _grab_image(region: Optional[tuple[int, int, int, int]] = None):
    try:
        from PIL import ImageGrab
    except ImportError:
        log.warning("[OCR] Pillow(ImageGrab) 미설치")
        return None
    try:
        bbox = None
        if region:
            left, top, width, height = region
            bbox = (left, top, left + width, top + height)
        return ImageGrab.grab(bbox=bbox)
    except Exception as exc:
        log.warning("[OCR] 화면 캡처 실패: %s", exc)
        return None


def _ocr_pil_image(img) -> str:
    if img is None:
        return ""

    reader = _get_easyocr_reader()
    if reader is not None:
        try:
            import numpy as np
            results = reader.readtext(np.array(img), detail=0, paragraph=True)
            return "\n".join(str(item).strip() for item in results if str(item).strip())
        except Exception as exc:
            log.warning("[OCR] easyocr 추출 실패: %s", exc)

    pytesseract = _try_import_pytesseract()
    if pytesseract is not None:
        try:
            return str(pytesseract.image_to_string(img, lang="kor+eng") or "").strip()
        except Exception as exc:
            log.warning("[OCR] pytesseract 추출 실패: %s", exc)

    _warn_unavailable_once()
    return ""


def ocr_screen(region: Optional[tuple[int, int, int, int]] = None) -> str:
    return _ocr_pil_image(_grab_image(region))


def ocr_image_file(path: str) -> str:
    try:
        from PIL import Image
        return _ocr_pil_image(Image.open(path))
    except Exception as exc:
        log.warning("[OCR] 이미지 파일 OCR 실패: %s", exc)
        return ""


def ocr_contains(text_to_find: str, region=None, case_sensitive=False) -> bool:
    target = str(text_to_find or "").strip()
    if not target:
        return False
    screen_text = ocr_screen(region)
    if not case_sensitive:
        return target.lower() in screen_text.lower()
    return target in screen_text


def get_screen_text_snapshot() -> dict[str, str]:
    raw_text = ocr_screen()
    return {
        "raw_text": raw_text,
        "lines": [line.strip() for line in raw_text.splitlines() if line.strip()],
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    snapshot = get_screen_text_snapshot()
    logging.debug("%s", snapshot["timestamp"])
    logging.debug("%s", snapshot["raw_text"][:500])
