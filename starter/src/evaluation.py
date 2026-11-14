"""Score retrieved evidence per query, keep full traces, aggregate by strategy and split.

What is automatic here (and what is NOT)
* Hit@1 / Evidence Hit@3: a retrieved chunk is a HIT only if it is from the gold document, lies on a
  gold page AND contains the whole recorded `evidence_quote` (whitespace/Unicode normalised).
  Any `alt_gold` (other valid page + quote) is accepted. Hit@1 = top-1 is a hit; Hit@3 = any of top-3.
* Page-level hit is reported separately as a diagnostic ("right page, evidence incomplete" is a
  chunking failure, e.g. evidence split across chunks).
* Metadata check (source/page/section) and filter compliance are automatic PROXIES; the manual sheets
  built by `build_manual_sheets` still have to be filled by a human (coherence, grounding, metadata).
* Nothing here infers coherence or grounding scores from string matching.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

# Pages that can legitimately carry each `section` value (pages 3 and 20 hold two sections).
SECTION_PAGES = {"A": {1, 2, 3}, "B.I": set(range(3, 21)), "B.II": {20, 21, 22, 23}}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def gold_evidence(question: dict[str, Any]) -> list[tuple[int, str]]:
    """All accepted (page, quote) pairs: the main gold plus every documented alternative."""
    golds = [(question["gold_page"], question["evidence_quote"])]
    golds += [(a["gold_page"], a["evidence_quote"]) for a in question.get("alt_gold", [])]
    return golds


def is_hit(question: dict[str, Any], hit: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return (hit, page_ok, evidence_ok) for one retrieved chunk."""
    if hit.get("document_id") != question["gold_source_id"]:
        return False, False, False
    text = norm(hit["text"])
    page_ok = evidence_ok = False
    for page, quote in gold_evidence(question):
        if hit["page"] == page:
            page_ok = True
            if norm(quote) in text:
                evidence_ok = True
    return evidence_ok, page_ok, evidence_ok


def check_metadata(hit: dict[str, Any], expected_source: str, n_pages: int) -> dict[str, Any]:
    """Automatic proxy for 'metadata is present and correct' on one retrieved record."""
    meta = hit.get("metadata") or {}
    section = meta.get("section")
    checks = {
        "source_ok": hit.get("source") == expected_source,
        "page_ok": isinstance(hit.get("page"), int) and 1 <= hit["page"] <= n_pages,
        "section_ok": None if section is None else (section in SECTION_PAGES and hit["page"] in SECTION_PAGES[section]),
    }
    checks["all_ok"] = all(v for v in checks.values() if v is not None)
    return checks


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]], *, strategy: str = "",
                   filter_applied: dict | None = None, expected_source: str = "", n_pages: int = 0,
                   latency_ms: float | None = None) -> dict[str, Any]:
    """Score one query. `hits` must be the retrieved top-k in rank order (best first)."""
    top: list[dict[str, Any]] = []
    for rank, h in enumerate(hits, start=1):
        hit, page_ok, evidence_ok = is_hit(question, h)
        top.append({
            "rank": rank, "chunk_id": h["chunk_id"], "document_id": h.get("document_id"), "source": h.get("source"),
            "page": h["page"], "score": round(float(h["score"]), 5), "metadata": h.get("metadata"),
            "hit": hit, "page_ok": page_ok, "evidence_ok": evidence_ok,
            "metadata_check": check_metadata(h, expected_source, n_pages) if expected_source else None,
            "text": h["text"],
        })
    first = next((t["rank"] for t in top if t["hit"]), None)
    if first == 1:
        outcome = "hit@1"
    elif first:
        outcome = f"hit@{first}"
    elif any(t["page_ok"] for t in top):
        outcome = "page_only"  # gold page retrieved but no chunk holds the whole evidence
    else:
        outcome = "miss"

    flt = question.get("filter")
    compliant = None
    if filter_applied:  # did every returned chunk respect the filter that WAS applied?
        compliant = all((t["metadata"] or {}).get(k) == v for t in top for k, v in filter_applied.items())
    return {
        "strategy": strategy, "id": question["id"], "split": question["split"], "type": question.get("type"),
        "question": question["question"], "question_filter": flt, "filter_applied": filter_applied,
        "gold": [{"page": p, "evidence_quote": q} for p, q in gold_evidence(question)],
        "expected_answer": question.get("expected_answer"),
        "hit1": first == 1, "hit3": first is not None, "first_hit_rank": first, "outcome": outcome,
        "page_hit3": any(t["page_ok"] for t in top), "filter_compliant": compliant,
        "latency_ms": None if latency_ms is None else round(latency_ms, 2), "top3": top,
    }


