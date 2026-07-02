---
title: 专业账号追踪 期2 creator spike 验证记录
type: 验收记录
case: 专业账号追踪
phase: 2
created: 2026-07-02
---

# Spike：creator 模式纯 user_id 可行性验证

**日期：** 2026-07-02  
**执行人：** 自动化 spike（Claude Code）

---

## 执行命令

```bash
cd /Users/xinyue/VSCode/ws_2026/xhs-recon-lab/MediaCrawler && uv run python main.py \
  --platform xhs --type creator \
  --creator_id 601d0481000000000101cc46 \
  --lt qrcode \
  --save_data_option jsonl \
  --save_data_path /Users/xinyue/VSCode/ws_2026/xhs-recon-lab/xhs-recon/data/raw/spike-creator-20260702 \
  --enable_ip_proxy no --get_comment no --get_sub_comment no \
  --max_concurrency_num 1 --crawler_max_notes_count 5
```

目标账号：「陈皮糖」（user_id: `601d0481000000000101cc46`），不携带 xsec_token。

---

## 结果：成功

产出文件：`xhs-recon/data/raw/spike-creator-20260702/xhs/jsonl/creator_contents_2026-07-02.jsonl`

- **条数：** 5 条（按 `--crawler_max_notes_count 5` 上限）
- **登录态：** CDP 连接成功（本地浏览器 port 9222），扫码重新登录后正常拉取

### 字段清单（共 21 字段）

与 search 模式完全一致，无增减：

| 字段 | 说明 |
|------|------|
| note_id | 笔记 ID |
| type | normal / video |
| title | 标题 |
| desc | 正文/话题标签 |
| video_url | 视频链接（图文为空） |
| time | 发布时间（epoch ms） |
| last_update_time | 最后更新时间（epoch ms） |
| user_id | 作者 ID |
| nickname | 昵称 |
| avatar | 头像 URL |
| liked_count | 点赞数 |
| collected_count | 收藏数 |
| comment_count | 评论数 |
| share_count | 分享数 |
| ip_location | IP 归属地 |
| image_list | 封面图 URL |
| tag_list | 标签（逗号分隔） |
| last_modify_ts | 写入时间戳（ms） |
| note_url | 笔记完整 URL（含 xsec_token） |
| source_keyword | 来源关键词 |
| xsec_token | 笔记的 xsec_token |

### 时间新近性

所有 5 条 `time` 字段均约为 `1782997379000 ~ 1782997453000`，换算为 **2026-07-02**（即今天），属于该账号最新一批发帖，拉取结果时效性良好。

### 互动数字段

`liked_count`、`collected_count`、`comment_count`、`share_count` 均为空字符串（`""`）——这是 creator 模式通过主页列表 API 拉取的已知限制；search 模式通过搜索结果 API 能返回这些数值。如需互动数，需额外调用单篇详情接口。

### source_keyword 字段

全部为空字符串 `""`（与预期一致：creator 模式不来自关键词搜索，无来源词）。

---

## 对期2方案的结论

**纯 user_id 可用，无需完整 URL / xsec_token。**

- MediaCrawler creator 模式只需 `--creator_id <user_id>` 即可成功拉取指定账号主页最新笔记。
- 字段 schema 与 search 模式完全一致（21 字段），下游处理管道无需改动。
- 互动计数字段在 creator 模式下为空，若期2需要互动数排序，需补充单篇详情调用或仅依赖 search 模式数据。
- `source_keyword` 恒为空，期2如需区分来源，可用 `type=creator` 标记加以区分。

**期2方案推荐：** 直接使用 `--type creator --creator_id <user_id>` 追踪专业账号，不需要从完整帖子 URL 中提取 xsec_token，降低维护成本。
