import csv
from pathlib import Path

from ...domain.research import SearchAnalysis


def _csv(path: Path, header: list[str], rows) -> str:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


class SearchFilesOutput:
    def __init__(self, root: Path, run_name: str) -> None:
        self.base = root / "search"
        self.run_dir = self.base / run_name

    def write(self, analysis: SearchAnalysis) -> dict[str, str]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        keywords_by_content = {}
        for collection in analysis.collections:
            for content in collection.contents:
                keywords_by_content.setdefault(content.id, []).append(collection.keyword)
        paths = {
            "search_contents": _csv(
                self.run_dir / "search_contents.csv",
                [
                    "platform",
                    "content_id",
                    "account_id",
                    "keywords",
                    "title",
                    "url",
                    "published_at",
                    "likes",
                    "collects",
                    "comments",
                    "shares",
                ],
                [
                    [
                        content.id.platform.value,
                        content.id.external_id,
                        content.creator_id.external_id,
                        "|".join(keywords_by_content.get(content.id, [])),
                        content.title,
                        content.url,
                        content.published_at,
                        content.engagement.likes,
                        content.engagement.collects,
                        content.engagement.comments,
                        content.engagement.shares,
                    ]
                    for content in analysis.contents
                ],
            ),
            "search_accounts": _csv(
                self.run_dir / "search_accounts.csv",
                [
                    "platform",
                    "account_id",
                    "nickname",
                    "content_count",
                    "keyword_count",
                    "average_interaction",
                    "score",
                ],
                [
                    [
                        rank.creator_id.platform.value,
                        rank.creator_id.external_id,
                        rank.nickname,
                        rank.content_count,
                        rank.keyword_count,
                        f"{rank.average_interaction:.2f}",
                        f"{rank.score:.2f}",
                    ]
                    for rank in analysis.ranks
                ],
            ),
        }
        report = self.run_dir / "search_report.md"
        relation_count = sum(len(collection.contents) for collection in analysis.collections)
        failed = [collection for collection in analysis.collections if collection.failures]
        lines = [
            "# 关键词搜索",
            "",
            "## 摘要",
            "",
            f"- 配置关键词：{len(analysis.keywords)}",
            f"- 完成关键词：{len(analysis.collections) - len(failed)}",
            f"- 失败关键词：{len(failed)}",
            f"- 去重帖子：{len(analysis.contents)}",
            f"- 账号：{len(analysis.creators)}",
            f"- 关键词关系：{relation_count}",
            "",
            "## 关键词覆盖",
            "",
            "| 关键词 | 帖子 | 账号 | 状态 |",
            "|---|---:|---:|---|",
        ]
        lines.extend(
            f"| {collection.keyword} | {len(collection.contents)} | "
            f"{len(collection.creators)} | "
            f"{'失败：' + collection.failures[0].message if collection.failures else '完成'} |"
            for collection in analysis.collections
        )
        lines.extend(["", "## 账号候选", ""])
        lines.extend(
            f"- {rank.nickname or rank.creator_id.external_id}："
            f"{rank.content_count} 篇，命中 {rank.keyword_count} 个关键词，得分 {rank.score:.2f}"
            for rank in analysis.ranks
        )
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths["search_report"] = str(report)
        self._update_latest()
        return paths

    def _update_latest(self) -> None:
        latest = self.base / "latest"
        if latest.is_symlink():
            latest.unlink()
        elif latest.exists():
            return
        latest.symlink_to(self.run_dir.name, target_is_directory=True)
