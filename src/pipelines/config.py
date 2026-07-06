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
    # 少量多次：每个 MC 会话最多 N 个关键词，其余下会话（0=全部一会话，旧行为）
    batch_size: int = 0


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
    # 少量多次：每次 track 只抓最久未抓的 N 个账号（0=全抓，旧行为）；跨次轮转靠库
    # 的 creator_fetched_at。需 store.enabled 才生效（否则无轮转状态）
    batch_size: int = 0
    # 抓过不足 N 天的账号本次跳过（未到期）；0=不按时间跳、纯轮询最旧
    refresh_days: int = 0


class SelectionCfg(BaseModel):
    top_notes_per_account: int = 2
    half_life_days: int = 0


class CommentsCfg(BaseModel):
    enabled: bool = False
    limit: int = 10
    report_top_k: int = 3
    # 采评论的典型笔记上限（按分数截前 N，防批量超时）
    max_notes: int = 30
    # 增量：距上次抓评论超过 refresh_days 才重抓；<=0 = 只抓从没抓过的（最省请求）
    refresh_days: int = 0
    fixture_path: str | None = None


class MediaCrawlerCfg(BaseModel):
    login_type: str = "qrcode"
    cookies: str = ""
    out_dir: str = "data/raw"
    # 单会话超时下限（秒）；各阶段按工作量放大。设 0 = 完全不限时（无限等，慎用）
    timeout: int = 600
    max_concurrency: int = 1
    sleep_sec: float = 2.0
    # 全量采集：creator 会话下载原图到本地（URL 带时间签名几天即失效，唯下载可永久看）
    download_images: bool = True
    # 持久图片库：采后把原图从 raw（临时）复制到此（按 note_id 组织、不随 raw 清理）
    media_dir: str = "data/media"


class LoggingCfg(BaseModel):
    level: str = "info"
    dir: str = "data/logs"
    file_enabled: bool = True


class ExportCfg(BaseModel):
    out_dir: str = "data/exports"


class StoreCfg(BaseModel):
    # enabled=False → 不建库，行为与旧版一致（全量、per-run 目录）；真实配置里置 true 开增量
    enabled: bool = False
    # 本机 MySQL 的独立库（凭据自 ~/.my.cnf）；与 uni_atlas 的 study_abroad 同服务器异库
    database: str = "xhs_recon"


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
    store: StoreCfg = StoreCfg()
