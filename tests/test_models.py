from datetime import datetime, timezone

from docsentry.models import Document, SourceKind, hash_bytes, make_chunk_id, make_doc_id


def test_make_doc_id_is_stable_and_16_hex():
    first = make_doc_id("mcp", "https://example.com/a.md")
    second = make_doc_id("mcp", "https://example.com/a.md")

    assert first == second
    assert len(first) == 16
    assert all(c in "0123456789abcdef" for c in first)


def test_make_doc_id_depends_on_source_and_locator():
    assert make_doc_id("mcp", "x") != make_doc_id("langgraph", "x")
    assert make_doc_id("mcp", "x") != make_doc_id("mcp", "y")


def test_hash_bytes_matches_known_sha256():
    # sha256("") -- fixed vector, so the hash function cannot silently change
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _document(**overrides):
    base = dict(
        doc_id="abc123",
        source="mcp",
        kind=SourceKind.LLMS_TXT,
        version="2026-07-28",
        url="https://example.com/a",
        title="A",
        path="data/raw/mcp/example.com/a.md",
        content="# A\nbody",
        content_hash="deadbeef",
        origin_format="md",
        fetched_at=datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Document(**base)


def test_document_json_round_trip():
    original = _document()

    restored = Document.from_json(original.to_json())

    assert restored == original


def test_document_json_round_trip_with_indexed_at():
    stamp = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
    original = _document(indexed_at=stamp)

    assert Document.from_json(original.to_json()).indexed_at == stamp


def test_document_kind_serializes_as_string():
    assert _document().to_json()["kind"] == "llms_txt"


def test_chunk_id_is_stable_and_strategy_scoped():
    a = make_chunk_id("doc123", 0, "structural")
    assert a == make_chunk_id("doc123", 0, "structural")
    # the same position under a different strategy is a different chunk
    assert a != make_chunk_id("doc123", 0, "fixed")
    assert a != make_chunk_id("doc123", 1, "structural")
    assert len(a) == 16
