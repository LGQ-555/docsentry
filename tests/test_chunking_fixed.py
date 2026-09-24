"""``FixedSizeChunker`` contract tests.

The baseline strategy: a hard character window with overlap. The first test
pins the *stride* semantics -- windows start at 0, ``target - overlap``, 2x, ...
-- and the tail: the final window slides past the end and is clamped short, so
every character of the source is covered by at least one window while every
non-final chunk is exactly ``target_size``.
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import Chunker
from docsentry.chunking.fixed import FixedSizeChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind


@pytest.fixture
def doc():
    return Document(
        doc_id="doc1", source="mcp", kind=SourceKind.LLMS_TXT, version="2026-07-28",
        url="https://example.com/a.md", title="A", path="a.md",
        content="x" * 2500, content_hash="h", origin_format="md",
        fetched_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


def test_fixed_window_advances_by_target_minus_overlap(doc):
    chunker = FixedSizeChunker(ChunkingConfig(target_size=1000, overlap=200))
    chunks = chunker.chunk(doc)

    # 2500 chars, window 1000, stride 800 -> starts at 0, 800, 1600, 2400
    assert len(chunks) == 4
    assert chunks[0].text == "x" * 1000
    assert chunks[-1].text == "x" * 100       # the tail


def test_fixed_chunks_carry_document_provenance(doc):
    chunker = FixedSizeChunker(ChunkingConfig())
    chunk = chunker.chunk(doc)[0]

    assert chunk.doc_id == "doc1"
    assert chunk.source == "mcp"
    assert chunk.version == "2026-07-28"
    assert chunk.url == "https://example.com/a.md"
    assert chunk.strategy == "fixed"
    assert chunk.breadcrumb == []
    assert chunk.char_count == len(chunk.text)
    assert chunk.indexed_at is None


def test_fixed_chunk_ids_are_unique_and_stable(doc):
    chunker = FixedSizeChunker(ChunkingConfig())
    first = chunker.chunk(doc)
    again = chunker.chunk(doc)

    assert [c.chunk_id for c in first] == [c.chunk_id for c in again]
    assert len({c.chunk_id for c in first}) == len(first)


def test_fixed_handles_document_shorter_than_one_window(doc):
    short = Document(**{**doc.__dict__, "content": "abc"})
    chunks = FixedSizeChunker(ChunkingConfig()).chunk(short)

    assert len(chunks) == 1
    assert chunks[0].text == "abc"


def test_fixed_empty_document_yields_no_chunks(doc):
    """No window can start in an empty document; emitting one would be a
    zero-character chunk that nothing downstream can embed or tokenise."""
    empty = Document(**{**doc.__dict__, "content": ""})
    assert FixedSizeChunker(ChunkingConfig()).chunk(empty) == []


def test_fixed_satisfies_the_chunker_protocol():
    """Strategies are dispatched with structural ``isinstance`` checks."""
    assert isinstance(FixedSizeChunker(ChunkingConfig()), Chunker)
