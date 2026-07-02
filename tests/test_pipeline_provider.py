from src.adapters.fixture_adapter import FixtureAdapter
from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter
from src.pipelines.run_research import _build_adapter

FIXTURE = "tests/fixtures/search_contents_sample.jsonl"
CREATOR = "tests/fixtures/creator_contents_sample.jsonl"


def test_mediacrawler_missing_dir_falls_back_to_fixture():
    cfg = {
        "provider": "mediacrawler",
        "mediacrawler_dir": "/no/such/dir",
        "fixture_path": FIXTURE,
        "creator_fixture_path": CREATOR,
    }
    adapter = _build_adapter(cfg)
    assert isinstance(adapter, FixtureAdapter)  # 路径 (a) 真降级
    assert adapter._creator_path is None  # mediacrawler 分支不消费 creator_fixture_path


def test_mediacrawler_present_dir_returns_mc_adapter(tmp_path):
    cfg = {
        "provider": "mediacrawler",
        "mediacrawler_dir": str(tmp_path),
        "fixture_path": FIXTURE,
        "creator_fixture_path": CREATOR,
        "mediacrawler": {},
        "search": {"limit": 20, "sort": "time_descending"},
    }
    adapter = _build_adapter(cfg)
    assert isinstance(adapter, MediaCrawlerAdapter)
    assert adapter.sort_type == "time_descending"


def test_default_provider_is_fixture():
    assert isinstance(_build_adapter({"fixture_path": FIXTURE}), FixtureAdapter)


def test_fixture_provider_consumes_creator_fixture_path():
    adapter = _build_adapter({"fixture_path": FIXTURE, "creator_fixture_path": CREATOR})

    assert isinstance(adapter, FixtureAdapter)
    assert str(adapter._creator_path) == CREATOR
