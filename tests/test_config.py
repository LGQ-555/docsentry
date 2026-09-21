from pathlib import Path

import pytest
from pydantic import ValidationError

from docsentry.config import Settings, load_sources_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_two_sources(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include:
      - /docs/
      - /specification/
  - name: local
    kind: local_dir
    path: ./data/internal_docs
    default_version: internal-2026Q3
""",
    )

    config = load_sources_config(path)

    assert [s.name for s in config.sources] == ["mcp", "local"]
    assert config.sources[0].url_include == ["/docs/", "/specification/"]
    assert config.sources[0].keep_all_versions is True
    assert config.sources[1].default_version == "internal-2026Q3"


def test_bare_string_url_include_is_wrapped(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://example.com/llms.txt
    url_include: /docs/
""",
    )

    assert load_sources_config(path).sources[0].url_include == ["/docs/"]


def test_missing_url_include_means_no_filter(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://example.com/llms.txt
""",
    )

    assert load_sources_config(path).sources[0].url_include == []


def test_llms_txt_kind_requires_url(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: mcp\n    kind: llms_txt\n")

    with pytest.raises(ValidationError, match="requires 'llms_txt'"):
        load_sources_config(path)


def test_local_dir_kind_requires_path(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: local\n    kind: local_dir\n")

    with pytest.raises(ValidationError, match="requires 'path'"):
        load_sources_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sources_config(tmp_path / "nope.yaml")


def test_settings_derives_paths(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")

    assert settings.raw_dir == tmp_path / "data" / "raw"
    assert settings.manifest_path == tmp_path / "data" / "manifest.json"
    assert settings.corpus_path == tmp_path / "data" / "corpus.jsonl"


def test_settings_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSENTRY_DATA_DIR", str(tmp_path / "elsewhere"))

    assert Settings().data_dir == tmp_path / "elsewhere"
