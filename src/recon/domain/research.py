from dataclasses import dataclass

from .content import (
    AccountCollectionResult,
    AccountTarget,
    Content,
    Creator,
    SearchCollectionResult,
)
from .identity import EntityId


@dataclass(frozen=True, slots=True)
class AccountSummary:
    creator_id: EntityId
    nickname: str
    content_count: int
    likes: int
    collects: int
    comments: int
    shares: int
    average_interaction: float
    latest_published_at: str


@dataclass(frozen=True, slots=True)
class AccountAnalysis:
    collection: AccountCollectionResult
    summaries: tuple[AccountSummary, ...]


@dataclass(frozen=True, slots=True)
class AccountAnalysisReceipt:
    analysis: AccountAnalysis
    output_paths: dict[str, str]


@dataclass(frozen=True, slots=True)
class CreatorRank:
    creator_id: EntityId
    nickname: str
    content_count: int
    keyword_count: int
    average_interaction: float
    score: float


@dataclass(frozen=True, slots=True)
class SearchAnalysis:
    keywords: tuple[str, ...]
    collections: tuple[SearchCollectionResult, ...]
    creators: tuple[Creator, ...]
    contents: tuple[Content, ...]
    ranks: tuple[CreatorRank, ...]
    window_days: int = 0


@dataclass(frozen=True, slots=True)
class SearchReceipt:
    analysis: SearchAnalysis
    output_paths: dict[str, str]


@dataclass(frozen=True, slots=True)
class WatchlistAnalysis:
    requested: tuple[AccountTarget, ...]
    due: tuple[EntityId, ...]
    collections: tuple[AccountCollectionResult, ...]


@dataclass(frozen=True, slots=True)
class WatchlistReceipt:
    analysis: WatchlistAnalysis
    output_paths: dict[str, str]


@dataclass(frozen=True, slots=True)
class ResearchAnalysis:
    search: SearchAnalysis
    watchlist: WatchlistAnalysis
    manual_count: int
    auto_count: int


@dataclass(frozen=True, slots=True)
class ResearchReceipt:
    analysis: ResearchAnalysis
    output_paths: dict[str, str]
