"""领域模型（平台无关）。pydantic BaseModel，.model_dump() 出 dict。"""

from pydantic import BaseModel


class Account(BaseModel):
    account_id: str
    nickname: str
    source_keywords: list[str]
    note_count: int
    first_seen_at: str
    last_seen_at: str


class Note(BaseModel):
    note_id: str
    account_id: str
    title: str
    body: str
    tags: list[str]
    url: str
    like_count: int
    collect_count: int
    comment_count: int
    published_at: str
    collected_at: str
    source_keywords: list[str]
    raw_path: str


class Comment(BaseModel):
    body: str
    note_id: str
    like_count: int
    collected_at: str


class AccountRank(BaseModel):
    account_id: str
    nickname: str
    relevant_note_count: int
    keyword_hit_count: int
    avg_interaction: float
    account_score: float
    note_ids: list[str]
    vertical_ratio: float = 0.0
    recent_note_count: int = 0
    profile_score: float = 0.0


class TypicalNote(BaseModel):
    account_id: str
    note_id: str
    title: str
    url: str
    note_score: float
    selection_reason: str


class WatchAccount(BaseModel):
    account_id: str
    nickname: str = ""
    source: str


class CreatorProfile(BaseModel):
    """创作者主页档案（官方主页数据，机构判定用软信号）。"""

    account_id: str
    nickname: str = ""
    desc: str = ""
    fans: int = 0
    follows: int = 0
    interaction: int = 0
    tags: dict[str, str] = {}
    ip_location: str = ""
    collected_at: str = ""


class FetchResult(BaseModel):
    """采集+解析的边界产物。失败不抛，装进 error；core 只读 notes/accounts。"""

    provider: str
    operation: str
    collected_at: str
    keyword: str | None = None
    page: int | None = None
    note_id: str | None = None
    notes: list[Note] = []
    accounts: list[Account] = []
    comments: list[Comment] = []
    profiles: list[CreatorProfile] = []
    raw_path: str | None = None
    raw_text: str | None = None
    error: str | None = None
    command: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
