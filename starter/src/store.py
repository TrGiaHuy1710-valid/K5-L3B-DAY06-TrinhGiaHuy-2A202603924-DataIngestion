"""PostgreSQL + pgvector store: one table, one row per (strategy, chunk).

    chunks(strategy, chunk_id, document_id, source, page, text, content_hash,
           embedding_model, embedding vector(N), metadata jsonb, created_at)
    PRIMARY KEY (strategy, chunk_id)

Design notes
* Strategies A/B/C live in the same table, separated by `strategy`, so all three share the
  same database, model dimension and cosine metric.
* Search is EXACT (sequential scan, `embedding <=> query`). With a few hundred rows this is
  fast and avoids the HNSW "filter after ANN" recall trap. `create_index()` is optional.
* Cosine distance `<=>`; `score = 1 - distance` (higher = more similar).
* Filters are limited to a whitelist and always passed as bind parameters. Columns
  (`document_id`, `source`, `page`) are compared directly, other keys via `metadata @> jsonb`.
* `upsert` is idempotent: stable ids, ON CONFLICT DO UPDATE, and obsolete chunks of that
  strategy (ids not in the new batch) are deleted, so re-running never duplicates.
* The store never falls back to anything else: connection or dimension problems raise.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
COLUMN_FILTERS = {"document_id", "source", "page"}
METADATA_FILTERS = {"section", "article"}
ALLOWED_STRATEGIES = {"A", "B", "C"}


def database_url_from_env() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL missing: copy starter/.env.example to starter/.env")
    return url


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, embedding_model: str = "") -> None:
        if not database_url:
            raise ValueError("database_url is required")
        if dimensions <= 0 or dimensions > 2000:  # pgvector hnsw/ivfflat limit is 2000 for `vector`
            raise ValueError(f"unsupported dimensions: {dimensions}")
        self.database_url, self.dimensions, self.embedding_model = database_url, dimensions, embedding_model

    # ------------------------------------------------------------------ #
    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        """Create the extension/table if missing and verify the vector dimension matches."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy        text        NOT NULL,
                    chunk_id        text        NOT NULL,
                    document_id     text        NOT NULL,
                    source          text        NOT NULL,
                    page            integer     NOT NULL,
                    text            text        NOT NULL,
                    content_hash    text        NOT NULL,
                    embedding_model text        NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    metadata        jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at      timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id),
                    CHECK (strategy IN ('A','B','C'))
                )""")
            cur.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_meta_gin ON {TABLE} USING gin (metadata)")
            cur.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_strategy_page ON {TABLE} (strategy, page)")
            cur.execute("""SELECT a.atttypmod FROM pg_attribute a
                           WHERE a.attrelid = %s::regclass AND a.attname = 'embedding'""", (TABLE,))
            existing = cur.fetchone()[0]
            if existing != self.dimensions:
                raise RuntimeError(
                    f"table '{TABLE}' has vector({existing}) but the embedder produces {self.dimensions}. "
                    "Use another table/database or drop the table explicitly; nothing was changed.")

    def create_index(self) -> None:
        """Optional HNSW (approximate) cosine index. Not used by default: search is exact."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_hnsw ON {TABLE} "
                        "USING hnsw (embedding vector_cosine_ops)")

    # ------------------------------------------------------------------ #
    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Write chunks idempotently and delete obsolete ones of the same strategy."""
        if strategy not in ALLOWED_STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(ALLOWED_STRATEGIES)}")
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if not chunks:
            raise ValueError("refusing to upsert an empty batch (would delete the whole strategy)")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in batch")
        for c, v in zip(chunks, vectors):
            if len(v) != self.dimensions:
                raise ValueError(f"{c.chunk_id}: vector has {len(v)} dims, expected {self.dimensions}")

        rows = [
            (strategy, c.chunk_id, c.document_id, c.source, c.page, c.text,
             hashlib.sha256(c.text.encode("utf-8")).hexdigest(), self.embedding_model, _vec(v),
             json.dumps(c.metadata, ensure_ascii=False))
            for c, v in zip(chunks, vectors)
        ]
        with self._connect() as conn, conn.cursor() as cur:  # one transaction
            cur.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,))
            before = cur.fetchone()[0]
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, text, content_hash,
                                     embedding_model, embedding, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s::jsonb)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                    text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                    embedding_model = EXCLUDED.embedding_model, embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata, created_at = now()""", rows)
            cur.execute(f"DELETE FROM {TABLE} WHERE strategy = %s AND NOT (chunk_id = ANY(%s))", (strategy, ids))
            removed = cur.rowcount
            cur.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,))
            after = cur.fetchone()[0]
        return {"before": before, "written": len(rows), "removed_obsolete": removed, "after": after}

    # ------------------------------------------------------------------ #
    @staticmethod
    def _where(strategy: str, filters: dict[str, Any] | None) -> tuple[str, list[Any]]:
        if strategy not in ALLOWED_STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(ALLOWED_STRATEGIES)}")
        clauses, params = ["strategy = %s"], [strategy]
        meta: dict[str, Any] = {}
        for key, value in (filters or {}).items():
            if key in COLUMN_FILTERS:
                clauses.append(f"{key} = %s")
                params.append(value)
            elif key in METADATA_FILTERS:
                meta[key] = value
            else:
                raise ValueError(f"filter key {key!r} not allowed; use {sorted(COLUMN_FILTERS | METADATA_FILTERS)}")
        if meta:
            clauses.append("metadata @> %s::jsonb")
            params.append(json.dumps(meta, ensure_ascii=False))
        return " AND ".join(clauses), params

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exact cosine top-k inside one strategy; metadata filter applied in SQL."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query has {len(query_vector)} dims, expected {self.dimensions}")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        where, params = self._where(strategy, filters)
        self._check_single_model(strategy)
        q = _vec(query_vector)
        sql = f"""
            SELECT chunk_id, text, 1 - (embedding <=> %s::vector) AS score, strategy, document_id, source,
                   page, metadata
            FROM {TABLE} WHERE {where}
            ORDER BY embedding <=> %s::vector, chunk_id
            LIMIT %s"""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, [q, *params, q, top_k])
            return [
                {"chunk_id": r[0], "text": r[1], "score": float(r[2]), "strategy": r[3], "document_id": r[4],
                 "source": r[5], "page": r[6], "metadata": r[7], "rank": i + 1}
                for i, r in enumerate(cur.fetchall())
            ]

    # ------------------------------------------------------------------ #
    def _check_single_model(self, strategy: str) -> None:
        """Refuse to rank vectors that were produced by a different model than the query's."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT embedding_model FROM {TABLE} WHERE strategy = %s", (strategy,))
            models = [r[0] for r in cur.fetchall()]
        if len(models) > 1 or (self.embedding_model and models and models != [self.embedding_model]):
            raise RuntimeError(f"strategy {strategy}: stored embedding models {models} != query model "
                               f"{self.embedding_model!r}; re-run `python -m src.indexing`")

    def count(self, strategy: str | None = None) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT strategy, count(*) FROM {TABLE} GROUP BY strategy ORDER BY strategy")
            counts = {s: n for s, n in cur.fetchall()}
        return {strategy: counts.get(strategy, 0)} if strategy else counts

    def delete_strategy(self, strategy: str) -> int:
        """Explicit, scoped delete (never called implicitly)."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE} WHERE strategy = %s", (strategy,))
            return cur.rowcount
