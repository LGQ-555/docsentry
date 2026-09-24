"""``FixedSizeChunker`` contract tests.

The baseline strategy: a hard character window with overlap. The first test
pins the *stride* semantics -- windows start at 0, ``target - overlap``, 2x, ...
-- and the tail: the final window slides past the end and is clamped short, so
every character of the source is covered by at least one window while every
non-final chunk is exactly ``target_size``.

That coverage property has one documented exception since the M2 fix pass: a
window that is nothing but HTML tags is dropped, and the union of the windows
then has a gap where it was. Intended -- a chunk with nothing retrievable in it
is not worth indexing -- but it is a contract change, so it is tested rather
than left to be discovered (``test_fixed_drops_a_tag_only_window_and_counts_it``).
"""

from datetime import datetime, timezone

import pytest

from docsentry.chunking.base import Chunker, is_noise
from docsentry.chunking.fixed import FixedSizeChunker
from docsentry.config import ChunkingConfig
from docsentry.models import Document, SourceKind, make_chunk_id


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


# --- M2 fix pass: the noise rule is a system rule, and fixed has a gap ---


def test_fixed_drops_a_tag_only_window_and_counts_it(doc):
    """``fixed`` had no notion of noise until the M2 fix pass, so it indexed
    whatever a window happened to contain -- including a window that is nothing
    but HTML tags, which is unembeddable. Measured on the 2026-09-24 corpus: 1
    such window across 774 documents.

    The fixture's windows are laid out so that exactly the second one
    (``[800, 1800)``) is all tags, and the marker tag sits in ``[1000, 1600)``
    -- the span the overlap does *not* copy into a neighbour. So the marker is
    in the document and in no chunk: that is the coverage gap, measured rather
    than asserted in prose, and it is the intended trade (see the module
    docstring). The upstream test that pins "fixed covers the corpus" measures
    exactly this and has to know about it.

    The tag length is 20 characters on purpose: the window stride (800) and the
    window size (1000) are both multiples of it, so no window cuts a tag in
    half. A partial tag is not noise -- ``<div id="a`` has no closing ``>`` to
    strip -- and the first draft of this fixture silently produced zero drops
    for exactly that reason.

    Also pinned: the surviving windows keep their source ordinals, so their ids
    are unchanged. Incremental re-indexing (M3) deletes by id, and renumbering
    would re-insert a document's whole tail because one unrelated window
    vanished.
    """
    content = ("x" * 800 + '<div id="aaaaaaa" />' * 20 + '<div id="DROPME!" />'
               + '<div id="bbbbbbb" />' * 29 + "y" * 1000)
    long_doc = Document(**{**doc.__dict__, "content": content})
    chunker = FixedSizeChunker(ChunkingConfig())

    chunks = chunker.chunk(long_doc)

    assert [c.text for c in chunks] == [content[0:1000], content[1600:2600], content[2400:2800]]
    assert chunker.last_dropped == 1
    assert all(not is_noise(c.text) for c in chunks)
    assert "DROPME!" not in "".join(c.text for c in chunks), \
        "the dropped window's span is covered by no chunk -- the documented gap"
    assert chunks[1].chunk_id == make_chunk_id("doc1", 2, "fixed"), \
        "the surviving window keeps its source ordinal; the drop leaves a gap"


def test_fixed_last_dropped_resets_per_document(doc):
    """Same per-document semantics as the other two strategies: the fairness
    check reuses one chunker across every corpus document, and the published
    total must count each document's drops once."""
    chunker = FixedSizeChunker(ChunkingConfig())
    chunker.chunk(Document(**{**doc.__dict__, "content": '<div id="aaaaaaa" />' * 50}))
    assert chunker.last_dropped > 0

    chunker.chunk(doc)
    assert chunker.last_dropped == 0
