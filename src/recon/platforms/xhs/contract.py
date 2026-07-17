"""XHS 插件与成熟采集适配器之间的窄契约。"""

from typing import Any, Protocol


class LegacyCommentLike(Protocol):
    comment_id: str
    note_id: str
    parent_comment_id: str
    author_id: str
    created_at: str
    body: str


class XhsAdapter(Protocol):
    provider_name: str
    on_progress: Any

    def search(self, keyword: str, page: int, limit: int, collected_at: str) -> Any: ...

    def search_many(
        self, keywords: list[str], pages: int, limit: int, collected_at: str
    ) -> list[Any]: ...

    def fetch_creator_notes(
        self,
        account_ids: list[str],
        limit: int,
        collected_at: str,
        with_comments: bool = True,
    ) -> Any: ...

    def list_creator_notes(
        self, account_ids: list[str], collected_at: str, limit: int | None = None
    ) -> tuple[list[dict], list[Any]]: ...

    def fetch_note_details(
        self, cards: list[dict], collected_at: str, with_comments: bool = True
    ) -> Any: ...
