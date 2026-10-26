---
name: kg-extract
version: "2026.1"
description: 抽取层规范——概念/词书/关系的抽取约定，指向现有 SKILL_02~05，并补充 part_of 语义抽取与去重/幂等规则。
---

# kg-extract — 抽取层

## 何时用
- 摄入管线中做具体抽取（概念、词/句/汉字、关系、公式）。
- 用户要「抽这节的概念 / 补关系 / 抽公式」。
- 「更新图谱 / 加知识」类**模糊**入口词由 `kg-help` 统一接管路由,本 skill 不抢注。

## 子步骤 → 现有 Skill（实现细节见之，本 skill 只给规范与衔接）
| 步骤 | 实现 Skill | 产出 |
|------|-----------|------|
| 抽概念 + 跨教材去重 | `knowledge/tools/kg/skills/SKILL_02_extract_concepts.md` | `Concept` 条目追加进 `graph/entities/concepts/<学科>.yaml` 聚合文件 + `covered_by` |
| 抽词书（词/短语/句/汉字） | `SKILL_03_extract_items.md` | `Word/Phrase/Sentence/Character` 写入章节 md 文末 `## 汉字/单词/短语/句子` 四类表格 + `demonstrates` |
| 抽关系 | `SKILL_04_extract_relations.md` | `covered_by`(必)/`demonstrates`(按学科)/`prerequisite`(候选)/`related` |

> 抽取约定：插图只写节 md 文末 `## 插图` 纯文本图注（不派生实体）；解题方法正文写节 md `## 解题模型` 区块（不建实体）。

## 抽取规范（强制执行）
1. **`covered_by` 必选**：每个 `Concept` 至少 1 条，指向所在 `Section`。
2. **概念去重**：每章抽取前先读已有概念列表（同 `concept:<学科>:<名称>` 不重复建）。
3. **已有实体摘要注入**：LLM 抽取 prompt 必须拼入该学科已有实体的 `id/title/aliases` 清单（从 `graph/entities/concepts/<学科>.yaml` 提取）；跨教材同名概念（如「数轴」七上/七下均现）必须复用已有 id，严禁造 `-2`/`-v2` 变体。
4. **关系五类都应产出**（修订后 SKILL_04）：`covered_by`/`demonstrates`/`prerequisite`/`related`/`part_of` 不得为 0；
   含 **跨年级关联**小节（见 `kg-curriculum`）。
5. **`part_of` 须 LLM 语义抽取**（确定性工具不产出）：识别整体-部分（如「三角形」⊃「等腰/直角/等边」），
   写 `part_of` 边。
6. **幂等**：默认不覆盖已存在实体；`--force` 重抽。关系按 `from→to` 去重追加。
7. **错误模式负面清单**：抽取前读 `tools/kg/state/error-patterns/` 对应类别（概念/词书 → entity-errors.yaml，关系 → relation-errors.yaml），把已知模式作为负面清单带入 prompt；文件为空则跳过。回写机制见 `knowledge/tools/kg/skills/00-META.md` §6。

## 遗漏模式清单(抽取完成后自查)

逐条对照:源文本出现下列模式而未产出对应实体,即为遗漏,须补抽:

| 文本模式 | 应产实体 |
|---|---|
| 插图/图形/几何图/示意图 | 节 md 文末 `## 插图` 纯文本图注（v4 起不派生实体、无 demonstrates 边） |
| 黑体术语/定义句("……叫做/称为……") | Concept(+ covered_by 边) |
| 英语课文对话/例句 | Sentence;生词表 → Word;固定搭配 → Phrase |
| 语文生字表/写字表 | Character |
| 解题方法/口诀/易错提醒成段正文 | 节 md `## 解题模型` 区块正文（不建实体） |

自查约束:遗漏列表**不得包含已存在实体**(先按 id/title 对照该学科聚合文件排除,防误报);每种模式计数为 0 时要能说明"该节确实没有此类内容"。

## 修复工具（缺口/补链）
- `fix_covered_by.ts`（`kg:fix:covered`）：由 `sourceRef` 补 `covered_by`。
- `link_orphans_by_title.ts`（`kg:fix:orphans`）：标题定位补链 + 修 `sourceRef`（清 orphan 概念）。
- `infer_relations.ts`（`kg:infer`）：确定性推 `demonstrates`/`related`/`prerequisite` 跨年级骨架。

## 反模式
- ❌ 把 `related`/`part_of`/`demonstrates` 标「可选跳过」（已修订为必产出）。
- ❌ 重复创建同名概念（先查重）。
- ❌ 抽完不等 `lint` 就进下一章（增量正确性靠每章 lint+build 保障）。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 初版版本化（借鉴 omp-knowledge kg-* 系列的版本化实践） |
