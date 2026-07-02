"""管线编排：读 config → 注入 adapter → 关键词扩展 → 搜索 → 聚合 → 打分 → 选典型 → 导出。

typer CLI；adapter 由 config 决定（期1 仅 fixture），core 各步平台无关。
"""

from datetime import datetime, timezone
from pathlib import Path

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

app = typer.Typer(add_completion=False)


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


def run_research(config_path: str) -> dict[str, str]:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    collected_at = _now_iso()
    adapter = _build_adapter(config)

    keywords = expand_keywords(config.get("keywords", []), config.get("synonyms"))
    search_cfg = config.get("search", {})
    pages = search_cfg.get("pages", 1)
    limit = search_cfg.get("limit", 20)

    results = []
    for kw in keywords:
        for page in range(1, pages + 1):
            results.append(adapter.search(kw, page, limit, collected_at))

    notes, accounts = aggregate(results)
    ranks = rank_accounts(accounts, notes, config.get("ranking", {}).get("weights"))
    top = config.get("selection", {}).get("top_notes_per_account", 2)
    typical = select_typical_notes(notes, top)

    comments_cfg = config.get("comments", {})
    comments = []
    if comments_cfg.get("enabled"):
        try:
            comment_result = adapter.fetch_comments(
                typical, comments_cfg.get("limit", 10), collected_at
            )
        except NotImplementedError:
            comment_result = None
        if comment_result and comment_result.ok:
            comments = comment_result.comments

    out_dir = config.get("export", {}).get("out_dir", "data/exports")
    return export_all(
        out_dir,
        accounts=accounts,
        notes=notes,
        ranks=ranks,
        typical_notes=typical,
        comments=comments,
        comment_top_k=comments_cfg.get("report_top_k", 3),
    )


@app.command()
def main(config: str = typer.Option(..., "--config", help="YAML 配置路径")):
    paths = run_research(config)
    for name, p in paths.items():
        typer.echo(f"{name}: {p}")


if __name__ == "__main__":
    app()
