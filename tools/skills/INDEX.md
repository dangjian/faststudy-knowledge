# 知识库 Skill 系列 — 总览

> 本目录（`knowledge/tools/skills/`）是 kg-* skill 系列的**唯一维护位置（事实来源）**——skill 随图谱同仓演进。
> 宿主环境的 `.claude/skills/` 中的 kg-* 可以为指向此处的软链（安装方式见第 6 节），**改 skill 一律改这里，不改软链侧**。
> 分为两簇：**消费簇**（用图谱：查询 / 脑图 / 巡检）与 **摄入簇**（建图谱：摄入 / 大纲 / 抽取 / 验先修）。
>
> 设计原则（Approach A）：**图谱是层级网状结构，查询由大语言模型（LLM）前置驱动**——
> LLM 逐层下钻、只读取所需 YAML 切片并基于关系边推理；脚本只做 LLM 不擅长的事：
> 跨大关系文件的精确切片、传递闭包（先修链多跳）。`kg_ask.ts` 是唯一的「有界切片 / 闭包」后端原语。

---

## 0. 架构约定（所有 skill 必读）

```
knowledge/content/      ← 真源 L1「学什么」：章节文档承载一切内容
  <年级>/<学期>/<科目>/<textbookId>/
    index.md                          (front-matter 的 chapters 键 = 结构唯一源；Textbook/Chapter/Section 由此派生，不落盘)
    chapters/C<n>/index.md            (章级真源 + 文末词书区块，如章级汉字表)
    chapters/C<n>/sections/S<m>.md    (节正文 + 文末区块，固定顺序：
                                       ## 汉字/单词/短语/句子 — 词书四类 md 表格，照常派生实体
                                       ## 插图 — 纯文本图注，不派生实体
                                       ## 解题模型 / ## 笔记 / ## 总结)
knowledge/graph/        ← 真源 L2「知识如何连接」：节点身份 + 边，零正文载荷
  ontology.yaml                       (含 storage: graph|derived 归属声明，lint 强制；content/ 下不得出现 yaml)
  entities/concepts/<学科>.yaml       (Concept，10 个学科聚合数组；科学为后续追加，未进后端可信先修白名单)
  relations/{covered_by,demonstrates,prerequisite,related,part_of}.yaml
knowledge/dist/         ← 派生产物（graph.json / stats.json / manifest.json）
                          ⚠️ 仅给在线/外部 agent 消费；本地 agent **禁止**读取它来查询。
```

- **本地查询经 `kg_ask.ts` 调用 `loadGraph()`+`Query` 类**（loader 聚合 graph/ 节点与边、从书级 index.md front-matter 派生 structure、扫描 section/章 md 文末词书区块物化词书四类学习项），或按上述路径直读源文件切片（structure 与词书学习项**不在** `graph/` 下）。
- **禁止**让本地 agent 读 `knowledge/dist/`（那是给外部消费、且 gitignore 的编译产物）。

## 1. 本体（Ontology）

**8 类实体**：Textbook · Chapter · Section（structure，派生不落盘）· Concept · Word · Phrase · Sentence · Character
**5 类关系**：`covered_by` · `demonstrates` · `related` · `prerequisite` · `part_of`

| 关系 | 方向 | 含义 |
|------|------|------|
| `covered_by` | Concept → Section | 概念被某节覆盖（必选，每个 Concept 至少 1 条） |
| `demonstrates` | Word/Phrase/Sentence/Character → Concept | 词/句/汉字 例证某概念 |
| `related` | Concept ↔ Concept | 主题相关（对称，网状） |
| `prerequisite` | Concept → Concept | 先修（有向，构成 DAG） |
| `part_of` | Concept → Concept | 整体-部分（如「三角形」⊃「等腰三角形」） |

## 2. 实体 ID 格式

```
textbook:BSDU-7-1-Math
chapter :BSDU-7-1-Math-C1
section :BSDU-7-1-Math-C1-S1
concept :<学科>:<名称>           如  concept:数学:一次函数
```

## 3. 后端原语 `kg_ask.ts`（有界切片 / 闭包）

