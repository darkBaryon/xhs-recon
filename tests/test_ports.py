import pytest

from src.core.ports import ResearchAdapter
from src.models import FetchResult


class _Dummy(ResearchAdapter):
    provider_name = "dummy"

    def search(self, keyword, page, limit, collected_at):
        return FetchResult(provider="dummy", operation="search", collected_at=collected_at)


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        ResearchAdapter()


def test_concrete_search_returns_ok_result():
    r = _Dummy().search("k", 1, 20, "2026")
    assert r.ok and r.provider == "dummy"


def test_fetch_comments_defaults_to_not_implemented():
    with pytest.raises(NotImplementedError):
        _Dummy().fetch_comments("n1", 10, "2026")


def test_fetch_creator_notes_defaults_to_not_implemented():
    with pytest.raises(NotImplementedError):
        _Dummy().fetch_creator_notes(["u1"], 10, "2026")
