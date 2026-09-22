"""M1 acceptance against the real corpora.

Excluded by default (see pyproject `addopts`). Run with:

    uv run pytest -m network -v

Slow by design: it downloads both corpora end to end. Six of the eight tests
read one shared first-run sync (see the `synced` fixture); only the idempotence
test re-fetches, because two consecutive runs *are* its subject.

This is the only test that talks to the real internet, and the first live run
(2026-09-22) is why it exists: it found that a page the site does not publish
as Markdown was being ingested as if it were, that LangChain serves sixteen
such pages, and that two sources sharing one manifest delete each other's
entries. None of that was visible to the other 192 tests, which use stubs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docsentry.config import Settings, load_sources_config
from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from scripts.fetch_corpus import build_source

pytestmark = pytest.mark.network

CONFIG = Path("configs/sources.yaml")

# Upstream is not perfect and neither are we entitled to assume it is: the
# index lists pages that 404, and pages that are not served as Markdown at all
# (design spec 6.1.2 -- a source can only promise to re-read the pointer).
# What we do owe is that the loss is small, bounded, and *named*.
MAX_FAILURE_RATE = 0.05


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="module")
def sources():
    return {s.name: s for s in load_sources_config(CONFIG).sources}


def _enabled(sources) -> list:
    return [config for config in sources.values() if config.enabled]


def _scoped(settings: Settings, data_dir: Path) -> Settings:
    """The real settings, pointed at a temp dir.

    Same type and same derived paths -- including ``manifest_path_for`` -- so the
    test exercises the CLI's own layout rather than a parallel one, without
    reading or writing the repo's ``data/``.
    """
    return settings.model_copy(update={"data_dir": data_dir, "reports_dir": data_dir.parent / "reports"})


def _sync(config, settings: Settings):
    """Run one source exactly as the CLI does: its own manifest, start to finish."""
    manifest = Manifest.load(settings.manifest_path_for(config.name))
    report = SourceReport(name=config.name, kind=config.kind)

    documents = sync_source(
        source=build_source(config, settings),
        converter=MarkdownConverter(),
        raw_root=settings.raw_dir,
        manifest=manifest,
        report=report,
        workers=settings.fetch_workers,
    )
    manifest.save(settings.manifest_path_for(config.name))
    return documents, report


def _sync_all(configs, settings: Settings):
    return {config.name: _sync(config, settings) for config in configs}


@pytest.fixture(scope="module")
def synced(settings, sources, tmp_path_factory):
    """Both sources, one first run, shared by the tests below.

    Syncing per test downloaded the two corpora seven times over (~5250 requests,
    measured 9m40s) to observe an upstream state that cannot differ within a
    single run. The sources still share one ``raw_root``, in config order -- that
    is the CLI's own shape, and the reason a cross-source deletion is visible
    here at all (`test_one_source_never_deletes_another_sources_documents` in
    test_fetch_corpus_cli.py pins the same interaction on stubs).
    """
    scoped = _scoped(settings, tmp_path_factory.mktemp("corpus"))
    return _sync_all(_enabled(sources), scoped)


def test_two_sources_yield_at_least_400_documents(synced):
    total = 0
    for name, (documents, report) in synced.items():
        # A first run has nothing to delete. Counting a deletion here means a
        # source looked at another source's baseline (or its own stray files).
        assert report.deleted == 0, f"{name} deleted {report.deleted} on a first run"
        assert len(report.failed) <= MAX_FAILURE_RATE * report.discovered, f"{name}: {report.failed[:5]}"
        total += len(documents)

    assert total >= 400, f"only {total} documents"


def test_every_failure_names_a_reason_we_expect(synced):
    """The report is where a loss belongs; it must never be unexplained."""
    for name, (_, report) in synced.items():
        for failure in report.failed:
            assert "404" in failure["error"] or "unexpected content type" in failure["error"], (
                f"{name}: {failure}"
            )


def test_no_html_page_is_ingested(synced):
    """langchain serves sixteen `.md` URLs as `text/html`.

    Four of those embed a per-request CSRF token, so before this guard they
    were also the reason a second run could never report zero changes.
    """
    for name, (documents, _) in synced.items():
        for document in documents:
            assert not document.content.lstrip().startswith("<!DOCTYPE"), f"{name}: {document.url}"


def test_mcp_version_labelling_is_at_least_90_percent(synced):
    """The M1 criterion, measured over the pages actually indexed.

    `/docs/` + `/specification/` are 252 pages: 198 dated + 54 draft. The 95
    versionless pages (`/seps/`, `/community/`, `/registry/`, `/extensions/`)
    are deliberately not part of this source (see configs/sources.yaml), so
    they cannot dilute the figure. `draft` is a real version channel and counts
    as labelled.
    """
    _, report = synced["mcp"]

    assert report.versions["dated"] + report.versions["draft"] >= 0.9 * report.discovered
    assert report.discovered >= 240


def test_mcp_covers_every_published_spec_version(synced):
    """Version-aware retrieval is only meaningful if the versions are all there."""
    documents, _ = synced["mcp"]

    versions = {document.version for document in documents}

    assert {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"} <= versions
    assert "draft" in versions


def test_langchain_recursion_expands_the_python_index(synced):
    """Recursion reaches the topic sub-indexes, not just the top-level one.

    2026-09-22: 539 discovered -- 369 from `/oss/python/llms.txt` plus seven
    sibling sub-indexes (concepts, contributing, deepagents, langchain,
    langgraph, migrate, releases). The floor is deliberately well below the
    observed count: this asserts that recursion happened, not how big the
    corpus is on any given day.
    """
    documents, report = synced["langgraph"]

    assert len(documents) >= 350
    assert report.versions["unknown"] == len(documents)  # the corpus carries no versions


def test_mcp_documents_are_real_markdown_with_titles(synced):
    documents, _ = synced["mcp"]
    sample = [d for d in documents if "/specification/2026-07-28/" in d.url]

    assert sample, "no 2026-07-28 specification pages retrieved"

    for document in sample:
        assert document.title, f"no title extracted from {document.url}"
        assert len(document.content) > 500, f"suspiciously short: {document.url}"
        # the per-page navigation banner must be gone from every page
        assert "Documentation Index" not in document.content, document.url


def test_second_run_skips_everything(settings, sources, tmp_path):
    """Idempotence -- the property the scheduled task depends on.

    Deliberately not the shared fixture: two consecutive runs against one data
    dir *is* the property, so it owns its corpus rather than borrowing a
    baseline someone else established.
    """
    scoped = _scoped(settings, tmp_path / "data")
    configs = _enabled(sources)
    _sync_all(configs, scoped)

    for name, (_, second) in _sync_all(configs, scoped).items():
        assert second.added == 0, f"{name} re-added {second.added}"
        assert second.updated == 0, f"{name} re-fetched {second.updated} as changed"
        assert second.deleted == 0, f"{name} deleted {second.deleted}"
        # Every discovered page is either unchanged or explained by a failure.
        assert second.skipped + len(second.failed) == second.discovered
