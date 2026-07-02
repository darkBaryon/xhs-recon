# xhs-recon — 小红书竞品研究工具

个人自用、本地运行的小红书竞品研究管线：给定 seed keywords，自动完成**搜索 → 提取 → 打分 → 选典型 → 读评论 → 导出**，产出可直接喂给 LLM 做竞品分析的结构化资料。

```
关键词扩展 → 只读搜索（MediaCrawler / 离线 fixture）→ 提取 notes/accounts
  → 账号去重打分排名 → 每账号选典型笔记 → 批量读典型笔记一级评论（可选）
  → 导出 data/exports/（5 个 CSV + report_input.md）
```

**v0 三期已全部交付**：期1 fixture 管线 · 期2 MediaCrawler 真实采集 · 期3 典型笔记评论。

**合规口径（个人自用）**：只调现成 MediaCrawler、低频小范围；CDP 连本机真实浏览器（不伪造身份）；不开付费代理池、不并发、无任何点赞/评论/私信写操作；**评论只存 `body/note_id/like_count/collected_at` 四字段**，评论者身份/IP/头像在 parser 边界丢弃（红线，pytest 专项守护）。

## 快速开始

### 离线跑通（无需登录，随时可跑）

```bash
uv run python -m src.pipelines.run_research --config configs/sample.yaml
```

吃 `tests/fixtures/` 样本，产出完整 6 文件，用于开发自测与了解产出格式。

### 真实采集（manual）

**前置一：MediaCrawler** —— 位于 `../MediaCrawler/`（uv 管理，含 Playwright 环境）。

**前置二：采集浏览器（CDP，一次性设置）** —— Chrome 136+ 出于安全默认 profile 会**静默忽略**调试端口参数，须用专用 profile 直接调二进制启动（`open -a` 只会把参数丢给已运行实例，不要用）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$HOME/.xhs-recon-chrome" &

curl -s http://127.0.0.1:9222/json/version   # 有 JSON 返回 = 端口就绪
```

首次在该窗口登录小红书（扫码一次），登录态存在专用 profile 里，**之后每次采集免登录**；该窗口与日常 Chrome 互不影响。采集期间不要操作该窗口。

**跑：**

```bash
uv run python scripts/integration_mediacrawler.py --config configs/sample_mediacrawler.yaml -v
```

一次运行会起 2-3 个 MediaCrawler 子进程（每关键词一次 search + 一次 detail 读评论），每个子进程在采集浏览器里新开标签页驱动，属正常现象。9222 不可达时 MediaCrawler 会白等 60s 再回退自带浏览器（能跑但慢，且可能要求扫码）。

## 产出（`data/exports/`）

| 文件 | 内容 | 给谁 |
|---|---|---|
| `report_input.md` | 账号排名 + 典型笔记链接 + 高赞评论织入 | **人读 / 喂 LLM 的主入口** |
| `accounts.csv` `notes.csv` | 全量账号/笔记明细 | 机器 |
| `account_rank.csv` | 账号评分排名（笔记数×关键词命中×互动加权） | 机器 |
| `typical_notes.csv` | 每账号代表作及入选理由 | 机器 |
| `comments.csv` | 典型笔记一级评论，表头固定 `body,note_id,like_count,collected_at` | 机器 |

`comments.enabled: false` 时不产 `comments.csv`，其余行为与期2 完全一致。管线口径**诚实不假装**：某步采集失败 → 记入 error、该部分为空、其余照出。

## 数据目录

- `data/raw/<run>/` — MediaCrawler 原始 JSONL，按运行时间戳隔离（**评论 raw 含作者字段，仅本地留存，gitignore**）；
- `data/exports/` — 最终导出（gitignore）；
- `data/logs/` — 管线运行日志（gitignore），文件名形如 `run-<run_id>.log`；
- 配置：`configs/sample.yaml`（fixture）/ `configs/sample_mediacrawler.yaml`（真实），键与缺省见文件内注释。

## 日志

控制台默认显示 INFO 阶段行；加 `--verbose` / `-v` 后控制台显示 DEBUG。每次运行会写 `data/logs/run-<run_id>.log`，文件日志固定 DEBUG，目录可在配置的 `logging.dir` 调整，也可用 `logging.file_enabled: false` 关闭。

真实 MediaCrawler 子进程输出会完整落到本次 raw 目录的 `mediacrawler.log`。复盘真实采集时先看 `data/logs/run-*.log` 定位阶段和 raw_path，再打开对应 `mediacrawler.log` 看 MediaCrawler 原始 stdout/stderr。

## 架构

```
pipelines（组装点：读配置、_build_adapter 注入、编排六阶段）
   ↓ 依赖
core（平台无关研究核心：expander/aggregator/ranker/selector/exporter/ports——内部 0 处 "xhs"）
   ↓ 依赖
models（pydantic 领域模型）

adapters（实现 core 的 ResearchAdapter 端口，隔离一切平台细节）
  ├─ fixture_adapter    读本地 JSONL（期1，也是官方测试替身）
  ├─ mediacrawler_adapter 子进程调 MediaCrawler + 读回解析（期2/3）
  └─ parsers.py         JSONL → 模型（评论身份字段在此丢弃）
```

依赖铁律：`pipelines → core → models`；core 永不 import adapter；实现选择只发生在 [run_research.py](src/pipelines/run_research.py) 的 `_build_adapter`（composition root）。

## 测试

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

全离线（mock 子进程 + fixtures），不依赖真实小红书访问；红线（评论四字段、core 平台无关）有专项用例。真实采集不进 CI，靠 manual 集成脚本验收。

## 开发流程

功能开发走 [workbench/](workbench/) 工作台（需求 → 方案 → 评审 → Gate 1 → 实施 → 预飞 → 代码评审 → Gate 2）：

```bash
cd workbench && python3 tools/serve_site.py --port 8767   # 浏览过程文档站
```

入口：[workbench/规范.md](workbench/规范.md) · [workbench/index.md](workbench/index.md)。

## 状态

v0（三期）已交付。进行中：日志系统（标准级，`feat/logging`）。已知待办：典型笔记总量上限、raw 层评论字段口径。
