"""期1 适配器：读本地 fixture JSONL，经 parsers 出 FetchResult。零网络。"""

from pathlib import Path

from src.adapters.parsers import parse_jsonl_lines
from src.core.ports import ResearchAdapter
from src.models import FetchResult


class FixtureAdapter(ResearchAdapter):
    provider_name = "fixture"

    def __init__(self, fixture_path: str):
        self._path = Path(fixture_path)

    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> FetchResult:
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
