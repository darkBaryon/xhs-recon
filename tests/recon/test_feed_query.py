from src.recon.infrastructure.query.feed import ResearchFeedQuery
from web.feed import assemble


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=()):
        self.connection.calls.append((sql, params))
        if "FROM contents" in sql:
            self.rows = self.connection.notes
        elif "FROM content_comments" in sql:
            self.rows = self.connection.comments
        else:
            self.rows = self.connection.profiles

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self):
        self.calls = []
        self.notes = [
            {
                "note_id": "n1",
                "account_id": "a1",
                "nickname": "账号",
                "title": "标题",
                "body": "正文",
                "tags": "[]",
                "image_paths": "[]",
                "image_urls": "[]",
            }
        ]
        self.comments = []
        self.profiles = [{"account_id": "a1", "fans": 10, "verify_type": 2}]

    def cursor(self):
        return Cursor(self)


def test_new_schema_query_preserves_web_row_contract_and_keyword_filter(tmp_path):
    connection = Connection()

    notes, comments, profiles = ResearchFeedQuery(connection).read("留学辅导")
    payload = assemble(notes, comments, profiles, tmp_path)

    assert payload["notes"][0]["id"] == "n1"
    assert payload["accounts"][0]["fans"] == 10
    note_sql, params = connection.calls[0]
    assert "content_keywords" in note_sql
    assert params == ("留学辅导",)
