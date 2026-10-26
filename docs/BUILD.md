# 换一套教材重建图谱

本仓库的 99 册以**西安当前在用教材**为例。其他地区用同一套流程重建，只需替换 `content/` 下的教材，再重跑抽取与校验。

---

## 1. 当前用的是哪一套

| 版本 | 出版社代码 | 学科 | 册数 | 年级 |
|---|---|---|---:|---|
| 北师大版 | `BSDU` | 数学 | 18 | 1–9 |
| 人教版 | `PEP` | 语文 | 18 | 1–9 |
| 人教版 | `PEP` | 道德与法治 | 18 | 1–9 |
| 人教版 | `PEP` | 英语 | 13 | 3–9 |
| 教科版 | `ES` | 科学 | 12 | 1–6 |
| 人教版 | `PEP` | 历史 | 6 | 7–9 |
| 中图版 | `ZTB` | 地理 | 4 | 7–8 |
| 人教版 | `PEP` | 生物 | 4 | 7–8 |
| 苏科版 | `SK` | 物理 | 4 | 8–9 |
| 科粤版 | `KY` | 化学 | 2 | 9 |

版本记录在每本书 `index.md` 的 `publisher` 字段里，也是教材 ID 的前缀（如 `BSDU-7-1-Math`）。

---

## 2. 换地区要动什么

仓库分两层，换教材只动这两层：

| 层 | 位置 | 内容 |
|---|---|---|
| **L1 教材** | `content/` | 教材原文（Markdown）+ 书级结构（章节树、页码区间） |
| **L2 图谱** | `graph/` | 概念、关系、课标条目与章节映射 |

`dist/` 是编译产物，由 `kg:build` 重算，不入库、不手改。

**目录布局**（每本书一个目录）：

```
content/七年级/上册/数学/BSDU-7-1-Math/
├── index.md                      # 书级 front-matter：元数据 + 章节树（含页码）
└── chapters/C1/
    ├── index.md                  # 章
    └── sections/S1.md            # 节 = 教材正文 + 文末词书区块
```

---

## 3. 构建流程

由 `kg-ingest` 编排（见 `tools/skills/kg-ingest/SKILL.md`），两条入口：

**纸质/PDF → 全管线**

```
init → ocr → polish → repair → format → sync → extract → ingest → verify → build
```

**已有 Markdown → 注入管线**（含讲义、专题等扩展素材，落成 `EXT-` 虚拟教材）

```
propose → apply → extract → ingest → build
```

命令：

```bash
# 源数据目录默认 source_data/，也可用环境变量指定
KG_SOURCE_DIR=/path/to/pdf pnpm kg:ingest
```

**Python 依赖**（只有注入/重切这一路需要；`kg:lint`/`build`/`test`/`eval` 全是 TypeScript，不需要 Python）：

```bash
pip install -r tools/kg/requirements.txt   # 主要是 pyyaml
```

不装会直接 `ModuleNotFoundError: No module named 'yaml'`——这是当前最常见的阻塞。

---

## 4. 四个会直接失败的前置

| 前置 | 不满足的后果 |
|---|---|
| 书级 `index.md` front-matter 完整 | 缺 `textbookId`/`grade`/`term`/`subject`/`publisher`/`chapters[]` 任一，该书被静默跳过或 lint 报错 |
| 每个节有 `pageRange` | lint `pageRange-required` 报 error，`build` 拒绝产出 |
| 教材 ID 用出版社前缀（`BSDU-*` / `PEP-*`） | **目前无 lint 强制**，靠约定；写成别的前缀不会报错，但跨书引用（概念 `sourceRef`、章节 ID）会难以辨认 |
| `KG_SOURCE_DIR` 可读 | 缺失直接报错退出（不静默降级） |

---

## 5. 结构修偏（三个命令组）

换教材时若「章节切得不对」或「素材还没成书」，用下面三组命令修结构，不必重跑全管线。

### 5.1 内容注入：把一份现成 Markdown 变成一本书

