from datetime import datetime

from ..content import Content


def filter_contents(
    contents: tuple[Content, ...], window_days: int, now_iso: str
) -> tuple[Content, ...]:
    if window_days <= 0:
        return contents
    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("collected_at must be a valid ISO datetime") from exc
    kept = []
    for content in contents:
        try:
            published = datetime.fromisoformat(content.published_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - published).total_seconds() / 86400 <= window_days:
            kept.append(content)
    return tuple(kept)
