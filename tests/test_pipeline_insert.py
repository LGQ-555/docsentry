# tests/test_pipeline_insert.py
from pathlib import Path

from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, hash_bytes, utcnow


class FakeSource:
    """In-memory source: locator -> bytes. Lets the pipeline be tested with no HTTP.

    ``title`` defaults to the empty string, mirroring ``LocalDirectorySource``
    (which leaves the title to the document's first heading). A stub title like
    ``Path(locator).stem`` would be a title no real source produces for a URL,
    and being truthy it would block the heading fallback under test.
    """

    def __init__(self, name="fake", pages=None, fail_on=(), title=""):
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.pages = dict(pages or {})
        self.fail_on = set(fail_on)
        self.title = title

    def discover(self):
        # Deliberately NOT sorted: a source is allowed to hand back index order,
        # and sync_source promises sorted output regardless. Sorting here would
        # make the ordering test below pass on the fixture's work, not the
        # pipeline's.
        return [
            DocRef(source=self.name, kind=self.kind, locator=locator, title=self.title)
            for locator in self.pages
        ]

    def fetch(self, ref):
        if ref.locator in self.fail_on:
            raise RuntimeError(f"boom: {ref.locator}")
        return Fetched(ref=ref, data=self.pages[ref.locator], fetched_at=utcnow())

    def refreshable(self):
        return True


def _sync(tmp_path, source, manifest=None, report=None):
    # NOT `manifest or Manifest()`: Manifest defines __len__, so an empty
    # manifest is falsy and the caller's object would be silently dropped.
    return sync_source(
        source=source,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=manifest if manifest is not None else Manifest(),
        report=report if report is not None else SourceReport(name=source.name, kind="llms_txt"),
        workers=1,
    )


