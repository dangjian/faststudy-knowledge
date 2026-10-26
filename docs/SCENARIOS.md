# 与开源教育产品结合的使用场景

本仓库的定位是 **AI agent 处理中小学知识点时的数据底座**，不是终端产品。
它提供「教材原文 + 概念 + 关系 + 页码」四类事实，课件、动画、视频由别的开源项目负责渲染。

按**四条可核查的标准**排序，不按技术栈：

1. **项目实据**：有仓库、有 README 里写明的接入点（数据格式、检索引擎、CLI 命令），不是"据说能接"
2. **我们是否刚需**：对方缺、且我们原生具备（教材原文与页码是典型；渲染能力则不是）
3. **落地成本**：能否用现成命令接上，还是要写新适配层
4. **零集成优先**：不需要对方做任何适配的场景排前面——它决定这条路径今天就能跑通

前三位都是在 GitHub 上 40k+ star、README 明确描述数据如何进入的项目。

下面每个场景都给出：**我们提供什么 → 对方提供什么 → 产出什么 → 最小验证路径 → 风险**。
每个场景都标清**分工边界**：哪些由本仓库负责，哪些由上游/下游负责。

---

## 1. 直接产出单页 HTML（不需要任何第三方项目）

最短路径：agent 读本仓数据，**输出一个自包含 HTML 文件**，双击即用。没有安装、没有服务、没有对接。

**产出的三种形态，按复杂度递增**

| 形态 | 用什么 | 我们的输入 | 验证情况 |
|---|---|---|---|
| 参数化图表 | 原生 canvas 2D | 概念 + 页码 + 章节结构 | **已实现**：`demo/net.js` 是零依赖 Canvas 力导向，160 节点 300 次迭代 20 ms |
| 公式与解析页 | KaTeX 内联 | `explanation` + `misconceptions` | **已实现**：demo 把 KaTeX 放在 `demo/vendor/`，按需加载并局部降级 |
| 三维演示 | three.js | 概念参数（需 agent 自行建模） | 未实现，且需注意下面两条约束 |

**两条来自实测的约束**

1. **ES Module 不能用 `file://` 打开**。浏览器会因 CORS 拒绝加载模块，必须起一个本地 HTTP 服务
   （`python3 -m http.server`）。本仓 demo 的 README 里已记录同一条限制。
2. **CDN 依赖会破坏"自包含"**。要真正离线可用，需把库文件内联进 HTML，单文件会涨到数百 KB；
   只在线用则保留 CDN 引用即可。这是取舍，不是技术障碍。

**为什么这个场景排第一**

| 标准 | 说明 |
|---|---|
| 项目实据 | 不依赖外部项目，形态由我们自己验证过（Canvas 力导向 + KaTeX 都在 demo 里跑着） |
| 我们是否刚需 | 需要教材原文、页码、易错点——正是本仓的字段 |
| 落地成本 | **零**：不需要对方支持任何格式 |

**最小验证路径**

```bash
pnpm kg:ask covered 'concept:物理:凸透镜成像规律'   # 概念 + 所在节 + 页码
pnpm kg:ask concepts 'PEP-8-1-Physics-C4-S2'     # 该节概念清单与易错点
```

把这两段交给 agent，要求输出单个 HTML：滑块调参 → canvas 画光路 → 侧栏显示「教材 p.x–y」
与该概念的 `misconceptions`。**检验标准只有一个**：页面上的页码能在教材里对上。

**已经做出来的示例**：[docs/examples/convex-lens.html](examples/convex-lens.html)（单文件、零依赖）

用它自己的数据生成：`concept:物理:凸透镜成像规律`、教材 `p.61–90`、两条 `misconceptions`。
四步导航覆盖「认识焦距 → 改变物距 → 实像与虚像 → 光屏承接」，
拖滑块实时算像距与放大率（`1/v − 1/u = 1/f`），页脚固定显示教材页码与易错点。

用浏览器打开即可，无需安装；双击 `file://` 也能跑（本例未用 ES Module 与 CDN）。

---

## 2. 教材即知识库：DeepTutor

**事实**（HKUDS/DeepTutor，Apache-2.0，43.5k★，v1.6.15）：Knowledge Center 是 RAG 背后的文档集合，
**每个知识库绑定一个检索引擎**，可选 LlamaIndex（默认 hybrid vector + BM25）、**PageIndex（page-level citations）**、
GraphRAG、LightRAG、WeKnora、Kiwix、Obsidian。导入支持**链接文件夹**（按 hash-diff 增量同步）、GitHub 仓库、
文档站 URL，命令形如 `deeptutor kb create my-kb --doc textbook.pdf`；解析可选 MinerU / Docling / markitdown / PyMuPDF4LLM。

