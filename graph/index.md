# 图谱检索入口(AI Agent 必读)

> 本文件是 agent 查询知识库的入口:先在此定位,再下钻具体文件或调 `kg:ask`。
> 计数区块由 `kg:build` 自动刷新,**请勿手改区块内内容**;区块外为手写,维护时同步更新。
> 与 `tools/skills/INDEX.md` 的分工:那里讲**怎么建图**,这里讲**怎么查图**。两者口径必须一致。

<!-- stats:begin -->
> 最后更新: 2026-10-28 | 分层 v4 | 18542 nodes, 33568 edges

| 实体类型 | 数量 |
|---|---|
| Concept | 8282 |
| Textbook | 99 |
| Chapter | 722 |
| Section | 2976 |
| Word | 2803 |
| Phrase | 1320 |
| Sentence | 1099 |
| Character | 1241 |

| 关系类型 | 数量 |
|---|---|
| covered_by | 9779 |
| demonstrates | 2591 |
| part_of | 4993 |
| prerequisite | 1798 |
| related | 14407 |
<!-- stats:end -->

> **prerequisite 可信度分两档，靠边字段 `reviewed` 区分，消费方必须据此收口。**
>
> | 档位 | 条数 | 含义 |
> |---|---:|---|
> | `audited` | 1,680 | 逐条判定过方向与强度 |
> | `sampled` | 118 | 仅抽样验收 |
>
> - 消费方（如 learner 的先修闭包）只走 `audited`；`sampled` 不享受同等结论。
> - 含容关系统一归 `part_of`，因此 prerequisite 天然比 part_of 稀疏。需要补上位知识时，
>   除 prerequisite 外还要上行 `part_of`。
> - 新加的先修边必须标 `reviewed`，否则被 lint rule 24 告警并被闭包排除。
> - 其余 4 类关系未做同等档位复核，按原样使用。

## 分层布局(哪类东西在哪)

```
content/<年级>/<学期>/<科目>/<textbookId>/   L1「学什么」(真源,章节文档承载一切内容)
  index.md                                   front-matter 的 chapters 键 = 结构唯一源
                                             (Textbook/Chapter/Section 由此派生,不落盘)
  chapters/C<n>/index.md                     章正文(真源,可带章级词书区块,如汉字表)
  chapters/C<n>/sections/S<m>.md             节正文 + 文末区块(顺序固定):
                                               ## 汉字/单词/短语/句子  词书四类 md 表格,照常派生实体
                                               ## 插图                 纯文本图注,不派生实体
                                               ## 解题模型            解题方法/动画/视频外链正文
                                               ## 笔记 / ## 总结       自由文本,不派生实体
graph/                                       L2「知识如何连接」(真源,零正文载荷)
  ontology.yaml                              8 实体类型(含 storage 声明)、5 关系类型
                                             covered_by 端点两级: Concept → Section | Chapter
  entities/concepts/<学科>.yaml              Concept 身份节点,10 个学科聚合文件
  relations/{covered_by,demonstrates,part_of,prerequisite,related}.yaml
  curriculum-standards.yaml                  课标条目注册表;chapter-standards.yaml 为章→课标对齐
  suspended-prerequisites.json               暂缓落盘的先修候选(判定后归 part_of/related,留档待复核)
dist/                                        派生产物 — 本地 agent 禁止读取(给外部服务/第三方消费；用途见 README「dist/ 什么时候用」)
```

## 问句 → 路径映射(先查这张表,别全库 grep)

