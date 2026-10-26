---
name: kg-delta
version: "2026.1"
description: 知识缺口状态机。当用户说"检测缺口"、"补知识"、"补这本书"、"创建 delta"、"处理 内容审计记录"、"处理缺口"、"kg-delta"时触发。缺口发现 → 建卡 → 调研（页图实证）→ 草稿 → 审核 → 发布收尾，一条 delta 一张卡走完整状态机。
---

# KG Delta — 知识缺口状态机

主动找「缺什么知识」并补齐。与 kg-ingest 互补：delta 主动发现缺口，ingest 被动接入成套教材。

## 知识库位置

`knowledge/` 仓。缺口台账（卡目录 + 索引）**不入公开仓**，维护在仓外私有位置；本仓只保留发现与修复的规范，不含卡片与审计记录。

## 触发词 → 模式

| 触发词 | 模式 |
|---|---|
| 「检测缺口」「扫一遍缺什么」 | 自动检测：`python3 tools/kg/diag_gap.py` + lint warning + 与 PG catalog 的 coverage 差异 |
| 「补这本书」「补知识」「创建 delta」 | 管线 A：建卡 |
| 「处理缺口」「处理 delta」 | 管线 B：调研 + 草稿 + 发布 |

与兄弟 skill 分界：补新知识块走 delta；单点小改走 kg-edit；成套教材接入走 kg-ingest。

## 管线 A：建卡

1. **骨架**：在仓外台账取最大序号 +1 → 创建 `DELTA-{序号}-{slug}/` + `delta.md`（frontmatter：type/status: open/severity/labels）+ `assets/`（放资料：OCR 文本、页图截图、对照摘录）
2. **判定**：对照图谱与 content 判断缺口类型（missing_textbook 整书 / missing_section 缺节 / content_thin 内容偏薄 / correctness 校正）
3. **成型**：正文写「描述 / 证据（页图、coverage 数据、lint 输出）/ 期望产出」

**编号占用约定**：编号以目录名为占用凭据——删卡/空号不复用（git 历史与 index 不断链），发布不改号；同号多目录先改号消歧。

## 管线 B：处理

1. **选择**：「处理缺口」→ 列 status: open 的卡，按 severity（high>medium>low）+ 创建时间排序
2. **调研**：读 delta.md + assets/ → **忠实性红线：一切内容以原始 PDF 页图为校准源**（页图号 = 印刷页 + imageOffset，rapidocr 核对）；需要录新书走 kg-ingest 管线
3. **草稿**：content 增补/修正方案（涉及整书/成节走 kg-ingest 管线产出）→ status → drafted → review → 向用户展示摘要
4. **审核**：通过 → approved；有意见 → 改后 review_round += 1 → 回到 review
5. **发布**：approved → 执行写入 → 过**收尾四件套** → status → resolved

**收尾四件套（任何图谱写入路径都适用：ingest/手工 edit/脚本）**：

1. content/graph 变更与 delta 记录一致（缺什么补什么，不多不少）
2. `pnpm kg:lint` + `pnpm kg:build` 刷 `dist/` 计数，核对 stats 增量符合预期
3. `tools/kg/state/log.md` 追加条目（依据 / content 更新 / 图谱更新 / 验证，四段式）
4. delta.md 状态推进 + 仓外台账索引同步

（教训来源：某次手工路径写入后跳过收尾，四件套缺三，靠 kg-review 才追回——与上游 omp-knowledge 内容审计记录 同型事故。）

## 状态机

collecting → open → researching → drafted → review →（changes_requested → drafted）→ approved → resolved

进入条件注解：图谱/content 已出现本 delta 的产出 ⇒ 状态至少 drafted（不得「卡片未动、图谱已写」错位）；resolved = 期望产出落地 + 四件套完成。

## 硬约束

- **单次只处理 1 张卡**，避免上下文溢出
- **content 忠实性红线**：一切教材内容以页图为准，禁止发明；OCR 无法证实的表述不改
- **已有实体优先复用 ID**：调研先查图谱是否已有相似概念
- **日期锚点与内部编号不落图谱/content**：commit id、任务编号、"20XX 版新增"类表述只留在 delta 卡证据段
- **sourceRef 指向 content 文件**：不指向 delta 卡或外部资料
- **git push 需用户确认**

## 与兄弟 skill 分界

| skill | 场景 |
|---|---|
| kg-delta | 找缺口 / 补知识块（状态机管理） |
| kg-ingest | 成套教材/成块素材接入 |
| kg-edit | 已有内容的单点小改 |
| kg-review | 巡检检出问题（检出不修复） |
| kg-curriculum | 跨册成网/课标对齐 |

## 非目标（YAGNI）

- 不做单点微调——走 kg-edit
- 不做只读查询——走 kg-query
- 不引入 JIRA/Confluence 等外部源——本仓缺口证据只来自页图/coverage/lint 输出

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 自 omp-knowledge kg-delta（2026.14）移植并领域适配：剥离 JIRA/Confluence/三源回顾，忠实性红线与收尾四件套按本仓门禁改写；初始 5 张缺口卡建档 |
