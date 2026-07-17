import json
import zipfile
from datetime import datetime
from pathlib import Path

from ...domain.content import Content
from ...domain.research import ResearchAnalysis

_README = """# 领域研究快照

本 zip 是「{topic}」赛道的一次研究快照。

- research.json：输入词、时间窗和 watchlist 配置。
- accounts.json：账号档案、来源与搜索评分。
- notes.jsonl：搜索和账号主页内容，一行一条。

verify_type：2=机构、1=个人、0=未认证、-1=未知。互动字段缺失时表示未采集。
"""


def _in_window(published_at: str, collected_at: str, days: int):
    if days <= 0:
        return True
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        collected = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (collected - published).total_seconds() / 86400 <= days


class ResearchBundleFilesOutput:
    """直接从新分析模型生成稳定四文件 bundle，不依赖旧 CSV。"""

    def __init__(self, root: Path, run_name: str, research_input: dict) -> None:
        self.root = root
        self.run_name = run_name
        self.research_input = research_input

    def write(self, analysis: ResearchAnalysis) -> dict[str, str]:
        topic = str((self.research_input.get("seed_keywords") or ["research"])[0])
        name = f"{topic}-{self.run_name}"
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        research = {
            **self.research_input,
            "expanded_keywords": list(analysis.search.keywords),
            "watchlist": {
                "manual_count": analysis.manual_count,
                "self_count": sum(
                    1 for target in analysis.watchlist.requested if target.source == "self"
                ),
                "auto_top_n": analysis.auto_count,
                "max_total": self.research_input.get("max_total", 0),
            },
        }
        (folder / "research.json").write_text(
            json.dumps(research, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        accounts = self._accounts(analysis)
        (folder / "accounts.json").write_text(
            json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (folder / "notes.jsonl").open("w", encoding="utf-8") as file:
            for row in self._notes(analysis):
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
        (folder / "README.md").write_text(_README.format(topic=topic), encoding="utf-8")
        zip_path = self.root / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(folder.iterdir()):
                archive.write(item, f"{name}/{item.name}")
        return {"bundle": str(zip_path)}

    def _accounts(self, analysis: ResearchAnalysis) -> list[dict]:
        creators: dict = {creator.id: creator for creator in analysis.search.creators}
        for collection in analysis.watchlist.collections:
            creators.update({creator.id: creator for creator in collection.creators})
        ranks = {rank.creator_id: rank for rank in analysis.search.ranks}
        targets = {target.id: target for target in analysis.watchlist.requested}
        note_ids = {}
        for content in analysis.search.contents:
            note_ids.setdefault(content.creator_id, []).append(content.id.external_id)
        ids = list(targets) if targets else list(ranks)
        return [
            self._account_row(
                entity_id,
                creators.get(entity_id),
                ranks.get(entity_id),
                targets.get(entity_id),
                note_ids.get(entity_id, []),
            )
            for entity_id in ids
        ]

    @staticmethod
    def _account_row(entity_id, creator, rank, target, note_ids) -> dict:
        return {
            "account_id": entity_id.external_id,
            "nickname": (target.nickname if target else "")
            or (creator.nickname if creator else "")
            or (rank.nickname if rank else "")
            or entity_id.external_id,
            "source": target.source if target else "rank",
            "verify_type": creator.verify_type if creator else None,
            "red_id": creator.red_id if creator else "",
            "fans": creator.fans if creator else None,
            "follows": creator.follows if creator else None,
            "ip_location": creator.ip_location if creator else "",
            "desc": creator.description if creator else "",
            "account_score": rank.score if rank else None,
            "relevant_note_count": rank.content_count if rank else None,
            "keyword_hit_count": rank.keyword_count if rank else None,
            "profile_score": None,
            "vertical_ratio": None,
            "recent_note_count": None,
            "note_ids": note_ids,
        }

    def _notes(self, analysis: ResearchAnalysis):
        nicknames = {creator.id: creator.nickname for creator in analysis.search.creators}
        collected_at = self.research_input.get("collected_at", "")
        for collection in analysis.watchlist.collections:
            for creator in collection.creators:
                nicknames[creator.id] = creator.nickname
            for content in collection.contents:
                yield self._note_row(content, "creator", nicknames, collected_at, analysis)
        for content in analysis.search.contents:
            yield self._note_row(content, "search", nicknames, collected_at, analysis)

    @staticmethod
    def _note_row(
        content: Content,
        side: str,
        nicknames: dict,
        collected_at: str,
        analysis: ResearchAnalysis,
    ) -> dict:
        return {
            "account_id": content.creator_id.external_id,
            "nickname": nicknames.get(content.creator_id, ""),
            "side": side,
            "note_id": content.id.external_id,
            "title": content.title,
            "body": content.body,
            "tags": list(content.tags),
            "url": content.url,
            "published_at": content.published_at,
            "in_window": _in_window(
                content.published_at, collected_at, analysis.search.window_days
            ),
            "like_count": content.engagement.likes,
            "collect_count": content.engagement.collects,
            "comment_count": content.engagement.comments,
        }
