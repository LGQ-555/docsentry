# tests/test_health.py
import json
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from docsentry.corpus.manifest import Manifest, ManifestEntry
from scripts.health import app, stale_documents

runner = CliRunner()

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _manifest(tmp_path, entries):
    path = tmp_path / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _entry(version="2026-07-28", days_old=0):
    return {
        "content_hash": "h",
        "version": version,
        "fetched_at": (NOW - timedelta(days=days_old)).isoformat(),
    }


def _manifest_of(entries):
    """``{locator: (version, days_old)}`` -> Manifest -- the shape the CLI reads."""
    return Manifest(
        {
            locator: ManifestEntry(
                content_hash="h", version=version, fetched_at=NOW - timedelta(days=days_old)
            )
            for locator, (version, days_old) in entries.items()
        }
    )


def test_stale_documents_flags_old_entries():
    manifest = _manifest_of(
        {"https://x/fresh.md": ("2026-07-28", 1), "https://x/old.md": ("2026-07-28", 30)}
    )

    stale = stale_documents(manifest, max_age_days=7, now=NOW)

    assert [locator for locator, _, _ in stale] == ["https://x/old.md"]


def test_stale_documents_reports_days_since_check():
    manifest = _manifest_of({"https://x/old.md": ("2026-07-28", 30)})

    stale = stale_documents(manifest, max_age_days=7, now=NOW)

    assert stale[0][1] == 30


def test_stale_documents_is_empty_when_all_fresh():
    manifest = _manifest_of({"https://x/a.md": ("2026-07-28", 0)})

    assert stale_documents(manifest, max_age_days=7, now=NOW) == []


def test_cli_summarises_versions(tmp_path):
    path = _manifest(
        tmp_path,
        {
            "https://x/a.md": _entry("2026-07-28"),
            "https://x/b.md": _entry("draft"),
            "https://x/c.md": _entry("unknown"),
        },
    )

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 0, result.output
    assert "1 dated" in result.output
    assert "1 draft" in result.output
    assert "1 unknown" in result.output


def test_cli_warns_about_stale_documents(tmp_path):
    path = _manifest(tmp_path, {"https://x/old.md": _entry(days_old=30)})

    result = runner.invoke(app, ["--manifest", str(path), "--max-age-days", "7", "--now", NOW.isoformat()])

    assert "stale" in result.output.lower()
    assert "https://x/old.md" in result.output


def test_cli_is_quiet_when_everything_is_fresh(tmp_path):
    path = _manifest(tmp_path, {"https://x/a.md": _entry(days_old=1)})

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert "stale" not in result.output.lower()


def test_cli_handles_missing_manifest(tmp_path):
    result = runner.invoke(app, ["--manifest", str(tmp_path / "nope.json"), "--now", NOW.isoformat()])

    assert result.exit_code == 0
    assert "no manifest" in result.output.lower()


def test_cli_refuses_to_report_on_an_unreadable_manifest(tmp_path):
    # The plan's loader caught the exception and returned {} -- a corrupt
    # manifest was reported as an absent one with exit code 0, which a
    # scheduled task cannot tell apart from a first run.
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"https://x/a.md": {"content_hash": "h",')  # truncated write

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 2
    assert str(path) in result.output
    assert "no manifest" not in result.output.lower()


def test_cli_refuses_on_undecodable_bytes(tmp_path):
    # UnicodeDecodeError derives from ValueError, not OSError, so an
    # `except OSError` around the read does not catch it. That is how the first
    # version of this escaped (see the manifest module's docstring).
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff\xfe{}")  # not UTF-8

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 2
    assert "unreadable" in result.output.lower()
