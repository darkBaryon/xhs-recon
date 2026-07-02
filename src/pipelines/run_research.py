"""管线编排：读 config → 注入 adapter → 关键词扩展 → 搜索 → 聚合 → 打分 → 选典型 → 导出。

typer CLI；adapter 由 config 决定（期1 仅 fixture），core 各步平台无关。
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import typer
import yaml

from src.adapters.fixture_adapter import FixtureAdapter
from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter
from src.adapters.parsers import normalize_creator_ref
from src.core.account_ranker import profile_accounts, rank_accounts
from src.core.aggregator import aggregate
from src.core.exporter import export_all
from src.core.keyword_expander import expand_keywords
from src.core.note_selector import select_typical_notes
from src.core.ports import ResearchAdapter
from src.core.time_window import filter_notes
from src.core.watchlist import build_watchlist
from src.models import Account, FetchResult, WatchAccount
from src.pipelines.logging_setup import _compact_run_id, configure_logging, log_result

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _build_adapter(config: dict) -> ResearchAdapter:
    provider = config.get("provider", "fixture")
    comments_path = config.get("comments", {}).get("fixture_path")
    creator_path = config.get("creator_fixture_path")
    search_cfg = config.get("search", {})
    if provider == "mediacrawler":
        mc_dir = config["mediacrawler_dir"]
        if Path(mc_dir).exists():
            mc = config.get("mediacrawler", {})
            return MediaCrawlerAdapter(
                mc_dir,
                out_dir=mc.get("out_dir", "data/raw"),
                login_type=mc.get("login_type", "qrcode"),
                cookies=mc.get("cookies", ""),
                sort_type=search_cfg.get("sort", ""),
                max_notes=search_cfg.get("limit", 20),
            )
        # creator_fixture_path is fixture-provider only; MediaCrawler mode must use
        # MediaCrawler creator output. The unavailable-dir fallback keeps that boundary explicit.
        # 路径 (a)：MediaCrawler 目录不可用 → 启动降级 fixture
        return FixtureAdapter(config["fixture_path"], comments_path=comments_path)
    return FixtureAdapter(
        config["fixture_path"], comments_path=comments_path, creator_path=creator_path
    )


def _apply_time_window(
    results: list[FetchResult], window_days: int, collected_at: str
) -> list[FetchResult]:
    if window_days <= 0:
        return results

    filtered_results: list[FetchResult] = []
    kept = 0
    out_of_window = 0
    missing_time = 0

    for result in results:
        if not result.ok:
            filtered_results.append(result)
            continue

        notes, stats = filter_notes(result.notes, window_days, collected_at)
        kept += stats.kept
        out_of_window += stats.out_of_window
        missing_time += stats.missing_time
        filtered_results.append(result.model_copy(update={"notes": notes}))

    typer.echo(
        f"time_window: kept={kept} out_of_window={out_of_window} missing_time={missing_time}"
    )
    return filtered_results


def _backfill_watchlist_nicknames(
    watchlist: list[WatchAccount], accounts: list[Account]
) -> list[WatchAccount]:
    nickname_by_id = {a.account_id: a.nickname for a in accounts if a.nickname}
    return [
        wa.model_copy(update={"nickname": nickname_by_id[wa.account_id]})
        if not wa.nickname and wa.account_id in nickname_by_id
        else wa
        for wa in watchlist
    ]


def run_research(config_path: str, *, verbose: bool = False) -> dict[str, str]:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    collected_at = _now_iso()
    adapter = _build_adapter(config)
    configure_logging(
        config.get("logging", {}),
        verbose=verbose,
        run_id=collected_at,
        provider=adapter.provider_name,
    )

    keywords = expand_keywords(config.get("keywords", []), config.get("synonyms"))
    logger.info("关键词扩展：%d 个（%s）", len(keywords), " / ".join(keywords))
    search_cfg = config.get("search", {})
    pages = search_cfg.get("pages", 1)
    limit = search_cfg.get("limit", 20)
    window_days = search_cfg.get("window_days", 0)

    results = []
    for kw in keywords:
        for page in range(1, pages + 1):
            t0 = perf_counter()
            result = adapter.search(kw, page, limit, collected_at)
            dt = perf_counter() - t0
            log_result(logger, result)
            logger.info(
                "搜索「%s」第 %d 页：笔记 %d · 账号 %d · %.1fs",
                kw,
                page,
                len(result.notes),
                len(result.accounts),
                dt,
            )
            results.append(result)

    results = _apply_time_window(results, window_days, collected_at)
    notes, accounts = aggregate(results)
    logger.info("聚合去重：笔记 %d · 账号 %d", len(notes), len(accounts))
    ranking_weights = config.get("ranking", {}).get("weights")
    ranks = rank_accounts(accounts, notes, ranking_weights)
    logger.info("账号打分：%d 个", len(ranks))

    watchlist = None
    creator_notes = None
    account_profiles = None
    topic_feed_notes = None
    topic_feed_stats = None
    watchlist_cfg = config.get("watchlist")
    if watchlist_cfg is not None:
        try:
            manual_ids = [normalize_creator_ref(ref) for ref in watchlist_cfg.get("manual", [])]
        except ValueError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e

        auto_top_n = watchlist_cfg.get("auto_top_n", 0)
        max_total = watchlist_cfg.get("max_total", 10)
        watchlist = build_watchlist(ranks, manual_ids, auto_top_n, max_total)
        auto_count = sum(1 for account in watchlist if account.source == "auto")
        logger.info(
            "watchlist：manual %d · auto %d/%d · total %d",
            len(manual_ids),
            auto_count,
            auto_top_n,
            len(watchlist),
        )

        creator_notes = []
        if watchlist:
            creator_cfg = config.get("creator", {})
            try:
                creator_result = adapter.fetch_creator_notes(
                    [account.account_id for account in watchlist],
                    creator_cfg.get("notes_per_account", 10),
                    collected_at,
                )
            except NotImplementedError:
                logger.warning("创作者笔记采集：跳过（数据源不支持）")
            else:
                log_result(logger, creator_result)
                creator_notes = creator_result.notes
                watchlist = _backfill_watchlist_nicknames(watchlist, creator_result.accounts)
                logger.info("创作者笔记：采到 %d 条", len(creator_notes))
        else:
            logger.info("watchlist：为空，跳过创作者笔记采集")
        account_profiles = profile_accounts(
            watchlist,
            creator_notes,
            keywords,
            window_days,
            collected_at,
            ranking_weights,
        )
        topic_feed_notes, topic_feed_stats = filter_notes(creator_notes, window_days, collected_at)
        logger.info(
            "topic_feed：kept=%d out_of_window=%d missing_time=%d",
            topic_feed_stats.kept,
            topic_feed_stats.out_of_window,
            topic_feed_stats.missing_time,
        )

    selection_cfg = config.get("selection", {})
    top = selection_cfg.get("top_notes_per_account", 2)
    typical = select_typical_notes(
        notes,
        top,
        half_life_days=selection_cfg.get("half_life_days", 0),
        now_iso=collected_at,
    )
    logger.info("选出典型笔记：%d 条", len(typical))

    comments_cfg = config.get("comments", {})
    comments = []
    if comments_cfg.get("enabled"):
        # 进行时提示：评论段是单个子进程调用，期间无逐条输出，预告避免误判卡死
        logger.info("评论：开始采集 %d 条典型笔记的评论（单并发批量，约需数分钟）", len(typical))
        try:
            comment_result = adapter.fetch_comments(
                typical, comments_cfg.get("limit", 10), collected_at
            )
        except NotImplementedError:
            comment_result = None
            logger.info("评论：跳过（数据源不支持）")
        if comment_result and comment_result.ok:
            log_result(logger, comment_result)
            comments = comment_result.comments
            logger.info("评论：采到 %d 条", len(comments))
        elif comment_result:
            log_result(logger, comment_result)
            logger.info("评论：采到 0 条")
    else:
        logger.info("评论：跳过（未启用）")

    # 按运行归档：每次导出独立时间戳目录（与 run 日志同一时间戳，可互相对上），不覆盖历史
    out_base = Path(config.get("export", {}).get("out_dir", "data/exports"))
    run_dir = out_base / _compact_run_id(collected_at)
    paths = export_all(
        run_dir,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=typical,
        comments=comments,
        comment_top_k=comments_cfg.get("report_top_k", 3),
        watchlist=watchlist,
        creator_notes=creator_notes,
        account_profiles=account_profiles,
        topic_feed=topic_feed_notes,
        topic_feed_stats=topic_feed_stats,
        topic_feed_window_days=window_days,
    )
    _update_latest_link(out_base, run_dir)
    logger.info("✓ 导出 %d 个文件 → %s", len(paths), run_dir)
    return paths


def _update_latest_link(base: Path, run_dir: Path) -> None:
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


@app.command()
def main(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 控制台日志"),
):
    paths = run_research(config, verbose=verbose)
    for name, p in paths.items():
        typer.echo(f"{name}: {p}")


if __name__ == "__main__":
    app()
