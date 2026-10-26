---
name: kg-ingest
version: "2026.1"
description: 知识库摄入编排器。两条入口：纸质教材走 OCR 全管线（init→ocr→polish→repair→format→sync→extract→ingest→verify→build）；已成 md 的素材（含 EXT- 扩展知识）走注入管线 propose→apply→extract→ingest→build。源数据目录由 `KG_SOURCE_DIR` 指定（默认仓内 `source_data/`，缺失即报错，见 .env.example）。
---

# kg-ingest — 摄入编排器

## 何时用
- 要把新教材（或 21 本缺口教材）录入图谱。
- 要把一份**扩展素材**（讲义、专题、课外读物）注入成 `EXT-` 虚拟教材。
- 用户说「摄入 / 建图谱 / 抽这本教材 / 把八下九上补上 / 把这份材料加进去」。
- 「更新图谱 / 加知识」类**模糊**入口词由 `kg-help` 统一接管路由,本 skill 不抢注;本 skill 由具体动词触发(摄入/录入/抽这本教材 + 明确材料)。

## 先选入口：素材现在是什么形态？

| 素材形态 | 走哪条 | 起点 |
|---|---|---|
| 纸质教材扫描件 / PDF | **A. OCR 管线** | 下面「管线 A」第 1 步 |
| 已经是 md | **B. 注入管线** | 下面「管线 B」第 ① 步 |
| docx / html / epub / 网页 | 先转成 md，**再走 B** | 转换在管线之外，不进本 skill |

> **md 是注入管线的入口契约。** 管线不做格式转换——把 docx/pdf 转 md 用什么工具是你的自由，
> 但交给 `book_propose.py` 的必须已经是 md。这条边界是有意划的：格式转换的失败模式
> （表格塌陷、图丢失、编码错乱）与知识抽取的失败模式毫无关系，混在一条管线里没法单独验收。

## 源数据（已就位，无需新建）
源图目录由环境变量 `KG_SOURCE_DIR` 指定（默认仓内 `source_data/`，缺失即报错，见 `.env.example`）：
- 全部教材 PDF（命名 `（根据2022…）义务教育教科书·X七/八/九年级…pdf`）
- 21 个已处理教材文件夹 `{id}/metadata.json`(TOC→页码) + `pages/*.jpg`(渲染页图)
- `chapters_reference.json`

## 管线 A：纸质教材（OCR）
完整步骤见 **`knowledge/tools/kg/skills/SKILL_00_pipeline.md`**（本 skill 是对它的上层编排说明）。

1. **init**（确定性）：由 `metadata.json` 生成书级 `index.md`（front-matter 承载教材元信息与章节目录）+ 章节 stub。
2. **ocr**（RapidOCR 本地，无云费）：`pdf_ocr_to_index.py` 优先读 `$KG_SOURCE_DIR/{id}/pages/*.jpg`。
3. **polish / repair / format**：默认由当前 agent 直接修改（用 OCR 参照验证忠实性）；外部 API 校准链已移除（2026-10-15）——校准一律由当前 agent 按 kg-repair S2 在上下文中执行。
4. **sync**（确定性）：`sync_sections_from_index.py` 由章级 `index.md` 派生 `sections/S*.md`。
5. **extract**：见 `kg-extract`。产出 `state/ingest/<id>/extract/*.json`，**不写图谱**。
6. **ingest**（确定性）：`pnpm kg:ingest --textbook <id>` 把 extract JSON 落盘。**漏了这步，后面的 lint+build 会在图谱毫无变化的情况下全绿——那是静默成功，不是通过。**
7. **verify**：见 `kg-verify-prereq`（Pass2 验先修 + 保 DAG）。
8. **build**：`kg:lint` + `kg:build`，0 error 才算完成。

## 管线 B：已成 md 的素材（注入）

五步，**LLM 只出现在 ①→② 之间和第 ③ 步；所有写盘都是确定性代码**。

