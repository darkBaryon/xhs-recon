# xhs-recon

个人自用、本地运行的内容平台研究工具。目前接入小红书，架构上允许后续增加抖音等平台。

项目把不同需求拆成独立 application：竞品账号分析、关键词搜索、watchlist 更新、组合研究、
媒体回填。application 只表达业务规则，采集方式通过 Port 注入；平台实现负责浏览器、请求、
批次和 payload 翻译。

## 已有功能

### 竞品账号分析 `account`

从 YAML 读取一组账号，采集账号帖子并输出：

- 账号内容数量和点赞、收藏、评论、分享汇总；
- 帖子明细及互动排序；
- 发布时间分布和代表内容链接；
- 默认不采评论，可在账号分析配置中显式开启。

### 关键词搜索 `search`

从 YAML 读取主关键词和扩展词，按综合或时间顺序搜索，并保存：

- 搜索结果列表可见的标题、作者和互动数；
- 每条内容对应的搜索关键词；
- 跨关键词去重后的账号排名；
- 可选发布时间窗口过滤。

搜索是轻量发现接口：只读取搜索列表卡片，不逐帖请求正文详情、评论或媒体。这样既保留账号
发现和关键词归属，也避免一次搜索被放大为大量详情请求。

### Watchlist `watchlist`

从 YAML 读取关注账号，只处理本次到期账号：

1. 一次批量主页列表会话取得最新帖子卡片；
2. 与数据库中的已知帖子做差集；
3. 一次批量详情会话只补新增内容；
4. 按账号独立保存结果和刷新时间。

失败账号不会被标记成功。`track` 是 `watchlist` 的快捷别名，`track-all` 会按配置分批巡逻。

### 组合研究 `research`

组合独立的 `search + watchlist` application，并生成稳定研究快照：

- `research.json`：关键词、窗口和 watchlist 配置；
- `accounts.json`：账号档案、来源和搜索评分；
- `notes.jsonl`：搜索与账号内容；
- 快照目录及 zip 包。

### 其他能力

- `backfill`：为数据库中缺少本地媒体的历史内容补详情和图片，不重复抓评论；
- `web`：从本地数据库渲染静态浏览站点；
- `bundle`：定位最近一次 research 快照 zip；
- `migrate-legacy`：将旧表数据幂等迁移到新 schema，默认只对账。

## 快速开始

安装主项目依赖：

```bash
uv sync
```

离线运行，不需要浏览器或登录：

```bash
./run.sh
# 等价于
uv run python -m src.recon.entrypoints.cli research --config configs/sample.yaml
```

真实采集默认读取 `configs/留学辅导/run.yaml`。更换领域时通过 `CONFIG` 指向另一份长期配置，
不需要临时写 Python 脚本：

```bash
CONFIG=configs/AP-ALevel/run.yaml ./run.sh search
CONFIG=configs/留学辅导/run.yaml ./run.sh account
CONFIG=configs/留学辅导/run.yaml ./run.sh track
```

常用命令：

```bash
./run.sh account      # 竞品账号分析
./run.sh search       # 关键词轻量搜索
./run.sh track        # 更新一批到期 watchlist 账号
./run.sh track-all    # 分批巡逻全部到期账号
./run.sh research     # search + watchlist + bundle
./run.sh backfill     # 历史内容媒体回填
./run.sh web          # 渲染并打开本地站点
./run.sh bundle       # 返回最近一次研究快照
./run.sh browser      # 只启动或检查采集浏览器
```

## 真实采集环境

项目使用同级目录中的 MediaCrawler fork：

```text
xhs-recon-lab/
├── xhs-recon/
└── MediaCrawler/
```

真实采集复用专用 Chrome profile 的登录状态。`run.sh` 会自动检查并启动 CDP 9222；第一次使用
时，在打开的专用窗口中手动登录小红书即可。采集期间不要操作该窗口，也不要同时运行多个真实
采集任务。

```bash
./run.sh browser
curl -s http://127.0.0.1:9222/json/version
```

边界约束：低频、小范围、单并发、不使用代理池，不执行点赞、评论、私信等写操作，不绕过
验证码或平台安全控制。检测到 CAPTCHA、IP 限流或登录失效后，搜索会停止当前会话和后续关键词
批次，不自动连续重试。

## 配置

配置按领域长期保存，不需要为每次运行写新脚本：

