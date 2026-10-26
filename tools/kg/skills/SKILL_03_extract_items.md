> ⚠️ **未适配 v4**：词书条目现写入节 md / 章 index.md 文末 `## 汉字/单词/短语/句子` 区块（非 `items/` 目录），插图不再派生实体。启用前需先更新写入路径与目标格式。

# SKILL_03 - 抽取 items

从 section 抽取学习项，写入 `content/<年级>/<学期>/<科目>/<textbookId>/items/C<n>-S<m>.md`（分层 v3：五类学习项走 md 表格、习题正文走 `### E1 {#完整id}` 锚点；习题的身份与我方标注另落 `graph/entities/exercises/<学科>.yaml`。**content 下不得出现 yaml**）。

## ⚠️ 重要：使用 ingest 工具写入，禁止手工拼接 YAML

手工拼接 YAML 容易因中文引号、特殊字符导致解析失败。**必须使用 `tools/kg/src/ingest.ts` 的 `writeExtract()` 函数写入**（目标目录由其 `itemsDir` 选项指定，即该教材的 `content/.../<textbookId>/items/`），该函数内部使用 `yaml.stringify()` 安全序列化。

## 输出格式

```yaml
sectionId: <sectionId>
words:       # 英语单词
  - {id: word:<textbookId>:U<n>:<word>, type: Word, word: <w>, ipa: <ipa>, pos: <pos>, meaning: <中文>, sourceRef: <content path>}
phrases:     # 英语短语/句型
  - {id: phrase:<textbookId>:U<n>:<slug>, type: Phrase, en: <英文>, cn: <中文>, sourceRef: ...}
sentences:   # 英语重点句
  - {id: sentence:<textbookId>:U<n>:s<m>-<k>, type: Sentence, english: [<词>...], cn: <中文>, sourceRef: ...}
characters:  # 语文生字词
  - {id: character:<textbookId>:<unit>:<char>, type: Character, char: <字词>, pinyin: <拼音>, definition: <释义>, example: <课文例句>, sourceRef: ...}
figures:     # 图表（几何图等）
  - {id: fig:<textbookId>:<sectionId>:<slug>, type: Figure, ...}
exercises:   # 习题（本节课后练习等）
  - {id: exercise:<textbookId>-<n>-S<m>-E<k>, type: Exercise, exerciseType: <选择|填空|解答...>, body: <题干>, difficulty: <易|中|难>, sourceRef: ...}
```

## 按学科调整

| 学科 | 主要 Item 类型 | 说明 |
|------|--------------|------|
| 英语 | words, phrases, sentences | 单词、短语、句型 |
| 语文 | characters | 生字词（含成语），words/phrases/sentences 留空 |
| 数学 | figures | 几何图用 SKILL_06，公式留正文 |

## 注意事项

- item 不内联 `concepts` 字段——item→concept 关系由 SKILL_04 产出 demonstrates
- id 全局唯一可引用，命名规则：`<type>:<textbookId>:<unit>:<identifier>`
- 如果写入时遇到 YAML 解析错误，检查字段值是否含未转义引号——改用 `yaml.stringify()` 可自动处理
- **YAML boolean 陷阱**：英文词/句里的 `off / on / yes / no / true / false` 会被 YAML 1.1 解析器读成 boolean，导致 lint 报 `expected string, received boolean`。**`writeExtract()` 已自动 requote**（`requoteBoolWords()` 对这些保留词补单引号），走工具写入无需手工处理；若确需手写 YAML，这些词仍必须加引号（单双引号均可，如 `'off'` 或 `"off"`）。