> ⚠️ **已退役**：ExamModel 实体、`applies_to` 边与 `supplements/` 载体已随 v4（2026-09-27）章节区块融合删除，解题方法正文现写在节 md 的 `## 解题模型` 区块。本文件仅存档，启用前需整体改写。

# SKILL_08 - 抽取中考解题模型（ExamModel）

从教材章节/习题中提炼「可迁移的解题模型、思想方法、易错点」。分层 v2 下产出分两处：**身份节点**（id/title/aliases/domain/summary/sourceRef）追加进 `graph/entities/models/<subject>.yaml`（每学科一个聚合文件）；**正文**（method/misconceptions/animations/videos）写 `content/supplements/<subject>/<slug>.md`（frontmatter + 正文），节点 `sourceRef` 指向该 supplement 文件（lint rule 11 强制）。并挂 `applies_to`（→ Concept）与 `exemplifies`（← Exercise）两类边。模型是复习层的聚合核心：`kg:ask review-unit` 按章节聚合命中模型，`review-exam` 按学科/domain 聚合，`models` 反查概念命中的模型。

## 一、什么是 ExamModel（与 Concept/Exercise 的区别）

- **Concept**：知识点本体（「什么是绝对值」）。
- **Exercise**：单道习题（题面 + 难度 + 通用解法）。
- **ExamModel**：**跨越多个知识点的解题范式**（「绝对值化简的『零点分段法』」「一元一次方程行程问题『画线段图找等量关系』」）。一个模型 `applies_to` 多个 Concept，被多个 Exercise `exemplifies`。

> 模型不是「再抄一遍知识点」，而是**可复用的解题套路 + 典型易错点**。

## 二、domain 词表（取其一，用于 review-exam 按专题聚合）

`数与代数` · `图形与几何` · `统计与概率` · `综合与实践`

## 三、输出格式（节点 + 正文两处）

**① 身份节点**：追加进 `graph/entities/models/<subject>.yaml`（聚合数组的一个条目，瘦身，不带正文）：

```yaml
- id: model:<subject>:<slug>
  type: ExamModel
  subject: <学科，如 数学>
  title: <模型名，如 绝对值化简·零点分段法>
  aliases: [<别名/俗称，如 分段讨论>]
  domain: <数与代数|图形与几何|统计与概率|综合与实践>
  summary: <一句话说清模型是什么、何时用>
  sourceRef: content/supplements/<subject>/<slug>.md   # 必须指向 supplement（lint rule 11）
```

**② 正文**：写 `content/supplements/<subject>/<slug>.md`，frontmatter + 正文（正文即 method，加载时由 `supplements.ts` 水化回节点）：

```markdown
---
id: model:<subject>:<slug>
origin: <content/.../chapters/Cx/sections/Sx.md 或 第三方 modules 文件>
misconceptions:
  - <易错点1>
  - <易错点2>
animations:            # 可选：key 对齐第三方 zk-anim 的 data-anim 命名
  - {key: numberLine, description: <一句话说明该动画演示了模型的哪一步>}
videos:                # 可选：仅挂载已校验可达的视频
  - {platform: bilibili, url: <url>, title: <标题>}
---
<解题步骤/套路，2-5 步，即 method 正文>
```

## 四、关系落地（两个独立 yaml）

`graph/relations/applies_to.yaml`（from=模型, to=概念）：
```yaml
- from: model:数学:绝对值化简·零点分段法
  to: concept:数学:绝对值
```

`graph/relations/exemplifies.yaml`（from=习题, to=模型）：
```yaml
- from: exercise:BSDU-7-1-Math-2-S1-E1
  to: model:数学:绝对值化简·零点分段法
```

## 五、抽取流程（按章节）

1. 读 `content/<年级>/<册>/<学科>/<教材>/chapters/Cx/sections/*.md` + 该章各节 `content/<...>/<教材>/items/Cx-S*.md` 的「## 习题」锚点段落。
2. 识别该章可提炼的**解题模型**（通常每章 1–2 个）；跨章通用模型（如「方程思想」「数形结合」）归入中考模型层（数学先行）。
3. 用 `applies_to` 挂到**已存在的 Concept**（先用 `kg:ask concepts <sectionId>`（接受 sectionId，非 chapterId）或查 `graph/entities/concepts/<学科>.yaml` 确认概念 id，禁止臆造）。
4. 用 `exemplifies` 挂到**已存在的 Exercise**（从 items 文件的 `exercises` 键取真实 id；一条模型至少 1 道例题，优先选综合性/易错题）。
5. 在对应 Concept 条目上补 `misconceptions` 字段（数组，易错点）；若该条目无此字段则新增。
6. 在相关 Exercise 上补四字段：`difficulty`(易/中/难)、`commonError`、`generalMethod`、`adaptedFrom`（借鉴第三方内容时填其来源，自编留空）。

## 六、已落地约束（来自 lint rule 9 / 11）

ExamModel 必须同时满足，否则 `kg:lint` 报 error 且不通过 build：
- ≥ 1 条 `applies_to` 指向已存在的 Concept
- ≥ 1 条 `exemplifies` 指向已存在的 Exercise
- 非空 `sourceRef`，且**必须指向 `content/supplements/`**（rule 11 supplement-ref：正文归 supplements，节点只留身份）

> 因此「先建模型后补题」会卡 lint。正确顺序：模型与它的例题/概念边**同批次提交**。

## 七、质检清单（提交前自测）

- [ ] `kg:ask models <任一 applies_to 的概念>` 能返回该模型
- [ ] `kg:ask review-unit <章节>` 的 `models` 字段含该模型
- [ ] `kg:lint` 0 error（尤其 exam-model 规则）
- [ ] 所有 `applies_to`/`exemplifies` 的 id 在图中真实存在（referential integrity）
- [ ] 不臆造 Concept/Exercise id；视频仅挂已校验可达链接

## 八、范围

- **数学先行**；英语/物理/化学/历史/语文/生物/地理/道法为后续扩科任务，不在本 skill 首轮范围。
- 借鉴第三方 `chuzhongstudy-main` 时只取其**结构/思路/素材元数据**，用 `adaptedFrom` 追溯，不整段照搬内容。
