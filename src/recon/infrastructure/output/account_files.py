import csv
from collections import Counter
from pathlib import Path

from ...domain.research import AccountAnalysis


def _write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> str:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(path)


class AccountFilesOutput:
    def __init__(self, root: Path, run_name: str) -> None:
        self.base = root / "account"
        self.run_dir = self.base / run_name

    def write(self, analysis: AccountAnalysis) -> dict[str, str]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        summaries = sorted(
            analysis.summaries,
            key=lambda item: item.likes + item.collects + item.comments + item.shares,
            reverse=True,
        )
        contents = sorted(
            analysis.collection.contents,
            key=lambda item: item.engagement.total,
            reverse=True,
        )
        paths = {
            "account_summary": _write_csv(
                self.run_dir / "account_summary.csv",
                [
                    "platform",
                    "account_id",
                    "nickname",
                    "content_count",
                    "likes",
                    "collects",
                    "comments",
                    "shares",
                    "average_interaction",
                    "latest_published_at",
                ],
                [
                    [
                        row.creator_id.platform.value,
                        row.creator_id.external_id,
                        row.nickname,
                        row.content_count,
                        row.likes,
                        row.collects,
                        row.comments,
                        row.shares,
                        f"{row.average_interaction:.2f}",
                        row.latest_published_at,
                    ]
                    for row in summaries
                ],
            ),
            "account_contents": _write_csv(
                self.run_dir / "account_contents.csv",
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
                    "total_interaction",
                ],
                [
                    [
                        row.id.platform.value,
                        row.id.external_id,
                        row.creator_id.external_id,
                        row.title,
                        row.url,
                        row.published_at,
                        row.engagement.likes,
                        row.engagement.collects,
                        row.engagement.comments,
                        row.engagement.shares,
                        row.engagement.total,
                    ]
                    for row in contents
                ],
            ),
        }
        paths["account_report"] = self._write_report(analysis, summaries, contents)
        self._update_latest()
        return paths

    def _write_report(self, analysis, summaries, contents) -> str:
        by_creator = {}
        for content in contents:
            by_creator.setdefault(content.creator_id, []).append(content)
        lines = ["# 竞品账号分析", ""]
        for summary in summaries:
            lines.append(f"## {summary.nickname or summary.creator_id.external_id}")
            lines.append(
                f"- 帖子 {summary.content_count} · 获赞 {summary.likes} · "
                f"收藏 {summary.collects} · 评论 {summary.comments} · "
                f"分享 {summary.shares} · 平均互动 {summary.average_interaction:.2f}"
            )
            months = Counter(
                content.published_at[:7]
                for content in by_creator.get(summary.creator_id, [])
                if len(content.published_at) >= 7
            )
            if months:
                distribution = "、".join(f"{k}={v}" for k, v in sorted(months.items()))
                lines.append("- 发布分布：" + distribution)
            for content in by_creator.get(summary.creator_id, [])[:10]:
                lines.append(
                    f"  - [{content.title or content.id.external_id}]({content.url}) "
                    f"· 互动 {content.engagement.total}"
                )
            lines.append("")
        if analysis.collection.failures:
            lines.extend(["## 采集警告", ""])
            lines.extend(f"- {failure.message}" for failure in analysis.collection.failures)
        path = self.run_dir / "account_report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def _update_latest(self) -> None:
        latest = self.base / "latest"
        if latest.is_symlink():
            latest.unlink()
        elif latest.exists():
            return
        latest.symlink_to(self.run_dir.name, target_is_directory=True)
