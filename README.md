# 中小学教材知识库

[![在线演示](https://img.shields.io/badge/在线演示-打开-2ea44f)](https://dangjian.github.io/faststudy-knowledge/)
![代码](https://img.shields.io/badge/代码-MIT-green)
![数据](https://img.shields.io/badge/数据-CC%20BY--NC--SA%204.0-lightgrey)
![概念](https://img.shields.io/badge/概念-8%2C282-blue)
![教材](https://img.shields.io/badge/教材-99%20册-informational)

`faststudy-knowledge` · 为 AI agent 提供可直接查询的教材事实。

问「学生光合作用总搞混，问题在哪」，agent 能拿到这个概念、它的先修链、常见错误，
以及教材第 29–37 页的原文——而不是靠模型记忆编答案。

**33,549 条关系 · 1,497 万字原文**。纯文本文件，无数据库、无服务。

它是**数据底座**，不产课件：动画、讲义、视频交给开源项目渲染 → [结合场景](docs/SCENARIOS.md)。

| 你是 | 怎么用 |
|---|---|
| 做 AI 教育应用 | 让 agent 读 [graph/index.md](graph/index.md)，按 [tools/skills/kg-query](tools/skills/kg-query/SKILL.md) 逐层下钻 |
| 教研 / 课程设计 | 查概念在哪一节、有哪些易错点、对应课标哪个领域（见「[命令行也能查](#命令行也能查)」） |

**在线演示**：<https://dangjian.github.io/faststudy-knowledge/> —— 树状浏览（教材 → 章 → 节 → 概念），
概念可看关系网、教材原文与页码。

**本地也能跑**（离线可用）：

```bash
# ① 命令行：一个概念在教材哪几节、第几页
$ pnpm kg:ask covered 'concept:生物:光合作用'
PEP-8-1-Biology-C5-S2  第二节 生态系统的结构和功能  [Section]  p.83-89
PEP-7-2-Biology-C3-S2  第二节 光合作用            [Section]  p.29-37

# ② 树状浏览器：教材 → 章 → 节 → 概念，点节点看详情；概念还能开关系网
$ pnpm kg:build && pnpm kg:demo
$ python3 -m http.server 8765
# 打开 http://localhost:8765/demo/index.html（说明见 demo/README.md）
```

## 能用来做什么

本仓只提供数据，不产课件。把它交给下游的开源项目，能拼出这些：

| 结合 | 我们提供 | 产出 |
|---|---|---|
| [EduLab](https://github.com/wy51ai/edulab) | 概念、易错点、教材页码 | 一道题 → 可操作的分步解题页，侧栏挂「教材 p.29–37」 |
| Manim / Slidev | 章节结构、概念清单 | 一节课的微课片段或讲义，页脚可回链教材 |
| RAGFlow | 1,497 万字原文 + 页码 | 回答必须给「教材 p.29–37」，而不是模型记忆 |

完整 9 个场景（含分工边界与最小验证路径）→ [docs/SCENARIOS.md](docs/SCENARIOS.md)

教材以**西安当前在用版本**为例：北师大版数学、人教版语文/道法/英语/历史/生物、教科版科学、中图版地理、苏科版物理、科粤版化学；**其他地区可按同一流程换教材重建** → [docs/BUILD.md](docs/BUILD.md)。

```
教材原文  ──►  概念（释义/易错点/类型/掌握标准）  ──►  关系（先修/层级/覆盖）  ──►  入口 index.md + skill  ──►  Agent
1,497 万字      8,282 个                          33,549 条                    按需读切片
```

---

## 给 AI Agent 用：入口文件 + Skill

不打服务、不起进程。agent 靠两个文件配合查询：

| 文件 | 作用 |
|---|---|
| `graph/index.md` | **入口**：问句→路径映射表、ID 前缀速查、局限声明。agent 先读这一页 |
| `tools/skills/kg-query/SKILL.md` | **查法**：五步下钻流程（Textbook → Chapter → Section → Concept → 关系边） |

### 为什么不把整个图谱塞给模型

8,282 个概念、33,549 条边，编译产物 `dist/graph.json` 有 11MB。全量读入等于把上下文烧光，
而且模型很难在 3 万条边里保持准确。所以 `kg-query` 的核心约定是：
**LLM 逐层下钻、只读命中路径上的 YAML 切片**；脚本只承担两件 LLM 不擅长的事——
跨大关系文件的精确切片、先修链的多跳闭包。

一次典型查询的实际读取量：

```text
graph/index.md                          入口，约 4 KB
  → kg:ask tree BSDU-7-1-Math           章节目录，约 2 KB
    → kg:ask concepts ...-C1-S1         该节概念 id，约 0.3 KB
      → grep 概念条目                    单条 YAML，约 0.3 KB
        → kg:ask prereq <id>            先修链，约 0.5 KB
```

合计不到 8 KB，且每一步都能停下来。

### 安装 skill

把 `tools/skills/` 下的 kg-* 软链到宿主的 skill 目录（项目级 `.codebuddy/skills/` 或用户级都可以）：

```bash
cd /path/to/faststudy-knowledge
mkdir -p .codebuddy/skills
ln -s "$(pwd)/knowledge/tools/skills/kg-query" .codebuddy/skills/kg-query
ln -s "$(pwd)/knowledge/tools/skills/kg-help"  .codebuddy/skills/kg-help
ln -s "$(pwd)/knowledge/tools/skills/kg-mindmap" .codebuddy/skills/kg-mindmap
```

**改 skill 一律改 `tools/skills/` 原件，软链侧不动**——那里是唯一事实来源。
若宿主不识别软链，改为复制安装，复制件视为只读镜像。

### 一次真实的下钻

问「光合作用学生总搞混，该怎么补」：

```text
① 读 graph/index.md，命中「某概念被哪些节覆盖」→ 决定用 kg:ask covered
② kg:ask covered 'concept:生物:光合作用'
   → PEP-7-2-Biology-C3-S2 第二节 光合作用
     PEP-8-1-Biology-C5-S2 第二节 生态系统的结构和功能
③ kg:ask concepts PEP-7-2-Biology-C3-S2 → 蒸腾作用 / 光合作用
④ 直读该节 md → 教材原文；再 grep 概念条目拿 misconceptions
⑤ kg:ask prereq 'concept:生物:光合作用' → 先修链（只走 reviewed=audited）
```

关键在第 ④ 步：能直接读到**教材原文**，agent 可以照着原文讲，不必靠先验知识编造。
这也是这份图谱相对纯关系图谱的差别——内容和结构在同一个仓库里。

---

## 命令行也能查

Agent 之外，人也可以直接用 CLI（只读）：

```bash
pnpm kg:ask prereq  'concept:数学:无理数'   # 先修链
pnpm kg:ask covered 'concept:生物:光合作用'  # 这个概念的落点
pnpm kg:ask concepts 'PEP-7-2-Biology-C3-S2' # 这一节的概念
pnpm kg:ask partof  'concept:化学:元素符号的意义'  # → 元素符号
pnpm kg:ask related 'concept:化学:元素符号的意义'  # → 元素周期表 / 空气的组成
pnpm kg:ask tree     'BSDU-7-1-Math'
```

---

## 数据规模

10 学科、99 册、**722 章 / 2,976 节**——每节都有教材原文与页码区间。

分学科如下：

| 学科 | 教材 | 概念 | 先修边 | 覆盖边 | 课标对齐 |
|---|---:|---:|---:|---:|---:|
| 语文 | 18 | 1,570 | 144 | 2,196 | 94% |
| 历史 | 6 | 1,297 | 237 | 1,302 | 100% |
| 数学 | 18 | 1,096 | 569 | 1,608 | 97% |
| 道德与法治 | 18 | 999 | 20 | 1,113 | 96% |
| 英语 | 13 | 930 | 132 | 1,069 | 96% |
| 生物 | 4 | 648 | 79 | 663 | 100% |
| 地理 | 4 | 600 | 193 | 603 | 100% |
| 物理 | 4 | 425 | 255 | 440 | 100% |
| 科学 | 12 | 363 | 27 | 431 | 100% |
| 化学 | 2 | 354 | 142 | 354 | 100% |
| **合计** | **99** | **8,282** | **1,798** | **9,779** | **97.6%** |

「先修边」列是边数，不是概念覆盖率：**1,288 / 8,282 个概念（15.6%）有先修边**。语文（144 条）与道法（20 条）少，是这两科的知识点多为并列关系（篇目、事件、制度），本身不构成能力依赖，不是抽取遗漏。

### 每个概念带什么

| 字段 | 覆盖 | 有什么用 |
|---|---|---|
| `title` `subject` `explanation` | 全覆盖 | 是什么、属于哪科、一句话释义 |
| `misconceptions` | 6,807（82%） | 常见错误认知，用于判断「学生是不是踩了坑」 |
| `conceptType` | 全覆盖 | 概念型 / 程序型 / 推理型 / 应用型 / 建模型——决定该讲定义还是演步骤 |
| `masteryCriteria` | 6,805（82%） | 「怎样算学会了」，目前是错误规避式（由易错点反推） |
| `standards` | 97.6% | 课标领域/主题群码（**非条目级**）。其中 1,465 条只挂 2011 版旧码（待迁移），196 个概念所在章标题无主题信息、未对齐 |
| `gradeRange` | 全覆盖 | 出现该概念的年级区间 |
| `strength`（先修边上） | 全覆盖 | hard = 不学会就学不下去；soft = 有帮助但非门槛 |

精确到百分点的实测精度见「可信到什么程度」。

### 其他实体

| 类型 | 数量 | 说明 |
|---|---:|---|
| 词汇四类 | 6,463 | 单词 2,803 / 短语 1,320 / 句子 1,099 / 汉字 1,241 |
| 章节结构 | 722 章 / 2,976 节 | 每节都有教材原文与页码区间 |

---

## 快速开始

```bash
pnpm install              # Node ≥ 22；无 pnpm 时：cd tools/kg && npm install
pnpm kg:lint              # 图谱校验：22 条规则，0 error 才允许构建
pnpm kg:test              # 工具链测试（TS 168 例 + Python 5 套）
pnpm kg:build             # 编译 dist/（stats/manifest，供外部消费）
```

不想装 Node？直接下 [Release 产物](https://github.com/dangjian/faststudy-knowledge/releases/latest)，
`graph.json` 就是完整图谱。用法见 [从 Release 直接下载](#从-release-直接下载不装-node)。

Agent 查图谱走的是 YAML 源文件（按需读切片），不需要 dist；`dist/` 的用途见下方「`dist/` 什么时候用」。

---

## 数据结构

```
content/<年级>/<学期>/<学科>/<教材ID>/
  index.md                        教材元信息 + 章节目录
  chapters/C<n>/index.md          章级正文
  chapters/C<n>/sections/S<m>.md  节正文（教材原文）+ 文末区块（词表 / 解题模型）

graph/
  ontology.yaml                   8 类实体、5 类关系（端点声明与判定口径）
  entities/concepts/<学科>.yaml   概念：释义、易错点、出处
  relations/                      先修 / 层级 / 相关 / 覆盖 / 词句演示
  curriculum-standards.yaml       课标条目（80 条）
  chapter-standards.yaml          章 → 课标映射

tools/skills/                     kg-* skill（查询/摄入/复核），唯一事实来源
```

概念长这样（构建后自动补 `gradeRange` 与 `standards`）：

```yaml
- id: concept:生物:光合作用
  subject: 生物
  title: 光合作用
  explanation: 绿色植物利用光能，把二氧化碳和水转化成储存能量的有机物，并释放氧气。
  misconceptions:
    - 认为植物白天只进行光合作用、不进行呼吸作用
  sourceRef: content/七年级/下册/生物/PEP-7-2-Biology/chapters/C3/sections/S2.md
```

五种关系：

| 关系 | 端点 | 含义 |
|---|---|---|
| `prerequisite` | 概念 → 概念 | 先修，**无环**；`audited`（逐条判过）/ `sampled`（仅抽样）两档 |
| `part_of` | 概念 → 概念 | 上位 / 部分关系 |
| `related` | 概念 ↔ 概念 | 主题相关（同章聚类为主） |
| `covered_by` | 概念 → **节或章** | 节级 = 该节能举证；章级 = 归章已定、落节无据 |
| `demonstrates` | 词/短语/句/汉字 → 概念 | 词句演示概念 |

---

## `dist/` 什么时候用

`kg:build` 产出三个文件，都是**派生物**（已 gitignore，可随时重建）：

| 文件 | 内容 | 给谁用 |
|---|---|---|
| `graph.json`（11.7 MB） | `{ nodes, edges }` 运行时视图，18,542 节点 / 33,549 边 | 不在仓库里跑的消费者 |
| `stats.json` | 建库口径计数（投影前） | 监控、报表、回归对比 |
| `manifest.json` | 版本、契约、字段白名单、**每个文件的 SHA-256** | 缓存失效判断、契约校验 |

### 从 Release 直接下载（不装 Node）

每次打 tag 会把 `dist/` 挂到 Release，给"只想拿数据、不想跑构建"的场景：

| 文件 | 用途 |
|---|---|
| `graph.json`（11.7 MB） | 完整图谱：18,542 节点 / 33,549 边，结构是 `{ nodes, edges }` |
| `stats.json` | 建库口径计数（投影前），做报表或回归对比时用 |
| `manifest.json` | 版本、契约、字段白名单、每个文件的 SHA-256——缓存失效判断靠它 |
| `SHA256SUMS.txt` | 校验下载完整性 |

```js
// Node
const { nodes, edges } = require('./graph.json')
const concepts = nodes.filter(n => n.type === 'Concept')
```

```python
# Python
import json
g = json.load(open('graph.json'))
concepts = [n for n in g['nodes'] if n['type'] == 'Concept']
```

读之前要知道三件事：

- **节点与边分离**：边用 `from` / `to` 存 id，没有内联对象，需要自己 join
- **两个派生字段只在这里有**：`concept.standards`（课标主题码）与 `gradeRange`（年级区间）由 build 计算，YAML 源里不存在
- **不含正文**：`graph.json` 只有 id 与 `sourceRef`，教材原文要回仓库按路径取

### 该用 dist 的四种场景

**1. 后端服务启动加载**
下游服务（如本项目的 `kg-review`）读 `dist/graph.json` 在内存里聚合视图，**不解析 YAML**。
实测（同一台机器、三次取均值）：`loadGraph()` 解析全部 YAML **1,343 ms**，
`JSON.parse(dist/graph.json)` **15 ms**——差约 90 倍，服务冷启动时这就是可感知的差异。

**2. 第三方 / 外部 agent 单文件集成**
只想要数据、不想跑 Node 工具链的人，拿一个 `graph.json` 就能用；
不用装 `yaml` 依赖，也不用理解 `content/` 与 `graph/` 的分层。

**3. 版本对齐与缓存失效**
`manifest.json` 里每个文件带 `sha256` 与 `bytes`。消费方缓存图谱后，比对哈希就知道要不要重载，
不用自己算版本。

**4. 离线分发**
`dist/` 可以单独打包传走（教材原文仍在 `content/`，需要正文时再按 `sourceRef` 取）。

### 不该用 dist 的场景

| 场景 | 为什么 |
|---|---|
| 本地 agent 按问题下钻查 | dist 是全量 11.7 MB，读进上下文等于烧光预算；应走 `graph/index.md` + skill 的切片路径（一次查询 <8 KB） |
| 需要全保真字段 | dist 是**投影后**的视图：`aliases`、`category`、`evidence`、`centrality` 等治理字段被裁掉；全量在 `graph/` 的 YAML 源里 |
| 要读教材原文 | dist 只有 `sourceRef` 路径，正文在 `content/` |

### dist 与 YAML 源的字段差异

| 类型 | dist 保留 | dist 裁掉 |
|---|---|---|
| Concept | `id/type/sourceRef/title/subject/explanation/misconceptions` + 派生 `standards/gradeRange` | `aliases` `category` `evidence` `centrality` |
| 边 | `type/from/to` + `reviewed` | `strength` `reason` |
| 其他实体 | 各自运行必需字段（见 `manifest.json` 的 `runtimeView.fields`） | 同上原则：运行时没人读的一律不进 |

> 投影规则写在 `tools/kg/src/runtime_view.ts`，字段白名单会同步进 `manifest.json`，消费方可据此校验。

---

## 可信到什么程度

所有数字都来自可重跑的评测，不是自评。

### 数据怎么来的

1. **教材原文**：PDF 转录为 Markdown（OCR + 人工抽检），3,802 个文件
2. **概念**：LLM 从节正文抽取 → 人工抽检错例 → 补 `explanation` / `misconceptions`
3. **关系**：LLM 生成草案 → 按学科分批复核 → 抽检建金标
4. **课标**：登记 80 条领域/主题群条目（2022 版为主，历史/语文/英语/道法/数学 仍混有 2011 版旧码），再按章节标题规则映射到章

### 人工金标（1,223 条，可回归）

| 金标 | 规模 | 实测精度 | 判据 |
|---|---:|---:|---|
| `covered_by` 归属 | 97 条 | 章级 93.3% / 节级 97.1% | 双人盲判 κ=0.43、AC1=0.72 |
| `prerequisite` 方向 | 300 条 | 87.9% / 92.4% / 85.0%（按档） | 分层抽样 + 逐条判定 |
| `part_of` 层级 | 500 条 | **81.9%**（全量） | 见下方处置 |
| `conceptType` 类型 | 98 条 | **91.8%** | 分层抽样 + 独立盲判 |
| `masteryCriteria` 掌握标准 | 30 条 | **96.7%**（29/30） | 三条件：可观察 / 属于该概念 / 有区分度 |
| `strength` 先修强度 | 198 条 | 逐条判定（非规则） | hard 68.2% / soft 31.8% |

`pnpm kg:eval:covered / :prereq / :partof / :type / :mastery / :strength` 可随时复跑；
金标判为正确的内容一旦消失或被改判，退出码即 1。

**`part_of` 的处置**：实测全量仅 81.9%（约每 5 条错 1 条），且规则筛查无效（命中里 58–83% 是误报）。因此上位关系只接受「子概念标题包含父概念标题」的子集——精度 **96.6%**，覆盖 842 个概念（10.2%）。其余 4,186 条保留供「相关概念」浏览，不冒充上位。

### 使用前须知（三条会误用的坑）

| 坑 | 事实 | 怎么规避 |
|---|---|---|
| 上位关系只有 10.2% 可用 | `part_of` 全量 5,062 条精度 **81.9%**（约每 5 条错 1 条），其中约 900 条存疑 | 上位只认「子概念标题包含父概念标题」子集（精度 96.6%，842 个概念）；其余仅供「相关概念」浏览，不要当权威上位 |
| 课标不是条目级 | 80 条**领域/主题群级**条目，不是「课标第 38 页第 4 条」 | 需要逐条合规对接时不能直接用；条目级对齐未做 |
| 章级归属不知道落哪节 | 1,293 条 `covered_by` 只到章（"这概念属于第X章"），不知道具体哪一节讲 | 查「哪一节讲」只认节级边（8,486 条） |

**不在本仓库范围**：题库（刷题层已在产品层裁撤）、在线演示站、边级 `evidence`（正文原句/页码）。

### 质量门禁

`kg:lint` 22 条现行规则（编号至 25，缺 9/11/18；0 error 才允许构建）：Schema 合法性、端点类型、ID 唯一性、先修无环、引用完整性、孤儿检测、`sourceRef` 存在性、分层归属、摘要高度、课标引用一致性等。

---

## 许可

- **代码**：MIT
- **自撰数据**（`graph/`、各节文末词表区块与 `## 解题模型`）：CC BY-NC-SA 4.0
- **教材原文**：版权归各出版社所有，仅供个人学习与研究，见 [NOTICE](NOTICE)

---

## 深入

| 文档 | 内容 |
|---|---|
| [docs/SCENARIOS.md](docs/SCENARIOS.md) | **与开源教育产品结合的场景**（Manim/Slidev/H5P/Mermaid/whisperX…） |
| [demo/README.md](demo/README.md) | **树状浏览器**怎么跑（静态页，教材→章→节→概念） |
| [docs/BUILD.md](docs/BUILD.md) | **换一套教材怎么重建**（流程、前置、换后哪些要重做） |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层架构、派生规则 |
| [docs/REFERENCE.md](docs/REFERENCE.md) | 本体全表、lint 规则清单、摄入管线 |
| [graph/index.md](graph/index.md) | 图谱总览与局限声明（agent 入口） |
| `tools/kg/eval/rubric-cases.md` | 判定口径与仲裁案例 |
| `tools/skills/` | 面向 agent 的运维技能：摄入、抽取、复核、缺口治理 |
