"""The ``Converter`` abstraction -- design spec 4.3 and 6.2.

A converter takes a file on disk and returns normalised Markdown plus the few
facts the pipeline cannot derive itself. It deliberately does *not* build a
``Document``: source, version, doc id and timestamps are the pipeline's to
assemble, and a converter that guessed them would be wrong in the same way for
every format.

M1 ships the one mandatory converter (Markdown). PDF / Office / image
converters are optional per the design's priority table and land only if the
schedule allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ConvertedDoc:
    text: str
    title: str
    origin_format: str


@runtime_checkable
class Converter(Protocol):
    supported: set[str]

    def convert(self, path: Path) -> ConvertedDoc:
        """Read ``path`` and return normalised Markdown."""
        ...
