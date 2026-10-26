# 操作参考（REFERENCE）

> 本文件承接原 README 的技术细节：目录结构、本体定义、lint 规则清单、工具链命令、
> Python 脚本表、LLM 抽取流水线、环境变量与输入契约。
> 面向使用者的入口在 [README](../README.md)，架构与分层见 [ARCHITECTURE](ARCHITECTURE.md)。
> 内容随代码演进，若与 `tools/kg/src` 冲突以代码为准。

---

# faststudy-knowledge

FastStudy 知识库独立仓库。把中小学教材以 **知识即代码（knowledge-as-code）** 的方式版本化管理：教材正文 prose + 概念知识图谱，全部以本地 `markdown / YAML` 表达，**本地文件是唯一源**；`dist/` 下的 `graph.json` / `stats.json` 仅为编译派生产物（gitignore，不要手工修改）。

A knowledge-as-code library that turns primary & secondary school textbooks into versioned markdown prose plus a concept knowledge graph, with a build/lint/query toolchain.

> 本仓库不含数据库。所有数据都落地在 `content/` 与 `graph/` 的文本文件中，图谱构建与查询由工具链在内存中完成，编译结果导出到 `dist/`。

> **分层边界（v4）**：**章节文档承载一切内容**——`content/` 各节 md = 教材原文 + 文末区块（`## 汉字/单词/短语/句子` 词书四类 + `## 插图` 纯文本图注 + `## 解题模型` + `## 笔记`/`## 总结`）；节点身份 + 关系写 `graph/`；structure（Textbook/Chapter/Section）与词书四类学习项由 content md 派生，不落盘。详见 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。

> **本地 agent 查询约定**：本地 agent 经 `tools/kg` 的 `loadGraph` + `Query` 类（或 `kg_ask.ts`）查询——loader 会聚合 `graph/` 节点与边、从书级 `content/**/index.md` front-matter 派生 structure、扫描 `content/**/sections/*.md` 与 `content/**/chapters/C*/index.md` 文末词书区块物化四类学习项；也可按上述新路径直读源文件（structure **不在** `graph/` 下）。**不要**读取 `dist/graph.json`。`dist/` 是编译后导出、供**在线/外部** agent 消费的产物。

## English

**faststudy-knowledge** turns China's primary & middle-school textbooks (grades 1–9) into versioned markdown prose (`content/`) plus a concept knowledge graph (`graph/`) — 99 textbooks, 18.5k nodes, 33k edges, with a cycle-enforced prerequisite DAG, part-of hierarchy and section coverage. Pure files, no database. Built for AI agents and education developers.

```bash
pnpm install        # or, with Node >= 22 only: cd tools/kg && npm install
pnpm kg:lint && pnpm kg:test && pnpm kg:build
pnpm kg:ask prereq 'concept:数学:无理数'
```

- **Data releases**: push a git tag (e.g. `v1.0.0`) — CI builds `dist/` and attaches `graph.json` / `stats.json` / `manifest.json` (+ SHA-256) to the GitHub Release.
- **Ontology**: see the entity/relation tables below; semantics in [docs/ARCHITECTURE.md](ARCHITECTURE.md).
- **License**: code MIT; self-authored data CC BY-NC-SA 4.0; textbook transcriptions are copyright their respective publishers (see [NOTICE](../NOTICE)) — personal study & research only, provided as-is without warranty.

## License

Code: MIT (see [LICENSE](../LICENSE)). Self-authored data (`graph/`, 以及 `content/` 下的词书区块与 `## 解题模型`/`## 笔记`/`## 总结` 区块):
CC BY-NC-SA 4.0 (see [LICENSE-DATA](../LICENSE-DATA)). Textbook transcriptions in `content/`
are copyright their respective publishers (see [NOTICE](../NOTICE)), for personal
study and research only.

All content is provided "as is", with no warranty of accuracy, completeness or
fitness for any teaching purpose. See [NOTICE](../NOTICE) for the full disclaimer
and the rights-holder takedown procedure.

## 快速开始

环境要求：Node.js ≥ 22。不需要数据库，不需要任何凭据。

```bash
pnpm install                                # 无 pnpm 时：cd tools/kg && npm install
pnpm kg:lint                                # 图谱校验（11 条规则，0 error 方可通过）
pnpm kg:test                                # 工具链单元测试
pnpm kg:build                               # 编译 dist/graph.json + stats.json + manifest（SHA-256 校验和）
pnpm kg:ask prereq 'concept:数学:无理数'      # 查概念先修传递闭包
```

最后一条的真实输出：