**三个可落地的接入点**

| 接入点 | 我们提供 | 为什么成立 |
|---|---|---|
| 知识库用 **linked folder** 指向 `content/` | 2,976 节 markdown，已按 年级/学期/学科/章/节 组织 | 它按 hash-diff 增量同步文件夹，不需要转换格式 |
| 检索引擎选 **PageIndex** | 每节都带 `pageRange`（2,976 / 2,976） | 它主打 page-level citations，而教材页号正是我们的原生字段 |
| 选 **GraphRAG / LightRAG** | `prerequisite` 1,798 · `part_of` 5,062 · `related` 14,338 | 它接受图检索，我们的边可导出为三元组 |

**它缺、我们补的**：教材原文与页码。DeepTutor 的 `book` 与 `immersive reading` 强调 verified citations，
但页码只能来自文档——PDF 要靠分页推断，我们的 markdown 直接带 `p.x-y`。

**可量化的验收**：它自带 `deeptutor kb eval --dataset qa.jsonl`（Recall@k / nDCG@k / MRR）。
用本仓的概念-章节对造 100 条 QA，可在同一条命令下比较「有教材」与「无教材」的检索质量。

---

## 3. 互动课堂生成：OpenMAIC

**事实**（THU-MAIC，MIT，41.5k★，v1.3.0-rc.1）：输入是「描述主题，或附上素材」，素材支持 PDF / Word /
PowerPoint / 表格 / 文本 / 图片 / 音频 / 视频，经解析进入两阶段流水线 **Outline → Scenes**
（每个大纲项生成 slide / quiz / interactive / PBL 场景）。v1.3.0-rc.1 起有**知识库**：按文件夹组织、
composer 里用 `@` 引用、agent 可读取与检索。导出支持 PPTX / Resource Pack / Offline HTML /
Classroom ZIP（`.maic.zip`）/ MP4，数据落 PostgreSQL 16。

**接入点**

| 接入点 | 我们提供 | 注意 |
|---|---|---|
| Outline 阶段 | `pnpm kg:ask tree <textbookId>` 的章节树，本身即结构化大纲 | 比让它从主题自由发挥更有教材依据 |
| Scenes 生成 | 每节概念清单 + `misconceptions` | 概念卡可直接成一张 slide，易错点可变成 quiz 干扰项 |
| 知识库（`@` 引用） | 节 markdown | 它列出的格式未明确写 markdown，按「文本」类别处理 |
| 导出之后 | 页码需写进正文（`教材 p.x–y`） | 它没有页码字段，只能标在文本里 |

**它缺、我们补的**：教材级大纲与出处。OpenMAIC 强在把大纲切成课堂场景，但大纲从哪来取决于输入；
给它教材章节树，生成的课堂才会落在正式教材范围内。

---

## 4. 交互式解题课件：EduLab

