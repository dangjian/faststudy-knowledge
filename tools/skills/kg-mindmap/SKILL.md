---
name: kg-mindmap
version: "2026.1"
description: 把知识库的章节树、part_of 层级、先修 DAG、相关关系组装成 Mermaid 脑图。LLM 读取图谱切片后生成，kg_ask.ts 提供有界聚合。
---

# kg-mindmap — 知识脑图（Mermaid）

## 何时用
- 用户要「整理脑图 / 思维导图 / 知识框架 / 章节结构图」。
- 范围可是：整本教材 / 单章 / 单节 / 单个概念及其关系网。

## 输入模式（先确定 scope）
| 用户意图 | 锚点 | 入口命令 |
|----------|------|----------|
| 整本教材结构 | `textbookId` | `tree <textbookId>` |
| 单章/单节概念网 | `sectionId` | `mindmap <sectionId>` |
| 单个概念辐射网 | `conceptId` | `related` + `partof` + `prereq` + `covered` |

## 生成流程

### A. 章节结构脑图（教材级）
1. `pnpm exec tsx tools/kg/src/kg_ask.ts tree <textbookId>` 拿章/节树。
2. 渲染 Mermaid `graph TD`：
   ```
   textbookId[教材名] --> C1[章1] --> S1[节1.1] & S2[节1.2]
   C1 --> C2[章2] --> ...
   ```
3. 若需把每节的概念也铺开：对每个节跑 `concepts <sectionId>`，概念挂到对应节下。

### B. 概念辐射脑图（节 / 概念级）
1. 节级聚合：`pnpm exec tsx tools/kg/src/kg_ask.ts mindmap <sectionId>`
   返回每个概念的 `{concept,title,partOf,prereq,related,demonstrates}` 数组，直接喂 LLM 组装。
2. 概念级：分别拉 `related` / `partof` / `prereq` / `covered` 切片。
3. 渲染策略：
   - **层级**：`part_of` 用有向边（整体→部分）。
   - **先修链**：`prerequisite` 用有向边（先→后），可标注 `classDef` 区分。
   - **相关**：`related` 用虚线/灰色边（网状，非层级）。
   - **例证**：`demonstrates`（Item→Concept）可挂在概念旁作叶节点。
4. Mermaid 节点数控制：单图建议 ≤ 40 节点；过大时按章/按子主题拆分多张图，或只保留「核心概念 + 直接先修/相关」。

### C. 样式与可读性
- 中文节点用 `[]` 矩形；用 `subgraph` 给「先修」「相关」「例证」分组。
- 关系边加 label（`prereq`/`related`/`part_of`）避免歧义。
- 输出同时给：① Mermaid 代码块；② 一句话说明 scope 与缺失关系（如「part_of 图谱暂为空，未展开整体-部分」）。

## 反模式
- ❌ 全量读图谱拼大图（用 `tree`/`mindmap` 有界聚合）。
- ❌ 把 `related` 当层级画成树（它是网状，用虚线）。
- ❌ 编造图谱没有的关系边。

## 边界
- `part_of` 在图谱中当前为空（待 LLM 语义抽取），脑图里相应分支标「未录入」。
- 概念网跨年级时，`prereq`/`related` 可能指向其他教材概念，正常展开并注明出处教材。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 初版版本化（借鉴 omp-knowledge kg-* 系列的版本化实践） |
