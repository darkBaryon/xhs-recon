from src.adapters.parsers import (
    card_time_to_iso,
    epoch_ms_to_iso,
    normalize_count,
    normalize_creator_ref,
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


def test_normalize_creator_ref_accepts_pure_user_id():
    assert normalize_creator_ref("66f0aabbccddeeff00112233") == "66f0aabbccddeeff00112233"


def test_normalize_creator_ref_accepts_profile_url_with_query():
    ref = "https://www.xiaohongshu.com/user/profile/66f0aabbccddeeff00112233?xsec_token=abc"

    assert normalize_creator_ref(ref) == "66f0aabbccddeeff00112233"


def test_normalize_creator_ref_lowercases_uppercase_id():
    assert normalize_creator_ref("66F0AABBCCDDEEFF00112233") == "66f0aabbccddeeff00112233"


def test_normalize_creator_ref_rejects_other_domain_with_original_ref():
    ref = "https://example.com/user/profile/66f0aabbccddeeff00112233"

    try:
        normalize_creator_ref(ref)
    except ValueError as e:
        assert ref in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_normalize_creator_ref_rejects_wrong_length_with_original_ref():
    ref = "66f0aabbccddeeff001122"

    try:
        normalize_creator_ref(ref)
    except ValueError as e:
        assert ref in str(e)
    else:
        raise AssertionError("expected ValueError")


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


def test_card_time_parses_relative_labels_with_clock_suffix():
    collected_at = "2026-07-17T16:07:07+00:00"

    assert card_time_to_iso(0, "昨天 18:15", collected_at) == "2026-07-17T18:15:00+08:00"
    assert card_time_to_iso(0, "31分钟前", collected_at).startswith("2026-07-17T15:36")
    assert card_time_to_iso(0, "2小时前", collected_at).startswith("2026-07-17T14:07")


def test_parse_comment_keeps_full_fields():
    """全量采集：评论保留身份/楼层/配图（推翻早期四项裁剪红线，用户明确扩范围）。"""
    row = {
        "comment_id": "c1",
        "create_time": 1718359058000,
        "ip_location": "上海",
        "note_id": "n1",
        "content": "这个角度很有帮助",
        "user_id": "user-abc",
        "nickname": "某昵称",
        "avatar": "https://avatar.example/u.png",
        "sub_comment_count": "3",
        "pictures": "https://pic.example/1.png,https://pic.example/2.png",
        "parent_comment_id": "0",
        "like_count": "1.2万",
    }

    c = parse_comment(row, collected_at="2026")

    assert c.body == "这个角度很有帮助"
    assert c.note_id == "n1"
    assert c.like_count == 12000
    assert c.collected_at == "2026"
    # 现在保留全字段
    assert c.comment_id == "c1"
    assert c.parent_comment_id == "0"
    assert c.author_id == "user-abc"
    assert c.author_nickname == "某昵称"
    assert c.author_avatar == "https://avatar.example/u.png"
    assert c.ip_location == "上海"
    assert c.pictures == ["https://pic.example/1.png", "https://pic.example/2.png"]
    assert c.sub_comment_count == 3
    assert c.created_at == epoch_ms_to_iso(1718359058000)


def test_parse_comments_jsonl_lines_skips_blank_lines():
    lines = [
        '{"content":"A","note_id":"n1","like_count":"10","user_id":"u1"}',
        "",
        '{"content":"B","note_id":"n2","like_count":null,"nickname":"nick"}',
    ]

    comments = parse_comments_jsonl_lines(lines, collected_at="2026")

    assert [c.body for c in comments] == ["A", "B"]
    assert [c.like_count for c in comments] == [10, 0]


def test_parse_creator_profiles_normalizes_counts_and_tags():
    from src.adapters.parsers import parse_creator_profiles_jsonl_lines

    lines = (
        open("tests/fixtures/creator_creators_sample.jsonl", encoding="utf-8").read().splitlines()
    )
    profiles = parse_creator_profiles_jsonl_lines(lines, collected_at="2026")
    assert len(profiles) == 2
    p0 = profiles[0]
    assert p0.account_id == "601d0481000000000101cc46"
    assert p0.fans == 12000  # "1.2万" 归一
    assert p0.interaction == 34000
    assert p0.tags == {"profession": "教育", "info": "已认证"}  # tag_list JSON → dict
    assert "教育科技" in p0.desc
    assert profiles[1].tags == {}  # 空标签账号 → 空 dict
    assert profiles[1].fans == 320  # 纯数字也走归一


def test_parse_creator_profiles_bad_line_skipped():
    from src.adapters.parsers import parse_creator_profiles_jsonl_lines

    lines = ['{"user_id": "a", "fans": 10}', "{broken", "", '{"user_id": "b", "fans": 20}']
    profiles = parse_creator_profiles_jsonl_lines(lines, collected_at="2026")
    assert [p.account_id for p in profiles] == ["a", "b"]  # 坏行跳过，好行保留


def test_parse_creator_profile_missing_fields_degrade():
    from src.adapters.parsers import parse_creator_profiles_jsonl_lines

    profiles = parse_creator_profiles_jsonl_lines(['{"user_id": "x"}'], collected_at="2026")
    p = profiles[0]
    assert p.account_id == "x"
    assert p.fans == 0 and p.tags == {} and p.desc == "" and p.ip_location == ""


def test_parse_tag_list_malformed_degrades_to_empty():
    from src.adapters.parsers import _parse_tag_list

    assert _parse_tag_list("not json") == {}
    assert _parse_tag_list("[1,2]") == {}  # 非 dict JSON
    assert _parse_tag_list(None) == {}
    assert _parse_tag_list('{"a": "b"}') == {"a": "b"}


def test_parse_creator_profile_verify_type_and_red_id():
    from src.adapters.parsers import parse_creator_profiles_jsonl_lines

    lines = [
        '{"user_id": "a", "verify_type": 2, "red_id": "12345"}',  # 机构认证
        '{"user_id": "b", "verify_type": 0, "red_id": "67890"}',  # 未认证
        '{"user_id": "c"}',  # 旧版 fork 无此字段 → verify_type=-1 未知
        '{"user_id": "d", "verify_type": "bad"}',  # 非法值 → -1
    ]
    ps = parse_creator_profiles_jsonl_lines(lines, collected_at="2026")
    assert [p.verify_type for p in ps] == [2, 0, -1, -1]
    assert ps[0].red_id == "12345"
    assert ps[2].red_id == ""  # 缺字段降级空串
