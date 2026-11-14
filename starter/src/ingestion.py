"""Read a PDF, clean it and save structured Markdown for the chunking experiments.

Pipeline (each step is a plain function so it can be tested / swapped):

    load_pdf          -> raw DocumentPage per physical page (+ empty/table flags)
    strip_boilerplate -> drop repeated running headers and bare page numbers
    parse_blocks      -> unwrap hard-wrapped lines, detect headings / clauses,
                         track section + heading breadcrumb
    to_markdown       -> Markdown with `<!-- page: N -->` markers (page fidelity)
    verify_preservation -> prove no text was lost or invented while cleaning
    ingest_pdf        -> orchestrates everything and writes the outputs

Outputs (under --out, default data/processed):
    <document_id>.md          clean Markdown, one page marker per PDF page
    <document_id>.pages.json  per-page text + structural blocks + metadata

Design rules:
  * Never merge text across pages: gold evidence is judged per PDF page.
    A paragraph that continues on the next page is flagged `continued`.
  * Never rewrite wording (typos in the source stay), only whitespace/Unicode.

Run:  python -m src.ingestion   (from starter/)   or   python starter/src/ingestion.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:  # `python -m src.ingestion` (package) ...
    from .models import Block, DocumentPage
except ImportError:  # ... or `python starter/src/ingestion.py` (direct script)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.models import Block, DocumentPage

PARSER_VERSION = "1.0"

# --------------------------------------------------------------------------- #
# 1. Loading
# --------------------------------------------------------------------------- #


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract each physical page with its 1-based number and source.

    Pages without a text layer are flagged (`metadata["empty"]`); OCR is a
    separate step and is deliberately not done here.
    """
    import fitz  # PyMuPDF; imported lazily so the module imports without it

    pages: list[DocumentPage] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("text", sort=True)
            pages.append(
                DocumentPage(
                    document_id=document_id,
                    source=source,
                    page=i,
                    text=raw,
                    metadata={
                        "empty": len(raw.strip()) == 0,
                        "n_images": len(page.get_images()),
                        "raw_chars": len(raw),
                    },
                )
            )
    return pages


# --------------------------------------------------------------------------- #
# 2. Normalisation and boilerplate removal
# --------------------------------------------------------------------------- #

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_SPACES = re.compile(r"[ \t     ]+")


def normalize_text(text: str) -> str:
    """Unicode NFC + whitespace clean-up; keeps line breaks (structure) intact."""
    text = unicodedata.normalize("NFC", text)
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.split("\n")]
    return "\n".join(lines)


def _shape(line: str) -> str:
    """Digits -> '#', so 'MẪU 01.X' and page numbers match across pages."""
    return re.sub(r"\d+", "#", line.strip())


def strip_boilerplate(pages: list[DocumentPage], edge: int = 4, min_ratio: float = 0.6) -> list[DocumentPage]:
    """Remove running headers/footers and bare page numbers.

    A line is boilerplate if, within the first/last `edge` lines of a page, its
    digit-normalised shape recurs on >= `min_ratio` of the pages. A line that is
    only the page number is also dropped. Removed lines are logged in metadata.
    """
    n = max(len(pages), 1)
    norm_lines = [[ln for ln in normalize_text(p.text).split("\n")] for p in pages]
    counter: Counter[str] = Counter()
    for lines in norm_lines:
        non_empty = [ln for ln in lines if ln]
        edges = set(map(_shape, non_empty[:edge] + non_empty[-edge:]))
        counter.update(edges)
    repeated = {s for s, c in counter.items() if c / n >= min_ratio and len(pages) >= 3}

    cleaned: list[DocumentPage] = []
    for page, lines in zip(pages, norm_lines):
        non_empty_idx = [i for i, ln in enumerate(lines) if ln]
        edge_idx = set(non_empty_idx[:edge] + non_empty_idx[-edge:])
        kept, removed = [], []
        for i, ln in enumerate(lines):
            is_page_no = ln == str(page.page)
            if ln and i in edge_idx and (_shape(ln) in repeated or is_page_no):
                removed.append(ln)
            else:
                kept.append(ln)
        meta = dict(page.metadata)
        meta["removed_boilerplate"] = removed
        cleaned.append(DocumentPage(page.document_id, page.source, page.page, "\n".join(kept), meta))
    return cleaned


# --------------------------------------------------------------------------- #
# 3. Structure detection
# --------------------------------------------------------------------------- #

_ROMAN_PAREN = r"(?:i{1,3}|iv|vi{0,3}|ix|x{1,2}i{0,3})"
# A line that is only a list marker; its text sits on the next line in this PDF.
_LONE_MARKER = re.compile(rf"^(?:\d+(?:\.\d+)*\.?|[A-Z]\.|[IVX]+\.|[a-zđ][.)]|\({_ROMAN_PAREN}\))$")
_PART = re.compile(r"^([A-H])\.\s+(\S.*)$")  # I, V, X are Roman numerals, not parts
_ROMAN = re.compile(r"^([IVX]+)\.\s+(\S.*)$")
# numbered: "1.2.3 text" or "1. text" (a dot is required, so "30 triệu" never matches)
_NUM = re.compile(r"^(\d+(?:\.\d+)+|\d+\.)\.?\s+(\S.*)$")
_LETTER = re.compile(r"^([a-zđ][.)])\s+(\S.*)$")
_ROMAN_ITEM = re.compile(rf"^(\({_ROMAN_PAREN}\))\s*(\S.*)$")
_TERMINAL = tuple(".;:!?…")

MAX_HEADING_CHARS = 100
MAX_HEADING_LINE_WITH_MARKER = 95   # next line starts a new block -> heading may be fairly long
MAX_HEADING_LINE_BEFORE_TEXT = 80  # next line is plain text -> only short lines are headings
MAX_TOP_NUMBER_HEADING_CHARS = 40  # "1. Giải thích từ ngữ" yes; a short clause "1. ..." no


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _join_lone_markers(lines: list[str]) -> list[str]:
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln and _LONE_MARKER.match(ln) and i + 1 < len(lines) and lines[i + 1]:
            out.append(f"{ln} {lines[i + 1]}")
            i += 2
        else:
            out.append(ln)
            i += 1
    return out


def _starts_block(line: str) -> bool:
    return bool(_PART.match(line) or _ROMAN.match(line) or _NUM.match(line)
                or _LETTER.match(line) or _ROMAN_ITEM.match(line))


def _looks_wrapped(line: str, next_line: str) -> bool:
    """True if `line` is probably the first physical line of a longer clause.

    The PDF hard-wraps at ~105 chars, so a numbered line that is long, or whose
    next line is a lowercase continuation, is body text, not a heading.
    """
    if not next_line or _starts_block(next_line):
        return len(line) > MAX_HEADING_LINE_WITH_MARKER
    return len(line) > MAX_HEADING_LINE_BEFORE_TEXT or next_line[0].islower()


def _classify(line: str, next_line: str = "") -> tuple[str, str, str, int]:
    """Return (kind, label, text, level) for a line that may start a new block.

    kind: heading | clause | continuation. `next_line` disambiguates a short
    numbered heading ("1.3 Hạn mức thẻ") from the first, still-wrapped line of
    a numbered clause ("1.2.3 Chủ thẻ chính chịu trách nhiệm ... và (các)").
    """
    m = _PART.match(line)
    if m and _is_upper(m.group(2)):
        return "heading", m.group(1) + ".", m.group(2), 1
    m = _ROMAN.match(line)
    if m and _is_upper(m.group(2)):
        return "heading", m.group(1) + ".", m.group(2), 2
    m = _NUM.match(line)
    if m:
        label, title = m.group(1), m.group(2)  # label keeps the source marker ("1.5.1." / "1.5.1")
        depth = label.rstrip(".").count(".") + 1
        short = len(title) <= MAX_HEADING_CHARS and not title.rstrip().endswith(_TERMINAL) and ":" not in title
        if depth == 1:
            short = short and len(title) <= MAX_TOP_NUMBER_HEADING_CHARS
        if short and title[0].isupper() and not _looks_wrapped(line, next_line):
            return "heading", label, title, 3 if depth <= 2 else 4
        return "clause", label, title, 0
    for rx in (_LETTER, _ROMAN_ITEM):
        m = rx.match(line)
        if m:
            return "clause", m.group(1), m.group(2), 0
    return "continuation", "", line, 0


