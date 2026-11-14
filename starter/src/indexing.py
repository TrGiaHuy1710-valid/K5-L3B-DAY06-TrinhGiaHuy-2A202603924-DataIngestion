"""Build the three indexes: chunks (A/B/C) -> embeddings -> pgvector. Idempotent.

Run from starter/:  python -m src.indexing [--strategies ABC] [--skip-ingest]
Writes results/ingest_log.json (chunk counts, embed time, tokens, truncation, DB counts).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .chunking import DEFAULT_MAX_SIZE, DEFAULT_OVERLAP, DEFAULT_SIZE, build_chunks, chunk_stats
    from .embeddings import embed_strategy, make_embedder
    from .ingestion import ingest_pdf, load_processed
    from .store import PgVectorStore, database_url_from_env
except ImportError:  # direct script run
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.chunking import DEFAULT_MAX_SIZE, DEFAULT_OVERLAP, DEFAULT_SIZE, build_chunks, chunk_stats
    from src.embeddings import embed_strategy, make_embedder
    from src.ingestion import ingest_pdf, load_processed
    from src.store import PgVectorStore, database_url_from_env

STARTER = Path(__file__).resolve().parent.parent
DOC_ID = "vcb-credit-card-terms-2026"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strategies", default="ABC")
    ap.add_argument("--skip-ingest", action="store_true", help="reuse data/processed/*.pages.json")
    ap.add_argument("--no-cache", action="store_true", help="re-embed everything (ignore the embedding cache)")
    args = ap.parse_args(argv)

    t_all = time.perf_counter()
    out = STARTER / "data" / "processed"
    t0 = time.perf_counter()
    if not args.skip_ingest:
        r = ingest_pdf(STARTER.parent / "data" / "20260415_ DieuLeTheVCB.pdf", DOC_ID,
                       "data/20260415_ DieuLeTheVCB.pdf", out)
        if r["problems"]:
            print("ingestion problems:", r["problems"])
            return 1
    pages = load_processed(out / f"{DOC_ID}.pages.json")
    parse_seconds = round(time.perf_counter() - t0, 2)

    embedder = make_embedder()  # one embedder instance shared by every strategy
    store = PgVectorStore(database_url_from_env(), embedder.dimensions, embedder.model_name)
    store.create_schema()
    print(f"embedder: {embedder.model_name} ({embedder.dimensions}d) | parse+clean {parse_seconds}s")

    log = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": embedder.model_name,
           "dimensions": embedder.dimensions, "parse_seconds": parse_seconds,
           "params": {"A": {"size": DEFAULT_SIZE, "overlap": DEFAULT_OVERLAP},
                      "B": {"max_size": DEFAULT_MAX_SIZE}, "C": {"max_size": DEFAULT_MAX_SIZE}},
           "strategies": {}}
    for strat in args.strategies.upper():
        params = log["params"][strat]
        t = time.perf_counter()
        chunks = build_chunks(strat, pages, **params)
        chunk_seconds = round(time.perf_counter() - t, 3)
        vectors, rep = embed_strategy(strat, chunks, embedder, use_cache=not args.no_cache)
        t = time.perf_counter()
        db = store.upsert(strat, chunks, vectors)
        rep.update({"chunk_seconds": chunk_seconds, "store_seconds": round(time.perf_counter() - t, 2),
                    "chunk_stats": chunk_stats(chunks), "db": db})
        log["strategies"][strat] = rep
        print(f"[{strat}] chunks={rep['n_chunks']} embedded={rep['embedded']} cached={rep['from_cache']} "
              f"embed={rep['embed_seconds']}s truncated={rep['truncated_inputs']} db={db}")
    log["db_counts"] = store.count()
    log["total_seconds"] = round(time.perf_counter() - t_all, 2)
    (STARTER / "results").mkdir(exist_ok=True)
    (STARTER / "results" / "ingest_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("db counts:", log["db_counts"], "| log -> results/ingest_log.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
