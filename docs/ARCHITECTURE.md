# 知识库分层架构

> 当前口径为 **v4（章节区块融合）**。本文描述现行架构；版本演进见文末「演进记录」。

四层正交：**真源 vs 派生**、**共享静态 vs 学生个性化**——`content/`（L1 学什么）与 `graph/`（L2 知识如何连接）为真源，structure 与词书学习项由 content 派生不落盘，学习者数据在应用侧只按 canonical ID 引用。

---

## 1. 四层总览

两条正交轴：**真源 vs 派生**、**共享静态 vs 学生个性化**。

```
L1 content/   学什么(共享·真源)：prose + 文末区块（词书/图注/解题模型/笔记/总结）
      │ 抽取/引用
L2 graph/     知识如何连接(共享·真源)：节点身份 + 边，零正文载荷
      │ build(可重算)
L3 derived    派生层：dist/、structure 节点、复习层视图、mastery —— 一律不入库
      ▲ 仅按稳定 canonical ID 引用，绝不复制
L4 学习者层  学生个性化(应用侧·不在本仓)：只按稳定 canonical ID 引用图谱
```

### 判定标准（每条内容问三个问题）

| 问题 | 答案 → 归属 |
|---|---|
| 是"学的东西"还是"知识间的关系"？ | 正文/词条/方法讲解 → L1；节点身份+边 → L2 |
| 能从别处重算出来吗？ | 能 → L3，不入 git |
| 和某个学生的状态有关吗？ | 有 → L4，只按 canonical ID 引用图谱 |

### 纯知识铁律

知识图谱完全按纯知识构建。`knowledge/` 仓库（L1+L2）做到**零用户数据、零用户代码、零用户字段**——节点与边上不得出现 mastery、薄弱点、学习记录等任何学生态信息；学习者相关代码不进 `tools/kg`。依赖方向单向：应用/学习者侧 → 知识库，永不反向。

---

## 2. 各层内容明细

### L1 content/ — 学什么

- `<年级>/<学期>/<科目>/<textbookId>/`
  - `index.md`：front-matter 承载教材元信息 + `chapters` 章节目录（id/title/order/pageRange/sections，**结构唯一源**）
  - `chapters/C<n>/index.md`（章级真源，可带章级词书区块如汉字表）、`chapters/C<n>/sections/S<m>.md`（节正文 + 文末区块，约定不变）
  - 节 md 文末区块（v4，固定顺序）：`## 汉字`/`## 单词`/`## 短语`/`## 句子`（词书四类 md 表格，**照常派生实体**）、`## 插图`（纯文本图注，不派生实体）、`## 解题模型`、`## 笔记`/`## 总结`（v4 新增类型，机制先行）

### L2 graph/ — 知识如何连接

- `ontology.yaml`：每类实体带 `layer` + **`storage: content | graph | derived` 声明**，lint 据此校验文件归属：
  - `storage: graph`：Concept
  - `storage: derived`：Textbook、Chapter、Section、Word、Phrase、Sentence、Character（词书四类由 `content` 改判；Figure/ExamModel 已随 v4 退役）
  - `storage: content`：**v3 后已无实体使用**——content 只放 md，不再作为实体源文件形态
  - 另：lint rule 10 断言 **`content/` 下不得出现任何 yaml**；rule 8 断言 `sourceRef` 指向的文件必须存在（2026-08-28 升为 error）
- `entities/concepts/<学科>.yaml`：Concept 按学科聚合为 9 个文件（每文件为实体数组）。保留 id/type/subject/title/aliases/category/一句话 explanation/misconceptions（短列表，节点级元数据）/sourceRef
- `relations/`：5 类边（prerequisite/related/part_of/demonstrates/covered_by）。`extends`/`reinforces` 未引入（YAGNI）；`assesses`/`exemplifies` 随 2026-09-27 刷题层移除删除，`applies_to` 随 v4 章节区块融合删除
- **不再有 `entities/structure/`、`entities/items/` 与 `entities/models/`**：structure 节点由 loadGraph 从书级 `content/**/index.md` front-matter 即时派生；词书四类学习项由 loadGraph 扫描 `content/**/sections/*.md` 与 `content/**/chapters/C*/index.md` 文末词书区块物化——节点在内存图与 dist 中存在，源文件归 L1

### 素材组织对照（什么进 md，什么进 graph）

组织原则：**能"讲"出来的进 content（一律 md）；能"连"起来的进 graph（边）；需要被边引用的，在 graph 只留身份节点（id/title/aliases/summary/sourceRef），正文永远不跟节点走。**

