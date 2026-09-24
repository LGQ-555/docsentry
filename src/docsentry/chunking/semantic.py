"""``SemanticChunker`` -- the middle baseline -- design spec 6.3.2.

Accumulates paragraphs up to ``target_size`` and cuts at blank lines. It never
splits a paragraph, but it still has no idea a heading hierarchy exists -- which
is exactly the gap ``structural`` is meant to close.

No overlap: it cuts at real boundaries, so there is no blind cut to compensate
for (design spec 6.3, M2 design decision 4). Because the chunks partition the
paragraph sequence, re-joining them with the paragraph separator reproduces the
document exactly: nothing is indexed twice and nothing is dropped. The indexed
total is ``len(content) - 2 * (n_chunks - 1)`` -- the separators that each
inter-chunk boundary consumed -- never more than the source.
"""

from __future__ import annotations

from docsentry.chunking.base import accumulate_paragraphs
from docsentry.config import ChunkingConfig
from docsentry.models import Chunk, Document, make_chunk_id


class SemanticChunker:
    name = "semantic"

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config

    def chunk(self, doc: Document) -> list[Chunk]:
        if not doc.content:
            # ``accumulate_paragraphs`` fast-paths short text and returns
            # ``[""]`` for empty content; emitting that as a chunk would put a
            # zero-character, unembeddable unit in the index while ``fixed``
            # yields no chunks for the same document.
            return []
        pieces = accumulate_paragraphs(doc.content, self.config.target_size)
        return [
            Chunk(
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
            for ordinal, text in enumerate(pieces)
        ]