| 你想回答的问题 | 走哪条路 |
|---|---|
| 某节讲了哪些概念 | `pnpm kg:ask concepts <sectionId>` |
| 某概念的先修链(传递闭包) | `pnpm kg:ask prereq <conceptId>` |
| 某概念被哪些节覆盖 | `pnpm kg:ask covered <conceptId>` |
| 例证某概念的词/句/汉字 | `pnpm kg:ask demo <conceptId>` |
| 某概念的相关概念 | `pnpm kg:ask related <conceptId>`(严禁全量读 related.yaml,近 1MB;已含双向) |
| 某概念隶属于哪个上位概念 | `pnpm kg:ask partof <conceptId>`(出边:部分→整体;反查组成部分暂无命令) |
| 章节树 | `pnpm kg:ask tree <textbookId>` |
| 脑图聚合 JSON | `pnpm kg:ask mindmap <sectionId>` |
| 概念身份/别名/易错点 | 直读 `graph/entities/concepts/<学科>.yaml`(按 id/title grep) |
| 解题方法/动画/视频正文 | 直读节 md 的 `## 解题模型` 区块(v4 起正文随节走,不再是独立实体) |
| 某节的词/句/汉字原文 | 直读 `content/.../chapters/C<n>/sections/S<m>.md` 文末词书区块 |
| 章节正文 | 直读 `content/.../chapters/C<n>/index.md` |

> 习题(Exercise)与解题模型(ExamModel)不作为实体存在:
> `kg:ask` 没有 `exercises` / `models` / `review-unit` / `review-exam` 子命令,`assesses` / `exemplifies` / `applies_to` 边不存在。
> 产品侧已裁撤练习功能,图谱不再承载题目。

## ID 前缀速查

```
textbook :BSDU-7-1-Math                  教材(<出版社>-<年级>-<学期>-<科目>;学期段 0 表示全一册,如 PEP-9-0-English)
chapter  :BSDU-7-1-Math-C1               章
section  :BSDU-7-1-Math-C1-S1            节
concept  :concept:<学科>:<名称>           如 concept:数学:一次函数
item     :word|phrase|sentence|character 四类词书学习项
         word|phrase|sentence:<textbookId>:U<n>:<slug>   如 word:PEP-7-1-English:U1:hello
         character:<textbookId>:<sectionId>:<名称>        如 character:PEP-7-1-Chinese:PEP-7-1-Chinese-C1-S1:朗
```

## 局限声明(agent 须知)

- **本地 agent 禁读 `dist/`**——那是外部消费的编译产物(gitignore)
- 关系文件按类型扁平:大文件(`related.yaml` 近 1MB、`covered_by.yaml` 上万条)严禁全量读入,走 `kg:ask` 切片;`part_of.yaml` 同理
- 先修边的可信度分两档,见文首声明——需要"绝对可信"时按 `reviewed === 'audited'` 过滤,不要默认全库可信
- `covered_by` **两级**:`to=Section` 表示该节正文/标题能举证(现有 8,486 条);`to=Chapter` 表示概念属于该章知识清单但**没有任何一节能举证**(现有 1,293 条,教材正文用叙述表达、概念名多为概括句)。章级是如实记录,不是豁免——查"某节讲什么"只认节级,查"某概念归哪章"两级都认
- 不要再按"概念标题能否在正文逐字出现"去逐条清 `covered_by`:零散未锚定 **67 条(小学 44 / 初中 23)**,多为小学的写作方法类元知识(详略得当/时间顺序/心理描写)与初中的概括句标题,正文用叙述表达,**不是缺陷**。真信号只剩节级覆盖率(单节 ≥5 且 ≥50%),已清零
- 小学**不走**章级归属:小学 1,937 节、每节中位数 1 个概念,没有「整章压一节」问题;且 `section-concept-min`(error)要求小学有正文的节至少贡献 1 个概念,上提会把 44 个节变成零概念、只能靠堆豁免维持,门禁随之失效
- `part_of`（层级关系）抽样金标 **500 条**：单边正确率 **81.9%**（跨章仅 66.7%），且规则筛查无效
  （命中里 58–83% 是误报）——**它是探索性关联，不是权威上位推荐**；消费侧 `broader` 已封顶深度 1，
  不做传递闭包；更关键的是**只有「子概念标题包含父概念标题」的 part_of 才作为 broader 返回**（该子集精度 96.6%，全量仅 81.9%），其余边保留供 `related` 一跳邻居使用（见 `tools/kg/eval/rubric-cases.md` 第七、八、十三节）
- 图谱没有的知识点就是没有——**不得编造**,如实回答"图谱未覆盖"
- 已知缺口与数据问题清单见 `仓外治理记录（不入公开仓）index.md`(过程产物,仅本地;公开仓不含)
