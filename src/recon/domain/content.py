from dataclasses import dataclass, field

from .identity import EntityId


@dataclass(frozen=True, slots=True)
class AccountTarget:
    id: EntityId
    nickname: str = ""
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class Creator:
    id: EntityId
    nickname: str = ""
    red_id: str = ""
    description: str = ""
    fans: int = 0
    follows: int = 0
    interaction: int = 0
    verify_type: int = -1
    tags: tuple[tuple[str, str], ...] = ()
    ip_location: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class Engagement:
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0

    @property
    def total(self) -> int:
        return self.likes + self.collects + self.comments + self.shares


@dataclass(frozen=True, slots=True)
class Content:
    id: EntityId
    creator_id: EntityId
    title: str
    body: str
    url: str
    published_at: str
    updated_at: str
    engagement: Engagement = field(default_factory=Engagement)
    tags: tuple[str, ...] = ()
    content_type: str = ""
    video_url: str = ""
    image_urls: tuple[str, ...] = ()
    image_paths: tuple[str, ...] = ()
    raw_path: str = ""
    author_avatar: str = ""
    ip_location: str = ""


@dataclass(frozen=True, slots=True)
class Comment:
    id: EntityId
    content_id: EntityId
    body: str
    likes: int = 0
    parent_external_id: str = ""
    author_external_id: str = ""
    author_nickname: str = ""
    created_at: str = ""
    updated_at: str = ""
    author_avatar: str = ""
    ip_location: str = ""
    pictures: tuple[str, ...] = ()
    sub_comment_count: int = 0


@dataclass(frozen=True, slots=True)
class CollectionFailure:
    target_external_id: str
    message: str


@dataclass(frozen=True, slots=True)
class AccountCollectionResult:
    platform: str
    collected_at: str
    creators: tuple[Creator, ...] = ()
    contents: tuple[Content, ...] = ()
    comments: tuple[Comment, ...] = ()
    failures: tuple[CollectionFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchCollectionResult:
    platform: str
    keyword: str
    collected_at: str
    creators: tuple[Creator, ...] = ()
    contents: tuple[Content, ...] = ()
    failures: tuple[CollectionFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class ContentReference:
    id: EntityId
    url: str
    creator_id: EntityId | None = None


@dataclass(frozen=True, slots=True)
class CreatorFeedResult:
    platform: str
    collected_at: str
    creators: tuple[Creator, ...] = ()
    contents: tuple[ContentReference, ...] = ()
    failures: tuple[CollectionFailure, ...] = ()
