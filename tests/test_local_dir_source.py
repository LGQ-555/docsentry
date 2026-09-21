from pathlib import Path

import pytest

from docsentry.corpus.sources.local_dir import LocalDirectorySource
from docsentry.models import SourceKind


def _make_source(tmp_path: Path, **kwargs) -> LocalDirectorySource:
    return LocalDirectorySource(name="internal", path=tmp_path, **kwargs)


def test_discover_finds_markdown_recursively_and_sorted(tmp_path):
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "c.md").write_text("# C\n", encoding="utf-8")

    refs = _make_source(tmp_path).discover()

    assert [Path(r.locator).name for r in refs] == ["a.md", "b.md", "c.md"]


def test_discover_ignores_non_markdown(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nope\n", encoding="utf-8")
    (tmp_path / "c.pdf").write_bytes(b"%PDF-")

    assert len(_make_source(tmp_path).discover()) == 1


def test_discover_carries_kind_and_source(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    ref = _make_source(tmp_path).discover()[0]

    assert ref.kind is SourceKind.LOCAL_DIR
    assert ref.source == "internal"


def test_default_version_becomes_the_version_hint(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    refs = _make_source(tmp_path, default_version="internal-2026Q3").discover()

    assert refs[0].version_hint == "internal-2026Q3"


def test_no_default_version_leaves_hint_unset(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    assert _make_source(tmp_path).discover()[0].version_hint is None


def test_locator_is_an_absolute_path(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    assert Path(_make_source(tmp_path).discover()[0].locator).is_absolute()


def test_missing_directory_discoveres_nothing(tmp_path):
    assert _make_source(tmp_path / "does-not-exist").discover() == []


def test_empty_directory_discoveres_nothing(tmp_path):
    assert _make_source(tmp_path).discover() == []


def test_fetch_reads_current_bytes(tmp_path):
    target = tmp_path / "a.md"
    target.write_bytes(b"# A\n")
    source = _make_source(tmp_path)

    fetched = source.fetch(source.discover()[0])

    assert fetched.data == b"# A\n"


def test_fetch_returns_bytes_verbatim(tmp_path):
    """``read_text`` would translate CRLF to LF; ``fetch`` must not.

    The content hash has to see the file exactly as it sits on disk, or a
    line-ending-only edit would be invisible. This is also where ``local_dir``
    legitimately differs from the HTTP sources: on Windows a local file keeps
    its ``\\r\\n`` in the hash, while the converter's ``read_text`` normalises
    it away before any text is chunked.
    """
    (tmp_path / "a.md").write_bytes(b"# A\r\nbody\r\n")
    source = _make_source(tmp_path)

    assert source.fetch(source.discover()[0]).data == b"# A\r\nbody\r\n"


def test_fetch_sees_an_edit(tmp_path):
    target = tmp_path / "a.md"
    target.write_bytes(b"# A\n")
    source = _make_source(tmp_path)
    ref = source.discover()[0]

    target.write_bytes(b"# A edited\n")

    assert source.fetch(ref).data == b"# A edited\n"


def test_fetch_raises_when_file_vanished(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("# A\n", encoding="utf-8")
    source = _make_source(tmp_path)
    ref = source.discover()[0]

    target.unlink()

    with pytest.raises(FileNotFoundError):
        source.fetch(ref)


def test_refreshable_is_true(tmp_path):
    assert _make_source(tmp_path).refreshable() is True
