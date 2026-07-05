# 领域研究快照

本 zip 是「{topic}」赛道一次采集的完整研究快照，供下游程序 / LLM 分析（人读走 `run.sh web`）。

## 文件

- `research.json` — 研究**输入侧**：这次搜了哪些词、扩展成什么、时间窗、watchlist 配置。
- `accounts.json` — **账号侧**：每个账号的认证、主页档案、打分、笔记 id 列表。
- `notes.jsonl` — **内容侧**：全部笔记，一行一条 JSON，含正文全文。

## 字段口径（务必知道，否则会误读）

- **互动数 `like_count/collect_count/comment_count`**：`side=creator` 的笔记这三项恒为
  **0——是「未采集」不是真实 0**（creator 主页列表 API 不返回互动数）。真实互动只在
  `side=search` 的笔记里。
- **`verify_type`**（账号官方认证）：`2`=机构/企业认证（专业号）· `1`=个人认证 ·
  `0`=未认证 · `-1`=档案未含该字段（个人号常见）。判机构号看 `verify_type==2`。
- **`in_window`**（笔记是否在时间窗内）：`true`=发布时间在近 `window_days` 天内 ·
  `false`=出窗 · `null`=缺发布时间。窗口大小见 `research.json.window_days`。
- **`source`**（账号来源）：`self`=**本方账号（我们自己的号，非竞品，分析时应单独对待）** ·
  `manual`=手动关注 · `auto`=搜索榜单自动入选 · `rank`=纯搜索榜单（无 watchlist 时）。
- **打分**：`account_score`=搜索侧加权（笔记数×关键词命中×互动）；
  `profile_score`=垂直度×10 + 窗内发帖数；均可能为 `null`（该侧未采）。
- **`side`**：`creator`=从账号主页拉的最新笔记 · `search`=关键词搜索命中的笔记。

## 采集口径

- 只读公开内容，单账号真实登录、单并发、低频；不含私密数据 / 互动写操作。
- `collected_at` 见 `research.json`。
