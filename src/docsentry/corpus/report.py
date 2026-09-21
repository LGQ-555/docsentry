"""Fetch reporting -- design spec 6.1.5.

The risk this module exists for is not "updates are slow", it is "you think an
update happened, but one source failed and the index is quietly missing
content". So failures are collected per locator with their error text, and the
version breakdown is reported in three buckets rather than one coverage
number, so that genuinely versionless pages stay visible instead of being
averaged into a figure that looks like an extraction bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docsentry.corpus.versioning import version_bucket

_BUCKETS = ("dated", "draft", "unknown")


@dataclass
class SourceReport:
    name: str
    kind: str
    discovered: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)
    versions: dict[str, int] = field(default_factory=lambda: {b: 0 for b in _BUCKETS})

    def count_version(self, version: str) -> None:
        bucket = version_bucket(version)
        self.versions[bucket] = self.versions.get(bucket, 0) + 1

    def fail(self, locator: str, error: str) -> None:
        self.failed.append({"locator": locator, "error": error})

    @property
    def labelled_ratio(self) -> float:
        """Share of documents carrying any version label (dated or draft)."""
        total = sum(self.versions.values())
        if total == 0:
            return 0.0
        return (self.versions["dated"] + self.versions["draft"]) / total

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "discovered": self.discovered,
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "failed": sorted(self.failed, key=lambda item: item["locator"]),
            "versions": dict(self.versions),
            "labelled_ratio": round(self.labelled_ratio, 4),
        }


@dataclass
class FetchReport:
    started_at: datetime
    duration_s: float
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        return {
            key: sum(getattr(source, key) for source in self.sources)
            for key in ("discovered", "added", "updated", "skipped", "deleted")
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "duration_s": round(self.duration_s, 3),
            "totals": self.totals,
            "sources": [source.to_json() for source in self.sources],
        }

    @property
    def failures(self) -> list[tuple[str, str, str]]:
        """``(source, locator, error)`` for every failure, in source order.

        The same information as ``sources[i]["failed"]``, flattened so the
        console can show it in one block -- each line carries its source name,
        which the per-source layout used to imply by position.
        """
        return [
            (source.name, item["locator"], item["error"])
            for source in self.sources
            for item in sorted(source.failed, key=lambda i: i["locator"])
        ]

    def summary(self) -> str:
        """Human-readable block for the console, failures first.

        Failures come before any per-source statistics. The failure this report
        exists to expose is the one that gets read past, so it does not get to
        sit between two blocks of reassuring counts.
        """
        lines = [f"fetch report  ({self.duration_s:.1f}s)", ""]

        failures = self.failures
        if failures:
            lines.append(f"  {len(failures)} failed:")
            for source_name, locator, error in failures:
                lines.append(f"    - {source_name}: {locator}: {error}")
            lines.append("")

        for source in self.sources:
            lines.append(
                f"  {source.name:<10} discovered={source.discovered:<5} "
                f"added={source.added:<5} updated={source.updated:<5} "
                f"skipped={source.skipped:<5} deleted={source.deleted}"
            )
            versions = source.versions
            lines.append(
                f"  {'':<10} versions: {versions['dated']} dated, "
                f"{versions['draft']} draft, {versions['unknown']} unknown "
                f"({source.labelled_ratio:.0%} labelled)"
            )

        totals = self.totals
        lines.append("")
        lines.append(
            f"  total      discovered={totals['discovered']} added={totals['added']} "
            f"updated={totals['updated']} skipped={totals['skipped']} deleted={totals['deleted']}"
        )
        return "\n".join(lines)