def test_first_sync_adds_every_page(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\nbody a\n", "https://x/b.md": b"# B\nbody b\n"})
    report = SourceReport(name="fake", kind="llms_txt")

    documents = _sync(tmp_path, source, report=report)

    assert report.discovered == 2
    assert report.added == 2
    assert report.updated == 0
    assert report.skipped == 0
    assert len(documents) == 2


def test_documents_carry_content_and_metadata(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\nbody\n"})
    manifest = Manifest()

    documents = _sync(tmp_path, source, manifest=manifest)

    document = documents[0]
    assert document.content == "# A\nbody\n"
    assert document.title == "A"
    assert document.version == "2026-07-28"
    assert document.kind is SourceKind.LLMS_TXT
    assert document.origin_format == "md"
    assert document.url == "https://x/docs/2026-07-28/a.md"
    assert document.content_hash == hash_bytes(b"# A\nbody\n")


def test_raw_files_are_written_under_raw_root(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\n"})

    _sync(tmp_path, source)

    assert (tmp_path / "raw" / "fake" / "x" / "docs" / "2026-07-28" / "a.md").read_bytes() == b"# A\n"


def test_manifest_records_hash_and_version(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\n"})
    manifest = Manifest()

    _sync(tmp_path, source, manifest=manifest)

    entry = manifest.get("https://x/docs/2026-07-28/a.md")
    assert entry.content_hash == hash_bytes(b"# A\n")
    assert entry.version == "2026-07-28"


def test_second_sync_skips_unchanged_pages(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.added == 0
    assert report.updated == 0
    assert report.skipped == 1


def test_second_sync_refreshes_fetched_at(tmp_path):
    """fetched_at means "last confirmed from source", so a skip still refreshes it."""
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)
    first_stamp = manifest.get("https://x/a.md").fetched_at

    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.skipped == 1
    assert manifest.get("https://x/a.md").fetched_at >= first_stamp


def test_missing_raw_file_is_rewritten_without_counting_as_a_change(tmp_path):
    """Self-healing: a cleared data/raw must not silently break the corpus."""
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)
    (tmp_path / "raw" / "fake" / "x" / "a.md").unlink()

    report = SourceReport(name="fake", kind="llms_txt")
    documents = _sync(tmp_path, source, manifest=manifest, report=report)

    assert (tmp_path / "raw" / "fake" / "x" / "a.md").read_bytes() == b"# A\n"
    assert report.added == 0
    assert report.updated == 0
    assert report.skipped == 1
    assert documents[0].content == "# A\n"


def test_changed_page_is_reported_as_updated(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    source.pages["https://x/a.md"] = b"# A\nnew body\n"
    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.updated == 1
    assert report.added == 0
    assert manifest.get("https://x/a.md").content_hash == hash_bytes(b"# A\nnew body\n")


def test_changed_page_overwrites_raw_file(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    source.pages["https://x/a.md"] = b"# A\nnew\n"
    _sync(tmp_path, source, manifest=manifest)

    assert (tmp_path / "raw" / "fake" / "x" / "a.md").read_bytes() == b"# A\nnew\n"


def test_failed_fetch_is_recorded_and_does_not_abort_the_run(tmp_path):
    source = FakeSource(
        pages={"https://x/a.md": b"# A\n", "https://x/broken.md": b"# B\n"},
        fail_on={"https://x/broken.md"},
    )
    report = SourceReport(name="fake", kind="llms_txt")

    documents = _sync(tmp_path, source, report=report)

    assert len(documents) == 1
    assert report.added == 1
    assert len(report.failed) == 1
    assert report.failed[0]["locator"] == "https://x/broken.md"
    assert "RuntimeError" in report.failed[0]["error"]


def test_failed_page_is_not_written_to_manifest(tmp_path):
    source = FakeSource(pages={"https://x/broken.md": b"# B\n"}, fail_on={"https://x/broken.md"})
    manifest = Manifest()

    _sync(tmp_path, source, manifest=manifest)

    assert "https://x/broken.md" not in manifest


def test_version_breakdown_is_counted(tmp_path):
    source = FakeSource(
        pages={
            "https://x/docs/2026-07-28/a.md": b"# A\n",
            "https://x/docs/draft/b.md": b"# B\n",
            "https://x/seps/c.md": b"# C\n",
        }
    )
    report = SourceReport(name="fake", kind="llms_txt")

    _sync(tmp_path, source, report=report)

    assert report.versions == {"dated": 1, "draft": 1, "unknown": 1}


def test_locator_with_unknown_version_still_becomes_a_document(tmp_path):
    source = FakeSource(pages={"https://x/seps/2322-MRTR.md": b"# MRTR\n"})

    documents = _sync(tmp_path, source)

    assert documents[0].version == "unknown"


def test_doc_id_is_derived_from_source_and_locator(tmp_path):
    from docsentry.models import make_doc_id

    source = FakeSource(pages={"https://x/a.md": b"# A\n"})

    documents = _sync(tmp_path, source)

    assert documents[0].doc_id == make_doc_id("fake", "https://x/a.md")


# --- contracts the implementation claims but the plan never pinned ---------


def test_source_title_wins_over_the_heading(tmp_path):
    # llms.txt carries a human-written title; the document's first heading is
    # the fallback for sources that do not (design spec 6.2). The declared
    # order matters -- reversing it would silently demote every llms_txt title.
    source = FakeSource(pages={"https://x/a.md": b"# Heading\n"}, title="Build a server")

    documents = _sync(tmp_path, source)

    assert documents[0].title == "Build a server"


def test_documents_come_back_sorted_by_locator(tmp_path):
    source = FakeSource(pages={"https://x/b.md": b"# B\n", "https://x/a.md": b"# A\n"})

    documents = _sync(tmp_path, source)

    assert [document.url for document in documents] == ["https://x/a.md", "https://x/b.md"]


def test_raw_write_is_atomic_and_leaves_no_part_file(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})

    _sync(tmp_path, source)
    source.pages["https://x/a.md"] = b"# A\nnew\n"
    _sync(tmp_path, source)

    assert list((tmp_path / "raw").rglob("*.part")) == []
