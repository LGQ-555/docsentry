from docsentry.corpus.versioning import (
    UNKNOWN_VERSION,
    extract_version,
    is_dated,
    logical_key,
    prune_to_latest,
    resolve_version,
    version_bucket,
)
from docsentry.models import DocRef, SourceKind


def _ref(locator, source="mcp", version_hint=None):
    return DocRef(source=source, kind=SourceKind.LLMS_TXT, locator=locator, version_hint=version_hint)


# --- extract_version: every shape observed in the real corpus -------------

def test_extracts_dated_docs_path():
    url = "https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server.md"
    assert extract_version(url) == "2026-07-28"


def test_extracts_dated_specification_path():
    url = "https://modelcontextprotocol.io/specification/2025-11-25/server/tools.md"
    assert extract_version(url) == "2025-11-25"


def test_extracts_draft_from_docs_and_specification():
    assert extract_version("https://modelcontextprotocol.io/docs/draft/learn/architecture.md") == "draft"
    assert extract_version("https://modelcontextprotocol.io/specification/draft/basic/lifecycle.md") == "draft"


def test_versionless_paths_are_unknown():
    for url in (
        "https://modelcontextprotocol.io/seps/2322-MRTR.md",
        "https://modelcontextprotocol.io/community/governance.md",
        "https://modelcontextprotocol.io/registry/about.md",
        "https://modelcontextprotocol.io/extensions/overview.md",
        "https://modelcontextprotocol.io/examples.md",
    ):
        assert extract_version(url) == UNKNOWN_VERSION, url


def test_langchain_docs_are_unknown():
    url = "https://docs.langchain.com/oss/python/langgraph/graph-api.md"
    assert extract_version(url) == UNKNOWN_VERSION


def test_page_about_versioning_is_still_a_versioned_page():
    # `versioning.md` is the page's *name*, not a version segment;
    # the version still comes from the path.
    url = "https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning.md"
    assert extract_version(url) == "2026-07-28"


# --- bucketing ------------------------------------------------------------

def test_bucket_classifies_dated_draft_unknown():
    assert version_bucket("2026-07-28") == "dated"
    assert version_bucket("draft") == "draft"
    assert version_bucket("unknown") == "unknown"
    assert version_bucket("internal-2026Q3") == "unknown"


def test_is_dated():
    assert is_dated("2026-07-28")
    assert not is_dated("draft")
    assert not is_dated("unknown")


# --- resolve_version ------------------------------------------------------

def test_version_hint_wins_over_url():
    ref = _ref("https://example.com/plain.md", version_hint="internal-2026Q3")
    assert resolve_version(ref) == "internal-2026Q3"


def test_resolve_falls_back_to_url_extraction():
    ref = _ref("https://modelcontextprotocol.io/docs/2026-07-28/x.md")
    assert resolve_version(ref) == "2026-07-28"


# --- logical_key ----------------------------------------------------------

def test_logical_key_strips_version_segment():
    a = logical_key("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")
    b = logical_key("https://modelcontextprotocol.io/docs/2025-11-25/learn/architecture.md")
    c = logical_key("https://modelcontextprotocol.io/docs/draft/learn/architecture.md")

    assert a == b == c
    assert a == "https://modelcontextprotocol.io/docs/learn/architecture.md"


def test_logical_key_keeps_docs_and_specification_distinct():
    docs = logical_key("https://modelcontextprotocol.io/docs/2026-07-28/index.md")
    spec = logical_key("https://modelcontextprotocol.io/specification/2026-07-28/index.md")

    assert docs != spec


# --- prune_to_latest (keep_all_versions: false) ---------------------------

def test_prune_keeps_newest_dated_version():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2025-11-25/learn/architecture.md"),
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md"),
        _ref("https://modelcontextprotocol.io/docs/2025-06-18/learn/architecture.md"),
    ]

    kept = prune_to_latest(refs)

    assert len(kept) == 1
    assert kept[0].locator.endswith("/2026-07-28/learn/architecture.md")


def test_prune_prefers_draft_over_dated():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/x.md"),
        _ref("https://modelcontextprotocol.io/docs/draft/x.md"),
    ]

    assert prune_to_latest(refs)[0].locator.endswith("/draft/x.md")


def test_prune_keeps_every_versionless_page():
    refs = [
        _ref("https://modelcontextprotocol.io/seps/1-a.md"),
        _ref("https://modelcontextprotocol.io/community/governance.md"),
    ]

    assert len(prune_to_latest(refs)) == 2


def test_prune_keeps_docs_and_specification_separately():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2025-11-25/index.md"),
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/index.md"),
        _ref("https://modelcontextprotocol.io/specification/2025-11-25/index.md"),
        _ref("https://modelcontextprotocol.io/specification/2026-07-28/index.md"),
    ]

    assert len(prune_to_latest(refs)) == 2
