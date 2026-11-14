"""Three chunking strategies for the Day 06 benchmark.

    A  fixed_size(page, size, overlap)   fixed character windows, base metadata only
    B  by_paragraph(page, max_size)      structure-aware (clauses under their headings),
                                         base metadata only, no filtering
    C  by_paragraph(..., with_metadata)  EXACT same chunks/ids/text as B, plus filterable
                                         metadata (section, heading_path, article, clauses)

A -> B changes only the chunking; B -> C changes only metadata + filtering, so the two
differences can be analysed separately (see GUIDE.md section 3).

Rules shared by every strategy:
  * a chunk never crosses a PDF page, so `page` is exact (gold is judged per page);
  * text is never rewritten, only whitespace is collapsed;
  * chunk ids are deterministic -> re-ingesting the same data does not duplicate rows.

C only filters when the question carries a filter: use `matches_filter` / `to_store_filter`.

CLI (from starter/):  python -m src.chunking [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

try:
    from .models import Block, Chunk, DocumentPage
except ImportError:  # direct script run
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.models import Block, Chunk, DocumentPage  # noqa: F401

# Defaults follow the GUIDE example for A; B/C group whole clauses up to MAX_SIZE.
DEFAULT_SIZE, DEFAULT_OVERLAP, DEFAULT_MAX_SIZE = 500, 50, 1000


def _flat(text: str) -> str:
    """Collapse every whitespace run (incl. hard line breaks) into one space."""
    return " ".join(text.split())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _cid(page: DocumentPage, tag: str, i: int) -> str:
    return f"{page.document_id}|{tag}|p{page.page:02d}|{i:03d}"


# --------------------------------------------------------------------------- #
# Strategy A - fixed size
# --------------------------------------------------------------------------- #


def fixed_size(page: DocumentPage, size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    """Overlapping character windows over the whitespace-flattened page text.

    Deliberately naive (may cut mid-sentence / mid-word): it is the baseline.
    Metadata: document_id, source, page (+ char offsets for traceability).
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("need size > 0 and 0 <= overlap < size")
    text = _flat(page.text)
    step, chunks, start = size - overlap, [], 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(Chunk(
            _cid(page, "A", len(chunks)), page.document_id, page.source, page.page, text[start:end],
            {"strategy": "A", "char_start": start, "char_end": end},
        ))
        if end >= len(text):
            break
        start += step
    return chunks


# --------------------------------------------------------------------------- #
# Strategy B / C - structure aware
# --------------------------------------------------------------------------- #

_SENT = re.compile(r"(?<=[.;:!?])\s+")


def _split_oversized(text: str, max_size: int) -> list[str]:
    """Split one very long clause at sentence ends, then (last resort) at spaces."""
    pieces, cur = [], ""
    for sent in _SENT.split(text):
        while len(sent) > max_size:  # a single sentence longer than the limit
            cut = sent.rfind(" ", 0, max_size) or max_size
            head, sent = sent[:cut], sent[cut:].lstrip()
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(head)
        if cur and len(cur) + 1 + len(sent) > max_size:
            pieces.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        pieces.append(cur)
    return pieces


def _filter_section(section: str) -> str:
    """Only real filter values survive: 'A', 'B.I', 'B.II'. The bare part heading 'B' is
    not a valid scope (it sits before B.I), so it is treated as 'no section yet'."""
    return "" if section == "B" else section


def _units(page: DocumentPage, max_size: int) -> list[dict]:
    """Blocks of the page as text units; oversized clauses become several units."""
    units: list[dict] = []
    for b in page.metadata.get("blocks", []):
        is_head = b["kind"] in ("heading", "title")
        text = f"{b['label']} {b['text']}".strip() if b["kind"] in ("heading", "clause") else b["text"]
        pieces = [text] if is_head or len(text) <= max_size else _split_oversized(text, max_size)
        for k, piece in enumerate(pieces):
            units.append({"text": piece, "head": is_head, "section": _filter_section(b["section"]), "path": b["heading_path"],
                          "label": b["label"], "level": b.get("level", 0), "piece": k if len(pieces) > 1 else None})
    return units


