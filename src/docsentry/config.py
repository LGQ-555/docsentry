"""Configuration: declarative sources + environment-driven paths.

Sources are declared in ``configs/sources.yaml`` rather than code so that
adding a corpus is a config change, not a code change -- which is the point of
the ``Source`` abstraction.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A source name becomes both a directory (``raw/<name>/``) and a filename
# (``manifests/<name>.json``), so it has to be a plain path segment.
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class SourceConfig(BaseModel):
    """One registered source. Validated so a typo fails at load, not at fetch."""

    name: str
    kind: Literal["llms_txt", "local_dir", "snapshot"]
    enabled: bool = True

    # llms_txt
    llms_txt: str | None = None
    url_include: list[str] = Field(default_factory=list)
    keep_all_versions: bool = True

    # local_dir
    path: Path | None = None
    default_version: str | None = None

    @field_validator("name")
    @classmethod
    def _name_is_a_path_segment(cls, value: str) -> str:
        # Rejecting ``../x`` and ``a/b`` here rather than sanitising at the
        # write site: the name is an identifier, and a name that cannot name a
        # directory is a config error. Same class as the drive-letter escape in
        # corpus/paths.py, caught earlier.
        if not _NAME_RE.fullmatch(value):
            raise ValueError(f"source name {value!r} must be a plain identifier (letters, digits, . _ -)")
        return value

    @field_validator("url_include", mode="before")
    @classmethod
    def _wrap_bare_string(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def _require_kind_specific_fields(self):
        if self.kind == "llms_txt" and not self.llms_txt:
            raise ValueError(f"source {self.name!r}: kind=llms_txt requires 'llms_txt'")
        if self.kind == "local_dir" and not self.path:
            raise ValueError(f"source {self.name!r}: kind=local_dir requires 'path'")
        return self


class SourcesConfig(BaseModel):
    sources: list[SourceConfig]

    def enabled(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def by_name(self, name: str) -> SourceConfig:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"no source named {name!r} in config")


class Settings(BaseSettings):
    """Environment-driven settings. Prefix: ``DOCSENTRY_``, or a ``.env`` file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOCSENTRY_", extra="ignore")

    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    sources_config: Path = Path("configs/sources.yaml")
    chunking_config: Path = Path("configs/chunking.yaml")
    http_timeout_s: float = 30.0
    http_retries: int = 3
    fetch_workers: int = 8

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def manifests_dir(self) -> Path:
        return self.data_dir / "manifests"

    def manifest_path_for(self, source_name: str) -> Path:
        """One manifest per source.

        The manifest is the deletion baseline (``pipeline`` computes ``vanished``
        as the locators it remembers minus the ones it found), so a single file
        shared by every source would make each source treat the others' pages as
        vanished: it would drop their entries, report their count as ``deleted``,
        and re-add them as new on the next run. See the design spec 6.1.4.
        """
        return self.manifests_dir / f"{source_name}.json"

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus.jsonl"


def load_sources_config(path: Path) -> SourcesConfig:
    if not path.exists():
        raise FileNotFoundError(f"sources config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SourcesConfig.model_validate(raw)


class ChunkingConfig(BaseModel):
    """Chunking parameters -- design spec 6.3.

    ``target_size`` is shared by all three strategies; that is the fairness
    constraint, not a convenience. ``overlap`` applies to ``fixed`` alone:
    overlap compensates for a hard cut not knowing where a boundary is, and the
    two structure-aware strategies cut *at* boundaries, so they do not need it.

    Measured indexed-character totals (2026-09-24): ``fixed`` 1.24x the corpus,
    ``semantic`` 1.08x, ``structural`` 1.06x. The difference is disclosed in the
    report rather than equalised -- but note it is no longer *only* the overlap:
    ``fixed``'s 1.24x comes from its 200-character overlap, while the other two
    exceed 1.00x because an atomic unit forced over ``max_atomic_size`` repeats
    context (a table's header in every piece). That repetition costs 1.8% of
    ``structural``'s total, concentrated on 12 wide-table pages.
    """

    target_size: int = 1000
    overlap: int = 200
    max_atomic_size: int = 4000
    max_code_size: int = 3000

    @model_validator(mode="after")
    def _overlap_must_advance(self):
        if self.overlap >= self.target_size:
            raise ValueError("overlap must be smaller than target_size, or the fixed window never advances")
        return self


def load_chunking_config(path: Path) -> ChunkingConfig:
    if not path.exists():
        raise FileNotFoundError(f"chunking config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ChunkingConfig.model_validate(raw)
