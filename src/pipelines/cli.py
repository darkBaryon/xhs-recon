"""子命令路由：search（广角）/ track（盯人）/ comments（评论深读）/ research（全流程）。

路由层只做「读配置 → 建 adapter → 调阶段函数 → 导出」；业务全在 core 与
run_research 的阶段函数里。命令间靠 data/exports/latest/ 的文件契约衔接：
search 建当次运行目录，comments 补全写回该目录；track 紧接 search 时补全写回、
独立跑时自建新目录逐次归档（熟悉领域后只跑 track 即可，不必先 search）。

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
from src.models import AccountRank
from src.pipelines import runtime
from src.pipelines.artifacts import load_ranks_csv, load_typical_csv, resolve_latest_run_dir
from src.pipelines.config import RunConfig
from web.bundle import build_bundle
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
    """全流程（search + track + comments 组合，与旧入口等价）。"""
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


def _latest_ranks(out_base: Path) -> list[AccountRank]:
    """auto 名额榜单：回溯到最近一个含 account_rank.csv 的运行目录。

    track 自建目录只有 watchlist 侧、没有榜单，故不能只看 latest——连续独立 track
    会让 latest 指向无榜单的自建目录，auto 名额被静默清空。按时间戳倒序找回最近一次
    search 的榜单（缺则 []）。
    """
    if not out_base.exists():
        return []
    run_dirs = sorted(
        (p for p in out_base.iterdir() if p.is_dir() and not p.is_symlink()),
        reverse=True,  # compact run_id 字典序即时间序
    )
    for d in run_dirs:
        try:
            return load_ranks_csv(d / "account_rank.csv")
        except ValueError:
            continue
    return []


def _resolve_track_target(config: RunConfig, collected_at: str) -> tuple[Path, list[AccountRank]]:
    """定 track 的写入目录 + auto 名额榜单，解耦「必须先 search」。

    紧接 search（latest 是尚未 track 的纯搜索目录）→ 补全写回该目录；
    否则（latest 已 track 过 / 根本没有）→ 自建新运行目录逐次归档。
    两种情形 auto 名额都回溯到最近一次 search 的榜单（缺则降级为仅 manual）。
    """
    out_base = _out_base(config)
    ranks = _latest_ranks(out_base)

    try:
        latest = resolve_latest_run_dir(out_base)
    except ValueError:
        latest = None

    if latest is not None and not (latest / "watchlist.csv").exists():
        return latest, ranks  # 纯搜索目录 → 补全写回

    run_dir = out_base / runtime.compact_run_id(collected_at)
    run_dir.mkdir(parents=True, exist_ok=True)  # 先建目录，latest 软链才有落点
    runtime.update_latest_link(out_base, run_dir)
    if ranks:
        logger.info("track 自建运行目录，auto 名额沿用最近搜索榜单（%d 账号）", len(ranks))
    else:
        logger.info("track 自建运行目录，无榜单 → 仅 manual")
    return run_dir, ranks


@app.command()
def track(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """长焦盯人：watchlist 合成 → creator 拉取 → 写运行目录。

    独立可跑：紧接 search 时补全写回同一目录；否则自建新目录逐次归档
    （auto 名额沿用上次搜索榜单，缺则仅 manual）。
    """
    cfg, collected_at, adapter = runtime.prepare(config, verbose=verbose)

    if cfg.watchlist is None:
        logger.warning("配置无 watchlist 段，track 无事可做")
        raise typer.Exit(0)

    run_dir, ranks = _resolve_track_target(cfg, collected_at)

    artifacts = run_research._sync_stage(cfg, adapter, collected_at, ranks)
    paths = export_watch_side(
        run_dir,
        watchlist=artifacts.watchlist,
        creator_notes=artifacts.creator_notes,
        account_profiles=artifacts.account_profiles,
        creator_profiles=artifacts.creator_profiles,
    )
    logger.info("✓ 写回 %d 个文件 → %s", len(paths), run_dir)
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


@app.command()
def bundle(config: str = _CONFIG_OPT):
    """把最新一跑打包成研究快照 zip（research/accounts/notes + 自描述 README，供下游程序/LLM）。"""
    raw = runtime.resolve_config_refs(yaml.safe_load(Path(config).read_text(encoding="utf-8")))
    cfg = RunConfig.model_validate(raw)
    run_dir = _latest_run_dir_or_exit(cfg)
    path = build_bundle(run_dir, cfg)
    typer.echo(f"bundle: {path}")


if __name__ == "__main__":
    app()
