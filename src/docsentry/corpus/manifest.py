"""Change detection -- design spec 6.1.4.

The manifest is the only durable record of what we already have. It stores
just enough to detect change (``content_hash``) and to explain provenance
(``version``, ``fetched_at``); everything else about a document is re-derived
on every run so the manifest cannot drift away from reality.

Note the deliberate absence of file paths: a locator maps to a path
deterministically via ``paths.raw_relpath``, so storing it would create a
second source of truth that can go stale. There is a test asserting this.

``fetched_at`` means "last time we confirmed this content from the source" --
it is refreshed on every run, including runs where the content was unchanged
but was re-downloaded and re-hashed. That is what makes the health check's
"not verified in N days" warning meaningful.

Writes are atomic (temp file + rename), so a crash mid-write leaves the
previous manifest intact rather than a truncated one.

Reading keeps apart two failures that used to be conflated. A *missing* file
is a first run: no baseline exists, so an empty manifest loses nothing. A file
that is present but cannot be honoured -- undecodable, invalid JSON, or a
well-formed JSON document of the wrong shape -- raises ``ManifestUnreadable``
instead. The distinction is not cosmetic: the manifest doubles as the deletion
baseline (``pipeline.sync_source`` computes ``vanished`` from it), so silently
rebuilding it empties ``vanished``, the pages that disappeared from the source
are never deleted, and because the run then rewrites the manifest from memory,
those locators end up recorded nowhere. Losing the baseline must be loud.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ManifestUnreadable(Exception):
    """The manifest file exists but cannot be turned into entries.

    Deliberately *not* an ``OSError`` subclass, and there is a test pinning
    that: a caller written as ``except OSError`` must not be able to swallow
    this back into the silent-rebuild path it exists to prevent.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"manifest at {path} is unreadable: {reason}")
        self.path = path
        self.reason = reason


@dataclass
class ManifestEntry:
    content_hash: str
    version: str
    fetched_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "version": self.version,
            "fetched_at": self.fetched_at.isoformat(),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ManifestEntry:
        return cls(
            content_hash=raw["content_hash"],
            version=raw["version"],
            fetched_at=datetime.fromisoformat(raw["fetched_at"]),
        )


class Manifest:
    """``locator -> ManifestEntry``, persisted as a single JSON object."""

    def __init__(self, entries: dict[str, ManifestEntry] | None = None) -> None:
        self._entries: dict[str, ManifestEntry] = dict(entries or {})

    def __contains__(self, locator: str) -> bool:
        return locator in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, locator: str) -> ManifestEntry | None:
        return self._entries.get(locator)

    def locators(self) -> set[str]:
        return set(self._entries)

    def items(self):
        return self._entries.items()

    def set(self, locator: str, entry: ManifestEntry) -> None:
        self._entries[locator] = entry

    def remove(self, locator: str) -> None:
        """Idempotent -- removing an unknown locator is not an error."""
        self._entries.pop(locator, None)

    def to_json(self) -> dict[str, Any]:
        return {locator: entry.to_json() for locator, entry in self._entries.items()}

    @classmethod
    def load(cls, path: Path) -> Manifest:
        """Load the manifest, or start over when there is nothing to load.

        A missing file is a first run and yields an empty manifest. Everything
        else raises ``ManifestUnreadable``: the bytes are there, we cannot
        honour them, and discarding the baseline quietly is the one outcome
        this module refuses to produce.

        Reading is strict (no ``errors="replace"``): the manifest is a file we
        wrote ourselves, so a byte we cannot decode is a real fault rather than
        corpus noise to be tolerated the way the converter tolerates it.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            # OSError: permissions, a directory where the file should be, I/O
            # fault. ValueError: UnicodeDecodeError, for bytes that are not
            # UTF-8. Catching the parents rather than naming subtypes is the
            # point -- the concrete leaf differs by platform.
            raise ManifestUnreadable(path, str(exc)) from exc

        try:
            raw = json.loads(text)
        except ValueError as exc:  # JSONDecodeError derives from ValueError
            raise ManifestUnreadable(path, f"not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ManifestUnreadable(path, f"expected a JSON object, got {type(raw).__name__}")

        entries: dict[str, ManifestEntry] = {}
        for locator, entry in raw.items():
            if not isinstance(entry, dict):
                raise ManifestUnreadable(path, f"entry {locator!r} is not a JSON object")
            try:
                entries[locator] = ManifestEntry.from_json(entry)
            except (KeyError, TypeError, ValueError) as exc:
                raise ManifestUnreadable(path, f"entry {locator!r} is malformed: {exc}") from exc
        return cls(entries)

    def save(self, path: Path) -> None:
        """Atomic write: temp file in the same directory, then ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_json(), indent=2, sort_keys=True, ensure_ascii=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
