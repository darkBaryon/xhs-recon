class ResearchFeedQuery:
    """把新 schema 投影成现有 Web assemble 所需的稳定行契约。"""

    def __init__(self, connection) -> None:
        self.connection = connection

    def read(self, keyword: str | None = None):
        where = ""
        params = ()
        if keyword:
            where = (
                " WHERE EXISTS (SELECT 1 FROM content_keywords ck"
                " WHERE ck.platform=c.platform"
                " AND ck.content_external_id=c.external_id AND ck.keyword=%s)"
            )
            params = (keyword,)
        notes_sql = (
            "SELECT c.external_id AS note_id,c.creator_external_id AS account_id,"
            "cr.nickname,c.author_avatar,c.title,c.body,c.tags,c.url,c.like_count,"
            "c.collect_count,c.comment_count,c.published_at,c.content_type AS note_type,"
            "c.video_url,c.image_paths,c.image_urls,c.ip_location"
            " FROM contents c LEFT JOIN creators cr ON cr.platform=c.creator_platform"
            " AND cr.external_id=c.creator_external_id" + where + " ORDER BY c.published_at DESC"
        )
        comments_sql = (
            "SELECT external_id AS comment_id,comment_key,content_external_id AS note_id,"
            "parent_external_id AS parent_comment_id,body,author_nickname,author_avatar,"
            "like_count,created_at,ip_location FROM content_comments ORDER BY created_at"
        )
        profiles_sql = (
            "SELECT external_id AS account_id,fans,description AS descr,red_id,verify_type"
            " FROM creators"
        )
        return (
            self._fetch(notes_sql, params),
            self._fetch(comments_sql),
            self._fetch(profiles_sql),
        )

    def _fetch(self, sql: str, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())
