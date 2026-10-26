---
name: kg-edit
version: "2026.1"
description: 知识库单点微调。改已有实体字段/增删单个实体或单条边/修正正文小错。由"改/补/删掉/修正"等具体动词触发;「更新图谱/加知识」类模糊入口词归 kg-help,成块新知识录入归 kg-ingest/kg-extract。
---

# kg-edit — 单点微调

## 何时用
- 改已有实体的字段值(title/aliases/explanation/difficulty 等)
- 增删单个实体、单条关系边
- 修正 content 正文/items 条目的小错(错字、错答案、错难度)
- **不适用**:成块新知识(走 kg-ingest/kg-extract);批量数据修改(走脚本 + 用户确认)

## 流程(三色标注见 tools/kg/skills/00-META.md)

1. `[SCRIPT]` **定位**:按 ID 前缀速查(graph/index.md)grep 到目标文件;涉及概念同时查 relations/ 中引用
2. `[AI]` **判断改哪边**:content 正文错 → 只改 content;图谱身份/边错 → 只改 graph;两边都涉及 → 双改。仅图谱改动须在汇报中标注"仅图谱"
3. `[HUMAN]` **展示计划**:列出"改哪个文件、哪一处、改成什么",等用户确认——所有写回都走此门,无例外
4. `[AI]` **写回**:精准编辑,不动无关行;实体 id 一律不改(id 变更是迁移不是微调)
5. `[SCRIPT]` **验证**:`pnpm kg:lint` 0 error;涉及节点/边计数变化时跑 `pnpm kg:build` 并核对 stats 增量符合预期
6. `[AI]` **落盘**:变更涉及建模取舍时,在 `tools/kg/state/log.md` 追加 fix 段

## 硬边界
- 单次会话只处理一批相关的小改动;不做批量重构
- 严禁顺手"改进"无关条目
- 删除实体前必须先查该 id 在 relations/ 与 items 中的全部引用,悬空引用一并处理

## 写回内容边界(防回流)

写回的 `explanation`/`misconceptions`/`aliases` 只写**教学语义**（是什么/为什么易错），不得回流：
- 过程性元语言（谁确认的、来源对比、口径演进）——留 `tools/kg/state/log.md`
- 日期锚点与内部编号（"20XX 版新增"、commit id、任务编号）
- 实现细节 token（文件路径、脚本名、表名）

graph/ 语义层与 content/ 教材正文都不承载调研过程，二者只写知识事实。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 新增「写回内容边界（防回流）」 |
