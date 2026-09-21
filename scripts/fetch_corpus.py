#!/usr/bin/env python
"""Fetch or incrementally update the corpus.

    uv run scripts/fetch_corpus.py --update               # 增量（默认）
    uv run scripts/fetch_corpus.py --update --source mcp  # 只跑一个源
    uv run scripts/fetch_corpus.py --full                 # 忽略 manifest 全量重抓

Idempotent: running it twice in a row is a no-op the second time. That is the
property the health check and the scheduled task both depend on.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import typer

from docsentry.config import Settings, SourceConfig, load_sources_config
from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest, ManifestUnreadable
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import FetchReport, SourceReport
from docsentry.corpus.sources.llms_txt import LlmsTxtSource
from docsentry.corpus.sources.local_dir import LocalDirectorySource
from docsentry.models import utcnow

app = typer.Typer(add_completion=False, help="Fetch or incrementally update the corpus.")


def build_source(config: SourceConfig, settings: Settings):
    """Turn a validated config entry into a live Source."""
    if config.kind == "llms_txt":
        return LlmsTxtSource(
            name=config.name,
            llms_txt=config.llms_txt,
            url_include=config.url_include,
            keep_all_versions=config.keep_all_versions,
            timeout_s=settings.http_timeout_s,
            retries=settings.http_retries,
        )
    if config.kind == "local_dir":
        return LocalDirectorySource(
            name=config.name,
            path=config.path,
            default_version=config.default_version,
        )
    raise typer.BadParameter(f"unsupported source kind: {config.kind}")


def write_corpus(path: Path, documents) -> None:
    """Write corpus.jsonl atomically, sorted by doc_id for reproducibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for document in sorted(documents, key=lambda d: d.doc_id):
            handle.write(json.dumps(document.to_json(), ensure_ascii=False))
            handle.write("\n")
    tmp.replace(path)


@app.command()
def main(
    config: Path = typer.Option(None, "--config", help="Path to sources.yaml"),
    data_dir: Path = typer.Option(None, "--data-dir"),
    reports_dir: Path = typer.Option(None, "--reports-dir"),
    source: list[str] = typer.Option(None, "--source", help="Only run these sources (repeatable)"),
    update: bool = typer.Option(False, "--update", help="Incremental update (the default)"),
    full: bool = typer.Option(False, "--full", help="Ignore the manifest and re-fetch everything"),
) -> None:
    # `--update` is the spelling documented in CLAUDE.md; it names the default
    # behaviour, and `--full` is its only override. Both are accepted so the
    # documented command works verbatim.
    if update and full:
        typer.secho("error: --update and --full are mutually exclusive", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    settings = Settings()
    if config is not None:
        settings.sources_config = config
    if data_dir is not None:
        settings.data_dir = data_dir
    if reports_dir is not None:
        settings.reports_dir = reports_dir

    try:
        sources_config = load_sources_config(settings.sources_config)
    except FileNotFoundError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    selected = sources_config.enabled()
    if source:
        try:
            selected = [sources_config.by_name(name) for name in source]
        except KeyError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)

    if full:
        manifest = Manifest()  # empty manifest == everything looks new
    else:
        try:
            manifest = Manifest.load(settings.manifest_path)
        except ManifestUnreadable as exc:
            # Aborting beats pretending the file was absent: the manifest is
            # also the deletion baseline, so rebuilding it quietly costs more
            # than the re-fetch it saves (see the manifest module's docstring).
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            typer.secho(
                f"       delete {exc.path} to rebuild it from scratch: every page is then re-fetched.",
                err=True,
            )
            raise typer.Exit(code=2)

    started = utcnow()
    clock = time.perf_counter()
    reports: list[SourceReport] = []
    documents = []

    for source_config in selected:
        live = build_source(source_config, settings)
        typer.echo(f"fetching {source_config.name} ...")
        source_report = SourceReport(name=source_config.name, kind=source_config.kind)

        documents.extend(
            sync_source(
                source=live,
                converter=MarkdownConverter(),
                raw_root=settings.raw_dir,
                manifest=manifest,
                report=source_report,
                workers=settings.fetch_workers,
            )
        )
        reports.append(source_report)

    manifest.save(settings.manifest_path)
    write_corpus(settings.corpus_path, documents)

    report = FetchReport(started_at=started, duration_s=time.perf_counter() - clock, sources=reports)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    destination = settings.reports_dir / f"fetch-{stamp}.json"
    destination.write_text(json.dumps(report.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")

    latest = settings.reports_dir / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destination, latest / "fetch.json")

    typer.echo(report.summary())
    typer.echo(f"\ncorpus: {settings.corpus_path}  ({len(documents)} documents)")
    typer.echo(f"report: {destination}")

    if any(item.failed for item in reports):
        raise typer.Exit(code=1)  # non-zero so a scheduled task can notice


if __name__ == "__main__":
    app()
