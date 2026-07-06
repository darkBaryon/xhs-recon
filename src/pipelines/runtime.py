"""管线运行时编排工具（cli 与 run_research 共享）。

时间源 / adapter 构建 / 配置解析 / 归档软链集中于此，两个入口都以 `runtime.X`
模块属性访问——一处 monkeypatch pin（如 `src.pipelines.runtime.now_iso`）即覆盖
全部命令。core 层永不 import 本模块（这里认具体 adapter，属组装层）。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml

from src.adapters.fixture_adapter import FixtureAdapter
from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter
from src.adapters.mysql_store import MySQLStore
from src.core.ports import ResearchAdapter
from src.core.store import Store
from src.pipelines.config import RunConfig
from src.pipelines.logging_setup import _compact_run_id as compact_run_id
from src.pipelines.logging_setup import configure_logging

logger = logging.getLogger(__name__)

# 供 run_research 复用 logging_setup 的文件名压缩形，无需再从 logging_setup 直接 import
__all__ = [
    "now_iso",
    "build_adapter",
    "build_store",
    "resolve_config_refs",
    "update_latest_link",
    "compact_run_id",
    "prepare",
]


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def build_store(config: RunConfig) -> Store | None:
    """组装根建 store：store.enabled=false → None（旧版全量行为）；否则连本机 MySQL。"""
    if not config.store.enabled:
        return None
    return MySQLStore(config.store.database)


def build_adapter(config: RunConfig) -> ResearchAdapter:
    comments_path = config.comments.fixture_path
    if config.provider == "mediacrawler":
        mc_dir = config.mediacrawler_dir
        if not mc_dir:
            # provider=mediacrawler 必须给 mediacrawler_dir；缺失是配置错误，
            # 显式报错而非静默降级 fixture（避免真采集悄悄变假数据）
            raise ValueError("provider=mediacrawler 需要 mediacrawler_dir 配置")
        if Path(mc_dir).exists():
            mc = config.mediacrawler
            return MediaCrawlerAdapter(
                mc_dir,
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
        # creator_fixture_path is fixture-provider only; MediaCrawler mode must use
        # MediaCrawler creator output. The unavailable-dir fallback keeps that boundary explicit.
        # 路径 (a)：MediaCrawler 目录不可用 → 启动降级 fixture
        return FixtureAdapter(config.fixture_path, comments_path=comments_path)
    return FixtureAdapter(
        config.fixture_path,
        comments_path=comments_path,
        creator_path=config.creator_fixture_path,
        creator_profiles_path=config.creator_profiles_fixture_path,
    )


def _read_asset_yaml(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        raise ValueError(f"引用的资产文件不存在：{path_str}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"资产文件顶层须为键值映射：{path_str}")
    return data


def resolve_config_refs(config: dict) -> dict:
    """解析 keywords_file / watchlist_file 两个可选资产引用（双源冲突即报错，不静默合并）。"""
    keywords_file = config.get("keywords_file")
    if keywords_file:
        if "keywords" in config or "synonyms" in config:
            raise ValueError("keywords_file 与主配置 keywords/synonyms 不可同时提供，二选一")
        data = _read_asset_yaml(keywords_file)
        if "keywords" not in data:
            raise ValueError(f"keywords_file 缺少 keywords 键：{keywords_file}")
        config["keywords"] = data["keywords"]
        if "synonyms" in data:
            config["synonyms"] = data["synonyms"]

    watchlist_file = config.get("watchlist_file")
    if watchlist_file:
        watchlist_cfg = config.get("watchlist") or {}
        if watchlist_cfg.get("manual"):
            raise ValueError("watchlist_file 与主配置 watchlist.manual 不可同时提供，二选一")
        data = _read_asset_yaml(watchlist_file)
        if "manual" not in data:
            raise ValueError(f"watchlist_file 缺少 manual 键：{watchlist_file}")
        watchlist_cfg["manual"] = data["manual"]
        # 主配置无 watchlist 段时自动创建（默认 auto_top_n/max_total 生效）
        config["watchlist"] = watchlist_cfg
    return config


def update_latest_link(base: Path, run_dir: Path) -> None:
    """维护 base/latest 软链指向最新一次运行目录；失败只警告不拦管线（旁路口径）。"""
    latest = base / "latest"
    try:
        if latest.is_symlink():
            latest.unlink()
        elif latest.exists():
            logger.warning("latest 已存在且不是软链，跳过更新：%s", latest)
            return
        latest.symlink_to(run_dir.name, target_is_directory=True)
    except OSError as e:
        logger.warning("latest 软链更新失败：%s", e)


def prepare(
    config_path: str, *, verbose: bool
) -> tuple[RunConfig, str, ResearchAdapter, Store | None]:
    """各命令共用前奏：读配置（含资产引用）→ 建模 → 时间戳 → adapter → store → 日志。

    资产引用双源冲突等 → 打印后 typer.Exit(1)。now_iso/build_adapter 以模块内裸名调用，
    monkeypatch pin `src.pipelines.runtime.now_iso` 等对本函数生效（cli 与 run_research 同源）。
    store 为 None 时管线走旧版全量行为（见 build_store）。
    """
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    try:
        raw = resolve_config_refs(raw)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    config = RunConfig.model_validate(raw)
    collected_at = now_iso()
    adapter = build_adapter(config)
    store = build_store(config)
    configure_logging(
        config.logging.model_dump(),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )
    return config, collected_at, adapter, store
