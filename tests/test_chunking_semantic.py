"""``SemanticChunker`` contract tests.

Cuts at blank lines, never inside a paragraph, and indexes every character
exactly once. "No overlap" is asserted as a round-trip: ``accumulate_paragraphs``
partitions the paragraph sequence, so re-joining the chunks with the paragraph
separator reproduces the source exactly -- nothing dropped, nothing duplicated.
The ``sum(char_count)`` accounting is *not* ``len(content)``: every boundary
between two chunks consumes its 2-character separator, so the indexed total is
exactly ``len(content) - 2 * (n_chunks - 1)`` -- never more than the source.

Task 12b adds the one documented exception to "never inside a paragraph": the
``max_atomic_size`` ceiling is a *system* rule about what can be embedded at
all (M2 design decision 2), so a chunk over the ceiling is re-cut -- blocks
over the ceiling with ``cut_atomic`` (flagged ``split_atomic=True``), the rest
at block boundaries. Ordinary documents must stay byte-identical.
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import Chunker, accumulate_paragraphs, segment_blocks
from docsentry.chunking.semantic import SemanticChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind, make_chunk_id


def make_doc(content: str) -> Document:
    return Document(
        doc_id="d", source="mcp", kind=SourceKind.LLMS_TXT, version="2026-07-28",
        url="https://example.com/a.md", title="A", path="a.md",
        content=content, content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


@pytest.fixture
def doc():
    return Document(
        doc_id="d", source="mcp", kind=SourceKind.LLMS_TXT, version="v",
        url="u", title="t", path="p",
        content="a" * 400 + "\n\n" + "b" * 400 + "\n\n" + "c" * 400,
        content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


def test_semantic_splits_at_paragraph_boundaries(doc):
    chunks = SemanticChunker(ChunkingConfig(target_size=1000)).chunk(doc)

    assert len(chunks) == 2
    assert chunks[0].text.endswith("b" * 400)
    assert chunks[1].text.startswith("c")


def test_semantic_never_cuts_a_paragraph():
    """Each chunk must be a whole number of paragraphs."""
    long_doc = Document(
        doc_id="d2", source="s", kind=SourceKind.LLMS_TXT, version="v",
        url="u", title="t", path="p",
        content="\n\n".join(["p" * 300] * 10),
        content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    for chunk in SemanticChunker(ChunkingConfig(target_size=1000)).chunk(long_doc):
        for paragraph in chunk.text.split("\n\n"):
            assert paragraph == "p" * 300


def test_semantic_has_no_overlap(doc):
    """Indexed characters never exceed the source; nothing is dropped.

    ``sum(char_count) == len(content)`` does *not* hold: the chunks partition
    the paragraph sequence, and each boundary between two chunks consumes its
    2-character ``\\n\\n`` separator instead of carrying it into a chunk. The
    invariants that do hold, and are asserted here:

    * round-trip -- re-joining the chunks reproduces the source exactly, so no
      paragraph is indexed twice and none is silently dropped;
    * accounting -- the indexed total is ``len(content) - 2 * (n_chunks - 1)``,
      which is exactly the separators the boundary consumed, never more.

    Scope: this fixture has no piece over ``max_atomic_size``, so it pins the
    boundary behaviour. The ceiling's forced cuts are the documented exception
    -- a table piece repeats its header, so those documents index more than
    their source -- and they are covered by the Task 12b tests below.
    """
    chunks = SemanticChunker(ChunkingConfig()).chunk(doc)

    assert all(c.strategy == "semantic" for c in chunks)
    assert "\n\n".join(c.text for c in chunks) == doc.content
    assert sum(c.char_count for c in chunks) == len(doc.content) - 2 * (len(chunks) - 1)


def test_semantic_empty_document_yields_no_chunks(doc):
    """``accumulate_paragraphs`` fast-paths short text and would hand back
    ``[""]`` for empty content; a zero-character chunk is unembeddable, and
    ``fixed`` yields no chunks for the same document, so the strategies agree."""
    empty = Document(**{**doc.__dict__, "content": ""})
    assert SemanticChunker(ChunkingConfig()).chunk(empty) == []


def test_semantic_satisfies_the_chunker_protocol():
    """Strategies are dispatched with structural ``isinstance`` checks."""
    assert isinstance(SemanticChunker(ChunkingConfig()), Chunker)


# --- Task 12b: the max_atomic_size ceiling is a system rule (M2 decision 2) ---


def test_semantic_respects_the_atomic_ceiling():
    """A 106,158-character chunk was measured on the real corpus. Nothing may
    exceed max_atomic_size -- the ceiling is a system rule about what can be
    embedded at all, not a structural-strategy feature."""
    giant = '<div class="table">\n' + "".join(f"| r{i} | v{i} |\n" for i in range(2000)) + "</div>\n"
    doc = make_doc(giant)
    small = SemanticChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert chunks
    assert all(c.char_count <= 1500 for c in chunks), max(c.char_count for c in chunks)
    assert any(c.split_atomic for c in chunks), "the forced cut must be flagged"


def test_semantic_giant_prose_run_is_hard_cut_and_flagged():
    """Semantic's identity is "never cut a paragraph", so the ceiling's one
    exception must be *visible* on the chunk. An unbroken prose run has no
    boundary to cut at -- no blank line, no fence, no pipe row -- so the cut
    is mid-line at the ceiling, and every piece says ``split_atomic``. This is
    the real-corpus case: measured on the 2026-09-24 corpus, the ceiling
    hard-cuts 245 prose runs, the largest 45,240 characters.
    """
    doc = make_doc("x" * 5000)
    chunks = SemanticChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500)).chunk(doc)

    assert [c.char_count for c in chunks] == [1500, 1500, 1500, 500]
    assert all(c.split_atomic for c in chunks), "the exception must be visible"
    # A hard cut inside a single line drops nothing: the pieces re-join into
    # the run they came from.
    assert "".join(c.text for c in chunks) == doc.content


def test_semantic_still_cuts_at_paragraph_boundaries():
    """The ceiling must not turn semantic into a hard cutter: ordinary
    multi-paragraph text is still split on blank lines, unflagged, and the
    pieces are byte-identical to the pre-ceiling algorithm's."""
    doc = make_doc("\n\n".join(["p" * 300] * 8))
    chunks = SemanticChunker(ChunkingConfig(target_size=1000)).chunk(doc)

    assert all(not c.split_atomic for c in chunks)
    assert [c.text for c in chunks] == accumulate_paragraphs(doc.content, 1000)


