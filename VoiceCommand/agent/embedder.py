from __future__ import annotations

"""
전략 기억 검색용 텍스트 임베딩 모듈.
"""

import hashlib
import importlib
import logging
import os
from typing import Any, Optional

import numpy as np

_EMBED_DIM_MINILM = 384
_EMBED_DIM_FALLBACK = 64
log = logging.getLogger(__name__)


class Embedder:
    def __init__(self, preferred: str = "auto"):
        self.backend: str = "fallback"
        self.dim: int = _EMBED_DIM_FALLBACK
        self._model = None
        self._client = None
        self._init_backend(preferred)

    def _init_backend(self, preferred: str):
        order = [preferred] if preferred != "auto" else ["sentence_transformers", "openai", "gemini", "fallback"]
        for candidate in order:
            if candidate == "sentence_transformers" and self._try_sentence_transformers():
                return
            if candidate == "openai" and self._try_openai():
                return
            if candidate == "gemini" and self._try_gemini():
                return
            if candidate == "fallback":
                self.backend = "fallback"
                self.dim = _EMBED_DIM_FALLBACK
                return

    def _try_sentence_transformers(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            self.backend = "sentence_transformers"
            self.dim = _EMBED_DIM_MINILM
            return True
        except Exception as exc:
            log.debug("[Embedder] sentence_transformers 비활성: %s", exc)
            return False

    def _try_openai(self) -> bool:
        api_key = self._get_api_key("openai_api_key")
        if not api_key:
            return False
        try:
            openai_module = importlib.import_module("openai")
            self._client = openai_module.OpenAI(api_key=api_key)
            self.backend = "openai"
            self.dim = 1536
            return True
        except Exception as exc:
            log.debug("[Embedder] openai 비활성: %s", exc)
            return False

    def _try_gemini(self) -> bool:
        api_key = self._get_api_key("gemini_api_key")
        if not api_key:
            return False
        self._client = api_key
        self.backend = "gemini"
        self.dim = 768
        return True

    def _get_api_key(self, key: str) -> str:
        try:
            from core.config_manager import ConfigManager
            return str(ConfigManager.load_settings().get(key, "") or "").strip()
        except Exception:
            return os.environ.get(key.upper(), "")

    def embed(self, text: str) -> np.ndarray:
        text = str(text or "").strip()
        if not text:
            return np.zeros(self.dim, dtype=float)
        try:
            if self.backend == "sentence_transformers" and self._model is not None:
                return np.array(self._model.encode(text), dtype=float)
            if self.backend == "openai" and self._client is not None:
                resp = self._client.embeddings.create(model="text-embedding-3-small", input=text)
                return np.array(resp.data[0].embedding, dtype=float)
            if self.backend == "gemini":
                try:
                    genai = importlib.import_module("google.generativeai")
                    genai.configure(api_key=self._client)
                    resp = genai.embed_content(model="models/embedding-001", content=text)
                    return np.array(resp["embedding"], dtype=float)
                except Exception as exc:
                    log.debug("[Embedder] gemini embed 실패: %s", exc)
            return self._fallback_embed(text)
        except Exception as exc:
            log.warning("[Embedder] 임베딩 실패, fallback 사용: %s", exc)
            return self._fallback_embed(text)

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if self.backend == "sentence_transformers" and self._model is not None:
            try:
                vectors = self._model.encode([str(text or "") for text in texts])
                return [np.array(vector, dtype=float) for vector in vectors]
            except Exception as exc:
                log.debug("[Embedder] 배치 임베딩 실패: %s", exc)
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
        if a is None or b is None or a.size == 0 or b.size == 0:
            return 0.0
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)


class CrossEncoderReranker:
    def __init__(self):
        self._model = None
        self._try_load()

    def _try_load(self):
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as exc:
            log.debug("[Embedder] reranker 비활성: %s", exc)

    def rerank(self, query: str, candidates: list[tuple[float, Any]]) -> list[tuple[float, Any]]:
        if self._model is None or not candidates:
            return candidates
        try:
            pairs = [[query, getattr(item, "goal_summary", str(item))] for _, item in candidates]
            scores = self._model.predict(pairs)
            reranked = [(float(score), item) for score, (_, item) in zip(scores, candidates)]
            return sorted(reranked, key=lambda pair: pair[0], reverse=True)
        except Exception as exc:
            log.debug("[Embedder] rerank 실패: %s", exc)
            return candidates


_embedder: Optional[Embedder] = None
_reranker: Optional[CrossEncoderReranker] = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def get_reranker() -> CrossEncoderReranker:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker


if __name__ == "__main__":
    embedder = get_embedder()
    print(embedder.backend, embedder.dim)
