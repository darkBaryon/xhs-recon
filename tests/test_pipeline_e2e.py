import csv
from pathlib import Path

import yaml

from src.pipelines.run_research import run_research


def test_pipeline_end_to_end(tmp_path):
    cfg = {
        "provider": "fixture",
        "fixture_path": "tests/fixtures/search_contents_sample.jsonl",
        "keywords": ["留学辅导"],
        "search": {"pages": 1, "limit": 20},
        "ranking": {"weights": {"note_count": 10, "keyword_hit": 5, "interaction": 0.01}},
        "selection": {"top_notes_per_account": 2},
        "export": {"out_dir": str(tmp_path)},
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    paths = run_research(str(cfg_path))

    for key in ["accounts", "notes", "account_rank", "typical_notes", "report_input"]:
        assert Path(paths[key]).exists()

    with open(tmp_path / "accounts.csv", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) - 1 == 5  # sample 5 个不同作者 → 去重后 5 个账号

    md = (tmp_path / "report_input.md").read_text(encoding="utf-8")
    assert md.strip() != ""
