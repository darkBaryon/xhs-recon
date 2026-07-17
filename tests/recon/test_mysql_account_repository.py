import pytest

from src.recon.domain.content import (
    AccountCollectionResult,
    AccountTarget,
    CollectionFailure,
    Comment,
    Content,
    Creator,
    Engagement,
    SearchCollectionResult,
)
from src.recon.domain.identity import EntityId, PlatformId
from src.recon.infrastructure.persistence.mysql import repository as repository_module

XHS = PlatformId("xhs")


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.connection.executed.append(sql)

    def fetchall(self):
        return self.connection.query_rows

    def executemany(self, sql, rows):
        if self.connection.fail_on and self.connection.fail_on in sql:
            raise RuntimeError("database write failed")
        self.connection.many.append((sql, list(rows)))


class FakeConnection:
    def __init__(self, *, fail_on=""):
        self.executed = []
        self.many = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_on = fail_on
        self.query_rows = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _result():
    creator_id = EntityId(XHS, "creator-1")
    content_id = EntityId(XHS, "content-1")
    return AccountCollectionResult(
        platform="xhs",
        collected_at="2026-07-16T10:00:00+08:00",
        creators=(Creator(creator_id, nickname="竞品", updated_at="creator-updated"),),
        contents=(
            Content(
                id=content_id,
                creator_id=creator_id,
                title="标题",
                body="正文",
                url="https://example.test/content-1",
                published_at="published",
                updated_at="content-updated",
                engagement=Engagement(likes=10, collects=5, comments=2, shares=1),
                image_paths=("data/images/one.jpg",),
            ),
        ),
        comments=(
            Comment(
                id=EntityId(XHS, "comment-1"),
                content_id=content_id,
                body="评论",
            ),
        ),
    )


def _repository(monkeypatch, *, database_fail_on=""):
    boot = FakeConnection()
    database = FakeConnection(fail_on=database_fail_on)
    connections = iter((boot, database))
    monkeypatch.setattr(repository_module.pymysql, "connect", lambda **kwargs: next(connections))
    return repository_module.MySQLAccountRepository("candidate"), boot, database


def test_schema_and_upserts_preserve_entity_ownership(monkeypatch):
    repository, boot, database = _repository(monkeypatch)

    repository.save(_result())

    assert boot.commits == 1
    assert database.commits == 2  # 建表一次，业务事务一次
    ddl = "\n".join(database.executed)
    assert "first_seen_at" in ddl
    assert "last_seen_at" in ddl
    assert "creator_fetched_at" in ddl
    assert "comments_fetched_at" in ddl
    assert "PRIMARY KEY(platform, content_external_id, comment_key)" in ddl

    statements = {
        sql.split("INSERT INTO ", 1)[1].split()[0]: (sql, rows)
        for sql, rows in database.many
        if "INSERT INTO " in sql
    }
    creator_sql, creator_rows = statements["creators"]
    content_sql, content_rows = statements["contents"]
    comment_sql, comment_rows = statements["content_comments"]

    assert "first_seen_at=VALUES(first_seen_at)" not in creator_sql
    assert "first_seen_at=VALUES(first_seen_at)" not in content_sql
    assert "last_seen_at=VALUES(last_seen_at)" in creator_sql
    assert "last_seen_at=VALUES(last_seen_at)" in content_sql
    assert creator_rows[0][11:14] == (
        "2026-07-16T10:00:00+08:00",
        "2026-07-16T10:00:00+08:00",
        "2026-07-16T10:00:00+08:00",
    )
    assert content_rows[0][-2:] == (
        "2026-07-16T10:00:00+08:00",
        "2026-07-16T10:00:00+08:00",
    )
    assert "content_platform" not in comment_sql
    assert comment_rows[0][:4] == ("xhs", "comment-1", "content-1", "comment-1")


def test_database_name_must_be_a_plain_identifier():
    with pytest.raises(ValueError, match="invalid MySQL database name"):
        repository_module.MySQLAccountRepository("candidate`; DROP DATABASE x; --")


def test_save_rolls_back_the_whole_result_on_failure(monkeypatch):
    repository, _, database = _repository(monkeypatch, database_fail_on="INSERT INTO contents")

    with pytest.raises(RuntimeError, match="database write failed"):
        repository.save(_result())

    assert database.commits == 1  # 只有初始化建表提交
    assert database.rollbacks == 1


