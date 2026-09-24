from pathlib import Path

import pytest
from pydantic import ValidationError

from docsentry.config import (
    ChunkingConfig,
    Settings,
    SourceConfig,
    load_chunking_config,
    load_sources_config,
)


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
    assert settings.manifests_dir == tmp_path / "data" / "manifests"
    assert settings.corpus_path == tmp_path / "data" / "corpus.jsonl"


def test_manifest_path_is_per_source(tmp_path):
    """One baseline per source -- a shared file makes each source delete the others'."""
    settings = Settings(data_dir=tmp_path / "data")

    assert settings.manifest_path_for("mcp") == tmp_path / "data" / "manifests" / "mcp.json"
    assert settings.manifest_path_for("mcp") != settings.manifest_path_for("langgraph")


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b", "", "."])
def test_source_name_must_be_a_path_segment(name):
    """The name becomes a directory and a filename, so it cannot climb out."""
    with pytest.raises(ValidationError):
        SourceConfig(name=name, kind="llms_txt", llms_txt="https://x/llms.txt")


def test_settings_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSENTRY_DATA_DIR", str(tmp_path / "elsewhere"))

    assert Settings().data_dir == tmp_path / "elsewhere"


def test_chunking_config_defaults(tmp_path):
    path = tmp_path / "chunking.yaml"
    path.write_text("target_size: 1000\n", encoding="utf-8")
    cfg = load_chunking_config(path)

    assert cfg.target_size == 1000
    assert cfg.overlap == 200
    assert cfg.max_atomic_size == 4000
    assert cfg.max_code_size == 3000


def test_chunking_config_rejects_overlap_ge_target(tmp_path):
    """overlap >= target_size makes the fixed window never advance."""
    path = tmp_path / "chunking.yaml"
    path.write_text("target_size: 500\noverlap: 500\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_chunking_config(path)


def _chunking(tmp_path, body: str) -> ChunkingConfig:
    path = tmp_path / "chunking.yaml"
    path.write_text(body, encoding="utf-8")
    return load_chunking_config(path)


def test_chunking_config_accepts_the_shipped_config():
    """The guard on editing ``configs/chunking.yaml``.

    That file is the config the fairness report and the M2 acceptance tests
    actually read, and it is user-editable, so a rule it does not satisfy would
    take the whole milestone's measurements down with it at the next run. This
    asserts the shipped file against the real path rather than a copy, because
    a copy is exactly what would drift.
    """
    config = load_chunking_config(Path(__file__).resolve().parents[1] / "configs" / "chunking.yaml")

    assert config.target_size <= config.max_atomic_size


def test_chunking_config_rejects_target_above_the_atomic_ceiling(tmp_path):
    """``target_size`` and ``max_atomic_size`` are both system rules, and this
    config states them so that they contradict.

    Rejected at load rather than resolved at chunk time. Picking a winner at
    chunk time is what the code did before: under exactly this pair, ``fixed``
    -- whose window *is* ``target_size``, since it has no notion of an atomic
    unit -- emitted 8,000-character windows while ``semantic`` and
    ``structural`` capped their packing at 4,000. That silently breaks the one
    thing the shared ``target_size`` exists for (design spec 6.3): the three
    strategies are supposed to differ only in *where* they cut.

    The error must name both rules, because "1000 > 4000 is false" tells a
    reader nothing about which knob to turn.
    """
    with pytest.raises(ValidationError) as excinfo:
        _chunking(tmp_path, "target_size: 8000\nmax_atomic_size: 4000\n")

    message = str(excinfo.value)
    assert "target_size" in message and "max_atomic_size" in message


def test_chunking_config_rejects_negative_overlap(tmp_path):
    """A negative overlap is silent text loss, not just a strange number.

    The stride is ``target_size - overlap``, so an overlap of -500 over a
    1,000-character window strides 1,500: the windows stop touching and the
    region between them is never indexed at all. Measured on a 2,500-character
    document, the two windows cover ``[0:1000]`` and ``[1500:2500]`` and the
    500 characters in ``[1000:1500]`` appear in no chunk. Nothing downstream
    can see the hole -- the chunk count and the chunk sizes both look normal --
    which is why the bound lives on the field rather than in a test.
    """
    with pytest.raises(ValidationError):
        _chunking(tmp_path, "target_size: 1000\noverlap: -500\n")


@pytest.mark.parametrize("field_name", ["target_size", "max_atomic_size", "max_code_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_chunking_config_sizes_must_be_positive(tmp_path, field_name, value):
    """A zero or negative size is not a smaller chunk, it is a broken one: a
    zero window emits nothing, and a negative ceiling rejects every atomic unit
    the corpus contains."""
    with pytest.raises(ValidationError):
        _chunking(tmp_path, f"{field_name}: {value}\n")
