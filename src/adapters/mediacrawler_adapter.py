"""期2 适配器：命令行触发 MediaCrawler 采集 → 读回 JSONL → 复用 parsers。

合规（个人自用）：关代理池（--enable_ip_proxy no）、默认单并发（--max_concurrency_num 1）；
CDP 用 MediaCrawler 默认（本机真实浏览器，不伪造身份）。真实采集需 MediaCrawler 的
Playwright 环境与登录态，不进 CI。
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from src.adapters.parsers import (
    parse_comments_jsonl_lines,
    parse_creator_profiles_jsonl_lines,
    parse_jsonl_lines,
)
from src.core.ports import ResearchAdapter
from src.models import Account, Comment, CreatorProfile, FetchResult, Note, TypicalNote

logger = logging.getLogger(__name__)

# adapter 进度事件的消费端类型（pipeline 注入；adapter 不 import 显示层）
ProgressCallback = Callable[[dict], None]

# MediaCrawler creator 会话的进度标记（已在真实 mediacrawler.log 验证格式）：
# 每处理一个账号打一行 "Parse creator URL info: user_id='...'"，
# 每完成一条笔记详情打一行 "Finish get note detail, note_id: ..."
_RE_CREATOR_START = re.compile(r"Parse creator URL info: .*?user_id='([^']*)'")
_RE_SEARCH_KEYWORD_START = re.compile(r"Current search keyword: (.+)")
_RE_SEARCH_PAGE_START = re.compile(r"search Xiaohongshu keyword: (.*), page: (\d+)")
_RE_CAPTCHA = re.compile(r"CAPTCHA appeared, request failed, ([^\n]+)")
_RE_DATA_FETCH_ERROR = re.compile(r"DataFetchError: (.+)")
_RE_NOTE_DETAIL_DONE = re.compile(r"Finish get note detail, note_id")
# 每篇评论抓完后的限速行：detail 会话里评论段是串行大头，用它逐篇推进度
_RE_NOTE_COMMENTS_DONE = re.compile(r"Sleeping for .+ after fetching comments for note")
# store 层每存一条评论打一行：评论段篇内耗时长（子评论翻页），用累计条数证明没卡死
_RE_COMMENT_SAVED = re.compile(r"store\.xhs\.update_xhs_note_comment\]")
_RE_NOTE_DETAIL_FAILED = re.compile(r"Failed to get note detail,\s*(?:Id|note_id):\s*([^,\s]+)")


def _safe_dirname(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "-", s) or "run"


def _summarize_crawler_failure(output: str) -> str:
    captcha_matches = _RE_CAPTCHA.findall(output)
    if captcha_matches:
        return f"触发验证码/风控：{captcha_matches[-1].strip()}"
    if "登录已过期" in output:
        return "登录已过期"
    matches = _RE_DATA_FETCH_ERROR.findall(output)
    if matches:
        return matches[-1].strip()
    return output[-300:]


class MediaCrawlerAdapter(ResearchAdapter):
    provider_name = "mediacrawler"

    # 单会话 creator 超时按账号数缩放的每账号预算（秒）：实测 ~60s/账号(10 篇)，留余量
    _CREATOR_PER_ACCOUNT_SEC = 120
    # 单会话 search 超时按关键词×页缩放；每页 20 条，MC 默认每条详情后 sleep 2s
    _SEARCH_PER_KEYWORD_PAGE_SEC = 120
    # 单会话 comments 超时按笔记数缩放的每笔记预算（秒）：扁平 600s 对 30 篇不够（实测超时）
    _COMMENT_PER_NOTE_SEC = 120
    # 全量采集：creator 抓每篇笔记随带的一级评论上限（二级评论另计）
    _COMMENTS_PER_NOTE_CAP = 30

    def __init__(
        self,
        mediacrawler_dir: str,
        out_dir: str,
        *,
        login_type: str = "qrcode",
        cookies: str = "",
        sort_type: str = "",
        max_notes: int = 20,
        max_concurrency: int = 1,
        sleep_sec: float = 2.0,
        timeout: int = 600,
        download_images: bool = True,
        media_dir: str = "data/media",
        launcher: list[str] | None = None,
    ):
        self.mediacrawler_dir = str(mediacrawler_dir)
        # 绝对路径：MediaCrawler 以自身目录为 cwd 运行，save_data_path 须绝对才能跨 cwd 读回
        self.out_dir = Path(out_dir).resolve()
        self.login_type = login_type
        self.cookies = cookies
        self.sort_type = sort_type
        self.max_notes = max_notes
        # 全量采集：creator 会话下载原图到本地（XHS 图片 URL 带时间签名、几天即 403，
        # 只有爬取当下下载才永久可看）；search 保持轻量不下图
        self.download_images = download_images
        # 持久图片库：MC 下到 raw（临时可清理），采后复制到此（按 note_id 组织、永不自动清理）
        self.media_dir = Path(media_dir).resolve()
        self.max_concurrency = max_concurrency
        self.sleep_sec = sleep_sec
        self.timeout = timeout
        # MediaCrawler 以 uv 管理（有 uv.lock/pyproject）；用其环境跑以带上 Playwright。
        # 可配以免硬依赖 uv（如换成其 .venv 的 python）。
        self.launcher = launcher or ["uv", "run", "python"]
        # 进度事件回调（pipeline 可选注入，见 fetch_creator_notes）；None = 不上报
        self.on_progress: ProgressCallback | None = None

    def _save_path(self, collected_at: str) -> Path:
        # 每次 run 用唯一子目录隔离 MediaCrawler 的同日追加写
        return self.out_dir / _safe_dirname(collected_at)

    def _search_save_path(self, collected_at: str, keyword: str, page: int) -> Path:
        # 每词/页再各自一层子目录：MediaCrawler 按日追加写同名 JSONL，
        # 共享目录会让后词读回前词的累积内容（统计失真 + 空结果被掩蔽）
        digest = hashlib.md5(keyword.encode("utf-8")).hexdigest()[:6]
        slug = re.sub(r"[^\w]+", "-", keyword)[:20] or "kw"
        return self._save_path(collected_at) / f"search-{slug}-p{page}-{digest}"

    def _search_session_save_path(self, collected_at: str) -> Path:
        return self._save_path(collected_at) / "search"

    def _base_command(self, save_path: Path) -> list[str]:
        """三种会话（search/detail/creator）共享的启动与合规 flag。

        --type 及各自的主选择器（--keywords/--specified_id/--creator_id）由调用方拼接。
        合规红线在此集中：关代理池、单并发（构造可配）、按 sleep_sec 间隔请求。
        """
        return [
            *self.launcher,
            "main.py",
            "--platform",
            "xhs",
            "--lt",
            self.login_type,
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(save_path),
            "--enable_ip_proxy",
            "no",
            "--max_concurrency_num",
            str(self.max_concurrency),
            "--crawler_max_sleep_sec",
            str(self.sleep_sec),
        ]

    def _append_cookies(self, cmd: list[str]) -> list[str]:
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        return cmd

    def _build_search_command(
        self, keywords: list[str], start_page: int, pages: int, limit: int, save_path: Path
    ) -> list[str]:
        # MC 的 --keywords 支持逗号分隔；内部在同一个 browser/page 会话里顺序循环。
        # 小红书搜索页固定最多 20 条/页；MediaCrawler 会按 limit 截断详情采集。
        crawler_max_notes = max(limit or self.max_notes, 1) * max(pages, 1)
        cmd = self._base_command(save_path) + [
            "--type",
            "search",
            "--keywords",
            ",".join(keywords),
            "--get_comment",
            "no",
            "--get_sub_comment",
            "no",
            "--crawler_max_notes_count",
            str(crawler_max_notes),
            "--start",
            str(start_page),
        ]
        self._append_cookies(cmd)
        if self.sort_type:
            cmd += ["--sort_type", self.sort_type]
        return cmd

    def _build_command(self, keyword: str, page: int, limit: int, save_path: Path) -> list[str]:
        return self._build_search_command([keyword], page, 1, limit, save_path)

    def _build_comments_command(self, urls: list[str], limit: int, save_path: Path) -> list[str]:
        cmd = self._base_command(save_path) + [
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
        ]
        return self._append_cookies(cmd)

    def _build_creator_command(
        self, account_ids: list[str], limit: int, save_path: Path
    ) -> list[str]:
        # 单会话多账号:--creator_id 接受逗号分隔列表，MC 在一次会话里顺序拉完
        # （省掉逐账号的浏览器启动开销）；单并发与 sleep 间隔来自 _base_command，速率不放大。
        # 全量采集：creator 同会话带回每篇笔记的一级+二级评论（省掉单独 comments 命令）。
        cmd = self._base_command(save_path) + [
            "--type",
            "creator",
            "--creator_id",
            ",".join(account_ids),
            "--get_comment",
            "yes",
            "--get_sub_comment",
            "yes",
            "--max_comments_count_singlenotes",
            str(self._COMMENTS_PER_NOTE_CAP),
            "--crawler_max_notes_count",
            str(limit or self.max_notes),
        ]
        if self.download_images:
            # fork 加的透传 flag（缺省 no）：下载原图到 {save_path}/xhs/images/{note_id}/
            cmd += ["--get_images", "yes"]
        return self._append_cookies(cmd)

    def _session_budget(self, scaled: int) -> int:
        """单会话超时预算：config timeout<=0 → 0（无限制）；否则 max(下限, 按工作量放大)。"""
        return 0 if self.timeout <= 0 else max(self.timeout, scaled)

    def _run_crawler(
        self,
        cmd: list[str],
        timeout: int | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> tuple[int, str]:
        """实跑 MediaCrawler；单测注入此点以避免真实采集。timeout 缺省用构造值。

        流式逐行读（stderr 并入 stdout），每行喂给可选的 on_line（creator 进度解析用）；
        返回值语义与旧版 subprocess.run 一致：(rc, 完整输出)。超时同样抛
        TimeoutExpired 且 e.output 带已读到的部分（抢救已落盘账号的口径不变）。
        """
        budget = self.timeout if timeout is None else timeout
        wait_arg = budget if budget and budget > 0 else None  # <=0 → 不设超时，无限等
        lines: list[str] = []
        with subprocess.Popen(
            cmd,
            cwd=self.mediacrawler_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            # 强制子进程无缓冲：否则 MC 的 stdout 块缓冲，进度事件会攒到进程结束才涌出，
            # 进度条中途收不到、退出时才 snap 到满（短会话尤其明显）
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        ) as p:
            # 读管道放子线程：主线程用 p.wait(timeout) 管超时，读线程永不阻塞超时判定
            # on_line 抛异常必须就地吞掉：读线程一死没人排空管道，子进程写满
            # 缓冲区会被堵住 → 被误判超时 kill；输出也会静默截断
            def _pump() -> None:
                assert p.stdout is not None
                # 用 readline 而非 `for line in p.stdout`：后者迭代器会 readahead 预读一整块，
                # 导致行攒着不吐、进度条中途收不到；readline 来一行吐一行，真流式
                try:
                    for line in iter(p.stdout.readline, ""):
                        lines.append(line)
                        if on_line is not None:
                            try:
                                on_line(line)
                            except Exception:
                                logger.debug("on_line 回调异常（忽略，继续读）", exc_info=True)
                except (ValueError, OSError):
                    # Ctrl-C 等中断时主线程的 Popen 上下文先关了 stdout，阻塞中的
                    # readline 对已关闭文件抛 ValueError——正常收尾，不往终端喷堆栈
                    pass

            reader = threading.Thread(target=_pump, daemon=True)
            reader.start()
            try:
                rc = p.wait(timeout=wait_arg)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                reader.join(timeout=5)
                raise subprocess.TimeoutExpired(cmd, budget, output="".join(lines)) from None
            reader.join(timeout=5)
        return rc, "".join(lines)

    def _read_jsonl(self, save_path: Path, pattern: str) -> list[str]:
        """按 glob 收集 MC 落盘的 JSONL 行（多文件合并，按文件名排序）。"""
        lines: list[str] = []
        for f in sorted(Path(save_path).glob(pattern)):
            lines.extend(f.read_text(encoding="utf-8").splitlines())
        return lines

    def _read_results(
        self, save_path: Path, keyword: str, collected_at: str
    ) -> tuple[list[Note], list[Account]]:
        lines = self._read_jsonl(save_path, "xhs/jsonl/search_contents_*.jsonl")
        return parse_jsonl_lines(
            lines, keyword=keyword, collected_at=collected_at, raw_path=str(save_path)
        )

    def _read_search_results_by_keyword(
        self, save_path: Path, keywords: list[str], collected_at: str
    ) -> dict[str, tuple[list[Note], list[Account]]]:
        notes, accounts = self._read_results(save_path, "", collected_at)
        keyword_set = set(keywords)
        buckets: dict[str, tuple[list[Note], list[Account]]] = {
            keyword: ([], []) for keyword in keywords
        }
        for note, account in zip(notes, accounts, strict=False):
            keyword = note.source_keywords[0] if note.source_keywords else ""
            if keyword not in keyword_set:
                continue
            buckets[keyword][0].append(note)
            buckets[keyword][1].append(account)
        return buckets

    def _read_comments(self, save_path: Path, collected_at: str):
        lines = self._read_jsonl(save_path, "xhs/jsonl/*_comments_*.jsonl")
        return parse_comments_jsonl_lines(lines, collected_at=collected_at)

    def _read_creator_results(
        self, save_path: Path, collected_at: str
    ) -> tuple[list[Note], list[Account]]:
        lines = self._read_jsonl(save_path, "xhs/jsonl/creator_contents_*.jsonl")
        return parse_jsonl_lines(
            lines, keyword="", collected_at=collected_at, raw_path=str(save_path)
        )

    def _promote_images(self, notes: list[Note], save_path: Path) -> None:
        """把 MC 下到 raw 的原图复制到持久 media 库，image_paths 存 media 绝对路径（就地）。

        MC 落图在 {save_path}/xhs/images/{note_id}/<N>.jpg（临时暂存，可清理）；
        复制到 {media_dir}/xhs/{note_id}/<N>.jpg（持久库，按 note_id 去重、永不自动清理）。
        存绝对路径 → 哪个 cwd 都能 open、raw 清了也不受影响。没图的笔记保持 []。
        """
        img_root = save_path / "xhs" / "images"
        if not img_root.is_dir():
            return
        for n in notes:
            src = img_root / n.note_id
            if not src.is_dir():
                continue
            dst = self.media_dir / "xhs" / n.note_id
            dst.mkdir(parents=True, exist_ok=True)
            paths = []
            for f in sorted(p for p in src.iterdir() if p.is_file()):
                target = dst / f.name
                shutil.copy2(f, target)  # 复制而非移动：raw 作全量备份，用户想清再清
                paths.append(str(target.resolve()))
            if paths:
                n.image_paths = paths

    def _read_creator_profiles(self, save_path: Path, collected_at: str):
        # 档案软信号：旧版 fork 无此文件 / 抓取失败 / 罕见 IO 异常 → 空列表，
        # 不计失败不入 error（与同流程 _read_creator_results 的防御对称，代码评审 #1 建议）
        try:
            lines = self._read_jsonl(save_path, "xhs/jsonl/creator_creators_*.jsonl")
        except OSError:
            return []
        return parse_creator_profiles_jsonl_lines(lines, collected_at=collected_at)

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

    def _search_progress_parser(
        self, stats: dict[str, dict[str, int]] | None = None
    ) -> Callable[[str], None]:
        """逐行解析 MC search 会话输出 → 语义事件。"""
        counts = {"keyword": 0, "note": 0}
        current_keyword: str | None = None

        def handle(line: str) -> None:
            nonlocal current_keyword
            m = _RE_SEARCH_KEYWORD_START.search(line)
            if m:
                current_keyword = m.group(1).strip()
                counts["keyword"] += 1
                counts["note"] = 0
                if stats is not None:
                    stats.setdefault(current_keyword, {"processed": 0, "failed": 0})
                self._emit(
                    {
                        "kind": "keyword_start",
                        "index": counts["keyword"],
                        "keyword": current_keyword,
                    }
                )
                return

            m = _RE_SEARCH_PAGE_START.search(line)
            if m:
                self._emit(
                    {
                        "kind": "page_start",
                        "keyword": m.group(1).strip(),
                        "page": int(m.group(2)),
                    }
                )
                return

            if _RE_NOTE_DETAIL_DONE.search(line):
                counts["note"] += 1
                if current_keyword and stats is not None:
                    stats.setdefault(current_keyword, {"processed": 0, "failed": 0})[
                        "processed"
                    ] += 1
                self._emit({"kind": "note", "count": counts["note"]})
                return

            if _RE_NOTE_DETAIL_FAILED.search(line) and current_keyword and stats is not None:
                stats.setdefault(current_keyword, {"processed": 0, "failed": 0})["failed"] += 1

        return handle

    def search_many(
        self, keywords: list[str], pages: int, limit: int, collected_at: str
    ) -> list[FetchResult]:
        """单会话搜索多个关键词；MC 内部顺序处理，不放大并发。"""
        if not keywords:
            return []

        save_path = self._search_session_save_path(collected_at)
        cmd = self._build_search_command(keywords, 1, pages, limit, save_path)
        session_timeout = self._session_budget(
            self._SEARCH_PER_KEYWORD_PAGE_SEC * len(keywords) * max(pages, 1)
        )
        detail_stats: dict[str, dict[str, int]] = {}
        on_line = self._search_progress_parser(detail_stats)

        rc: int | None = None
        out = ""
        run_error: str | None = None
        try:
            rc, out = self._run_crawler(cmd, timeout=session_timeout, on_line=on_line)
            self._write_crawler_log(save_path, out)
            if rc == 0:
                self._emit({"kind": "done"})
        except subprocess.TimeoutExpired as e:
            run_error = f"session timed out after {session_timeout}s"
            out = e.output or ""
            self._write_crawler_log(save_path, f"{run_error}\n{out}")
            logger.warning("MediaCrawler search 会话超时 %ds，抢救已落盘部分", session_timeout)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            run_error = f"run failed: {e}"
            self._write_crawler_log(save_path, run_error)

        if rc not in (0, None):
            logger.warning("MediaCrawler 退出码 %d，完整日志：%s", rc, save_path)

        try:
            buckets = self._read_search_results_by_keyword(save_path, keywords, collected_at)
        except (OSError, ValueError) as e:
            return [
                self._err(
                    keyword,
                    None,
                    collected_at,
                    cmd,
                    f"read results failed: {e}",
                    save_path,
                )
                for keyword in keywords
            ]

        results: list[FetchResult] = []
        for keyword in keywords:
            notes, accounts = buckets[keyword]
            error_parts = []
            if run_error:
                error_parts.append(run_error)
            if rc not in (0, None) and not notes:
                error_parts.append(f"exit {rc}: {out[-300:]}")
            if not notes:
                stats = detail_stats.get(keyword, {})
                failed = stats.get("failed", 0)
                processed = stats.get("processed", 0)
                if failed:
                    error_parts.append(
                        f"detail failed {failed}/{processed or failed} candidates; "
                        "no notes parsed from output"
                    )
                else:
                    error_parts.append("no notes parsed from output")
            results.append(
                FetchResult(
                    provider=self.provider_name,
                    operation="search",
                    collected_at=collected_at,
                    keyword=keyword,
                    page=None,
                    notes=notes,
                    accounts=accounts,
                    raw_path=str(save_path),
                    error="; ".join(error_parts) or None,
                    command=" ".join(cmd),
                )
            )
        return results

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
        # 超时按笔记数缩放：一个会话顺序读 N 篇的评论，扁平 600s 对 30 篇不够（实测超时）
        session_timeout = self._session_budget(self._COMMENT_PER_NOTE_SEC * len(urls))
        on_line = self._comments_progress_parser(len(urls))
        try:
            rc, out = self._run_crawler(cmd, timeout=session_timeout, on_line=on_line)
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

    def _emit(self, event: dict) -> None:
        """进度事件出口：回调异常只记 DEBUG 不拦采集（显示层故障不值一次会话）。"""
        if self.on_progress is None:
            return
        try:
            self.on_progress(event)
        except Exception:
            logger.debug("进度回调异常（忽略）", exc_info=True)

    def _creator_progress_parser(self) -> Callable[[str], None]:
        """逐行解析 MC creator 会话输出 → 语义事件（MC 输出格式是平台知识，留在 adapter）。"""
        counts = {"creator": 0, "note": 0}

        def handle(line: str) -> None:
            m = _RE_CREATOR_START.search(line)
            if m:
                counts["creator"] += 1
                self._emit(
                    {"kind": "creator_start", "index": counts["creator"], "user_id": m.group(1)}
                )
            elif _RE_NOTE_DETAIL_DONE.search(line):
                counts["note"] += 1
                self._emit({"kind": "note", "count": counts["note"]})

        return handle

    def _comments_progress_parser(self, total: int) -> Callable[[str], None]:
        """逐行解析评论 detail 会话输出，按篇往日志写进度（非 TTY 下也可见，不依赖进度条）。

        detail 模式每篇完成打 `Finish get note detail`、失败打 `Failed to get note detail`，
        与 creator 同款信号。这里只做日志（评论段常被 run.sh 管道跑，进度条会被抑制）。
        """
        seen = {"n": 0}

        def handle(line: str) -> None:
            if _RE_NOTE_DETAIL_DONE.search(line):
                seen["n"] += 1
                logger.info("评论：笔记 %d/%d 详情完成", seen["n"], total)
            else:
                m = _RE_NOTE_DETAIL_FAILED.search(line)
                if m:
                    seen["n"] += 1
                    logger.warning("评论：笔记 %d/%d 详情失败（%s）", seen["n"], total, m.group(1))

        return handle

    def fetch_creator_notes(
        self, account_ids: list[str], limit: int, collected_at: str
    ) -> FetchResult:
        # 单会话：全部账号一次子进程，MC 会话内顺序拉完（省 N-1 次浏览器启动）；
        # 合并落盘（一个 save_path），notes/profiles 各行自带 user_id 可区分。
        save_path = self._save_path(collected_at) / "creator"
        cmd = self._build_creator_command(account_ids, limit, save_path)
        # 超时按账号数缩放：一个会话拉 N 账号，固定 600s 对大 watchlist 不够
        session_timeout = self._session_budget(self._CREATOR_PER_ACCOUNT_SEC * len(account_ids))
        t0 = perf_counter()

        on_line = self._creator_progress_parser() if self.on_progress else None
        rc: int | None = None
        out = ""
        run_error: str | None = None
        try:
            rc, out = self._run_crawler(cmd, timeout=session_timeout, on_line=on_line)
            self._write_crawler_log(save_path, out)
            if rc == 0:
                self._emit({"kind": "done"})
        except subprocess.TimeoutExpired as e:
            run_error = f"session timed out after {session_timeout}s"
            out = e.output or ""
            self._write_crawler_log(save_path, f"{run_error}\n{out}")
            logger.warning("MediaCrawler creator 会话超时 %ds，抢救已落盘部分", session_timeout)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            run_error = f"run failed: {e}"
            self._write_crawler_log(save_path, run_error)

        # 无论成功/超时/非零退出：都读已落盘部分——MC 逐条写盘，超时前完成的账号可抢救
        notes: list[Note] = []
        accounts: list[Account] = []
        profiles: list[CreatorProfile] = []
        comments: list[Comment] = []
        try:
            notes, accounts = self._read_creator_results(save_path, collected_at)
            profiles = self._read_creator_profiles(save_path, collected_at)
            # 全量：同会话带回的评论也一并读出（get_comment=yes 落在 *_comments_*.jsonl）
            comments = self._read_comments(save_path, collected_at)
            # 全量：把下载的原图从 raw 提升到持久 media 库，image_paths 存 media 绝对路径
            self._promote_images(notes, save_path)
        except (OSError, ValueError) as e:
            self._write_crawler_log(save_path, f"read creator failed: {e}")
        if rc not in (0, None):
            logger.warning("MediaCrawler 退出码 %d，完整日志：%s", rc, save_path)

        # 失败判定（单会话下无逐账号退出码）：请求的 id 在结果里既无笔记又无档案 = 失败。
        got = {n.account_id for n in notes} | {p.account_id for p in profiles}
        failed_ids = [aid for aid in account_ids if aid not in got]
        logger.debug(
            "creator 单会话：%d 账号 · 笔记 %d · 档案 %d · %.1fs",
            len(account_ids),
            len(notes),
            len(profiles),
            perf_counter() - t0,
        )

        error_parts = []
        if run_error:
            error_parts.append(run_error)
        if rc not in (0, None):
            error_parts.append(f"exit {rc}: {_summarize_crawler_failure(out)}")
        if failed_ids:
            error_parts.append(f"creator fetch failed: {','.join(failed_ids)}")
        error = "; ".join(error_parts) or None
        return FetchResult(
            provider=self.provider_name,
            operation="creator_notes",
            collected_at=collected_at,
            notes=notes,
            accounts=accounts,
            profiles=profiles,
            comments=comments,
            raw_path=str(save_path),
            error=error,
            command=" ".join(cmd),
        )

    # ---- 两段式增量：列表 → 库 diff → 只抓新帖详情 ----
    def _build_list_command(self, account_ids: list[str], save_path: Path) -> list[str]:
        # creator + --list_only：只拉主页 note 列表（id/token/卡片计数），跳详情/评论/图
        cmd = self._base_command(save_path) + [
            "--type",
            "creator",
            "--creator_id",
            ",".join(account_ids),
            "--list_only",
            "yes",
            "--crawler_max_notes_count",
            str(self.max_notes),
        ]
        return self._append_cookies(cmd)

    def _read_note_cards(self, save_path: Path, collected_at: str) -> list[dict]:
        cards = []
        for line in self._read_jsonl(save_path, "xhs/jsonl/*_notelist_*.jsonl"):
            line = line.strip()
            if not line:
                continue
            try:
                cards.append(json.loads(line))
            except ValueError:
                continue  # 坏行跳过，不坏整跑
        return cards

    def list_creator_notes(
        self, account_ids: list[str], collected_at: str
    ) -> tuple[list[dict], list[CreatorProfile]]:
        """列表模式：只拉 note 卡片（id/token/计数）+ 创作者档案，不抓详情。省请求的大头。"""
        save_path = self._save_path(collected_at) / "creator-list"
        cmd = self._build_list_command(account_ids, save_path)
        timeout = self._session_budget(self._CREATOR_PER_ACCOUNT_SEC * len(account_ids))
        try:
            _rc, out = self._run_crawler(cmd, timeout=timeout)
            self._write_crawler_log(save_path, out)
        except subprocess.TimeoutExpired as e:
            self._write_crawler_log(save_path, f"list timed out {timeout}s\n{e.output or ''}")
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            self._write_crawler_log(save_path, f"list run failed: {e}")
        cards: list[dict] = []
        profiles: list[CreatorProfile] = []
        try:
            cards = self._read_note_cards(save_path, collected_at)
            profiles = self._read_creator_profiles(save_path, collected_at)
        except (OSError, ValueError) as e:
            self._write_crawler_log(save_path, f"read list failed: {e}")
        logger.info("列表模式：卡片 %d · 档案 %d", len(cards), len(profiles))
        return cards, profiles

    def _build_detail_command(
        self, urls: list[str], save_path: Path, with_comments: bool = True
    ) -> list[str]:
        cmd = self._base_command(save_path) + [
            "--type",
            "detail",
            "--specified_id",
            ",".join(urls),
            "--get_comment",
            "yes" if with_comments else "no",
            "--get_sub_comment",
            "yes" if with_comments else "no",
            "--max_comments_count_singlenotes",
            str(self._COMMENTS_PER_NOTE_CAP),
        ]
        if self.download_images:
            cmd += ["--get_images", "yes"]
        return self._append_cookies(cmd)

    @staticmethod
    def _card_note_url(card: dict) -> str:
        nid = card.get("note_id", "")
        token = card.get("xsec_token", "")
        source = card.get("xsec_source") or "pc_feed"
        return f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={token}&xsec_source={source}"

    def _detail_progress_parser(self) -> Callable[[str], None]:
        """逐行解析 detail 会话输出：正文完成 emit note，评论完成 emit comments。

        MC 的 detail 模式先并发抓全部正文（Finish 行几秒内全到），再串行逐篇抓
        评论（限速 sleep，占整段大头）——只锚正文会让进度条秒满后长时间挂满格，
        所以两个阶段各自 emit，显示层各画一条。"""
        count = {"note": 0, "comments": 0, "comment_rows": 0}

        def handle(line: str) -> None:
            if _RE_NOTE_DETAIL_DONE.search(line):
                count["note"] += 1
                self._emit({"kind": "note", "count": count["note"]})
            elif _RE_NOTE_COMMENTS_DONE.search(line):
                count["comments"] += 1
                self._emit({"kind": "comments", "count": count["comments"]})
            elif _RE_COMMENT_SAVED.search(line):
                count["comment_rows"] += 1
                self._emit({"kind": "comment_rows", "count": count["comment_rows"]})

        return handle

    def fetch_note_details(
        self, cards: list[dict], collected_at: str, with_comments: bool = True
    ) -> FetchResult:
        """详情模式：对给定卡片（新帖）抓 正文 + 一级/二级评论 + 图片，图提升到 media 库。

        with_comments=False = 只补正文/图（评论段是大头，补图回填用它省时且少打评论接口）。"""
        save_path = self._save_path(collected_at) / "detail"
        urls = [self._card_note_url(c) for c in cards if c.get("note_id")]
        cmd = self._build_detail_command(urls, save_path, with_comments=with_comments)
        timeout = self._session_budget(self._COMMENT_PER_NOTE_SEC * max(len(urls), 1))
        on_line = self._detail_progress_parser() if self.on_progress else None
        run_error: str | None = None
        out = ""
        try:
            _rc, out = self._run_crawler(cmd, timeout=timeout, on_line=on_line)
            self._write_crawler_log(save_path, out)
        except subprocess.TimeoutExpired as e:
            run_error = f"detail timed out after {timeout}s"
            self._write_crawler_log(save_path, f"{run_error}\n{e.output or ''}")
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
            run_error = f"run failed: {e}"
            self._write_crawler_log(save_path, run_error)
        notes: list[Note] = []
        accounts: list[Account] = []
        comments: list[Comment] = []
        try:
            # detail 模式写 detail_contents_*.jsonl（与 creator/search 同格式，同一 parser）
            lines = self._read_jsonl(save_path, "xhs/jsonl/*_contents_*.jsonl")
            notes, accounts = parse_jsonl_lines(
                lines, keyword="", collected_at=collected_at, raw_path=str(save_path)
            )
            comments = self._read_comments(save_path, collected_at)
            self._promote_images(notes, save_path)
        except (OSError, ValueError) as e:
            self._write_crawler_log(save_path, f"read detail failed: {e}")
        return FetchResult(
            provider=self.provider_name,
            operation="note_details",
            collected_at=collected_at,
            notes=notes,
            accounts=accounts,
            comments=comments,
            raw_path=str(save_path),
            error=run_error,
            command=" ".join(cmd),
        )
