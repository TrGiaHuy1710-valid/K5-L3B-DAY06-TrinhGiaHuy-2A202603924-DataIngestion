"""Run the benchmark: same questions, same query vectors, strategies A / B / C -> traces + metrics.

    python -m src.run                 # dev split only (default: do not look at test while tuning)
    python -m src.run --split all     # final run: dev + test, also writes the manual labelling sheets
    python -m src.run --split test --update-log

Prerequisite: `python -m src.indexing` (chunks + embeddings are already in pgvector).

Protocol (GUIDE.md / BENCHMARK.md)
* one embedder, one vector store, cosine, top-3 for every strategy;
* A and B never filter; C applies the question's `filter` ONLY when it has one (otherwise unfiltered);
* the query text is the question only: no gold page / answer / source is ever put in query or filter;
* every query's full top-3 (text, score, metadata, hit flags) is saved in results/traces_<S>.jsonl.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .chunking import DEFAULT_MAX_SIZE, DEFAULT_OVERLAP, DEFAULT_SIZE, build_chunks
    from .embeddings import make_embedder
    from .evaluation import build_manual_sheets, evaluate_query, summarize, to_markdown
    from .ingestion import load_processed
    from .store import PgVectorStore, database_url_from_env
except ImportError:  # direct script run
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.chunking import DEFAULT_MAX_SIZE, DEFAULT_OVERLAP, DEFAULT_SIZE, build_chunks
    from src.embeddings import make_embedder
    from src.evaluation import build_manual_sheets, evaluate_query, summarize, to_markdown
    from src.ingestion import load_processed
    from src.store import PgVectorStore, database_url_from_env

STARTER = Path(__file__).resolve().parent.parent
DOC_ID = "vcb-credit-card-terms-2026"
MIN_CONTENT_PAGES = 30  # RUBRIC.md / GUIDE.md


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--strategies", default="ABC")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--bench", type=Path, default=STARTER.parent / "data" / "benchmark_questions.json")
    ap.add_argument("--out", type=Path, default=STARTER / "results")
    ap.add_argument("--update-log", action="store_true", help="fill artifacts/experiment_log.csv numeric columns")
    args = ap.parse_args(argv)

    bench = json.loads(args.bench.read_text(encoding="utf-8"))
    questions = [q for q in bench["questions"] if args.split == "all" or q["split"] == args.split]
    expected_source = bench["meta"]["source"]
    pages = load_processed(STARTER / "data" / "processed" / f"{DOC_ID}.pages.json")
    n_pages = len(pages)
    strategies = args.strategies.upper()

    if n_pages < MIN_CONTENT_PAGES:
        print(f"WARNING: corpus has {n_pages} content pages < {MIN_CONTENT_PAGES} required by the rubric. "
              "Add more documents before the final submission.")
    if args.split in ("test", "all"):
        print("NOTE: test split is being evaluated. Do not change strategies based on these numbers; "
              "if you do, record it in the report and build a new test set.")

    embedder = make_embedder()
    store = PgVectorStore(database_url_from_env(), embedder.dimensions, embedder.model_name)

    # The evaluated index must be exactly what chunking produces now (no stale/missing rows).
    params = {"A": {"size": DEFAULT_SIZE, "overlap": DEFAULT_OVERLAP},
              "B": {"max_size": DEFAULT_MAX_SIZE}, "C": {"max_size": DEFAULT_MAX_SIZE}}
    chunks_by_strategy = {s: build_chunks(s, pages, **params[s]) for s in strategies}
    for s, chunks in chunks_by_strategy.items():
        if {c.chunk_id for c in chunks} != store.chunk_ids(s):
            print(f"ERROR: pgvector index for strategy {s} differs from current chunks. Run: python -m src.indexing")
            return 1

    # Embed every question once -> identical query vectors for all strategies.
    t0 = time.perf_counter()
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    print(f"{len(questions)} questions ({args.split}) embedded in {time.perf_counter() - t0:.2f}s "
          f"with {embedder.model_name} ({embedder.dimensions}d)")

    args.out.mkdir(parents=True, exist_ok=True)
    traces: list[dict] = []
    for s in strategies:
        for q in questions:
            flt = q.get("filter") if s == "C" else None  # the ONLY place a filter is used
            t = time.perf_counter()
            hits = store.search(s, qvecs[q["id"]], args.top_k, flt)
            ms = (time.perf_counter() - t) * 1000
            traces.append(evaluate_query(q, hits, strategy=s, filter_applied=flt, expected_source=expected_source,
                                         n_pages=n_pages, latency_ms=ms))
    for s in strategies:
        path = args.out / f"traces_{s}.jsonl"
        path.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in traces if t["strategy"] == s) + "\n",
                        encoding="utf-8")

    summary = summarize(traces)
    run_info = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "split": args.split,
        "model": embedder.model_name, "dimensions": embedder.dimensions, "device": getattr(embedder, "device", ""),
        "top_k": args.top_k, "metric": "cosine (exact scan)", "n_pages": n_pages, "chunk_params": params,
        "python": platform.python_version(), "n_questions": len(questions), "db_counts": store.count(),
    }
    (args.out / "metrics.json").write_text(json.dumps({"run": run_info, "summary": summary}, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (args.out / "metrics.md").write_text(to_markdown(summary, traces), encoding="utf-8")

    for split in ("dev", "test"):
        rows = [(s, summary[s][split]) for s in strategies if split in summary.get(s, {})]
        if rows:
            print(f"\n[{split}]  strategy | Hit@1 | Evidence Hit@3 | page-hit@3 | filter compliance | misses")
            for s, v in rows:
                print(f"  {s}  {v['hit1']:>10}  {v['evidence_hit3']:>10}  {v['page_hit3']:>10}  "
                      f"{v['filter_compliance']}  {v['failed_ids']}")

    if args.split in ("test", "all"):
        sheets = build_manual_sheets(traces, chunks_by_strategy, pages, args.out)
        print("\nmanual sheets to fill:", ", ".join(p.name for p in sheets.values()))

    if args.update_log:
        _update_experiment_log(summary, run_info)
    print(f"\ntraces -> {args.out}/traces_<A|B|C>.jsonl | metrics -> metrics.json, metrics.md")
    return 0


def _count(rate: str) -> str:
    return rate.split(" ")[0]


def _update_experiment_log(summary: dict, run_info: dict) -> None:
    """Fill the numeric/config columns of artifacts/experiment_log.csv; leave hypothesis/notes to the human."""
    path = STARTER.parent / "artifacts" / "experiment_log.csv"
    cfg = {
        "A": ("fixed size", DEFAULT_SIZE, DEFAULT_OVERLAP, "document_id,source,page", "none"),
        "B": ("structure (clauses under headings)", f"<= {DEFAULT_MAX_SIZE}", 0, "document_id,source,page", "none"),
        "C": ("structure (same chunks as B)", f"<= {DEFAULT_MAX_SIZE}", 0,
              "B + section,heading_path,article,clauses", "section (only when question has a filter)"),
    }
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for r in rows:
        s = r["strategy"]
        if s not in summary:
            continue
        r.update(dict(zip(["chunking", "chunk_size", "overlap", "metadata", "filter"], cfg[s])))
        r["vectorizer"] = f"{run_info['model']} ({run_info['dimensions']}d, dense, cosine)"
        for split in ("dev", "test"):
            if split in summary[s]:
                r[f"{split}_hit1"] = _count(summary[s][split]["hit1"])
                r[f"{split}_hit3"] = _count(summary[s][split]["evidence_hit3"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"updated {path}")


if __name__ == "__main__":
    sys.exit(main())
