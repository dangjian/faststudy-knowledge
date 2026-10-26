#!/usr/bin/env python3
"""内容完整性诊断：对照同年级两学期节数 + 课标学科映射，输出缺失清单。

用法:
    python3 tools/kg/diag_gap.py
依赖: 仅标准库
"""
import os, glob
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', 'content')
ROOT = os.path.abspath(ROOT)
GRADES = ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级', '七年级', '八年级', '九年级']
TERMS = ['上册', '下册', '全一册']
# 课标：各年级应开学科（1–6 年级按小学入图谱 spec P2 矩阵；7–9 年级地理/生物仅七、八）
PRIMARY_LOW = ['语文', '数学', '道德与法治', '科学']
PRIMARY_HIGH = PRIMARY_LOW + ['英语']
EXPECT = {
    '一年级': PRIMARY_LOW, '二年级': PRIMARY_LOW,
    '三年级': PRIMARY_HIGH, '四年级': PRIMARY_HIGH, '五年级': PRIMARY_HIGH, '六年级': PRIMARY_HIGH,
    '七年级': ['语文', '数学', '英语', '历史', '地理', '生物', '道德与法治'],
    '八年级': ['语文', '数学', '英语', '历史', '地理', '生物', '道德与法治', '物理'],
    '九年级': ['语文', '数学', '英语', '历史', '物理', '化学', '道德与法治'],
}

def count_sec(g, t, subj):
    base = os.path.join(ROOT, g, t, subj)
    if not os.path.isdir(base):
        return None
    n = 0
    for tb in os.listdir(base):
        for _ in glob.glob(os.path.join(base, tb, 'chapters', '*', 'sections', '*.md')):
            n += 1
    return n

def main():
    sec = {}
    for g in GRADES:
        for t in TERMS:
            for s in EXPECT[g]:
                sec[(g, t, s)] = count_sec(g, t, s)

    print("=== A. 同年级两学期对照（节数）===")
    for g in GRADES:
        print(f"\n[{g}]")
        for s in EXPECT[g]:
            a = sec[(g, '上册', s)]; b = sec[(g, '下册', s)]; whole = sec[(g, '全一册', s)]
            if whole is not None:
                print(f"  {s:<8} 全一册={whole}"); continue
            if a is None and b is None:
                print(f"  {s:<8} 上下册均缺失"); continue
            a = a or 0; b = b or 0
            lo, hi = min(a, b), max(a, b)
            flag = '  ⚠ 偏少学期疑似未完整转录' if (hi > 0 and lo < 0.5 * hi) else ''
            print(f"  {s:<8} 上={a:<3} 下={b:<3}{flag}")

    print("\n=== B. 跨年级应开学科是否缺失 ===")
    for g in GRADES:
        for s in EXPECT[g]:
            if not any(sec[(g, t, s)] for t in TERMS):
                print(f"  {g} 完全缺失学科：{s}")

if __name__ == '__main__':
    main()
