import logging
import subprocess
import sys
from pathlib import Path
from time import perf_counter

import pytest

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
    assert cmd[cmd.index("--crawler_max_sleep_sec") + 1] == "2.0"
    assert cmd[cmd.index("--get_comment") + 1] == "no"  # 禁评论（期2 不碰评论、不存敏感字段）
    assert cmd[cmd.index("--get_sub_comment") + 1] == "no"
    assert cmd[cmd.index("--keywords") + 1] == "留学辅导"
    assert cmd[cmd.index("--type") + 1] == "search"
    assert "ENABLE_CDP" not in " ".join(cmd)  # CDP 用默认，不在命令里


def test_build_search_command_joins_keywords_single_session(tmp_path):
    cmd = _adapter(tmp_path)._build_search_command(
        ["留学辅导", "essay辅导"],
        1,
        2,
        20,
        tmp_path / "search",
    )

    assert cmd[cmd.index("--type") + 1] == "search"
    assert cmd[cmd.index("--keywords") + 1] == "留学辅导,essay辅导"
    assert cmd[cmd.index("--crawler_max_notes_count") + 1] == "40"
    assert cmd[cmd.index("--start") + 1] == "1"
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"


def test_build_command_uses_configured_speed_controls(tmp_path):
    cmd = _adapter(tmp_path, max_concurrency=2, sleep_sec=0.5)._build_command(
        "留学辅导", 1, 12, tmp_path / "run"
    )

    assert cmd[cmd.index("--crawler_max_notes_count") + 1] == "12"
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "2"
    assert cmd[cmd.index("--crawler_max_sleep_sec") + 1] == "0.5"


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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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


def test_fetch_comments_logs_per_note_progress(tmp_path, monkeypatch, caplog):
    # detail 会话每篇的 Finish/Failed 行 → 逐篇进度日志（非 TTY 也可见）
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None, on_line=None):
        assert on_line is not None
        on_line("... Finish get note detail, note_id: n1 ...")
        on_line("... Failed to get note detail, note_id: n2, ...")
        on_line("... Finish get note detail, note_id: n3 ...")
        return 0, ""

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    notes = [_typical(f"n{i}", f"https://xhs.example/n{i}?xsec_token=t{i}") for i in range(3)]
    with caplog.at_level(logging.INFO):
        a.fetch_comments(notes, 10, "2026-06-24T00:00:00Z")
    text = caplog.text
    assert "笔记 1/3 详情完成" in text
    assert "笔记 2/3 详情失败" in text
    assert "笔记 3/3 详情完成" in text


def test_fetch_comments_timeout_scales_with_note_count(tmp_path, monkeypatch):
    a = _adapter(tmp_path)  # 默认 timeout=600
    captured = {}

    def fake_run(cmd, timeout=None, on_line=None):
        captured["timeout"] = timeout
        return 0, ""

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    notes = [_typical(f"n{i}", f"https://xhs.example/n{i}?xsec_token=t{i}") for i in range(10)]
    a.fetch_comments(notes, 10, "2026-06-24T00:00:00Z")
    assert captured["timeout"] == 120 * 10  # _COMMENT_PER_NOTE_SEC × 篇数，> 下限 600


def test_session_timeout_zero_config_means_unbounded(tmp_path, monkeypatch):
    a = _adapter(tmp_path, timeout=0)  # 0 = 去掉超时限制
    captured = {}

    def fake_run(cmd, timeout=None, on_line=None):
        captured["timeout"] = timeout
        return 0, ""

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.fetch_comments([_typical("n1", "https://xhs.example/n1?xsec_token=a")], 10, "2026")
    assert captured["timeout"] == 0  # 会话预算 0 → _run_crawler 内转无限等


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
    monkeypatch.setattr(a, "_run_crawler", lambda cmd, timeout=None, on_line=None: (1, "boom"))

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
    assert cmd[cmd.index("--crawler_max_sleep_sec") + 1] == "2.0"
    # 全量采集：评论随会话抓 + 默认下载原图
    assert cmd[cmd.index("--get_comment") + 1] == "yes"
    assert cmd[cmd.index("--get_sub_comment") + 1] == "yes"
    assert cmd[cmd.index("--get_images") + 1] == "yes"