def parse_blocks(pages: list[DocumentPage]) -> list[Block]:
    """Turn cleaned pages into structural blocks with section + breadcrumb.

    Hard-wrapped lines are unwrapped into one paragraph per clause. State
    (current section / heading path) carries across pages, blocks do not.
    """
    blocks: list[Block] = []
    part, roman = "", ""
    stack: dict[int, str] = {}
    prev_open_ended = False  # previous page's last block had no terminal punctuation

    def section() -> str:
        if part == "A":
            return "A"
        if part == "B" and roman:
            return f"B.{roman}"
        return part

    for page in pages:
        lines = _join_lone_markers([ln for ln in page.text.split("\n")])
        first_block_idx = len(blocks)
        buf: list[str] = []
        cur: dict | None = None

        def flush() -> None:
            nonlocal cur, buf
            if cur is None:
                return
            text = " ".join(buf).strip()
            if text:
                blocks.append(Block(page.page, cur["kind"], text, cur["level"], cur["label"],
                                    cur["section"], cur["path"]))
            cur, buf = None, []

        def path_now() -> str:
            return " > ".join(stack[k] for k in sorted(stack))

        non_empty = [x for x in lines if x]
        for idx, ln in enumerate(non_empty):
            nxt = non_empty[idx + 1] if idx + 1 < len(non_empty) else ""
            kind, label, text, level = _classify(ln, nxt)

            # all-caps title lines before the first "A." heading (document title)
            if kind == "continuation" and not part and _is_upper(ln) and len(ln) > 8:
                if cur and cur["kind"] == "title":
                    buf.append(ln)
                else:
                    flush()
                    cur = {"kind": "title", "level": 1, "label": "", "section": "", "path": ""}
                    buf = [ln]
                continue

            if kind == "continuation":
                if cur is not None and cur["kind"] == "title":
                    flush()  # e.g. "(Áp dụng cho khách hàng cá nhân)" is not part of the title
                if cur is None:
                    cur = {"kind": "paragraph", "level": 0, "label": "", "section": section(), "path": path_now()}
                buf.append(ln)
                continue

            flush()
            if kind == "heading":
                if level == 1:
                    part, roman = label[0], ""
                    stack = {1: f"{label} {text}"}
                elif level == 2:
                    roman = label.rstrip(".")
                    stack = {k: v for k, v in stack.items() if k < 2}
                    stack[2] = f"{label} {text}"
                else:
                    stack = {k: v for k, v in stack.items() if k < level}
                    stack[level] = f"{label} {text}"
                cur = {"kind": "heading", "level": level, "label": label, "section": section(), "path": path_now()}
                buf = [text]
                flush()
            else:  # clause
                cur = {"kind": "clause", "level": 0, "label": label, "section": section(), "path": path_now()}
                buf = [text]
        flush()

        page_blocks = blocks[first_block_idx:]
        if page_blocks and prev_open_ended and page_blocks[0].kind == "paragraph":
            page_blocks[0].continued = True
        if page_blocks:
            last = page_blocks[-1]
            prev_open_ended = last.kind in ("paragraph", "clause") and not last.text.rstrip().endswith(_TERMINAL)

    return blocks


# --------------------------------------------------------------------------- #
# 4. Markdown rendering
# --------------------------------------------------------------------------- #


def _block_md(b: Block) -> str:
    if b.kind == "title":
        return f"# {b.text}"
    if b.kind == "heading":
        label = f"{b.label} " if b.label else ""
        return f"{'#' * (b.level + 1)} {label}{b.text}"
    if b.kind == "clause":
        return f"{b.label} {b.text}"
    return b.text


def to_markdown(pages: list[DocumentPage], blocks: list[Block], document_id: str, source: str) -> str:
    """Markdown with a page marker per PDF page; headings use #..#####."""
    head = [
        "---",
        f"document_id: {document_id}",
        f"source: {source}",
        f"pages: {len(pages)}",
        f"parser: pdf-structured-md {PARSER_VERSION}",
        "---",
        "",
    ]
    body: list[str] = []
    for page in pages:
        pb = [b for b in blocks if b.page == page.page]
        sections = sorted({b.section for b in pb if b.section})
        flag = " continued" if pb and pb[0].continued else ""
        body.append(f"<!-- page: {page.page}{flag} sections: {','.join(sections)} -->")
        if page.metadata.get("empty"):
            body.append("<!-- empty page: no text layer, OCR needed -->")
        body.extend(_block_md(b) + "\n" for b in pb)
    return "\n".join(head + body).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# 5. Verification
