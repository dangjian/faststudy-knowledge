---
name: kg-verify-prereq
version: "2026.1"
description: 先修层——Pass2 验证 prerequisite、保 DAG 无环、补 part_of。保证先修链可经 prereq 闭包正确遍历，是知识递进学习的地基。
---

# kg-verify-prereq — 先修层验证

## 何时用
- 抽取后做 Pass2 先修校验。
- 用户要「验先修 / 查有没有环 / 补 part_of / 先修链对不对」。

## 1. Pass2 验 prerequisite（实现见 `SKILL_05_verify_prerequisites.md`）
- 对全量 `Concept` 复核 `prerequisite` 候选：方向正确（先→后）、证据充分。
- 证据充分时允许新增 **跨年级** `prerequisite`（原 SKILL_05 已放开）。
- 每个 `prerequisite` 边应能经 `kg_ask prereq` 正确回溯到根概念。
- **新增/改写边必须标 `reviewed`**：`audited`（逐条判定过）或 `sampled`（仅抽样验收）。
  缺字段时 lint rule 24 告警，且该边会被下游先修闭包直接排除——症状是补救路径少一环。
  跨册批次新增的边先标 `sampled`，逐条判定通过后再改 `audited`。

## 2. 保 DAG 无环（关键）
- `prerequisite` 必须构成 **有向无环图（DAG）**。加边前做可达性检测。
- 工具：`infer_relations.ts`（`kg:infer`）加边前自动检测；巡检时抽样 `prereq` 验无回溯环。
- 发现环：断最弱证据边，记录理由，不静默保留。

## 3. 补 part_of（整体-部分层级）
- `part_of` 已大规模补录（口径 B 把大量含容边从 prerequisite 迁到这里），新知识的整体-部分仍走语义抽取（见 `kg-extract`）。
- 例：图形家族（三角形⊃等腰/直角/等边）、数系（实数⊃有理数⊃整数…）、语法（句子⊃短语⊃词）。
- 写 `part_of` 边后，`kg-mindmap` 才能展开整体-部分分支。

## 4. 验证命令
```bash
cd knowledge   # 本仓根目录
pnpm --filter @faststudy/kg run lint          # 0 error
pnpm exec tsx tools/kg/src/kg_ask.ts prereq <conceptId>   # 抽样验闭包无环、方向对
pnpm exec tsx tools/kg/src/kg_ask.ts partof <conceptId>   # 验 part_of 下游
```

## Finding 输出契约

> 与 kg-review 共用同一 finding 格式,便于未来统一处理。

验证产出的每条问题必须结构化为:

```json
{ "dimension": "direction|cycle|part_of_coverage|cross_grade", 
  "findings": [{ "type": "missing_entity|wrong_classification|wrong_relation|inconsistency",
                 "description": "问题一句话(含具体 id)",
                 "fix": "建议动作一句话" }] }
```

分派规则(按 type):
| type | 去向 |
|---|---|
| missing_entity | kg-extract 补抽(成块)/ kg-edit(单个) |
| wrong_classification | kg-edit(改字段/挂靠) |
| wrong_relation | kg-edit(单条)/ 成批 → 建 gap(如 先修方向判据修订（2026-08）) |
| inconsistency | 先建 gap 调查,裁决后分派 |

约束:系统性/成批问题(同类 ≥3 条)不逐条派发,收敛为一条 finding 并建 gap;finding 的 description 必须含可定位的实体/边 id,禁止"部分概念有问题"式模糊表述。

## 反模式
- ❌ 手工加 `prerequisite` 不检测环（必用可达性检测）。
- ❌ 把环当「互为先修」保留（知识有先后，断弱边）。
- ❌ 忽略跨年级先修（七→八→九递进，见 kg-curriculum）。

## 边界
- 本 skill 只读 + 报告 + 最小补边；大批量重抽转 `kg-ingest`（幂等/`--force`）。

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 初版版本化（借鉴 omp-knowledge kg-* 系列的版本化实践） |