def test_build_creator_command_can_disable_image_download(tmp_path):
    cmd = _adapter(tmp_path, download_images=False)._build_creator_command(
        ["601d0481000000000101cc46"], 5, tmp_path / "creator"
    )
    assert "--get_images" not in cmd


def test_attach_image_paths_fills_downloaded_files(tmp_path):
    """MC 落图在 {save_path}/xhs/images/{note_id}/ → 回填 note.image_paths；没图保持 []。"""
    from src.models import Note

    def _note(nid):
        return Note(
            note_id=nid,
            account_id="u",
            title="t",
            body="b",
            tags=[],
            url="",
            like_count=0,
            collect_count=0,
            comment_count=0,
            published_at="",
            collected_at="2026",
            source_keywords=[],
            raw_path="",
        )

    save = tmp_path / "creator"
    img_dir = save / "xhs" / "images" / "n1"
    img_dir.mkdir(parents=True)
    (img_dir / "0.jpg").write_bytes(b"x")
    (img_dir / "1.jpg").write_bytes(b"y")

    notes = [_note("n1"), _note("n2")]
    _adapter(tmp_path)._attach_image_paths(notes, save)

    assert [Path(p).name for p in notes[0].image_paths] == ["0.jpg", "1.jpg"]
    assert notes[1].image_paths == []


def test_fetch_creator_notes_single_session_reads_combined_jsonl(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    fixture_lines = Path(CREATOR).read_text(encoding="utf-8").splitlines()
    commands = []

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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
    assert "exit 1" in r.error
    # 整会话失败：两个 id 都算失败
    assert "601d0481000000000101cc46" in r.error
    assert "602d0481000000000101cc47" in r.error
    assert "MediaCrawler 退出码 1" in caplog.text


def test_fetch_creator_notes_nonzero_exit_summarizes_login_expired(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None, on_line=None):
        return 1, "Traceback...\nDataFetchError: 登录已过期\nRetryError..."

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["601d0481000000000101cc46"], 2, "2026")

    assert not r.ok
    assert "exit 1: 登录已过期" in r.error


def test_fetch_creator_notes_nonzero_exit_summarizes_captcha(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None, on_line=None):
        return (
            1,
            "CAPTCHA appeared, request failed, Verifytype: 301, "
            "Verifyuuid: abc, Response: <Response [461 status code 461]>",
        )

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["601d0481000000000101cc46"], 2, "2026")

    assert not r.ok
    assert "exit 1: 触发验证码/风控：Verifytype: 301" in r.error


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

    def fake_run(cmd, timeout=None, on_line=None):
        seen.append(Path(cmd[cmd.index("--save_data_path") + 1]))
        return 1, "boom"  # 直接失败即可，只看命令

    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")
    a.search("essay辅导", 1, 20, "2026-06-24T00:00:00Z")
    assert seen[0] != seen[1]


def test_search_many_single_session_groups_by_source_keyword(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    commands = []
    events = []
    a.on_progress = events.append

    def fake_run(cmd, timeout=None, on_line=None):
        commands.append(cmd)
        assert on_line is not None
        for line in [
            "[XiaoHongShuCrawler.search] Current search keyword: 留学辅导\n",
            "[XiaoHongShuCrawler.search] search Xiaohongshu keyword: 留学辅导, page: 1\n",
            "[get_note_detail_async_task] Finish get note detail, note_id: n1\n",
            "[XiaoHongShuCrawler.search] Current search keyword: essay辅导\n",
            "[XiaoHongShuCrawler.search] search Xiaohongshu keyword: essay辅导, page: 1\n",
            "[get_note_detail_async_task] Finish get note detail, note_id: n2\n",
        ]:
            on_line(line)
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026.jsonl").write_text(
            "\n".join(
                [
                    (
                        '{"note_id":"n1","user_id":"u1","nickname":"机构A",'
                        '"source_keyword":"留学辅导"}'
                    ),
                    (
                        '{"note_id":"n2","user_id":"u2","nickname":"机构B",'
                        '"source_keyword":"essay辅导"}'
                    ),
                ]
            ),
            encoding="utf-8",
        )
        return 0, "search stdout"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    results = a.search_many(["留学辅导", "essay辅导"], 1, 20, "2026")

    assert len(commands) == 1
    assert commands[0][commands[0].index("--keywords") + 1] == "留学辅导,essay辅导"
    assert [r.keyword for r in results] == ["留学辅导", "essay辅导"]
    assert [r.notes[0].note_id for r in results] == ["n1", "n2"]
    assert [r.accounts[0].account_id for r in results] == ["u1", "u2"]
    assert Path(results[0].raw_path, "mediacrawler.log").read_text(encoding="utf-8") == (
        "search stdout"
    )
    assert events == [
        {"kind": "keyword_start", "index": 1, "keyword": "留学辅导"},
        {"kind": "page_start", "keyword": "留学辅导", "page": 1},
        {"kind": "note", "count": 1},
        {"kind": "keyword_start", "index": 2, "keyword": "essay辅导"},
        {"kind": "page_start", "keyword": "essay辅导", "page": 1},
        {"kind": "note", "count": 1},
        {"kind": "done"},
    ]


