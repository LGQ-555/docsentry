"""Core data models.

M1 defines the corpus-layer models only (``SourceKind`` / ``DocRef`` /
``Document``). ``Chunk`` and ``Answer`` belong to the milestones that produce
them (M2 chunking, M4 generation) and are deliberately absent here so nothing
in this module is dead code.
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
