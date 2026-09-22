#!/usr/bin/env python
"""Index health check -- design spec 6.1.5.

Reports what the corpus believes it has, and warns about anything that has not
been verified against its source recently. The failure this guards against is
silent: a source that failed months ago leaves an index that looks complete.

Reading goes through ``Manifest.load`` rather than re-parsing the JSON here.
There is one loader for this file and it already draws the line between "no
manifest yet" and "manifest present but unusable" (that module's docstring
explains why the distinction is load-bearing); a second, weaker parser beside
it would report a corrupt manifest as a missing one -- which is the same
silent-completeness failure this module exists to surface, one level up.

There is one manifest per source, so the default reads and merges them all:
the questions here are about the corpus as a whole. ``--manifest`` points at a
single file instead, which is what the unit tests use.

Unlike ``fetch_corpus``, this script never writes the manifest, so an unreadable
one cannot cost us the deletion baseline. It aborts anyway: a health check that
answers "nothing to report" for a file it could not read is worse than one that
refuses to answer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from docsentry.config import Settings
from docsentry.corpus.manifest import Manifest, ManifestUnreadable
from docsentry.corpus.versioning import version_bucket

app = typer.Typer(add_completion=False, help="Report corpus health and staleness.")


def merge_manifests(manifests_dir: Path) -> tuple[Manifest, str]:
    """Every per-source manifest under ``manifests_dir``, as one view.

    Locators are unique per source; should two sources ever list the same one,
    the last file read wins, which can only misstate the reported totals.
    """
    paths = sorted(manifests_dir.glob("*.json")) if manifests_dir.is_dir() else []
    merged = Manifest()
    for path in paths:
        for locator, entry in Manifest.load(path).items():
            merged.set(locator, entry)
    label = f"{manifests_dir} ({len(paths)} sources)" if paths else str(manifests_dir)
    return merged, label


def stale_documents(manifest: Manifest, *, max_age_days: int, now: datetime):
    """``[(locator, days_since_check, version)]`` for entries older than the limit."""
    stale = []
    for locator, entry in manifest.items():
        age_days = (now - entry.fetched_at).days
        if age_days > max_age_days:
            stale.append((locator, age_days, entry.version))
    return sorted(stale, key=lambda item: item[1], reverse=True)


@app.command()
def main(
    manifest: Path = typer.Option(None, "--manifest"),
    max_age_days: int = typer.Option(7, "--max-age-days", help="Warn beyond this many days unverified"),
    now: str = typer.Option(None, "--now", help="Override the current time (for tests)"),
) -> None:
    settings = Settings()
    try:
        if manifest is not None:
            corpus_manifest, label = Manifest.load(manifest), str(manifest)
        else:
            corpus_manifest, label = merge_manifests(settings.manifests_dir)
    except ManifestUnreadable as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        typer.secho(
            "       the corpus is unverified until this is resolved;"
            " run fetch_corpus.py to rebuild it.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not corpus_manifest:
        typer.echo(f"no manifest at {label} -- run fetch_corpus.py first")
        raise typer.Exit(code=0)

    buckets = {"dated": 0, "draft": 0, "unknown": 0}
    for _, entry in corpus_manifest.items():
        buckets[version_bucket(entry.version)] += 1

    typer.echo(f"manifest: {label}")
    typer.echo(f"documents: {len(corpus_manifest)}")
    typer.echo(f"versions: {buckets['dated']} dated, {buckets['draft']} draft, {buckets['unknown']} unknown")

    current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    stale = stale_documents(corpus_manifest, max_age_days=max_age_days, now=current)
    if stale:
        typer.secho(f"\nstale: {len(stale)} documents unverified for over {max_age_days} days", fg=typer.colors.YELLOW)
        for locator, age_days, version in stale[:20]:
            typer.echo(f"  {age_days:>4}d  [{version}]  {locator}")
        if len(stale) > 20:
            typer.echo(f"  ... and {len(stale) - 20} more")


if __name__ == "__main__":
    app()
