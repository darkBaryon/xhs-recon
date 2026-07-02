from src.adapters.parsers import (
    epoch_ms_to_iso,
    normalize_count,
    parse_comment,
    parse_comments_jsonl_lines,
    parse_note,
    split_tags,
)


def test_normalize_count_variants():
    assert normalize_count("1万") == 10000
    assert normalize_count("1.2万") == 12000
    assert normalize_count("10万+") == 100000
    assert normalize_count("921") == 921
    assert normalize_count("") == 0
    assert normalize_count(None) == 0
    assert normalize_count("garbage") == 0


def test_split_tags():
    assert split_tags("a,b,c") == ["a", "b", "c"]
    assert split_tags("") == []
    assert split_tags("  x , y ") == ["x", "y"]


def test_parse_note_field_mapping():
    row = {
        "note_id": "n1",
        "user_id": "u1",
        "title": "标题",
        "desc": "正文",
        "tag_list": "留学,essay",
        "note_url": "https://x/n1",
        "liked_count": "1万",
        "collected_count": "921",
        "comment_count": "12",
        "time": 1718359058000,
        "source_keyword": "留学辅导",
    }
    n = parse_note(row, keyword="fallback", collected_at="2026", raw_path="p")
    assert n.account_id == "u1"
    assert n.body == "正文"
    assert n.url == "https://x/n1"
    assert n.like_count == 10000
    assert n.collect_count == 921
    assert n.tags == ["留学", "essay"]
    assert n.source_keywords == ["留学辅导"]  # 取 row 的 source_keyword 而非 fallback
    assert n.published_at.startswith("2024-06")


def test_epoch_conversion_bad_input():
    assert epoch_ms_to_iso("nope") == ""


def test_parse_comment_drops_identity_fields():
    row = {
        "comment_id": "c1",
        "create_time": 1718359058000,
        "ip_location": "上海",
        "note_id": "n1",
        "content": "这个角度很有帮助",
        "user_id": "user-secret",
        "nickname": "昵称不能落盘",
        "avatar": "https://avatar.example/u.png",
        "sub_comment_count": "3",
        "pictures": ["https://pic.example/1.png"],
        "parent_comment_id": "0",
        "like_count": "1.2万",
    }

    c = parse_comment(row, collected_at="2026")

    assert c.body == "这个角度很有帮助"
    assert c.note_id == "n1"
    assert c.like_count == 12000
    assert c.collected_at == "2026"
    assert c.model_dump() == {
        "body": "这个角度很有帮助",
        "note_id": "n1",
        "like_count": 12000,
        "collected_at": "2026",
    }
    assert not hasattr(c, "user_id")
    assert not hasattr(c, "nickname")
    assert "avatar" not in c.model_dump()
    assert "ip_location" not in c.model_dump()


def test_parse_comments_jsonl_lines_skips_blank_lines():
    lines = [
        '{"content":"A","note_id":"n1","like_count":"10","user_id":"u1"}',
        "",
        '{"content":"B","note_id":"n2","like_count":null,"nickname":"nick"}',
    ]

    comments = parse_comments_jsonl_lines(lines, collected_at="2026")

    assert [c.body for c in comments] == ["A", "B"]
    assert [c.like_count for c in comments] == [10, 0]