def test_search_many_nonzero_salvages_completed_keyword(tmp_path, monkeypatch, caplog):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None, on_line=None):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026.jsonl").write_text(
            '{"note_id":"n1","user_id":"u1","source_keyword":"留学辅导"}',
            encoding="utf-8",
        )
        return 1, "detail failed"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    with caplog.at_level(logging.WARNING):
        results = a.search_many(["留学辅导", "essay辅导"], 1, 20, "2026")

    assert results[0].ok
    assert results[0].notes[0].note_id == "n1"
    assert not results[1].ok
    assert "exit 1" in results[1].error
    assert "no notes parsed" in results[1].error
    assert "MediaCrawler 退出码 1" in caplog.text


def test_search_many_empty_keyword_reports_detail_failures(tmp_path, monkeypatch):
    a = _adapter(tmp_path)

    def fake_run(cmd, timeout=None, on_line=None):
        assert on_line is not None
        for line in [
            "[XiaoHongShuCrawler.search] Current search keyword: 论文修改润色\n",
            (
                "[XiaoHongShuCrawler.get_note_detail_async_task] "
                "Failed to get note detail, note_id: n1, api_error: empty response\n"
            ),
            "[get_note_detail_async_task] Finish get note detail, note_id: n1\n",
            ("[XiaoHongShuCrawler.get_note_detail_async_task] Failed to get note detail, Id: n2\n"),
            "[get_note_detail_async_task] Finish get note detail, note_id: n2\n",
        ]:
            on_line(line)
        return 0, "search stdout"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    results = a.search_many(["论文修改润色"], 1, 12, "2026")

    assert not results[0].ok
    assert "detail failed 2/2 candidates" in results[0].error
    assert "no notes parsed from output" in results[0].error


def test_search_corrupt_jsonl_is_error_not_crash(tmp_path, monkeypatch):
    """B2：读回坏行进 error（与 comments/creator 同口径），不穿透崩管线。"""

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
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

    def fake_run(cmd, timeout=None, on_line=None):
        seen_timeout.append(timeout)
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.fetch_creator_notes([f"{i:024d}" for i in range(20)], 10, "2026")
    # 20 账号 × 120s = 2400s，远大于默认 600
    assert seen_timeout[0] == 20 * a._CREATOR_PER_ACCOUNT_SEC


# ---- _run_crawler 流式改造：语义不变 + 逐行回调 ----


def test_run_crawler_streams_lines_and_returns_full_text(tmp_path):
    """(rc, full_text) 语义不变；on_line 按序收到每一行。"""
    script = tmp_path / "chatty.py"
    script.write_text(
        "import sys\nprint('line one')\nprint('line two')\n"
        "sys.stderr.write('err line\\n')\nprint('line three')\n",
        encoding="utf-8",
    )
    a = MediaCrawlerAdapter(str(tmp_path), tmp_path, launcher=[sys.executable])
    seen = []

    rc, out = a._run_crawler([sys.executable, str(script)], on_line=seen.append)

    assert rc == 0
    for expected in ("line one", "line two", "err line", "line three"):
        assert expected in out  # stderr 并入 stdout，完整输出不丢
    stdout_only = [ln.strip() for ln in seen if ln.startswith("line")]
    assert stdout_only == ["line one", "line two", "line three"]  # 行序保持


