import pytest

from src.adapters.fixture_adapter import FixtureAdapter

SAMPLE = "tests/fixtures/search_contents_sample.jsonl"
COMMENTS = "tests/fixtures/comments.jsonl"


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