def _group(units: list[dict], max_size: int) -> list[list[dict]]:
    """Greedy grouping: never cross a section or an article heading, never split a heading from its body."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    size = 0

    def section_of(g: list[dict]) -> str:
        return next((u["section"] for u in g if u["section"]), "")

    for u in units:
        new_section = bool(cur) and u["section"] and section_of(cur) and u["section"] != section_of(cur)
        # a new article heading ("1.5 ...", level <= 3) starts a new chunk once the current one has body text
        new_article = u["head"] and 0 < u["level"] <= 3 and any(not x["head"] for x in cur)
        if cur and (new_section or new_article or size + 1 + len(u["text"]) > max_size):
            trailing: list[dict] = []  # a heading must travel with the text it introduces
            while cur and cur[-1]["head"]:
                trailing.insert(0, cur.pop())
            if cur:
                groups.append(cur)
            else:  # only headings: nothing to separate them from
                cur, trailing = trailing, []
                groups.append(cur)
            cur = trailing
            size = sum(len(x["text"]) + 1 for x in cur)
        cur.append(u)
        size += len(u["text"]) + 1
    if cur:
        groups.append(cur)
    return groups


def _article(path: str) -> str:
    """Level-3 heading of the breadcrumb, e.g. '1.3 Hạn mức thẻ ...' (or '1. Giải thích từ ngữ')."""
    for part in path.split(" > "):
        if re.match(r"^\d+\.(\d+\.?)?\s", part):
            return part
    return ""


def by_paragraph(page: DocumentPage, max_size: int = DEFAULT_MAX_SIZE, with_metadata: bool = False) -> list[Chunk]:
    """Group clauses (kept whole when possible) under their headings, up to `max_size`.

    with_metadata=False -> strategy B (base metadata, no filter fields)
    with_metadata=True  -> strategy C (identical chunks + section/heading_path/article/clauses)
    """
    tag = "C" if with_metadata else "B"
    chunks: list[Chunk] = []
    for group in _group(_units(page, max_size), max_size):
        body = [u for u in group if not u["head"]] or group
        meta = {"strategy": tag, "n_units": len(group)}
        if with_metadata:
            labels = [u["label"] for u in body if u["label"]]
            meta.update({
                "section": next((u["section"] for u in group if u["section"]), ""),
                "heading_path": body[0]["path"],
                "article": _article(body[0]["path"]),
                "clauses": [labels[0], labels[-1]] if labels else [],
                "split_clause": any(u["piece"] is not None for u in group),
            })
        chunks.append(Chunk(_cid(page, tag, len(chunks)), page.document_id, page.source, page.page,
                            "\n".join(u["text"] for u in group), meta))
    return chunks


def build_chunks(strategy: str, pages: list[DocumentPage], **params) -> list[Chunk]:
    strategy = strategy.upper()
    if strategy == "A":
        return [c for p in pages for c in fixed_size(p, **params)]
    if strategy in ("B", "C"):
        return [c for p in pages for c in by_paragraph(p, with_metadata=strategy == "C", **params)]
    raise ValueError(f"unknown strategy {strategy!r}")


# --------------------------------------------------------------------------- #
# Filtering (strategy C) and measurements
# --------------------------------------------------------------------------- #


def matches_filter(chunk: Chunk, flt: dict | None) -> bool:
    """True when the chunk satisfies every key of the question's filter (None = no filter)."""
    return all(chunk.metadata.get(k) == v for k, v in (flt or {}).items())


def to_store_filter(flt: dict | None) -> dict | None:
    """Metadata filter in the shape most stores expect, e.g. pgvector: metadata @> %s::jsonb."""
    return dict(flt) if flt else None


def chunk_stats(chunks: list[Chunk]) -> dict:
    lens = [len(c.text) for c in chunks]
    return {
        "n_chunks": len(chunks), "total_chars": sum(lens), "min": min(lens), "max": max(lens),
        "mean": round(statistics.mean(lens), 1), "median": statistics.median(lens),
        "tiny_lt_100": sum(l < 100 for l in lens),
    }


def evidence_coverage(chunks: list[Chunk], questions: list[dict], use_filter: bool) -> dict:
    """Retrieval-free upper bound: does ONE chunk on a gold page hold the whole evidence?

    A miss here means evidence is split across chunks, so even a perfect retriever
    cannot get a full hit. `use_filter` restricts candidates to the question's filter (C).
    """
    covered, split_ids = 0, []
    for q in questions:
        golds = [(q["gold_page"], q["evidence_quote"])] + [(a["gold_page"], a["evidence_quote"]) for a in q.get("alt_gold", [])]
        flt = q.get("filter") if use_filter else None
        ok = any(
            c.page == pg and _norm(ev) in _norm(c.text) and matches_filter(c, flt)
            for pg, ev in golds for c in chunks
        )
        covered += ok
        if not ok:
            split_ids.append(q["id"])
    return {"covered": f"{covered}/{len(questions)}", "evidence_split": split_ids}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        from .ingestion import load_processed
    except ImportError:
        from src.ingestion import load_processed

    starter = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", type=Path, default=starter / "data" / "processed" / "vcb-credit-card-terms-2026.pages.json")
    ap.add_argument("--out", type=Path, default=starter / "data" / "processed")
    ap.add_argument("--bench", type=Path, default=starter.parent / "data" / "benchmark_questions.json")
    ap.add_argument("--size", type=int, default=DEFAULT_SIZE)
    ap.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    ap.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE)
    ap.add_argument("--check", action="store_true", help="evidence coverage against the benchmark")
    args = ap.parse_args(argv)

    pages = load_processed(args.pages)
    questions = json.loads(args.bench.read_text(encoding="utf-8"))["questions"] if args.check else []
    for strat in "ABC":
        params = {"size": args.size, "overlap": args.overlap} if strat == "A" else {"max_size": args.max_size}
        chunks = build_chunks(strat, pages, **params)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), "duplicate chunk ids"
        assert all(c.page and c.text.strip() for c in chunks)
        path = args.out / f"chunks_{strat}.jsonl"
        path.write_text("\n".join(json.dumps(c.__dict__, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
        print(f"[{strat}] {params} -> {path.name}\n    {chunk_stats(chunks)}")
        if args.check:
            print(f"    evidence in a single chunk: {evidence_coverage(chunks, questions, use_filter=strat == 'C')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
