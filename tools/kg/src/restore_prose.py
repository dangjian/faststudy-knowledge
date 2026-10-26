#!/usr/bin/env python3
"""
git 历史正文回填：修复「批次 apply 重切」丢课正文事故（2026-09-18：7612a4e2 / 120f8e57 等）。

问题：重切提交删除了章级 index.md 的课正文与课内小节块、且未搬入 sections/S*.md，
     全库 81 个 section 正文空壳（<100 字符），图谱 prose（load.ts 直读 sections）为空。

算法（锚点区间回填）：
1. 以当前 index.md 存活的 ## 块标题序列为锚点骨架（同名多块按出现序对齐）；
2. 在该文件 git 历史版本中定位各锚点标题，取「锚点 → 下一锚点」的历史区间
   （被重切删除的课内小节块自然落回宿主锚点区间）；
3. 选择「锚点命中数最多、其次区间 prose 总量最大」的历史版本；
4. 回填 = 保留当前 frontmatter 与锚点标题行，正文区替换为历史区间。
只处理区间 prose 低于阈值的锚点（空块），当前已有正文的锚点区间不动。

用法:
  python3 restore_prose.py content/七年级/上册/历史/PEP-7-1-History --dry-run
  python3 restore_prose.py content/七年级/上册/历史/PEP-7-1-History --apply
  python3 restore_prose.py content --batch --dry-run

台账: tools/kg/state/ingest/restore_prose_report.json（本机私有，不入 git）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
REPORT = REPO / 'knowledge' / 'tools' / 'kg' / 'state' / 'ingest' / 'restore_prose_report.json'

MIN_CHARS = 100          # 锚点区间正文低于此值视为空（消费端口径）
MIN_RECOVER_CHARS = 30   # 历史区间正文至少此值才值得回填


def parse_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith('---'):
        return '', text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return '', text
    return parts[1].strip('\n'), parts[2].lstrip('\n')


def prose_len(text: str) -> int:
    """正文字符数：去标题行、表格行、插图区（消费端口径，与巡检一致）。"""
    in_fig = False
    chars = 0
    for line in text.splitlines():
        if line.startswith('## '):
            in_fig = line.strip() == '## 插图'
            continue
        if line.startswith('#') or line.startswith('|') or in_fig:
            continue
        chars += len(line.replace(' ', ''))
    return chars


def norm(title: str) -> str:
    t = re.sub(r'[\s\.、．·]+', '', title)
    t = re.sub(r'^第?\d+课?', '', t)
    return t.strip('《》')


def heading_positions(body: str) -> list[tuple[str, int, int]]:
    """[(norm_title, start_pos, title_line_end)] 按 ## 标题出现序。"""
    out = []
    for m in re.finditer(r'^## (.+?)\s*$', body, flags=re.M):
        out.append((norm(m.group(1)), m.start(), m.end()))
    return out


def analyze_current(body: str) -> list[dict]:
    """当前锚点骨架：[{norm, title, start, end, prose}]，end=下一锚点 start 或文末。"""
    hs = heading_positions(body)
    anchors = []
    for i, (k, start, tend) in enumerate(hs):
        end = hs[i + 1][1] if i + 1 < len(hs) else len(body)
        seg = body[tend:end]
        anchors.append({
            'norm': k,
            'title': body[start:tend].strip()[3:].strip(),
            'start': start,
            'end': end,
            'prose': prose_len(seg),
        })
    return anchors


def align_anchors(cur: list[dict], hist_pos: list[tuple[str, int, int]]) -> dict[int, int]:
    """当前锚点序 → 历史标题序（同名按出现序对齐；缺位锚点跳过，部分对齐）。"""
    mapping = {}
    h_used: dict[str, int] = {}
    h_list_by_key: dict[str, list[int]] = {}
    for j, (k, _, _) in enumerate(hist_pos):
        h_list_by_key.setdefault(k, []).append(j)
    for i, a in enumerate(cur):
        lst = h_list_by_key.get(a['norm'])
        if not lst:
            continue
        j_idx = h_used.get(a['norm'], 0)
        if j_idx >= len(lst):
            continue
        mapping[i] = lst[j_idx]
        h_used[a['norm']] = j_idx + 1
    return mapping


def best_version(rel: str, cur: list[dict], empty_idx: set[int]) -> tuple[dict | None, str]:
    """在历史版本中选最优：以「空锚点回填增益」（历史区间 prose − 当前 prose 的正数和）评分。"""
    out = subprocess.run(['git', 'log', '--format=%H', '--', rel],
                         capture_output=True, text=True, cwd=REPO / 'knowledge')
    commits = out.stdout.split()
    cur_anchor_keys = {a['norm'] for a in cur}
    best = None
    best_desc = ''
    for c in commits:
        r = subprocess.run(['git', 'show', f'{c}:{rel}'],
                           capture_output=True, text=True, cwd=REPO / 'knowledge')
        if r.returncode != 0:
            continue
        _, hbody = parse_frontmatter(r.stdout)
        hpos = heading_positions(hbody)
        mapping = align_anchors(cur, hpos)
        if not mapping:
            continue
        gain, segs = 0, {}
        for i in sorted(mapping):
            if i not in empty_idx:
                continue
            htend = hpos[mapping[i]][2]
            # 历史侧区间：该锚点标题后 → 历史中下一个「当前锚点集合」标题（含缺位跳查）
            hend = len(hbody)
            for j2 in range(mapping[i] + 1, len(hpos)):
                if hpos[j2][0] in cur_anchor_keys:
                    hend = hpos[j2][1]
                    break
            seg = hbody[htend:hend]
            # 重叠守卫：区间内若含「当前已有正文」的其他锚点 → 内容重复，跳过
            inner = [hpos[j2][0] for j2 in range(mapping[i] + 1, len(hpos))
                     if hpos[j2][1] < hend]
            conflict = any(k in cur_anchor_keys
                           and next(a for a in cur if a['norm'] == k)['prose'] >= MIN_CHARS
                           for k in inner if k != cur[i]['norm'])
            if conflict:
                continue
            d = prose_len(seg) - cur[i]['prose']
            if d > 0:
                segs[i] = seg
                gain += d
        desc = f'{c[:8]}(anchors={len(mapping)}/{len(cur)}, gain={gain})'
        if gain > 0 and (best is None or gain > best[0]):
            best = (gain, segs, c, hbody)
            best_desc = desc
    return best, best_desc


