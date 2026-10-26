> ⚠️ **未适配 v4**：插图已降级为节 md 文末 `## 插图` 纯文本图注（不派生 Figure 实体、无 demonstrates 边）。启用前需先按 v4 改写。

# SKILL_06 - 抽取 figures

对需推理的图（几何题、带标注关系图），抽语义描述符，不画图。产出并入对应 section 的 items 文件 `content/<...>/<textbookId>/items/C<n>-S<m>.md` 的「## 插图」表格（分层 v3，经 `writeExtract()` 写入；`render` 列存 JSON 字符串）：

```yaml
figures:
  - id: fig:<textbookId>:<sectionId>:<slug>
    type: Figure
    figType: <right-triangle|...>
    render: {image: pages/<n>.jpg, source: image <n>}
    description: <文字描述>
    primitives: [{id: A, kind: point, role: vertex}, ...]
    relations: [{type: right-angle-at, at: C}, ...]
    sourceRef: <content path>
```

纯示意图只需 `description` + `render`。几何存储为 primitives + relations 子图，渲染分离（OSS 页面图 / 后续 JSXGraph）。
注意 entity 的 `type` 固定 `Figure`，原图类型放 `figType`。
