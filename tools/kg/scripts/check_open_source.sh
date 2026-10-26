#!/usr/bin/env bash
# 开源门禁（spec §4.3）：git grep -in 只搜跟踪文件；白名单 + 其余零命中。
# 用法: bash tools/kg/scripts/check_open_source.sh   （在仓库任意位置）
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
SELF=':!tools/kg/scripts/check_open_source.sh'   # 排除自身——禁串字面量写在脚本里，不排除会自证其罪
fail=0

for pat in '/Users/' 'temp_processed_data' 'backend' 'porsche' 'dangyifan' '党逸帆' '8.141.84.52' '主仓' 'superpowers' 'handoff' 'platform_uuid' 'aceconsulting'; do
  if git grep -in -e "$pat" -- . "$SELF" ; then
    echo "FAIL: 禁串命中 [$pat]"; fail=1
  fi
done

# LTAI：阿里云 AccessKey 形态（LTAI + ≥12 位字母数字）。
# 不用裸子串——deltaId 等字段名大小写不敏感地含 "ltaid"，会误报。
if git grep -inE 'LTAI[0-9A-Za-z]{12,}' -- . "$SELF" ; then
  echo "FAIL: 阿里云 AccessKey 形态命中 [LTAI...]"; fail=1
fi

# faststudy：白名单 = 包名/品牌名（新增合法形态必须人工过目后显式加进 ALLOW，禁止放宽）
ALLOW='faststudy-knowledge|@faststudy/kg|FastStudy 知识|faststudy-knowledge@'
viol=$(git grep -in -e 'faststudy' -- . "$SELF" | grep -Ev "$ALLOW" || true)
if [ -n "$viol" ]; then echo "FAIL: faststudy 非白名单命中:"; echo "$viol"; fail=1; fi

[ "$fail" -eq 0 ] && echo "OPEN-SOURCE GATE PASS"
exit "$fail"