| 素材 | 拆解 | 归属 |
|---|---|---|
| 原始教材 | 正文 prose | content md（`chapters/.../S<m>.md`） |
| | 词/短语/句/汉字条目 | content 节 md 文末词书区块（v4） |
| | 插图图注 | content 节 md 文末 `## 插图` 纯文本区块（v4，不派生实体） |
| | 章节结构 | content 书级 `index.md` front-matter（structure 节点派生） |
| | 概念身份 + 覆盖关系 | graph Concept 节点 + `covered_by` 边 |
| 复习资料 | 总结出的知识关系（先修/关联/隶属） | graph 边（`prerequisite/related/part_of`） |
| | 讲解正文（方法步骤/口诀/易错点） | content 节 md 文末 `## 解题模型` 区块 |
| | 概念级通用易错点（不附着具体题） | Concept.misconceptions 短列表 |
| 动画/视频外链 | `{key/platform, url}` | 随所属 `## 解题模型` 区块正文走；graph 不存（v4 起，原 supplements frontmatter 载体已退役） |

### L3 derived — 可重算，不入库

`dist/`（graph.json/stats.json/manifest.json）、structure 节点、复习层聚合视图、mastery 快照。规则：**gitignore 或运行时生成，永不手改、永不当真源**。

### L4 学习者层 — 学生个性化

学习者数据在应用侧，不在本仓：学生个性化数据（事件流、掌握度等）由下游应用自建存储，仅按稳定 canonical ID 引用图谱。应用侧经 `@faststudy/kg` 的只读 Query 访问图谱，mastery 重算、薄弱点分析（沿 `prerequisitesOf` 闭包溯源）均不进本仓库。

---

## 3. 强制点（让规则咬合）

文档口径由 lint 规则强制执行（要点见 README「lint —— 校验规则」），其中分层专属一条，配有负样例测试：

- **rule 10 `layer-placement`**（error）：源文件归属必须匹配 ontology 的 `storage` 声明——storage=content 的实体出现在 `graph/`、storage=graph 的实体出现在 content、storage=derived 的实体以源文件形式存在，均报 error



配套约定：抽取写入统一走 `ingest.ts` 的 `writeExtract()`（词书四类渲染为文末区块追加 section md、concepts 聚合追加、未知类型抛错、YAML 布尔保留词自动 requote）。

---

## 4. 分层约束

四条硬约束，由 `lint` 强制，不满足即构建失败：

| 约束 | 内容 |
|---|---|
| L1/L2 边界 | `content/` 是「学什么」，`graph/` 是「知识如何连接」。ontology 用 `storage` 声明归属，`layer-placement` 规则校验 |
| content 不含 YAML | 教材正文即 md；书级结构收在 `index.md` 的 front-matter；`sourceRef` 指向的文件必须存在（error） |
| 章节区块内联 | 词书四类、解题模型、笔记、总结一律写在节 md 文末区块，不建独立实体 |
| 学习者数据不入库 | 本仓只放知识，进度与作答留在应用侧，按 canonical ID 引用 |

非目标：不引入 `extends`/`reinforces`；不做多学生聚合与教师视图。

---

## 5. 关联文档

- 项目总览与 ontology：`../README.md`
- 抽取流水线：`../tools/kg/skills/SKILL_00_pipeline.md`（产出路径口径与本档一致）

---

## 6. 设计细则

> 以下规则为当前实现口径。

### 6.1 纯 md 分层规则

- `content/` 只放静态原始 md：五类学习项的 `items/*.yaml` 折成 `items/*.md`（v3）；书级 `textbook.yaml` 折进 `index.md` front-matter（`chapters` 键 = 结构唯一源）。
- 归属由 lint rule 10（layer-placement）强制：`content/` 下不得出现任何 yaml；源文件归属必须匹配 `ontology.yaml` 的 `storage` 声明（graph=身份节点、derived=无源文件、content=v3 后已无实体使用）。

### 6.2 part_of / prerequisite 语义（口径 B：含容优先）

- **part_of 判定最先问**：「from 是 to 的一种 / 一部分 / 一个实例 / 一个子话题？」——含容成立即 part_of，**不因能力依赖也成立而让位**。
- **prerequisite 仅在两端互不隶属**且存在能力依赖时成立（判据：把 to 从课程里拿掉，from 的讲解是否无法进行）；「教材里先讲」不是判据（实测存在教材顺序与先修关系相反的案例）。
- prerequisite 必须构成 DAG（lint rule 6 无环强制）。口径 B 下先修闭包比复核前稀疏得多（含容关系全部搬去了 part_of），下游若要补全上位知识需同时上行 part_of——详见 `graph/ontology.yaml` 的 `relation_semantics` 与 `graph/index.md` 复核注记。

### 6.3 figure / 公式抽取约定

- **公式**：数学/物理公式由视觉模型按页图转写为 LaTeX（SKILL_07）。
- graph 侧不存正文载荷（与「正文永远不跟节点走」原则一致）。
