import subprocess
from pathlib import Path

from src.adapters.mediacrawler_adapter import MediaCrawlerAdapter

SAMPLE = "tests/fixtures/search_contents_sample.jsonl"


def _adapter(tmp_path, **kw):
    return MediaCrawlerAdapter("/some/mediacrawler", tmp_path, **kw)


def test_build_command_has_compliance_flags(tmp_path):
    cmd = _adapter(tmp_path)._build_command("留学辅导", 1, 20, tmp_path / "run")
    assert cmd[cmd.index("--enable_ip_proxy") + 1] == "no"  # 关代理池
    assert cmd[cmd.index("--max_concurrency_num") + 1] == "1"  # 单并发
    assert cmd[cmd.index("--keywords") + 1] == "留学辅导"
    assert cmd[cmd.index("--type") + 1] == "search"
    assert "ENABLE_CDP" not in " ".join(cmd)  # CDP 用默认，不在命令里


def test_cookies_appended_only_when_set(tmp_path):
    assert "--cookies" not in _adapter(tmp_path)._build_command("k", 1, 20, tmp_path)
    cmd = _adapter(tmp_path, cookies="abc")._build_command("k", 1, 20, tmp_path)
    assert cmd[cmd.index("--cookies") + 1] == "abc"


def test_search_success_reads_and_parses(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    sample = Path(SAMPLE).read_text(encoding="utf-8")

    def fake_run(cmd):
        sp = Path(cmd[cmd.index("--save_data_path") + 1])
        d = sp / "xhs" / "jsonl"
        d.mkdir(parents=True, exist_ok=True)
        (d / "search_contents_2026-06-24.jsonl").write_text(sample, encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(a, "_run_crawler", fake_run)
    r = a.search("留学辅导", 1, 20, "2026-06-24T00:00:00Z")
    assert r.ok
    assert len(r.notes) == 5
    assert r.notes[0].like_count == 10000  # 复用期1 parsers，"1万"→10000


def test_search_nonzero_exit_is_error(tmp_path, monkeypatch):
    a = _adapter(tmp_path)
    monkeypatch.setattr(a, "_run_crawler", lambda cmd: (1, "boom"))
    r = a.search("k", 1, 20, "2026-06-24T00:00:00Z")
    assert not r.ok and "exit 1" in r.error


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


def test_launcher_default_and_configurable(tmp_path):
    assert _adapter(tmp_path)._build_command("k", 1, 20, tmp_path)[:4] == [
        "uv",
        "run",
        "python",
        "main.py",
    ]
    cmd = _adapter(tmp_path, launcher=["python3"])._build_command("k", 1, 20, tmp_path)
    assert cmd[:2] == ["python3", "main.py"]
