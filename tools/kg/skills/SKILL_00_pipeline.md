> ⚠️ **未适配 v4**：下文「分层 v3」约束中 concepts/models/exercises 聚合与 items/supplements 路径已变更——v4 仅 `entities/concepts/`，词书与解题模型正文写章节 md 文末区块。启用前需先核对。

# SKILL_00 - 抽取编排器

你是 FastStudy 知识库抽取编排器。按以下顺序对一本教材执行抽取：

1. SKILL_01 OCR 文本化：页面图 -> content/ prose
2. SKILL_02 抽概念 + 跨教材去重
3. SKILL_03 抽 items（词/短语/句/汉字/图）
4. SKILL_04 抽关系（covered_by 必选，demonstrates 按学科可选，prerequisite 候选）
5. SKILL_05 Pass2 验 prerequisite
6. SKILL_06 抽 figures（几何用语义描述符）
7. SKILL_07 抽公式 LaTeX（数学/物理，用视觉模型）

约束（分层 v3）：**节点身份+关系写 `graph/`（concepts/models/exercises 按学科聚合 + relations/）；prose、items md、supplements 正文写 `content/`，且 content 下只能是 md；structure（Textbook/Chapter/Section）与五类学习项由 content md 派生，不落盘**。正文约定：`index.md` 为章级真源，`sections/` 由 `sync_sections_from_index.py` 派生。幂等：默认不覆盖已存在实体，`--force` 重抽。
完成后跑 `tools/kg lint` + `build`，0 error 才算完成。

## 批量处理策略

### 阶段一：结构初始化（一次性）
1. 分析教材目录，确定 imageOffset（页面图编号 vs 教材页码）
2. 写书级 `index.md`（front-matter 承载完整章节目录 + pageRange）
3. 回填书级 `index.md` front-matter 的 `chapters` 键（每章 id/title/order/pageRange/sections，**结构唯一源**；Textbook/Chapter/Section 节点由 loadGraph 从它即时派生，不再生成 structure 实体文件）

### 阶段二：逐章 OCR（SKILL_01）
- 每章 OCR 完后立即跑 `lint`，确保 YAML 格式正确
- 优先 aliyun-ocr basic，备选 Tesseract

### 阶段三：逐章抽取（SKILL_02 + SKILL_03 + SKILL_04）
- 按章处理，一章内按 section 顺序
- 概念去重：每章抽取前先读已有概念列表，避免重复创建
- 每章完成后跑 `lint + build`，确保增量正确

### 阶段四：全量验证（SKILL_05 + 最终 lint）
- SKILL_05 验 prerequisite 全量
- 最终 `lint + build` 0 error

### 阶段五：跨年级整体关联（全局 Pass，必做）
单本教材抽完只是"点"，初中知识要"成网"。全部教材抽取完后，必须按 **学科 + 年级顺序（七 → 八 → 九）** 做全局关联：
- 同一学科内，低年级已学概念 → 高年级同/近主题概念：建立 `prerequisite` / `related` / `part_of`。
  - 例：七下"用字母表示数" → 八上"整式"（prerequisite）；八下"一次函数" → 九上"二次函数"（prerequisite）。
- 跨学科关联（如 数学"函数图像" ↔ 物理"图像法"）建立 `related`。
- 这一步是"整体梳理几个年级知识"的关键，不能只停在单本教材内。详见 SKILL_04「跨年级关联」。

### 完整性门禁（Completion Gate，交付前必查）
- **三个年级 × 9 学科**（语文/数学/英语/物理/化学/历史/地理/生物/道德与法治）都要有概念且被 `covered_by` 覆盖。
- 每个 `Concept` 至少 1 条 `covered_by`；每个有正文的 section 至少贡献 1 个概念（orphan warning 应趋近 0）。
- `related` / `part_of` / `demonstrates` 任一类**不得为 0**（按学科产出，见 SKILL_04）。
- 最终 `lint` 0 error，且 `kg:build` 后 `dist/stats.json` 三类关系计数均 > 0。

### 预估工作量
| 教材 | Section 数 | 预估轮次 |
|------|-----------|---------|
| 语文 PEP-7-2-Chinese | 42 | 6 章 × 1 轮 |
| 数学 BSDU-7-2-Math | ~30 | 6 章 × 1 轮 |

### 幂等保障
- content prose：sectionId 同名文件已存在则跳过（`--force` 重抽）
- concept：按 id 查重，存在则跳过
- items：按 sectionId 聚合文件，存在则跳过
- relations：按 `from->to` 去重追加