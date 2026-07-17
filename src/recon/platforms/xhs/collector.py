import hashlib
import re
from urllib.parse import urlencode, urlparse

from ...application.ports.collection import CreatorFeedCollectionRequest
from ...domain.content import (
    CollectionFailure,
    ContentReference,
    Creator,
    CreatorFeedResult,
)
from ...domain.identity import EntityId, PlatformId
from .contract import LegacyCommentLike, XhsAdapter

XHS = PlatformId("xhs")
_ALL_POSTS_LIMIT = 10_000
_CREATOR_ID = re.compile(r"^[0-9a-fA-F]{24}$")


def _normalize_creator_ref(ref: str) -> str:
    original = ref
    text = str(ref).strip()
    if _CREATOR_ID.fullmatch(text):
        return text.lower()
    parsed = urlparse(text)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme == "https"
        and parsed.netloc.lower() == "www.xiaohongshu.com"
        and len(parts) == 3
        and parts[:2] == ["user", "profile"]
        and _CREATOR_ID.fullmatch(parts[2])
    ):
        return parts[2].lower()
    raise ValueError(f"invalid creator ref: {original}")


def normalize_xhs_target(ref: str) -> EntityId:
    return EntityId(XHS, _normalize_creator_ref(ref))


def _comment_id(comment: LegacyCommentLike) -> str:
    if comment.comment_id:
        return comment.comment_id
    payload = "\0".join(
        [
            comment.note_id,
            comment.parent_comment_id,
            comment.author_id,
            comment.created_at,
            comment.body,
        ]
    )
    return "synthetic:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _card_url(card: dict) -> str:
    note_id = str(card.get("note_id") or "")
    query = urlencode(
        {
            "xsec_token": str(card.get("xsec_token") or ""),
            "xsec_source": str(card.get("xsec_source") or "pc_feed"),
        }
    )
    return f"https://www.xiaohongshu.com/explore/{note_id}?{query}"


class XhsCreatorFeedCollector:
    """批量读取账号主页列表；浏览器会话策略完全留在 adapter 内。"""

    platform_id = "xhs"

    def __init__(self, adapter: XhsAdapter) -> None:
        self.adapter = adapter

    def collect_creator_feeds(self, request: CreatorFeedCollectionRequest) -> CreatorFeedResult:
        account_ids = [target.id.external_id for target in request.targets]
        limit = request.max_notes if request.max_notes is not None else _ALL_POSTS_LIMIT
        if limit <= 0:
            raise ValueError("max_notes must be positive or null")
        try:
            cards, profiles = self.adapter.list_creator_notes(
                account_ids, request.collected_at, limit
            )
        except (OSError, ValueError, NotImplementedError) as exc:
            return CreatorFeedResult(
                platform="xhs",
                collected_at=request.collected_at,
                failures=tuple(
                    CollectionFailure(account_id, str(exc)) for account_id in account_ids
                ),
            )

        profile_by_id = {profile.account_id: profile for profile in profiles}
        target_by_id = {target.id.external_id: target for target in request.targets}
        references = []
        accounts_with_cards = set()
        for card in cards:
            note_id = str(card.get("note_id") or "")
            account_id = str(card.get("user_id") or "")
            if not note_id or account_id not in target_by_id:
                continue
            accounts_with_cards.add(account_id)
            references.append(
                ContentReference(
                    id=EntityId(XHS, note_id),
                    url=_card_url(card),
                    creator_id=EntityId(XHS, account_id),
                )
            )

        creators = []
        failures = []
        for account_id, target in target_by_id.items():
            profile = profile_by_id.get(account_id)
            if profile is None and account_id not in accounts_with_cards:
                failures.append(
                    CollectionFailure(account_id, "主页列表与账号档案均为空，未标记采集成功")
                )
                continue
            creators.append(
                Creator(
                    id=target.id,
                    nickname=(profile.nickname if profile else "") or target.nickname,
                    red_id=profile.red_id if profile else "",
                    description=profile.desc if profile else "",
                    fans=profile.fans if profile else 0,
                    follows=profile.follows if profile else 0,
                    interaction=profile.interaction if profile else 0,
                    verify_type=profile.verify_type if profile else -1,
                    tags=tuple((profile.tags if profile else {}).items()),
                    ip_location=profile.ip_location if profile else "",
                    updated_at=request.collected_at,
                )
            )
        return CreatorFeedResult(
            platform="xhs",
            collected_at=request.collected_at,
            creators=tuple(creators),
            contents=tuple(references),
            failures=tuple(failures),
        )
