"""新入口的时间源与采集适配器组装。"""

import re
from datetime import datetime, timezone
from pathlib import Path

from src.adapters.fixture_adapter import FixtureAdapter
from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter

from .config_models import RunConfig


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def compact_run_id(run_id: str) -> str:
    base = run_id.split(".")[0].split("+")[0]
    return re.sub(r"[^0-9A-Za-zT]", "", base) or "run"


def build_adapter(config: RunConfig):
    comments_path = config.comments.fixture_path
    if config.provider == "mediacrawler":
        if not config.mediacrawler_dir:
            raise ValueError("provider=mediacrawler 需要 mediacrawler_dir 配置")
        if not Path(config.mediacrawler_dir).exists():
            raise ValueError(f"MediaCrawler 目录不可用：{config.mediacrawler_dir}")
        mc = config.mediacrawler
        return MediaCrawlerAdapter(
            config.mediacrawler_dir,
            out_dir=mc.out_dir,
            login_type=mc.login_type,
            cookies=mc.cookies,
            sort_type=config.search.sort,
            max_notes=config.search.limit,
            max_concurrency=mc.max_concurrency,
            sleep_sec=mc.sleep_sec,
            timeout=mc.timeout,
            download_images=mc.download_images,
            media_dir=mc.media_dir,
        )
    if config.provider != "fixture":
        raise ValueError(f"不支持的 provider：{config.provider}")
    if not config.fixture_path:
        raise ValueError("provider=fixture 需要 fixture_path 配置")
    return FixtureAdapter(
        config.fixture_path,
        comments_path=comments_path,
        creator_path=config.creator_fixture_path,
        creator_profiles_path=config.creator_profiles_fixture_path,
    )