def test_semantic_ceiling_leaves_surrounding_paragraphs_untouched():
    """The ceiling only fires on the oversized piece: the paragraphs around a
    giant block keep exactly the packing the pre-ceiling algorithm gave them,
    while every forced-cut piece of the giant is flagged."""
    giant = ("| key | value |\n| --- | --- |\n"
             + "".join(f"| r{i} | v{i} |\n" for i in range(2000)))
    # ``rstrip``: the last row already ends in a newline, so without it the
    # separator that follows makes a triple one and the next paragraph is the
    # pre-ceiling algorithm's ``"\n" + b * 300`` -- a fixture artefact, not the
    # behaviour under test.
    doc = make_doc("\n\n".join(["a" * 300] * 3) + "\n\n" + giant.rstrip("\n")
                   + "\n\n" + "\n\n".join(["b" * 300] * 3))
    small = SemanticChunker(ChunkingConfig(target_size=1000, max_atomic_size=1500))
    chunks = small.chunk(doc)

    assert chunks[0].text == "\n\n".join(["a" * 300] * 3)
    assert not chunks[0].split_atomic
    assert chunks[-1].text == "\n\n".join(["b" * 300] * 3)
    assert not chunks[-1].split_atomic
    assert all(c.split_atomic for c in chunks[1:-1])
    assert all(c.char_count <= 1500 for c in chunks)


def test_semantic_drops_a_tag_only_piece_and_counts_it():
    """The noise rule is a system rule (``is_noise`` in ``base.py``), not a
    structural feature: before the M2 fix pass this strategy kept 31 tag-only
    chunks on the real corpus -- chunks with nothing in them to embed -- while
    ``structural`` dropped a section with the same body.

    Dropping one piece must not renumber the others. The chunk id is
    ``sha256(doc_id + ordinal + strategy)``, and incremental re-indexing (M3)
    deletes by id: if a drop shifted its neighbours' ordinals, every following
    chunk of that document would be re-inserted as new even though its text
    never changed. Ordinal counts *pieces*, not emitted chunks.
    """
    doc = make_doc("a" * 1100 + "\n\n<div id=\"enable-section-numbers\" />\n\n" + "b" * 1100)
    chunker = SemanticChunker(ChunkingConfig())

    chunks = chunker.chunk(doc)

    assert [c.text for c in chunks] == ["a" * 1100, "b" * 1100]
    assert chunker.last_dropped == 1
    assert chunks[1].chunk_id == make_chunk_id("d", 2, "semantic"), \
        "the surviving piece keeps its source ordinal; the drop leaves a gap"


def test_semantic_last_dropped_resets_per_document():
    """The fairness check reuses one chunker across all 774 corpus documents,
    so ``last_dropped`` must mean "dropped by the most recent ``chunk()``
    call" -- a running counter would smear every document's drops over every
    later one, and the published total would be arithmetic on the wrong
    quantity."""
    chunker = SemanticChunker(ChunkingConfig())
    stub = '<div id="x" />'
    chunker.chunk(make_doc("a" * 1100 + "\n\n" + stub))
    assert chunker.last_dropped == 1

    chunker.chunk(make_doc("a" * 1100 + "\n\n" + "b" * 1100))
    assert chunker.last_dropped == 0


def test_semantic_ceiling_applies_to_the_piece_not_just_each_block():
    """A paragraph can exceed the ceiling while every block inside it is under
    it -- prose glued to a mid-size table. The ceiling is about what can be
    embedded, the *chunk*, so such a piece is split at block boundaries. No
    unit is cut mid-unit, so nothing is flagged; the table lands whole.

    The premise is asserted rather than assumed: the first draft of this test
    used 115 rows, which is a 1,650-character table -- over the 1,500 ceiling
    -- so ``cut_atomic`` fired and the test silently checked the wrong path.
    """
    ceiling, target = 1500, 1000
    header = "| key | value |\n| --- | --- |\n"
    rows = "".join(f"| r{i} | v{i} |\n" for i in range(100))  # 1,380 chars
    doc = make_doc("i" * 100 + "\n" + header + rows + "o" * 100 + "\n")

    assert len(doc.content) > ceiling, "the assembled piece must exceed the ceiling"
    assert all(len(block) <= ceiling for _, block in segment_blocks(doc.content)), \
        "every block inside the piece must be under the ceiling"

    small = SemanticChunker(ChunkingConfig(target_size=target, max_atomic_size=ceiling))
    chunks = small.chunk(doc)

    assert all(c.char_count <= ceiling for c in chunks)
    assert not any(c.split_atomic for c in chunks), "whole blocks, no mid-unit cut"
    table = [c for c in chunks if c.text.startswith("| key |")]
    assert len(table) == 1
    assert "| r99 |" in table[0].text, "the table must land whole"
    assert all("|" not in c.text for c in chunks if c is not table[0]), \
        "no table row may leak into the prose pieces"
