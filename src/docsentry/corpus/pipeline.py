"""Corpus sync: discover -> fetch -> hash-compare -> write, then delete.

The ordering is the point (design spec 6.1.4):

    insert phase  ->  delete phase

New and changed content is written **before** anything is removed. A crash
inside the delete phase therefore leaves extra files, never a hole. The
reverse order -- delete first, then insert -- can delete successfully and then
fail to insert, producing an index gap that nothing notices. There is a test
for the ordering (Task 14) and a test that a failure during deletion still
leaves the new content on disk.

The manifest is saved last and atomically. A crash before that save means the
next run simply re-detects the same changes, so the whole operation is
idempotent in the direction that matters: it never under-reports what it has.

Fetching is concurrent (bounded thread pool) because a full pass is ~700 HTTP
requests. Failures are collected rather than raised -- one 404 must not cost us
the other 699 pages, and the report makes the loss visible.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docsentry.corpus.converters.base import Converter
from docsentry.corpus.manifest import Manifest, ManifestEntry
from docsentry.corpus.paths import ensure_within, raw_relpath
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched, Source
from docsentry.corpus.versioning import resolve_version
from docsentry.models import DocRef, Document, hash_bytes, make_doc_id


def sync_source(
    *,
    source: Source,
    converter: Converter,
    raw_root: Path,
    manifest: Manifest,
    report: SourceReport,
    workers: int = 8,
) -> list[Document]:
    """Bring the raw store in line with one source. Returns its documents."""
    refs = source.discover()
    report.discovered = len(refs)
    docs_root = raw_root / source.name

    discovered = {ref.locator for ref in refs}
    # Decided before anything is touched, from two independent judges: the
    # manifest remembers what this source used to have, and the raw tree shows
    # what is actually on disk. Neither alone is enough -- a lost manifest
    # would disable deletion entirely, while a file with no manifest entry can
    # only be found by looking at the tree.
    vanished = sorted(manifest.locators() - discovered)
    stragglers = _stragglers(docs_root, refs, vanished)

    # ---- insert phase: new and changed content lands on disk first --------
    documents: list[Document] = []
    for fetched in _fetch_all(source, refs, workers, report):
        documents.append(_absorb(source, converter, fetched, docs_root, manifest, report))

    # ---- delete phase: only once the new content is safely in place -------
    for locator in vanished:
        if _forget(source, locator, docs_root, manifest):
            report.deleted += 1

    # Files the manifest no longer remembers. A non-zero count here is the
    # visible trace of a lost or ignored manifest being healed by the tree.
    for path in stragglers:
        if _discard(path):
            report.deleted += 1

    return documents


def _forget(source: Source, locator: str, docs_root: Path, manifest: Manifest) -> bool:
    """Drop one vanished document: its raw file first, then its manifest entry.

    Scoped to ``docs_root`` -- this source's own subtree -- so a source can
    never delete another source's files, even if two sources list the same URL.

    The order inside this function does not matter for correctness, because the
    durable artifact (``manifest.json``) is only written at the very end of the
    run by the caller. A crash here is recovered by the next run, which sees the
    pre-crash manifest and simply retries the delete.

    Returns whether the file is gone. The manifest entry goes either way: it is
    the part that must not linger, and a file that could not be removed becomes
    a straggler next run, which needs no locator to be found again.
    """
    path = _raw_path(docs_root, locator)
    gone = True if path is None else _discard(path)
    manifest.remove(locator)
    return gone


def _raw_path(docs_root: Path, locator: str) -> Path | None:
    """Resolved raw path for a locator, or ``None`` if it cannot be derived.

    ``None`` covers a locator with no usable path segments (``raw_relpath``
    raises) and one that would escape ``docs_root`` (``ensure_within`` refuses).
    """
    try:
        return ensure_within(docs_root / raw_relpath(locator), docs_root)
    except (ValueError, OSError):
        return None


def _discard(path: Path) -> bool:
    """Unlink a raw file; ``True`` if it is gone. A locked file is not fatal."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False  # locked: it stays on disk and is retried next run
    return True


