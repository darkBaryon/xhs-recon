from src.recon.infrastructure.persistence.mysql.legacy_import import LegacyImporter


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def executemany(self, sql, rows):
        self.connection.calls.append((sql, list(rows)))


class Connection:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _rows():
    accounts = [
        {
            "account_id": "a1",
            "nickname": "旧昵称",
            "first_seen_at": "first",
            "last_seen_at": "last",
            "creator_fetched_at": "creator-fetched",
        }
    ]
    notes = [
        {
            "note_id": "n1",
            "account_id": "a1",
            "title": "标题",
            "source_keywords": '["留学辅导","essay辅导","留学辅导"]',
            "image_paths": '["data/media/n1/0.jpg"]',
            "first_collected_at": "note-first",
            "last_collected_at": "note-last",
            "comments_fetched_at": "comments-fetched",
        }
    ]
    comments = [
        {
            "note_id": "n1",
            "comment_key": "stable-key",
            "comment_id": "c1",
            "body": "评论",
        }
    ]
    profiles = [
        {
            "account_id": "a1",
            "nickname": "档案昵称",
            "red_id": "red",
            "descr": "简介",
            "fans": 10,
            "collected_at": "profile-at",
        }
    ]
    return accounts, notes, comments, profiles


def test_legacy_import_preserves_state_and_keyword_ownership():
    connection = Connection()

    report = LegacyImporter(connection).import_rows(*_rows())

    assert report.creators == report.contents == report.comments == 1
    assert report.keywords == 2
    assert report.media_assets == 1
    calls = {
        sql.split("INSERT INTO ", 1)[1].split("(", 1)[0].strip(): rows
        for sql, rows in connection.calls
    }
    assert calls["creators"][0][11:14] == ("first", "last", "creator-fetched")
    assert calls["contents"][0][-4:] == (
        "note-first",
        "note-last",
        "note-last",
        "comments-fetched",
    )
    assert {row[2] for row in calls["content_keywords"]} == {"留学辅导", "essay辅导"}
    assert calls["content_comments"][0][3] == "stable-key"
    assert connection.commits == 1


def test_legacy_import_dry_run_has_no_writes():
    connection = Connection()

    report = LegacyImporter(connection).import_rows(*_rows(), dry_run=True)

    assert report.dry_run is True
    assert connection.calls == []
    assert connection.commits == 0


def test_legacy_import_creates_placeholder_for_note_author_missing_from_accounts():
    accounts, notes, comments, profiles = _rows()
    notes.append(
        {
            "note_id": "orphan-note",
            "account_id": "missing-account",
            "first_collected_at": "2026-01-01T00:00:00Z",
            "last_collected_at": "2026-01-02T00:00:00Z",
        }
    )
    connection = Connection()

    report = LegacyImporter(connection).import_rows(accounts, notes, comments, profiles)

    assert report.creators == 2
    assert report.placeholder_creators == 1
    creator_rows = next(rows for sql, rows in connection.calls if "INTO creators" in sql)
    placeholder = next(row for row in creator_rows if row[1] == "missing-account")
    assert placeholder[11:13] == (
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )
