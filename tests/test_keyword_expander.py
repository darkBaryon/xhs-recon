from src.core.keyword_expander import expand_keywords


def test_expand_with_synonyms_dedup_preserves_order():
    out = expand_keywords(["留学辅导"], {"留学辅导": ["essay辅导", "final自救", "留学辅导"]})
    assert out == ["留学辅导", "essay辅导", "final自救"]


def test_no_synonyms_returns_seeds():
    assert expand_keywords(["a", "b"]) == ["a", "b"]


def test_cross_seed_dedup():
    out = expand_keywords(["a", "b"], {"a": ["x"], "b": ["x", "y"]})
    assert out == ["a", "x", "b", "y"]
