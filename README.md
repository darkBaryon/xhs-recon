# xhs-recon — 小红书竞品研究工具

个人自用、本地运行的小红书竞品研究管线。给定 seed keywords，做：关键词扩展 → 只读搜索（期1 离线 fixture；期2 调用本机 MediaCrawler，不可用时降级 fixture）→ 提取 notes/accounts → 账号去重打分 → 选典型笔记 →（可选）读评论 → 导出 LLM 分析用的结构化文件。

**不做**大而全/商用爬取、不绕风控、不开付费代理池、不并发、不自动点赞/评论/私信，不存评论用户敏感字段。采集走现成 MediaCrawler（CDP=本机真实浏览器、低频、个人自用）。

## 运行

```bash
# 期1：离线 fixture 管线（无需登录、可重复）
uv run python -m src.pipelines.run_research --config configs/sample.yaml

# 期2：真实采集（需 ../MediaCrawler 就绪 + 已登录；manual 集成验收）
uv run python scripts/integration_mediacrawler.py --config configs/sample_mediacrawler.yaml
```

导出落 `data/exports/`：`accounts/notes/account_rank/typical_notes.csv` + `report_input.md`。

## 工程化

采集层（xhs 专属、可换 adapter）与研究核心（关键词/解析/打分/选择/导出，平台无关、可复用）解耦，便于后续功能复用。

## 开发流程

本仓的功能开发走 [workbench/](workbench/) 工作台（需求 → 方案 → 评审 → Gate → 实施 → 验收）：

```bash
cd workbench
python3 tools/serve_site.py --port 8767   # 浏览过程文档
```

入口：[workbench/规范.md](workbench/规范.md)（流程规范）· [workbench/index.md](workbench/index.md)（活跃工作台）。

## 状态

v0 开发中。期1（fixture 管线）已交付；期2（MediaCrawler 真实采集）实施中。
