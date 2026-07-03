import logging
import subprocess
import sys
from pathlib import Path

from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter
from src.models import TypicalNote

SAMPLE = "tests/fixtures/search_contents_sample.jsonl"
CREATOR = "tests/fixtures/creator_contents_sample.jsonl"


def _adapter(tmp_path, **kw):
    return MediaCrawlerAdapter("/some/mediacrawler", tmp_path, **kw)


def _typical(note_id: str, url: str) -> TypicalNote:
    return TypicalNote(
        account_id="u",
        note_id=note_id,
        title=f"title {note_id}",
        url=url,
        note_score=1.0,
        selection_reason="test",
    )


def test_build_command_has_compliance_flags(tmp_path):
    cmd = _adapter(tmp_path)._build_command("留学辅导", 1, 20, tmp_path / "run")
    assert cmd[cmd.index("--enable_ip_proxy") + 1] == "no"  # 关代理池
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"  # 单并发
    assert cmd[cmd.index("--get_comment") + 1] == "no"  # 禁评论（期2 不碰评论、不存敏感字段）
    assert cmd[cmd.index("--get_sub_comment") + 1] == "no"
    assert cmd[cmd.index("--keywords") + 1] == "留学辅导"
    assert cmd[cmd.index("--type") + 1] == "search"
    assert "ENABLE_CDP" not in " ".join(cmd)  # CDP 用默认，不在命令里


def test_cookies_appended_only_when_set(tmp_path):
    assert "--cookies" not in _adapter(tmp_path)._build_command("k", 1, 20, tmp_path)
    cmd = _adapter(tmp_path, cookies="abc")._build_command("k", 1, 20, tmp_path)
    assert cmd[cmd.index("--cookies") + 1] == "abc"


def test_sort_type_appended_only_when_set(tmp_path):
    assert "--sort_type" not in _adapter(tmp_path)._build_command("k", 1, 20, tmp_path)
    cmd = _adapter(tmp_path, sort_type="time_descending")._build_command("k", 1, 20, tmp_path)
    assert cmd[cmd.index("--sort_type") + 1] == "time_descending"