```text
concept:数学:有理数	有理数	[Concept]
concept:数学:勾股定理	勾股定理	[Concept]
concept:数学:直角三角形	直角三角形	[Concept]
concept:数学:正数和负数	正数和负数	[Concept]
```

「无理数」的先修知识一键溯源到「有理数 → 正数和负数」，且先修关系为 DAG（lint 强制无环）。其余查询原语（`tree/concepts/covered/demo/related/partof/mindmap`）见下文「工具链」。

所有提交经 CI 门禁（`.github/workflows/ci.yml`）：单元测试 → lint 0 error → build → 开源内容扫描。

---

## 目录结构

```
faststudy-knowledge/
├── package.json              # 根 workspace；scripts: kg:lint / kg:build / kg:test / kg:query
├── pnpm-workspace.yaml       # packages: tools/kg
├── content/                  # L1「学什么」（真源）
│   ├── <年级>/<学期>/<科目>/<textbookId>/
│   │   ├── index.md           # front-matter：教材元信息 + chapters 章节目录（结构唯一源，structure 节点由此派生）
│   │   ├── chapters/C<n>/index.md        # 章级真源（正文 + 文末词书区块，如章级汉字表）
│   │   ├── chapters/C<n>/sections/S<m>.md # 小节正文 + 文末区块：## 汉字/单词/短语/句子（词书四类表格）、## 插图（纯文本图注）、## 解题模型、## 笔记/总结
│   │   └── appendix/*.md      # 附录正文
├── graph/                    # L2「知识如何连接」（真源：节点身份 + 边，零正文载荷）
│   ├── ontology.yaml         # 实体类型 + 关系类型注册表（本体，含 storage 归属声明）
│   ├── entities/
│   │   └── concepts/<学科>.yaml # Concept 实体（9 个学科聚合数组）
│   └── relations/            # prerequisite / related / part_of / demonstrates / covered_by
├── dist/                     # 编译派生产物（gitignore，只读）
│   ├── graph.json            # { nodes, edges }（Concept 节点含派生 gradeRange/standards/centrality；prerequisite 边含 strength/reason）
│   ├── stats.json            # 节点/边统计
│   └── manifest.json         # 版本 + 计数 + 各产物 SHA-256 校验和（对外分发可信度）
├── source_data/              # 摄入源数据（gitignore，不入仓）：原始 PDF ×99（pdf_sources/<BookId>.pdf）+ <BookId>/pages 页图 + metadata
└── tools/kg/                 # 工具链（@faststudy/kg）
    ├── src/                  # TS 工具 + Python 辅助脚本
    │   ├── lint.ts build.ts query.ts ingest.ts load.ts ontology.ts
    │   ├── schema/           # zod 实体/关系 schema
    │   ├── extractors/       # 抽取底层实现
    │   └── *.py              # PDF/OCR、LLM 抽取、prose 格式化、结构同步、批量
    ├── skills/               # SKILL_00..08：LLM 抽取流水线 prompt
    ├── tests/                # 单元测试（node --test）
    └── README_EXTRACTORS.md  # 教材提取工具套件说明
```

---

## 知识图谱本体（ontology）

定义在 `graph/ontology.yaml`，是 `lint`（schema / ontology-drift 两条规则）的校验依据。

### 实体类型（按层）

`storage` 列声明源文件归属（被 lint rule 10 layer-placement 强制）：`graph`=graph/entities/ 身份节点（Concept）；`derived`=由 content md 派生、无独立源文件（structure 三类 + 词书四类学习项）。**`content/` 下不得出现任何 yaml。**

| 层 | 类型 | storage | 关键属性 |
|----|------|---------|----------|
| structure | `Textbook` | derived | title, grade, term, subject, publisher, totalPages, standardEdition, sourceRef |
| structure | `Chapter`  | derived | textbookId, title, order, pageRange, sourceRef |
| structure | `Section`  | derived | chapterId, textbookId, title, order, pageRange, sourceRef |
| learning   | `Concept`  | graph | subject, title, aliases, explanation, category, misconceptions, sourceRef（dist 派生增强：gradeRange, standards, evidence, centrality） |
| content    | `Word`     | content | word, ipa, pos, meaning, sourceRef |
| content    | `Phrase`   | content | en, cn, sourceRef |
| content    | `Sentence` | content | english, cn, sourceRef |
| content    | `Character`| content | char, pinyin, definition, example, sourceRef |

实体 id 全局唯一，概念形如 `concept:<学科>:<中文名>`（如 `concept:数学:杠杆`，slug 以中文概念名为主）。

### 关系类型

