from urllib.parse import parse_qs, urlparse

from ...application.ports.collection import ContentDetailCollectionRequest
from ...domain.content import (
    AccountCollectionResult,
    CollectionFailure,
    Comment,
    Content,
    Creator,
    Engagement,
)
from ...domain.identity import EntityId
from .collector import XHS, _comment_id


class XhsContentDetailCollector:
    """批量读取帖子详情；account、watchlist、backfill 共用。"""

    platform_id = "xhs"

    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def collect_content_details(
        self, request: ContentDetailCollectionRequest
    ) -> AccountCollectionResult:
        cards = []
        for content in request.contents:
            query = parse_qs(urlparse(content.url).query)
            cards.append(
                {
                    "note_id": content.id.external_id,
                    "xsec_token": (query.get("xsec_token") or [""])[0],
                    "xsec_source": (query.get("xsec_source") or ["pc_feed"])[0],
                    "user_id": content.creator_id.external_id if content.creator_id else "",
                }
            )
        result = self.adapter.fetch_note_details(
            cards, request.collected_at, with_comments=request.fetch_comments
        )
        creators = {
            account.account_id: Creator(
                EntityId(XHS, account.account_id),
                nickname=account.nickname,
                updated_at=request.collected_at,
            )
            for account in result.accounts
        }
        contents = tuple(
            Content(
                id=EntityId(XHS, note.note_id),
                creator_id=EntityId(XHS, note.account_id),
                title=note.title,
                body=note.body,
                url=note.url,
                published_at=note.published_at,
                updated_at=note.collected_at,
                engagement=Engagement(
                    note.like_count,
                    note.collect_count,
                    note.comment_count,
                    note.share_count,
                ),
                tags=tuple(note.tags),
                content_type=note.note_type,
                video_url=note.video_url,
                image_urls=tuple(note.image_urls),
                image_paths=tuple(note.image_paths),
                raw_path=note.raw_path,
                author_avatar=note.author_avatar,
                ip_location=note.ip_location,
            )
            for note in result.notes
        )
        content_ids = {content.id.external_id for content in contents}
        comments = tuple(
            Comment(
                id=EntityId(XHS, _comment_id(comment)),
                content_id=EntityId(XHS, comment.note_id),
                body=comment.body,
                likes=comment.like_count,
                parent_external_id=comment.parent_comment_id,
                author_external_id=comment.author_id,
                author_nickname=comment.author_nickname,
                created_at=comment.created_at,
                updated_at=comment.collected_at,
                author_avatar=comment.author_avatar,
                ip_location=comment.ip_location,
                pictures=tuple(comment.pictures),
                sub_comment_count=comment.sub_comment_count,
            )
            for comment in result.comments
            if comment.note_id in content_ids
        )
        failures = (CollectionFailure("", result.error),) if result.error else ()
        return AccountCollectionResult(
            platform="xhs",
            collected_at=request.collected_at,
            creators=tuple(creators.values()),
            contents=contents,
            comments=comments,
            failures=failures,
        )
