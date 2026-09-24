"""Core data models.

M1 defined the corpus-layer models (``SourceKind`` / ``DocRef`` /
``Document``). M2 adds ``Chunk`` here, next to the document it is cut from.
``Answer`` belongs to M4 generation and is deliberately absent so nothing in
this module is dead code.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    """How a source stays fresh -- design spec 6.1.2.

    ``LLMS_TXT`` and ``LOCAL_DIR`` hold *pointers* and can be re-read
    automatically. ``SNAPSHOT`` holds a *copy* and cannot -- which is exactly
    why the project does not build an upload flow.
    """

    LLMS_TXT = "llms_txt"
    LOCAL_DIR = "local_dir"
    SNAPSHOT = "snapshot"


def make_doc_id(source: str, locator: str) -> str:
    """Stable 16-hex identity for a document -- sha256(source + locator)[:16].

    Deliberately content-independent: a document keeps its id across edits, so
    the index can tell "this page changed" from "this page is new".
    """
    return hashlib.sha256(f"{source}{locator}".encode("utf-8")).hexdigest()[:16]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DocRef:
    """A pointer to one document. Cheap to produce in bulk; carries no content."""

    source: str
    kind: SourceKind
    locator: str
    version_hint: str | None = None
    title: str = ""


@dataclass
class Document:
    """One document, normalised to Markdown, ready to be chunked.

    ``indexed_at`` is ``None`` at corpus stage. It is stamped by ``build_index``
    (M3) when the document's chunks are actually upserted -- the authoritative
    value lives in the Qdrant payload, and having the corpus layer guess it
    would misreport provenance by however long the corpus sat on disk.
    """

    doc_id: str
    source: str
    kind: SourceKind
    version: str
    url: str
    title: str
    path: str
    content: str
    content_hash: str
    origin_format: str
    fetched_at: datetime
    indexed_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "kind": self.kind.value,
            "version": self.version,
            "url": self.url,
            "title": self.title,
            "path": self.path,
            "content": self.content,
            "content_hash": self.content_hash,
            "origin_format": self.origin_format,
            "fetched_at": self.fetched_at.isoformat(),
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Document:
        indexed_at = raw.get("indexed_at")
        return cls(
            doc_id=raw["doc_id"],
            source=raw["source"],
            kind=SourceKind(raw["kind"]),
            version=raw["version"],
            url=raw["url"],
            title=raw["title"],
            path=raw["path"],
            content=raw["content"],
            content_hash=raw["content_hash"],
            origin_format=raw["origin_format"],
            fetched_at=datetime.fromisoformat(raw["fetched_at"]),
            indexed_at=datetime.fromisoformat(indexed_at) if indexed_at else None,
        )


def make_chunk_id(doc_id: str, ordinal: int, strategy: str) -> str:
    """Stable 16-hex identity for one chunk -- sha256(doc_id + ordinal + strategy)[:16].

    Strategy is part of the identity on purpose: the same span of text under
    ``fixed`` and under ``structural`` are different chunks, and the vector
    store keys collections by strategy.
    """
    return hashlib.sha256(f"{doc_id}{ordinal}{strategy}".encode("utf-8")).hexdigest()[:16]


@dataclass
class Chunk:
    """One retrievable unit -- design spec 5.

    ``indexed_at`` is ``None`` at chunking stage; ``build_index`` (M3) stamps it
    when the chunk is actually upserted. Same convention as ``Document``: the
    authoritative value lives in the Qdrant payload, and guessing it earlier
    would misreport provenance by however long the corpus sat on disk.

    ``split_atomic`` records that the chunk is a piece of a unit (code block,
    table, or an unbroken prose run) that exceeded ``max_atomic_size`` and
    had to be cut. The evaluation reports on these chunks separately -- "we
    never cut a code block" is a claim the system cannot honestly make, so
    it records when it did instead (design spec 6.3.3 step 6).
    """

    chunk_id: str
    doc_id: str
    text: str
    breadcrumb: list[str]
    source: str
    version: str
    url: str
    kind: str                    # "prose" | "code" | "table" | "mixed"
    strategy: str
    char_count: int
    split_atomic: bool = False
    indexed_at: datetime | None = None
