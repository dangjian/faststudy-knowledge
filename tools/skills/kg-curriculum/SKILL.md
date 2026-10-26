---
name: kg-curriculum
version: "2026.1"
description: 大纲层——跨年级成网、完整性门禁、与 curriculum/chapter-standards 对齐。保证初中知识「成网」而非散点，是单本摄入后的全局 Pass。
---

# kg-curriculum — 大纲层（跨年级成网）

## 何时用
- 一批教材抽完后做全局关联（SKILL_00 阶段五）。
- 用户要「把几个年级的知识串起来 / 检查完整性 / 对齐课标」。

## 1. 跨年级成网（全局 Pass，必做）
单本教材只是「点」，初中知识要「成网」。全部教材抽完后，按 **学科 + 年级顺序（七→八→九）** 做全局关联：

- **同/近主题跨年级概念** → 建 `prerequisite` / `related` / `part_of`
  - 例：七下「用字母表示数」→ 八上「整式」(prerequisite)；八下「一次函数」→ 九上「二次函数」(prerequisite)。
- **跨学科关联**（如 数学「函数图像」↔ 物理「图像法」）→ 建 `related`。
- 这一步不能只停在单本教材内。确定性骨架可由 `kg:infer` 推导
  （`infer_relations.ts`：demonstrates/related/prerequisite 跨年级，加边前可达性检测保 DAG 无环）。

## 2. 完整性门禁（Completion Gate）
- **三年级 × 9 学科**（语/数/英/物/化/史/地/生/道法）都要有概念且被 `covered_by` 覆盖。
- 每 Concept ≥ 1 条 `covered_by`；每有正文 section 至少贡献 1 概念（orphan→0）。
- `related`/`part_of`/`demonstrates` 任一类 **不得为 0**（按学科产出）。
- 最终 `lint` 0 error，且 `kg:build` 后 `dist/stats.json` 三类关系计数均 > 0。

## 3. 课标对齐
- 图谱含 `knowledge/graph/curriculum-standards.yaml` 与 `chapter-standards.yaml`。
- 巡检时比对：课标知识点是否都有对应 `Concept` + `covered_by`；缺失的列入待摄入清单（转 `kg-ingest`）。
- 年级/学期映射以 standards 为准，避免章节 id 错位。

## 4. 工具
- `infer_relations.ts`（`kg:infer`）：确定性跨年级骨架，DAG 无环保障。
- `diag_gap.py`：内容缺口诊断（哪些章节/概念尚未录入）。
- `fix_covered_by.ts` / `link_orphans_by_title.ts`：补链与修 sourceRef（见 kg-extract / kg-verify-prereq）。

## 反模式
- ❌ 只做单本关联就交付（缺跨年级）。
- ❌ 手工加 `prerequisite` 不检测环（用 `kg:infer` 或 `prereq` 抽样验无回溯）。
- ❌ 把内容缺口当工具 bug（先 `diag_gap.py` 比对源数据）。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 初版版本化（借鉴 omp-knowledge kg-* 系列的版本化实践） |
