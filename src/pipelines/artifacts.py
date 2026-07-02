"""跨命令文件契约读回（组装层：latest 目录的既有 CSV → 领域模型）。

只做反序列化，不做计算；core 不感知文件布局。缺文件/缺列一律 ValueError
fail-fast，不静默补默认（配置或数据缺口应显式暴露）。
"""

import csv
from pathlib import Path

from src.models import AccountRank, TypicalNote

PIPE = "|"


def _split_pipe(s: str) -> list[str]:
    # "".split("|") == [''] 的坑：空串必须显式归空列表（方案评审 #1 阻塞2 口径）
    return s.split(PIPE) if s else []


def _read_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        raise ValueError(f"文件不存在：{path}")
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise ValueError(f"{path} 缺少列：{','.join(sorted(missing))}")
        return list(reader)


def load_ranks_csv(path: Path) -> list[AccountRank]:
    required = {
        "account_id",
        "nickname",
        "relevant_note_count",
        "keyword_hit_count",
        "avg_interaction",
        "account_score",
        "note_ids",
    }
    return [
        AccountRank(
            account_id=row["account_id"],
            nickname=row["nickname"],
            relevant_note_count=int(row["relevant_note_count"]),
            keyword_hit_count=int(row["keyword_hit_count"]),
            avg_interaction=float(row["avg_interaction"]),
            account_score=float(row["account_score"]),
            note_ids=_split_pipe(row["note_ids"]),
        )
        for row in _read_rows(Path(path), required)
    ]


def load_typical_csv(path: Path) -> list[TypicalNote]:
    required = {"account_id", "note_id", "title", "url", "note_score", "selection_reason"}
    return [
        TypicalNote(
            account_id=row["account_id"],
            note_id=row["note_id"],
            title=row["title"],
            url=row["url"],
            note_score=float(row["note_score"]),
            selection_reason=row["selection_reason"],
        )
        for row in _read_rows(Path(path), required)
    ]


def resolve_latest_run_dir(out_base: Path) -> Path:
    """latest 软链 → 实际运行目录；缺失/悬空/非目录 → ValueError（提示先跑 search）。"""
    latest = Path(out_base) / "latest"
    if not latest.exists():
        raise ValueError(f"{latest} 不存在——请先跑 search 或 research 产出一次运行")
    resolved = latest.resolve()
    if not resolved.is_dir():
        raise ValueError(f"{latest} 未指向有效运行目录：{resolved}")
    return resolved
