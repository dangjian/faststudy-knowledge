# 与开源教育产品结合的使用场景

本仓库的定位是 **AI agent 处理中小学知识点时的数据底座**，不是终端产品。
它提供「教材原文 + 概念 + 关系 + 页码」四类事实，课件、动画、视频由别的开源项目负责渲染。

按 **「与数据的匹配度 × 落地成本」** 排序，不按技术栈排。

下面每个场景都给出：**我们提供什么 → 对方提供什么 → 产出什么 → 最小验证路径 → 风险**。
每个场景都标清**分工边界**：哪些由本仓库负责，哪些由上游/下游负责。

---

## 1. 交互式解题课件：EduLab

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

## 2. AI 课堂与个性化辅导：OpenMAIC / DeepTutor

两个项目都做「agent 驱动的一堂课或一段辅导」。它们强在**怎么教**（角色分工、对话、课件生成），
弱在**教什么**的出处——这正是本仓补的位置。

| 项目 | 形态（据仓库自述） | 我们补什么 |
|---|---|---|
| [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC)（41.5k★，TypeScript） | 一键生成多智能体互动课堂：多角色协作、幻灯片、交互组件、苏格拉底式提问 | 每节课的章节结构、本节概念清单、易错点、教材页码——课堂引用的内容能回落到原文 |
| [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor)（43.5k★，Python） | 长期个性化辅导，多智能体 + CLI（标签：interactive-learning、multi-agent-systems） | 概念的前置依赖、常见错误、课标领域——让「该补哪里」有依据，而不只依赖对话历史 |

**分工**：它们决定教学策略与对话，我们负责事实与出处。2,976 节全带页码、1,497 万字原文，
是这类系统最容易缺的一环——多数教学 agent 只能靠模型记忆讲教材。

**最小验证路径**

```bash
pnpm kg:ask tree 'BSDU-7-1-Math'                    # 章节树 + 每节页码
pnpm kg:ask concepts 'BSDU-7-1-Math-C1-S1'          # 本节概念清单
pnpm kg:ask covered 'concept:数学:几何体'            # 该概念还在哪些节出现
```

拿这三段喂给对方写课堂脚本，检查生成的每一页能否标注「教材 p.x–y」。
标不出来说明它只用了模型记忆；标得出就是真的落了数据。

## 3. 可溯源问答：RAGFlow

**开源项目**：[infiniflow/ragflow](https://github.com/infiniflow/ragflow)（Apache-2.0）

**我们提供**：教材原文 + `sourceRef` + 页码，天然带引用锚点。
**对方提供**：分块、检索、引用回显。

**场景**：学生问"光合作用的原料是什么"，回答必须给出「教材 p.29–37」并在正文中回链，
而不是模型记忆。**这是本仓库最直接的差异点**——多数知识图谱只有 1–2 句描述，没有可读原文。

---

## 4. 课件/讲义：Slidev 或 Marp

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

## 5. 动态微课：Manim + manim-slides

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

## 6. 视频与交互点：H5P Interactive Video + 时间戳对齐

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

## 7. 关系图：Mermaid / D2

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

## 8. 学科专用可视化

**开源项目**：[jsxgraph/jsxgraph](https://github.com/jsxgraph/jsxgraph)（交互式几何）、[molstar/molstar](https://github.com/molstar/molstar)（分子结构）、[excalidraw/excalidraw](https://github.com/excalidraw/excalidraw)（手绘风白板，文件是 JSON 可脚本生成）

**我们提供**：概念的所属节、页码、易错点（决定要画哪个"反例"）。
**对方提供**：几何约束求解、分子 SMILES 渲染、手绘风插图。

**场景**：给几何概念生成可拖动的标准图 + 一个"易错形态"对照（如"高在三角形外部"），
易错点正好是我们 82% 概念都有的字段。

**风险**：这三类库都需要学科专家定"标准图形"，不能纯靠标题生成。

---

## 9. 可交互例题：Marimo / Quarto

**开源项目**：[marimo-team/marimo](https://github.com/marimo-team/marimo)（Apache-2.0，纯 Python 可 diff 的 notebook）、[quarto-dev/quarto-cli](https://github.com/quarto-dev/quarto-cli)

**我们提供**：概念 + 掌握标准（`masteryCriteria`，目前是"能指出并纠正这一错误：…"形态）。
**对方提供**：可执行 cell、参数化重算、一份源出多格式。

**场景**：把 `masteryCriteria` 转成"判断题 + 解释"，学生在 notebook 里改参数看结论是否仍成立。

**分工**：题目由现场生成或上游提供，本仓库提供该概念的掌握标准与教材出处，两者拼成完整的练习闭环。

---

## 10. LMS 承载：Moodle / Open edX / Kolibri

**开源项目**：[moodle](https://github.com/moodle/moodle)（GPL-3.0）、[openedx](https://github.com/openedx/openedx-platform)（AGPL-3.0）、[kolibri](https://github.com/learningequality/kolibri)（MIT，离线优先）

**我们提供**：书 → 章 → 节 → 概念的目录结构，可直接映射成课程目录。
**对方提供**：课程承载、进度、SCORM/xAPI。

**场景**：按「册/章/节」批量建课，概念作为"标签"挂在资源上；离线场景用 Kolibri 分发。

**分工**：平台负责教学管理与进度，我们负责目录与知识点映射。宣称时以"目录级对接"为准，不必夸大。

---

## 11. 分工边界

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

## 12. 一条最小可行流水线

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
