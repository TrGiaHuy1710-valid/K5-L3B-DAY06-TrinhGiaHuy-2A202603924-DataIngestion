"""Shared data contracts; keep traceability from chunk back to source."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentPage:
    document_id: str
    source: str
    page: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Block:
    """A structural unit (heading / clause / paragraph) of one PDF page.

    Blocks never span pages, so `page` is always the physical PDF page that
    holds the text (needed for gold-page evaluation).
    """
    page: int
    kind: str                      # "title" | "heading" | "clause" | "paragraph"
    text: str
    level: int = 0                 # heading depth (1..4); 0 for non-headings
    label: str = ""                # clause marker, e.g. "1.3.3", "a.", "(iv)"
    section: str = ""              # filterable scope: "A" | "B.I" | "B.II"
    heading_path: str = ""         # breadcrumb of enclosing headings
    continued: bool = False        # True if it continues a paragraph from the previous page


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    source: str
    page: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
