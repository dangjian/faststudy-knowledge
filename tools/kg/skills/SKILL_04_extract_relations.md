# SKILL_04 - 抽取关系（Pass1 候选 + 跨年级关联）

产出关系边，按类型追加到 `graph/relations/<type>.yaml`：

```yaml
- from: <id>
  to: <id>
```

## 五种关系（全部应产出，不要默认跳过）

| 关系 | 方向 | 说明 | 适用范围 |
|------|------|------|---------|
| `covered_by` | Concept → Section | 该节覆盖某概念 | **必选**，所有学科、所有 section 都要有概念挂接 |
| `prerequisite` | Concept → Concept | 学此前需先学某概念 | **必选候选**，含跨年级，需 SKILL_05 Pass2 复核 |
| `demonstrates` | Item → Concept | 该学习项演示某概念 | **应产出**：英语核心（word→grammar）；语文/数学按需（如例题演示定理） |
| `related` | Concept → Concept | 相关（非方向） | **应产出**：同主题、易混淆、跨学科关联 |
| `part_of` | Concept → Concept | 隶属某主题/上位概念 | **应产出**：概念归类（如"一次函数" part_of "函数"） |

> ⚠️ 旧版把 related/part_of/demonstrates 标为"可选跳过"导致图谱关系残缺。**修订后这三类必须按学科尽量产出，不得整类为空。**

> ⚠️ **prerequisite 是最容易被滥用的一类，产出前先按 `graph/ontology.yaml` 的 `relation_semantics` 走判定顺序**：
> ①能力依赖→prerequisite ②整体—部分→part_of ③并列相关→related ④都不成立→不产出。
> 存量 8690 条实测仅 13.3% 站得住、约 78% 实为 part_of/related/应删（先修方向判据修订（2026-08）），主因就是把上下位与"教材里先讲"当成了依赖。
> 判据只有一条：**把 to 从课程里拿掉，from 的讲解是否无法进行**。"名字包含"（如 三角形/等边三角形）不是依赖，是 part_of。

## 学科差异

- **英语**：demonstrates 是核心（"fox" → "animal vocabulary"）；related 用于语法点互链。
- **语文**：covered_by + part_of 核心（"对比手法" part_of "写作手法"）；demonstrates 用于字词→文学常识。
- **数学/物理**：covered_by + prerequisite + part_of 核心（"整式乘法" part_of "多项式运算"；"二次函数" prerequisite "一次函数"）。
- **历史/地理/生物/化学/道德与法治**：covered_by + related + part_of（主题归类、因果/演进关联）。

## 跨年级关联（关键，必须执行）

单本教材内抽完关系后，必须做**全局跨年级 Pass**：

1. 同一学科内，按年级顺序 七 → 八 → 九：低年级已学概念对高年级同/近主题概念建立 `prerequisite` / `related` / `part_of`。
   - 例：七下"用字母表示数" → 八上"整式" prerequisite；八下"一次函数" → 九上"二次函数" prerequisite。
2. 跨学科关联（如 数学"函数图像" ↔ 物理"图像法"）建立 `related`。
3. 跨年级关联以"学科 + 年级先后"为锚，避免无依据乱连；不确定时优先 `related`（低风险）而非 `prerequisite`（高风险）。

## 约束

- 端点 id 必须已存在实体（先确保 SKILL_02 概念全、SKILL_00 结构全）。
- `prerequisite` 仅作候选，最终以 SKILL_05 为准；跨年级 prerequisite 更要谨慎。
- 完整性门禁：完成后 `lint` 的 orphan warning 应趋近 0；related/part_of/demonstrates 任一类不得为 0。
