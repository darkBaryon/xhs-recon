from src.adapters.fixture_adapter import FixtureAdapter

SAMPLE = "tests/fixtures/search_contents_sample.jsonl"


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
