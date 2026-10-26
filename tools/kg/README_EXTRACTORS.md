# 教材提取工具套件

从课本 PDF/扫描图 → 结构化图谱 (prose + Concept + Item)

---

## 📦 工具概览

| 工具 | 用途 |
|------|------|
| `pdf_extractor.py` | PDF 文本提取 / 图片 OCR |
| `concept_extractor.py` | 单篇课文概念提取框架 |
| `llm_extract_graph.py` | LLM 抽取 Concept/Item/covered_by → graph 实体 |

## 🚀 使用流程

```
PDF 课本 ────────────┐
图片目录 ────────────┤
                     ├→ pdf_extractor.py ─→ content/ prose markdown ──┐
现有 markdown 目录 ─┘                                              └→ llm_extract_graph.py ─→ graph/ 实体 (Concept/Item/covered_by)
```

## 🔧 工具使用

### 1. PDF 提取

**方式一：从 PDF 提取

```bash
cd tools/kg
python src/pdf_extractor.py ~/课本/七年级下册数学.pdf \
  --subject 数学 \
  --grade 七年级 \
  --term 下册 \
  --start-page 10 \
  --end-page 50
```

**方式二：从图片目录 OCR 提取**（源图目录由环境变量 `KG_SOURCE_DIR` 指定，见仓库根 `.env.example`）

```bash
python src/pdf_extractor.py "$KG_SOURCE_DIR/PEP-7-2-Chinese/pages/" \
  --subject 语文 \
  --grade 七年级 \
  --term 下册
```

### 2. 知识库抽取（LLM）

```bash
# 对单本教材抽取 Concept/Item/covered_by（自动写入 graph/entities）
python src/llm_extract_graph.py content/八年级/上册/数学/BSDU-8-1-Math --batch

# 批量对八下/九年级：抽取 + lint + build
python src/batch_graph_8_9.py
```

## 📋 输出结构

```
content/
└── 七年级/
    └── 下册/
        └── 语文/
            └── PEP-7-2-Chinese/
                └── chapters/
                    └── C1/
                        └── sections/
                            ├── S1.md
                            └── S2.md
graph/entities/concepts/
    └── 语文/
        ├── 叙事散文.yaml
        ├── 借景抒情.yaml
        └── ...
```

## 🛠 依赖安装

```bash
# PDF 提取
pip install pypdf

# OCR （需额外安装 tesseract 语言包
pip install pytesseract pillow

# macOS: brew install tesseract tesseract-lang
# Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-chi-sim
```

## ✅ 验证

```bash
# lint 检查
pnpm kg:lint

# 构建图谱
pnpm kg:build
```

## 📊 知识库统计

```
七年级下册: 7学科 ✅
  - 数学: 49 sections
  - 语文: 待补全
  - 英语: 待补全

八年级上册: 8学科 ✅
  - 语文: 48 sections
  - 英语: 24 sections ✅
  - ...
```

---

下一步工作流已完成 ✅
