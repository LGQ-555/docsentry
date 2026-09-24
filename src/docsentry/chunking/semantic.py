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

That accounting is a property of the *boundary* cuts and stops holding where
the ceiling's forced cuts start (below). A table piece repeats its header row
and delimiter row, so those documents index more than their source: measured
on the 2026-09-24 corpus, +1,130,208 characters of repeated headers against
275 newlines dropped at the prose hard cuts, moving the strategy's indexed
total from 1.00x to 1.08x the corpus and its chunk count from 13,088 to
14,682. It touches 57 of 774 documents; the other 717 are byte-identical.

**A second exception to "nothing is dropped": the noise rule is a system rule
too.** Since the M2 fix pass every strategy applies ``is_noise``, so a piece
whose whole text is HTML tags produces no chunk -- measured on the 2026-09-24
corpus, 31 chunks across 774 documents (0.21%), which is why the counts above
now read 14,651 chunks and 15,154,449 characters against the 14,682 /
15,155,151 recorded when only ``structural`` applied the rule. Dropping these
is the point: nothing in them can be embedded, and keeping them would be the
same silent failure the ceiling exists to prevent, one step earlier.
``last_dropped`` publishes the count, because a piece that disappears without a
number is indistinguishable from one that was never produced.

**The atomic ceiling is a system rule, not a structural feature -- M2 design
decision 2, Task 12b.** Measured on the 2026-09-24 corpus, 288 semantic chunks
(2.20%) exceeded ``max_atomic_size`` and held 21.5% of the indexed characters,
the largest 106,158 -- a chunk the embedding model truncates, and everything
past the limit is invisible to retrieval. Decision 2 already made structural's
"code blocks are never cut" yield to embeddability; the same reasoning yields
semantic's "never cut a paragraph". The rule is therefore enforced on the
*chunk*: a piece that exceeds the ceiling is re-cut -- its blocks over the
ceiling with ``cut_atomic`` (every fragment flagged ``split_atomic=True``, so
the exception is visible rather than silent), the rest packed at block
boundaries. Two consequences follow from enforcing the rule on the piece
rather than on every block:

* A block over the ceiling that the paragraph accumulator would already have
  split at its internal blank lines into embeddable pieces (a fenced code
  listing with a blank line in it -- 28 blocks across 21 corpus documents)
  is left alone: nothing about those chunks violates the ceiling, and
  cutting them would fire the ceiling where no chunk is oversized.
* A paragraph that exceeds the ceiling while every block inside it is under
  it (prose glued to a mid-size table) *is* re-cut: the ceiling is about
  what can be embedded, and that paragraph would become one truncated
  chunk. The cut lands at block boundaries, so no unit is cut mid-unit and
  nothing is flagged there.

Everything else is untouched by construction: when no accumulated piece
exceeds the ceiling, the exact pre-ceiling algorithm runs -- the same
``accumulate_paragraphs`` call on the whole document -- so the chunks of
ordinary documents are byte-identical to before, ids included.
"""

from __future__ import annotations

from docsentry.chunking.base import (
    accumulate_paragraphs,
    cut_atomic,
    effective_target,
    is_noise,
    segment_blocks,
)
from docsentry.config import ChunkingConfig
from docsentry.models import Chunk, Document, make_chunk_id


class SemanticChunker:
    name = "semantic"

    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config
        # Dropped-chunk count for this document -- ``Chunker.last_dropped``.
        # Reported, never silent: see ``is_noise`` in ``base.py`` for why a
        # strategy that drops chunks owes the report a number.
        self.last_dropped = 0

    def chunk(self, doc: Document) -> list[Chunk]:
        self.last_dropped = 0
        if not doc.content:
            # ``accumulate_paragraphs`` fast-paths short text and returns
            # ``[""]`` for empty content; emitting that as a chunk would put a
            # zero-character, unembeddable unit in the index while ``fixed``
            # yields no chunks for the same document.
            return []
        pieces = self._pieces(doc.content)
        chunks: list[Chunk] = []
        for ordinal, (text, atomic) in enumerate(pieces):
            if is_noise(text):
                # The ordinal is the piece's position in the source, never the
                # emitted count: a dropped piece leaves a gap in the numbering
                # rather than renumbering its neighbours, so a chunk's id stays
                # a function of the source text. Incremental re-indexing (M3)
                # depends on that -- an id that shifts because an unrelated
                # piece was dropped would delete and re-insert chunks whose
                # content never changed.
                self.last_dropped += 1
                continue
            chunks.append(Chunk(
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
                split_atomic=atomic,
            ))
        return chunks

    def _pieces(self, content: str) -> list[tuple[str, bool]]:
        """``[(text, split_atomic)]`` in document order -- Task 12b.

        When no accumulated piece exceeds ``max_atomic_size`` this is exactly
        the pre-ceiling algorithm, so ordinary documents keep their chunks
        byte-identical. Only oversized pieces are re-cut; the ceiling never
        rewrites pieces that already fit inside it.
        """
        # ``target`` is capped at the ceiling: the system rule is "nothing may
        # exceed max_atomic_size", and under a config that puts the target
        # above it, the accumulator would happily build over-ceiling pieces.
        # ``effective_target`` is the one implementation of that cap -- it used
        # to live here (and, differently, in ``structural``). Such a config is
        # rejected at load now (``ChunkingConfig``), so the cap is the second
        # line of defence rather than the only one; it stays because this
        # chunker should not rely on a check made in another module.
        ceiling = self.config.max_atomic_size
        target = effective_target(self.config)
        base = accumulate_paragraphs(content, target)
        if all(len(piece) <= ceiling for piece in base):
            return [(piece, False) for piece in base]

        pieces: list[tuple[str, bool]] = []
        for piece in base:
            if len(piece) <= ceiling:
                pieces.append((piece, False))
            else:
                pieces.extend(self._cut_oversized(piece))
        return pieces

    def _cut_oversized(self, piece: str) -> list[tuple[str, bool]]:
        """Re-cut one piece that exceeds ``max_atomic_size``.

        The piece is a single paragraph (a multi-paragraph piece never
        exceeds ``target - 2`` and the target is capped at the ceiling), so
        its blocks touch with no separator between them: packing them by
        concatenation reproduces the piece exactly. Blocks over the ceiling
        go through ``cut_atomic`` and come back flagged; blocks under it are
        packed to ``target`` and stay unflagged -- the cut landed at a block
        boundary (pipe run, fence), never mid-unit.
        """
        ceiling = self.config.max_atomic_size
        target = effective_target(self.config)
        out: list[tuple[str, bool]] = []
        buffer: list[str] = []
        size = 0
        for kind, block in segment_blocks(piece):
            if len(block) > ceiling:
                if buffer:
                    out.append(("".join(buffer), False))
                    buffer, size = [], 0
                out.extend((text, True) for text in cut_atomic(kind, block, self.config))
                continue
            if buffer and size + len(block) > target:
                out.append(("".join(buffer), False))
                buffer, size = [block], len(block)
            else:
                buffer.append(block)
                size += len(block)
        if buffer:
            out.append(("".join(buffer), False))
        return out
