# AGENTS.md — Agent 接入指南

> 面向 AI agent（WorkBuddy / Claude Code / 其他编码 agent）的机器可读约定。
> 人类读者请看 [README.md](README.md) 与 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 这个仓库是什么

中小学教材知识库（knowledge-as-code）：`content/` 教材正文 + `graph/` 概念与关系，本地 md/YAML 是唯一真源。不装数据库，构建与查询由 `tools/kg` 工具链在内存完成。

## 三层边界（写错会挂 lint）

| 目录 | 角色 | 规则 |
|---|---|---|
| `content/` | L1 真源「学什么」 | 只放 md（章节正文 + 文末区块：`## 汉字/单词/短语/句子/插图/解题模型/笔记/总结`）；**禁止任何 yaml** |
| `graph/` | L2 真源「知识如何连接」 | 只放节点身份（`entities/concepts/<学科>.yaml`）+ 5 类边（`relations/`）；零正文载荷 |
| `dist/` | L3 派生（gitignore） | **永不手改、永不当查询源**（本地 agent 查询禁止读它；它仅供在线/外部 agent 消费） |

- structure（Textbook/Chapter/Section）与词书四类学习项**不落盘**：由 `loadGraph()` 从 content 派生物化。

## 查询图谱（Approach A：LLM 前置 + 脚本切片）

1. 先读 `graph/index.md`（问句→路径映射 + ID 前缀速查）。
2. 完整流程走 skill：`tools/skills/kg-query/SKILL.md`（总览见 `tools/skills/INDEX.md`）。
3. 脚本原语（仓库根目录运行）：

```bash
pnpm kg:ask tree     <textbookId>   # 章/节树
pnpm kg:ask concepts <sectionId>    # 某节概念
pnpm kg:ask covered  <conceptId>    # 概念被哪些节覆盖
pnpm kg:ask prereq   <conceptId>    # 先修传递闭包（DAG，必用脚本勿手写 BFS）
pnpm kg:ask demo     <conceptId>    # 例证学习项
pnpm kg:ask related  <conceptId>    # 相关概念
pnpm kg:ask partof   <conceptId>    # 整体-部分下游
pnpm kg:ask mindmap  <sectionId>    # 脑图聚合 JSON
```

4. 预算约束：关系边推理 ≤3 跳；单轮最多直读 5 个数据文件；大文件（concepts 聚合、related.yaml 等）严禁全量读入上下文，用上面切片命令。

## 修改图谱 / 内容

- 走 skill，不要绕过管线手改 YAML：写入用 `kg-edit`，摄入用 `kg-ingest`，巡检用 `kg-review`，缺口补齐用 `kg-delta`（路由入口 `kg-help`）。
- 交付门禁：每 Concept ≥1 条 covered_by；lint 0 error；`kg:build` 后三类关系计数 > 0。
- 决策落盘：改动后追加 `tools/kg/state/log.md`。

## 提交前必跑

```bash
pnpm kg:lint    # 0 error 才可提交
pnpm kg:test    # node --test，全部通过
pnpm kg:build   # 重建 dist；若 graph/ 有变更，dist 必须同步重建（在线消费方依赖它）
```

内容完整性诊断（输出缺失章节清单）：`python3 tools/kg/diag_gap.py`（仅标准库）。

## 环境注意

- pnpm workspace，包在 `tools/kg`。
- **内容修复/校准统一走 skill `kg-repair`（执行入口 `pnpm kg:repair -- <BookId>`，含 --gate 红旗基线非回归门禁）**。其中 S2 内容校准**由当前 agent 在上下文中直接执行**（遵守 kg-repair 的块级硬规则：忠实转写、不改题意、uncertain 旁路），**严格不通过外部 API**——外部 API 校准脚本（llm_repair_ocr/llm_polish_prose/llm_format_refine）已删除（2026-10-15），备选路径不复存在。确定性清洗/忠实验证/图引用仍走对应工具，agent 手术仅 S0 结构裁定等少数场景且必须遵守写盘/断言铁律。
- `graph/suspended-prerequisites.json`：被挂起的候选先修边（验证未通过暂不启用），不在常规 build 语义内，勿当作生效边引用。
- 许可：代码 MIT；自建数据 CC BY-NC-SA 4.0；教材转录版权归出版社（见 NOTICE），仅限个人学习研究。