```bash
cd knowledge   # 本仓根目录

# ① propose：扫 md 标题，产出待人工确认的切分台账（不写 content/）
pnpm kg:book:propose --textbook-id EXT-Astronomy-Basics \
  --md tmp/astro.md --title 天文学基础 --grade 7 --term 1 \
  --subject Astronomy --subject-dir 天文 --source '《天文学新概论》第 4 版'
#   → tools/kg/state/ingest/EXT-Astronomy-Basics/outline.json

# ①.5 你（agent）读 md，把 outline.json 的 chapters 填成章/节结构，交人确认
#     每个 chapter/section 给 id / title / order / fromLine / toLine

# ② apply：按台账切片写 content/（书级 index.md + 章 index.md + 节 S<m>.md）
pnpm kg:book:apply --textbook-id EXT-Astronomy-Basics

# ③ extract：抽概念/词书/关系 → extract JSON，不写图谱
#    默认：当前 agent 按 SKILL_02~04 规范直接产出 extract JSON（无需凭据）
#    备选（无 agent 批处理）：python3 tools/kg/src/llm_extract_graph.py <教材目录> --batch（需 .env 凭据）

# ④ ingest：唯一写盘方
pnpm kg:ingest --textbook EXT-Astronomy-Basics

# ⑤ 验收
pnpm kg:lint && pnpm kg:build && pnpm kg:test
```

**为什么切成 propose/apply 两段**：LLM 的判断先落成可 diff、可复核、可重放的中间文件（`outline.json`），
人在这个文件上确认，然后由确定性代码写盘。与本仓 difficulty 打标、字符清洗规范（2026-08）、扩展知识清洗规范 用的是同一套
export→台账→apply 范式。重跑 `apply` 逐字节幂等。

### 扩展知识（EXT-）的三条约定
- **id 必须 `EXT-` 前缀**，且 `origin: extension`。两者双向连锁：`EXT-` 前缀而 `origin: textbook`、
  或反之，`book_outline.py` 写入前就拦、lint rule 15 落盘后再拦一道。
- **`source` 必填**（书名/站点/作者），原始教材反而**禁填**。出处不明的材料不要注入。
- **不写 `pageRange`**。扩展知识没有纸质页码，**绝不用 md 行号冒充**（页码约定 裁决：`pageRange`
  恒为教材页号）。行号只在 `outline.json` 里用于切片，不进任何实体。
  原始教材的 `pageRange` 必填性由 lint rule 17 强制，严格程度不减。

## 批量入口
```bash
cd knowledge   # 本仓根目录
python tools/kg/src/batch_graph_8_9.py   # 对八下+九年级跑 extract → ingest → lint + build
```
- ⚠️ `batch_content_8_9.py` 已 **OBSOLETE**（写死批次 + 依赖已删除的 `textbook.yaml`），勿在新教材上使用；
  通用路径见 `pdf_ocr_to_index.py` / `batch_ocr.py` / `gen_section_stubs.py`。
- Python 依赖见 `tools/kg/requirements.txt`（建议固定 venv 运行，勿依赖系统全局环境）。
- LLM 凭证由脚本自动读本仓根 `.env` 加载（见 `.env.example`；**须在本仓根目录运行**）。

## 21 本缺口 id（2026-08-02 终态：全部 init 完成，OCR 进行中）
- 八下(8)：BSDU-8-2-Math, PEP-8-2-English, PEP-8-2-Chinese, SK-8-2-Physics,
  PEP-8-2-Biology, PEP-8-2-History, PEP-8-2-Politics, ZTB-8-2-Geography
- 九(13)：BSDU-9-1-Math, BSDU-9-2-Math, PEP-9-0-English, PEP-9-1-Chinese, PEP-9-2-Chinese,
  PEP-9-1-History, PEP-9-2-History, PEP-9-1-Politics, PEP-9-2-Politics,
  SK-9-1-Physics, SK-9-2-Physics, KY-9-1-Chemistry, KY-9-2-Chemistry

## 完整性门禁（交付前必查，详见 INDEX §4）
- 三个年级 × 9 学科都有概念且被 `covered_by` 覆盖；orphan→0；
  `related`/`part_of`/`demonstrates` 任一类 ≠ 0；`lint` 0 error 且 `kg:build` 后三类关系计数 > 0。
