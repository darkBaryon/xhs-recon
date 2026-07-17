from dataclasses import dataclass
from typing import Protocol

from ...domain.content import (
    AccountCollectionResult,
    AccountTarget,
    ContentReference,
    CreatorFeedResult,
    SearchCollectionResult,
)


@dataclass(frozen=True, slots=True)
class SearchCollectionRequest:
    keyword: str
    collected_at: str
    pages: int = 1
    limit: int = 20


class SearchCollector(Protocol):
    platform_id: str

    def collect_search(self, request: SearchCollectionRequest) -> SearchCollectionResult: ...

    def collect_search_batch(
        self, requests: tuple[SearchCollectionRequest, ...]
    ) -> tuple[SearchCollectionResult, ...]: ...


@dataclass(frozen=True, slots=True)
class CreatorFeedCollectionRequest:
    targets: tuple[AccountTarget, ...]
    collected_at: str
    max_notes: int | None = None


class CreatorFeedCollector(Protocol):
    platform_id: str

    def collect_creator_feeds(self, request: CreatorFeedCollectionRequest) -> CreatorFeedResult: ...


@dataclass(frozen=True, slots=True)
class ContentDetailCollectionRequest:
    contents: tuple[ContentReference, ...]
    collected_at: str
    fetch_comments: bool = False


class ContentDetailCollector(Protocol):
    platform_id: str

    def collect_content_details(
        self, request: ContentDetailCollectionRequest
    ) -> AccountCollectionResult: ...