| 关系 | 端点（from → to） | 说明 |
|------|-------------------|------|
| `prerequisite` | Concept → Concept | 先修依赖，构成**有向无环图（DAG）**；可选 `strength`(hard/soft) 与 `reason`（理由） |
| `related`      | Concept → Concept | 主题相关（非方向） |
| `part_of`      | Concept → Concept | 概念隶属 |
| `demonstrates` | Word/Phrase/Sentence/Character → Concept | 学习项演示概念（英语核心，语/数可选） |
| `covered_by`   | Concept → Section | 概念在某节中被覆盖 |

---

## 工具链 `tools/kg`

### 常用命令（在仓库根目录执行）

```bash
pnpm install          # 安装工具链依赖（pnpm workspace，仅 tools/kg）
pnpm kg:lint          # 校验图谱（11 条规则）
pnpm kg:build         # 编译 -> dist/graph.json + dist/stats.json
pnpm kg:test          # 工具链单元测试（node --test）
pnpm kg:query         # 运行查询模块（见下文「查询 API」）
pnpm kg:ask           # 命令行问答（tree/concepts/covered/prereq/demo/related/partof/mindmap）
pnpm kg:fix:covered   # 由 concept.sourceRef 派生 covered_by，清除 orphan
pnpm kg:fix:orphans   # 按标题在 content/ 定位 section，补 covered_by + 修正占位 sourceRef
pnpm kg:infer         # 确定性推导三类关系：demonstrates / related(同章) / prerequisite(跨年级骨架)
python3 tools/kg/src/llm_relations_hierarchy.py   # LLM 抽取 part_of(层级) + 跨章 related
python3 tools/kg/src/llm_prereq_intra.py           # LLM 抽取章内 prerequisite（加密先修链）
python3 tools/kg/src/llm_demo_lang.py              # LLM 抽取英语 demonstrates（补语言侧）
python3 tools/kg/diag_gap.py   # 内容完整性诊断（对照课标矩阵，直接输出缺失清单）
```

> **关系补全**：
> - **确定性（无需 LLM，`kg:infer`）**：从 `covered_by` + 结构 + content `sourceRef` 推导 `demonstrates`（文本命中概念名）、`related`（同章星形聚类）、`prerequisite`（章节链跨年级骨架，DAG 无环）。
> - **LLM 语义（`llm_*.py`）**：补齐确定性不可得的关系——
>   `part_of` 概念层级（is-a/隶属）、`related` 跨章关联、`prerequisite` 章内排序、`demonstrates` 英语侧（不再依赖中文名命中）。
> - **执行者说明**：有 AI agent 参与的工作流中，上述 LLM 语义任务**由 agent 直接完成**（无需任何凭据配置）；`llm_*.py` 是为无 agent 的批处理/CI 环境准备的等价实现，需自配 `.env` 凭据（见 `.env.example`）。
>
> 当前各关系计数以 `pnpm kg:build` 后的 `dist/stats.json` 为准（见下方「数据规模」）。`part_of`/`related` 跨章/`prerequisite` 章内均由 LLM 抽取补全。

> **内容缺口**：部分教材/学期尚未完整转录，运行 `python3 tools/kg/diag_gap.py` 可得到实时缺失清单。补全需提供教材扫描/PDF，走摄入管线（见 `tools/skills/kg-ingest/SKILL.md`）。

> **图谱修正辅助**：`fix:covered` 用概念自带 `sourceRef` 反推 section 补 `covered_by`；`fix:orphans` 对 `sourceRef` 为占位的孤儿概念，按标题在 `content/` 中唯一定位并补链。两者都幂等、可重复跑。仍无法匹配的多半是对应教材章节尚未转录（内容缺口），需补全 content 后重抽。

> 等价地，也可进入 `tools/kg` 目录用 `pnpm lint|build|query|test` 直接运行（后缀 `-- ../../` 指定根目录）。

### 可选环境变量

- `KG_SOURCE_DIR`：教材源图目录（含 `<教材id>/pages`、`metadata.json`），摄入/OCR 管线必读，缺失即报错退出；仓内默认 `source_data/`（原始 PDF 与页图，gitignore 不入仓）。
- `KG_PAGE_IMAGE_BASE_URL`：页图 CDN 基址。构建 dist 时据此派生 Section.pageImages；未设置则不产页图字段。

完整变量清单（LLM 凭据 `AI_*` 与摄入 `KG_*`）见 [`.env.example`](../.env.example)。

### 可选输入契约：`tools/kg/state/curriculum_toc.json`

`reoutline_propose.py` 与 lint rule 19（`section-toc-agree`）支持一个**可选**输入——教材目录快照（外部输入，不入仓）。顶层结构：