def _rate(num: int, den: int) -> str:
    return f"{num}/{den}" + (f" ({num / den:.0%})" if den else "")


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by strategy and split (counts, not only percentages)."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), ts in sorted(groups.items()):
        n = len(ts)
        recs = [r for t in ts for r in t["top3"] if r["metadata_check"]]
        fq = [t for t in ts if t["filter_applied"]]
        out.setdefault(strategy, {})[split] = {
            "n_questions": n,
            "hit1": _rate(sum(t["hit1"] for t in ts), n),
            "evidence_hit3": _rate(sum(t["hit3"] for t in ts), n),
            "page_hit3": _rate(sum(t["page_hit3"] for t in ts), n),
            "metadata_auto_ok": _rate(sum(r["metadata_check"]["all_ok"] for r in recs), len(recs)),
            "filter_compliance": _rate(sum(bool(t["filter_compliant"]) for t in fq), len(fq)) if fq else "N/A (no filter applied)",
            "n_filter_questions_in_split": sum(bool(t["question_filter"]) for t in ts),
            "outcomes": {o: sum(t["outcome"] == o for t in ts) for o in sorted({t["outcome"] for t in ts})},
            "failed_ids": [t["id"] for t in ts if not t["hit3"]],
            "mean_latency_ms": round(sum(t["latency_ms"] or 0 for t in ts) / n, 2),
        }
    return out


