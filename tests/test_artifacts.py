"""artifacts 文件契约读回：往返一致（含空 note_ids）、缺文件/缺列/悬空 latest 报错。"""

import pytest

from src.core.exporter import export_all
from src.models import AccountRank, TypicalNote
from src.pipelines.artifacts import (
    _split_pipe,
    load_ranks_csv,
    load_typical_csv,
    resolve_latest_run_dir,
)


def _rank(account_id="a1", note_ids=None) -> AccountRank:
    return AccountRank(
        account_id=account_id,
        nickname="昵称",
        relevant_note_count=2,
        keyword_hit_count=1,
        avg_interaction=3.5,
        account_score=25.04,
        note_ids=note_ids if note_ids is not None else ["n1", "n2"],
    )


def _typical(note_id="n1") -> TypicalNote:
    return TypicalNote(
        account_id="a1",
        note_id=note_id,
        title="标题",
        url="https://example.com/n1",
        note_score=12.0,
        selection_reason="top by interaction",
    )


def _export(tmp_path, ranks, typical):
    return export_all(tmp_path, accounts=[], notes=[], ranks=ranks, typical_notes=typical)


def test_split_pipe_empty_is_empty_list():
    assert _split_pipe("") == []
    assert _split_pipe("a|b") == ["a", "b"]


def test_ranks_roundtrip(tmp_path):
    ranks = [_rank(), _rank(account_id="a2", note_ids=[])]
    paths = _export(tmp_path, ranks, [])
    loaded = load_ranks_csv(paths["account_rank"])
    assert loaded == ranks  # 含空 note_ids 往返仍为 []（评审 #1 阻塞2 锁定）


def test_typical_roundtrip(tmp_path):
    typical = [_typical(), _typical(note_id="n2")]
    paths = _export(tmp_path, [], typical)
    assert load_typical_csv(paths["typical_notes"]) == typical


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        load_ranks_csv(tmp_path / "no.csv")


def test_load_missing_column_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("account_id,nickname\na1,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少列"):
        load_ranks_csv(bad)


def test_resolve_latest_missing_raises(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        resolve_latest_run_dir(tmp_path)


def test_resolve_latest_dangling_symlink_raises(tmp_path):
    (tmp_path / "latest").symlink_to(tmp_path / "gone", target_is_directory=True)
    with pytest.raises(ValueError, match="不存在|有效"):
        resolve_latest_run_dir(tmp_path)


def test_resolve_latest_returns_real_dir(tmp_path):
    run = tmp_path / "20260703T000000"
    run.mkdir()
    (tmp_path / "latest").symlink_to(run.name, target_is_directory=True)
    assert resolve_latest_run_dir(tmp_path) == run.resolve()


def test_resolve_latest_pointing_to_file_raises(tmp_path):
    # latest 存在但指向的是文件而非目录（代码评审 #1 建议2：非目录分支补覆盖）
    target = tmp_path / "not-a-dir.txt"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "latest").symlink_to(target.name)
    with pytest.raises(ValueError, match="有效运行目录"):
        resolve_latest_run_dir(tmp_path)