```json
{
  "exportedAt": "<ISO-8601 时间戳，超过 7 天视为过期、拒绝使用>",
  "source": "<导出来源标识>",
  "books": [
    {
      "id": "<textbookId>", "title": "…", "subject": "…", "grade": "…", "term": "…",
      "chapters": [
        { "id": "…", "title": "…", "order": 1, "pageRange": [1, 21],
          "sections": [ { "id": "…", "title": "…", "order": 1, "pageRange": [2, 7] } ] }
      ]
    }
  ]
}
```

- 它用于把教材目录快照与图谱 structure 对账：缺失时 rule 19 自动跳过（现有行为），不报错。
- lint 侧快照路径可经参数覆盖；reoutline 侧为固定约定路径 `tools/kg/state/curriculum_toc.json`。

### `lint` —— 校验规则（要点）

1. **schema** — 实体须有 `type`，关系须有 `from`/`to`（zod 兜底）
2. **ontology-drift** — 实体/关系类型必须在 `ontology.yaml` 注册
3. **ID-uniqueness** — 实体 id 全局唯一
4. **relation-endpoint** — 关系端点类型必须匹配 `relation_endpoints`
5. **referential-integrity** — 关系端点引用的实体必须存在
6. **cycle** — `prerequisite` 必须无环（DAG 约束）
7. **orphan（warning）** — 每个 `Concept` 至少被一个 section `covered_by`
8. **sourceRef（warning）** — 实体应带有指向 `content/` 的 `sourceRef`
9. **layer-placement** — 源文件归属必须匹配 ontology 的 `storage` 声明（content 实体不得出现在 `graph/`，graph 实体不得出现在 content，derived 实体不得有源文件）

> 另有 summary-height / confidence / prerequisite-downstream / extension-provenance / book-frontmatter-schema / pageRange-required / section-toc-agree 等规则，完整清单见 `tools/kg/src/lint.ts`。

`lint` 发现 error 会以退出码 1 失败；`build` 依赖 `lint` 通过（有 error 则中止）。

### `build` —— 编译产物

聚合 `graph/` 下所有实体与关系，输出：

- `dist/graph.json`：`{ nodes: Entity[], edges: RelationEdge[] }`
- `dist/stats.json`：`{ nodes, edges, byType, byRelation }`
- `dist/manifest.json`：`{ version, generatedAt, counts, derivedFields, files: { graph.json/stats.json 的 sha256+bytes } }`

### `build` 派生的增强字段（仅出现在 `dist/`，不回写 `graph/` 源文件）

