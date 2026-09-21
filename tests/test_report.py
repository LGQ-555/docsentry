from datetime import datetime, timezone

from docsentry.corpus.report import FetchReport, SourceReport


def test_source_report_counts_versions_into_buckets():
    report = SourceReport(name="mcp", kind="llms_txt")

    report.count_version("2026-07-28")
    report.count_version("2025-11-25")
    report.count_version("draft")
    report.count_version("unknown")

    assert report.versions == {"dated": 2, "draft": 1, "unknown": 1}


def test_unknown_version_bucket_starts_at_zero():
    assert SourceReport(name="x", kind="llms_txt").versions == {"dated": 0, "draft": 0, "unknown": 0}


def test_labelled_ratio_excludes_unknown():
    report = SourceReport(name="mcp", kind="llms_txt")
    for _ in range(9):
        report.count_version("2026-07-28")
    report.count_version("unknown")

    assert report.labelled_ratio == 0.9


def test_labelled_ratio_of_empty_report_is_zero():
    assert SourceReport(name="x", kind="llms_txt").labelled_ratio == 0.0


def test_failed_is_a_list_of_locator_and_error():
    report = SourceReport(name="mcp", kind="llms_txt")

    report.fail("https://x/broken.md", "HTTPStatusError: 404")

    assert report.failed == [{"locator": "https://x/broken.md", "error": "HTTPStatusError: 404"}]


def _report() -> FetchReport:
    started = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source = SourceReport(name="mcp", kind="llms_txt", discovered=10, added=3, updated=1, skipped=6)
    return FetchReport(started_at=started, duration_s=12.5, sources=[source])


def test_report_totals_sum_across_sources():
    report = _report()
    report.sources.append(SourceReport(name="langgraph", kind="llms_txt", discovered=5, added=5))

    totals = report.totals

    assert totals["discovered"] == 15
    assert totals["added"] == 8
    assert totals["updated"] == 1
    assert totals["skipped"] == 6


def test_report_json_includes_failures_and_version_breakdown():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")

    payload = report.to_json()

    assert payload["sources"][0]["failed"] == [{"locator": "https://x/broken.md", "error": "boom"}]
    assert payload["sources"][0]["versions"] == {"dated": 0, "draft": 0, "unknown": 0}
    assert payload["started_at"] == "2026-09-20T03:00:00+00:00"
    assert payload["duration_s"] == 12.5


def test_report_json_is_json_serialisable():
    import json

    json.dumps(_report().to_json())  # must not raise


def test_summary_mentions_failures_when_present():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")

    text = report.summary()

    assert "1 failed" in text
    assert "https://x/broken.md" in text


def test_summary_is_quiet_when_nothing_failed():
    assert "failed" not in _report().summary().lower()


def test_summary_reports_version_coverage():
    report = _report()
    report.sources[0].count_version("2026-07-28")

    assert "1 dated" in report.summary()


# --- failures first: the docstring's promise, pinned -----------------------


def test_summary_puts_failures_before_the_counts():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")

    lines = report.summary().splitlines()
    first_failure = next(i for i, line in enumerate(lines) if "failed" in line)
    first_counts = next(i for i, line in enumerate(lines) if "discovered=" in line)

    assert first_failure < first_counts


def test_summary_groups_failures_from_every_source_with_their_source_name():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")
    report.sources.append(SourceReport(name="langgraph", kind="llms_txt", discovered=5))
    report.sources[1].fail("https://x/other.md", "404")

    text = report.summary()

    # One block, so lifting failures out of the per-source layout must not
    # lose which source each one came from.
    assert "2 failed" in text
    assert "mcp: https://x/broken.md: boom" in text
    assert "langgraph: https://x/other.md: 404" in text
