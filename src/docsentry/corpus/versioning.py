"""Version extraction, bucketing, and version-set pruning.

The version segment lives in the URL path for MCP: ``/docs/2026-07-28/...``
and ``/specification/2026-07-28/...``. ``draft`` is a real version channel --
the next, unreleased spec -- and is kept distinct from a dated release so
retrieval can refuse to serve draft text as if it were stable.

LangChain pages carry no version in URL or body, so they resolve to
``unknown``. That is a property of the corpus, not a gap in extraction.
"""

from __future__ import annotations

import re
from collections import defaultdict

from docsentry.models import DocRef

UNKNOWN_VERSION = "unknown"
DRAFT_VERSION = "draft"

# /docs/2026-07-28/...  |  /specification/draft/...
_VERSION_RE = re.compile(r"/(?:docs|specification)/(\d{4}-\d{2}-\d{2}|draft)(?:/|$)")
# Same, but anchored to the version segment so it can be *replaced*.
_VERSION_SEGMENT_RE = re.compile(r"/(docs|specification)/(?:\d{4}-\d{2}-\d{2}|draft)(?=/)")
_DATED_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def extract_version(locator: str) -> str:
    """Pull a version out of a locator, or ``UNKNOWN_VERSION``."""
    match = _VERSION_RE.search(locator)
    return match.group(1) if match else UNKNOWN_VERSION


def is_dated(version: str) -> bool:
    return bool(_DATED_RE.fullmatch(version))


def version_bucket(version: str) -> str:
    """Reporting bucket: ``"dated"`` | ``"draft"`` | ``"unknown"``.

    The fetch report must break these out separately so that versionless pages
    are visible rather than silently averaged into a coverage number.
    """
    if is_dated(version):
        return "dated"
    if version == DRAFT_VERSION:
        return "draft"
    return "unknown"


def resolve_version(ref: DocRef) -> str:
    """Decide a document's version: an explicit hint wins, else URL extraction.

    ``version_hint`` is how a ``local_dir`` source stamps its
    ``default_version`` onto files that have no version in their path.
    """
    if ref.version_hint:
        return ref.version_hint
    return extract_version(ref.locator)


def logical_key(locator: str) -> str:
    """Strip the version segment so all versions of one page share a key.

    ``/docs/2026-07-28/learn/architecture.md`` and
    ``/docs/draft/learn/architecture.md`` both map to
    ``/docs/learn/architecture.md``. ``/docs/`` and ``/specification/`` stay
    distinct -- they are different documents that happen to share a version.
    """
    return _VERSION_SEGMENT_RE.sub(r"/\1", locator, count=1)


def _version_sort_key(version: str) -> tuple[int, str]:
    # draft outranks every dated release (it is the newest channel);
    # ISO date strings compare lexicographically == chronologically.
    if version == DRAFT_VERSION:
        return (1, "")
    return (0, version)


def prune_to_latest(refs: list[DocRef]) -> list[DocRef]:
    """Keep only the newest version of each page -- ``keep_all_versions: false``.

    Versionless pages pass through untouched: they have no newer alternative,
    and dropping them would delete SEPs and community docs entirely.
    """
    groups: dict[str, list[DocRef]] = defaultdict(list)
    passthrough: list[DocRef] = []

    for ref in refs:
        if resolve_version(ref) == UNKNOWN_VERSION:
            passthrough.append(ref)
        else:
            groups[logical_key(ref.locator)].append(ref)

    kept = list(passthrough)
    for group in groups.values():
        kept.append(max(group, key=lambda r: _version_sort_key(resolve_version(r))))
    return kept
