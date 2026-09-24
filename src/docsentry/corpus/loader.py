"""Read ``data/corpus.jsonl`` back into ``Document`` objects."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from docsentry.models import Document


def load_corpus(path: Path) -> Iterator[Document]:
    """Yield every document in a corpus file.

    Deliberately a generator: the real corpus is ~15 MB and chunking streams it,
    so materialising a list would double peak memory for no gain.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield Document.from_json(json.loads(line))
