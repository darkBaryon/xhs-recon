# xhs-recon — 小红书竞品研究工具

个人自用、本地运行的小红书竞品研究管线。给定 seed keywords，做：关键词扩展 → 只读搜索（期1 离线 fixture；期2 调用本机 MediaCrawler，不可用时降级 fixture）→ 提取 notes/accounts → 账号去重打分 → 选典型笔记 →（期3 可选）只读典型笔记一级评论 → 导出 LLM 分析用的结构化文件。

**不做**大而全/商用爬取、不绕风控、不开付费代理池、不并发、不自动点赞/评论/私信，不存评论用户敏感字段。采集走现成 MediaCrawler（CDP=本机真实浏览器、低频、个人自用）。

## 运行

```bash
# 期3：离线 fixture 管线（无需登录、可重复；默认开启 comments fixture）
uv run python -m src.pipelines.run_research --config configs/sample.yaml

# 期3：真实采集（需 ../MediaCrawler 就绪 + 已登录；manual 集成验收）
uv run python scripts/integration_mediacrawler.py --config configs/sample_mediacrawler.yaml -v
```

导出落 `data/exports/`：`accounts/notes/account_rank/typical_notes.csv` + `report_input.md`。当 `comments.enabled: true` 且采到评论时，额外产出 `comments.csv`，表头固定为 `body,note_id,like_count,collected_at`，并把每条典型笔记的前几条高赞评论织入 `report_input.md`。

真实评论采集会在搜索后再起一次 MediaCrawler `detail` 子进程。建议用 CDP / 本机已登录浏览器复用会话；纯 `qrcode` 登录可能在评论阶段再次要求扫码。只抓典型笔记一级评论，不抓全量笔记或二级评论。

## 日志

控制台默认显示 INFO 阶段行；加 `--verbose` / `-v` 后控制台显示 DEBUG。每次运行会写 `data/logs/run-<run_id>.log`，文件日志固定 DEBUG，目录可在配置的 `logging.dir` 调整，也可用 `logging.file_enabled: false` 关闭。

真实 MediaCrawler 子进程输出会完整落到本次 raw 目录的 `mediacrawler.log`。复盘真实采集时先看 `data/logs/run-*.log` 定位阶段和 raw_path，再打开对应 `mediacrawler.log` 看 MediaCrawler 原始 stdout/stderr。

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

v0 开发中。期1（fixture 管线）已交付；期2（MediaCrawler 真实采集）已交付；期3（典型笔记评论采集）实施中。
