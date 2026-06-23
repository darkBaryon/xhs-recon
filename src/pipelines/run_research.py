"""管线编排：读 config → 注入 adapter → 关键词扩展 → 搜索 → 聚合 → 打分 → 选典型 → 导出。

typer CLI；adapter 由 config 决定（期1 仅 fixture），core 各步平台无关。
"""

from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml

from src.adapters.fixture_adapter import FixtureAdapter
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
    if provider == "fixture":
        return FixtureAdapter(config["fixture_path"])
    # 期2 在此接 xhs_cli_adapter + 无命令降级
    raise ValueError(f"unknown provider: {provider}")


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

    out_dir = config.get("export", {}).get("out_dir", "data/exports")
    return export_all(out_dir, accounts=accounts, notes=notes, ranks=ranks, typical_notes=typical)


@app.command()
def main(config: str = typer.Option(..., "--config", help="YAML 配置路径")):
    paths = run_research(config)
    for name, p in paths.items():
        typer.echo(f"{name}: {p}")


if __name__ == "__main__":
    app()
