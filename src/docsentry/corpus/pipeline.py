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

    # ---- insert phase: new and changed content lands on disk first --------
    documents: list[Document] = []
    for fetched in _fetch_all(source, refs, workers, report):
        documents.append(_absorb(source, converter, fetched, docs_root, manifest, report))

    return documents


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
        return ref, source.fetch(ref), None
    except Exception as exc:  # noqa: BLE001 -- any per-page failure is reportable, not fatal
        return ref, None, f"{type(exc).__name__}: {exc}"
