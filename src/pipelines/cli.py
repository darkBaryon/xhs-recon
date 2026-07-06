"""子命令路由：search（广角）/ track（盯人，评论随笔记抓回）/ research（全流程）。

路由层只做「读配置 → 建 adapter → 调阶段函数 → 导出」；业务全在 core 与
run_research 的阶段函数里。命令间靠 data/exports/latest/ 的文件契约衔接：
search 建当次运行目录；track 紧接 search 时补全写回、独立跑时自建新目录逐次归档
（熟悉领域后只跑 track 即可，不必先 search）。评论随 creator 笔记一同抓回，无单独命令。

运行时编排（时间源/adapter/归档软链）走 runtime 模块，与 run_research 共享；
monkeypatch pin（如 "src.pipelines.runtime.now_iso"）对全部命令一处生效。
"""

import logging
import random
import time
from pathlib import Path

import typer
import yaml

import src.pipelines.run_research as run_research
from src.core.exporter import export_all, export_watch_side
from src.core.note_selector import select_typical_notes
from src.models import AccountRank
from src.pipelines import runtime
from src.pipelines.artifacts import load_ranks_csv, resolve_latest_run_dir
from src.pipelines.config import RunConfig
from web.bundle import build_bundle
from web.feed import build_feed

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
    """全流程（search + track 组合；评论随 track 的 creator 笔记抓回）。"""
    _echo_paths(run_research.run_research(config, verbose=verbose))


@app.command()
def search(config: str = _CONFIG_OPT, verbose: bool = _VERBOSE_OPT):
    """广角：关键词搜索 → 聚合打分 → 选典型 → 导出搜索侧文件（不采评论，建新运行目录）。"""
    cfg, collected_at, adapter, store = runtime.prepare(config, verbose=verbose)
    notes, accounts, ranks = run_research._search_stage(cfg, adapter, collected_at, store)

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
def track(
    config: str = _CONFIG_OPT,
    verbose: bool = _VERBOSE_OPT,
    loop: bool = typer.Option(
        False, "--loop", help="连续巡逻：一批接一批直到没有到期账号（批间随机休眠）"
    ),
    pause_min: int = typer.Option(300, "--pause-min", help="批间休眠下限（秒）"),
    pause_max: int = typer.Option(600, "--pause-max", help="批间休眠上限（秒）"),
):
    """长焦盯人：watchlist 合成 → creator 拉取 → 写运行目录。

    独立可跑：紧接 search 时补全写回同一目录；否则自建新目录逐次归档
    （auto 名额沿用上次搜索榜单，缺则仅 manual）。--loop 时每批一个运行目录，
    批间随机休眠，直到 watchlist 全部账号都在刷新期内自动收工。
    """
    batch_no = 0
    while True:
        batch_no += 1
        cfg, collected_at, adapter, store = runtime.prepare(config, verbose=verbose)

        if cfg.watchlist is None:
            logger.warning("配置无 watchlist 段，track 无事可做")
            raise typer.Exit(0)

        run_dir, ranks = _resolve_track_target(cfg, collected_at)

        artifacts = run_research._sync_stage(cfg, adapter, collected_at, ranks, store)
        paths = export_watch_side(
            run_dir,
            watchlist=artifacts.watchlist,
            creator_notes=artifacts.creator_notes,
            account_profiles=artifacts.account_profiles,
            creator_profiles=artifacts.creator_profiles,
        )
        logger.info("✓ 写回 %d 个文件 → %s", len(paths), run_dir)
        _echo_paths(paths)

        if not loop:
            return
        batch_size = cfg.creator.batch_size
        if store is None or batch_size <= 0:
            logger.warning(
                "--loop 需要 store.enabled 且 creator.batch_size>0（否则一跑已覆盖全部），结束"
            )
            return
        # 本批实际抓到的非 self 账号（self 每批都跟着抓，不算轮转名额）
        fetched = [wa for wa in (artifacts.watchlist or []) if wa.source != "self"]
        if not fetched:
            logger.info("巡逻结束：第 %d 批已无到期账号（全部在刷新期内）", batch_no)
            return
        if len(fetched) < batch_size:
            # accounts_due 最多返回 batch_size 个，不足说明到期账号已抓完
            logger.info("巡逻结束：第 %d 批收尾 %d 个账号，全部抓完", batch_no, len(fetched))
            return
        pause = random.randint(max(pause_min, 0), max(pause_max, pause_min, 0))
        logger.info(
            "第 %d 批完成（%d 账号），休眠 %d 秒后继续下一批", batch_no, len(fetched), pause
        )
        time.sleep(pause)


# 全量采集后评论随 creator 笔记一同抓回（见 track/research），不再有单独 comments 命令。


@app.command()
def web(config: str = _CONFIG_OPT):
    """把 MySQL 全库装成小红书风格本地站（data/site/，file:// 可开）。"""
    path = build_feed(Path("data/site"))
    typer.echo(f"web: {path}")


@app.command(name="backfill-media")
def backfill_media(
    config: str = _CONFIG_OPT,
    batch: int = typer.Option(30, "--batch", help="每个 detail 会话补几帖"),
    limit: int = typer.Option(0, "--limit", help="最多补几帖（0=全部缺图帖）"),
    verbose: bool = _VERBOSE_OPT,
):
    """补抓缺本地图的老帖（评论不重抓）：详情+图回填 media 库与 image_paths。

    历史成因：搜索侧/早期无图库版本入库的帖被两段式增量当老帖跳过详情。"""
    from urllib.parse import parse_qs, urlparse

    _cfg, _collected_at, adapter, store = runtime.prepare(config, verbose=verbose)
    if store is None or not hasattr(store, "notes_missing_media"):
        typer.echo("需要 store.enabled=true（MySQL）", err=True)
        raise typer.Exit(1)
    if not hasattr(adapter, "fetch_note_details"):
        typer.echo("当前 adapter 不支持详情抓取", err=True)
        raise typer.Exit(1)

    rows = store.notes_missing_media(limit=limit)
    logger.info("补图回填：缺图帖 %d 个，按 %d/批", len(rows), batch)
    filled = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        cards = []
        for r in chunk:
            q = parse_qs(urlparse(r["url"]).query)
            cards.append(
                {
                    "note_id": r["note_id"],
                    "xsec_token": (q.get("xsec_token") or [""])[0],
                    "xsec_source": (q.get("xsec_source") or ["pc_feed"])[0],
                }
            )
        result = adapter.fetch_note_details(cards, runtime.now_iso(), with_comments=False)
        got = [n for n in result.notes if n.image_paths]
        store.upsert_notes(result.notes)
        filled += len(got)
        logger.info(
            "补图批 %d/%d：请求 %d · 回图 %d%s",
            i // batch + 1,
            (len(rows) + batch - 1) // batch,
            len(chunk),
            len(got),
            f"（{result.error}）" if result.error else "",
        )
    logger.info("补图回填完成：%d/%d 帖拿到本地图", filled, len(rows))


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
