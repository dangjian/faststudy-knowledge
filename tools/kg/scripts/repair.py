#!/usr/bin/env python3
"""repair.py — kg-repair 唯一执行入口（统一方法论 driver）。

确保后续 content 修复只走统一工具与流程的机制：
  1) 五层计分卡一条命令产出（check）；
  2) S1/S2/S4/S5 全部委托既有工具（本脚本只编排，不实现修复逻辑）；
  3) S0 结构手术不自动化（需人工裁定），但产物必须过 --check；
  4) --gate 基线非回归：红旗清单只许减不许增（CI/提交前跑）；
  5) 计分卡落盘 state/verify/repair/<BookId>/，账目可审计。

用法（knowledge 仓根目录）：
  pnpm kg:repair -- <BookId> --check            # 快速计分卡（L1/L3/L4/L5）
  pnpm kg:repair -- <BookId> --check --full     # 含 L2 忠实 diff（慢，需 PDF）
  pnpm kg:repair -- <BookId> --stage S1 --apply # 确定性清洗
  pnpm kg:repair -- <BookId> --stage S2 --apply # LLM 校准（AI_API_KEY）
  pnpm kg:repair -- <BookId> --stage S4 --apply # 图引用重建
  pnpm kg:repair -- <BookId> --stage S5         # 门禁
  pnpm kg:repair -- <BookId> --gate             # 红旗基线非回归
  pnpm kg:repair -- <BookId> --update-baseline  # 修复收敛后刷新基线
"""
import argparse, json, os, re, subprocess, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STATE = os.path.join(ROOT, 'tools/kg/state/verify/repair')
BASELINE = os.path.join(ROOT, 'tools/kg/state/verify/repair/redflag-baseline.json')


