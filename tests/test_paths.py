from pathlib import Path

import pytest

from docsentry.corpus.paths import ensure_within, raw_relpath


def test_maps_https_url_to_host_and_path():
    rel = raw_relpath("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")

    assert rel == Path("modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")


def test_two_hosts_never_collide():
    a = raw_relpath("https://a.example.com/x.md")
    b = raw_relpath("https://b.example.com/x.md")

    assert a != b


def test_drops_traversal_segments():
    rel = raw_relpath("https://example.com/../../etc/passwd.md")

    assert ".." not in rel.parts


def test_sanitizes_illegal_characters():
    # '*' is legal in a URL but illegal in a Windows filename.
    assert raw_relpath("https://example.com/a*b.md").name == "a_b.md"
    # ':' must be sanitised too: unsanitised it is read as a drive separator.
    assert raw_relpath("https://example.com/a:b.md").name == "a_b.md"


def test_host_survives_a_colon_in_the_path():
    # Regression: sanitising *after* building a Path let Windows read 'a:' as a
    # drive, discarding the host -- which silently defeated the guarantee that
    # two hosts can never collide.
    a = raw_relpath("https://a.example.com/x:y.md")
    b = raw_relpath("https://b.example.com/x:y.md")

    assert a != b
    assert a.parts[0] == "a.example.com"


def test_rejects_locator_with_no_usable_path():
    with pytest.raises(ValueError, match="cannot derive a path"):
        raw_relpath("https://example.com/")


def test_query_string_is_dropped():
    rel = raw_relpath("https://example.com/a.md?v=2")

    assert rel.name == "a.md"


def test_ensure_within_accepts_child(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()

    assert ensure_within(root / "mcp" / "a.md", root) == (root / "mcp" / "a.md").resolve()


def test_ensure_within_rejects_escape(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()

    with pytest.raises(ValueError, match="refusing to touch"):
        ensure_within(tmp_path / "outside.md", root)
