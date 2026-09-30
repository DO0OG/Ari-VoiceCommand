"""Genie 추론 자료 경로."""

import os

from tts.gsv.model_store import get_model_dir


def get_genie_data_path(*parts: str) -> str:
    return os.path.join(get_model_dir(), "GenieData", *parts)
