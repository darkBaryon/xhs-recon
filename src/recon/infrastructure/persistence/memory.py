from datetime import datetime, timedelta

from ...domain.content import AccountCollectionResult, SearchCollectionResult


class MemoryAccountRepository:
    def __init__(self) -> None:
        self.saved: list[AccountCollectionResult] = []

    def save(self, result: AccountCollectionResult) -> None:
        self.saved.append(result)

    def close(self) -> None:
        return None


class MemorySearchRepository:
    def __init__(self) -> None:
        self.saved: list[SearchCollectionResult] = []

    def save_search(self, result: SearchCollectionResult) -> None:
        self.saved.append(result)

    def close(self) -> None:
        return None


class MemoryWatchlistRepository:
    def __init__(self) -> None:
        self.known: dict[str, set[str]] = {}
        self.fetched: dict[str, str] = {}
        self.comments_fetched: dict[str, str] = {}

    def due_targets(self, targets, collected_at, refresh_days, batch_size):
        if refresh_days <= 0:
            due = targets
        else:
            cutoff = datetime.fromisoformat(collected_at.replace("Z", "+00:00")) - timedelta(
                days=refresh_days
            )
            due = tuple(
                target
                for target in targets
                if target.id.external_id not in self.fetched
                or datetime.fromisoformat(
                    self.fetched[target.id.external_id].replace("Z", "+00:00")
                )
                < cutoff
            )
        selected = due if batch_size <= 0 else due[:batch_size]
        selected_ids = {target.id for target in selected}
        return tuple(
            target for target in targets if target.id in selected_ids or target.source == "self"
        )

    def known_content_ids(self, target):
        return frozenset(self.known.get(target.id.external_id, set()))

    def content_ids_needing_comments(self, target, collected_at, refresh_days):
        known = self.known.get(target.id.external_id, set())
        cutoff = None
        if refresh_days > 0:
            cutoff = datetime.fromisoformat(collected_at.replace("Z", "+00:00")) - timedelta(
                days=refresh_days
            )
        return frozenset(
            content_id
            for content_id in known
            if content_id not in self.comments_fetched
            or (
                cutoff is not None
                and datetime.fromisoformat(self.comments_fetched[content_id].replace("Z", "+00:00"))
                < cutoff
            )
        )

    def save_watchlist(self, result, *, comments_fetched):
        for content in result.contents:
            self.known.setdefault(content.creator_id.external_id, set()).add(content.id.external_id)
            if comments_fetched:
                self.comments_fetched[content.id.external_id] = result.collected_at
        if not result.failures:
            self.fetched.update(
                {creator.id.external_id: result.collected_at for creator in result.creators}
            )

    def close(self) -> None:
        return None
