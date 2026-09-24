"""The strategy registry -- one place that maps strategy names to chunkers.

The CLI, the indexer and the fairness check all need to turn a strategy name
into a chunker; the registry exists so they cannot drift apart on what the
strategies are called or how they are built.
"""

import pytest

from docsentry.chunking.registry import STRATEGIES, build_chunker
from docsentry.config import ChunkingConfig


def test_all_three_strategies_are_reachable():
    assert set(STRATEGIES) == {"fixed", "semantic", "structural"}


@pytest.mark.parametrize("name", ["fixed", "semantic", "structural"])
def test_build_returns_a_chunker_with_matching_name(name):
    chunker = build_chunker(name, ChunkingConfig())
    assert chunker.name == name


def test_unknown_strategy_fails_loudly():
    """A typo must surface as an exception, not silently become some default
    strategy -- an eval that quietly ran ``fixed`` for ``structual`` would
    report numbers for a strategy nobody asked for."""
    with pytest.raises(KeyError):
        build_chunker("nope", ChunkingConfig())
