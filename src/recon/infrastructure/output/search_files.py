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
        lines = ["# 关键词搜索", "", "关键词：" + "、".join(analysis.keywords), ""]
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
