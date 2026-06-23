from src.adapters.fixture_adapter import FixtureAdapter
from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter
from src.pipelines.run_research import _build_adapter

FIXTURE = "tests/fixtures/search_contents_sample.jsonl"


def test_mediacrawler_missing_dir_falls_back_to_fixture():
    cfg = {
        "provider": "mediacrawler",
        "mediacrawler_dir": "/no/such/dir",
        "fixture_path": FIXTURE,
    }
    assert isinstance(_build_adapter(cfg), FixtureAdapter)  # 路径 (a) 真降级


def test_mediacrawler_present_dir_returns_mc_adapter(tmp_path):
    cfg = {
        "provider": "mediacrawler",
        "mediacrawler_dir": str(tmp_path),
        "fixture_path": FIXTURE,
        "mediacrawler": {},
        "search": {"limit": 20},
    }
    assert isinstance(_build_adapter(cfg), MediaCrawlerAdapter)


def test_default_provider_is_fixture():
    assert isinstance(_build_adapter({"fixture_path": FIXTURE}), FixtureAdapter)
