import csv
from pathlib import Path

from ...domain.research import WatchlistAnalysis


class WatchlistFilesOutput:
    def __init__(self, root: Path, run_name: str) -> None:
        self.base = root / "watchlist"
        self.run_dir = self.base / run_name

    def write(self, analysis: WatchlistAnalysis) -> dict[str, str]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        contents = [content for result in analysis.collections for content in result.contents]
        path = self.run_dir / "watchlist_contents.csv"
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "platform",
                    "content_id",
                    "account_id",
                    "title",
                    "url",
                    "published_at",
                    "likes",
                    "collects",
                    "comments",
                    "shares",
                ]
            )
            writer.writerows(
                [
                    content.id.platform.value,
                    content.id.external_id,
                    content.creator_id.external_id,
                    content.title,
                    content.url,
                    content.published_at,
                    content.engagement.likes,
                    content.engagement.collects,
                    content.engagement.comments,
                    content.engagement.shares,
                ]
                for content in contents
            )
        report = self.run_dir / "watchlist_report.md"
        failures = [failure for result in analysis.collections for failure in result.failures]
        lines = [
            "# Watchlist 最新帖子",
            "",
            f"- 配置账号：{len(analysis.requested)}",
            f"- 本次到期：{len(analysis.due)}",
            f"- 新增帖子：{len(contents)}",
            f"- 失败账号：{len(failures)}",
        ]
        lines.extend(
            f"- 失败：{failure.target_external_id} {failure.message}" for failure in failures
        )
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._update_latest()
        return {"watchlist_contents": str(path), "watchlist_report": str(report)}

    def _update_latest(self) -> None:
        latest = self.base / "latest"
        if latest.is_symlink():
            latest.unlink()
        elif latest.exists():
            return
        latest.symlink_to(self.run_dir.name, target_is_directory=True)
