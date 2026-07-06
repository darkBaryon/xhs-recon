"""web/feed.py 纯函数层：DB 行 → 前端 payload（不连库；DB 读取靠真库手验）。"""

import json

from web.feed import assemble, norm_comment, norm_note


def _note_row(**over):
    row = {
        "note_id": "n1",
        "account_id": "a1",
        "nickname": "测试号",
        "author_avatar": "https://cdn/av.jpg",
        "title": "标题",
        "body": "正文",
        "tags": json.dumps(["留学", "文书"]),
        "url": "https://xhs/n1",
        "like_count": 12000,
        "collect_count": 3,
        "comment_count": 5,
        "published_at": "2026-07-01T10:00:00+08:00",
        "note_type": "normal",
        "video_url": "",
        "image_paths": "[]",
        "image_urls": json.dumps(["http://cdn/1.jpg"]),
        "ip_location": "上海",
    }
    row.update(over)
    return row


def test_norm_note_basics(tmp_path):
    n = norm_note(_note_row(), tmp_path)
    assert n["id"] == "n1" and n["author"] == "测试号"
    assert n["tags"] == ["留学", "文书"]
    assert n["date"] == "2026-07-01"
    assert not n["video"]
    # 无本地图 → 远程首图兜底
    assert n["imgs"] == [] and n["cover_remote"] == "http://cdn/1.jpg"


def test_norm_note_local_images_relative(tmp_path):
    media = tmp_path / "data" / "media" / "xhs" / "n1"
    media.mkdir(parents=True)
    img = media / "0.jpg"
    img.write_bytes(b"x")
    row = _note_row(image_paths=json.dumps([str(img), str(media / "missing.jpg")]))
    n = norm_note(row, tmp_path / "data" / "site")
    # 存在的转相对路径，不存在的丢弃；有本地图则不用远程兜底
    assert n["imgs"] == ["../media/xhs/n1/0.jpg"]
    assert n["cover_remote"] == ""


def test_norm_note_bad_json_fields(tmp_path):
    n = norm_note(_note_row(tags="not json", image_paths=None, image_urls=""), tmp_path)
    assert n["tags"] == [] and n["imgs"] == []


def test_assemble_groups_accounts_and_profiles(tmp_path):
    rows = [_note_row(), _note_row(note_id="n2"), _note_row(note_id="n3", account_id="a2", nickname="乙")]
    comments = [
        {"note_id": "n1", "comment_id": "c1", "parent_comment_id": "", "body": "顶", "author_nickname": "路人", "like_count": 2, "created_at": "2026-07-02", "ip_location": "广东", "author_avatar": ""},
    ]
    profiles = [{"account_id": "a1", "fans": 2847, "descr": "简介", "red_id": "123", "verify_type": 2}]
    payload = assemble(rows, comments, profiles, tmp_path)
    assert len(payload["notes"]) == 3
    accs = {a["aid"]: a for a in payload["accounts"]}
    assert accs["a1"]["notes"] == 2 and accs["a1"]["fans"] == 2847 and accs["a1"]["verify"] == 2
    assert accs["a2"]["notes"] == 1 and "fans" not in accs["a2"]
    c = payload["comments"][0]
    assert c == norm_comment(comments[0])
    assert c["nid"] == "n1" and c["parent"] == "" and c["like"] == 2