def _stragglers(docs_root: Path, refs: list[DocRef], vanished: list[str]) -> list[Path]:
    """Raw files under ``docs_root`` that no known document claims.

    This is what makes a lost manifest cost one re-fetch instead of silently
    disabling deletion: the raw tree is the durable record, the manifest only a
    memory of it. Compensation for the memory being gone, nothing more -- every
    page still in the source is claimed and therefore safe.

    Claimed paths come from **every discovered ref**, not from the ones that
    fetched successfully, so a transient 404 can never turn into a deletion.

    Both sides are compared *resolved*: ``_absorb`` writes to the resolved path
    while ``rglob`` echoes back the root it was handed, and with a relative or
    dot-containing data dir those two disagree -- which would make every live
    file look unclaimed.

    ``raw_relpath`` sanitises, so a path cannot be turned back into a locator.
    This function never tries: "this file is not claimed" is all it needs.
    """
    claimed = {_raw_path(docs_root, ref.locator) for ref in refs}
    claimed |= {_raw_path(docs_root, locator) for locator in vanished}
    claimed.discard(None)
    if not docs_root.exists():
        return []
    return sorted(
        path for path in docs_root.rglob("*") if path.is_file() and path.resolve() not in claimed
    )


def _absorb(
    source: Source,
    converter: Converter,
    fetched: Fetched,
    docs_root: Path,
    manifest: Manifest,
    report: SourceReport,
) -> Document:
    """Hash-compare one fetched page, write it if needed, and build its Document."""
    ref = fetched.ref
    digest = hash_bytes(fetched.data)
    known = manifest.get(ref.locator)
    unchanged = known is not None and known.content_hash == digest

    version = resolve_version(ref)
    raw_path = ensure_within(docs_root / raw_relpath(ref.locator), docs_root)

    if unchanged and raw_path.exists():
        report.skipped += 1
    else:
        # New, changed, or unchanged-but-missing (someone cleared data/raw).
        # All three need the bytes on disk; only the first two are real changes.
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(raw_path, fetched.data)
        if unchanged:
            report.skipped += 1  # content was already current; only the file was gone
        elif known is None:
            report.added += 1
        else:
            report.updated += 1

    # Refreshed on every run, including unchanged ones: fetched_at means "last
    # confirmed from source", which is what the health check warns on.
    manifest.set(ref.locator, ManifestEntry(digest, version, fetched.fetched_at))
    report.count_version(version)

    converted = converter.convert(raw_path)
    return Document(
        doc_id=make_doc_id(source.name, ref.locator),
        source=source.name,
        kind=source.kind,
        version=version,
        url=ref.locator,
        title=ref.title or converted.title,
        path=str(raw_path),
        content=converted.text,
        content_hash=digest,
        origin_format=converted.origin_format,
        fetched_at=fetched.fetched_at,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file, then rename -- never leave a half-written page."""
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _fetch_all(source: Source, refs: list[DocRef], workers: int, report: SourceReport) -> list[Fetched]:
    """Fetch every ref concurrently, recording failures, ordered by locator.

    Failures are recorded on the **main** thread after the pool drains, so the
    report never depends on completion order and two runs produce identical
    reports. Ordering the result by locator gives the same determinism to the
    rest of the pipeline.
    """
    if workers <= 1:
        outcomes = [_try_fetch(source, ref) for ref in refs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(lambda ref: _try_fetch(source, ref), refs))

    fetched: list[Fetched] = []
    for ref, result, error in sorted(outcomes, key=lambda outcome: outcome[0].locator):
        if error is not None:
            report.fail(ref.locator, error)
            continue
        fetched.append(result)
    return fetched


def _try_fetch(source: Source, ref: DocRef) -> tuple[DocRef, Fetched | None, str | None]:
    try:
        fetched = source.fetch(ref)
    except Exception as exc:  # noqa: BLE001 -- any per-page failure is reportable, not fatal
        return ref, None, f"{type(exc).__name__}: {exc}"
    unexpected = _unexpected_format(fetched)
    if unexpected is not None:
        return ref, None, unexpected
    return ref, fetched, None


# Every ``.md`` URL in both corpora answers with one of these. docs.langchain.com
# serves ``200 text/html`` for sixteen of the URLs its index still lists
# (reference dumps, changelogs, the academy landing page) -- pages it does not
# publish as Markdown at all. ``text/plain`` is deliberately absent: it is not a
# markdown claim, and a corpus that serves .md that way should show up in the
# failure list rather than be guessed at.
_MARKDOWN_TYPES = frozenset({"text/markdown", "text/x-markdown"})


def _unexpected_format(fetched: Fetched) -> str | None:
    """The reason these bytes are not what the source asked for, or ``None``.

    A page rejected here is never written and never remembered, so it cannot
    become a phantom document -- and it is reported like any other failure, which
    is where a loss belongs. ``content_type`` of ``None`` (a source with no
    server to ask) means no claim to check against.
    """
    if fetched.content_type is None:
        return None
    media_type = fetched.content_type.split(";", 1)[0].strip().lower()
    if media_type in _MARKDOWN_TYPES:
        return None
    return f"unexpected content type: {fetched.content_type}"
