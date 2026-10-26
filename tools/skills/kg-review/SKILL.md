---
name: kg-review
version: "2026.1"
description: 知识库健康巡检。跑 kg:lint + kg:build，产出缺口/孤儿/环/关系计数报告，指出修复入口 skill。
---

# kg-review — 图谱巡检报告

## 何时用
- 用户要「检查图谱质量 / 出巡检报告 / 看缺什么 / 完整性核对」。
- 摄入一批教材后、或定期体检时。

## 巡检流程

### Step 1 — 静态校验
在本仓根目录运行：
```bash
pnpm --filter @faststudy/kg run lint
pnpm --filter @faststudy/kg run build   # 产出 dist/stats.json
```
- `lint` 0 error 才合格；记录 error / warning 行。
- `build` 成功后读 `knowledge/dist/stats.json` 拿关系计数（注意：stats 仅用于巡检统计，本地查询仍走 `graph/`）。

### Step 2 — 健康维度核对（对照 INDEX §4 门禁）
| 维度 | 合格标准 | 检查方式 |
|------|----------|----------|
| 覆盖 | 每 Concept ≥1 条 `covered_by` | lint orphan / `covered` 抽样 |
| 孤儿 | orphan 概念 → 0 | lint 输出 |
| 关系非空 | `related`/`part_of`/`demonstrates` 任一类 ≠ 0 | stats.json 计数 |
| 无环 | `prerequisite` 构成 DAG | `kg:infer` 可达性检测（已内置）/ 巡检时跑 `prereq` 抽样验无回溯 |
| 跨年级 | 同/近主题跨年级有 `prerequisite`/`related` | `related`/`prereq` 抽样 |

### Step 3 — 缺口诊断（内容缺口）
- 若某教材/章节只有结构无概念，或 orphan 确属内容未转录：
  跑 `diag_gap.py`（本仓工具）或人工比对 `KG_SOURCE_DIR` 源数据，列出待摄入清单。

### Step 4 — 产出报告
报告结构：
1. **总览**：节点/边规模、build 是否通过。
2. **问题清单**：按严重度（error / warn / gap）列出，每条给：现象 + 影响 + 修复入口 skill
   （如 orphan 概念 → `kg-ingest` 补抽；`part_of` 为空 → `kg-extract` 补语义；跨年级缺失 → `kg-curriculum`；单点字段错 → `kg-edit`）。
3. **建议下一步**：明确的修复任务序列。
4. 巡检发现的系统性问题若当场不修,录入 `仓外治理记录（不入公开仓）`(规范见 仓外治理记录（不入公开仓）README.md),并在报告中附 gap 链接。

## Finding 输出契约

> 本契约是机器可读层,叠加于 Step 4 人类可读报告之上:报告照常写,每条问题同时结构化为 finding。

巡检产出的每条问题必须结构化为:

```json
{ "dimension": "orphan|relation_count|cycle|coverage|semantic", 
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

## 语义复核维度（程序化检查之外的 agent 人工复核清单）

程序化 lint 全绿不等于图谱正确。以下维度逐书抽样复核（借鉴 omp-knowledge kg-lint 的 reflect 层）：

1. **实体分类合理性**——Concept 的 category 与 explanation 是否匹配
2. **关系方向正确性**——prerequisite 端点是否写反（「拿掉 to，from 讲不通」判据）；part_of 是否该是反向
3. **命名一致性**——同概念跨书/跨册 title 与 aliases 是否一致
4. **sourceRef 精度**——指向的节是否真的承载该概念（非仅同章擦边）
5. **跨册一致性**——同一知识点在不同年级册的表述口径
6. **过时信息**——frontmatter/pageRange 与 content 现状是否脱节

## 反模式
- ❌ 用 `dist/graph.json` 当查询源（仅 stats 用于统计）。
- ❌ 只报 lint 0 error 就宣称健康（还要核关系计数/孤儿/跨年级）。
- ❌ 把内容缺口误判为工具 bug（先比对源数据）。

## 边界
- 巡检只读 + 报告，**不自动修复**。修复交给对应修复 skill(kg-edit/kg-extract/kg-ingest/kg-curriculum)，且重抽需幂等/`--force`。

## 硬边界(消费型约束)

- **只读+报告**:不改图谱/content/任何文件,不产生 git 变更;修复建议分派到 kg-edit(单点小改)/kg-extract(补语义抽取)/kg-ingest(orphan 补抽)/kg-curriculum(跨年级缺失),不顺手修
- **诚实性**:图谱没有的知识点就是没有——缺口必须如实报"图谱未覆盖",严禁编造;报告只基于 lint/build 输出与图谱原文
- **预算**:**关系边推理**最多 3 跳(结构下钻 Textbook→Chapter→Section 与脚本闭包如 `kg:ask prereq` 不计入),单轮最多读 5 个数据文件(`kg:ask` 切片调用不计入);批量任务口径以 `tools/kg/skills/00-META.md` §2 预算铁律为准
- **溯源**:每条问题附来源(节 id / 概念 id / lint 输出行),让用户可回查

## 变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-03 | 2026.1 | 新增「语义复核维度」 |
