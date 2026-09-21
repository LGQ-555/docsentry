# tests/test_pipeline_ordering.py
from pathlib import Path

import pytest

from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, utcnow


class FakeSource:
    def __init__(self, name="fake", pages=None):
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.pages = dict(pages or {})

    def discover(self):
        return [
            DocRef(source=self.name, kind=self.kind, locator=locator, title=locator)
            for locator in sorted(self.pages)
        ]

    def fetch(self, ref):
        return Fetched(ref=ref, data=self.pages[ref.locator], fetched_at=utcnow())

    def refreshable(self):
        return True


class RecordingManifest(Manifest):
    """Records the order of mutating operations, so ordering can be asserted."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ops = []

    def set(self, locator, entry):
        self.ops.append(("set", locator))
        super().set(locator, entry)

    def remove(self, locator):
        self.ops.append(("remove", locator))
        super().remove(locator)


class ExplodingOnRemoveManifest(RecordingManifest):
    """A crash partway through the delete phase."""

    def remove(self, locator):
        super().remove(locator)
        raise RuntimeError("crash during delete phase")


def _sync(tmp_path, source, manifest, report=None):
    return sync_source(
        source=source,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=manifest,
        report=report or SourceReport(name=source.name, kind="llms_txt"),
        workers=1,
    )


def _seed(tmp_path, pages, *, name="fake"):
    """One full sync with the manifest persisted -- mirrors fetch_corpus.py."""
    path = tmp_path / f"manifest-{name}.json"
    source = FakeSource(name=name, pages=pages)
    manifest = Manifest.load(path)
    _sync(tmp_path, source, manifest)
    manifest.save(path)
    return source, path


def _rerun(tmp_path, source, manifest_path, report=None):
    """A subsequent run: load the manifest, sync, save. No crash simulation."""
    manifest = Manifest.load(manifest_path)
    documents = _sync(tmp_path, source, manifest, report)
    manifest.save(manifest_path)
    return documents


def _raw(tmp_path, *parts):
    return tmp_path / "raw" / Path(*parts)


# --- the delete phase -----------------------------------------------------

def test_removed_page_is_deleted(tmp_path):
    source, manifest_path = _seed(
        tmp_path, {"https://x/keep.md": b"# Keep\n", "https://x/gone.md": b"# Gone\n"}
    )
    assert _raw(tmp_path, "fake", "x", "gone.md").exists()

    source.pages = {"https://x/keep.md": b"# Keep\n"}
    report = SourceReport(name="fake", kind="llms_txt")
    _rerun(tmp_path, source, manifest_path, report=report)

    assert not _raw(tmp_path, "fake", "x", "gone.md").exists()
    assert "https://x/keep.md" in Manifest.load(manifest_path)
    assert "https://x/gone.md" not in Manifest.load(manifest_path)
    assert report.deleted == 1
    assert report.skipped == 1


def test_insert_happens_before_delete(tmp_path):
    """The whole claim: new content is on disk before anything is removed."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    recording = RecordingManifest(dict(Manifest.load(manifest_path).items()))

    # one page vanishes, one page appears -- both phases have work to do
    source.pages = {"https://x/new.md": b"# New\n"}
    _sync(tmp_path, source, recording)

    ops = [kind for kind, _ in recording.ops]
    assert "set" in ops and "remove" in ops
    assert ops.index("set") < ops.index("remove"), f"delete ran before insert: {ops}"


def test_crash_during_delete_still_leaves_new_content(tmp_path):
    """A failure in the delete phase must not cost us the newly fetched page."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    exploding = ExplodingOnRemoveManifest(dict(Manifest.load(manifest_path).items()))

    source.pages = {"https://x/new.md": b"# New\n"}
    with pytest.raises(RuntimeError, match="crash during delete phase"):
        _sync(tmp_path, source, exploding)

    # the new page reached disk and the in-memory manifest before the crash
    assert _raw(tmp_path, "fake", "x", "new.md").read_bytes() == b"# New\n"
    assert "https://x/new.md" in exploding


def test_crash_during_delete_is_recovered_by_the_next_run(tmp_path):
    """Whatever the crashed run left behind, the retry converges -- no holes."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    exploding = ExplodingOnRemoveManifest(dict(Manifest.load(manifest_path).items()))

    source.pages = {"https://x/new.md": b"# New\n"}
    with pytest.raises(RuntimeError):
        _sync(tmp_path, source, exploding)

    # The crash happened before the manifest was saved, so the retry reads the
    # pre-crash manifest -- exactly what a fresh process would see.
    report = SourceReport(name="fake", kind="llms_txt")
    _rerun(tmp_path, source, manifest_path, report=report)

    assert not _raw(tmp_path, "fake", "x", "old.md").exists()
    assert _raw(tmp_path, "fake", "x", "new.md").read_bytes() == b"# New\n"
    assert "https://x/old.md" not in Manifest.load(manifest_path)
    assert "https://x/new.md" in Manifest.load(manifest_path)
    assert report.added == 1
    assert report.deleted == 1


def test_delete_phase_removes_only_this_sources_files(tmp_path):
    """A source must never delete another source's raw files."""
    _seed(tmp_path, {"https://x/x.md": b"# Other\n"}, name="other")
    assert _raw(tmp_path, "other", "x", "x.md").exists()

    source, manifest_path = _seed(tmp_path, {"https://x/a.md": b"# A\n"})
    source.pages = {}
    _rerun(tmp_path, source, manifest_path)

    assert not _raw(tmp_path, "fake", "x", "a.md").exists()
    assert _raw(tmp_path, "other", "x", "x.md").exists()