```bash
# ① 扫标题层级 → outline.json（确定性，不调 LLM）
pnpm kg:book:propose -- --textbook-id EXT-Astronomy-Basics \
  --md notes/astronomy.md --subject 天文 --grade 7 --term 1 \
  --title 天文学基础 --source '《XXX》第 3 版'

# 多份 md 按给定顺序拼接（每份之间不插入任何内容）
pnpm kg:book:propose -- --textbook-id EXT-... --md a.md --md b.md ...

# ② 确认过的 outline → content/ 书骨架（先 dry-run 看要写哪些文件）
pnpm kg:book:apply -- --textbook-id EXT-Astronomy-Basics --dry-run
pnpm kg:book:apply -- --textbook-id EXT-Astronomy-Basics
```

`book:propose` 必需参数：`--textbook-id` `--md` `--title` `--grade` `--term` `--subject`；
其余（`--publisher` `--source` `--total-pages` `--standard-edition` `--image-offset` `--force`）可选。

### 5.2 章节重切（三阶段，OCR 与写盘刻意分离）

```bash
pnpm kg:reoutline:propose -- --textbook BSDU-8-2-Math     # 对比目标态，产出重切台账（确定性）
pnpm kg:reoutline:ocr -- --textbook BSDU-8-2-Math --sections C1-S2 C2-S1   # 只补台账里需 OCR 的节
pnpm kg:reoutline:apply -- --textbook BSDU-8-2-Math       # 默认 dry-run，只打印写盘清单
pnpm kg:reoutline:apply -- --textbook BSDU-8-2-Math --apply   # 确认后实写
```

`apply` 只认 **confirmed** 台账、纯确定性、逐字节幂等；OCR 与 LLM 是非确定性的，所以单独成命令，
不让它们混进写盘那一步。

### 5.3 修既有数据

```bash
pnpm kg:infer -- --dry     # 先看会推导出多少条 demonstrates/related（不写盘）
pnpm kg:infer              # 实写（并集，不覆盖已有边）
pnpm kg:fix:covered        # 按 sourceRef 补 covered_by
pnpm kg:fix:orphans        # 把孤儿概念按同名标题挂到节
```

⚠ `fix:covered` 与 `fix:orphans` **没有 dry-run，直接写盘**。跑之前先 `git status` 确认工作区干净，
跑完用 `git diff` 复核。

## 6. 验收

每完成一步都跑一次，全绿才算完成：

```bash
pnpm kg:lint    # 22 条规则，0 error
pnpm kg:build   # 产出 dist/
pnpm kg:test    # 168 个单测
pnpm kg:eval:covered && pnpm kg:eval:prereq && pnpm kg:eval:partof
pnpm kg:eval:type && pnpm kg:eval:mastery && pnpm kg:eval:strength
```

`kg:eval:*` 是人工金标回归：判为正确的内容一旦消失或被改判，退出码即 1。**换教材后金标可能不再适用**（它们绑定具体概念 ID），需要重新抽样建标，判据见 `tools/kg/eval/rubric-cases.md`。

---

## 7. 换地区时哪些共用、哪些要重做

| 项 | 是否共用 |
|---|---|
| 本体（实体/关系类型）、lint 规则、查询 skill、抽取 skill | **共用**，与教材版本无关 |
| 概念、关系、词书 | 要重抽（不同教材的知识点顺序与表述不同） |
| `chapter-standards.yaml`（章节 → 课标主题码） | 要重做：按章节标题规则生成，换书后标题全变 |
| 人工金标 | 要重抽：绑定具体概念 ID |
| `conceptType` / `strength` | 要重判：这两列是逐条语义判定，不能从旧教材迁移 |

**不要做的事**：把两个地区的教材混在同一份图谱里。概念按 `subject` 聚合在同一文件（`graph/entities/concepts/<学科>.yaml`），混入会导致同名概念冲突与课标映射歧义。需要多地区时，建议一个地区一份仓库、共用本仓库的工具链。
