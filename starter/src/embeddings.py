"""Real embedding providers (local or API) + per-strategy embedding with an on-disk cache.

Providers (choose with env vars, never a silent mock fallback):
    EMBEDDING_PROVIDER = local (default) | openrouter | openai
    EMBEDDING_MODEL    = local: model folder, default <repo>/models/multilingual-e5-base
                         (768-d, 512 tokens). API: model id.

* LocalE5Embedder      multilingual-e5 from models/, run by src/xlmr_encoder.py (plain torch, so it
                       works in the `robot` env where transformers cannot load models: torch 2.5.1).
* OpenAICompatEmbedder OpenAI-style /embeddings endpoint (OpenAI or OpenRouter).

The SAME embedder instance/config must be used for strategies A, B and C
(GUIDE.md), which `embed_strategy` makes explicit and records in its report.

Vectors are cached in data/processed/embedding_cache/<model>.jsonl keyed by the SHA-256
of the exact input text, so B and C (identical texts) are embedded once and re-runs cost
nothing. The report separates `embedded` (really computed) from `from_cache`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Protocol

from .models import Chunk

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOCAL_MODEL = str(REPO_ROOT / "models" / "multilingual-e5-base")
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "processed" / "embedding_cache"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


# --------------------------------------------------------------------------- #
# Local models
# --------------------------------------------------------------------------- #


class LocalE5Embedder:
    """multilingual-e5 from the local models/ folder, run by `xlmr_encoder` (plain torch).

    Mean pooling + L2 normalisation, prefixes "passage: " / "query: " as the model card requires.
    """

    provider = "local"

    def __init__(self, model_path: str = DEFAULT_LOCAL_MODEL, batch_size: int = 16, max_length: int = 512,
                 device: str | None = None) -> None:
        import torch

        path = Path(model_path)
        if not (path / "model.safetensors").exists():
            raise FileNotFoundError(f"no model at {path} (expected config.json, model.safetensors, tokenizer.json)")
        from .xlmr_encoder import XLMRobertaEncoder

        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.encoder = XLMRobertaEncoder(path, self.device)
        self.model_name = path.name  # "multilingual-e5-base": cache key + DB column
        self.batch_size, self.max_length = batch_size, min(max_length, self.encoder.max_positions)
        self.dimensions = self.encoder.hidden_size
        self.truncated = 0  # inputs longer than max_length tokens (their tail is NOT embedded)
        self.tokens = 0

    def _encode(self, texts: list[str]) -> list[list[float]]:
        torch = self._torch
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            ids, full = self.encoder.tokenize(texts[i:i + self.batch_size], self.max_length)
            self.truncated += sum(n > self.max_length for n in full)
            self.tokens += sum(len(x) for x in ids)
            hidden = self.encoder(ids)
            mask = self.encoder.last_mask.unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)  # mean pooling
            out.extend(torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().tolist())
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([f"query: {question}"])[0]


# --------------------------------------------------------------------------- #
# API model (OpenAI-compatible)
# --------------------------------------------------------------------------- #


class OpenAICompatEmbedder:
    """OpenAI or OpenRouter embeddings endpoint; fails loudly when key/model is missing."""

    def __init__(self, model_name: str, provider: str = "openrouter", batch_size: int = 64) -> None:
        from openai import OpenAI

        self.provider, self.model_name, self.batch_size = provider, model_name, batch_size
        if provider == "openrouter":
            key, base = os.getenv("OPENROUTER_API_KEY"), "https://openrouter.ai/api/v1"
        elif provider == "openai":
            key, base = os.getenv("OPENAI_API_KEY"), None
        else:
            raise ValueError(f"unknown API provider {provider!r}")
        if not key:
            raise RuntimeError(f"{provider.upper()}_API_KEY is empty; set it in starter/.env")
        self.client = OpenAI(api_key=key, base_url=base)
        self.tokens = 0
        self.dimensions = len(self._call(["dimension probe"])[0])

    def _call(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model_name, input=texts)
        self.tokens += getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
        return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v for i in range(0, len(texts), self.batch_size) for v in self._call(texts[i:i + self.batch_size])]

    def embed_query(self, question: str) -> list[float]:
        return self._call([question])[0]


def make_embedder() -> Embedder:
    """Build the embedder from env (.env is loaded if python-dotenv is present)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    provider = os.getenv("EMBEDDING_PROVIDER", "local").lower()
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    if provider == "local":
        return LocalE5Embedder(model or DEFAULT_LOCAL_MODEL)
    if not model:
        raise RuntimeError("EMBEDDING_MODEL must be set for API providers (e.g. openai/text-embedding-3-small)")
    return OpenAICompatEmbedder(model, provider)


# --------------------------------------------------------------------------- #
# Per-strategy embedding with cache
# --------------------------------------------------------------------------- #


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_path(model_name: str) -> Path:
    return CACHE_DIR / (re.sub(r"[^\w.-]+", "_", model_name) + ".jsonl")


def _load_cache(model_name: str) -> dict[str, list[float]]:
    path = _cache_path(model_name)
    cache: dict[str, list[float]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            cache[rec["k"]] = rec["v"]
    return cache


def _append_cache(model_name: str, new: dict[str, list[float]]) -> None:
    if not new:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _cache_path(model_name).open("a", encoding="utf-8") as f:
        for k, v in new.items():
            f.write(json.dumps({"k": k, "v": [round(x, 7) for x in v]}) + "\n")


def embed_strategy(strategy: str, chunks: list[Chunk], embedder: Embedder, use_cache: bool = True
                   ) -> tuple[list[list[float]], dict]:
    """Embed the chunks of ONE strategy; return (vectors in chunk order, report).

    The report feeds criterion 5 (resources): seconds, texts really embedded vs cached,
    tokens (when the provider exposes them) and truncation count for local models.
    """
    texts = [c.text for c in chunks]
    cache = _load_cache(embedder.model_name) if use_cache else {}
    missing = list(dict.fromkeys(t for t in texts if _key(t) not in cache))  # unique, ordered

    tok0, trunc0 = getattr(embedder, "tokens", 0), getattr(embedder, "truncated", 0)
    t0 = time.perf_counter()
    new_vecs = embedder.embed_documents(missing) if missing else []
    seconds = time.perf_counter() - t0
    fresh = {_key(t): v for t, v in zip(missing, new_vecs)}
    if use_cache:
        _append_cache(embedder.model_name, fresh)
    cache.update(fresh)

    vectors = [cache[_key(t)] for t in texts]
    if any(len(v) != embedder.dimensions for v in vectors):
        raise RuntimeError("embedding dimension mismatch")
    report = {
        "strategy": strategy,
        "model": embedder.model_name,
        "provider": getattr(embedder, "provider", "custom"),
        "dimensions": embedder.dimensions,
        "n_chunks": len(chunks),
        "embedded": len(missing),
        "from_cache": len(texts) - len(missing),
        "embed_seconds": round(seconds, 2),
        "tokens": getattr(embedder, "tokens", 0) - tok0,
        "truncated_inputs": getattr(embedder, "truncated", 0) - trunc0,
        "cost_usd": 0.0 if getattr(embedder, "provider", "") == "local" else None,  # API cost: fill from billing
    }
    return vectors, report
