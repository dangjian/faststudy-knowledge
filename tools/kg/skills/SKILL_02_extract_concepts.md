# SKILL_02 - 抽取概念 + 去重

从 section 文本识别知识点，生成 Concept 实体。**不同学科的概念类型不同，需根据学科调整。**

## 概念类型按学科

| 学科 | 概念类型 | 示例 |
|------|---------|------|
| 英语 | 语法点、词汇主题、发音规则、写作技能 | 一般现在时、动物词汇、wh-问句 |
| 语文 | 写作手法、修辞手法、文章结构、表达方式、文学体裁 | 对比手法、人物传记、夹叙夹议、引用 |
| 数学 | 定理、公式、概念定义、解题方法 | 整式乘法、同位角、概率定义 |

## 输出格式

写入 `graph/entities/concepts/<subject>.yaml`（**每学科一个聚合文件，顶层为实体数组**；经 `ingest.ts` 的 `writeExtract()` 按 id 幂等追加，不再一概念一文件）。单条概念格式：
```yaml
id: concept:<subject>:<slug>     # slug 以中文概念名为主(如 concept:数学:杠杆),与存量数据一致;去重按 title
type: Concept
subject: <subject>
title: <中文标题>
aliases: [<英文别名>]
category: <分类：grammar/vocabulary/写作手法/修辞手法/定理...>
explanation: <1-2 句定义>
sourceRef: content/<textbookId>/chapters/C<n>/sections/S<m>.md
```

## 去重规则

1. 匹配 `graph/entities/concepts/<subject>.yaml` 聚合文件内已有概念
2. 按 `title` 精确匹配 + `aliases` 模糊匹配
3. 命中则复用其 id，不新建条目
4. 新建时 slug 不可与已有冲突
5. 跨教材概念（如"对比手法"在多个课文出现）只建一次，通过 covered_by 关联多个 section
6. **已有实体摘要注入**：LLM 抽取 prompt 必须拼入该学科已有实体的 `id/title/aliases` 清单（从 `graph/entities/concepts/<subject>.yaml` 提取），让模型在生成阶段即复用已有 id；跨教材同名概念（如"数轴"七上/七下均现）严禁造 `-2`/`-v2` 变体 id

## ontology 约束

type 固定 `Concept`，subject 必填，category 建议填写以区分概念类型。

## 完整性约束（必查）
- **穷尽**：一个 section 内所有可教概念都要抽出，不只抽"显眼"的；定义、定理、公式、手法、规则、主题词都在内。
- **必挂 covered_by**：每个新建 Concept 的 `sourceRef` 必须指向它所在的 section，SKILL_04 据此生成 `covered_by`。不允许出现"抽了概念却无任何 section 覆盖"的孤儿概念。
- **跨教材去重优先**：不同年级/课文出现的同一概念（如"比喻""一次函数"）只建一次，靠 `covered_by` 关联多个 section，避免重复实体。