def build_new_body(body: str, cur: list[dict], segs: dict[int, str]) -> tuple[str, list[dict]]:
    """重建正文：空锚点区间换历史，非空锚点保持原样。"""
    out: list[str] = []
    changed = []
    pos = 0
    for i, a in enumerate(cur):
        if a['prose'] >= MIN_CHARS:
            continue
        seg = segs.get(i, '')
        if prose_len(seg) < MIN_RECOVER_CHARS or prose_len(seg) - a['prose'] <= 20:
            continue
        title_line = f"## {a['title']}"
        out.append(body[pos:a['start']])
        out.append(f"{title_line}\n\n{seg.strip()}\n\n")
        pos = a['end']
        changed.append({'title': a['title'],
                        'from': a['prose'], 'to': prose_len(seg)})
    out.append(body[pos:])
    return ''.join(out), changed


def head_prose_pool(rel: str) -> str:
    """HEAD 版该书全部 section 正文（norm 后拼接）——回填片段的重复检测池。"""
    book_dir = (REPO / 'knowledge' / rel).parent.parent
    texts = []
    for md in book_dir.glob('chapters/*/sections/S*.md'):
        r = subprocess.run(['git', 'show', f'HEAD:{md.relative_to(REPO / "knowledge")}'],
                           capture_output=True, text=True, cwd=REPO / 'knowledge')
        if r.returncode != 0:
            continue
        _, b = parse_frontmatter(r.stdout)
        # 与巡检同口径取正文
        lines, in_fig = [], False
        for line in b.split('\n'):
            if line.startswith('## '):
                in_fig = line.strip() == '## 插图'
                continue
            if line.startswith('#') or line.startswith('|') or in_fig:
                continue
            lines.append(line)
        texts.append(norm(''.join(lines).replace(' ', '')))
    return ''.join(texts)


def strip_known(seg: str, pool: str) -> str:
    """剥离 seg 中已在 HEAD 各节正文里存在的段落（按空行段 + 40 字指纹 in-pool 判定）。"""
    if not pool:
        return seg
    kept = []
    dropped = 0
    for para in re.split(r'\n\s*\n', seg):
        fp = norm(para.replace(' ', ''))[:40]
        if len(fp) >= 20 and fp in pool:
            dropped += 1
            continue
        kept.append(para)
    return '\n\n'.join(kept)


def process(idx: Path, apply: bool) -> dict:
    rel = str(idx.relative_to(REPO / 'knowledge'))
    raw = idx.read_text(encoding='utf-8')
    fm, body = parse_frontmatter(raw)
    cur = analyze_current(body)
    empty = [a for a in cur if a['prose'] < MIN_CHARS]
    if not empty:
        return {'file': rel, 'status': 'clean'}

    best, desc = best_version(rel, cur, {i for i, a in enumerate(cur) if a['prose'] < MIN_CHARS})
    if not best:
        return {'file': rel, 'status': 'no-compatible-version',
                'empty': [a['title'] for a in empty]}
    _, segs, commit, _ = best
    pool = head_prose_pool(rel)
    segs = {i: strip_known(seg, pool) for i, seg in segs.items()}
    new_body, changed = build_new_body(body, cur, segs)
    res = {
        'file': rel,
        'status': 'planned' if not apply else 'applied',
        'version': desc,
        'changed': changed,
    }
    if apply and changed:
        idx.write_text(f'---\n{fm}\n---\n\n' + new_body.lstrip('\n'), encoding='utf-8')
    return res


def collect(root: Path) -> list[Path]:
    if (root / 'chapters').is_dir():
        return sorted((root / 'chapters').glob('*/index.md'))
    if root.name == 'content':
        return sorted(root.glob('*/*/*/*/chapters/*/index.md'))
    return sorted(root.glob('chapters/*/index.md')) if root.is_dir() else [root]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('path', type=Path)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    root = args.path if args.path.is_absolute() else REPO / 'knowledge' / args.path

    idx_files = collect(root)
    print(f'scanning {len(idx_files)} chapter indexes under {root.name}')
    results = []
    for idx in idx_files:
        r = process(idx, apply=args.apply)
        results.append(r)
        if r['status'] == 'clean':
            continue
        tag = r['status']
        print(f"\n== {r['file']} [{tag}] {r.get('version', '')}")
        for c in r.get('changed', []):
            print(f"   [{c['from']:>4} -> {c['to']:>6}] {c['title'][:44]}")
        for t in r.get('empty', []):
            print(f"   [no-version] {t[:44]}")

    n_plan = sum(1 for r in results if r['status'] in ('planned', 'applied'))
    n_blocks = sum(len(r.get('changed', [])) for r in results)
    print(f"\nfiles touched: {n_plan}/{len(results)}, blocks restored: {n_blocks}, "
          f"mode: {'APPLY' if args.apply else 'dry-run'}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'report: {REPORT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
