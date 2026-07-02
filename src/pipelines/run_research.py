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
from src.pipelines.logging_setup import configure_logging, log_result

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _build_adapter(config: dict) -> ResearchAdapter:
    provider = config.get("provider", "fixture")
    comments_path = config.get("comments", {}).get("fixture_path")
    if provider == "mediacrawler":
        mc_dir = config["mediacrawler_dir"]
        if Path(mc_dir).exists():
            mc = config.get("mediacrawler", {})
            return MediaCrawlerAdapter(
                mc_dir,
                out_dir=mc.get("out_dir", "data/raw"),
                login_type=mc.get("login_type", "qrcode"),
                cookies=mc.get("cookies", ""),
                max_notes=config.get("search", {}).get("limit", 20),
            )
        # 路径 (a)：MediaCrawler 目录不可用 → 启动降级 fixture
        return FixtureAdapter(config["fixture_path"], comments_path=comments_path)
    return FixtureAdapter(config["fixture_path"], comments_path=comments_path)


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
    logger.info("keywords expanded: %d -> %s", len(keywords), keywords)
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
                "search kw=%s p%d: %d notes %d accounts in %.1fs",
                kw,
                page,
                len(result.notes),
                len(result.accounts),
                dt,
            )
            results.append(result)

    notes, accounts = aggregate(results)
    logger.info("aggregate: %d notes %d accounts", len(notes), len(accounts))
    ranks = rank_accounts(accounts, notes, config.get("ranking", {}).get("weights"))
    logger.info("rank: %d accounts", len(ranks))
    top = config.get("selection", {}).get("top_notes_per_account", 2)
    typical = select_typical_notes(notes, top)
    logger.info("select typical: %d notes", len(typical))

    comments_cfg = config.get("comments", {})
    comments = []
    if comments_cfg.get("enabled"):
        try:
            comment_result = adapter.fetch_comments(
                typical, comments_cfg.get("limit", 10), collected_at
            )
        except NotImplementedError:
            comment_result = None
            logger.info("comments skipped: not implemented")
        if comment_result and comment_result.ok:
            log_result(logger, comment_result)
            comments = comment_result.comments
            logger.info("comments: %d", len(comments))
        elif comment_result:
            log_result(logger, comment_result)
            logger.info("comments: 0")
    else:
        logger.info("comments skipped: disabled")

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
    logger.info("export: %d files", len(paths))
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
