from collections import defaultdict

from ..content import AccountCollectionResult
from ..research import AccountSummary


def summarize_accounts(result: AccountCollectionResult) -> tuple[AccountSummary, ...]:
    by_creator = defaultdict(list)
    for content in result.contents:
        by_creator[content.creator_id].append(content)
    creators = {creator.id: creator for creator in result.creators}

    summaries = []
    creator_ids = set(creators) | set(by_creator)
    for creator_id in sorted(creator_ids, key=lambda item: item.external_id):
        contents = by_creator[creator_id]
        totals = [content.engagement for content in contents]
        interaction = sum(metric.total for metric in totals)
        summaries.append(
            AccountSummary(
                creator_id=creator_id,
                nickname=creators.get(creator_id).nickname if creator_id in creators else "",
                content_count=len(contents),
                likes=sum(metric.likes for metric in totals),
                collects=sum(metric.collects for metric in totals),
                comments=sum(metric.comments for metric in totals),
                shares=sum(metric.shares for metric in totals),
                average_interaction=interaction / len(contents) if contents else 0,
                latest_published_at=max((content.published_at for content in contents), default=""),
            )
        )
    return tuple(summaries)