def test_search_success_reads_and_parses(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    sample = Path(SAMPLE).read_text(encoding="utf-8")

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026-06-24.jsonl").write_text(sample, encoding="utf-8")
        return 0, "crawler stdout"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")
    assert r.ok
    assert len(r.notes) == 5
    assert r.notes[0].like_count == 10000  # 复用期1 parsers，"1万"→10000
    assert Path(r.raw_path, "mediacrawler.log").read_text(encoding="utf-8") == "crawler stdout"


def test_search_replacement_character_output_still_parses(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    sample = Path(SAMPLE).read_text(encoding="utf-8")

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026-06-24.jsonl").write_text(sample, encoding="utf-8")
        return 0, "stderr already decoded with replacement \ufffd"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")

    assert r.ok
    assert len(r.notes) == 5


def test_run_crawler_replaces_invalid_output_bytes(tmp_path):
    script = tmp_path / "bad_bytes.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(b'ok')\nsys.stderr.buffer.write(b'bad\\xe8bytes')\n",
        encoding="utf-8",
    )
    a = MediaCrawlerAdapter(str(tmp_path), tmp_path, launcher=[sys.executable])

    rc, out = a._run_crawler([sys.executable, str(script)])

    assert rc == 0
    assert "bad\ufffdbytes" in out


def test_search_nonzero_exit_is_error_and_writes_crawler_log(tmp_path, monkeypatch, caplog):
    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", lambda cmd: (1, "boom"))
    with caplog.at_level(logging.WARNING):
        r = a.search("k", 1, 20, "2026-06-24T00:00:00Z")
    assert not r.ok and "exit 1" in r.error
    assert Path(r.raw_path, "mediacrawler.log").read_text(encoding="utf-8") == "boom"
    assert "MediaCrawler 退出码 1" in caplog.text


def test_search_empty_output_is_error(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", lambda cmd: (0, ""))
    r = a.search("k", 1, 20, "2026-06-24T00:00:00Z")
    assert not r.ok and "no notes" in r.error


def test_search_subprocess_exception_is_error(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def boom(cmd):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(a, "_run_crawler", boom)
    r = a.search("k", 1, 20, "2026-06-24T00:00:00Z")
    assert not r.ok and "run failed" in r.error


def test_save_path_is_absolute_for_cross_cwd():
    a = MediaCrawlerAdapter("/some/mediacrawler", "data/raw")
    assert a._save_path("2026-06-24T00:00:00Z").is_absolute()  # 跨 cwd 须绝对


def test_launcher_default_and_configurable(tmp_path):
    assert _adapter(tmp_path)._build_command("k", 1, 20, tmp_path)[:4] == [
        "uv",
        "run",
        "python",
        "main.py",
    ]
    cmd = _adapter(tmp_path, launcher=["python3"])._build_command("k", 1, 20, tmp_path)
    assert cmd[:2] == ["python3", "main.py"]


def test_fetch_comments_builds_detail_command_and_reads_jsonl(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    commands = []

    def fake_run(cmd, timeout=None):
        commands.append(cmd)
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "detail_comments_2026-06-24.jsonl").write_text(
            "\n".join(
                [
                    '{"content":"第一条","note_id":"n1","like_count":"1万","user_id":"u1"}',
                    '{"content":"第二条","note_id":"n2","like_count":"8","nickname":"nick"}',
                ]
            ),
            encoding="utf-8",
        )
        return 0, "comments stdout"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    notes = [
        _typical("n1", "https://xhs.example/n1?xsec_token=a"),
        _typical("n2", "https://xhs.example/n2?xsec_token=b"),
    ]

    r = a.fetch_comments(notes, 7, "2026-06-24T00:00:00Z")

    assert r.ok
    assert [c.body for c in r.comments] == ["第一条", "第二条"]
    assert [c.like_count for c in r.comments] == [10000, 8]
    assert Path(r.raw_path, "mediacrawler.log").read_text(encoding="utf-8") == "comments stdout"
    cmd = commands[0]
    assert cmd[cmd.index("--type") + 1] == "detail"
    assert cmd[cmd.index("--specified_id") + 1] == (
        "https://xhs.example/n1?xsec_token=a,https://xhs.example/n2?xsec_token=b"
    )
    assert cmd[cmd.index("--get_comment") + 1] == "yes"
    assert cmd[cmd.index("--get_sub_comment") + 1] == "no"
    assert cmd[cmd.index("--max_comments_count_singlenotes") + 1] == "7"
    assert cmd[cmd.index("--enable_ip_proxy") + 1] == "no"
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"
    assert cmd[cmd.index("--lt") + 1] == "qrcode"
    assert cmd[cmd.index("--save_data_path") + 1].endswith("2026-06-24T00-00-00Z-comments")


def test_fetch_comments_empty_urls_short_circuits(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def fail_run(cmd):
        raise AssertionError("crawler should not run")

    monkeypatch.setattr(a, "_run_crawler", fail_run)
    r = a.fetch_comments([_typical("n1", "")], 10, "2026")

    assert r.ok
    assert r.comments == []
    assert r.command is None


def test_fetch_comments_nonzero_exit_is_error_and_writes_crawler_log(tmp_path, monkeypatch, caplog):
    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", lambda cmd: (1, "boom"))

    with caplog.at_level(logging.WARNING):
        r = a.fetch_comments([_typical("n1", "https://xhs.example/n1")], 10, "2026")

    assert not r.ok
    assert r.comments == []
    assert "exit 1" in r.error
    assert Path(r.raw_path, "mediacrawler.log").read_text(encoding="utf-8") == "boom"
    assert "MediaCrawler 退出码 1" in caplog.text


def test_build_creator_command_joins_ids_single_session(tmp_path):
    # 单会话：多个 id 逗号拼接进一条命令
    cmd = _adapter(tmp_path)._build_creator_command(
        ["601d0481000000000101cc46", "602d0481000000000101cc47"],
        7,
        tmp_path / "creator",
    )

    assert cmd[cmd.index("--type") + 1] == "creator"
    assert cmd[cmd.index("--creator_id") + 1] == (
        "601d0481000000000101cc46,602d0481000000000101cc47"
    )
    assert cmd[cmd.index("--crawler_max_notes_count") + 1] == "7"
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"  # 单并发不变


def test_fetch_creator_notes_single_session_reads_combined_jsonl(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    fixture_lines = Path(CREATOR).read_text(encoding="utf-8").splitlines()
    commands = []

    def fake_run(cmd, timeout=None):
        commands.append(cmd)
        # 单会话：一次调用写请求账号到同一个 jsonl（MC 只拉 --creator_id 列出的账号）
        wanted = cmd[cmd.index("--creator_id") + 1].split(",")
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        lines = [ln for ln in fixture_lines if any(f'"user_id": "{w}"' in ln for w in wanted)]
        (d / "creator_contents_2026-07-02.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return 0, "creator stdout"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(
        ["601d0481000000000101cc46", "602d0481000000000101cc47"],
        2,
        "2026-07-02T00:00:00Z",
    )

    assert r.ok
    assert r.operation == "creator_notes"
    assert {n.account_id for n in r.notes} == {
        "601d0481000000000101cc46",
        "602d0481000000000101cc47",
    }
    assert len(commands) == 1  # 单会话：只一次子进程
    assert commands[0][commands[0].index("--creator_id") + 1] == (
        "601d0481000000000101cc46,602d0481000000000101cc47"
    )


def test_fetch_creator_notes_missing_account_marked_failed(tmp_path, monkeypatch, caplog):
    # 单会话失败判定：请求的 id 在结果里没出现 = 失败（会话内单账号失败 MC 自身跳过）
    a = _adapter(tmp_path)
    fixture_lines = Path(CREATOR).read_text(encoding="utf-8").splitlines()
    present_id = "601d0481000000000101cc46"
    missing_id = "602d0481000000000101cc47"

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        # 只有 present_id 的行落盘，missing_id 无数据（模拟会话内该账号失败）
        lines = [line for line in fixture_lines if f'"user_id": "{present_id}"' in line]
        (d / "creator_contents_2026-07-02.jsonl").write_text("\n".join(lines), encoding="utf-8")
        return 0, "creator ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes([present_id, missing_id], 2, "2026-07-02T00:00:00Z")

    assert not r.ok
    assert {n.account_id for n in r.notes} == {present_id}
    assert r.error == f"creator fetch failed: {missing_id}"
    assert r.raw_path.endswith("creator")


def test_fetch_creator_notes_nonzero_exit_all_failed(tmp_path, monkeypatch, caplog):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None):
        return 1, "creator session boom"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    with caplog.at_level(logging.WARNING):
        r = a.fetch_creator_notes(
            ["601d0481000000000101cc46", "602d0481000000000101cc47"],
            2,
            "2026-07-02T00:00:00Z",
        )

    assert not r.ok
    assert r.notes == []
    # 整会话失败：两个 id 都算失败
    assert "601d0481000000000101cc46" in r.error
    assert "602d0481000000000101cc47" in r.error
    assert "MediaCrawler 退出码 1" in caplog.text


def test_search_save_path_isolated_per_keyword_and_page(tmp_path):
    """B1：每词/页独立子目录——共享目录会让后词读回前词的累积 JSONL。"""
    a = _adapter(tmp_path)
    ts = "2026-06-24T00:00:00Z"
    p1 = a._search_save_path(ts, "留学辅导", 1)
    p2 = a._search_save_path(ts, "essay辅导", 1)
    p3 = a._search_save_path(ts, "留学辅导", 2)
    assert len({p1, p2, p3}) == 3  # 词间、页间互不共享
    assert p1 == a._search_save_path(ts, "留学辅导", 1)  # 同输入确定性
    assert p1.parent == a._save_path(ts)  # 仍在本次 run 目录之下


def test_search_uses_isolated_save_path_in_command(tmp_path, monkeypatch):
    seen = []

    def fake_run(cmd, timeout=None):
        seen.append(Path(cmd[cmd.index("--save_data_path") + 1]))
        return 1, "boom"  # 直接失败即可，只看命令

    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")
    a.search("essay辅导", 1, 20, "2026-06-24T00:00:00Z")
    assert seen[0] != seen[1]


def test_search_corrupt_jsonl_is_error_not_crash(tmp_path, monkeypatch):
    """B2：读回坏行进 error（与 comments/creator 同口径），不穿透崩管线。"""

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026-06-24.jsonl").write_text("{broken json", encoding="utf-8")
        return 0, "ok"

    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")
    assert not r.ok
    assert "read results failed" in r.error


def test_creator_reads_profiles_when_present(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    profile_line = (
        '{"user_id": "aaaa", "nickname": "机构A", "fans": "2万",'
        ' "tag_list": "{\\"profession\\": \\"教育\\"}"}'
    )

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "creator_contents_2026.jsonl").write_text(
            '{"note_id":"n1","user_id":"aaaa"}', encoding="utf-8"
        )
        (d / "creator_creators_2026.jsonl").write_text(profile_line, encoding="utf-8")
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["aaaa"], 5, "2026")
    assert len(r.profiles) == 1
    assert r.profiles[0].fans == 20000
    assert r.profiles[0].tags == {"profession": "教育"}


def test_creator_missing_profiles_file_degrades_empty(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "creator_contents_2026.jsonl").write_text(
            '{"note_id":"n1","user_id":"aaaa"}', encoding="utf-8"
        )
        return 0, "ok"  # 旧版 fork：无 creator_creators 文件

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["aaaa"], 5, "2026")
    assert r.profiles == []  # 软降级，不入 error
    assert r.ok


def test_fetch_creator_notes_timeout_salvages_partial(tmp_path, monkeypatch):
    """单会话超时：已落盘的账号要抢救回来，只有没跑完的算失败。"""
    import subprocess as sp_mod

    a = _adapter(tmp_path)
    fixture_lines = Path(CREATOR).read_text(encoding="utf-8").splitlines()
    done_id = "601d0481000000000101cc46"
    timeout_id = "602d0481000000000101cc47"

    def fake_run(cmd, timeout=None):
        # 模拟：跑到一半超时——done_id 已落盘，然后抛 TimeoutExpired
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        lines = [ln for ln in fixture_lines if f'"user_id": "{done_id}"' in ln]
        (d / "creator_contents_2026-07-02.jsonl").write_text("\n".join(lines), encoding="utf-8")
        raise sp_mod.TimeoutExpired(cmd, timeout or 600)

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes([done_id, timeout_id], 2, "2026-07-02T00:00:00Z")

    assert {n.account_id for n in r.notes} == {done_id}  # 已落盘账号抢救成功
    assert not r.ok
    assert "timed out" in r.error
    assert timeout_id in r.error  # 没跑完的算失败


def test_creator_session_timeout_scales_with_account_count(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    seen_timeout = []

    def fake_run(cmd, timeout=None):
        seen_timeout.append(timeout)
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.fetch_creator_notes([f"{i:024d}" for i in range(20)], 10, "2026")
    # 20 账号 × 120s = 2400s，远大于默认 600
    assert seen_timeout[0] == 20 * a._CREATOR_PER_ACCOUNT_SEC