**开源项目**：[wy51ai/edulab](https://github.com/wy51ai/edulab)（教育 skill 集合，Claude Code 插件形态；Gitee 有 [liangdabiao/edulab](https://gitee.com/liangdabiao/edulab) 增强版）

**它做什么**：把一道学科题（早期只有立体几何，后扩到解析几何、化学反应）转成**自包含的交互 HTML 课件**——
左侧 MathJax 分步解析，右侧可操作的图形/反应演示。用 SymPy 做符号计算。

**它缺什么**：题目要从外部来；课件内容与「教材哪一页、这个知识点常见什么错」没有连接。

**我们提供**：

| 我们的字段 | 在这里的作用 |
|---|---|
| `concept` + `explanation` | 课件开头的"这个知识点是什么"锚点 |
| `misconceptions`（6,807 个概念有） | 直接变成课件的"常见错误"提示条 |
| `masteryCriteria` | 课件末尾的"怎样算学会了"自检 |
| `covered_by` + `pageRange` | 每页课件回链「教材 p.29–37」，可点开原文 |
| `conceptType` | 决定用哪种呈现：程序型逐步演示、概念型要素高亮 |

**结合后的形态**：EduLab 出交互题解 → 我们补上知识点上下文与教材出处 →
学生看完解析能跳到教材原文，教师能核对"这题对应课标哪个领域"。

**最小验证路径**

```bash
pnpm kg:ask covered 'concept:数学:配方法'   # 拿释义/易错点/页码
# 把 misconceptions 与 pageRange 注入 EduLab 生成的 HTML 模板
```

**分工边界**

- **题库在上游**：题目由出题方或 EduLab 的三种入口（文字/图片/随机）提供，本仓库负责把它挂到教材的确切位置。
**为什么它排在这里**：这是目前最贴近我们定位的开源项目——同样是「skill 形态 + 教育内容」，
但走的是"题 → 课件"路线，我们走"教材 → 数据底座"路线。**两条路可以直接串起来**。

## 5. 可溯源问答：RAGFlow

**开源项目**：[infiniflow/ragflow](https://github.com/infiniflow/ragflow)（Apache-2.0）

**我们提供**：教材原文 + `sourceRef` + 页码，天然带引用锚点。
**对方提供**：分块、检索、引用回显。

**场景**：学生问"光合作用的原料是什么"，回答必须给出「教材 p.29–37」并在正文中回链，
而不是模型记忆。**这是本仓库最直接的差异点**——多数知识图谱只有 1–2 句描述，没有可读原文。

---

## 6. 课件/讲义：Slidev 或 Marp

**开源项目**：[slidevjs/slidev](https://github.com/slidevjs/slidev)（MIT）、[marp-team/marp-cli](https://github.com/marp-team/marp-cli)（MIT）

**我们提供**：节 → 概念清单 → 页码；每个概念的结构化字段。
**对方提供**：Markdown → 幻灯片；KaTeX 公式；`slidev export` 出 PDF/PNG；Marp 可直接出 `.pptx`。

**场景**：从「某一节」一键生成一节课的讲义——每页一个概念，页脚标注「教材 p.29–37」与 `conceptId`，
让讲义与知识库**双向可追溯**（改概念能定位到哪几页幻灯片）。

**最小验证路径**

```bash
pnpm kg:ask concepts 'PEP-7-2-Biology-C3-S2'   # 该节概念清单
# 生成 slides.md（front-matter 写入 kp_id / page）
slidev export slides.md
```

**风险**：语文/历史的概念多为「篇目、事件、制度」，一页一个概念会显得空洞，需要按"问题串"重组。

---

## 7. 动态微课：Manim + manim-slides

**开源项目**：[ManimCommunity/manim](https://github.com/ManimCommunity/manim)（MIT）、[jeertmans/manim-slides](https://github.com/jeertmans/manim-slides)（MIT）

**我们提供**：概念的类型（`conceptType`）、公式与步骤（正文）、易错点（`misconceptions`）、该节页码。
**对方提供**：`Scene` / `Animation` 对象模型、LaTeX 渲染、导出 MP4 与「点击逐步播放」的幻灯片。

**场景**：给「程序型」与「概念型」概念各配一套参数化场景模板——

- 程序型（如配方法）→ 模板按「步骤数组」逐帧展开，一个概念一串动画
- 概念型（如平行四边形）→ 模板按「定义要素」逐项高亮

**最小验证路径**

```bash
pnpm kg:ask covered 'concept:数学:配方法'   # 拿到释义/易错点/所在节页码
# 用该概念构建一个 manim Scene，渲染 10 秒片段
manim -pql scene.py Peifang
```

**风险**：模板化的代价是表达力；`hard` 难度概念往往需要手工设计分镜，不宜全自动。

---

## 8. 视频与交互点：H5P Interactive Video + 时间戳对齐

**开源项目**：[h5p/h5p-core](https://github.com/h5p/h5p-core)（MIT）、[m-bain/whisperX](https://github.com/m-bain/whisperX)（词级时间戳）

**我们提供**：概念及其易错点（用于生成提问）、页码（用于溯源）。
**对方提供**：视频时间轴上的选择题/热点/弹窗；词级时间戳反查。

**场景**：讲解视频产出后，用 whisperX 得到词级时间轴，再按概念标题与易错点做匹配，
自动生成「第 03:12 出现『叶绿体』→ 插入一条关于"光合作用只发生在白天"的判断题目」。

**最小验证路径**

```bash
whisperx lesson.mp4 --language zh --word_timestamps True
pnpm kg:ask covered 'concept:生物:光合作用'   # 取 misconceptions 作为交互点素材
```

**风险**：错配率取决于语音识别质量；建议只自动生成候选，人工确认后再发布。

---

## 9. 关系图：Mermaid / D2

**开源项目**：[mermaid-js/mermaid](https://github.com/mermaid-js/mermaid)（MIT）、[terrastruct/d2](https://github.com/terrastruct/d2)（MPL-2.0）

**我们提供**：先修（含 `hard/soft`）、上位（`part_of`，仅标题含容子集）、相关。
**对方提供**：文本 → 图，布局质量好，可嵌入 Markdown / 幻灯片。

**场景**：把某一节的先修链导出成图，贴在讲义开头当"前置知识检查表"。

**最小验证路径**

```bash
pnpm kg:ask prereq 'concept:数学:无理数'    # → 有理数 / 勾股定理 / 正数和负数 / 直角三角形
```

**必须说清的边界**：全库只有 **15.6%** 的概念有先修边（1,288 / 8,282），中位数是 1 条；
先修的密度因学科而异：语文、道法的知识点多为并列关系（篇目、事件、制度），本就不构成能力依赖；
理科的链更密（数学 1,096 个概念中有 569 条先修边）。做图前先 `pnpm kg:ask prereq` 看一眼规模即可。

---

## 10. 学科专用可视化

**开源项目**：[jsxgraph/jsxgraph](https://github.com/jsxgraph/jsxgraph)（交互式几何）、[molstar/molstar](https://github.com/molstar/molstar)（分子结构）、[excalidraw/excalidraw](https://github.com/excalidraw/excalidraw)（手绘风白板，文件是 JSON 可脚本生成）

**我们提供**：概念的所属节、页码、易错点（决定要画哪个"反例"）。
**对方提供**：几何约束求解、分子 SMILES 渲染、手绘风插图。

**场景**：给几何概念生成可拖动的标准图 + 一个"易错形态"对照（如"高在三角形外部"），
易错点正好是我们 82% 概念都有的字段。

**风险**：这三类库都需要学科专家定"标准图形"，不能纯靠标题生成。

---

## 11. 可交互例题：Marimo / Quarto

**开源项目**：[marimo-team/marimo](https://github.com/marimo-team/marimo)（Apache-2.0，纯 Python 可 diff 的 notebook）、[quarto-dev/quarto-cli](https://github.com/quarto-dev/quarto-cli)

**我们提供**：概念 + 掌握标准（`masteryCriteria`，目前是"能指出并纠正这一错误：…"形态）。
**对方提供**：可执行 cell、参数化重算、一份源出多格式。

**场景**：把 `masteryCriteria` 转成"判断题 + 解释"，学生在 notebook 里改参数看结论是否仍成立。

**分工**：题目由现场生成或上游提供，本仓库提供该概念的掌握标准与教材出处，两者拼成完整的练习闭环。

---

## 12. LMS 承载：Moodle / Open edX / Kolibri

**开源项目**：[moodle](https://github.com/moodle/moodle)（GPL-3.0）、[openedx](https://github.com/openedx/openedx-platform)（AGPL-3.0）、[kolibri](https://github.com/learningequality/kolibri)（MIT，离线优先）

**我们提供**：书 → 章 → 节 → 概念的目录结构，可直接映射成课程目录。
**对方提供**：课程承载、进度、SCORM/xAPI。

**场景**：按「册/章/节」批量建课，概念作为"标签"挂在资源上；离线场景用 Kolibri 分发。

**分工**：平台负责教学管理与进度，我们负责目录与知识点映射。宣称时以"目录级对接"为准，不必夸大。

---

## 13. 分工边界

本仓库是**数据层**，不向上做题库、不向下做渲染。清楚的边界反而便于对接：

| 能力 | 归属 |
|---|---|
| 题目、判分、练习 | 上游（出题方、题库平台、EduLab 的入口） |
| 课件渲染、动画、视频合成 | 下游（Manim / Slidev / Three.js / EduLab 模板） |
| 教材原文、概念、易错点、页码、课标、先修 | **本仓库** |
| 学科间的交叉关联 | 暂未建立（现有关系集中在学科内部，见下） |

**关于跨学科**：现有 21,198 条概念关系全部落在学科内部。跨学科关联（如数学「函数图像」↔ 物理「图像法」）
是独立的数据工程，需要自己的判据与金标——按 `part_of` 的经验，没有金标的批量连边会带来
约 8% 的假边率，所以宁可先空着。做全库关系图时，呈现的是学科各自的簇结构。

## 14. 一条最小可行流水线

```
教材 md（本仓库 content/）
    │  pnpm kg:ask tree / covered  ← 章节、概念、页码
    ├─→ Slidev / Marp            → 讲义（PDF / PPTX）
    ├─→ Manim + manim-slides     → 微课片段
    ├─→ CosyVoice / Kokoro（TTS） → 讲解配音
    │        └ Editly 装配成片 → whisperX 时间戳 → 回填"概念 ↔ 时间片"索引
    └─→ H5P Interactive Video    → 在时间点插入易错点设问
                              ↓
                     Moodle / Open edX / Kolibri 承载
```

四类角色不互相替代：
**Manim 管"精确示意"，Slidev 管"讲义与知识点一一对应"，whisper 系管"把成片反向索引回知识点"，H5P 管"交互点"**。
缺任何一环，都会出现"有视频但检索不到知识点"或"有知识点但出不了片"的断裂。

---

## 许可提醒

上列项目中 **Remotion 不是 OSI 开源**（个人与 ≤3 人公司免费，更大规模需商业授权）；
HunyuanVideo、CogVideoX 部分权重、LTX-Video 均带非标准限制。商用前必须逐字读 LICENSE，
本文只做技术可行性判断，不构成许可意见。
