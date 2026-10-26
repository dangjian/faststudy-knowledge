#!/usr/bin/env bash
# 下载 Three.js 0.180 到 <目标 lib 目录>（页面 importmap 引用 ../lib/three.module.min.js）
# module 以 ./three.core.min.js 相对引入 core，两者须同目录
# 用法：bash fetch-three.sh <out-dir>/lib
set -euo pipefail
dest=${1:?用法：bash fetch-three.sh <目标 lib 目录>}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && npm pack three@0.180.0 --silent >/dev/null && tar xzf three-0.180.0.tgz)
mkdir -p "$dest"
cp "$tmp/package/build/three.module.min.js" "$tmp/package/build/three.core.min.js" "$dest/"
cp "$tmp/package/LICENSE" "$dest/three.LICENSE"
ls "$dest"
