"""Aggregate the HUMAN labels (coherence, grounding, metadata) into the numbers the report needs.

    python -m src.manual_scores                 # reads results/manual_*.csv, writes results/manual_scores.{json,md}
    python -m src.manual_scores --allow-partial # report on the rows filled so far (marks them as partial)

Nothing is inferred here: a blank score is "not labelled", never 0. Without --allow-partial the
script stops and lists the blank rows.

How each number is computed (GUIDE.md section 4)
* Coherence (0/1/2): the SAME 10 source positions for every strategy. A position can be covered by
  several chunks (strategy A windows overlap), so
    - per-position score = mean of the labels of the chunks covering it;
    - strategy coherence = mean of per-position scores / 2   (n = positions);
    - `row_mean` (mean over all labelled chunks) is also reported, so the effect of the
      averaging choice is visible; `min` per position is the pessimistic variant.
  Headline = per-position mean, because every position then counts once for every strategy.
* Grounding (0/1/2): one label per (test question, strategy); report count of 0/1/2 and mean /2.
* Metadata: manual 1/0 per (question, strategy, rank) row -> "complete and correct" n/N, with every
  error note listed. Filter compliance comes from the automatic traces (results/metrics.json) and
  is N/A for strategies that do not filter.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

STARTER = Path(__file__).resolve().parent.parent
VALID_012 = {"0", "1", "2"}
VALID_01 = {"0", "1"}


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing {path}. Run: python -m src.run --split all")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _label(raw: str | None) -> str:
    """Normalise a spreadsheet cell: '2', '2.0' and ' 2 ' all mean 2."""
    s = (raw or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _collect(rows: list[dict], col: str, valid: set[str], name: str, key) -> tuple[list[tuple[dict, int]], list[str], list[str]]:
    """Return (labelled rows with int score, blank row keys, invalid row descriptions)."""
    ok, blank, bad = [], [], []
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        v = _label(r.get(col))
        if v == "":
            blank.append(f"{name} line {i}: {key(r)}")
        elif v not in valid:
            bad.append(f"{name} line {i}: {key(r)} -> {r.get(col)!r} (allowed: {sorted(valid)})")
        else:
            ok.append((r, int(v)))
    return ok, blank, bad


def coherence(rows: list[dict]) -> tuple[dict, list[str], list[str]]:
    ok, blank, bad = _collect(rows, "coherence_0_1_2", VALID_012, "coherence",
                              lambda r: f"{r['position_id']} {r['strategy']} {r['chunk_id']}")
    per_pos: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r, v in ok:
        per_pos[r["strategy"]][r["position_id"]].append(v)
    # positions that a strategy covers with NO labelled chunk are not silently dropped
    all_positions = {r["position_id"] for r in rows}
    out = {}
    for s, pos in sorted(per_pos.items()):
        pos_scores = {p: mean(v) for p, v in pos.items()}
        flat = [v for vals in pos.values() for v in vals]
        out[s] = {
            "positions_labelled": len(pos_scores), "positions_total": len(all_positions),
            "chunks_labelled": len(flat),
            "mean_per_position": round(mean(pos_scores.values()), 3),
            "mean_per_position_over_2": f"{mean(pos_scores.values()):.2f}/2",
            "row_mean": round(mean(flat), 3),
            "min_per_position_mean": round(mean(min(v) for v in pos.values()), 3),
            "count_0_1_2": [flat.count(0), flat.count(1), flat.count(2)],
            "per_position": {p: round(x, 2) for p, x in sorted(pos_scores.items())},
            "reasons_for_low_scores": [f"{r['position_id']} {r['chunk_id']} = {v}: {(r.get('reason') or '').strip()}"
                                       for r, v in ok if r["strategy"] == s and v < 2],
        }
    return out, blank, bad


def grounding(rows: list[dict]) -> tuple[dict, list[str], list[str]]:
    ok, blank, bad = _collect(rows, "grounding_0_1_2", VALID_012, "grounding", lambda r: f"{r['id']} {r['strategy']}")
    by_s: dict[str, list[tuple[dict, int]]] = defaultdict(list)
    for r, v in ok:
        by_s[r["strategy"]].append((r, v))
    out = {}
    for s, items in sorted(by_s.items()):
        vals = [v for _, v in items]
        out[s] = {"n": len(vals), "count_0_1_2": [vals.count(0), vals.count(1), vals.count(2)],
                  "mean": round(mean(vals), 3), "mean_over_2": f"{mean(vals):.2f}/2",
                  "reasons_for_below_2": [f"{r['id']} = {v}: {(r.get('reason') or '').strip()}" for r, v in items if v < 2]}
    return out, blank, bad


def metadata(rows: list[dict]) -> tuple[dict, list[str], list[str]]:
    ok, blank, bad = _collect(rows, "manual_complete_and_correct_(1/0)", VALID_01, "metadata",
                              lambda r: f"{r['id']} {r['strategy']} rank{r['rank']}")
    by_s: dict[str, list[tuple[dict, int]]] = defaultdict(list)
    for r, v in ok:
        by_s[r["strategy"]].append((r, v))
    out = {}
    for s, items in sorted(by_s.items()):
        good = sum(v for _, v in items)
        out[s] = {"complete_and_correct": f"{good}/{len(items)}",
                  "errors": [f"{r['id']} rank{r['rank']} {r['chunk_id']}: {(r.get('error_note') or '').strip()}"
                             for r, v in items if v == 0]}
    return out, blank, bad


def filter_compliance(results_dir: Path) -> dict[str, str]:
    """Automatic, from the traces: questions with a filter whose top-3 stays inside the filter."""
    path = results_dir / "metrics.json"
    if not path.exists():
        return {}
    summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
    return {s: v.get("test", {}).get("filter_compliance", "N/A") for s, v in summary.items()}


def to_markdown(res: dict, partial: bool) -> str:
    strategies = sorted(set(res["coherence"]) | set(res["grounding"]) | set(res["metadata"]))
    note = "\n> PARTIAL: some rows are still blank; numbers cover labelled rows only.\n" if partial else ""
    lines = ["# Manual label scores (author-labelled; no LLM judge)", note,
             "| Strategy | Coherence /2 (positions) | Metadata complete+correct | Filter compliance (auto) | "
             "Grounding 0/1/2 | Grounding mean /2 |", "|---|---|---|---|---|---|"]
    for s in strategies:
        c, g, m = res["coherence"].get(s), res["grounding"].get(s), res["metadata"].get(s)
        coh_cell = f"{c['mean_per_position_over_2']} (n={c['positions_labelled']})" if c else "not labelled"
        met_cell = m["complete_and_correct"] if m else "not labelled"
        gro_cnt = "/".join(map(str, g["count_0_1_2"])) if g else "not labelled"
        gro_mean = g["mean_over_2"] if g else "not labelled"
        flt_cell = res["filter_compliance"].get(s, "N/A")
        lines.append(f"| {s} | {coh_cell} | {met_cell} | {flt_cell} | {gro_cnt} | {gro_mean} |")
    lines += ["", "## Coherence detail", "",
              "| Strategy | per-position mean | mean over all chunks | pessimistic (min per position) | chunks 0/1/2 |",
              "|---|---|---|---|---|"]
    for s, c in sorted(res["coherence"].items()):
        lines.append(f"| {s} | {c['mean_per_position']:.2f} | {c['row_mean']:.2f} | {c['min_per_position_mean']:.2f} | "
                     f"{'/'.join(map(str, c['count_0_1_2']))} |")
    for title, key, field in [("Coherence < 2", "coherence", "reasons_for_low_scores"),
                              ("Grounding < 2", "grounding", "reasons_for_below_2"),
                              ("Metadata errors", "metadata", "errors")]:
        lines += ["", f"## {title}", ""]
        found = False
        for s, v in sorted(res[key].items()):
            for item in v[field]:
                lines.append(f"- [{s}] {item}")
                found = True
        if not found:
            lines.append("- none")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", type=Path, default=STARTER / "results")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args(argv)

    coh, b1, x1 = coherence(_read(args.results / "manual_coherence.csv"))
    gro, b2, x2 = grounding(_read(args.results / "manual_grounding.csv"))
    met, b3, x3 = metadata(_read(args.results / "manual_metadata.csv"))
    blank, invalid = b1 + b2 + b3, x1 + x2 + x3

    if invalid:
        print("INVALID labels:\n  " + "\n  ".join(invalid))
        return 1
    if blank and not args.allow_partial:
        print(f"{len(blank)} rows not labelled yet (coherence {len(b1)}, grounding {len(b2)}, metadata {len(b3)}). "
              "Fill the score columns, or use --allow-partial.\nFirst blanks:\n  " + "\n  ".join(blank[:8]))
        return 1

    res = {"coherence": coh, "grounding": gro, "metadata": met, "filter_compliance": filter_compliance(args.results),
           "partial": bool(blank), "blank_rows": len(blank)}
    (args.results / "manual_scores.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(res, bool(blank))
    (args.results / "manual_scores.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"-> {args.results / 'manual_scores.md'} (+ .json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
