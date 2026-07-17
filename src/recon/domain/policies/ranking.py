from collections import defaultdict

from ..content import Content, Creator, SearchCollectionResult
from ..research import CreatorRank

DEFAULT_WEIGHTS = {"note_count": 10.0, "keyword_hit": 5.0, "interaction": 0.01}


def rank_creators(
    creators: tuple[Creator, ...],
    contents: tuple[Content, ...],
    collections: tuple[SearchCollectionResult, ...],
    weights: dict[str, float] | None = None,
) -> tuple[CreatorRank, ...]:
    resolved = {**DEFAULT_WEIGHTS, **(weights or {})}
    creator_by_id = {creator.id: creator for creator in creators}
    contents_by_creator = defaultdict(list)
    keywords_by_creator = defaultdict(set)
    for content in contents:
        contents_by_creator[content.creator_id].append(content)
    for collection in collections:
        for content in collection.contents:
            keywords_by_creator[content.creator_id].add(collection.keyword)
    ranks = []
    for creator_id, owned in contents_by_creator.items():
        interactions = [
            content.engagement.likes + content.engagement.collects + content.engagement.comments
            for content in owned
        ]
        average = sum(interactions) / len(interactions)
        keyword_count = len(keywords_by_creator[creator_id])
        score = (
            resolved["note_count"] * len(owned)
            + resolved["keyword_hit"] * keyword_count
            + resolved["interaction"] * average
        )
        ranks.append(
            CreatorRank(
                creator_id=creator_id,
                nickname=creator_by_id.get(creator_id).nickname
                if creator_id in creator_by_id
                else "",
                content_count=len(owned),
                keyword_count=keyword_count,
                average_interaction=average,
                score=score,
            )
        )
    return tuple(sorted(ranks, key=lambda item: item.score, reverse=True))
