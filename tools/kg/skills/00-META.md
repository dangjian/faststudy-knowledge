# 00-META — 图谱工程方法论(所有 SKILL 与工具演进的锚点)

> 三条原则:柳叶刀(规则 vs LLM 分工)、渐进载入(上下文预算)、三色步骤标注。
> 修改任何 SKILL_xx 或 tools/kg 脚本前先对照本文;违背时要么改回,要么在 state/log.md 记录裁决理由。

## 1. 柳叶刀方法:能用规则绝不用 LLM

LLM 只用于开放域语义判断;凡有确定性算法的步骤一律脚本。

| 步骤类型 | 执行方 | 现有落点 |
|---|---|---|
| 格式解析(YAML/frontmatter/TOC) | 脚本 | load.ts、sync_structure_from_textbook.py、pdf_ocr_to_index.py |
| ID 生成与引用校验 | 脚本 | ingest.ts、lint.ts(规则编号至 22,含退役空号) |
| 去重合并、幂等追加 | 脚本 | ingest.ts(按 id / from→to) |
| 计数、闭包、切片 | 脚本 | kg_ask.ts、query.ts、build.ts |
| 结构派生(Textbook/Chapter/Section) | 脚本 | load.ts deriveStructure |
| 概念/关系抽取、语义分类 | LLM | SKILL_02/04、llm_*.py |
| part_of 整体-部分识别、跨年级关联 | LLM | SKILL_04、kg-verify-prereq |
| 矛盾判定、OCR 语义修复 | 当前 agent | 按 kg-repair S2 上下文校准、人工裁决（外部 API 链已移除） |

**质检问句**:这次改动里,是否有本可用规则完成的步骤交给了 LLM?若有,先写脚本。
反例警示:迁移与巡检全走脚本+基线对比,唯裁决(如 chapterId 纠偏)才引入语义判断——这是分层 v2 迁移零事故的原因。

## 2. 渐进载入:上下文是预算,不是无限资源

三级加载,按需下钻,严禁一次读全:

1. **总览级**:只读 `tools/skills/INDEX.md` + `graph/index.md`(问句→路径映射)
2. **核心级**:目标 SKILL_xx 一篇 + `ontology.yaml`(或其摘要)
3. **专项级**:按 ID 前缀定位到具体 concepts/<学科>.yaml、节 md 的 `## 汉字/单词/短语/句子/解题模型` 区块切片

**预算铁律**:
- 单次抽取 = 1 个 SKILL + 1 个源文件(一章/一节)+ ontology 摘要;不并读多章
- 批量任务按目录分批,每批 5~10 文件,批间落盘再继续
- 大关系文件(related/covered_by 等,数百 KB~1MB)严禁全量读入,走 `kg:ask` 切片
- 错误模式:一次加载全部 SKILL 文档、"顺便"读整本教材——都是预算事故

## 3. 三色步骤标注:`[SCRIPT]` / `[AI]` / `[HUMAN]`

SKILL 的流程步骤应标注执行主体(存量 SKILL 修订时逐步补齐,新写必须带):

- `[SCRIPT]`:确定性脚本,零 LLM,可重复跑
- `[AI]`:LLM 语义判断,输出须可被下游校验(lint/对比/测试)
- `[HUMAN]`:必须停下等用户拍板——**固定四步:展示计划/摘要 → AI 评估建议 → 用户确认或否决 → 执行**

**`[HUMAN]` 的两个强制场景**(不得降级为 `[AI]`):
1. 任何数据导入/批量修改/删除(项目铁律:先确认再动数据)
2. 纯知识铁律边界:凡疑似把用户态信息写进 knowledge/ 的操作

## 4. 本体演化反问

新增实体类型或关系类型前,先问:**"能否用现有类型 + 新属性表达?"** 能则不加类型。
新增后必须:实体类型在 ontology.yaml 补 layer/storage(及 properties 白名单);关系类型补 relation_types 与 relation_endpoints → lint 规则消费 → 全链引用检查 → log.md 记录理由。

## 5. 反思循环收敛判据(逐本教材的停机条件)

对一本教材做"抽取→巡检→修正"循环时,何时停不靠感觉:

- **收敛**:最近一轮修正数为 0,或最近 3 轮修正数均 < 该教材实体总数的 5%
- **未收敛**:修正数持平或上升 → 检查是否同一类错误反复出现(≥3 次同类 → 提炼进错误模式库,而不是继续逐条修)
- **上限**:单本教材最多 3 轮;3 轮未收敛说明抽取逻辑有系统性问题,停下建 gap 调查根因
- **记录**:每轮结束在 state/log.md 的 verify 段记 `converged: true|false` 与 `convergenceReason`(人类可读一句话,如 "第 3 轮修正 2 条 < 5%")

## 6. 错误模式库

`tools/kg/state/error-patterns/` 三分文件(占位式契约,允许长期为空):

- **entity-errors.yaml**:实体本身的系统性抽取缺陷(字段错/漏抽/误抽/粒度错)
- **relation-errors.yaml**:关系边的系统性抽取缺陷(方向反/端点错/漏建/滥建)
- **source-errors.yaml**:教材原文/OCR 文本本身的问题——不由抽取 prompt 修,只能标注例外

收录门槛:同类反思发现 **≥3 次**才提炼为一条模式(呼应 §5);每次巡检/修正循环后更新;模式须写成针对抽取逻辑缺陷的通用描述,不针对特定实体。

**模式回写机制**:提炼出的模式作为"避免清单"拼进对应抽取 SKILL 的 prompt 段——实体类回写 SKILL_02(概念抽取)、关系类回写 SKILL_04(关系抽取);source 类**不回写 prompt**,登记进对应教材的 gap。

## 7. 置信度约定(confidence)

抽取类实体(Concept/Word/Phrase/Sentence/Character)可带可选 `confidence`(0~1),表示对抽取结果正确性的置信度。

**基准分**(按抽取方式):

| 抽取方式 | 基准 |
|---|---|
| 脚本确定性抽取 | 0.95 |
| AI 单源抽取 | 0.80 |
| AI 抽取 + 人工审核 | 0.90 |

**增量调整**(在基准上叠加):

- 反思修正通过:+0.05
- 多源交叉验证一致:+0.10
- 命中错误模式库(§6)某条模式:-0.10
- sourceRef 无法定位:-0.15

**红线**:confidence < 0.70 的实体必须经人工审核后才可保留(lint rule 13 报 warning 提示)。

**存量策略**:存量实体无 confidence 视为未评分,不补历史;自新抽取批次起赋值。

---
