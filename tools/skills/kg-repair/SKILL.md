---
name: kg-repair
version: "2026.6"
description: content 节修复统一方法论。当用户说「修这篇 content」「修复某节」「内容不对/格式乱」「越章/错挂/页脚/讹误」「校准这本书」，或五层验收不达标时触发。五层五步循环；S2 内容校准由当前 agent 在上下文中直接执行（严格不走外部 API），其余由既有工具组合执行。
---

# kg-repair — content 修复统一方法论

## 何时用
- 人工抽查 / redflag_scan / lint 报出某节缺陷（越章、错挂、页脚、讹误、表格塌缩、内容缺失）。
- 重切/摄入/对齐之后的节级收口。
- 整册校准（按节循环，队列清零即完成）。

**分工边界**：缺什么（缺书/缺节/缺文）→ `kg-delta`；图概念增删 → `kg-edit`；本 skill 管「把错的内容修对」。

## 五层验收标准（任何一层不过，不得宣布修复完成）

| 层 | 标准 | 唯一工具入口 |
|---|---|---|
| L1 结构 | 节 frontmatter 与书级 canonical 双写一致；pageRange ⊆ 章域且与内容跨度一致；章界=catalog-toc | `redflag_scan.py`（L1 特征）+ yaml 双读比对 |
| L2 忠实 | 内容完整性判据 = **bag_coverage ≥0.93**（文言/注释/旁批密集节的 shingle 天然偏低，仅作版式信号）。bag<0.93 才是内容缺口 → 第二层逐条裁决 | `verify_prose.py`（输出 shingle+bag_coverage 双指标） |
| L3 版式 | 无页眉脚/水印/残渣/两栏粘连/表格塌缩；标题、栏目、表格规范 | `polish_format.py`（规则 0 含水印变体）→ `reflow_prose.py`/`sanitize_prose.py` → `redflag_scan.py` 复扫 |
| L4 引用 | sourceRef 100% 可命中；covered_by 按**节级覆盖率**判定（单节 ≥5 且 ≥50% 概念锚不上才算缺陷） | `pnpm kg:fix:covered` → `kg:fix:orphans` → lint rule23 `covered-by-anchor`（逐条未锚定多为概括句标题，不追） |
| L5 门禁 | lint 0 error、test 过、build 成功、PG migration 幂等 ×2 | `pnpm kg:lint/kg:test/kg:build` |
| L5.5 余量（重排/补录/手术专属） | 节页域 OCR 行对 md 的 2-gram 覆盖核对——「OCR 有而正文无」逐条定谳（真实丢字/边界页共享/OCR形近噪声/图内文字），存在未解释余量不得放行。**目视核对不作为放行依据**（2026-10-16 拼接丢字事故） | `residual_scan.py <BookId>` |

## 六步组合管线（单册/单章执行序，全部既有工具）

**强制入口：`pnpm kg:repair -- <BookId> [stage]`（driver `tools/kg/scripts/repair.py`）——它编排下列全部命令并内嵌写盘/断言纪律。agent 不得绕过驱动器即兴手术；唯一例外是 S0 结构裁定（需人工/页图 judgment），但其产物必须通过 `--check` 与 `--gate`。**

**S3-first 工作流（决定 S2 范围，避免空转）**：每册先跑 L2 忠实验证——
```
pnpm kg:repair -- <BookId> --stage S3   # verify_prose（PDF 重 OCR diff，输出 shingle+bag_coverage）
```
- 全部节 bag_coverage ≥0.93 → **本册零 S2 校准需求**（内容已在摄入期校准），只做红旗/版式实修
- 存在 bag<0.93 的节 → 仅对这些节做 S2 内容校准（agent 上下文内，硬规则见下）
- 全仓预筛：`pnpm kg:repair -- --screen-all`（后台慢任务）产出 bag 地图 → MASTER-QUEUE 按"内容完好册/缺文册"分流

```bash
# S0 结构对齐（L1）——必须最先做，否则后面全在给错位内容做校准
#   取证：source_data/<BookId>/metadata.json toc + 页眉脚 OCR（印刷页=图号−imageOffset）
#   手术：book_apply 或按页域重切 → frontmatter 与书级 index 双写
# S1 确定性清洗（L3）
python3 tools/kg/src/polish_format.py <sections目录>  # 规则0水印变体+页眉脚行/断行合并/栏目加粗
python3 tools/kg/src/reflow_prose.py --dry-run <文件>  # 语文长段落版式（确认后去 --dry-run）
python3 tools/kg/src/sanitize_prose.py --dry-run <文件> # 数学册标题粘连/LaTeX 残渣
# S2 内容校准（L2/L3）——当前 agent 在上下文中直接执行（严格不走外部 API）
#   对象：S1 后仍存疑的块 + redflag/verify_prose 差异定位的块
#   规则：块级处理；忠实转写不改题意（不概括/不扩写/不删题/不改数字选项结论/不编造）；
#         错字可改（含出版社水印变体）；公式损坏→LaTeX 需上下文唯一；
#         截断句仅上下文唯一可补全时补全；无法可靠恢复→保持原样并记 uncertain 旁路
#   产出：修正写回节文件 + uncertain 清单落 state/verify/repair/<Book>/s2-uncertain.md
#   （外部 API 校准路径已移除——llm_repair_ocr/llm_polish_prose/llm_format_refine 已删除）
# S3 忠实闭环（L2）
python3 tools/kg/src/verify_prose.py   # PDF 重 OCR diff → 差异清单逐条裁决 → 重跑至收敛
# S4 图引用（L4）
pnpm kg:fix:covered && pnpm kg:fix:orphans
# S5 门禁（L5）
pnpm kg:lint && pnpm kg:test && pnpm kg:build   # 结构变更另出 PG migration（幂等 ×2）
```

