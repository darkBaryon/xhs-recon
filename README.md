# xhs-recon — 小红书竞品研究工具

个人自用、本地运行的小红书领域研究管线：给定 seed keywords 与关注账号，自动完成**搜索 → 提取 → 打分 → 盯账号 → 选典型 → 读评论 → 导出**，产出可直接喂给 LLM / 下游程序做领域分析的结构化资料（关键词、扩展词、账号、笔记、评论等全量工作）。

```
关键词扩展 → 只读搜索（MediaCrawler / 离线 fixture，时间序 + 时间窗过滤）
  → 提取 notes/accounts → 账号去重打分排名
  → watchlist 合成（手动账号 + 榜单自动 top-N）→ creator 模式取每账号最新 N 篇
  → 专业度分项打分（垂直度/活跃度）→ 每账号选典型笔记（互动 × 时间衰减）
  → 批量读典型笔记一级评论（可选）
  → 导出 data/exports/（9 个 CSV + report_input.md；可再 web 渲染 / bundle 打包）
```

**v0 三期已全部交付**：期1 fixture 管线 · 期2 MediaCrawler 真实采集 · 期3 典型笔记评论。
**「专业账号追踪」三期已全部交付**（2026-07）：期1 时间维度修复（排序透传/窗过滤/衰减）· 期2 creator 拉取与 watchlist · 期3 专业度打分与选题素材。

**运行边界(个人自用)**：低频、小范围、单线程；复用本机浏览器的现有登录态；不使用代理池；只读取公开列表与评论，不做任何写操作（点赞/评论/私信）；评论字段裁剪为 body/note_id/like_count/collected_at 四项，其余字段在 parser 边界丢弃，由 pytest 用例守护。

## 快速开始

**一键**（自动确保采集浏览器就绪；主题默认留学辅导，换赛道 `CONFIG=configs/<主题>/run.yaml ./run.sh track`）：

```bash
./run.sh            # 离线 fixture demo（无需登录/浏览器，用 configs/sample.yaml）
./run.sh search     # 真实·广角：关键词搜索+榜单（关键词分批，进入新领域时）
./run.sh track      # 真实·长焦：watchlist→creator（含评论+原图，账号轮转，日常盯人）
./run.sh track-all  # 真实·巡逻：自动一批批 track，批间随机休眠 5-10 分钟，抓完收工
./run.sh real       # 真实·全流程（= research）
./run.sh browser    # 只起/查采集浏览器
./run.sh web        # 把最新一跑的导出渲染成本地静态站并打开（离线，无需采集）
./run.sh bundle     # 把最新一跑打包成研究快照 zip（供下游程序/LLM）
```

分工：**search** 冷启动发现账号，**track** 盯已知账号（评论+原图随 creator 笔记一次抓回，无单独 comments 命令）。熟悉领域后账号已在 config 的 `watchlist.manual` 里，可**只跑 track**：靠库的 `creator_fetched_at` 轮转账号（`creator.batch_size` 每次只碰最久未抓的 N 个，少量多次）。等价直调：`uv run python -m src.pipelines.cli <子命令> --config configs/留学辅导/run.yaml`。

### 离线跑通（无需登录，随时可跑）

```bash
uv run python -m src.pipelines.run_research --config configs/sample.yaml
```

吃 `tests/fixtures/` 样本（含 creator 夹具，watchlist 全路径），产出完整 10 文件，用于开发自测与了解产出格式。

### 真实采集（manual）

**前置一：MediaCrawler** —— 位于 `../MediaCrawler/`（uv 管理，含 Playwright 环境）。

**前置二：采集浏览器（CDP，一次性设置）** —— Chrome 136+ 出于安全默认 profile 会**静默忽略**调试端口参数，须用专用 profile 直接调二进制启动（`open -a` 只会把参数丢给已运行实例，不要用）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir="$HOME/.xhs-recon-chrome" \
  >/dev/null 2>&1 &     # 静音：Chrome 内部日志不刷终端；成功标志=curl 有返回

