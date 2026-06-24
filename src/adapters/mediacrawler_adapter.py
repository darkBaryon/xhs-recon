"""期2 适配器：命令行触发 MediaCrawler 采集 → 读回 JSONL → 复用 parsers。

合规（个人自用）：关代理池（--enable_ip_proxy no）、单并发（--max_concurrency_num 1）；
CDP 用 MediaCrawler 默认（本机真实浏览器，不伪造身份）。真实采集需 MediaCrawler 的
Playwright 环境与登录态，不进 CI。
"""

import re
import subprocess
from pathlib import Path

from src.adapters.parsers import parse_jsonl_lines
from src.core.ports import ResearchAdapter
from src.models import Account, FetchResult, Note


def _safe_dirname(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "-", s) or "run"


class MediaCrawlerAdapter(ResearchAdapter):
    provider_name = "mediacrawler"

    def __init__(
        self,
        mediacrawler_dir: str,
        out_dir: str,
        *,
        login_type: str = "qrcode",
        cookies: str = "",
        max_notes: int = 20,
        timeout: int = 600,
        launcher: list[str] | None = None,
    ):
        self.mediacrawler_dir = str(mediacrawler_dir)
        # 绝对路径：MediaCrawler 以自身目录为 cwd 运行，save_data_path 须绝对才能跨 cwd 读回
        self.out_dir = Path(out_dir).resolve()
        self.login_type = login_type
        self.cookies = cookies
        self.max_notes = max_notes
        self.timeout = timeout
        # MediaCrawler 以 uv 管理（有 uv.lock/pyproject）；用其环境跑以带上 Playwright。
        # 可配以免硬依赖 uv（如换成其 .venv 的 python）。
        self.launcher = launcher or ["uv", "run", "python"]

    def _save_path(self, collected_at: str) -> Path:
        # 每次 run 用唯一子目录隔离 MediaCrawler 的同日追加写
        return self.out_dir / _safe_dirname(collected_at)

    def _build_command(self, keyword: str, page: int, limit: int, save_path: Path) -> list[str]:
        cmd = [
            *self.launcher,
            "main.py",
            "--platform",
            "xhs",
            "--type",
            "search",
            "--keywords",
            keyword,
            "--lt",
            self.login_type,
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(save_path),
            "--enable_ip_proxy",
            "no",
            "--get_comment",
            "no",
            "--get_sub_comment",
            "no",
            "--max_concurrency_num",
            "1",
            "--crawler_max_notes_count",
            str(limit or self.max_notes),
            "--start",
            str(page),
        ]
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        return cmd

    def _run_crawler(self, cmd: list[str]) -> tuple[int, str]:
        """实跑 MediaCrawler；单测注入此点以避免真实采集。"""
        p = subprocess.run(
            cmd,
            cwd=self.mediacrawler_dir,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return p.returncode, (p.stdout + p.stderr)

    def _read_results(
        self, save_path: Path, keyword: str, collected_at: str
    ) -> tuple[list[Note], list[Account]]:
        files = sorted(Path(save_path).glob("xhs/jsonl/search_contents_*.jsonl"))
        lines: list[str] = []
        for f in files:
            lines.extend(f.read_text(encoding="utf-8").splitlines())
        return parse_jsonl_lines(
            lines, keyword=keyword, collected_at=collected_at, raw_path=str(save_path)
        )

    def _err(self, keyword, page, collected_at, cmd, msg, save_path=None) -> FetchResult:
        return FetchResult(
            provider=self.provider_name,
            operation="search",
            collected_at=collected_at,
            keyword=keyword,
            page=page,
            error=msg,
            command=" ".join(cmd),
            raw_path=str(save_path) if save_path else None,
        )

    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> FetchResult:
        save_path = self._save_path(collected_at)
        cmd = self._build_command(keyword, page, limit, save_path)
        try:
            rc, out = self._run_crawler(cmd)
        except (OSError, subprocess.SubprocessError) as e:
            return self._err(keyword, page, collected_at, cmd, f"run failed: {e}")
        if rc != 0:
            return self._err(keyword, page, collected_at, cmd, f"exit {rc}: {out[-300:]}")
        notes, accounts = self._read_results(save_path, keyword, collected_at)
        if not notes:
            return self._err(
                keyword, page, collected_at, cmd, "no notes parsed from output", save_path
            )
        return FetchResult(
            provider=self.provider_name,
            operation="search",
            collected_at=collected_at,
            keyword=keyword,
            page=page,
            notes=notes,
            accounts=accounts,
            raw_path=str(save_path),
            command=" ".join(cmd),
        )