```text
configs/<领域>/
├── run.yaml          # 运行方式、限额、排序、存储、输出
├── keywords.yaml     # 主关键词及扩展词
├── watchlist.yaml    # 长期关注账号（需要 watchlist/research 时）
└── accounts.yaml     # 竞品账号（需要 account 时）
```

关键配置示例：

```yaml
provider: mediacrawler
mediacrawler_dir: ../MediaCrawler

keywords_file: configs/AP-ALevel/keywords.yaml

search:
  pages: 1
  limit: 3
  sort: time_descending
  window_days: 90
  batch_size: 4

creator:
  notes_per_account: 3
  batch_size: 1
  refresh_days: 14

comments:
  enabled: false

store:
  enabled: true
  database: xhs_recon
```

`limit` 是保留的列表结果数，不代表登录和页面初始化等全部网络请求。搜索列表模式不会再为每条
候选追加详情请求。不同关键词的归属以独立关系保存，同一帖子被多个关键词搜到时不会互相覆盖。

## 输出和数据

不同 application 使用独立目录：

```text
data/exports/
├── account/<run>/
│   ├── account_summary.csv
│   ├── account_contents.csv
│   └── account_report.md
├── search/<run>/
│   ├── search_contents.csv
│   ├── search_accounts.csv
│   └── search_report.md
├── watchlist/<run>/
│   ├── watchlist_contents.csv
│   └── watchlist_report.md
└── research/
    ├── <领域>-<run>/
    └── <领域>-<run>.zip
```

- `data/raw/`：MediaCrawler 原始 JSONL 和完整子进程日志；
- `data/logs/`：application 阶段日志；
- `data/media/`：持久化图片库；
- MySQL：内容实体、关键词关系、watchlist 状态和变更日志。

运行数据、日志和导出不应提交到 Git。

## 架构

```text
src/recon/
├── domain/                 # 平台无关实体和纯策略
├── application/
│   ├── ports/              # 采集、仓储、输出、时钟接口
│   ├── account/            # 竞品账号分析
│   ├── search/             # 关键词搜索
│   ├── watchlist/          # 增量账号跟踪
│   ├── research/           # 用例组合
│   └── backfill/           # 历史媒体回填
├── platforms/
│   ├── registry.py         # 平台能力注册
│   └── xhs/                # XHS collector、翻译和契约
├── infrastructure/         # MySQL、迁移、文件输出、查询、媒体
└── entrypoints/            # CLI、YAML、日志、进度、依赖装配

src/adapters/
├── fixture_adapter.py      # 离线测试替身
├── mediacrawler_adapter.py # MediaCrawler 进程、会话、限速和熔断
└── parsers.py              # 平台 payload 边界解析
```

采集 Port 按平台能力定义，而不是按 application 重复定义：

- `SearchCollector`：关键词列表发现；
- `CreatorFeedCollector`：批量账号主页列表；
- `ContentDetailCollector`：指定内容详情、评论和媒体。

`account` 与 `watchlist` 组合相同的 CreatorFeed/ContentDetail 能力，但各自决定全量或增量业务
规则。未来增加抖音时，可以只注册已经支持的能力，不需要复制整套业务流程或提供空实现。具体
扩展方式见 [平台接入指南](docs/平台接入.md)。

依赖方向：`domain ← application ← platforms/infrastructure ← entrypoints`。具体实现仅在
`entrypoints/container.py` 组装。

## 日志和进度

控制台默认输出 INFO 阶段日志；`-v/--verbose` 开启 DEBUG。真实 MediaCrawler 输出会完整保存到
对应 raw 目录的 `mediacrawler.log`。

TTY 中显示 application 级进度；非 TTY 环境仍持续输出阶段、批次、已处理数量和失败信息。
日志没有错误不代表浏览器页面一定没有出现验证提示，看到平台验证页时应立即停止真实采集并人工
确认账号状态。

## 测试

```bash
uv run ruff check src tests scripts web
uv run ruff format --check src tests scripts web
uv run pytest -q
python3 workbench/tools/build_views.py --check
```

测试全部离线运行，通过 fixtures 和 mock 子进程覆盖 application、Port 契约、数据库、迁移、
输出、进度和风险熔断；CI 不访问真实平台。

设计与实施记录位于 [工作台](workbench/index.md)。
