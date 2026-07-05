"""子命令路由：search（广角）/ sync（watchlist 同步）/ comments（评论深读）/ research（全流程）。

路由层只做「读配置 → 建 adapter → 调阶段函数 → 导出」；业务全在 core 与
run_research 的阶段函数里。命令间靠 data/exports/latest/ 的文件契约衔接：
search 建当次运行目录，sync/comments 补全写回该目录（Gate 拍板口径）。

运行时编排（时间源/adapter/归档软链）走 runtime 模块，与 run_research 共享；
monkeypatch pin（如 "src.pipelines.runtime.now_iso"）对全部命令一处生效。
"""

import logging
from pathlib import Path

import typer
import yaml

import src.pipelines.run_research as run_research
from src.core.exporter import export_all, export_comments, export_watch_side
from src.core.note_selector import select_typical_notes
from src.pipelines import runtime
from src.pipelines.artifacts import load_ranks_csv, load_typical_csv, resolve_latest_run_dir
from src.pipelines.config import RunConfig
from web.report import build_report

app = typer.Typer(add_completion=False, help="xhs-recon 子命令入口")
logger = logging.getLogger(__name__)

_CONFIG_OPT = typer.Option(..., "--config", help="YAML 配置路径")
_VERBOSE_OPT = typer.Option(False, "--verbose", "-v", help="输出 DEBUG 控制台日志")


def _out_base(config: RunConfig) -> Path:
    return Path(config.export.out_dir)


def _echo_paths(paths: dict[str, str]) -> None:
    for name, p in paths.items():
        typer.echo(f"{name}: {p}")


def _latest_run_dir_or_exit(config: RunConfig) -> Path:
    try:
        return resolve_latest_run_dir(_out_base(config))
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e


@app.command()
def research(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """全流程（search + sync + comments 组合，与旧入口等价）。"""
    _echo_paths(run_research.run_research(config, verbose=verbose))


@app.command()
def search(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """广角：关键词搜索 → 聚合打分 → 选典型 → 导出搜索侧文件（不采评论，建新运行目录）。"""
    cfg, collected_at, adapter = runtime.prepare(config, verbose=verbose)
    notes, accounts, ranks = run_research._search_stage(cfg, adapter, collected_at)

    typical = select_typical_notes(
        notes,
        cfg.selection.top_notes_per_account,
        half_life_days=cfg.selection.half_life_days,
        now_iso=collected_at,
    )
    logger.info("选出典型笔记：%d 条", len(typical))

    out_base = _out_base(cfg)
    run_dir = out_base / runtime.compact_run_id(collected_at)
    paths = export_all(
        run_dir,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=typical,
        comment_top_k=cfg.comments.report_top_k,
    )
    runtime.update_latest_link(out_base, run_dir)
    logger.info("✓ 导出 %d 个文件 → %s", len(paths), run_dir)
    _echo_paths(paths)


@app.command()
def sync(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """长焦：watchlist 合成（auto 名额读最近一跑榜单）→ creator 拉取 → 补全写回该运行目录。"""
    cfg, collected_at, adapter = runtime.prepare(config, verbose=verbose)
    run_dir = _latest_run_dir_or_exit(cfg)

    try:
        ranks = load_ranks_csv(run_dir / "account_rank.csv")
    except ValueError as e:
        logger.warning("榜单不可用（%s）——auto 名额置空，仅 manual 生效", e)
        ranks = []

    if cfg.watchlist is None:
        logger.warning("配置无 watchlist 段，sync 无事可做")
        raise typer.Exit(0)

    artifacts = run_research._sync_stage(cfg, adapter, collected_at, ranks)
    paths = export_watch_side(
        run_dir,
        watchlist=artifacts.watchlist,
        creator_notes=artifacts.creator_notes,
        account_profiles=artifacts.account_profiles,
        topic_feed=artifacts.topic_feed,
        topic_feed_stats=artifacts.topic_feed_stats,
        topic_feed_window_days=cfg.search.window_days,
        creator_profiles=artifacts.creator_profiles,
    )
    logger.info("✓ 补全写回 %d 个文件 → %s", len(paths), run_dir)
    _echo_paths(paths)


@app.command()
def comments(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """深读：对最近一跑的典型笔记补采评论，写回该目录（comments.csv + 重写 report_input.md）。"""
    cfg, collected_at, adapter = runtime.prepare(config, verbose=verbose)
    run_dir = _latest_run_dir_or_exit(cfg)

    try:
        typical = load_typical_csv(run_dir / "typical_notes.csv")
        ranks = load_ranks_csv(run_dir / "account_rank.csv")
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    if not typical:
        typer.echo(f"{run_dir} 无典型笔记可补采——请先跑 search 或 research", err=True)
        raise typer.Exit(1)

    collected = run_research._comments_stage(cfg, adapter, typical, collected_at)
    paths = export_comments(
        run_dir,
        ranks=ranks,
        typical_notes=typical,
        comments=collected,
        comment_top_k=cfg.comments.report_top_k,
    )
    logger.info("✓ 补全写回 %d 个文件 → %s", len(paths), run_dir)
    _echo_paths(paths)


@app.command()
def web(config: str = _CONFIG_OPT):
    """把最新一跑的导出渲染成本地静态站（index.html+style.css+app.js+data.js，file:// 可开）。"""
    cfg = RunConfig.model_validate(yaml.safe_load(Path(config).read_text(encoding="utf-8")))
    run_dir = _latest_run_dir_or_exit(cfg)
    path = build_report(run_dir)
    typer.echo(f"web: {path}")


if __name__ == "__main__":
    app()