- **跨年级成网**：见 `kg-curriculum`。

## 反模式
- ❌ 在仓外或上级目录跑脚本（路径锚定失效，须在本仓根目录运行）。
- ❌ 覆盖已存在实体（默认幂等，重抽 `--force`）。
- ❌ 单本抽完就交付（缺跨年级关联，见 kg-curriculum）。
- ❌ **抽完 extract JSON 就跑 lint+build 交付**（漏第 ④ 步 ingest，图谱根本没变，全绿是假的）。
- ❌ **拿 md 行号当 `pageRange` 写进实体**（`pageRange` 恒为教材页号，页码约定）。
- ❌ **手写 `content/` 下的书级/章级 index.md 来建新书**（结构走 `book_apply.py`，手写会与 outline.json 脱钩且不幂等）。

## 仓库位置与产物（分层 v4）
知识库是独立仓库，位于 `knowledge/`：
- `content/`（L1「学什么」）：章节文档承载一切内容——书级 `index.md`（front-matter 的 `chapters` 键 = 结构唯一源）、`chapters/C<n>/index.md`（章级真源 + 章级词书区块）、`chapters/C<n>/sections/S<m>.md`（节正文 + 文末区块：`## 汉字/单词/短语/句子` 词书四类表格、`## 插图` 纯文本图注、`## 解题模型`、`## 笔记`/`## 总结`）。**content/ 下不得出现任何 yaml**（lint rule 10 强制）。
- `graph/`（L2「知识如何连接」）：`ontology.yaml`（含 storage 归属声明）+ `entities/concepts/<学科>.yaml`（按学科聚合）+ `relations/` 5 类边（covered_by/demonstrates/prerequisite/related/part_of）。**不再有 `entities/items/`、`entities/models/`、`entities/structure/`**——structure 由 loadGraph 从书级 index.md front-matter 派生，词书四类学习项由章节 md 文末区块派生。
- `dist/`：只读派生（`graph.json`/`stats.json`/`manifest.json`），外部消费用，本地禁止读取。
- `tools/kg/skills/`：抽取 prompt 文档 SKILL_00~08。

## 铁律（不可违反，与 kg-extract / kg-verify-prereq 共用）
- **完成标准**：必须跑 `kg:lint` + `kg:build`，**0 error 才算完成**。
- **幂等**：默认不覆盖已存在实体（按 id/sectionId 查重跳过），`--force` 才重抽。
- **每章增量验证**：每完成一章立即 `lint + build`，确保增量正确，不要攒到最后。
- **概念去重**：每章抽取前先读已有概念列表，避免重复创建。
- **产出位置**（分层 v4）：**节点身份+关系写 `graph/`（concepts 学科聚合 + relations/）；prose、词书区块、解题模型等正文写 `content/` 章节 md，且 content 下只能是 md；structure 与词书四类学习项由 content md 派生，不落盘**。写入统一走 `ingest.ts` 的 `writeExtract()`（lint rule 10 layer-placement 强制归属）。

## 已知陷阱
- **YAML boolean 坑**：英文句子/词条里的 `off / on / yes / no / true / false` 会被 YAML 1.1 解析器读成 boolean，导致 lint 报 `expected string, received boolean`。**`writeExtract()` 已自动 requote**（补单引号），走工具写入无需手工处理；确需手写 YAML 时这些词仍必须加引号（单双均可）。
- **sourceRef 必填**：每个 word/phrase/sentence/character 都要写 `sourceRef`，指向对应 content 文件（如 `content/七年级/下册/英语/PEP-7-2-English/chapters/C2/sections/C2-S1.md`），否则 lint warning。

> 注：本节「铁律 / 已知陷阱 / 仓库位置」由原 `.claude/skills/knowledge-graph` 技能合并而来（2026-08-03 去重，单一摄入入口归并到本 skill）。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 初版版本化（借鉴 omp-knowledge kg-* 系列的版本化实践） |
