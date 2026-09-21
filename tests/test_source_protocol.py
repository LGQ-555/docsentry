from docsentry.corpus.sources.base import Fetched, Source
from docsentry.models import DocRef, SourceKind


def test_fetched_holds_ref_bytes_and_timestamp():
    ref = DocRef(source="s", kind=SourceKind.LLMS_TXT, locator="https://x/a.md")
    from docsentry.models import utcnow

    fetched = Fetched(ref=ref, data=b"# hi", fetched_at=utcnow())

    assert fetched.ref is ref
    assert fetched.data == b"# hi"


def test_a_conforming_class_satisfies_the_protocol():
    class FakeSource:
        name = "fake"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return []

        def fetch(self, ref):
            raise NotImplementedError

        def refreshable(self):
            return True

    assert isinstance(FakeSource(), Source)


def test_a_partial_class_does_not_satisfy_the_protocol():
    class MissingFetch:
        name = "broken"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return []

        def refreshable(self):
            return True

    assert not isinstance(MissingFetch(), Source)
