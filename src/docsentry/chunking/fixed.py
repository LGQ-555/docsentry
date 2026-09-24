"""``FixedSizeChunker`` -- the baseline -- design spec 6.3.1.

A hard character window with overlap. It makes no structural judgement at all,
which is the point: it exists to show what those judgements are worth.

The overlap is also why this strategy indexes 1.25x the corpus while the other
two index 1.00x. That difference is published, not equalised -- overlap is a
compensation for cutting blind, and the structure-aware strategies do not need
it (design spec 6.3, M2 design decision 4).
"""

from __future__ import annotations

from docsentry.config import ChunkingConfig
from docsentry.models import Chunk, Document, make_chunk_id


class FixedSizeChunker:
    name = "fixed"

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config

    def chunk(self, doc: Document) -> list[Chunk]:
        size = self.config.target_size
        stride = size - self.config.overlap
        content = doc.content

        # Windows start at every multiple of ``stride`` and keep sliding while
        # ``start < len``, so the final window is clamped short (the tail).
        # Stopping as soon as a window *touches* the end instead would skip
        # that tail window and glue its characters onto a last chunk of
        # variable size; sliding to the end keeps every chunk except the tail
        # at exactly ``target_size``. ``ChunkingConfig`` rejects ``overlap >=
        # target_size``, so ``stride >= 1``: the loop always advances and can
        # never emit the same window twice. An empty document has no window
        # starts and yields no chunks.
        chunks: list[Chunk] = []
        start = 0
        ordinal = 0
        while start < len(content):
            text = content[start:start + size]
            chunks.append(self._make(doc, text, ordinal))
            ordinal += 1
            start += stride
        return chunks

    def _make(self, doc: Document, text: str, ordinal: int) -> Chunk:
        return Chunk(
            chunk_id=make_chunk_id(doc.doc_id, ordinal, self.name),
            doc_id=doc.doc_id,
            text=text,
            breadcrumb=[],
            source=doc.source,
            version=doc.version,
            url=doc.url,
            kind="prose",
            strategy=self.name,
            char_count=len(text),
        )
