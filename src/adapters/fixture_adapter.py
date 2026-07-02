"""期1 适配器：读本地 fixture JSONL，经 parsers 出 FetchResult。零网络。"""

import logging
from pathlib import Path

from src.adapters.parsers import parse_comments_jsonl_lines, parse_jsonl_lines
from src.core.ports import ResearchAdapter
from src.models import FetchResult, TypicalNote

logger = logging.getLogger(__name__)


class FixtureAdapter(ResearchAdapter):
    provider_name = "fixture"

    def __init__(self, fixture_path: str, comments_path: str | None = None):
        self._path = Path(fixture_path)
        self._comments_path = Path(comments_path) if comments_path else None

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
