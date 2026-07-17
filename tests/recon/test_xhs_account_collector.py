from src.adapters.fixture_adapter import FixtureAdapter
from src.recon.application.ports.collection import (
    ContentDetailCollectionRequest,
    CreatorFeedCollectionRequest,
)
from src.recon.domain.content import AccountTarget
from src.recon.platforms.xhs.collector import XhsCreatorFeedCollector, normalize_xhs_target
from src.recon.platforms.xhs.details import XhsContentDetailCollector

CREATOR = "tests/fixtures/creator_contents_sample.jsonl"
PROFILES = "tests/fixtures/creator_creators_sample.jsonl"
COMMENTS = "tests/fixtures/comments.jsonl"
ACCOUNT = "601d0481000000000101cc46"


def _capabilities(comments_path=COMMENTS):
    adapter = FixtureAdapter(
        "tests/fixtures/search_contents_sample.jsonl",
        creator_path=CREATOR,
        creator_profiles_path=PROFILES,
        comments_path=comments_path,
    )
    return XhsCreatorFeedCollector(adapter), XhsContentDetailCollector(adapter)


def test_creator_feed_and_details_are_independent_shared_capabilities():
    feeds, details = _capabilities()
    feed = feeds.collect_creator_feeds(
        CreatorFeedCollectionRequest(
            targets=(AccountTarget(normalize_xhs_target(ACCOUNT)),),
            collected_at="2026",
            max_notes=None,
        )
    )
    result = details.collect_content_details(
        ContentDetailCollectionRequest(
            contents=feed.contents,
            collected_at="2026",
            fetch_comments=False,
        )
    )

    assert len(feed.contents) == 2
    assert feed.creators[0].nickname == "陈皮糖"
    assert len(result.contents) == 2
    assert result.comments == ()
    assert {content.creator_id.external_id for content in result.contents} == {ACCOUNT}


def test_detail_capability_can_explicitly_fetch_comments(tmp_path):
    comments = tmp_path / "comments.jsonl"
    comments.write_text(
        '{"comment_id":"c1","note_id":"6a4661cd0000000017029d86",'
        '"content":"匹配评论","like_count":"1"}\n'
        '{"comment_id":"c2","note_id":"not-selected","content":"不应返回"}\n',
        encoding="utf-8",
    )
    feeds, details = _capabilities(str(comments))
    feed = feeds.collect_creator_feeds(
        CreatorFeedCollectionRequest(
            targets=(AccountTarget(normalize_xhs_target(ACCOUNT)),),
            collected_at="2026",
            max_notes=1,
        )
    )
    result = details.collect_content_details(
        ContentDetailCollectionRequest(feed.contents, "2026", fetch_comments=True)
    )

    assert len(result.contents) == 1
    assert [comment.body for comment in result.comments] == ["匹配评论"]
