import logging
import random
import time
from pathlib import Path

import typer

from ..application.account.use_case import AnalyzeAccountsRequest
from ..application.backfill.use_case import BackfillRequest
from ..application.research.use_case import ResearchRequest
from ..application.search.use_case import SearchRequest
from ..application.watchlist.use_case import WatchlistRequest
from ..infrastructure.persistence.mysql.legacy_import import LegacyImporter
from ..infrastructure.persistence.mysql.repository import (
    MySQLResearchRepository,
    connect_existing_database,
)
from . import runtime
from .config import (
    load_account_config,
    load_run_config,
    load_search_config,
    load_watchlist_config,
)
from .container import (
    build_account_use_case,
    build_backfill_use_case,
    build_research_use_case,
    build_search_use_case,
    build_watchlist_use_case,
)

app = typer.Typer(add_completion=False, help="recon 模块化采集分析入口")
logger = logging.getLogger(__name__)


@app.callback()
def main() -> None:
    """多平台采集分析命令组。"""


@app.command()
def account(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志"),
):
    """从长期配置读竞品账号，采集帖子并生成分析。"""
    repository = None
    try:
        loaded = load_account_config(config)
        collected_at = runtime.now_iso()
        use_case, repository = build_account_use_case(loaded, collected_at, verbose=verbose)
        account_cfg = loaded.run.account_analysis
        assert account_cfg is not None
        receipt = use_case.execute(
            AnalyzeAccountsRequest(
                targets=loaded.targets,
                collected_at=collected_at,
                max_notes=account_cfg.max_notes,
                fetch_comments=account_cfg.fetch_comments,
            )
        )
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        if repository is not None:
            repository.close()
    for name, path in receipt.output_paths.items():
        typer.echo(f"{name}: {path}")
    failures = receipt.analysis.collection.failures
    if failures:
        typer.echo(f"警告：{len(failures)} 个采集错误，详见 account_report.md", err=True)


@app.command()
def search(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志"),
):
    """从长期配置读关键词，独立执行搜索、归属保存和分析输出。"""
    repository = None
    try:
        loaded = load_search_config(config)
        collected_at = runtime.now_iso()
        use_case, repository = build_search_use_case(loaded, collected_at, verbose=verbose)
        receipt = use_case.execute(
            SearchRequest(
                keywords=loaded.keywords,
                synonyms=loaded.synonyms,
                collected_at=collected_at,
                pages=loaded.run.search.pages,
                limit=loaded.run.search.limit,
                window_days=loaded.run.search.window_days,
                batch_size=loaded.run.search.batch_size,
                ranking_weights=loaded.run.ranking.weights,
            )
        )
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        if repository is not None:
            repository.close()
    for name, path in receipt.output_paths.items():
        typer.echo(f"{name}: {path}")


@app.command()
def research(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志"),
):
    """组合独立 search + watchlist，并生成稳定四文件 bundle。"""
    repositories = ()
    try:
        search_config = load_search_config(config)
        watchlist_config = load_watchlist_config(config)
        collected_at = runtime.now_iso()
        use_case, repositories = build_research_use_case(
            search_config, watchlist_config, collected_at, verbose=verbose
        )
        run = search_config.run
        watchlist_cfg = run.watchlist
        assert watchlist_cfg is not None
        receipt = use_case.execute(
            ResearchRequest(
                search=SearchRequest(
                    keywords=search_config.keywords,
                    synonyms=search_config.synonyms,
                    collected_at=collected_at,
                    pages=run.search.pages,
                    limit=run.search.limit,
                    window_days=run.search.window_days,
                    batch_size=run.search.batch_size,
                    ranking_weights=run.ranking.weights,
                ),
                manual_targets=watchlist_config.targets,
                auto_top_n=watchlist_cfg.auto_top_n,
                max_total=watchlist_cfg.max_total,
                watchlist_max_notes=run.creator.notes_per_account,
                watchlist_batch_size=run.creator.batch_size,
                watchlist_refresh_days=run.creator.refresh_days,
                watchlist_comments_refresh_days=run.comments.refresh_days,
                fetch_comments=run.comments.enabled,
            )
        )
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        for repository in repositories:
            repository.close()
    for name, path in receipt.output_paths.items():
        typer.echo(f"{name}: {path}")


