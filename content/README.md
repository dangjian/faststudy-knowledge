# content/ - 知识 prose 源

教材忠实转写正文 + 元信息。图谱结构见 `../graph/`。

- `<textbookId>/index.md` - front-matter 承载教材元信息 + 章节目录
- `<textbookId>/chapters/C<n>/sections/S<m>.md` - 小节正文
- `<textbookId>/appendix/*.md` - 附录正文

编译产出见 `../dist/graph.json`（`tools/kg build`）。
