def expand_keywords(
    seeds: tuple[str, ...], synonyms: dict[str, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    synonyms = synonyms or {}
    expanded = []
    seen = set()
    for seed in seeds:
        for keyword in (seed, *synonyms.get(seed, ())):
            keyword = keyword.strip()
            if keyword and keyword not in seen:
                seen.add(keyword)
                expanded.append(keyword)
    return tuple(expanded)
