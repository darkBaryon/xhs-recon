"""运行配置模型（管线私有）：YAML → RunConfig，入口一次性解析，下游全程属性访问。

保留原裸 dict 的容错口径：缺失段走默认值、未知键忽略（pydantic 默认 extra=ignore）。
watchlist 缺省 None（区别于「有段但空」）——sync 段据此判断整段跳过。
资产引用（keywords_file/watchlist_file）在建模前由 runtime.resolve_config_refs
在裸 dict 上解析并回填 keywords/watchlist，故本模型无需消费这两个键。
"""

from typing import Any

from pydantic import BaseModel


class SearchCfg(BaseModel):
    pages: int = 1
    limit: int = 20
    sort: str = ""
    window_days: int = 0


class RankingCfg(BaseModel):
    # None → account_ranker 用其 DEFAULT_WEIGHTS；给了则与默认合并
    weights: dict[str, float] | None = None


class WatchlistCfg(BaseModel):
    auto_top_n: int = 0
    max_total: int = 10
    # 条目可为 str 或 dict（url/id/昵称），归一化在 run_research._manual_watch_account
    manual: list[Any] = []


class CreatorCfg(BaseModel):
    notes_per_account: int = 10


class SelectionCfg(BaseModel):
    top_notes_per_account: int = 2
    half_life_days: int = 0


class CommentsCfg(BaseModel):
    enabled: bool = False
    limit: int = 10
    report_top_k: int = 3
    # 采评论的典型笔记上限（按分数截前 N，防批量超时）
    max_notes: int = 30
    fixture_path: str | None = None


class MediaCrawlerCfg(BaseModel):
    login_type: str = "qrcode"
    cookies: str = ""
    out_dir: str = "data/raw"
    timeout: int = 600
    max_concurrency: int = 1
    sleep_sec: float = 2.0


class LoggingCfg(BaseModel):
    level: str = "info"
    dir: str = "data/logs"
    file_enabled: bool = True


class ExportCfg(BaseModel):
    out_dir: str = "data/exports"


class RunConfig(BaseModel):
    provider: str = "fixture"
    # fixture 与降级用；mediacrawler_dir 仅 mediacrawler provider 用
    fixture_path: str | None = None
    mediacrawler_dir: str | None = None
    creator_fixture_path: str | None = None
    creator_profiles_fixture_path: str | None = None
    keywords: list[str] = []
    synonyms: dict[str, list[str]] | None = None
    # 资产引用键：建模前由 runtime.resolve_config_refs 消费，此处仅为文档存在（extra=ignore 亦可）
    keywords_file: str | None = None
    watchlist_file: str | None = None
    search: SearchCfg = SearchCfg()
    ranking: RankingCfg = RankingCfg()
    # None = 无 watchlist 段 → sync 整段跳过（与「空段」区别）
    watchlist: WatchlistCfg | None = None
    creator: CreatorCfg = CreatorCfg()
    selection: SelectionCfg = SelectionCfg()
    comments: CommentsCfg = CommentsCfg()
    mediacrawler: MediaCrawlerCfg = MediaCrawlerCfg()
    logging: LoggingCfg = LoggingCfg()
    export: ExportCfg = ExportCfg()
