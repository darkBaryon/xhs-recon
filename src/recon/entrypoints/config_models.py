"""新入口的 YAML 配置模型；保持现有长期配置字段与默认值。"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SearchConfig(BaseModel):
    pages: int = 1
    limit: int = 20
    sort: str = ""
    window_days: int = 0
    batch_size: int = 0


class RankingConfig(BaseModel):
    weights: dict[str, float] | None = None


class WatchlistConfig(BaseModel):
    auto_top_n: int = 0
    max_total: int = 10
    manual: list[Any] = []


class CreatorConfig(BaseModel):
    notes_per_account: int = 10
    batch_size: int = 0
    refresh_days: int = 0


class AccountAnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: list[Any] = []
    max_notes: int | None = Field(default=None, gt=0)
    incremental: bool = False
    fetch_comments: bool = False
    download_images: bool | None = None


class SelectionConfig(BaseModel):
    top_notes_per_account: int = 2
    half_life_days: int = 0


class CommentsConfig(BaseModel):
    enabled: bool = False
    limit: int = 10
    report_top_k: int = 3
    max_notes: int = 30
    refresh_days: int = 0
    fixture_path: str | None = None


class MediaCrawlerConfig(BaseModel):
    login_type: str = "qrcode"
    cookies: str = ""
    out_dir: str = "data/raw"
    timeout: int = 600
    max_concurrency: int = 1
    sleep_sec: float = 2.0
    download_images: bool = True
    media_dir: str = "data/media"


class LoggingConfig(BaseModel):
    level: str = "info"
    dir: str = "data/logs"
    file_enabled: bool = True


class ExportConfig(BaseModel):
    out_dir: str = "data/exports"


class StoreConfig(BaseModel):
    enabled: bool = False
    database: str = "xhs_recon"


class RunConfig(BaseModel):
    provider: str = "fixture"
    fixture_path: str | None = None
    mediacrawler_dir: str | None = None
    creator_fixture_path: str | None = None
    creator_profiles_fixture_path: str | None = None
    keywords: list[str] = []
    synonyms: dict[str, list[str]] | None = None
    keywords_file: str | None = None
    watchlist_file: str | None = None
    account_analysis_file: str | None = None
    search: SearchConfig = SearchConfig()
    ranking: RankingConfig = RankingConfig()
    watchlist: WatchlistConfig | None = None
    creator: CreatorConfig = CreatorConfig()
    account_analysis: AccountAnalysisConfig | None = None
    selection: SelectionConfig = SelectionConfig()
    comments: CommentsConfig = CommentsConfig()
    mediacrawler: MediaCrawlerConfig = MediaCrawlerConfig()
    logging: LoggingConfig = LoggingConfig()
    export: ExportConfig = ExportConfig()
    store: StoreConfig = StoreConfig()