## 铁律（2026-10-15 事故沉淀，违反必回滚）

1. **LOW/差异必须页图取证归因后才允许记账**——禁止把 LOW 直接归因为"表格塌缩"了事（C2/S2 教训：真因是内容错位）。
2. **写盘纪律脚本化**：所有文件内容在内存算完 → 统一写盘 → 写后重读断言。严禁先 open('w') 再算内容（已发生 4 次截断事故）。
3. **key 推导必须 fullmatch 断言**：从路径/文件名推导 ID 一律 `re.fullmatch` 验证；批量替换先干跑打印 diff（已发生 5 个同根因 bug：ecti/Secti/chapters/1/跨书子串误替换 84 行）。
4. **ground truth 三级**：页眉脚 OCR 实证 > 目录（metadata.json toc / 目录页）> 文件现有声明；OCR 无法裁定→记 not_fixed，禁止猜测。
5. **扫描器盲区=skill 盲区**：新发现的缺陷类必须沉淀为 redflag_scan 特征（残渣模式已自 scan_format_residue 并入）。
6. **S2 校准不走外部 API，且备选已移除**：内容校准只由当前 agent 在上下文中执行；API 校准脚本（llm_repair_ocr/llm_polish_prose/llm_format_refine）已于 2026-10-15 删除，杜绝再犯。

## 已退役 / deprecated

- `verify_fidelity.py` → 退役（verify_prose.py 为 L2 唯一验收，2026-10-15）
- `scan_format_residue.py` → 并入 redflag_scan.py 残渣模式（同日）
- `strip_page_footer.py` → 水印变体逻辑并入 polish_format.py 规则 0（同日）
- `query.ts` 保留（eval.ts/golden.test 活依赖——曾因 cwd 漂移假阴性误删，已恢复）
- `batch_ocr.py`、`pdf_extractor.py`、`sync_sections_from_index.py` → 退役（零引用，2026-10-15 查重）
- `sync_sections_from_index.py` → **deprecated**（"章级 canonical"假设已被当前架构推翻：书级 index.md 持 canonical 元数据、节文件持内容、章级 index 为 raw 层；双写一致性改由 S0 手术 + lint 保证）

## 工具速查

| 用途 | 命令 |
|---|---|
| **统一入口（必经）** | `pnpm kg:repair -- <BookId> --check/--stage S1|S2|S4|S5/--gate` |
| 红旗定位（L1/L3 特征） | `python3 tools/kg/scripts/redflag_scan.py [--book X --json OUT]` |
| L2 忠实 diff | `python3 tools/kg/src/verify_prose.py`（KG_SOURCE_DIR 在 knowledge/.env） |
| L3 清洗 | polish_format（含水印）/ reflow_prose / sanitize_prose |
| S2 内容校准 | **当前 agent 上下文内执行**（块级硬规则见 S2 段；uncertain 落账）——API 备选已删除 |
| L4 引用 | `pnpm kg:fix:covered` / `kg:fix:orphans` |
| L5 门禁 | `pnpm kg:lint` / `kg:test` / `kg:build` |
| 页图 | `source_data/<BookId>/pages/`（印刷页=图号−imageOffset） |
| 目录 | `source_data/<BookId>/metadata.json` toc |

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-15 | 2026.6 | L2 判据修正：bag_coverage≥0.93 为内容完整判据（文言节 shingle 低≠缺文） |
| 2026-10-15 | 2026.5 | 移除 API 备选：删除 llm_repair_ocr/llm_polish_prose/llm_format_refine；reoutline_ocr LLM 链改移交 agent |
| 2026-10-15 | 2026.4 | 修正主次颠倒：S2 内容校准主路径=当前 agent 上下文内直接执行（严格不走外部 API，用户重申）；llm_* 脚本降回无 agent 环境备选 |
| 2026-10-15 | 2026.3 | 强制执行层：唯一入口 `pnpm kg:repair`（driver 编排全部既有工具，内嵌断言/写盘纪律）；--gate 红旗基线非回归（提交前/CI）；S0 除外但产物必须过 --check |
| 2026-10-15 | 2026.2 | 统一方法论：六步组合管线（既有工具编排）；退役 verify_fidelity/scan_format_residue；五层工具表落到唯一入口；新增铁律 1-5（LOW 取证、写盘脚本化、fullmatch 断言等） |
| 2026-10-15 | 2026.1 | 初版（五层五步框架） |
