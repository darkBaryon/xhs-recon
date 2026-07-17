from typing import Protocol

from ...domain.content import (
    AccountCollectionResult,
    AccountTarget,
    ContentReference,
    SearchCollectionResult,
)


class AccountRepository(Protocol):
    def save(self, result: AccountCollectionResult) -> None: ...

    def close(self) -> None: ...


class SearchRepository(Protocol):
    def save_search(self, result: SearchCollectionResult) -> None: ...

    def close(self) -> None: ...


class WatchlistRepository(Protocol):
    def due_targets(
        self,
        targets: tuple[AccountTarget, ...],
        collected_at: str,
        refresh_days: int,
        batch_size: int,
    ) -> tuple[AccountTarget, ...]: ...

    def known_content_ids(self, target: AccountTarget) -> frozenset[str]: ...

    def content_ids_needing_comments(
        self,
        target: AccountTarget,
        collected_at: str,
        refresh_days: int,
    ) -> frozenset[str]: ...

    def save_watchlist(
        self, result: AccountCollectionResult, *, comments_fetched: bool
    ) -> None: ...

    def close(self) -> None: ...


class BackfillRepository(Protocol):
    def contents_missing_media(self, limit: int) -> tuple[ContentReference, ...]: ...

    def save_backfill(self, result: AccountCollectionResult) -> None: ...

    def close(self) -> None: ...
