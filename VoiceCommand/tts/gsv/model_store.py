"""GPT-SoVITS v2ProPlus와 Genie 추론 자료를 내려받는다."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Callable

import requests


_RELEASE_BASE = (
    "https://github.com/DO0OG/Ari-VoiceCommand/releases/download/"
    "tts-gsv-v2proplus-1"
)
_GENIE_BASE = (
    "https://huggingface.co/High-Logic/Genie/resolve/"
    "52b17272e0b7032415e85ad37b551db2386b1810/GenieData"
)
_BASE_FILES = {
    "prompt_encoder_fp16.bin": (
        44262912,
        "3647875f33deff144581647b0684da4361e5b747395c2639bca9d72e63006e8a",
    ),
    "prompt_encoder_fp32.onnx": (
        44464,
        "c4a3d8c1e385a17aecb7bd9c5ede5707ba390f85c3eb49b388deeaaaf53d2748",
    ),
    "t2s_encoder_fp32.bin": (
        11465732,
        "26f9894d6d713513516d34e3a20e4a9487b11784c2e17e3177aeb5b8c4e9fb1e",
    ),
    "t2s_encoder_fp32.onnx": (
        14568,
        "f6eb1acd47c8e6d36b777886981a49122e8e070a5eb9888d458fb188dc139f75",
    ),
    "t2s_first_stage_decoder_fp32.onnx": (
        416803,
        "868f395999508905128c5325c5db4f4b37b2e70e04d6e2719fec64cbb60ee7f9",
    ),
    "t2s_shared_fp16.bin": (
        153413634,
        "52350b81f9a3fbaa0f707c6c45af85f0edec6ec64231440ea75f9b049bffdabd",
    ),
    "t2s_stage_decoder_fp32.onnx": (
        417625,
        "3f02881c517423deb610f86d5441bd9825937c5069f3887cacefa1e9dc403b0d",
    ),
    "vits_fp16.bin": (
        124345856,
        "ed4eeaf2b97eeb8779ea07fb704c93f0b55c70f5b345d9dfbeed0f2813ba086d",
    ),
    "vits_fp32.onnx": (
        1611210,
        "2f918e08a1bfecc568de4cc5dc96135cb8baf37a07f4eb4ec9258a4854fcd3f3",
    ),
}
_GENIE_FILES = {
    "speaker_encoder.onnx": (
        184812166,
        "31ed0858f7059785dfd58731efb0effdbe39d5b9175b2b36f5a3341adbc0bb67",
    ),
    "chinese-hubert-base/chinese-hubert-base.onnx": (
        237741,
        "f517f4270ed864fd84594662838c581b63ff4178f73572882e3737c4dacd68ac",
    ),
    "chinese-hubert-base/chinese-hubert-base_weights_fp16.bin": (
        188741632,
        "83abf6483f49d51fa4da5634c7131a2670f01da96b94263cafdb564d24e92cea",
    ),
    "G2P/EnglishG2P/checkpoint20.npz": (
        3342298,
        "b8af35e4596d8dd5836dfd3fe9b2ba4f97b9c311efe8879544cbcfcbd566d8c6",
    ),
    "G2P/EnglishG2P/cmudict-fast.rep": (
        3613898,
        "53bfef0f27d7dd74d1ba74563d1e076d3e0672ce3596cb2d6c0d52ac9ad01f6d",
    ),
    "G2P/EnglishG2P/cmudict.rep": (
        3731285,
        "0e601d017d6e6f958443d41cd8922b4cd7598b3ba2056253a33f3e5a35f38494",
    ),
    "G2P/EnglishG2P/engdict-hot.rep": (
        75,
        "1c80418fe6fe5d537302ae67afd3612478997b35f2cf37cff52f959ed4334a71",
    ),
    "G2P/EnglishG2P/engdict_cache.pickle": (
        5965909,
        "9bff9393f4b192d873a11335efc8f124771087b6dc847d34fd240c2846889d2b",
    ),
    "G2P/EnglishG2P/namedict_cache.pickle": (
        760663,
        "559552094c4a6e995213e3fa586330e078ef8cb3a7a95a3109e945111cd2bfc1",
    ),
    (
        "G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/"
        "averaged_perceptron_tagger_eng.classes.json"
    ): (
        285,
        "d152ffa69d45b8357276341a3d592c6c025911d52ec0d9068d4f382560dd48b6",
    ),
    (
        "G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/"
        "averaged_perceptron_tagger_eng.tagdict.json"
    ): (
        25788,
        "4c713731cb06727736962bc8cd94ad919217a040e76691059af99bc0c2c9c246",
    ),
    (
        "G2P/EnglishG2P/taggers/averaged_perceptron_tagger_eng/"
        "averaged_perceptron_tagger_eng.weights.json"
    ): (
        5677744,
        "789e8e35f6fac656d9b7eccea29ba4e8a137cbb5b525dd31f39e4291a9e80832",
    ),
    "G2P/EnglishG2P/wordsegment/bigrams.txt": (
        5566017,
        "3bd156ba9477842930c5609fc7113864e3c093a97880736fba522c7edb4ba799",
    ),
    "G2P/EnglishG2P/wordsegment/unigrams.txt": (
        4952042,
        "fd27e15b83ee7a55d8e17731a397eb4d389cbe2afd1c26afcba8ee2634c0a6d5",
    ),
    "G2P/EnglishG2P/wordsegment/words.txt": (
        1763461,
        "0e5079e9a76bf19f303b8fa070a37372d8e9bf5af7f36225d95da1c8df357e00",
    ),
}
_OPEN_JTALK_ZIP = (
    "open_jtalk_dic_pyopenjtalk_plus_0.4.1.post9.zip",
    23485160,
    "7e7916813e9f8dbedec32050be9ce90de97b5b0c89453fd284f2fe3162a5023a",
)
_CHUNK_SIZE = 1024 * 1024
_TIMEOUT = (10, 60)
ProgressCallback = Callable[[int, int], None]


def get_model_dir() -> str:
    """사용자 데이터 폴더의 GSV 모델 위치를 반환한다."""
    from core.resource_manager import ResourceManager

    return ResourceManager.get_writable_path(os.path.join("local_tts", "gsv"))


def _assets() -> list[tuple[str, str, int, str]]:
    entries = [
        ("release", name, size, digest)
        for name, (size, digest) in _BASE_FILES.items()
    ]
    entries.extend(
        ("genie", name, size, digest)
        for name, (size, digest) in _GENIE_FILES.items()
    )
    name, size, digest = _OPEN_JTALK_ZIP
    entries.append(("release", name, size, digest))
    return entries


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("모델 설치가 취소되었습니다.")


def _extract_japanese_dictionary(zip_path: str, destination: str) -> None:
    root = os.path.abspath(destination + ".part")
    dictionary = os.path.join(root, "dictionary")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            for entry in archive.infolist():
                member = entry.filename.replace("\\", "/")
                member_path = PurePosixPath(member)
                target = os.path.abspath(os.path.join(root, *member_path.parts))
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or os.path.commonpath((root, target)) != root
                ):
                    raise ValueError("일본어 사전 압축 파일에 잘못된 경로가 있습니다.")
            archive.extractall(root)

        if not os.path.isfile(os.path.join(dictionary, "sys.dic")):
            raise ValueError("일본어 사전에서 sys.dic 파일을 찾을 수 없습니다.")
        if os.path.isdir(destination):
            shutil.rmtree(destination)
        os.replace(dictionary, destination)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _download_asset(
    kind: str,
    relative_path: str,
    expected_size: int,
    expected_sha256: str,
    model_dir: str,
    cancel_event: Event | None,
    progress_callback: ProgressCallback | None,
    downloaded_before: int,
    total_size: int,
) -> int:
    relative_path_obj = Path(relative_path)
    subdir = "GenieData" if kind == "genie" else ""
    final_path = os.path.join(model_dir, subdir, *relative_path_obj.parts)
    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    if os.path.isfile(final_path) and os.path.getsize(final_path) == expected_size:
        if _sha256(final_path) == expected_sha256:
            return expected_size
    part_path = final_path + ".part"
    if os.path.exists(part_path):
        os.remove(part_path)

    base = _GENIE_BASE if kind == "genie" else _RELEASE_BASE
    url = f"{base}/{relative_path.replace(os.sep, '/')}"
    digest = hashlib.sha256()
    received = 0
    try:
        with requests.get(url, stream=True, timeout=_TIMEOUT) as response:
            response.raise_for_status()
            with open(part_path, "wb") as target:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    _check_cancel(cancel_event)
                    if not chunk:
                        continue
                    if received + len(chunk) > expected_size:
                        raise ValueError(f"모델 파일 크기가 예상보다 큽니다: {relative_path}")
                    target.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress_callback:
                        progress_callback(
                            downloaded_before + received, total_size
                        )
        _check_cancel(cancel_event)
        if received != expected_size or digest.hexdigest() != expected_sha256:
            raise ValueError(f"모델 파일 검증에 실패했습니다: {relative_path}")
        os.replace(part_path, final_path)
        return received
    except (OSError, requests.RequestException, ValueError, InterruptedError):
        if os.path.exists(part_path):
            os.remove(part_path)
        raise


def install_model(
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> str:
    """필요한 모델 파일을 SHA256 검증 후 설치한다."""
    model_dir = get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    assets = _assets()
    total_size = sum(size for _kind, _path, size, _digest in assets)
    downloaded = 0
    try:
        for kind, path, size, digest in assets:
            _check_cancel(cancel_event)
            downloaded += _download_asset(
                kind,
                path,
                size,
                digest,
                model_dir,
                cancel_event,
                progress_callback,
                downloaded,
                total_size,
            )

        archive_path = os.path.join(model_dir, _OPEN_JTALK_ZIP[0])
        _check_cancel(cancel_event)
        _extract_japanese_dictionary(
            archive_path, os.path.join(model_dir, "open_jtalk_dic")
        )
        if progress_callback:
            progress_callback(total_size, total_size)
        return model_dir
    except InterruptedError:
        raise
    except (OSError, requests.RequestException, ValueError, zipfile.BadZipFile) as exc:
        logging.error("로컬 TTS 모델 설치 실패: %s", exc)
        raise


def is_model_installed(verify_hash: bool = True) -> bool:
    """모든 고정 파일과 일본어 사전이 정상 설치됐는지 확인한다."""
    model_dir = get_model_dir()
    for kind, relative_path, size, expected_sha256 in _assets():
        subdir = "GenieData" if kind == "genie" else ""
        path = os.path.join(model_dir, subdir, *Path(relative_path).parts)
        if not os.path.isfile(path) or os.path.getsize(path) != size:
            return False
        if verify_hash and _sha256(path) != expected_sha256:
            return False
    return os.path.isfile(os.path.join(model_dir, "open_jtalk_dic", "sys.dic"))
