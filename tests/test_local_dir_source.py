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


# --- the seam: what a local_dir document must satisfy downstream -----------
#
# The locator is this source's document identity (doc_id hashes it), and
# paths.raw_relpath() derives a raw-store path from it. An absolute Windows
# path satisfies neither: urlparse() takes the drive letter for a scheme, the
# remainder becomes a drive-anchored path, and ensure_within() then refuses it
# -- aborting the whole run. Nothing tested the two together, so a real CLI run
# over a local_dir source died at the first page.


def _sync(tmp_path, source):
    from docsentry.corpus.converters.markdown import MarkdownConverter
    from docsentry.corpus.manifest import Manifest
    from docsentry.corpus.pipeline import sync_source
    from docsentry.corpus.report import SourceReport

    return sync_source(
        source=source,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=Manifest(),
        report=SourceReport(name=source.name, kind="local_dir"),
        workers=1,
    )


def test_locator_is_relative_to_the_source_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("# B\n", encoding="utf-8")

    locators = [ref.locator for ref in _make_source(tmp_path).discover()]

    assert locators == ["a.md", "sub/b.md"]  # POSIX separators, no drive letter
    assert all(":" not in locator for locator in locators)


def test_local_document_survives_the_pipeline(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    # write_bytes, not write_text: the raw store holds the file's real bytes
    # (Windows text mode would turn these \n into \r\n and the first assertion
    # would be unsatisfiable), while the converter reads them back with
    # universal newlines -- which is why `content` below is LF again.
    (docs / "a.md").write_bytes(b"# A\nbody\n")

    documents = _sync(tmp_path, _make_source(docs, default_version="2026-09-01"))

    assert (tmp_path / "raw" / "internal" / "a.md").read_bytes() == b"# A\nbody\n"
    assert documents[0].url == "a.md"
    assert documents[0].content == "# A\nbody\n"
    assert documents[0].version == "2026-09-01"


def test_doc_id_does_not_depend_on_where_the_directory_lives(tmp_path):
    """Why the locator is relative: move the corpus, or read it on another
    machine, and every document keeps its identity -- no index rebuild."""
    first = tmp_path / "first"
    second = tmp_path / "second" / "deeper"
    for directory in (first, second):
        directory.mkdir(parents=True)
        (directory / "a.md").write_text("# A\nbody\n", encoding="utf-8")

    moved = _sync(tmp_path / "one", _make_source(first, default_version="2026-09-01"))
    elsewhere = _sync(tmp_path / "two", _make_source(second, default_version="2026-09-01"))

    assert moved[0].doc_id == elsewhere[0].doc_id
    assert (tmp_path / "two" / "raw" / "internal" / "a.md").exists()
