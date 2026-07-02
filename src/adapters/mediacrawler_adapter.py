"""期2 适配器：命令行触发 MediaCrawler 采集 → 读回 JSONL → 复用 parsers。

合规（个人自用）：关代理池（--enable_ip_proxy no）、单并发（--max_concurrency_num 1）；
CDP 用 MediaCrawler 默认（本机真实浏览器，不伪造身份）。真实采集需 MediaCrawler 的
Playwright 环境与登录态，不进 CI。
"""

import hashlib
import logging
import re
import subprocess
from pathlib import Path
from time import perf_counter

from src.adapters.parsers import parse_comments_jsonl_lines, parse_jsonl_lines
from src.core.ports import ResearchAdapter
from src.models import Account, FetchResult, Note, TypicalNote

logger = logging.getLogger(__name__)


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
        sort_type: str = "",
        max_notes: int = 20,
        timeout: int = 600,
        launcher: list[str] | None = None,
    ):
        self.mediacrawler_dir = str(mediacrawler_dir)
        # 绝对路径：MediaCrawler 以自身目录为 cwd 运行，save_data_path 须绝对才能跨 cwd 读回
        self.out_dir = Path(out_dir).resolve()
        self.login_type = login_type
        self.cookies = cookies
        self.sort_type = sort_type
        self.max_notes = max_notes
        self.timeout = timeout
        # MediaCrawler 以 uv 管理（有 uv.lock/pyproject）；用其环境跑以带上 Playwright。
        # 可配以免硬依赖 uv（如换成其 .venv 的 python）。
        self.launcher = launcher or ["uv", "run", "python"]

    def _save_path(self, collected_at: str) -> Path:
        # 每次 run 用唯一子目录隔离 MediaCrawler 的同日追加写
        return self.out_dir / _safe_dirname(collected_at)

    def _search_save_path(self, collected_at: str, keyword: str, page: int) -> Path:
        # 每词/页再各自一层子目录：MediaCrawler 按日追加写同名 JSONL，
        # 共享目录会让后词读回前词的累积内容（统计失真 + 空结果被掩蔽）
        digest = hashlib.md5(keyword.encode("utf-8")).hexdigest()[:6]
        slug = re.sub(r"[^\w]+", "-", keyword)[:20] or "kw"
        return self._save_path(collected_at) / f"search-{slug}-p{page}-{digest}"

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
        if self.sort_type:
            cmd += ["--sort_type", self.sort_type]
        return cmd

    def _build_comments_command(self, urls: list[str], limit: int, save_path: Path) -> list[str]:
        cmd = [
            *self.launcher,
            "main.py",
            "--platform",
            "xhs",
            "--type",
            "detail",
            "--specified_id",
            ",".join(urls),
            "--get_comment",
            "yes",
            "--get_sub_comment",
            "no",
            "--max_comments_count_singlenotes",
            str(limit),
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(save_path),
            "--enable_ip_proxy",
            "no",
            "--max_concurrency_num",
            "1",
            "--lt",
            self.login_type,
        ]
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        return cmd

    def _build_creator_command(self, account_id: str, limit: int, save_path: Path) -> list[str]:
        cmd = [
            *self.launcher,
            "main.py",
            "--platform",
            "xhs",
            "--type",
            "creator",
            "--creator_id",
            account_id,
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
            errors="replace",
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

    def _read_comments(self, save_path: Path, collected_at: str):
        files = sorted(Path(save_path).glob("xhs/jsonl/*_comments_*.jsonl"))
        lines: list[str] = []
        for f in files:
            lines.extend(f.read_text(encoding="utf-8").splitlines())
        return parse_comments_jsonl_lines(lines, collected_at=collected_at)

    def _read_creator_results(
        self, save_path: Path, collected_at: str
    ) -> tuple[list[Note], list[Account]]:
        files = sorted(Path(save_path).glob("xhs/jsonl/creator_contents_*.jsonl"))
        lines: list[str] = []
        for f in files:
            lines.extend(f.read_text(encoding="utf-8").splitlines())
        return parse_jsonl_lines(
            lines, keyword="", collected_at=collected_at, raw_path=str(save_path)
        )

    def _write_crawler_log(self, save_path: Path, text: str) -> None:
        try:
            save_path.mkdir(parents=True, exist_ok=True)
            (save_path / "mediacrawler.log").write_text(text, encoding="utf-8")
        except OSError as e:
            logger.warning("crawler log write failed: %s", e)

    def _err(
        self, keyword, page, collected_at, cmd, msg, save_path=None, operation: str = "search"
    ) -> FetchResult:
        return FetchResult(
            provider=self.provider_name,
            operation=operation,
            collected_at=collected_at,
            keyword=keyword,
            page=page,
            error=msg,
            command=" ".join(cmd),
            raw_path=str(save_path) if save_path else None,
        )

    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> FetchResult:
        save_path = self._search_save_path(collected_at, keyword, page)
        cmd = self._build_command(keyword, page, limit, save_path)
        try:
            rc, out = self._run_crawler(cmd)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            return self._err(keyword, page, collected_at, cmd, f"run failed: {e}")
        self._write_crawler_log(save_path, out)
        if rc != 0:
            logger.warning("MediaCrawler 退出码 %d，完整日志：%s", rc, save_path)
            return self._err(
                keyword, page, collected_at, cmd, f"exit {rc}: {out[-300:]}", save_path
            )
        try:
            notes, accounts = self._read_results(save_path, keyword, collected_at)
        except (OSError, ValueError) as e:
            # 与 comments/creator 读回同口径：坏行/读失败进 error，不穿透崩管线
            return self._err(
                keyword, page, collected_at, cmd, f"read results failed: {e}", save_path
            )
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

    def fetch_comments(
        self, notes: list[TypicalNote], limit: int, collected_at: str
    ) -> FetchResult:
        urls = [n.url for n in notes if n.url]
        if not urls:
            return FetchResult(
                provider=self.provider_name,
                operation="fetch_comments",
                collected_at=collected_at,
                comments=[],
            )

        save_path = self._save_path(collected_at + "-comments")
        cmd = self._build_comments_command(urls, limit, save_path)
        try:
            rc, out = self._run_crawler(cmd)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            return self._err(
                None,
                None,
                collected_at,
                cmd,
                f"run failed: {e}",
                save_path,
                operation="fetch_comments",
            )
        self._write_crawler_log(save_path, out)
        if rc != 0:
            logger.warning("MediaCrawler 退出码 %d，完整日志：%s", rc, save_path)
            return self._err(
                None,
                None,
                collected_at,
                cmd,
                f"exit {rc}: {out[-300:]}",
                save_path,
                operation="fetch_comments",
            )
        try:
            comments = self._read_comments(save_path, collected_at)
        except (OSError, ValueError) as e:
            return self._err(
                None,
                None,
                collected_at,
                cmd,
                f"read comments failed: {e}",
                save_path,
                operation="fetch_comments",
            )
        return FetchResult(
            provider=self.provider_name,
            operation="fetch_comments",
            collected_at=collected_at,
            comments=comments,
            raw_path=str(save_path),
            command=" ".join(cmd),
        )

    def fetch_creator_notes(
        self, account_ids: list[str], limit: int, collected_at: str
    ) -> FetchResult:
        save_root = self._save_path(collected_at) / "creator"
        commands: list[str] = []
        failed_ids: list[str] = []
        notes: list[Note] = []
        accounts: list[Account] = []

        for account_id in account_ids:
            save_path = save_root / account_id
            cmd = self._build_creator_command(account_id, limit, save_path)
            commands.append(" ".join(cmd))
            t0 = perf_counter()
            try:
                rc, out = self._run_crawler(cmd)
            except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
                failed_ids.append(account_id)
                self._write_crawler_log(save_path, f"run failed: {e}")
                continue
            self._write_crawler_log(save_path, out)
            if rc != 0:
                logger.warning("MediaCrawler 退出码 %d，完整日志：%s", rc, save_path)
                failed_ids.append(account_id)
                continue
            try:
                account_notes, account_rows = self._read_creator_results(save_path, collected_at)
            except (OSError, ValueError) as e:
                failed_ids.append(account_id)
                self._write_crawler_log(save_path, f"read creator failed: {e}")
                continue
            notes.extend(account_notes)
            accounts.extend(account_rows)
            # 每账号耗时留痕：多账号串行的总时长 = Σ单账号，复盘节奏用
            logger.debug(
                "creator %s：%d 条 · %.1fs", account_id, len(account_notes), perf_counter() - t0
            )

        error = f"creator fetch failed: {','.join(failed_ids)}" if failed_ids else None
        return FetchResult(
            provider=self.provider_name,
            operation="creator_notes",
            collected_at=collected_at,
            notes=notes,
            accounts=accounts,
            raw_path=str(save_root),
            error=error,
            command=" && ".join(commands),
        )
