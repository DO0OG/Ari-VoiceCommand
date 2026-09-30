"""Genie ONNX 추론 경로."""

# Genie (MIT), High-Logic, Core/Inference.py와 ModelManager.py의 추론 경로를 이식했습니다.

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np
import onnx
import onnxruntime as ort

from tts.gsv.audio import load_reference_audio
from tts.gsv.g2p import get_phones_and_bert


@dataclass
class ReferenceFeatures:
    phonemes_seq: np.ndarray
    text_bert: np.ndarray
    ssl_content: np.ndarray
    global_emb: np.ndarray | None = None
    global_emb_advanced: np.ndarray | None = None


def _external_offset(tensor: onnx.TensorProto) -> tuple[int, int]:
    values = {entry.key: entry.value for entry in tensor.external_data}
    offset = int(values.get("offset", "0"))
    length = int(values.get("length", "0"))
    return offset, length


def _session_with_weights(
    model_path: str,
    providers: list[str],
    options: ort.SessionOptions,
    weights_path: str = "",
    fp16_weights: bool = False,
) -> ort.InferenceSession:
    if not weights_path:
        return ort.InferenceSession(
            model_path, providers=providers, sess_options=options
        )

    model = onnx.load_model(model_path, load_external_data=False)
    if fp16_weights:
        raw_weights = np.fromfile(weights_path, dtype=np.float16)
        weight_data = raw_weights.astype(np.float32).tobytes()
    else:
        with open(weights_path, "rb") as source:
            weight_data = source.read()

    for tensor in model.graph.initializer:
        if tensor.data_location != onnx.TensorProto.EXTERNAL:
            continue
        offset, length = _external_offset(tensor)
        if length == 0:
            length = len(weight_data) - offset
        end = offset + length
        if offset < 0 or end > len(weight_data):
            raise ValueError(f"ONNX 외부 가중치 범위를 벗어났습니다: {tensor.name}")
        tensor.raw_data = weight_data[offset:end]
        del tensor.external_data[:]
        tensor.data_location = onnx.TensorProto.DEFAULT

    return ort.InferenceSession(
        model.SerializeToString(), providers=providers, sess_options=options
    )


