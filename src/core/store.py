"""Store 端口：把采集到的领域模型持久化并回答「哪些还没拉」。

与 ResearchAdapter 同级——core 定义抽象端口，adapters 给具体实现（MySQL），
pipelines 注入。core 只认这个抽象，不感知具体库/存储布局，也不出现平台名。

增量的支点全在这里：upsert 把新旧分开（新 note_id 插入、旧的只刷新易变字段），
notes_needing_comments 用行上的 comments_fetched_at 时间戳筛出「没拉过/过期」的评论目标，
让抓取侧只碰增量、少发请求（贴合低频/小范围运行边界）。
"""

from abc import ABC, abstractmethod

from src.models import Account, Comment, CreatorProfile, Note, TypicalNote


class Store(ABC):
    """累积库的抽象端口。所有 upsert 幂等：重复灌同一批不产生重复行。"""

    # ---- 写入（幂等 upsert）----
    @abstractmethod
    def upsert_accounts(self, accounts: list[Account]) -> None: ...

    @abstractmethod
    def upsert_notes(self, notes: list[Note]) -> None:
        """新 note_id 插入（first/last_collected_at=本次，comments_fetched_at=NULL）；
        已存在则只刷新易变字段（标题/正文/标签/互动数）与 last_collected_at，
        绝不回改 first_collected_at / comments_fetched_at。"""

    @abstractmethod
    def upsert_comments(self, comments: list[Comment]) -> None:
        """按 (note_id, 正文哈希) 去重插入；重复评论静默忽略。"""

    @abstractmethod
    def upsert_profiles(self, profiles: list[CreatorProfile]) -> None: ...

    # ---- 抓取状态标记 ----
    @abstractmethod
    def mark_comments_fetched(self, note_ids: list[str], at: str) -> None:
        """标记这些笔记「已在 at 时刻抓过评论」（即使抓到 0 条也标，避免反复空抓）。"""

    @abstractmethod
    def mark_creator_fetched(self, account_ids: list[str], at: str) -> None: ...

    # ---- 增量判据 / 读取 ----
    @abstractmethod
    def known_note_ids(self) -> set[str]:
        """库中已有的全部 note_id（去重、跳过下游用）。"""

    @abstractmethod
    def notes_needing_comments(
        self, candidates: list[TypicalNote], refresh_days: int, now_iso: str
    ) -> list[TypicalNote]:
        """从候选典型笔记里筛出「该抓评论」的：comments_fetched_at 为空（从没抓过），
        或距今超过 refresh_days（过期需刷新）。refresh_days<=0 表示只抓从没抓过的。"""

    @abstractmethod
    def load_notes(self) -> list[Note]:
        """库中全部笔记（窗口过滤交给 core.time_window，保持 store 只存不算）。"""

    @abstractmethod
    def load_accounts(self) -> list[Account]: ...

    def close(self) -> None:  # 默认空实现：内存实现无需关闭
        return None