def to_markdown(summary: dict[str, Any], traces: list[dict[str, Any]]) -> str:
    lines = ["# Retrieval results (automatic)", ""]
    for split in ("dev", "test", "all"):
        rows = [(s, v[split]) for s, v in summary.items() if split in v]
        if not rows:
            continue
        lines += [f"## {split}", "",
                  "| Strategy | Hit@1 | Evidence Hit@3 | Page hit@3 (diagnostic) | Metadata auto-OK | Filter compliance | Misses |",
                  "|---|---|---|---|---|---|---|"]
        for s, v in rows:
            lines.append(f"| {s} | {v['hit1']} | {v['evidence_hit3']} | {v['page_hit3']} | {v['metadata_auto_ok']} | "
                         f"{v['filter_compliance']} | {', '.join(v['failed_ids']) or '-'} |")
        lines.append("")
    by_q: dict[str, dict[str, dict]] = defaultdict(dict)
    for t in traces:
        by_q[t["id"]][t["strategy"]] = t
    strategies = sorted({t["strategy"] for t in traces})
    lines += ["## Per question (first hit rank; `-` = no full-evidence chunk in top-3, `p` = right page only)", "",
              "| id | split | type | filter | " + " | ".join(strategies) + " |",
              "|---|---|---|---|" + "---|" * len(strategies)]
    for qid, row in sorted(by_q.items(), key=lambda kv: (next(iter(kv[1].values()))["split"], kv[0])):
        any_t = next(iter(row.values()))
        cells = []
        for s in strategies:
            t = row.get(s)
            cells.append("" if t is None else (str(t["first_hit_rank"]) if t["hit3"] else ("p" if t["page_hit3"] else "-")))
        flt = any_t["question_filter"]
        lines.append(f"| {qid} | {any_t['split']} | {any_t['type']} | {flt['section'] if flt else ''} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Manual labelling sheets (to be filled by a human)
# --------------------------------------------------------------------------- #


def coherence_positions(pages, n: int = 10) -> list[dict[str, Any]]:
    """Fix the same n source positions for every strategy BEFORE looking at any score.

    Rule: the first n pages in ascending order; position = the middle clause/paragraph of the page,
    identified by the first <=80 chars of its text (the anchor).
    """
    positions = []
    for page in sorted(pages, key=lambda p: p.page)[:n]:
        body = [b for b in page.metadata.get("blocks", []) if b["kind"] in ("clause", "paragraph")]
        if not body:
            continue
        b = body[len(body) // 2]
        anchor = b["text"][:80].rsplit(" ", 1)[0] if len(b["text"]) > 80 else b["text"]
        positions.append({"position_id": f"pos{page.page:02d}", "page": page.page, "anchor": anchor})
    return positions


def _chunks_covering(chunks, pos, flat_page: str) -> list:
    # Match on the FULL anchor: a 40-char prefix is not unique (pos04: "Chu the chinh va (cac) Chu the phu cung ..."
    # also opens clause 1.2.1) and selected the wrong clause. Fall back to a shorter prefix only if the
    # full anchor is not found (e.g. line-wrap differences).
    full = norm(pos["anchor"])
    a = full if flat_page.find(full) >= 0 else full[:40]
    off = flat_page.find(a)
    out = []
    for c in chunks:
        if c.page != pos["page"]:
            continue
        if "char_start" in c.metadata:  # strategy A: exact window arithmetic
            if off >= 0 and c.metadata["char_start"] <= off < c.metadata["char_end"]:
                out.append(c)
        elif a in norm(c.text):
            out.append(c)
    return out


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows Vietnamese correctly
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def build_manual_sheets(traces: list[dict[str, Any]], chunks_by_strategy: dict[str, list], pages, out_dir: Path) -> dict[str, Path]:
    """Create blank-score CSV sheets for criteria 2, 3 and 4 (human labels, 0-2 scale for 2 and 4)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    page_flat = {p.page: norm(p.text) for p in pages}

    rows = []
    for pos in coherence_positions(pages):
        for strat, chunks in sorted(chunks_by_strategy.items()):
            for c in _chunks_covering(chunks, pos, page_flat[pos["page"]]):
                rows.append([pos["position_id"], pos["page"], pos["anchor"], strat, c.chunk_id, c.text, "", ""])
    paths["coherence"] = out_dir / "manual_coherence.csv"
    _write_csv(paths["coherence"], ["position_id", "page", "anchor", "strategy", "chunk_id", "chunk_text",
                                    "coherence_0_1_2", "reason"], rows)

    test = [t for t in traces if t["split"] == "test"]
    rows = []
    for t in sorted(test, key=lambda t: (t["id"], t["strategy"])):
        tops = [f"[#{r['rank']} p{r['page']} {r['chunk_id']}]\n{r['text']}" for r in t["top3"]]
        rows.append([t["id"], t["strategy"], t["question"], t["expected_answer"],
                     " || ".join(f"p{g['page']}: {g['evidence_quote']}" for g in t["gold"]),
                     *tops, "", ""])
    paths["grounding"] = out_dir / "manual_grounding.csv"
    _write_csv(paths["grounding"], ["id", "strategy", "question", "expected_answer", "gold_evidence",
                                    "top1", "top2", "top3", "grounding_0_1_2", "reason"],
               rows)

    rows = []
    for t in sorted(test, key=lambda t: (t["id"], t["strategy"])):
        for r in t["top3"]:
            m, mc = r["metadata"] or {}, r["metadata_check"] or {}
            rows.append([t["id"], t["strategy"], r["rank"], r["chunk_id"], r["source"], r["page"],
                         m.get("section", ""), m.get("heading_path", ""), mc.get("source_ok"), mc.get("page_ok"),
                         mc.get("section_ok"), "", ""])
    paths["metadata"] = out_dir / "manual_metadata.csv"
    _write_csv(paths["metadata"], ["id", "strategy", "rank", "chunk_id", "source", "page", "section",
                                   "heading_path", "auto_source_ok", "auto_page_ok", "auto_section_ok",
                                   "manual_complete_and_correct_(1/0)", "error_note"], rows)
    return paths