# --------------------------------------------------------------------------- #


def _alnum(text: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", text)).lower()


def verify_preservation(pages: list[DocumentPage], markdown: str) -> list[str]:
    """Compare per-page content of the Markdown with the cleaned page text.

    Only whitespace/markers may differ. Returns a list of problems (empty = OK).
    """
    problems: list[str] = []
    parts = re.split(r"<!-- page: (\d+)[^>]*-->", markdown)
    md_pages = {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}
    for p in pages:
        md = md_pages.get(p.page, "")
        md = re.sub(r"<!--.*?-->", "", md)
        md = re.sub(r"(?m)^#{1,6}\s+", "", md)
        if _alnum(md) != _alnum(p.text):
            a, b = _alnum(md), _alnum(p.text)
            problems.append(f"page {p.page}: content changed (md {len(a)} vs text {len(b)} alnum chars)")
    if set(md_pages) != {p.page for p in pages}:
        problems.append("page markers do not match PDF pages")
    return problems


# --------------------------------------------------------------------------- #
# 6. Orchestration
# --------------------------------------------------------------------------- #


def ingest_pdf(path: Path, document_id: str, source: str, out_dir: Path) -> dict:
    raw = load_pdf(path, document_id, source)
    pages = strip_boilerplate(raw)
    blocks = parse_blocks(pages)
    markdown = to_markdown(pages, blocks, document_id, source)
    problems = verify_preservation(pages, markdown)

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{document_id}.md"
    json_path = out_dir / f"{document_id}.pages.json"
    md_path.write_text(markdown, encoding="utf-8", newline="\n")

    payload = {
        "document_id": document_id,
        "source": source,
        "parser": f"pdf-structured-md {PARSER_VERSION}",
        "parsed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_pages": len(pages),
        "pages": [
            {
                "page": p.page,
                "text": p.text,
                "metadata": p.metadata,
                "sections": sorted({b.section for b in blocks if b.page == p.page and b.section}),
                "blocks": [
                    {k: v for k, v in b.__dict__.items() if k != "page"} for b in blocks if b.page == p.page
                ],
            }
            for p in pages
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    empty = [p.page for p in pages if p.metadata["empty"]]
    return {
        "markdown": md_path, "json": json_path, "pages": len(pages), "blocks": len(blocks),
        "kinds": dict(Counter(b.kind for b in blocks)), "empty_pages": empty,
        "removed_boilerplate": dict(Counter(l for p in pages for l in p.metadata["removed_boilerplate"])),
        "problems": problems,
    }


def load_processed(json_path: Path) -> list[DocumentPage]:
    """Reload pages written by `ingest_pdf` (blocks go to `metadata["blocks"]`)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return [
        DocumentPage(
            data["document_id"], data["source"], p["page"], p["text"],
            {**p["metadata"], "blocks": p["blocks"], "sections": p["sections"]},
        )
        for p in data["pages"]
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    starter = Path(__file__).resolve().parent.parent  # defaults do not depend on the cwd
    ap.add_argument("--pdf", type=Path, default=starter.parent / "data" / "20260415_ DieuLeTheVCB.pdf")
    ap.add_argument("--document-id", default="vcb-credit-card-terms-2026")
    ap.add_argument("--source", default="data/20260415_ DieuLeTheVCB.pdf")
    ap.add_argument("--out", type=Path, default=starter / "data" / "processed")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    r = ingest_pdf(args.pdf, args.document_id, args.source, args.out)
    print(f"pages={r['pages']} blocks={r['blocks']} kinds={r['kinds']}")
    print(f"empty pages: {r['empty_pages'] or 'none'}")
    print(f"boilerplate removed: {r['removed_boilerplate']}")
    print(f"markdown -> {r['markdown']}\njson     -> {r['json']}")
    if r["problems"]:
        print("PRESERVATION PROBLEMS:", *r["problems"], sep="\n - ")
        return 1
    print("Text preservation check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
