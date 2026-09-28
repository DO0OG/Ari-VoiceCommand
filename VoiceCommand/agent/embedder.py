"""전략 기억 검색용 텍스트 임베딩 모듈."""

from __future__ import annotations

import hashlib
import importlib
import logging
import math
import os
import threading
from typing import Any, Optional

import httpx
import numpy as np

from agent.agent_math import cosine_similarity as _cosine_similarity
from core.config_manager import ConfigManager

_LOCAL_MODEL = (
    "Xenova/paraphrase-multilingual-MiniLM-L12-v2",
    "2c4055b12046f11709e9df2c122e59ffbdc2f900",
    "onnx/model_int8.onnx",
    "tokenizer.json",
    384,
)
_EMBED_DIM_FALLBACK = 64
log = logging.getLogger(__name__)


class Embedder:
    DEFAULT_LOCAL_MODEL = _LOCAL_MODEL[0]

    def __init__(self, preferred: str = "auto", progress_callback=None):
        self.backend = "onnx"
        self.dim = _LOCAL_MODEL[4]
        self.model_id = f"{_LOCAL_MODEL[0]}@{_LOCAL_MODEL[1]}/{_LOCAL_MODEL[2]}"
        self._session = None
        self._tokenizer = None
        self._client = None
        self._remote_error_types = (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        )
        self._load_lock = threading.Lock()
        self._ready_event = threading.Event()
        self._status_lock = threading.Lock()
        self.status = "not_started"
        self.progress = 0.0
        self.progress_callback = progress_callback
        self._warmup_started = False
        self._init_backend(preferred)

    def _init_backend(self, preferred: str):
        if preferred in ("auto", "openai"):
            self._try_openai()

    def _remote_embedding_enabled(self) -> bool:
        try:
            return ConfigManager.get("embedding_remote_enabled", False) is True
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return False

    def _try_sentence_transformers(self) -> bool:
        return False

    def _model_cache_dir(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_runtime_path("models")
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            return os.path.join(os.getcwd(), ".ari_runtime", "models")

    def _emit_progress(self, event: str, **payload) -> None:
        if callable(self.progress_callback):
            try:
                self.progress_callback(event, **payload)
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                log.debug("[Embedder] progress callback 실패: %s", exc)

    def _set_status(self, status: str, progress: float) -> None:
        with self._status_lock:
            self.status = status
            self.progress = min(max(float(progress), 0.0), 1.0)
        self._emit_progress(status, model=self.model_id, progress=self.progress)

    def _try_openai(self) -> bool:
        api_key = self._get_api_key("openai_api_key") if self._remote_embedding_enabled() else ""
        if not api_key:
            return False
        try:
            openai_module = importlib.import_module("openai")
            api_error = getattr(openai_module, "OpenAIError", None)
            if isinstance(api_error, type) and issubclass(api_error, Exception):
                self._remote_error_types += (api_error,)
            self._client = openai_module.OpenAI(
                api_key=api_key,
                timeout=httpx.Timeout(self._read_timeout_seconds(), connect=5.0),
                max_retries=1,
            )
            self.backend = "openai"
            self.dim = 1536
            self.model_id = "openai:text-embedding-3-small"
            self.status = "remote"
            self._ready_event.set()
            return True
        except self._remote_error_types as exc:
            log.debug("[Embedder] openai 비활성: %s", exc)
            return False

    def _read_timeout_seconds(self) -> float:
        default = 30.0
        try:
            value = ConfigManager.get("llm_timeout_chat_seconds", default)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return default
        if isinstance(value, bool):
            return default
        try:
            seconds = float(value)
        except (OverflowError, TypeError, ValueError):
            return default
        if not math.isfinite(seconds) or seconds <= 0:
            return default
        return seconds

    def _try_gemini(self) -> bool:
        return False

    def _get_api_key(self, key: str) -> str:
        try:
            return str(ConfigManager.load_settings().get(key, "") or "").strip()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return os.environ.get(key.upper(), "")

    def _start_local_load(self) -> None:
        if self.backend != "onnx":
            return
        with self._load_lock:
            if self.status != "not_started":
                return
            self._set_status("downloading", 0.0)
            loader = threading.Thread(
                target=self._load_local_model,
                daemon=True,
                name="AriOnnxEmbedderDownload",
            )
            try:
                loader.start()
            except RuntimeError as exc:
                log.debug("[Embedder] ONNX 다운로드 시작 실패: %s", exc)
                self._set_status("failed", 0.0)
                self._ready_event.set()

    def _load_local_model(self) -> None:
        try:
            from huggingface_hub import hf_hub_download
            from tqdm.auto import tqdm

            embedder = self

            class _ProgressTqdm(tqdm):
                def update(self, n=1):
                    result = super().update(n)
                    fraction = self.n / self.total if self.total else 0.0
                    embedder._set_status("downloading", fraction)
                    return result

            model_repo, revision, model_file, tokenizer_file = _LOCAL_MODEL[:4]
            cache_dir = self._model_cache_dir()
            common = {
                "repo_id": model_repo,
                "revision": revision,
                "cache_dir": cache_dir,
                "tqdm_class": _ProgressTqdm,
            }
            model_path = hf_hub_download(filename=model_file, **common)
            tokenizer_path = hf_hub_download(filename=tokenizer_file, **common)
            self._set_status("loading", 1.0)
            from tokenizers import Tokenizer
            runtime = importlib.import_module("onnxruntime")
            tokenizer = Tokenizer.from_file(tokenizer_path)
            tokenizer.enable_truncation(max_length=256)
            session = runtime.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = tokenizer
            self._session = session
            self._set_status("ready", 1.0)
            self._ready_event.set()
            self._emit_progress("download_complete", model=self.model_id)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("[Embedder] ONNX 모델을 사용할 수 없습니다: %s", exc)
            self._set_status("failed", 0.0)
            self._emit_progress("download_failed", model=self.model_id)
        except Exception as exc:
            log.warning("[Embedder] ONNX 모델 초기화 실패: %s", exc)
            self._set_status("failed", 0.0)
            self._emit_progress("download_failed", model=self.model_id)
        finally:
            self._ready_event.set()

    def wait_until_ready(self) -> bool:
        if self.backend == "openai":
            return (
                self._remote_embedding_enabled()
                and self._client is not None
                and self.status == "remote"
            )
        self._start_local_load()
        self._ready_event.wait()
        return self.status == "ready"

    def embed(self, text: str) -> Optional[np.ndarray]:
        text = str(text or "").strip()
        if not text:
            return None
        if self.backend == "openai":
            if (
                not self._remote_embedding_enabled()
                or self.status != "remote"
                or self._client is None
            ):
                return None
            try:
                response = self._client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text,
                )
                vector = np.asarray(response.data[0].embedding, dtype=np.float32)
                if vector.shape != (self.dim,) or not np.isfinite(vector).all():
                    raise ValueError("임베딩 벡터 형식이 올바르지 않습니다.")
                return vector
            except self._remote_error_types + (
                AttributeError,
                IndexError,
                httpx.HTTPError,
                KeyError,
            ) as exc:
                log.debug("[Embedder] openai embed 실패: %s", exc)
                self._set_status("failed", 0.0)
                return None
        if self._session is None or self._tokenizer is None:
            self._start_local_load()
            return None
        try:
            encoded = self._tokenizer.encode(text)
            values = {
                "input_ids": np.asarray([encoded.ids], dtype=np.int64),
                "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
                "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
            }
            input_names = {item.name for item in self._session.get_inputs()}
            inputs = {name: value for name, value in values.items() if name in input_names}
            hidden = np.asarray(self._session.run(None, inputs)[0], dtype=np.float32)[0]
            if (
                hidden.shape != (len(encoded.ids), self.dim)
                or not np.isfinite(hidden).all()
            ):
                return None
            mask = np.asarray(encoded.attention_mask, dtype=np.float32)[:, None]
            vector = (hidden * mask).sum(axis=0) / max(float(mask.sum()), 1.0)
            norm = float(np.linalg.norm(vector))
            return vector / norm if norm else None
        except (AttributeError, IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            log.debug("[Embedder] ONNX embed 실패: %s", exc)
            return None

    def embed_batch(self, texts: list[str]) -> list[Optional[np.ndarray]]:
        if self.backend == "onnx" and self._session is None:
            self._start_local_load()
            return [None] * len(texts)
        return [self.embed(text) for text in texts]

    def _fallback_embed(self, text: str) -> np.ndarray:
        vector = np.zeros(_EMBED_DIM_FALLBACK, dtype=float)
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % _EMBED_DIM_FALLBACK
            vector[idx] += 1.0
        return vector

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        return _cosine_similarity(a, b)

    def warmup_async(self, sample_text: str = "아리 성능 워밍업") -> None:
        if self.backend != "onnx" or self._warmup_started:
            return
        self._warmup_started = True

        def _worker():
            try:
                self.embed(sample_text)
            except (AttributeError, httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
                log.debug("[Embedder] warmup 실패: %s", exc)

        threading.Thread(target=_worker, daemon=True, name="AriEmbedderWarmup").start()


class CrossEncoderReranker:
    def __init__(self):
        self._model = None
        self._try_load()

    def _try_load(self):
        self._model = None

    def rerank(self, query: str, candidates: list[tuple[float, Any]]) -> list[tuple[float, Any]]:
        return candidates


_embedder: Optional[Embedder] = None
_reranker: Optional[CrossEncoderReranker] = None
_embedder_lock = threading.Lock()
_reranker_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = Embedder()
    return _embedder


def reset_embedder() -> None:
    global _embedder
    with _embedder_lock:
        _embedder = None


def get_reranker() -> CrossEncoderReranker:
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = CrossEncoderReranker()
    return _reranker


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    embedder = get_embedder()
    logging.debug("%s %s", embedder.backend, embedder.dim)