def sh(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    return r


def book_dir(book):
    for root, dirs, fs in os.walk(os.path.join(ROOT, 'content')):
        if os.path.basename(root) == book and 'chapters' in dirs:
            return root
    sys.exit('book not found: %s' % book)


def norm(s):
    return re.sub(r'\s+', '', s)


def l1l3_flags(book):
    r = sh([sys.executable, 'tools/kg/scripts/redflag_scan.py', '--book', book, '--json', '/tmp/_rf.json'])
    try:
        return json.load(open('/tmp/_rf.json', encoding='utf-8'))
    except Exception:
        return []


def l4_anchor_misses(book):
    B = book_dir(book)
    new = {}
    for f in glob.glob(B + '/chapters/C*/sections/*.md'):
        t = open(f, encoding='utf-8').read()
        m = re.search(r'sectionId:\s*(\S+)', t)
        if not m:
            continue
        body = t.split('---', 2)[2]
        body = re.sub(r'## 插图[\s\S]*$', '', body)
        body = '\n'.join(l for l in body.split('\n') if not l.startswith('|'))
        new[m.group(1)] = norm(re.sub(r'^#.*$', '', body, flags=re.M))
    titles = {}
    for f in glob.glob(os.path.join(ROOT, 'graph/entities/concepts/*.yaml')):
        for l in open(f, encoding='utf-8'):
            m = re.match(r'- id: (concept:[^:]+:\S+)', l.strip())
            if m:
                titles[m.group(1)] = m.group(1).split(':')[2]
    txt = open(os.path.join(ROOT, 'graph/relations/covered_by.yaml'), encoding='utf-8').read()
    prefix = book + '-'
    miss = []
    for b in txt.split('- from: ')[1:]:
        ls = b.split('\n')
        cid = ls[0].strip()
        if not cid.startswith('concept:'):
            continue
        for l in ls[1:]:
            if 'to: ' + prefix in l:
                to = l.split('to: ')[1].strip()
                if re.fullmatch(re.escape(book) + r'-C\d-S\d', to):
                    title = titles.get(cid, cid.split(':')[-1])
                    if norm(title) and norm(title) not in new.get(to, ''):
                        miss.append({'concept': title, 'section': to})
                break
    return miss


def l5_gate():
    r = sh(['npm', 'run', 'kg:lint'])
    ok = r.returncode == 0
    tail = [l for l in (r.stdout + r.stderr).split('\n') if 'error(s)' in l]
    return ok, (tail[-1] if tail else 'lint 无输出')


def cmd_check(book, full):
    rows = l1l3_flags(book)
    miss = l4_anchor_misses(book)
    ok5, msg5 = l5_gate()
    card = {'book': book, 'L1L3_flags': rows, 'L1L3_count': len(rows),
            'L4_anchor_missing': miss, 'L4_count': len(miss),
            'L5': {'ok': ok5, 'detail': msg5}}
    if full:
        r = sh([sys.executable, 'tools/kg/src/verify_prose.py', book, '--all-chapters'])
        card['L2_verify_prose_tail'] = r.stdout.strip().split('\n')[-6:]
        card['L2_note'] = '详见上方 diff 输出；差异需逐条裁决'
    os.makedirs(os.path.join(STATE, book), exist_ok=True)
    out = os.path.join(STATE, book, 'scorecard.json')
    json.dump(card, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('计分卡 →', os.path.relpath(out, ROOT))
    for r in rows:
        print('  [L1/L3]', r['f'], ','.join(r['flags']))
    print('  [L4] 锚点缺失 %d 条' % len(miss))
    print('  [L5]', msg5)
    if full:
        print('  [L2] 见 verify_prose 输出尾')
    return 0


def cmd_stage(book, stage, apply):
    bd = book_dir(book)
    if stage == 'S1':
        if not apply:
            print('S1 确定性清洗（默认 dry-run 由各工具自行控制；--apply 执行写盘）')
        chs = sorted(os.listdir(os.path.join(bd, 'chapters')))
        for ch in chs:
            d = os.path.join(bd, 'chapters', ch, 'sections')
            if os.path.isdir(d):
                r = sh([sys.executable, 'tools/kg/src/polish_format.py', d] + (['--apply'] if apply else []))
                print(r.stdout[-500:] if r.stdout else r.stderr[-300:])
        r = sh([sys.executable, 'tools/kg/src/reflow_prose.py', '--dry-run', bd + '/chapters'])
        print('[reflow dry-run 预览]', r.stdout[-400:] if r.stdout else r.stderr[-200:])
    elif stage == 'S2':
        # 内容校准主路径 = 当前 agent 在上下文中直接执行（2026-10-15 用户重申：严格不走外部 API）
        flags = l1l3_flags(book)
        miss = l4_anchor_misses(book)
        os.makedirs(os.path.join(STATE, book), exist_ok=True)
        wl = os.path.join(STATE, book, 's2-worklist.md')
        with open(wl, 'w', encoding='utf-8') as f:
            f.write('# S2 校准工作清单（agent 上下文内执行）\n\n')
            f.write('## 硬规则（忠实转写，不改题意）\n')
            f.write('- 不概括/不扩写/不删题/不改数字选项结论/不编造；错字可改（含水印变体）\n')
            f.write('- 公式损坏→LaTeX 仅限上下文唯一；截断句仅唯一可补全时补全\n')
            f.write('- 无法可靠恢复→保持原样，记入本文件 uncertain 段\n\n')
            f.write('## 待校准定位\n')
            for r0 in flags:
                f.write('- [L1/L3] %s：%s\n' % (r0['f'], ','.join(r0['flags'])))
            for m in miss:
                f.write('- [L4] %s ← %s（核对是否内容缺失）\n' % (m['section'], m['concept']))
        print('S2 工作清单 →', os.path.relpath(wl, ROOT))
        print('执行者：当前 agent（上下文内块级校准，规则见清单）；完成后必须过 --check 与 verify_prose')
        if apply:
            print('S2 无脚本可跑：校准由当前 agent 上下文内执行（外部 API 链已于 2026-10-15 移除）')
        return 0
    elif stage == 'S4':
        for cmd in (['pnpm', 'kg:fix:covered'], ['pnpm', 'kg:fix:orphans']):
            r = sh(cmd)
            print('$', ' '.join(cmd), '→', (r.stdout or r.stderr)[-400:])
    elif stage == 'S5':
        for cmd in (['npm', 'run', 'kg:lint'], ['npm', 'run', 'kg:test'], ['npm', 'run', 'kg:build']):
            r = sh(cmd)
            tail = (r.stdout + r.stderr).strip().split('\n')[-2:]
            print('$', ' '.join(cmd), '→', ' | '.join(tail))
            if r.returncode != 0:
                return 1
        print('提醒：结构变更需另出 PG migration（幂等 ×2）——见 kg-repair S4/S5 手册')
    else:
        sys.exit('未知 stage: %s（S0 为人工结构手术：取证→book_apply/重切，产物必须过 --check）' % stage)
    # 登记机械化：任何 stage 完成后自动刷新主队列（防「修了不登记」）
    cmd_check_all()
    return 0


def cmd_gate(book):
    cur = l1l3_flags(book)
    curset = {(r['book'], r['f'], tuple(sorted(r['flags']))) for r in cur}
    if os.path.exists(BASELINE):
        base = {(r['book'], r['f'], tuple(sorted(r['flags']))) for r in json.load(open(BASELINE, encoding='utf-8'))}
        novel = curset - base
        if novel:
            for b, f, fl in sorted(novel):
                print('  新增红旗:', f, ','.join(fl))
            print('GATE FAIL: 新增 %d 条红旗（基线 %d，当前 %d）——禁止提交' % (len(novel), len(base), len(curset)))
            return 1
        print('GATE PASS: 红旗 %d 条（基线 %d），无新增' % (len(curset), len(base)))
        return 0
    json.dump(cur, open(BASELINE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('基线建立：%d 条 → %s' % (len(cur), os.path.relpath(BASELINE, ROOT)))
    return 0


def all_books():
    out = []
    content = os.path.join(ROOT, 'content')
    for root, dirs, fs in os.walk(content):
        if 'chapters' in dirs:
            out.append(os.path.basename(root))
    return sorted(out)


def cmd_check_all():
    """全仓枚举：每册 L1/L3 红旗 + L4 锚点缺口 → 主队列（json + md 勾选清单）。"""
    from datetime import date
    queue = []
    for book in all_books():
        flags = l1l3_flags(book)
        miss = l4_anchor_misses(book)
        if flags or miss:
            queue.append({'book': book, 'flags': flags, 'anchor_missing': miss})
    os.makedirs(STATE, exist_ok=True)
    jpath = os.path.join(STATE, 'master-queue.json')
    json.dump({'date': str(date.today()), 'books': queue}, open(jpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    md = os.path.join(STATE, 'MASTER-QUEUE.md')
    n_flags = sum(len(b['flags']) for b in queue)
    n_miss = sum(len(b['anchor_missing']) for b in queue)
    with open(md, 'w', encoding='utf-8') as f:
        f.write('# content 修复总队列（%s 生成；修复会话从本清单取任务，完成后重跑 --check-all 刷新）\n\n' % date.today())
        f.write('总册 99；有缺陷册 **%d**；红旗文件 **%d**；锚点缺失 **%d** 条。\n\n' % (len(queue), n_flags, n_miss))
        f.write('规则：一册做完 = 该册本清单条目清零 + `--gate` 通过 + `--update-baseline` 收紧。\n\n')
        for b in sorted(queue, key=lambda x: -(len(x['flags']) + len(x['anchor_missing']))):
            f.write('## %s（红旗 %d / 锚点缺失 %d）\n\n' % (b['book'], len(b['flags']), len(b['anchor_missing'])))
            for r in b['flags']:
                f.write('- [ ] L1/L3 `%s`：%s\n' % (r['f'], ','.join(r['flags'])))
            if b['anchor_missing']:
                f.write('- [ ] L4 锚点缺失 %d 条（明细 state/verify/repair/%s/anchors.json；多为转录缺口）\n' % (len(b['anchor_missing']), b['book']))
                ap = os.path.join(STATE, b['book'])
                os.makedirs(ap, exist_ok=True)
                json.dump(b['anchor_missing'], open(os.path.join(ap, 'anchors.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            f.write('\n')
    print('总队列 → %s 与 %s' % (os.path.relpath(jpath, ROOT), os.path.relpath(md, ROOT)))
    print('有缺陷册 %d / 99；红旗文件 %d；锚点缺失 %d' % (len(queue), n_flags, n_miss))
    return 0


BAG_THRESHOLD = 0.93


def cmd_screen_all():
    """全仓 L2 预筛：逐册 verify_prose → bag_coverage 地图 → 队列分流（内容完好册 vs 缺文册）。"""
    from datetime import datetime
    books = all_books()
    results = {}
    fails = []
    for i, book in enumerate(books, 1):
        print('[%d/%d] %s …' % (i, len(books), book), flush=True)
        r = sh([sys.executable, 'tools/kg/src/verify_prose.py', book, '--all-chapters'])
        jp = os.path.join(ROOT, 'tools/kg/state/verify', book + '.json')
        if not os.path.exists(jp):
            fails.append((book, (r.stdout + r.stderr).strip().split('\n')[-1][:120]))
            continue
        d = json.load(open(jp, encoding='utf-8'))
        secs = []

        def walk(x):
            if isinstance(x, dict):
                if 'section' in x:
                    secs.append(x)
                else:
                    for v in x.values():
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(d.get('sections', []))
        bags = [s.get('bag_coverage', 0) for s in secs if s.get('bag_coverage') is not None]
        low = [{'section': s['chapter'] + '/' + s['section'], 'title': s.get('title', ''),
                'bag': s.get('bag_coverage'), 'shingle': s.get('shingle'),
                'prose': s.get('prose_chars'), 'ocr': s.get('ocr_chars')}
               for s in secs if s.get('bag_coverage', 1) < BAG_THRESHOLD]
        results[book] = {'sections': len(secs), 'min_bag': min(bags) if bags else None,
                         'sections_below': len(low), 'low_sections': low}
    out = os.path.join(STATE, 'bag-map.json')
    json.dump({'threshold': BAG_THRESHOLD, 'books': results}, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # 队列分流量化
    ok_books = [b for b, v in results.items() if not v['low_sections']]
    gap_books = [(b, v) for b, v in results.items() if v['low_sections']]
    print('\n══ L2 预筛汇总 ══')
    print('内容完好册（bag 全 ≥%.2f）: %d' % (BAG_THRESHOLD, len(ok_books)))
    print('缺文册（存在 bag<%.2f 节）: %d' % (BAG_THRESHOLD, len(gap_books)))
    for b, v in sorted(gap_books, key=lambda x: -x[1]['sections_below'])[:15]:
        print('  %-24s 缺文节 %d / %d（min_bag %.3f）' % (b, v['sections_below'], v['sections'], v['min_bag'] or 0))
    if fails:
        print('失败 %d 册:' % len(fails))
        for b, e in fails:
            print('  ', b, e)
    json.dump({'fails': fails}, open(os.path.join(STATE, 'screen-fails.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('bag 地图 →', os.path.relpath(out, ROOT))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('book', nargs='?', default=None)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--stage')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--gate', action='store_true')
    ap.add_argument('--check-all', action='store_true', help='全仓 99 册枚举缺陷 → 主队列')
    ap.add_argument('--screen-all', action='store_true', help='全仓 L2 预筛：逐册 verify_prose → bag 地图（慢，后台跑）')
    ap.add_argument('--update-baseline', action='store_true')
    a = ap.parse_args()
    if a.check_all:
        return cmd_check_all()
    if a.screen_all:
        return cmd_screen_all()
    if a.update_baseline:
        if not a.book: sys.exit('--update-baseline 需要 <BookId>')
        cur = l1l3_flags(a.book)
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        json.dump(cur, open(BASELINE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print('基线已更新：%d 条' % len(cur))
        return 0
    if a.gate:
        if not a.book: sys.exit('--gate 需要 <BookId>（全仓基线收敛由 --check-all 刷新体现）')
        return cmd_gate(a.book)
    if a.check:
        if not a.book: sys.exit('--check 需要 <BookId>；全仓用 --check-all')
        return cmd_check(a.book, a.full)
    if a.stage:
        if not a.book: sys.exit('--stage 需要 <BookId>')
        return cmd_stage(a.book, a.stage, a.apply)
    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main())
