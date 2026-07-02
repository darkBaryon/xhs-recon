import pytest

from src.adapters.fixture_adapter import FixtureAdapter

SAMPLE = "tests/fixtures/search_contents_sample.jsonl"
COMMENTS = "tests/fixtures/comments.jsonl"
CREATOR = "tests/fixtures/creator_contents_sample.jsonl"


def test_search_returns_parsed_notes():
    r = FixtureAdapter(SAMPLE).search("留学辅导", 1, 20, "2026")
    assert r.ok
    assert len(r.notes) == 5
    assert r.notes[0].like_count == 10000  # 源 "1万"
    assert r.provider == "fixture"


def test_missing_file_degrades_to_error_not_raise():
    r = FixtureAdapter("tests/fixtures/nope.jsonl").search("k", 1, 20, "2026")
    assert not r.ok
    assert "read fixture failed" in r.error


def test_page_two_is_empty():
    r = FixtureAdapter(SAMPLE).search("留学辅导", 2, 20, "2026")
    assert r.notes == []


def test_limit_caps_notes():
    r = FixtureAdapter(SAMPLE).search("留学辅导", 1, 2, "2026")
    assert len(r.notes) == 2


def test_fetch_comments_without_fixture_is_not_implemented():
    with pytest.raises(NotImplementedError):
        FixtureAdapter(SAMPLE).fetch_comments([], 10, "2026")


def test_fetch_comments_reads_optional_fixture():
    r = FixtureAdapter(SAMPLE, comments_path=COMMENTS).fetch_comments([], 10, "2026")

    assert r.ok
    assert len(r.comments) >= 1
    assert r.comments[0].body.startswith("这个角度")
    assert r.comments[0].like_count == 12000
    assert set(r.comments[0].model_dump()) == {"body", "note_id", "like_count", "collected_at"}


def test_fetch_comments_limit_caps_comments():
    r = FixtureAdapter(SAMPLE, comments_path=COMMENTS).fetch_comments([], 1, "2026")

    assert len(r.comments) == 1


def test_fetch_creator_notes_without_fixture_is_not_implemented():
    with pytest.raises(NotImplementedError):
        FixtureAdapter(SAMPLE).fetch_creator_notes(["601d0481000000000101cc46"], 10, "2026")


def test_fetch_creator_notes_filters_accounts_and_caps_each_account():
    r = FixtureAdapter(SAMPLE, creator_path=CREATOR).fetch_creator_notes(
        ["601d0481000000000101cc46", "602d0481000000000101cc47"],
        1,
        "2026",
    )

    assert r.ok
    assert r.operation == "creator_notes"
    assert [n.note_id for n in r.notes] == [
        "6a4661cd0000000017029d86",
        "6a4661990000000017020001",
    ]
    assert [n.account_id for n in r.notes] == [
        "601d0481000000000101cc46",
        "602d0481000000000101cc47",
    ]
    assert r.notes[0].like_count == 0
    assert r.notes[0].source_keywords == []


def test_fetch_creator_notes_keeps_file_order_after_filtering():
    r = FixtureAdapter(SAMPLE, creator_path=CREATOR).fetch_creator_notes(
        ["602d0481000000000101cc47"],
        10,
        "2026",
    )

    assert [n.title for n in r.notes] == ["第二账号第一条主页笔记", "第二账号第二条主页笔记"]
