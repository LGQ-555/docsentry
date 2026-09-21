"""Configuration: declarative sources + environment-driven paths.

Sources are declared in ``configs/sources.yaml`` rather than code so that
adding a corpus is a config change, not a code change -- which is the point of
the ``Source`` abstraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    http_timeout_s: float = 30.0
    http_retries: int = 3
    fetch_workers: int = 8

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus.jsonl"


def load_sources_config(path: Path) -> SourcesConfig:
    if not path.exists():
        raise FileNotFoundError(f"sources config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SourcesConfig.model_validate(raw)
