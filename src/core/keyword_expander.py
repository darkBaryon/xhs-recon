"""关键词扩展（v0 占位策略：seed + 可选 synonyms 映射，去重保序）。

策略本身允许各期演进；当前仅做最简扩展。
"""


def expand_keywords(keywords: list[str], synonyms: dict[str, list[str]] | None = None) -> list[str]:
    synonyms = synonyms or {}
    out: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        for term in [kw, *synonyms.get(kw, [])]:
            if term and term not in seen:
                seen.add(term)
                out.append(term)
    return out
