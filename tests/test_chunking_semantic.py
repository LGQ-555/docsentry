"""``SemanticChunker`` contract tests.

Cuts at blank lines, never inside a paragraph, and indexes every character
exactly once. "No overlap" is asserted as a round-trip: ``accumulate_paragraphs``
partitions the paragraph sequence, so re-joining the chunks with the paragraph
separator reproduces the source exactly -- nothing dropped, nothing duplicated.
The ``sum(char_count)`` accounting is *not* ``len(content)``: every boundary
between two chunks consumes its 2-character separator, so the indexed total is
exactly ``len(content) - 2 * (n_chunks - 1)`` -- never more than the source.
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import Chunker
from docsentry.chunking.semantic import SemanticChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind


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
