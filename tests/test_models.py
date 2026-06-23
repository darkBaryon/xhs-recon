from src.models import Account, FetchResult, Note


def test_note_roundtrip():
    n = Note(
        note_id="n1",
        account_id="a1",
        title="t",
        body="b",
        tags=["x", "y"],
        url="u",
        like_count=10,
        collect_count=2,
        comment_count=1,
        published_at="2024-01-01T00:00:00Z",
        collected_at="2026-06-24T00:00:00Z",
        source_keywords=["k"],
        raw_path="p",
    )
    d = n.model_dump()
    assert d["like_count"] == 10
    assert d["tags"] == ["x", "y"]


def test_fetchresult_ok_flag():
    good = FetchResult(provider="fixture", operation="search", collected_at="2026")
    assert good.ok is True
    bad = FetchResult(provider="fixture", operation="search", collected_at="2026", error="boom")
    assert bad.ok is False


def test_list_defaults_isolated_between_instances():
    a = FetchResult(provider="fixture", operation="search", collected_at="2026")
    b = FetchResult(provider="fixture", operation="search", collected_at="2026")
    assert a.notes == [] and b.notes == []
    assert a.notes is not b.notes  # pydantic 每实例独立默认，无共享可变默认坑


def test_account_minimal():
    acc = Account(
        account_id="a",
        nickname="n",
        source_keywords=[],
        note_count=0,
        first_seen_at="x",
        last_seen_at="y",
    )
    assert acc.account_id == "a"
