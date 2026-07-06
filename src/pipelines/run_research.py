"""管线编排：读 config → 注入 adapter → 关键词扩展 → 搜索 → 聚合 → 打分 → 选典型 → 导出。

typer CLI；adapter 由 config 决定（期1 仅 fixture），core 各步平台无关。
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import typer
from pydantic import BaseModel

from src.adapters.parsers import normalize_creator_ref
from src.core.account_ranker import profile_accounts, rank_accounts
from src.core.aggregator import aggregate
from src.core.exporter import export_all
from src.core.keyword_expander import expand_keywords
from src.core.note_selector import select_typical_notes
from src.core.ports import ResearchAdapter
from src.core.store import Store
from src.core.time_window import filter_notes
from src.core.watchlist import build_watchlist
from src.models import (
    Account,
    AccountRank,
    Comment,
    CreatorProfile,
    FetchResult,
    Note,
    TypicalNote,
    WatchAccount,
)
from src.pipelines import progress, runtime
from src.pipelines.config import RunConfig
from src.pipelines.logging_setup import log_result

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)


@contextmanager
def _attach_progress(adapter: ResearchAdapter, on_progress) -> Iterator[None]:
    """采集期间把进度回调注入 adapter（支持 on_progress 属性者），退出时复位。

    on_progress=None（非 TTY）或 adapter 不支持进度 → 不注入；无论如何退出时都复位
    （若 adapter 有该属性），保证不把回调泄漏给下一段采集。
    """
    if on_progress is not None and hasattr(adapter, "on_progress"):
        adapter.on_progress = on_progress
    try:
        yield
    finally:
        if hasattr(adapter, "on_progress"):
            adapter.on_progress = None


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


def _manual_watch_account(entry) -> tuple[str, str, bool]:
    """归一化一条 manual 条目 →（account_id, nickname, is_self）。

    dict 条目可带 `self: true` 标记为「本方账号」，导出时 source 记为 self。
    """
    if isinstance(entry, str):
        return normalize_creator_ref(entry), "", False
    if isinstance(entry, dict):
        ref = entry.get("account_id") or entry.get("id") or entry.get("url") or entry.get("ref")
        if not ref:
            raise ValueError(f"watchlist.manual 条目缺少 account_id/id/url/ref：{entry}")
        nickname = str(entry.get("nickname") or entry.get("name") or "").strip()
        is_self = bool(entry.get("self") or entry.get("owner"))
        return normalize_creator_ref(str(ref)), nickname, is_self
    raise ValueError(f"invalid creator ref: {entry}")


class SyncArtifacts(BaseModel):
    """watchlist 同步段产物（组装层私有载体，不进 models.py）。"""

    watchlist: list[WatchAccount] | None = None
    creator_notes: list[Note] | None = None
    account_profiles: list[AccountRank] | None = None
    creator_profiles: list[CreatorProfile] | None = None


def _search_stage(
    config: RunConfig, adapter: ResearchAdapter, collected_at: str, store: Store | None = None
) -> tuple[list[Note], list[Account], list[AccountRank]]:
    """搜索段：关键词扩展 → 搜索采集 → 时间窗过滤 → 聚合去重 → 账号打分。

    store 非空时把聚合后的笔记/账号 upsert 进库（新增/刷新，幂等）。"""
    keywords = expand_keywords(config.keywords, config.synonyms)
    logger.info("关键词扩展：%d 个（%s）", len(keywords), " / ".join(keywords))
    pages = config.search.pages
    limit = config.search.limit
    window_days = config.search.window_days

    results = []
    search_many = getattr(adapter, "search_many", None)
    if callable(search_many):
        notes_per_keyword = max(limit or 20, 1) * max(pages, 1)
        t0 = perf_counter()
        with progress.search_progress(len(keywords), notes_per_keyword) as on_progress:
            with _attach_progress(adapter, on_progress):
                results = search_many(keywords, pages, limit, collected_at)
        dt = perf_counter() - t0
        for result in results:
            log_result(logger, result)
            logger.info(
                "搜索「%s」：详情成功 %d/%d · 账号 %d",
                result.keyword,
                len(result.notes),
                notes_per_keyword,
                len(result.accounts),
            )
        logger.info("搜索单会话：%d 个关键词 · %.1fs", len(keywords), dt)
    else:
        with progress.stage_bar("搜索", total=len(keywords) * pages) as bar:
            for kw in keywords:
                for page in range(1, pages + 1):
                    bar.describe(f"搜索「{kw}」")
                    t0 = perf_counter()
                    result = adapter.search(kw, page, limit, collected_at)
                    dt = perf_counter() - t0
                    bar.advance()
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
    if store is not None:
        store.upsert_accounts(accounts)
        store.upsert_notes(notes)
        logger.info("入库：账号 %d · 笔记 %d（新增/刷新）", len(accounts), len(notes))
    ranks = rank_accounts(accounts, notes, config.ranking.weights)
    logger.info("账号打分：%d 个", len(ranks))
    return notes, accounts, ranks


def _sync_stage(
    config: RunConfig,
    adapter: ResearchAdapter,
    collected_at: str,
    ranks: list[AccountRank],
    store: Store | None = None,
) -> SyncArtifacts:
    """watchlist 同步段：合成 → creator 拉取 → 专业度分项。

    store 非空时把 creator 笔记/档案 upsert 进库，并标记 watchlist 账号 creator_fetched_at。"""
    watchlist_cfg = config.watchlist
    if watchlist_cfg is None:
        return SyncArtifacts()

    try:
        manual_accounts = [_manual_watch_account(entry) for entry in watchlist_cfg.manual]
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    manual_ids = [account_id for account_id, _, _ in manual_accounts]
    manual_nicknames = {
        account_id: nickname for account_id, nickname, _ in manual_accounts if nickname
    }
    self_ids = {account_id for account_id, _, is_self in manual_accounts if is_self}

    auto_top_n = watchlist_cfg.auto_top_n
    max_total = watchlist_cfg.max_total
    watchlist = build_watchlist(
        ranks,
        manual_ids,
        auto_top_n,
        max_total,
        manual_nicknames=manual_nicknames,
        self_ids=self_ids,
    )
    auto_count = sum(1 for account in watchlist if account.source == "auto")
    self_count = sum(1 for account in watchlist if account.source == "self")
    logger.info(
        "watchlist：self %d · manual %d · auto %d/%d · total %d",
        self_count,
        len(manual_ids) - self_count,
        auto_count,
        auto_top_n,
        len(watchlist),
    )

    creator_notes: list[Note] = []
    creator_profiles: list[CreatorProfile] = []
    if watchlist:
        notes_per_account = config.creator.notes_per_account
        # 进度显示：adapter 支持进度事件（有 on_progress 属性，如 MediaCrawler）才注入
        # 回调；非 TTY 时 creator_progress 直接给 None，adapter 零回调开销
        names = {wa.account_id: wa.nickname or wa.account_id for wa in watchlist}
        try:
            with progress.creator_progress(
                len(watchlist),
                names,
                notes_per_creator=notes_per_account,
            ) as on_progress:
                with _attach_progress(adapter, on_progress):
                    creator_result = adapter.fetch_creator_notes(
                        [account.account_id for account in watchlist],
                        notes_per_account,
                        collected_at,
                    )
        except NotImplementedError:
            logger.warning("创作者笔记采集：跳过（数据源不支持）")
        else:
            log_result(logger, creator_result)
            creator_notes = creator_result.notes
            creator_profiles = creator_result.profiles
            watchlist = _backfill_watchlist_nicknames(watchlist, creator_result.accounts)
            logger.info("创作者笔记：采到 %d 条", len(creator_notes))
            logger.info("创作者档案：%d 份", len(creator_profiles))
            if store is not None:
                store.upsert_accounts(creator_result.accounts)
                store.upsert_notes(creator_notes)
                store.upsert_profiles(creator_profiles)
                # 标记「本次拉过主页」——即使某账号 0 篇也标，稳态下靠去重不会重复入库
                store.mark_creator_fetched([wa.account_id for wa in watchlist], collected_at)
                logger.info(
                    "入库：creator 笔记 %d · 档案 %d", len(creator_notes), len(creator_profiles)
                )
    else:
        logger.info("watchlist：为空，跳过创作者笔记采集")

    keywords = expand_keywords(config.keywords, config.synonyms)
    window_days = config.search.window_days
    account_profiles = profile_accounts(
        watchlist,
        creator_notes,
        keywords,
        window_days,
        collected_at,
        config.ranking.weights,
    )
    return SyncArtifacts(
        watchlist=watchlist,
        creator_notes=creator_notes,
        account_profiles=account_profiles,
        creator_profiles=creator_profiles,
    )


def _comments_stage(
    config: RunConfig,
    adapter: ResearchAdapter,
    typical: list[TypicalNote],
    collected_at: str,
    store: Store | None = None,
) -> list[Comment]:
    """评论段：对典型笔记批量采一级评论（可关）。

    store 非空时先增量过滤——只保留「从没抓过评论 / 超 refresh_days」的目标，
    抓到评论后 upsert 入库并标记 comments_fetched_at（省下已抓笔记的重复详情请求）。"""
    comments_cfg = config.comments
    comments: list[Comment] = []
    if comments_cfg.enabled:
        # 增量：库里已抓过评论（且未过期）的典型笔记直接跳过，是本重构省请求的大头
        if store is not None:
            before = len(typical)
            typical = store.notes_needing_comments(typical, comments_cfg.refresh_days, collected_at)
            skipped = before - len(typical)
            if skipped:
                logger.info("评论增量：%d 条已抓过跳过，仅抓 %d 条新的", skipped, len(typical))
            if not typical:
                logger.info("评论增量：无新笔记需抓评论，跳过")
                return []
        # 批量上限：典型笔记随账号数线性膨胀（实测 119 条单命令必超时），按分数截前 N
        max_notes = comments_cfg.max_notes
        targets = typical
        if max_notes and len(typical) > max_notes:
            targets = sorted(typical, key=lambda t: t.note_score, reverse=True)[:max_notes]
            logger.info(
                "评论：典型笔记 %d 条超上限，按分数取前 %d 条（comments.max_notes）",
                len(typical),
                max_notes,
            )
        # 进行时提示：单个子进程批量采，adapter 会按篇往日志写「N/总 完成」进度
        logger.info("评论：开始采集 %d 条典型笔记（单并发批量，逐篇进度见日志）", len(targets))
        try:
            with progress.spinner(f"评论采集：{len(targets)} 条典型笔记…"):
                comment_result = adapter.fetch_comments(targets, comments_cfg.limit, collected_at)
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
        if store is not None and comment_result is not None:
            # 抓成功（含抓到 0 条）就入库并标记；仅在 adapter 不支持（None）时不标，留待重试
            store.upsert_comments(comments)
            store.mark_comments_fetched([t.note_id for t in targets], collected_at)
            logger.info("入库：评论 %d 条 · 标记 %d 篇已抓", len(comments), len(targets))
    else:
        logger.info("评论：跳过（未启用）")
    return comments


def run_research(config_path: str, *, verbose: bool = False) -> dict[str, str]:
    config, collected_at, adapter, store = runtime.prepare(config_path, verbose=verbose)

    notes, accounts, ranks = _search_stage(config, adapter, collected_at, store)
    sync = _sync_stage(config, adapter, collected_at, ranks, store)

    typical = select_typical_notes(
        notes,
        config.selection.top_notes_per_account,
        half_life_days=config.selection.half_life_days,
        now_iso=collected_at,
    )
    logger.info("选出典型笔记：%d 条", len(typical))

    comments = _comments_stage(config, adapter, typical, collected_at, store)

    # 按运行归档：每次导出独立时间戳目录（与 run 日志同一时间戳，可互相对上），不覆盖历史
    out_base = Path(config.export.out_dir)
    run_dir = out_base / runtime.compact_run_id(collected_at)
    paths = export_all(
        run_dir,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=typical,
        comments=comments,
        comment_top_k=config.comments.report_top_k,
        watchlist=sync.watchlist,
        creator_notes=sync.creator_notes,
        account_profiles=sync.account_profiles,
        creator_profiles=sync.creator_profiles,
    )
    runtime.update_latest_link(out_base, run_dir)
    logger.info("✓ 导出 %d 个文件 → %s", len(paths), run_dir)
    return paths


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