借鉴 [Marble Skill Taxonomy](https://github.com/withmarbleapp/os-taxonomy) 的设计，`build` 在编译期为 Concept 节点与 prerequisite 边补充以下派生字段，供**外部/在线 agent**消费（本地 agent 仍走 `graph/` 源文件）：

- **`Concept.gradeRange`**（如 `"7"` 或 `"7-9"`）：由 `covered_by → Section → Textbook.grade` 推导（多 grade 覆盖时取区间），回退到 `sourceRef` 路径解析。
- **`Concept.centrality`**（0–1，越高越基础）：在 `prerequisite` 先修 DAG 上做 PageRank，衡量概念的基础重要性，可驱动复习优先级。
- **`Concept.standards`**（课程标准键，数组）：**已预留字段、当前为空**——待接入国家课程标准对齐层后填充（见下方"课程标准对齐"）。
- **`prerequisite.strength`**（默认 `hard`）/ **`reason`**：先修强度与一句理由；缺失时 `build` 默认置 `hard`。

> 这些字段只在 `dist/` 导出时计算与携带，`graph/` 源文件保持精简（不污染真源，重建可重算）。

### 课程标准对齐（scaffold）

`Concept.standards` 字段已就位，可用于挂接国家课程标准（如义务教育各学科课程标准）的代码键。当前图谱尚无标准映射数据；接入时建议在 `graph/` 新增 `curriculum-standards.yaml` 并在 `PROVENANCE` 中注明版权（第三方标准沿用上游许可），再在 `build` 期按学科/年级/章节对齐写入 `standards`。

### 查询 API（`query.ts`）

`kg:query` 运行查询模块；更常见的是在脚本/应用中直接引用 `Query` 类：

- `conceptsForSection(sectionId)` — 某节覆盖的概念
- `prerequisitesOf(conceptId)` — 某概念的（传递闭包）先修概念
- `itemsDemonstrating(conceptId)` — 演示该概念的学习项
- `coveredBySection(conceptId)` — 该概念被哪些 section 覆盖
- `sectionTree(textbookId)` — 某教材的章节结构

### Python 辅助脚本（`tools/kg/src/*.py`）

| 类别 | 脚本 | 用途 |
|------|------|------|
| PDF / OCR 摄入 | `pdf_extractor.py` `pdf_ocr_to_index.py` `batch_ocr.py` `toc_probe.py` | PDF 文本提取 / 页面图 OCR → `content/` prose |
| LLM 抽取 | `llm_extract_graph.py` `llm_format_refine.py` `llm_polish_prose.py` `llm_repair_ocr.py` `llm_misconceptions.py` `llm_demo_lang.py` `llm_prereq_intra.py` `llm_relations_hierarchy.py` | 调用大模型抽取图谱、关系补全、润色/修复正文 |
| prose 清洗 | `sanitize_prose.py` `reflow_prose.py` `polish_format.py` `restore_prose.py` `strip_page_footer.py` `wrap_latex_math.py` | 正文清洗、页脚剥离、数学公式 LaTeX 包裹、格式规整 |
| 结构同步 | `sync_sections_from_index.py` `gen_section_stubs.py` `book_propose.py` `book_apply.py` `reoutline_propose.py` `reoutline_apply.py` `reoutline_ocr.py` | 由书级 `index.md` 派生/重切 sections |
| 小学入图管线 | `gen_book_index.py` `primary_common.py` `primary_fix.py` | 书级 index 生成（G1–G7 门禁）与节文件修复 |
| 校验 / 诊断 | `validate_offsets.py` `verify_prose.py` `scan_format_residue.py` | 页码三处一致性、prose 校验、格式残渣扫描 |

Python 脚本依赖（按需安装）：`pypdf`、`PyMuPDF`、`rapidocr-onnxruntime`、`pillow`。

---

## LLM 抽取流水线（`tools/kg/skills`）

一整套供大模型执行的抽取 prompt，按序编排（详见 `SKILL_00_pipeline.md`）：

| Skill | 职责 |
|-------|------|
| SKILL_00 | 抽取编排器（总控与批量策略） |
| SKILL_01 | OCR 文本化（页面图 → prose） |
| SKILL_02 | 抽概念 + 跨教材去重（写 `graph/entities/concepts/<学科>.yaml` 聚合文件） |
| SKILL_03 | 抽词书（词/短语/句/汉字，写 section md 文末词书区块） |
| SKILL_04 | 抽关系：`covered_by` 必选；`demonstrates`/`related`/`part_of` 均按内容产出（不再"可选跳过"）；`prerequisite` 含**跨年级**关联 |
| SKILL_05 | Pass2 验证 prerequisite：可**新增证据充分的跨年级边**，剪枝错误边，保证 DAG 无环 |
| SKILL_06 | 插图抽取（已停用：插图区块为纯文本图注，随正文走，不派生实体） |
| SKILL_07 | 抽公式 LaTeX（数学/物理，视觉模型） |
| SKILL_08 | 解题模型抽取（已停用：解题方法迁入 `## 解题模型` 区块，不建实体） |

**幂等约定**：content prose 与 concept 按 id 查重跳过；词书区块按 section 追加/跳过；relations 按 `from->to` 去重追加。`--force` 可重抽覆盖。每完成一步都应跑一次 `lint + build`，全量 0 error 才算完成。

---

## 约定与协作

- **四层分界**（v4）：`content/`（L1 学什么）与 `graph/`（L2 知识如何连接）是真源；derived（L3：`dist/`、structure 节点、复习层视图）一律派生可重算、不入库不手改；学习者层（L4）数据在应用侧、不在本仓，只按稳定 canonical ID 引用图谱。任何改动先改 L1/L2 源文件，再 `build` 刷新 `dist/`。
- **先 lint 后 build**：`build` 仅在 `lint` 无 error 时成功。
- **sourceRef**：每个实体都应带 `sourceRef` 指回 `content/` 对应章节，便于溯源（warning 级，建议补齐）。
- **关系无环**：新增 `prerequisite` 前确认不会形成环。

---

## 数据规模（当前 `dist/stats.json`）

- 节点 **18,504**（Concept 8,263 / Word 2,803 / Phrase 1,320 / Sentence 1,099 / Character 1,218 / Textbook 99 / Chapter 721 / Section 2,981)
- 边 **33,107**：`covered_by` 10,284 · `demonstrates` 2,583 · `prerequisite` 1,862 · `related` 13,242 · `part_of` 5,136

> 数字随图谱更新而变化，以 `pnpm kg:build` 后生成的 `dist/stats.json` 为准。build = runtime（无投影剔除）。

---

## 设计文档

- 分层架构 v2（当前口径）：[`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