> 位置：`knowledge/tools/kg/src/kg_ask.ts`
> 运行：在本仓根目录用 `pnpm kg:ask <cmd> <id>`（根 workspace 无 tsx，**勿直接 `pnpm exec tsx tools/kg/src/kg_ask.ts`**；等价方式：`cd tools/kg && pnpm ask <cmd> <id>`）。

```bash
cd knowledge   # 本仓根目录
pnpm kg:ask tree      <textbookId>   # 章/节树
pnpm kg:ask concepts  <sectionId>    # 某节概念
pnpm kg:ask covered   <conceptId>    # 覆盖该概念的节
pnpm kg:ask prereq    <conceptId>    # 先修传递闭包（算法）
pnpm kg:ask demo      <conceptId>    # 例证该概念的 items
pnpm kg:ask related   <conceptId>    # 相关概念
pnpm kg:ask partof    <conceptId>    # 其上位话题（part_of 出边，部分→整体；反查组成部分暂无命令）
pnpm kg:ask mindmap   <sectionId>    # 给 LLM 组装脑图的聚合 JSON
```

> 解题模型正文不在图谱节点里，直接读章节 md 的 `## 解题模型` 区块。

`Query` 类方法（编程调用）：`conceptsForSection` / `prerequisitesOf`（传递闭包）/
`itemsDemonstrating` / `coveredBySection` / `sectionTree`。

## 4. 操作规则（强制执行）

1. **脚本一律在本仓根目录运行**（Python `llm_*.py` 以脚本位置锚定本仓根）。
2. **内容修复/校准默认由当前 agent 直接修改**（agent 即 LLM，用 rapidocr 参照验证忠实性），**不要求任何 LLM 凭据**。`src/llm_*.py` 批处理脚本仅为无 agent 环境的**备选**，运行才需凭据：OpenAI 兼容协议 `AI_API_KEY`/`AI_BASE_URL`/`AI_MODEL` 优先，或供应商专属 `DEEPSEEK_*`/`OPENAI_*`（`.env` 配置，见 `.env.example`）。
3. **幂等**：默认不覆盖已存在实体；重抽用 `--force`。关系按 `from→to` 去重追加。
4. **交付门禁**：每 Concept 至少 1 条 `covered_by`；每有正文的 section 至少贡献 1 概念（orphan→0）；`related`/`part_of`/`demonstrates` 任一类不得为 0；最终 `lint` 0 error 且 `kg:build` 后三类关系计数均 > 0。
5. **跨年级成网**：同/近主题跨年级概念建 `prerequisite`/`related`/`part_of`；跨学科（如数学图像 ↔ 物理图像法）建 `related`。不能只停在单本教材内。
6. **批量 id 用逗号分隔**（`--ids a,b,c`）；大文件（concepts 学科聚合、`related.yaml`/`demonstrates.yaml` 等大关系文件）严禁全量读入上下文，用 `kg_ask` 子命令切片。
7. **决策落盘**：每次录入/修订/重构后，在 `knowledge/tools/kg/state/log.md` 追加决策段（模板见该文件头）；方法论锚点（柳叶刀/渐进载入/三色步骤标注）见 `knowledge/tools/kg/skills/00-META.md`。

## 5. Skill 索引

> **总纲**:涉及图谱的操作(查询/摄入/抽取/修改)优先走 kg-* skill,不绕过管线手改 YAML——skill 内置幂等/去重/门禁,手改会绕过 lint 与交付门禁。
> **入口**:意图模糊时从 [kg-help/SKILL.md](kg-help/SKILL.md) 路由。自然语言触发不一定可靠,更稳的方式是直接指定 skill 名或"意图 + 材料路径"。
> **检索入口**:查询类任务先读 `knowledge/graph/index.md`(问句→路径映射 + ID 速查 + 局限声明)。

**四类定位(现在该用哪个)**:

| 类型 | 含义 | Skill |
|---|---|---|
| 拉式 | 处理已知内容:把材料变成图谱 | kg-ingest、kg-extract、kg-curriculum |
| 推式 | 发现未知缺口:体检与先修质量 | kg-review(lint 巡检)、kg-verify-prereq |
| 查询/消费 | 只读用图谱回答/画图 | kg-query、kg-mindmap |
| 闭环/维护 | 小修与串联:发现→修复→再验证 | kg-edit、kg-help(路由) |

