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
from src.core.account_ranker import rank_accounts
from src.core.aggregator import aggregate
from src.core.exporter import export_all
from src.core.keyword_expander import expand_keywords
from src.core.note_selector import select_typical_notes
from src.core.ports import ResearchAdapter
from src.core.time_window import filter_notes
from src.models import FetchResult
from src.pipelines.logging_setup import configure_logging, log_result

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _build_adapter(config: dict) -> ResearchAdapter:
    provider = config.get("provider", "fixture")
    comments_path = config.get("comments", {}).get("fixture_path")
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
        # 路径 (a)：MediaCrawler 目录不可用 → 启动降级 fixture
        return FixtureAdapter(config["fixture_path"], comments_path=comments_path)
    return FixtureAdapter(config["fixture_path"], comments_path=comments_path)


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

    results = _apply_time_window(results, search_cfg.get("window_days", 0), collected_at)
    notes, accounts = aggregate(results)
    logger.info("聚合去重：笔记 %d · 账号 %d", len(notes), len(accounts))
    ranks = rank_accounts(accounts, notes, config.get("ranking", {}).get("weights"))
    logger.info("账号打分：%d 个", len(ranks))
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

    out_dir = config.get("export", {}).get("out_dir", "data/exports")
    paths = export_all(
        out_dir,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=typical,
        comments=comments,
        comment_top_k=comments_cfg.get("report_top_k", 3),
    )
    logger.info("✓ 导出 %d 个文件 → %s", len(paths), out_dir)
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