def test_search_entities_and_keyword_ownership_share_one_transaction(monkeypatch):
    repository, _, database = _repository(monkeypatch)
    source = _result()
    result = SearchCollectionResult(
        platform=source.platform,
        keyword="留学辅导",
        collected_at=source.collected_at,
        creators=source.creators,
        contents=source.contents,
    )

    repository.save_search(result)

    keyword_calls = [call for call in database.many if "content_keywords" in call[0]]
    creator_calls = [call for call in database.many if "INSERT INTO creators" in call[0]]
    assert keyword_calls[0][1] == [("xhs", "content-1", "留学辅导")]
    assert creator_calls[0][1][0][13] is None
    assert "creator_fetched_at=COALESCE" in creator_calls[0][0]
    assert database.commits == 2


def test_watchlist_marks_success_but_not_partial_failure(monkeypatch):
    repository, _, database = _repository(monkeypatch)
    result = _result()

    repository.save_watchlist(result, comments_fetched=True)

    creator_call = next(call for call in database.many if "INSERT INTO creators" in call[0])
    assert creator_call[1][0][13] == result.collected_at
    assert any("UPDATE contents SET comments_fetched_at" in sql for sql, _rows in database.many)
    assert any("UPDATE contents SET detail_fetched_at" in sql for sql, _rows in database.many)

    database.many.clear()
    failed = AccountCollectionResult(
        platform=result.platform,
        collected_at=result.collected_at,
        creators=result.creators,
        contents=result.contents,
        failures=(CollectionFailure("creator-1", "failed"),),
    )
    repository.save_watchlist(failed, comments_fetched=True)

    creator_call = next(call for call in database.many if "INSERT INTO creators" in call[0])
    assert creator_call[1][0][13] is None
    assert not any("comments_fetched_at" in sql for sql, _rows in database.many)
    assert not any("detail_fetched_at" in sql for sql, _rows in database.many)


def test_watchlist_due_selection_is_oldest_first(monkeypatch):
    repository, _, database = _repository(monkeypatch)
    database.query_rows = [
        {"external_id": "recent", "creator_fetched_at": "2026-07-15T00:00:00+00:00"},
        {"external_id": "old", "creator_fetched_at": "2026-07-01T00:00:00+00:00"},
    ]
    targets = tuple(
        AccountTarget(EntityId(XHS, external_id)) for external_id in ("recent", "never", "old")
    )

    due = repository.due_targets(
        targets,
        "2026-07-16T00:00:00+00:00",
        refresh_days=3,
        batch_size=2,
    )

    assert [target.id.external_id for target in due] == ["never", "old"]


def test_watchlist_always_includes_self_without_using_a_rotation_slot(monkeypatch):
    repository, _, database = _repository(monkeypatch)
    database.query_rows = [
        {"external_id": "self", "creator_fetched_at": "2026-07-15T00:00:00+00:00"},
        {"external_id": "old", "creator_fetched_at": "2026-07-01T00:00:00+00:00"},
    ]
    targets = (
        AccountTarget(EntityId(XHS, "self"), source="self"),
        AccountTarget(EntityId(XHS, "never")),
        AccountTarget(EntityId(XHS, "old")),
    )

    due = repository.due_targets(
        targets,
        "2026-07-16T00:00:00+00:00",
        refresh_days=3,
        batch_size=1,
    )

    assert [target.id.external_id for target in due] == ["self", "never"]


def test_comment_due_selection_preserves_null_and_expired_semantics(monkeypatch):
    repository, _, database = _repository(monkeypatch)
    database.query_rows = [
        {"external_id": "never", "comments_fetched_at": None},
        {"external_id": "old", "comments_fetched_at": "2026-07-01T00:00:00+00:00"},
        {"external_id": "recent", "comments_fetched_at": "2026-07-15T00:00:00+00:00"},
    ]
    target = AccountTarget(EntityId(XHS, "creator"))

    due = repository.content_ids_needing_comments(
        target,
        "2026-07-16T00:00:00+00:00",
        refresh_days=3,
    )

    assert due == frozenset({"never", "old"})