def test_run_crawler_on_line_exception_does_not_truncate_or_hang(tmp_path):
    """on_line 抛异常：读线程不能死——否则输出截断，且大输出（超管道缓冲
    ~64KB）会堵住子进程、把正常会话误判成超时。"""
    script = tmp_path / "big_output.py"
    script.write_text(
        "for i in range(5000):\n    print(f'line {i:04d} ' + 'x' * 40)\n",
        encoding="utf-8",
    )
    a = MediaCrawlerAdapter(str(tmp_path), tmp_path, launcher=[sys.executable])

    def bad_on_line(line):
        raise RuntimeError("parser broke")

    rc, out = a._run_crawler([sys.executable, str(script)], timeout=30, on_line=bad_on_line)

    assert rc == 0  # 没被误判超时 kill
    assert out.count("line ") == 5000  # 输出一行不丢


def test_run_crawler_timeout_kills_and_keeps_partial_output(tmp_path):
    """超时：kill 子进程，TimeoutExpired.output 带已读到的行（抢救口径不变）。"""
    script = tmp_path / "slow.py"
    script.write_text(
        "import sys, time\nprint('early line', flush=True)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    a = MediaCrawlerAdapter(str(tmp_path), tmp_path, launcher=[sys.executable])
    t0 = perf_counter()

    with pytest.raises(subprocess.TimeoutExpired) as ei:
        a._run_crawler([sys.executable, str(script)], timeout=2)

    assert perf_counter() - t0 < 30  # 确实 kill 了，没等满 60s
    assert "early line" in (ei.value.output or "")


# ---- creator 进度事件：MC 标记行 → 语义事件 ----

MC_CREATOR_LINES = [
    "[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: user_id='aaa'\n",
    "[get_note_detail_async_task] Finish get note detail, note_id: n1\n",
    "[get_note_detail_async_task] Finish get note detail, note_id: n2\n",
    "some unrelated log line\n",
    "[XiaoHongShuCrawler.get_creators_and_notes] Parse creator URL info: user_id='bbb'\n",
    "[get_note_detail_async_task] Finish get note detail, note_id: n3\n",
]


def test_creator_progress_events_from_mc_output(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    events = []
    a.on_progress = events.append

    def fake_run(cmd, timeout=None, on_line=None):
        assert on_line is not None  # 设了回调才建解析器
        for line in MC_CREATOR_LINES:
            on_line(line)
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "creator_contents_2026.jsonl").write_text(
            '{"note_id":"n1","user_id":"aaa"}\n{"note_id":"n3","user_id":"bbb"}',
            encoding="utf-8",
        )
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["aaa", "bbb"], 5, "2026")

    assert r.ok
    assert events == [
        {"kind": "creator_start", "index": 1, "user_id": "aaa"},
        {"kind": "note", "count": 1},
        {"kind": "note", "count": 2},
        {"kind": "creator_start", "index": 2, "user_id": "bbb"},
        {"kind": "note", "count": 3},
        {"kind": "done"},
    ]


def test_creator_no_callback_means_no_parser(tmp_path, monkeypatch):
    """未注入 on_progress（默认）：不建解析器，_run_crawler 收到 on_line=None。"""
    a = _adapter(tmp_path)
    seen_on_line = []

    def fake_run(cmd, timeout=None, on_line=None):
        seen_on_line.append(on_line)
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    a.fetch_creator_notes(["aaa"], 5, "2026")
    assert seen_on_line == [None]


def test_creator_progress_callback_exception_does_not_break_fetch(tmp_path, monkeypatch):
    """回调炸了只记日志：采集结果照常返回。"""
    a = _adapter(tmp_path)

    def bad_callback(event):
        raise RuntimeError("display broke")

    a.on_progress = bad_callback

    def fake_run(cmd, timeout=None, on_line=None):
        for line in MC_CREATOR_LINES:
            on_line(line)
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "creator_contents_2026.jsonl").write_text(
            '{"note_id":"n1","user_id":"aaa"}\n{"note_id":"n2","user_id":"bbb"}',
            encoding="utf-8",
        )
        return 0, "ok"

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.fetch_creator_notes(["aaa", "bbb"], 5, "2026")
    assert r.ok
