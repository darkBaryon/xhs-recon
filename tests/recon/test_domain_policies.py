import pytest

from src.recon.domain.content import (
    AccountCollectionResult,
    Content,
    Creator,
    Engagement,
    SearchCollectionResult,
)
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.domain.policies.aggregate import summarize_accounts
from src.recon.domain.policies.keywords import expand_keywords
from src.recon.domain.policies.ranking import rank_creators
from src.recon.domain.policies.time_window import filter_contents

XHS = PlatformId("xhs")
NOW = "2026-07-02T00:00:00+00:00"


def _content(
    content_id: str,
    creator_id: str,
    *,
    published_at: str = "2026-07-01T00:00:00+00:00",
    likes: int = 0,
    collects: int = 0,
    comments: int = 0,
    shares: int = 0,
) -> Content:
    return Content(
        id=EntityId(XHS, content_id),
        creator_id=EntityId(XHS, creator_id),
        title=content_id,
        body="",
        url=f"https://example.com/{content_id}",
        published_at=published_at,
        updated_at=NOW,
        engagement=Engagement(likes, collects, comments, shares),
    )


def test_expand_keywords_deduplicates_and_preserves_order():
    assert expand_keywords(
        (" 留学辅导 ", "essay辅导"),
        {" 留学辅导 ": ("final自救", "留学辅导", "")},
    ) == ("留学辅导", "final自救", "essay辅导")


def test_time_window_keeps_boundary_and_skips_invalid_times():
    contents = (
        _content("boundary", "a", published_at="2026-06-02T00:00:00+00:00"),
        _content("old", "a", published_at="2026-06-01T23:59:59+00:00"),
        _content("invalid", "a", published_at=""),
    )

    assert [item.id.external_id for item in filter_contents(contents, 30, NOW)] == ["boundary"]
    assert filter_contents(contents, 0, NOW) is contents
    with pytest.raises(ValueError, match="collected_at"):
        filter_contents(contents, 30, "invalid")


def test_rank_creators_counts_distinct_keyword_ownership_and_applies_weights():
    creator_a = Creator(EntityId(XHS, "a"), nickname="账号 A")
    creator_b = Creator(EntityId(XHS, "b"), nickname="账号 B")
    a1 = _content("a1", "a", likes=100)
    a2 = _content("a2", "a")
    b1 = _content("b1", "b", likes=1)
    collections = (
        SearchCollectionResult("xhs", "留学", NOW, contents=(a1, b1)),
        SearchCollectionResult("xhs", "essay", NOW, contents=(a1,)),
    )

    ranks = rank_creators(
        (creator_a, creator_b),
        (a1, a2, b1),
        collections,
        {"note_count": 1, "keyword_hit": 10, "interaction": 0},
    )

    assert [rank.creator_id.external_id for rank in ranks] == ["a", "b"]
    assert ranks[0].content_count == 2
    assert ranks[0].keyword_count == 2
    assert ranks[0].score == 22


def test_summarize_accounts_includes_empty_creator_and_engagement_totals():
    populated = Creator(EntityId(XHS, "a"), nickname="账号 A")
    empty = Creator(EntityId(XHS, "b"), nickname="空账号")
    result = AccountCollectionResult(
        platform="xhs",
        collected_at=NOW,
        creators=(populated, empty),
        contents=(
            _content("a1", "a", likes=10, collects=2, comments=3, shares=1),
            _content(
                "a2",
                "a",
                published_at="2026-06-30T00:00:00+00:00",
                likes=4,
            ),
        ),
    )

    summaries = {item.creator_id.external_id: item for item in summarize_accounts(result)}
    assert summaries["a"].content_count == 2
    assert summaries["a"].likes == 14
    assert summaries["a"].average_interaction == 10
    assert summaries["a"].latest_published_at == "2026-07-01T00:00:00+00:00"
    assert summaries["b"].content_count == 0
    assert summaries["b"].average_interaction == 0
