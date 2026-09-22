# tests/test_fetch_corpus_cli.py
import json

from typer.testing import CliRunner

from scripts.fetch_corpus import app

runner = CliRunner()

CONFIG = """
sources:
  - name: one
    kind: llms_txt
    llms_txt: https://x/llms.txt
"""

TWO_SOURCE_CONFIG = """
sources:
  - name: alpha
    kind: llms_txt
    llms_txt: https://alpha.example.com/llms.txt
  - name: beta
    kind: llms_txt
    llms_txt: https://beta.example.com/llms.txt
"""


def _write_config(tmp_path, body=CONFIG):
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_run_writes_corpus_and_report(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli
    from docsentry.models import DocRef, SourceKind, hash_bytes, utcnow
    from docsentry.corpus.sources.base import Fetched

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [DocRef(source="one", kind=self.kind, locator="https://x/docs/2026-07-28/a.md", title="A")]

        def fetch(self, ref):
            return Fetched(ref=ref, data=b"# A\nbody\n", fetched_at=utcnow())

        def refreshable(self):
            return True

    monkeypatch.setattr(cli, "build_source", lambda config, settings: StubSource())

    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.output

    corpus = (tmp_path / "data" / "corpus.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(corpus) == 1
    assert json.loads(corpus[0])["title"] == "A"
    assert json.loads(corpus[0])["version"] == "2026-07-28"

    reports = list((tmp_path / "reports").glob("fetch-*.json"))
    assert len(reports) == 1


def test_report_is_also_copied_to_latest(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [DocRef(source="one", kind=self.kind, locator="https://x/a.md", title="A")]

        def fetch(self, ref):
            return Fetched(ref=ref, data=b"# A\n", fetched_at=utcnow())

        def refreshable(self):
            return True

    monkeypatch.setattr(cli, "build_source", lambda config, settings: StubSource())

    runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert (tmp_path / "reports" / "latest" / "fetch.json").exists()


def test_disabled_source_is_not_run(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli

    calls = []
    monkeypatch.setattr(cli, "build_source", lambda config, settings: calls.append(config.name))

    runner.invoke(
        app,
        [
            "--config", str(
                _write_config(
                    tmp_path,
                    "sources:\n"
                    "  - name: off\n    kind: llms_txt\n    llms_txt: https://x/llms.txt\n    enabled: false\n",
                )
            ),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert calls == []


def test_unknown_source_name_exits_nonzero(tmp_path):
    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--source", "nope",
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code != 0
    assert "nope" in result.output


def test_missing_config_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["--config", str(tmp_path / "nope.yaml"), "--data-dir", str(tmp_path / "data")])

    assert result.exit_code != 0


# --- the CLI's own promises, and Task 11's debt to it ----------------------
#
# One stub factory for the three tests below: they each need a *working* source
# (the five tests above carry their own copy, since each one stubs a different
# shape of answer).


def _stub(locators=("https://x/docs/2026-07-28/a.md",), body=b"# A\nbody\n"):
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [
                DocRef(source="one", kind=self.kind, locator=locator, title="A")
                for locator in locators
            ]

        def fetch(self, ref):
            return Fetched(ref=ref, data=body, fetched_at=utcnow())

        def refreshable(self):
            return True

    return StubSource()


def _invoke(tmp_path, monkeypatch, **stub_kwargs):
    import scripts.fetch_corpus as cli

    monkeypatch.setattr(cli, "build_source", lambda config, settings: _stub(**stub_kwargs))
    return runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )


def test_damaged_manifest_exits_with_an_actionable_message(tmp_path):
    """Task 11's debt: an unreadable manifest must not reach the user as a traceback."""
    data = tmp_path / "data"
    (data / "manifests").mkdir(parents=True)
    (data / "manifests" / "one.json").write_text("{not json", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(data),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 2
    assert "one.json" in result.output  # which file
    assert "delete" in result.output  # and what to do about it
    assert "Traceback" not in result.output


def test_second_run_is_a_no_op(tmp_path, monkeypatch):
    """The property the health check and the scheduled task both depend on."""
    assert _invoke(tmp_path, monkeypatch).exit_code == 0

    assert _invoke(tmp_path, monkeypatch).exit_code == 0

    payload = json.loads((tmp_path / "reports" / "latest" / "fetch.json").read_text(encoding="utf-8"))
    counts = payload["sources"][0]
    assert (counts["added"], counts["updated"], counts["skipped"]) == (0, 0, 1)


def test_corpus_jsonl_is_sorted_and_leaves_no_temp_file(tmp_path, monkeypatch):
    """Sorted by doc_id for reproducible diffs; written atomically."""
    from docsentry.models import make_doc_id

    result = _invoke(tmp_path, monkeypatch, locators=("https://x/z.md", "https://x/a.md"))

    assert result.exit_code == 0, result.output
    lines = (tmp_path / "data" / "corpus.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ids = [json.loads(line)["doc_id"] for line in lines]
    assert ids == sorted(ids)
    assert ids[0] == make_doc_id("one", "https://x/a.md")  # handed back z first
    assert list((tmp_path / "data").glob("*.tmp")) == []


# --- two sources in one run ------------------------------------------------
#
# The deletion baseline is per-source, so one shared manifest makes each source
# see the others' locators as vanished. Every other test here syncs a single
# source, which is exactly why this went unnoticed until the M1 acceptance run.


def _pages(name, locator):
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        kind = SourceKind.LLMS_TXT

        def __init__(self):
            self.name = name

        def discover(self):
            return [DocRef(source=name, kind=self.kind, locator=locator, title=name)]

        def fetch(self, ref):
            return Fetched(ref=ref, data=f"# {name}\nbody\n".encode(), fetched_at=utcnow())

        def refreshable(self):
            return True

    return StubSource()


def _invoke_two_sources(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli

    stubs = {
        "alpha": _pages("alpha", "https://alpha.example.com/docs/a.md"),
        "beta": _pages("beta", "https://beta.example.com/docs/b.md"),
    }
    monkeypatch.setattr(cli, "build_source", lambda config, settings: stubs[config.name])
    return runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path, TWO_SOURCE_CONFIG)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )


def _counts(tmp_path):
    payload = json.loads((tmp_path / "reports" / "latest" / "fetch.json").read_text(encoding="utf-8"))
    return {source["name"]: source for source in payload["sources"]}


def test_one_source_never_deletes_another_sources_documents(tmp_path, monkeypatch):
    result = _invoke_two_sources(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    counts = _counts(tmp_path)
    assert counts["alpha"]["added"] == 1
    assert counts["beta"]["added"] == 1
    # Nothing has vanished from either source on a first run.
    assert counts["alpha"]["deleted"] == 0, "alpha's documents were counted as vanished during beta's sync"
    assert counts["beta"]["deleted"] == 0


def test_two_sources_are_idempotent_across_runs(tmp_path, monkeypatch):
    """The scheduled task's premise, which only holds if the baselines are separate."""
    _invoke_two_sources(tmp_path, monkeypatch)

    result = _invoke_two_sources(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    for name, counts in _counts(tmp_path).items():
        assert (counts["added"], counts["updated"], counts["deleted"]) == (0, 0, 0), (
            f"{name} churned on a second run: {counts}"
        )
        assert counts["skipped"] == counts["discovered"] == 1