curl -s http://127.0.0.1:9222/json/version   # 有 JSON 返回 = 端口就绪
```

首次在该窗口登录小红书（扫码一次），登录态存在专用 profile 里，**之后每次采集免登录**；该窗口与日常 Chrome 互不影响。采集期间不要操作该窗口。

**跑（完整管线，含 watchlist/creator/专业度素材）：**

```bash
./run.sh real    # 或直调：uv run python -m src.pipelines.cli research --config configs/留学辅导/run.yaml
```

配置里的关注账号在 `watchlist.manual`（支持纯 user_id 或主页 URL，写错会显式报错）；`watchlist.auto_top_n` 从搜索榜单自动补足，总量上限 `max_total`（默认 10）；每账号取最新 `creator.notes_per_account` 篇（默认 10）。逐账号串行单并发拉取，跑一次算一次，无定时任务。

也可用旧集成脚本单验采集链路：`uv run python scripts/integration_mediacrawler.py --config configs/sample_mediacrawler.yaml -v`

一次运行会起 2-3 个 MediaCrawler 子进程（每关键词一次 search + 一次 detail 读评论），每个子进程在采集浏览器里新开标签页驱动，属正常现象。9222 不可达时 MediaCrawler 会白等 60s 再回退自带浏览器（能跑但慢，且可能要求扫码）。

## 产出（`data/exports/<时间戳>/`，按运行归档不覆盖）

每次运行导出到独立时间戳目录（与 `data/logs/run-*.log` 同一时间戳，可互相对上）；`data/exports/latest/` 软链永远指向最新一次——**日常看 `data/exports/latest/report_input.md`，或 `./run.sh web` 生成可视化 `index.html`（账号情报卡 + 内容流两视图，离线 file:// 直接开）；要交给下游程序/LLM 则 `./run.sh bundle` 打成研究快照 zip**。

| 文件 | 内容 | 给谁 |
|---|---|---|
| `report_input.md` | 账号排名 + 典型笔记链接 + 高赞评论织入 | **人读 / 喂 LLM 做竞品分析的主入口** |
| `account_profile.csv` | watchlist 账号专业度分项：垂直度（内容命中领域关键词占比）/ 窗内发帖数 / 综合分，可复算 | 机器 |
| `creator_profiles.csv` | watchlist 账号官方主页档案：**verify_type（0未认证/1个人/2机构认证）** / red_id（小红书号）/ 粉丝 / 简介 / IP——机构判定 `verify_type==2` 机械可判 | 机器 |
| `watchlist.csv` | 关注账号清单（manual/auto 来源标注） | 机器 |
| `creator_notes.csv` | 每账号最新 N 篇原样导出（不窗过滤；互动列 0=未采集） | 机器 |
| `accounts.csv` `notes.csv` | 全量账号/笔记明细 | 机器 |
| `account_rank.csv` | 账号评分排名（笔记数×关键词命中×互动加权） | 机器 |
| `typical_notes.csv` | 每账号代表作及入选理由 | 机器 |
| `comments.csv` | 典型笔记一级评论，表头固定 `body,note_id,like_count,collected_at` | 机器 |

一切新能力 opt-in：不配 `watchlist` 段 → 不产 watchlist/creator_notes/account_profile/creator_profiles 四件，行为与 v0 一致；`comments.enabled: false` 时不产 `comments.csv`。管线口径**诚实不假装**：某步采集失败 → 记入 error、该部分为空、其余照出（creator 部分账号失败时保留成功账号的笔记并在日志警告）。

## 数据目录

- `data/raw/<run>/` — MediaCrawler 原始 JSONL，按运行时间戳隔离（**评论 raw 含作者字段，仅本地留存，gitignore**）；
- `data/exports/<时间戳>/` — 最终导出，按运行归档不覆盖；`exports/latest/` 软链指向最新（gitignore）；
- `data/logs/` — 管线运行日志（gitignore），文件名形如 `run-<run_id>.log`；
- 配置**按主题分目录**：`configs/<主题>/run.yaml`（运行配置）+ `keywords.yaml`（词表资产）+ `watchlist.yaml`（账号资产）——现有 `configs/留学辅导/`（日常）与 `configs/测试/`（最小链路验证：1 词 × 3 账号）；`configs/sample.yaml`（fixture demo）保持根位，供预飞/CI 引用；
- 资产引用机制：`run.yaml` 里 `keywords_file` / `watchlist_file` 指向同主题资产文件；与 inline 同键互斥（双源报错）。新赛道 = 新建一个主题目录三件套。

## 日志

控制台默认显示 INFO 阶段行；加 `--verbose` / `-v` 后控制台显示 DEBUG。每次运行会写 `data/logs/run-<run_id>.log`，文件日志固定 DEBUG，目录可在配置的 `logging.dir` 调整，也可用 `logging.file_enabled: false` 关闭。

真实 MediaCrawler 子进程输出会完整落到本次 raw 目录的 `mediacrawler.log`。复盘真实采集时先看 `data/logs/run-*.log` 定位阶段和 raw_path，再打开对应 `mediacrawler.log` 看 MediaCrawler 原始 stdout/stderr。

## 架构

```
pipelines（组装点：读配置、_build_adapter 注入、编排：搜索→窗过滤→聚合→打分
          →watchlist→creator→专业度→选典型→评论→导出）
   ↓ 依赖
core（平台无关研究核心：expander/aggregator/ranker(+profile)/time_window/
     watchlist/selector/exporter/ports——内部 0 处 "xhs"）
   ↓ 依赖
models（pydantic 领域模型）

adapters（实现 core 的 ResearchAdapter 端口：search / fetch_creator_notes / fetch_comments）
  ├─ fixture_adapter    读本地 JSONL（也是官方测试替身，含 creator 夹具）
  ├─ mediacrawler_adapter 子进程调 MediaCrawler（search + creator 模式）+ 读回解析
  └─ parsers.py         JSONL → 模型（评论身份字段在此丢弃；主页 URL→user_id 归一化在此）
```

MediaCrawler fork 的唯一改动：CLI 可选 `--sort_type` 透传（缺省不覆盖其配置默认值）。

依赖铁律：`pipelines → core → models`；core 永不 import adapter；实现选择只发生在 [run_research.py](src/pipelines/run_research.py) 的 `_build_adapter`（composition root）。

## 测试

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

全离线（mock 子进程 + fixtures），不依赖真实小红书访问；红线（评论四字段、core 平台无关）有专项用例。真实采集不进 CI，靠 manual 集成脚本验收。

