# tests/test_smoke.py
import docsentry


def test_package_imports():
    assert docsentry.__version__


def test_corpus_subpackages_import():
    import docsentry.corpus.converters  # noqa: F401
    import docsentry.corpus.sources  # noqa: F401