@app.command()
def watchlist(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志"),
    loop: bool = typer.Option(False, "--loop", help="分批巡逻，直到本轮到期账号抓完"),
    pause_min: int = typer.Option(300, "--pause-min", help="批间休眠下限（秒）"),
    pause_max: int = typer.Option(600, "--pause-max", help="批间休眠上限（秒）"),
):
    """独立检查 YAML watchlist，只采集到期账号的新帖子。"""
    batch_no = 0
    while True:
        repository = None
        try:
            loaded = load_watchlist_config(config)
            collected_at = runtime.now_iso()
            use_case, repository = build_watchlist_use_case(loaded, collected_at, verbose=verbose)
            receipt = use_case.execute(
                WatchlistRequest(
                    targets=loaded.targets,
                    collected_at=collected_at,
                    max_notes=loaded.run.creator.notes_per_account,
                    batch_size=loaded.run.creator.batch_size,
                    refresh_days=loaded.run.creator.refresh_days,
                    comments_refresh_days=loaded.run.comments.refresh_days,
                    fetch_comments=loaded.run.comments.enabled,
                )
            )
        except (OSError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        finally:
            if repository is not None:
                repository.close()
        batch_no += 1
        for name, path in receipt.output_paths.items():
            typer.echo(f"{name}: {path}")
        if not loop:
            return
        batch_size = loaded.run.creator.batch_size
        due_count = len(receipt.analysis.due)
        if not loaded.run.store.enabled or batch_size <= 0:
            logger.warning("--loop 需要 store.enabled=true 且 creator.batch_size>0；本批完成后结束")
            return
        if due_count == 0:
            logger.info("巡逻结束：第 %d 批已无到期账号", batch_no)
            return
        if due_count < batch_size:
            logger.info("巡逻结束：第 %d 批收尾 %d 个账号", batch_no, due_count)
            return
        pause = random.randint(max(pause_min, 0), max(pause_max, pause_min, 0))
        logger.info(
            "第 %d 批完成（%d 个账号），休眠 %d 秒后继续",
            batch_no,
            due_count,
            pause,
        )
        time.sleep(pause)


@app.command(name="migrate-legacy")
def migrate_legacy(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    apply: bool = typer.Option(False, "--apply", help="实际写入；默认只对账不写库"),
):
    """把同库 accounts/notes/comments/profile 幂等导入候选新表。"""
    repository = None
    connection = None
    try:
        run = load_run_config(config)
        if apply:
            repository = MySQLResearchRepository(run.store.database)
            connection = repository.connection
        else:
            # 真正的只读 dry-run：不经过会自动建库、建表和补列的仓储初始化。
            connection = connect_existing_database(run.store.database)
        report = LegacyImporter(connection).run(dry_run=not apply)
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        if repository is not None:
            repository.close()
        elif connection is not None:
            connection.close()
    mode = "已写入" if apply else "DRY-RUN"
    typer.echo(
        f"{mode}: creators={report.creators} contents={report.contents} "
        f"comments={report.comments} keywords={report.keywords} "
        f"media={report.media_assets} placeholder_creators={report.placeholder_creators}"
    )


@app.command()
def web(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    keyword: str | None = typer.Option(None, "--keyword", help="只看指定实际搜索词"),
    out: str = typer.Option("data/recon/site", "--out", help="静态站输出目录"),
):
    """从候选新 schema 生成本地 Web；旧 web 命令在切换前保持不变。"""
    from web.feed import build_recon_feed

    run = load_run_config(config)
    path = build_recon_feed(Path(out), run.store.database, keyword)
    typer.echo(f"web: {path}")


@app.command()
def bundle(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
):
    """返回新 research 最近生成的稳定四文件 bundle。"""
    run = load_run_config(config)
    root = Path(run.export.out_dir) / "research"
    candidates = sorted(root.glob("*.zip"), reverse=True) if root.exists() else []
    if not candidates:
        typer.echo("尚无新 research bundle，请先运行 recon research", err=True)
        raise typer.Exit(1)
    typer.echo(f"bundle: {candidates[0]}")


@app.command(name="backfill-media")
def backfill_media(
    config: str = typer.Option(..., "--config", help="YAML 配置路径"),
    batch: int = typer.Option(30, "--batch", help="每批详情数量"),
    limit: int = typer.Option(0, "--limit", help="最多补抓数量，0=全部"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 日志"),
):
    """从新 schema 查询缺图内容并补抓详情，不读取旧运行目录。"""
    repository = None
    try:
        loaded = load_search_config(config)
        collected_at = runtime.now_iso()
        use_case, repository = build_backfill_use_case(loaded, collected_at, verbose=verbose)
        receipt = use_case.execute(
            BackfillRequest(collected_at=collected_at, batch_size=batch, limit=limit)
        )
    except (OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    finally:
        if repository is not None:
            repository.close()
    typer.echo(
        f"backfill: requested={receipt.requested} saved={receipt.saved} failures={receipt.failures}"
    )


if __name__ == "__main__":
    app()