class GSVEngine:
    """한 프로세스에서 공유하는 GPT-SoVITS/Genie 세션 묶음."""

    _SESSION_FILES = (
        ("t2s_encoder_fp32.onnx", "t2s_encoder_fp32.bin", False),
        (
            "t2s_first_stage_decoder_fp32.onnx",
            "t2s_shared_fp16.bin",
            True,
        ),
        ("t2s_stage_decoder_fp32.onnx", "t2s_shared_fp16.bin", True),
        ("vits_fp32.onnx", "vits_fp16.bin", True),
        ("prompt_encoder_fp32.onnx", "prompt_encoder_fp16.bin", True),
    )

    def __init__(self, model_dir: str, device: str = "auto"):
        self.model_dir = model_dir
        self._lock = threading.Lock()
        self._sessions: dict[str, ort.InferenceSession] = {}
        self._requested_device = device
        self._load_sessions()

    def _providers(self) -> list[str]:
        available = ort.get_available_providers()
        use_dml = self._requested_device in {"auto", "dml"}
        if use_dml and "DmlExecutionProvider" in available:
            return ["DmlExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    @staticmethod
    def _session_options() -> ort.SessionOptions:
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return options

    def _load_sessions(self) -> None:
        providers = self._providers()
        try:
            self._load_sessions_with(providers)
        except (OSError, RuntimeError, ValueError, TypeError):
            if providers == ["CPUExecutionProvider"]:
                raise
            logging.warning("DirectML 세션 로드 실패, CPU로 다시 로드합니다.", exc_info=True)
            self._sessions.clear()
            self._load_sessions_with(["CPUExecutionProvider"])

    def _load_sessions_with(self, providers: list[str]) -> None:
        options = self._session_options()
        for model_name, weight_name, is_fp16 in self._SESSION_FILES:
            model_path = os.path.join(self.model_dir, model_name)
            weight_path = os.path.join(self.model_dir, weight_name)
            self._sessions[model_name] = _session_with_weights(
                model_path,
                providers,
                options,
                weight_path,
                fp16_weights=is_fp16,
            )

        genie_dir = os.path.join(self.model_dir, "GenieData")
        hubert_path = os.path.join(
            genie_dir, "chinese-hubert-base", "chinese-hubert-base.onnx"
        )
        hubert_weights = os.path.join(
            genie_dir,
            "chinese-hubert-base",
            "chinese-hubert-base_weights_fp16.bin",
        )
        self._sessions["hubert"] = _session_with_weights(
            hubert_path,
            providers,
            options,
            hubert_weights,
            fp16_weights=True,
        )
        self._sessions["speaker"] = ort.InferenceSession(
            os.path.join(genie_dir, "speaker_encoder.onnx"),
            providers=providers,
            sess_options=options,
        )

    def prepare_reference(
        self, wav_path: str, text: str, language: str
    ) -> ReferenceFeatures:
        audio_32k, audio_16k = load_reference_audio(wav_path)
        phonemes_seq, text_bert = get_phones_and_bert(text, language)
        ssl_content = self._sessions["hubert"].run(
            None, {"input_values": audio_16k}
        )[0]
        speaker_embedding = self._sessions["speaker"].run(
            None, {"waveform": audio_16k}
        )[0]
        global_emb, global_emb_advanced = self._sessions[
            "prompt_encoder_fp32.onnx"
        ].run(
            None,
            {"ref_audio": audio_32k, "sv_emb": speaker_embedding},
        )
        return ReferenceFeatures(
            phonemes_seq=phonemes_seq,
            text_bert=text_bert,
            ssl_content=ssl_content,
            global_emb=global_emb,
            global_emb_advanced=global_emb_advanced,
        )

    def synthesize(
        self,
        text: str,
        reference: ReferenceFeatures,
        language: str,
        should_stop: Callable[[], bool],
    ) -> np.ndarray | None:
        with self._lock:
            if should_stop():
                return None
            text_seq, text_bert = get_phones_and_bert("。" + text, language)
            encoder = self._sessions["t2s_encoder_fp32.onnx"]
            first_stage = self._sessions["t2s_first_stage_decoder_fp32.onnx"]
            stage = self._sessions["t2s_stage_decoder_fp32.onnx"]
            y, prompts = encoder.run(
                None,
                {
                    "ref_seq": reference.phonemes_seq,
                    "text_seq": text_seq,
                    "ref_bert": reference.text_bert,
                    "text_bert": text_bert,
                    "ssl_content": reference.ssl_content,
                },
            )
            y, y_emb, *present_key_values = first_stage.run(
                None, {"x": y, "prompts": prompts}
            )
            input_names = [value.name for value in stage.get_inputs()]
            step_index = 0
            for step_index in range(500):
                if should_stop():
                    return None
                feed = dict(
                    zip(input_names, [y, y_emb, *present_key_values])
                )
                y, y_emb, stop_condition, *present_key_values = stage.run(
                    None, feed
                )
                if bool(np.asarray(stop_condition).reshape(-1)[0]):
                    break
            semantic = np.array(y, copy=True)
            semantic[0, -1] = 0
            semantic = semantic[:, -step_index:]
            semantic = np.expand_dims(semantic, axis=0)
            eos_indices = np.where(semantic >= 1024)
            if eos_indices[0].size:
                semantic = semantic[..., : int(eos_indices[-1][0])]
            if should_stop():
                return None
            return self._sessions["vits_fp32.onnx"].run(
                None,
                {
                    "text_seq": text_seq,
                    "pred_semantic": semantic,
                    "ge": reference.global_emb,
                    "ge_advanced": reference.global_emb_advanced,
                },
            )[0]

    def cleanup(self) -> None:
        with self._lock:
            self._sessions.clear()