> 四类为**使用视角**,下方消费/摄入分簇为**实现视角**,两者交叉不冲突。

| Skill | 文件 | 功能 |
|-------|------|------|
| `kg-help` | [kg-help/SKILL.md](kg-help/SKILL.md) | 意图路由入口:模糊请求 → 具体 kg-* skill 链,串联执行每步汇报 |
| `kg-edit` | [kg-edit/SKILL.md](kg-edit/SKILL.md) | 闭环/维护:单点微调,定位→判断改哪边→展示计划确认→写回→lint |

### 消费簇（用图谱）
| Skill | 文件 | 功能 |
|-------|------|------|
| `kg-query` | [kg-query/SKILL.md](kg-query/SKILL.md) | LLM 下钻 Textbook→Chapter→Section→Concept，读切片 + 语义匹配，回答知识点问题 |
| `kg-mindmap` | [kg-mindmap/SKILL.md](kg-mindmap/SKILL.md) | 组装章节树 + part_of 层级 + 先修 DAG + 相关 → Mermaid 脑图 |
| `kg-review` | [kg-review/SKILL.md](kg-review/SKILL.md) | lint + build 巡检报告（缺口/孤儿/环/关系计数） |
| `kg-delta` | [kg-delta/SKILL.md](kg-delta/SKILL.md) | 知识缺口状态机（建卡→调研→草稿→发布收尾四件套） |
| `kg-repair` | [kg-repair/SKILL.md](kg-repair/SKILL.md) | content 修复统一方法论（五层验收+六步既有工具组合管线；LOW 必须取证归因；管线外手术禁止） |

### 摄入簇（建图谱）
| Skill | 文件 | 功能 |
|-------|------|------|
| `kg-ingest` | [kg-ingest/SKILL.md](kg-ingest/SKILL.md) | 编排器：包装现有 SKILL_00~07 全管线（init→ocr→polish→repair→format→sync→extract→verify→build） |
| `kg-curriculum` | [kg-curriculum/SKILL.md](kg-curriculum/SKILL.md) | 大纲层：跨年级成网、完整性门禁、standards 对齐 |
| `kg-extract` | [kg-extract/SKILL.md](kg-extract/SKILL.md) | 抽取层：概念/词书四类/关系/公式 抽取规范（指向 SKILL_02~05、07） |
| `kg-verify-prereq` | [kg-verify-prereq/SKILL.md](kg-verify-prereq/SKILL.md) | 先修层：Pass2 验 prerequisite、保 DAG 无环、补 `part_of` |

### 内容制作簇（教学资源，非 kg-* 系列）
| Skill | 文件 | 功能 |
|-------|------|------|
| `reading-scene-animation` | [reading-scene-animation/SKILL.md](reading-scene-animation/SKILL.md) | 朗读 + Three.js 3D 场景：逐句 TTS 驱动镜头的独立静态 HTML(逐字点亮,叠层节奏/韵脚/注释/对仗)。触发:「把某篇/某段做成朗读场景/3D 场景/沉浸式朗读」 |

## 6. 如何加载这些 Skill（安装方式）

- **维护位置**：本目录 `knowledge/tools/skills/` 是唯一事实来源。
- **安装到 CodeBuddy（项目级，推荐）**：在仓库根建 `.codebuddy/skills/`，软链指向本目录：
  ```bash
  cd /path/to/faststudy-knowledge
  mkdir -p .codebuddy/skills
  for s in kg-query kg-help kg-mindmap kg-review kg-extract; do
    ln -s "$(pwd)/knowledge/tools/skills/$s" ".codebuddy/skills/$s"
  done
  ```
  装完**重启会话**才生效；`.codebuddy/skills/` 已 gitignore（软链含机器相关绝对路径）。
- **安装到 CodeBuddy（用户级，全局可用）**：`ln -s /path/to/faststudy-knowledge/knowledge/tools/skills/kg-query ~/.codebuddy/skills/kg-query`
- **安装到 Claude Code**：同上，把 `.codebuddy/skills/` 换成 `~/.claude/skills/`。
- 若宿主不识别软链，改为复制安装，但复制件视为只读镜像，修改仍回本目录。
- 加载后，每次处理知识库任务前，先读本 `INDEX.md` 的架构与操作规则，再加载具体子 skill。
