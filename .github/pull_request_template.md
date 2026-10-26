## 改了什么

<!-- 一句话说明，例如：修正 32 条 prerequisite 边被误判为 part_of -->

## 依据

<!-- 数据类改动必填：教材第几页哪句话 / 课标哪一条 / 金标第几条 -->

## 检查清单

- [ ] `pnpm kg:lint` **0 error**（22 条规则，含先修无环与页码必填）
- [ ] `pnpm kg:test` 全过
- [ ] 动到既有关系边时，跑了对应金标：`kg:eval:covered` / `prereq` / `partof` / `type` / `mastery` / `strength`
- [ ] 没有提交生成物（`dist/`、`demo/data/`、`demo/vendor/`、`node_modules/`）
- [ ] 没有引入仓库外路径、密钥或内网信息（`bash tools/kg/scripts/check_open_source.sh` 应为 PASS）
- [ ] 新增成批语义标注时，已建 30–100 条金标并盲判（一致率 ≥85%）
