"""``FixedSizeChunker`` -- the baseline -- design spec 6.3.1.

A hard character window with overlap. It makes no structural judgement at all,
which is the point: it exists to show what those judgements are worth.

The overlap is also why this strategy indexes 1.24x the corpus, more than either
of the other two (``semantic`` 1.08x, ``structural`` 1.06x on the 2026-09-24
corpus). That difference is published, not equalised -- overlap is a
compensation for cutting blind, and the structure-aware strategies do not need
it (design spec 6.3, M2 design decision 4). Nor does having no overlap put them
at 1.00x: their excess over the source is the header a forced atomic cut repeats
into every piece of a wide table.

**One exception to "every character is indexed": a window that is nothing but
HTML tags is dropped** -- the noise rule is a system rule, not a structural
feature, since the M2 fix pass (``is_noise`` in ``base.py``, design decision 3).
Measured on the 2026-09-24 corpus: 1 window across 774 documents. The
consequence is specific to this strategy and belongs in the open: the windows
are a character partition, so removing one leaves a gap in that document's
coverage, and "the union of ``fixed``'s windows covers every character" stops
being true -- the tail of one window is covered by the next only because of the
overlap, and a dropped window is covered by nothing. That is intended (a chunk
with no retrievable content in it is not worth indexing, and it is unembeddable
anyway) but it is a contract change, so it is stated rather than discovered.
``last_dropped`` publishes how often it happened.
"""

from __future__ import annotations

from docsentry.chunking.base import is_noise
from docsentry.config import ChunkingConfig
from docsentry.models import Chunk, Document, make_chunk_id


class FixedSizeChunker:
    name = "fixed"

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config
        # Dropped-window count for this document -- ``Chunker.last_dropped``.
        self.last_dropped = 0

    def chunk(self, doc: Document) -> list[Chunk]:
        self.last_dropped = 0
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
            if is_noise(text):
                # The window index advances either way, so a dropped window
                # leaves a gap in the ids instead of renumbering the windows
                # after it: a chunk's id stays a function of the source
                # offset, which incremental re-indexing (M3) depends on.
                self.last_dropped += 1
            else:
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
