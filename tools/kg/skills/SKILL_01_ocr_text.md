# SKILL_01 - OCR 文本化

目标：把教材页面图忠实转写为 markdown。

## 正文真源约定（重要）

| 文件 | 角色 |
|------|------|
| `chapters/C<n>/index.md` | **章级 canonical**。人工校对 / LLM 整理只改这份。 |
| `chapters/C<n>/sections/S<m>.md` | **节级派生视图**，供图谱 `sourceRef` 与按节抽取使用。 |

流程：

1. OCR + 整理 → 写入 / 更新 `index.md`
2. 运行派生脚本，回填 sections（保留原有 `sectionId` / `pageRange`）：

```bash
python3 tools/kg/src/sync_sections_from_index.py content/<年级>/<册> --batch
# 单章：
python3 tools/kg/src/sync_sections_from_index.py content/.../chapters/C2
```

3. 之后抽概念 / items / 关系时，仍读 `sections/S*.md`（此时内容来自 index）。

**禁止**：在已有高质量 `index.md` 的情况下，另起炉灶只改 sections 短摘要而不回写 index。

## OCR 步骤（写入 index）

1. 按章（或按 section 的 pageRange）逐页 OCR。
2. 聚合为章级 markdown，清理 OCR 噪声，补正标题层级；写入 `chapters/C<n>/index.md`。
3. 公式用 LaTeX（`$...$`/`$$...$$`），表格用 markdown 表格。
4. 不概括、不 paraphrase，忠实转写。图用 `【图：<描述>】` 占位。
5. 跑 `sync_sections_from_index.py` 派生 sections。

## OCR 工具选择

| 工具 | 命令 | 中文质量 | 适用场景 |
|------|------|---------|---------|
| **aliyun-ocr** | `pnpm run ocr <img> --mode basic` | 高（需激活服务） | 教材页面（通用文字识别） |
| Tesseract | `tesseract <img> stdout -l chi_sim+eng` | 中（噪声较多） | 备选/离线 |

**aliyun-ocr 现状**：
- `structured` 模式可用但专为试卷设计，教材页面返回空（`part_info` 空）
- `basic` 模式需在阿里云控制台激活"通用文字识别"服务
- `edu` 模式 ImageType 参数待确认

**当前建议**：英语用 Tesseract `-l eng`（质量可接受），中文优先尝试 aliyun-ocr basic，不可用时用 Tesseract（需人工清理噪声）。

`index.md` front-matter 含 `chapterId` / `title`。`sections/S*.md` front-matter 含 `sectionId`、`pageRange`，并由脚本写入 `derivedFrom`。
