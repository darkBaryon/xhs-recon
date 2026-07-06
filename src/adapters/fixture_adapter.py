"""期1 适配器：读本地 fixture JSONL，经 parsers 出 FetchResult。零网络。"""

import logging
from pathlib import Path

from src.adapters.parsers import (
    parse_comments_jsonl_lines,
    parse_creator_profiles_jsonl_lines,
    parse_jsonl_lines,
)
from src.core.ports import ResearchAdapter
from src.models import FetchResult, TypicalNote

logger = logging.getLogger(__name__)


class FixtureAdapter(ResearchAdapter):
    provider_name = "fixture"

    def __init__(
        self,
        fixture_path: str,
        comments_path: str | None = None,
        creator_path: str | None = None,
        creator_profiles_path: str | None = None,
    ):
        self._path = Path(fixture_path)
        self._comments_path = Path(comments_path) if comments_path else None
        self._creator_path = Path(creator_path) if creator_path else None
        self._creator_profiles_path = Path(creator_profiles_path) if creator_profiles_path else None

    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> FetchResult:
        logger.debug("fixture search path=%s page=%s limit=%s", self._path, page, limit)
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as e:
            return FetchResult(
                provider=self.provider_name,
                operation="search",
                collected_at=collected_at,
                keyword=keyword,
                page=page,
                error=f"read fixture failed: {e}",
            )
        # fixture 一次性返回；page>1 视作翻到空页（模拟分页边界）
        if page and page > 1:
            notes, accounts = [], []
        else:
            notes, accounts = parse_jsonl_lines(
                text.splitlines(),
                keyword=keyword,
                collected_at=collected_at,
                raw_path=str(self._path),
            )
            if limit:
                notes, accounts = notes[:limit], accounts[:limit]
        return FetchResult(
            provider=self.provider_name,
            operation="search",
            collected_at=collected_at,
            keyword=keyword,
            page=page,
            notes=notes,
            accounts=accounts,
            raw_path=str(self._path),
            raw_text=text,
        )

    def fetch_comments(
        self, notes: list[TypicalNote], limit: int, collected_at: str
    ) -> FetchResult:
        if self._comments_path is None:
            raise NotImplementedError
        logger.debug("fixture comments path=%s limit=%s", self._comments_path, limit)
        try:
            text = self._comments_path.read_text(encoding="utf-8")
        except OSError as e:
            return FetchResult(
                provider=self.provider_name,
                operation="fetch_comments",
                collected_at=collected_at,
                error=f"read comments fixture failed: {e}",
            )
        comments = parse_comments_jsonl_lines(text.splitlines(), collected_at=collected_at)
        if limit:
            comments = comments[:limit]
        return FetchResult(
            provider=self.provider_name,
            operation="fetch_comments",
            collected_at=collected_at,
            comments=comments,
            raw_path=str(self._comments_path),
            raw_text=text,
        )

    def fetch_creator_notes(
        self, account_ids: list[str], limit: int, collected_at: str
    ) -> FetchResult:
        if self._creator_path is None:
            raise NotImplementedError
        logger.debug("fixture creator path=%s limit=%s", self._creator_path, limit)
        try:
            text = self._creator_path.read_text(encoding="utf-8")
        except OSError as e:
            return FetchResult(
                provider=self.provider_name,
                operation="creator_notes",
                collected_at=collected_at,
                error=f"read creator fixture failed: {e}",
            )

        all_notes, all_accounts = parse_jsonl_lines(
            text.splitlines(),
            keyword="",
            collected_at=collected_at,
            raw_path=str(self._creator_path),
        )
        wanted = set(account_ids)
        counts: dict[str, int] = {}
        notes = []
        accounts = []
        for note, account in zip(all_notes, all_accounts, strict=True):
            if note.account_id not in wanted:
                continue
            if limit and counts.get(note.account_id, 0) >= limit:
                continue
            counts[note.account_id] = counts.get(note.account_id, 0) + 1
            notes.append(note)
            accounts.append(account)

        profiles = self._read_creator_profiles(wanted, collected_at)
        # 全量采集：评论随 creator 笔记一同带回（真实 adapter 同会话抓，夹具从 comments_path 读）
        comments = []
        if self._comments_path is not None:
            try:
                ctext = self._comments_path.read_text(encoding="utf-8")
                comments = parse_comments_jsonl_lines(ctext.splitlines(), collected_at=collected_at)
            except OSError:
                comments = []
        return FetchResult(
            provider=self.provider_name,
            operation="creator_notes",
            collected_at=collected_at,
            notes=notes,
            accounts=accounts,
            profiles=profiles,
            comments=comments,
            raw_path=str(self._creator_path),
            raw_text=text,
        )

    def _read_creator_profiles(self, wanted: set[str], collected_at: str):
        # 档案是软信号：未配路径或读不到 → 空列表，不报错
        if self._creator_profiles_path is None:
            return []
        try:
            text = self._creator_profiles_path.read_text(encoding="utf-8")
        except OSError:
            return []
        all_profiles = parse_creator_profiles_jsonl_lines(
            text.splitlines(), collected_at=collected_at
        )
        return [p for p in all_profiles if p.account_id in wanted]

    # ---- 两段式增量（离线替身）：从 creator 夹具派生卡片 + 按 id 出详情 ----
    def _creator_notes_for(self, account_ids: list[str], collected_at: str):
        if self._creator_path is None:
            return [], []
        text = self._creator_path.read_text(encoding="utf-8")
        notes, accounts = parse_jsonl_lines(
            text.splitlines(),
            keyword="",
            collected_at=collected_at,
            raw_path=str(self._creator_path),
        )
        wanted = set(account_ids)
        pairs = [(n, a) for n, a in zip(notes, accounts, strict=True) if n.account_id in wanted]
        return [n for n, _ in pairs], [a for _, a in pairs]

    def list_creator_notes(self, account_ids: list[str], collected_at: str):
        """列表模式替身：从 creator 夹具派生卡片（note_id + 计数）+ 档案。"""
        notes, _ = self._creator_notes_for(account_ids, collected_at)
        cards = [
            {
                "note_id": n.note_id,
                "xsec_token": "",
                "xsec_source": "pc_feed",
                "user_id": n.account_id,
                "liked_count": n.like_count,
            }
            for n in notes
        ]
        profiles = self._read_creator_profiles(set(account_ids), collected_at)
        return cards, profiles

    def fetch_note_details(self, cards: list[dict], collected_at: str) -> FetchResult:
        """详情模式替身：对给定卡片 id 出笔记全字段 + 评论（从 comments 夹具）。"""
        want = {c.get("note_id") for c in cards}
        acct_ids = list({c.get("user_id") for c in cards if c.get("user_id")})
        notes, accounts = self._creator_notes_for(acct_ids, collected_at)
        notes = [n for n in notes if n.note_id in want]
        comments = []
        if self._comments_path is not None:
            try:
                comments = parse_comments_jsonl_lines(
                    self._comments_path.read_text(encoding="utf-8").splitlines(),
                    collected_at=collected_at,
                )
            except OSError:
                comments = []
        return FetchResult(
            provider=self.provider_name,
            operation="note_details",
            collected_at=collected_at,
            notes=notes,
            accounts=[a for a in accounts if a.account_id in acct_ids],
            comments=comments,
        )
