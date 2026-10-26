#!/usr/bin/env python3
"""节级大纲重切 propose：以 PG 目录快照为目标态，产出重切台账（确定性，不调 LLM/OCR）。

用法（在 knowledge 仓根）:
  pnpm kg:reoutline:propose --textbook BSDU-8-2-Math
  pnpm kg:reoutline:propose --textbook BSDU-8-2-Math --force   # 覆盖已有台账
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_frontmatter import find_book_dir, parse_frontmatter, read_book  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]  # knowledge 仓根
SNAPSHOT = ROOT / 'tools' / 'kg' / 'state' / 'curriculum_toc.json'
H2_RE = re.compile(r'^##\s+(.+?)\s*$')
S_ID_RE = re.compile(r'^S\d+$')
MAX_AGE = timedelta(days=7)
COVERED_BY_FROM_RE = re.compile(r'^\s*-\s*from:\s*(concept:.+?)\s*$')
COVERED_BY_TO_RE = re.compile(r'^\s*to:\s*(.+?)\s*$')


def source_dir() -> Path:
    """教材源图目录。开源后经环境变量注入，缺失即退出。"""
    v = os.environ.get('KG_SOURCE_DIR')
    if not v:
        sys.exit('环境变量 KG_SOURCE_DIR 未设置：指向含 <教材id>/pages、metadata.json 的源图目录')
    return Path(v)


# ---- 标题归一（与应用侧同名服务保持同语义（跨仓契约）；golden 向量共用一份） ----
def norm_title(t: str) -> str:
    t = re.sub(r'\s+', '', t)
    t = re.sub(r'^第[0-9０-９一二三四五六七八九十百]+[节课章]?[、.．:：·]?', '', t)
    t = re.sub(r'^[0-9０-９]+[、.．:：·]?', '', t)
    t = re.sub(r'^[一二三四五六七八九十百]+[、.．:：·]', '', t)
    return t


def is_placeholder_title(t: str) -> bool:
    s = t.strip()
    return s == '' or re.fullmatch(r'第?[0-9０-９]+节', s) is not None


def classify_py(pg_title: str, kg_title: str) -> str:
    if pg_title.strip() == kg_title.strip():
        return 'agree'
    np_ = norm_title(pg_title)
    if np_ != '' and np_ == norm_title(kg_title):
        return 'agree'
    if is_placeholder_title(kg_title):
        return 'placeholder'
    return 'mismatch'


# ---- 决策与 diff ----
def decide_prose_source(pg_title: str, h2s: list, page_range, meta_level2: dict) -> str:
    """h2s: [(行号, 标题)]。唯一 H2 命中 → h2_block；否则看页码（PG 或 metadata 兜底）→ ocr；都没有 → missing。"""
    np_ = norm_title(pg_title)
    if np_:
        cands = [h for h in h2s if norm_title(h[1]) == np_]
        if len(cands) == 1:
            return 'h2_block'
    if page_range:
        return 'ocr'
    if np_ and np_ in meta_level2:
        return 'ocr'  # metadata 兜底页码（裁决 6）
    return 'missing'


def compute_id_diff(old: dict, new: dict) -> dict:
    """old/new: {完整节id: title}。replaced = id 同形但归一标题不同（内容换血）。"""
    inter = set(old) & set(new)
    return {
        'kept': sorted(i for i in inter if norm_title(old[i]) == norm_title(new[i])),
        'replaced': sorted(i for i in inter if norm_title(old[i]) != norm_title(new[i])),
        'added': sorted(set(new) - set(old)),
        'dropped': sorted(set(old) - set(new)),
    }


def _norm_text(t: str) -> str:
    return re.sub(r'\s+', '', t)


# LaTeX 命令 → Unicode 记号（探针双侧同用，不做通用 LaTeX 解析）
_LATEX_TO_UNICODE = [
    (r'\\triangle', '△'),
    (r'\\angle', '∠'),
    (r'\\parallel', '∥'),
    (r'\\perp', '⊥'),
    (r'\\cdot', '·'),
    (r'\\times', '×'),
    (r'\\neq', '≠'),
    (r'\\ne', '≠'),
    (r'\\leq', '≤'),
    (r'\\le', '≤'),
    (r'\\geq', '≥'),
    (r'\\ge', '≥'),
    (r'\\sim', '∼'),
    (r'\\cong', '≅'),
    (r'\\approx', '≈'),
    (r'\\deg', '°'),
    (r'\\circ', '°'),
    (r'\^\{\\circ\}', '°'),
    (r'\^\\circ', '°'),
    (r'\^circ', '°'),
    (r'\\alpha', 'α'),
    (r'\\beta', 'β'),
    (r'\\gamma', 'γ'),
    (r'\\delta', 'δ'),
    (r'\\pi', 'π'),
    (r'\\sqrt', '√'),
    (r'\\frac\{(.+?)\}\{(.+?)\}', r'\1/\2'),
]


def _math_norm(t: str) -> str:
    """记号归一：剥 $ 与空白，常见 LaTeX 命令转 Unicode，用于探针双侧匹配。"""
    s = t
    # 剥所有 $ （行内/行间公式界定符）
    s = s.replace('$', '')
    # 按长度降序替换（先替换长的，避免短的先吃长的，如 \neq 先于 \ne）
    for pattern, repl in sorted(_LATEX_TO_UNICODE, key=lambda x: -len(x[0])):
        s = re.sub(pattern, repl, s)
    # 剥残余反斜杠命令（\{command} 或 \command 形式，仅去反斜杠保留命令名）
    s = re.sub(r'\\([a-zA-Z]+)', r'\1', s)
    # 剥成对花括号（残留的 { }）
    s = re.sub(r'[{}]', '', s)
    # 去空白
    s = re.sub(r'\s+', '', s)
    return s


def _extract_h2_block_text(raw_md: str, target_title: str) -> str:
    """从章级 index.md 原始文本中提取指定标题 H2 块的正文（到下一个 H2/文件尾为止）。
    标题用 norm_title 归一后匹配。找不到返回空串。"""
    lines = raw_md.splitlines()
    h2s = [(i, m.group(1)) for i, line in enumerate(lines) if (m := H2_RE.match(line))]
    norm_target = norm_title(target_title)
    # 找匹配的 H2
    start_idx = None
    for i, title in h2s:
        if norm_title(title) == norm_target:
            start_idx = i
            break
    if start_idx is None:
        return ''
    # 找下一个 H2
    next_idx = len(lines)
    for i, _ in h2s:
        if i > start_idx:
            next_idx = i
            break
    # 正文 = H2 下一行到下一个 H2 前一行
    body_lines = lines[start_idx + 1:next_idx]
    return '\n'.join(body_lines)


def map_concepts(edges, prose, concept_data=None, fig_map=None):
    """edges: [{conceptId, title, to}]；prose: {sId: 文本}。
    concept_data: {conceptId: {title, aliases, explanation}}（可选，提供则启用 alias/explanation 证据级）
    fig_map: {conceptId: [fig_id, ...]}（可选，提供则启用 fig 证据级；fig 末段在 prose 【图：xxx】 中定位）

    证据链（按级递减，唯一命中即停止）：title → alias → explanation → fig
    返回 {
      mapped: {conceptId: {'section': sId, 'evidence': 'title'|'alias'|'explanation'|'fig'}},
      unmapped: [{conceptId, title, reason, hits, evidenceTried}],
    }
    其中 reason: 'multiMatch' | 'zeroMatch'；evidenceTried: [{level, hits}]。
    """
    norm_prose = {k: _math_norm(v) for k, v in prose.items()}
    cdata = concept_data or {}
    fmap = fig_map or {}

    # 预构建 prose 中 fig 标记 → 节的映射（用于 fig 级定位）
    # fig_id 末段（最后一个 : 后的部分，如 "图1-13"）→ 含【图：图1-13】的节集合
    fig_to_sections: dict[str, set] = {}
    if fmap:
        # 先收集所有涉及概念的 fig 末段
        all_fig_tails: set[str] = set()
        for fig_ids in fmap.values():
            for fig_id in fig_ids:
                tail = fig_id.rsplit(':', 1)[-1] if ':' in fig_id else fig_id
                all_fig_tails.add(tail)
        # 在 prose 中扫描这些 fig 标记
        for s_id, text in prose.items():
            for tail in all_fig_tails:
                if f'【图：{tail}' in text:
                    fig_to_sections.setdefault(tail, set()).add(s_id)

    mapped: dict[str, dict] = {}
    unmapped = []

    for e in edges:
        cid = e['conceptId']
        e_title = e.get('title', '')
        data = cdata.get(cid, {'title': e_title, 'aliases': [], 'explanation': ''})
        evidence_tried: list[dict] = []
        best_multi_hits: list | None = None
        best_multi_level = ''

        # ---- 级 1：title ----
        needle = _math_norm(data.get('title', '') or e_title)
        hits = [s for s in prose if needle and needle in norm_prose[s]]
        evidence_tried.append({'level': 'title', 'hits': len(hits)})
        if len(hits) == 1:
            mapped[cid] = {'section': hits[0], 'evidence': 'title'}
            continue
        if len(hits) > 1:
            best_multi_hits = hits
            best_multi_level = 'title'

        # ---- 级 2：aliases ----
        alias_hits: list[str] = []
        if data.get('aliases'):
            for alias in data['aliases']:
                a_needle = _math_norm(alias)
                if not a_needle:
                    continue
                a_hits = [s for s in prose if a_needle in norm_prose[s]]
                for s in a_hits:
                    if s not in alias_hits:
                        alias_hits.append(s)
        evidence_tried.append({'level': 'alias', 'hits': len(alias_hits)})
        if len(alias_hits) == 1:
            mapped[cid] = {'section': alias_hits[0], 'evidence': 'alias'}
            continue
        if len(alias_hits) > 1 and best_multi_level in ('', 'title'):
            best_multi_hits = alias_hits
            best_multi_level = 'alias'

        # ---- 级 3：explanation 分句 ----
        expl_hits: list[str] = []
        explanation = data.get('explanation', '') or ''
        if explanation:
            # 按 ；/。 切分，≥ 8 字的子句逐个探针
            clauses = [c.strip() for c in re.split(r'[；。]', explanation) if c.strip()]
            for clause in clauses:
                if len(clause) < 8:
                    continue
                c_needle = _math_norm(clause)
                if not c_needle:
                    continue
                c_hits = [s for s in prose if c_needle in norm_prose[s]]
                for s in c_hits:
                    if s not in expl_hits:
                        expl_hits.append(s)
        evidence_tried.append({'level': 'explanation', 'hits': len(expl_hits)})
        if len(expl_hits) == 1:
            mapped[cid] = {'section': expl_hits[0], 'evidence': 'explanation'}
            continue
        if len(expl_hits) > 1 and best_multi_level in ('', 'title', 'alias'):
            best_multi_hits = expl_hits
            best_multi_level = 'explanation'

        # ---- 级 4：fig 通路 ----
        fig_hits: list[str] = []
        fig_ids = fmap.get(cid, [])
        if fig_ids:
            for fig_id in fig_ids:
                tail = fig_id.rsplit(':', 1)[-1] if ':' in fig_id else fig_id
                f_secs = fig_to_sections.get(tail, set())
                for s in f_secs:
                    if s not in fig_hits:
                        fig_hits.append(s)
        evidence_tried.append({'level': 'fig', 'hits': len(fig_hits)})
        if len(fig_hits) == 1:
            mapped[cid] = {'section': fig_hits[0], 'evidence': 'fig'}
            continue
        if len(fig_hits) > 1 and best_multi_level != 'fig' and best_multi_level in ('', 'title', 'alias', 'explanation'):
            best_multi_hits = fig_hits
            best_multi_level = 'fig'

        # ---- 全部级走完无唯一 ----
        if best_multi_hits is not None:
            unmapped.append({
                'conceptId': cid, 'title': data.get('title', '') or e_title,
                'reason': 'multiMatch', 'hits': best_multi_hits,
                'evidenceTried': evidence_tried,
            })
        else:
            unmapped.append({
                'conceptId': cid, 'title': data.get('title', '') or e_title,
                'reason': 'zeroMatch', 'hits': [],
                'evidenceTried': evidence_tried,
            })

    return {'mapped': mapped, 'unmapped': unmapped}


FIG_ROW_RE = re.compile(r'^\|\s*fig:.+?\s*\|')


def _count_figs(h2_titles: list, h2_indices: list, lines: list) -> int:
    """统计 ## 插图 区块中的 fig 行数。
    多个插图区块 = apply 搬运后的常态（多来源表并入同一节），逐块求和，
    重复 fig 行按 id 去重（与 apply 的幂等追加对称）。"""
    if '插图' not in h2_titles:
        return 0
    seen_ids = set()
    total = 0
    for k, t in enumerate(h2_titles):
        if t != '插图':
            continue
        nxt = h2_indices[k + 1] if k + 1 < len(h2_indices) else len(lines)
        for line in lines[h2_indices[k] + 1:nxt]:
            if FIG_ROW_RE.match(line):
                fid = line.split('|')[1].strip()
                if fid not in seen_ids:
                    seen_ids.add(fid)
                    total += 1
    return total


def _parse_items_blocks(path: Path, allow_vocab: bool = False):
    """解析 items/C<n>-S<m>.md，返回 (blocks, fig_count)。
    blocks: 恒为 []——2026-09-27 刷题层移除，## 习题 段已全库剥离，出现即历史文件回流（SystemExit）。
    fig_count: ## 插图 区块中的 fig 表行数（无插图区块则为 0）。
    H2 规则（content v4）：## 插图 / ## 解题模型 / ## 笔记 / ## 总结 全书合法；
    ## 单词 / ## 短语 / ## 句子 / ## 汉字 仅 allow_vocab 书合法；## 习题 非法（刷题层已裁撤）。"""
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    # 收集所有 H2 标题及位置
    h2_titles = []
    h2_indices = []
    for i, line in enumerate(lines):
        m = H2_RE.match(line)
        if m:
            h2_titles.append(m.group(1).strip())
            h2_indices.append(i)
    # 合法性检查（所有路径统一闸门）
    if '习题' in h2_titles:
        raise SystemExit(f'{path} 含 ## 习题 区块（刷题层已移除，历史文件回流，进人工）')
    allowed = {'插图', '解题模型', '笔记', '总结'} | ({'单词', '短语', '句子', '汉字'} if allow_vocab else set())
    forbidden = {'单词', '短语', '句子', '汉字'} if not allow_vocab else set()
    bad = [t for t in h2_titles if t in forbidden]
    if bad:
        raise SystemExit(
            f'{path} 含非法 H2 区块：{bad}（非 allow_vocab 书不应出现词书区块，进人工）',
        )
    if not all(t in allowed for t in h2_titles):
        raise SystemExit(
            f'{path} 含未知 H2 区块：{h2_titles}（允许：插图/解题模型/笔记/总结 + 词书四类（allow_vocab））',
        )
    # 空壳文件（仅 frontmatter，P0/P1 遗留）：0 块 0 图，合法
    if not h2_titles and not norm_title(text.split('---', 2)[-1] if text.count('---') >= 2 else text):
        return [], 0
    # 统计 ## 插图 区块中的 fig 行数（单点实现 _count_figs，含重复块 fail-loud）
    fig_count = _count_figs(h2_titles, h2_indices, lines)
    return [], fig_count


def _parse_covered_by_for_book(cb_path: Path, textbook_id: str):
    """解析 covered_by.yaml 中 to 以 <textbook_id>-C 开头的条目，返回 [{conceptId, to}]。"""
    if not cb_path.is_file():
        return []
    entries = []
    current_from = None
    for line in cb_path.read_text(encoding='utf-8').splitlines():
        m_from = COVERED_BY_FROM_RE.match(line)
        if m_from:
            current_from = m_from.group(1)
            continue
        m_to = COVERED_BY_TO_RE.match(line)
        if m_to and current_from:
            to_val = m_to.group(1)
            if to_val.startswith(f'{textbook_id}-C'):
                entries.append({'conceptId': current_from, 'to': to_val})
            current_from = None
    return entries


def _load_concept_titles(root: Path, concept_ids: list) -> dict:
    """按概念 id 的学科段定位 concepts/<学科>.yaml，读取 title。返回 {conceptId: title}。"""
    data = _load_concept_data(root, concept_ids)
    return {cid: d['title'] for cid, d in data.items()}


def _load_concept_data(root: Path, concept_ids: list) -> dict:
    """加载概念的 title/aliases/explanation。返回 {conceptId: {title, aliases, explanation}}。
    aliases 为列表（解析不到则空列表），explanation 为字符串（解析不到则空串，支持多行续行拼接）。"""
    by_subject = {}
    for cid in concept_ids:
        parts = cid.split(':', 2)
        if len(parts) < 3:
            continue
        subject = parts[1]
        by_subject.setdefault(subject, []).append(cid)
    result = {}
    for subject, cids in by_subject.items():
        f = root / 'graph' / 'entities' / 'concepts' / f'{subject}.yaml'
        if not f.is_file():
            continue
        current_id = None
        current_obj: dict | None = None
        # 状态：None / 'aliases' / 'explanation' / 'other'
        field_state: str | None = None
        for line in f.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()

            # ---- 新实体 ----
            if stripped.startswith('- id: '):
                if current_id and current_id in cids and current_obj is not None:
                    result[current_id] = current_obj
                current_id = stripped[len('- id: '):].strip()
                current_obj = {'title': '', 'aliases': [], 'explanation': ''} if current_id in cids else None
                field_state = None
                continue
            if current_obj is None:
                continue

            # ---- 顶层字段（2 空格缩进，非列表项）----
            m_top = re.match(r'^  ([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$', line)
            if m_top:
                key = m_top.group(1)
                val = m_top.group(2).strip()
                if key == 'title':
                    current_obj['title'] = val
                    field_state = 'title'
                elif key == 'aliases':
                    if val == '':
                        # 空值 = 多行列表起始
                        field_state = 'aliases'
                    elif val.startswith('[') and val.endswith(']'):
                        # 内联数组
                        items = val[1:-1].split(',')
                        current_obj['aliases'] = [x.strip().strip('"\'') for x in items if x.strip()]
                        field_state = 'other'
                    else:
                        field_state = 'other'
                elif key == 'explanation':
                    current_obj['explanation'] = val
                    field_state = 'explanation'
                else:
                    field_state = 'other'
                continue

            # ---- 列表项（2 空格 + "- "）：仅 aliases 状态下消费 ----
            m_item = re.match(r'^  -\s+(.*)$', line)
            if m_item and field_state == 'aliases':
                current_obj['aliases'].append(m_item.group(1).strip())
                continue

            # ---- 续行（4+ 空格缩进）：仅 explanation 状态下消费 ----
            if re.match(r'^    \S', line) and field_state == 'explanation':
                if current_obj['explanation']:
                    current_obj['explanation'] += ' ' + stripped
                else:
                    current_obj['explanation'] = stripped
                continue

            # ---- 其他情况：复位状态 ----
            if stripped == '':
                continue  # 空行不改变状态
            field_state = 'other'

        # 文件尾保存
        if current_id and current_id in cids and current_obj is not None:
            result[current_id] = current_obj
    # 没找到的概念补默认值
    for cid in concept_ids:
        if cid not in result:
            result[cid] = {'title': '', 'aliases': [], 'explanation': ''}
    return result


DEMONSTRATES_FROM_RE = re.compile(r'^\s*-\s*from:\s*(fig:.+?)\s*$')
DEMONSTRATES_TO_RE = re.compile(r'^\s*to:\s*(concept:.+?)\s*$')


def _parse_demonstrates_for_book(dem_path: Path, textbook_id: str) -> dict:
    """解析 demonstrates.yaml 中 from 以 fig:<textbook_id>- 开头的条目。
    返回 {concept_id: [fig_id, ...]}。"""
    if not dem_path.is_file():
        return {}
    result: dict[str, list[str]] = {}
    current_from = None
    for line in dem_path.read_text(encoding='utf-8').splitlines():
        m_from = DEMONSTRATES_FROM_RE.match(line)
        if m_from:
            fig_id = m_from.group(1)
            # fig:BSDU-8-2-Math:... → 判断是否本书
            parts = fig_id.split(':', 2)
            if len(parts) >= 2 and parts[1] == textbook_id:
                current_from = fig_id
            else:
                current_from = None
            continue
        m_to = DEMONSTRATES_TO_RE.match(line)
        if m_to and current_from:
            concept_id = m_to.group(1)
            result.setdefault(concept_id, []).append(current_from)
            current_from = None
    return result


def compute_remappings(root: Path, book_dir: Path, ledger: dict) -> tuple:
    """计算 fig 搬运 + 概念重映射。返回 (conceptSectionMap, unmappedConcepts, figCarryover)。
    2026-09-27 刷题层移除：原 items 重桶（习题 E 块映射）与章命中率随之删除；
    词书/插图区块本体由 apply 侧 extract_*_blocks 原样搬运，不经台账重桶。"""
    textbook_id = ledger['textbookId']
    prose_dir = root / 'tools' / 'kg' / 'state' / 'ingest' / textbook_id / 'prose'

    # 收集全书 prose（按节 proseSource 分派：ocr→prose 文件，h2_block→章级 index.md 对应 H2 块，missing→空串）
    all_prose = {}
    for ch in ledger['chapters']:
        ch_short = ch['chapterId'].rsplit('-', 1)[-1]  # C<n>
        ch_index = book_dir / 'chapters' / ch_short / 'index.md'
        ch_raw = ch_index.read_text(encoding='utf-8') if ch_index.is_file() else ''
        for s in ch['sections']:
            s_key = f"{ch_short}-{s['sId']}"  # C<n>-S<m>
            source = s.get('proseSource', 'missing')
            if source == 'ocr':
                prose_file = prose_dir / f"{s_key}.md"
                all_prose[s_key] = prose_file.read_text(encoding='utf-8') if prose_file.is_file() else ''
            elif source == 'h2_block':
                all_prose[s_key] = _extract_h2_block_text(ch_raw, s['title'])
            else:
                all_prose[s_key] = ''

    # ---- fig 搬运统计（逐章；词书/插图区块本体由 apply 侧 extract_*_blocks 原样搬运） ----
    fig_carryover = []
    items_dir = book_dir / 'items'
    for ch in ledger['chapters']:
        ch_short = ch['chapterId'].rsplit('-', 1)[-1]  # C<n>
        new_secs_in_ch = [f"{ch_short}-{s['sId']}" for s in ch['sections']]
        last_sec_in_ch = new_secs_in_ch[-1] if new_secs_in_ch else ''

        # 收集该章旧节的 fig 数量（fig_old_sid 取第一个含插图的旧桶名）
        ch_fig_count = 0
        fig_old_sid = None
        if items_dir.is_dir():
            for item_file in sorted(items_dir.glob(f'{ch_short}-S*.md')):
                old_sid = item_file.stem  # C<n>-S<m>
                _, fig_count = _parse_items_blocks(
                    item_file,
                    allow_vocab=(ledger.get('subject') in ('英语', '语文')),
                )
                if fig_count > 0:
                    ch_fig_count += fig_count
                    if fig_old_sid is None:
                        fig_old_sid = old_sid

        # fig 搬运：旧 S1 同名新节优先，无则章末
        if ch_fig_count > 0 and new_secs_in_ch:
            old_s1_key = f'{ch_short}-S1'
            if fig_old_sid and fig_old_sid in new_secs_in_ch:
                carry_to = fig_old_sid
            elif old_s1_key in new_secs_in_ch:
                carry_to = old_s1_key
            else:
                carry_to = last_sec_in_ch
            fig_carryover.append({
                'chapter': ch_short,
                'carryToSection': carry_to,
                'figCount': ch_fig_count,
                'note': 'fig 重映射推迟 P2，插图区块原样搬运至旧 S1 同名新节',
            })

    # ---- 概念重映射 ----
    cb_path = root / 'graph' / 'relations' / 'covered_by.yaml'
    cb_entries = _parse_covered_by_for_book(cb_path, textbook_id)
    if cb_entries:
        concept_ids = [e['conceptId'] for e in cb_entries]
        concept_data = _load_concept_data(root, concept_ids)
        # demonstrates.yaml（fig 通路）
        dem_path = root / 'graph' / 'relations' / 'demonstrates.yaml'
        fig_map = _parse_demonstrates_for_book(dem_path, textbook_id)
        edges = [
            {'conceptId': e['conceptId'], 'title': concept_data.get(e['conceptId'], {}).get('title', ''), 'to': e['to']}
            for e in cb_entries
        ]
        concept_map = map_concepts(edges, all_prose, concept_data=concept_data, fig_map=fig_map)
    else:
        concept_map = {'mapped': {}, 'unmapped': []}

    unmapped_concepts = concept_map['unmapped']
    # conceptSectionMap: 概念 → {section: 新节完整id, evidence: 级名}
    # apply 用它改写 covered_by 的 to 与 concepts 的 sourceRef
    short_to_full = {}
    for ch in ledger['chapters']:
        ch_short = ch['chapterId'].rsplit('-', 1)[-1]
        for s in ch['sections']:
            short_to_full[f"{ch_short}-{s['sId']}"] = s['id']
    concept_section_map = {
        cid: {'section': short_to_full[entry['section']], 'evidence': entry['evidence']}
        for cid, entry in concept_map['mapped'].items()
        if entry['section'] in short_to_full
    }

    return concept_section_map, unmapped_concepts, fig_carryover


def resolve_book_offset(meta: dict) -> int:
    """书级 imageOffset。缺失即 SystemExit（imageOffset 缺失处置 裁决：不当 0 用）。

    显式 0 合法（前置页为 0 的书真实存在）。
    """
    off = meta.get('imageOffset')
    if off is None:
        raise SystemExit(
            f'{meta.get("textbookId") or meta.get("id") or "未知书"}: '
            'imageOffset 未标定（imageOffset 缺失处置），无法把教材页号换算成页图编号。'
            '请打开页图对照印刷页码与书页差值标定（如教材 p1 在页图第 6 张则 offset=5），不要按 0 处理。'
        )
    return int(off)


def load_pg_page_space(state_dir: Path, textbook_id: str) -> str:
    """PG pageRange 页空间声明（2026-09-15 P2 发现：PG 快照页空间逐书不一致——
    试点书 BSDU-8-2-Math=书页空间，BSDU-7-2-Math/ZTB-7-2-Geography=页图空间，
    已用页图印刷页码/节标题落点物理标定）。'page'=书页空间原样用；
    'image'=页图空间，先减 imageOffset 归一成书页再进台账。
    缺声明即 SystemExit——不许默认，每本书先做物理标定再显式声明。"""
    p = state_dir / 'page_space.json'
    if not p.is_file():
        raise SystemExit(
            f'缺 {p}：PG 页空间逐书不一致（2026-09-15 P2 实证），'
            '每本书须先按页图印刷页码标定后显式声明 "page" 或 "image"，不许默认。'
        )
    v = json.loads(p.read_text(encoding='utf-8')).get(textbook_id)
    if v not in ('page', 'image'):
        raise SystemExit(
            f'{p} 中 {textbook_id} 缺声明或值非法（{v!r}）：只接受 "page"（书页空间）或 "image"（页图空间，将减 offset 归一）。'
        )
    return v


def normalize_pg_ranges(chapters: list, offset: int) -> None:
    """页图空间 → 书页空间，原地归一：chapter/section 的 pageRange 各端减 offset。

    归一后出现非正页码即 fail-loud（书页从 1 起，负值说明声明或 offset 有误）。
    """
    for ch in chapters:
        pr = ch.get('pageRange')
        if pr:
            lo, hi = pr[0] - offset, pr[1] - offset
            if lo < 1 or hi < 1:
                raise SystemExit(
                    f'章 {ch.get("id")} 页域归一后出现非正页码 {pr}→[{lo},{hi}]：page_space 声明或 imageOffset 有误。'
                )
            ch['pageRange'] = [lo, hi]
        for s in ch.get('sections') or []:
            sr = s.get('pageRange')
            if sr:
                lo, hi = sr[0] - offset, sr[1] - offset
                if lo < 1 or hi < 1:
                    raise SystemExit(
                        f'节 {s.get("id")} 页域归一后出现非正页码 {sr}→[{lo},{hi}]：page_space 声明或 imageOffset 有误。'
                    )
                s['pageRange'] = [lo, hi]


def normalize_chapter_ids(book: dict, textbook_id: str) -> dict:
    """PG 非数字章后缀（TS/APP 等）→ 顺延数字章号 C<n>。返回 {pg_ch_id: new_ch_id}。
    图谱契约：章 id 必须为 C<n> 形态（load.ts 由书级 front-matter 派生 Chapter/Section）。
    2026-09-18 ZTB-7-2-Geography-TS/APP 首例暴露（book-frontmatter-schema lint error）。"""
    mapping: dict[str, str] = {}
    max_num = 0
    for ch in book.get('chapters', []):
        m = re.fullmatch(r'C(\d+)', ch['id'].rsplit('-', 1)[-1])
        if m:
            max_num = max(max_num, int(m.group(1)))
    next_num = max_num + 1
    for ch in book.get('chapters', []):
        suffix = ch['id'].rsplit('-', 1)[-1]
        if not re.fullmatch(r'C\d+', suffix):
            mapping[ch['id']] = f'{textbook_id}-C{next_num}'
            next_num += 1
    return mapping


def resolve_s_id(pg_section: dict, fm_sections: list) -> tuple:
    """PG 节 id → sId 后缀。非 S<n> 构词时（生产 UUID 脏数据，2026-09-15 7-2-Math 首现，
    每章「回顾与思考」类节），按归一标题在 knowledge 侧同章节列表内唯一匹配回填。
    返回 (sId, by_title_match)。匹配不到/多命中即 SystemExit（不发明 id）。"""
    s_id = pg_section['id'].rsplit('-', 1)[-1]
    if S_ID_RE.fullmatch(s_id):
        return s_id, False
    np_ = norm_title(pg_section.get('title', ''))
    cands = [s for s in (fm_sections or []) if np_ and norm_title(s.get('title', '')) == np_]
    if not cands and np_:
        # 字序颠倒容错：2026-09-15 实证 PG 7-2-Math C2「思考与回顾」vs 书页印刷「回顾与思考」
        # （image60 印刷页码核实，PG 侧笔误）——字符集唯一匹配才回填，多命中仍 fail-loud
        key = sorted(np_)
        cands = [s for s in (fm_sections or []) if sorted(norm_title(s.get('title', ''))) == key]
    if len(cands) != 1:
        raise SystemExit(
            f'PG 节 id 构词异常且标题无法唯一匹配：{pg_section.get("id")}「{pg_section.get("title")}」'
            f'（章内候选 {len(cands)} 个：{[c.get("id") for c in cands]}）。人工裁决后再跑。'
        )
    return cands[0]['id'], True


def load_snapshot(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f'PG 目录快照缺失：{path}（先生成 PG 目录快照 curriculum_toc.json（见 README 可选输入契约））')
    snap = json.loads(path.read_text(encoding='utf-8'))
    exported_at = snap['exportedAt']
    if exported_at.endswith('Z'):
        exported_at = exported_at[:-1] + '+00:00'
    age = datetime.now(timezone.utc) - datetime.fromisoformat(exported_at)
    if age > MAX_AGE:
        raise SystemExit(f'快照过期（exportedAt={snap["exportedAt"]}，>7 天）：重跑导出后再 propose')
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(description='重切 propose：逐节 action + idDiff → reoutline.json（不写盘内容）')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--textbook', required=True)
    ap.add_argument('--force', action='store_true', help='覆盖已存在的 reoutline.json')
    args = ap.parse_args()
    root = Path(args.root)

    snap = load_snapshot(SNAPSHOT)
    book = next((b for b in snap['books'] if b['id'] == args.textbook), None)
    if book is None:
        raise SystemExit(f'快照中无此书：{args.textbook}')

    book_dir = find_book_dir(root / 'content', args.textbook)
    fm = parse_frontmatter((book_dir / 'index.md').read_text(encoding='utf-8'), str(book_dir / 'index.md'))
    meta = read_book(book_dir)
    image_offset = resolve_book_offset(meta)
    pg_space = load_pg_page_space(root / 'tools' / 'kg' / 'state', args.textbook)
    if pg_space == 'image':
        normalize_pg_ranges(book['chapters'], image_offset)

    # OCR metadata 兜底目录（仅 level-2 条目；试点书为空）
    meta_path = source_dir() / args.textbook / 'metadata.json'
    meta_level2: dict = {}
    if meta_path.is_file():
        for t in json.loads(meta_path.read_text(encoding='utf-8')).get('toc', []):
            if isinstance(t, list) and len(t) >= 3 and t[0] == 2 and t[2] is not None:
                meta_level2[norm_title(str(t[1]))] = int(t[2])

    old_titles = {}
    for c in fm.get('chapters') or []:
        for s in c.get('sections') or []:
            old_titles[f"{args.textbook}-{c['id']}-{s['id']}"] = s.get('title', '')
    fm_chapters = {c['id']: c for c in fm.get('chapters') or []}

    chapters_out = []
    used_metadata_fallback = False
    uuid_matched = 0
    skipped_chapters = []
    ch_rename = normalize_chapter_ids(book, args.textbook)
    if ch_rename:
        print(f'[reoutline] PG 非数字章号归一化: {json.dumps(ch_rename, ensure_ascii=False)}')
    for ch0 in book['chapters']:
        ch = {**ch0, 'id': ch_rename.get(ch0['id'], ch0['id'])}
        if ch['id'] in ch_rename:
            pg_ch_id = ch0['id']
            ch['sections'] = [
                {**sec, 'id': ch['id'] + sec['id'][len(pg_ch_id):]} for sec in ch['sections']
            ]
        ch_dir = book_dir / 'chapters' / ch['id'].rsplit('-', 1)[-1]
        if not ch.get('sections'):
            # PG 0 节章（如 7-2-Math C7 综合与实践）：knowledge 无目录、门禁不管章级，跳过并留痕
            skipped_chapters.append(ch['id'])
            print(f'[reoutline] SKIP PG 章 {ch["id"]}（0 节，无对应目录）')
            continue
        if not ch_dir.is_dir():
            raise SystemExit(f'PG 章 {ch["id"]} 无对应目录：{ch_dir}（章目录按 C<n> 命名，人工裁决）')
        raw = (ch_dir / 'index.md').read_text(encoding='utf-8')
        h2s = [(i + 1, m.group(1)) for i, line in enumerate(raw.splitlines()) if (m := H2_RE.match(line))]
        fm_secs = (fm_chapters.get(ch['id'].rsplit('-', 1)[-1]) or {}).get('sections') or []
        secs_out = []
        for s in ch['sections']:
            s_id, by_match = resolve_s_id(s, fm_secs)
            if by_match:
                uuid_matched += 1
            source = decide_prose_source(s['title'], h2s, s.get('pageRange'), meta_level2)
            if source == 'ocr' and not s.get('pageRange'):
                used_metadata_fallback = True
            entry = {
                'id': s['id'], 'sId': s_id, 'title': s['title'], 'order': s['order'],
                'pageRange': s.get('pageRange'), 'proseSource': source,
            }
            if by_match:
                entry['sIdSource'] = 'title-match'
            secs_out.append(entry)
        chapters_out.append({
            'chapterId': ch['id'], 'dir': f'chapters/{ch["id"].rsplit("-", 1)[-1]}',
            'pgTitle': ch['title'], 'order': ch['order'], 'pageRange': ch.get('pageRange'),
            'imageOffset': image_offset, 'sections': secs_out,
        })

    new_titles = {s['id']: s['title'] for ch in chapters_out for s in ch['sections']}
    id_diff = compute_id_diff(old_titles, new_titles)

    # 强制人工确认条件（设计 §5.2；Task 9 会追加第三条：概念多命中/零命中）
    reasons = []
    if set(old_titles) != set(new_titles):
        reasons.append('节序与旧大纲不一致（idDiff 见台账）')
    if used_metadata_fallback:
        reasons.append('部分节目录回退到 OCR metadata 级')
    if any(s['proseSource'] == 'missing' for ch in chapters_out for s in ch['sections']):
        reasons.append('存在 missing 节（无页码无 metadata，需人工处理）')
    if uuid_matched:
        reasons.append(
            f'{uuid_matched} 节 PG id 为非标准构词（UUID 脏数据），sId 已按标题匹配回填；'
            '落库 sectionId 沿用 PG 原样 id（UUID）还是改写标准 S<n> 待人工裁决',
        )
    if skipped_chapters:
        reasons.append(f"PG 0 节章已跳过（无对应目录、门禁不管章级）：{', '.join(skipped_chapters)}")

    out = root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'reoutline.json'
    if out.exists() and not args.force:
        raise SystemExit(f'台账已存在（{out}），加 --force 覆盖')
    ledger = {
        'textbookId': args.textbook,
        'subject': fm.get('subject'),
        'contentDir': str(book_dir.relative_to(root)),
        'snapshotExportedAt': snap['exportedAt'],
        'pgPageSpace': pg_space,
        'chapters': chapters_out,
        'idDiff': id_diff,
        'confirmReasons': reasons,
        'confirmed': False,
    }

    # 映射计算（prose 存在才算，否则跳过并提示）
    prose_dir = root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'prose'
    if prose_dir.is_dir():
        concept_section_map, unmapped_concepts, fig_carryover = compute_remappings(
            root, book_dir, ledger,
        )
        ledger['conceptSectionMap'] = concept_section_map
        ledger['unmappedConcepts'] = unmapped_concepts
        ledger['figCarryover'] = fig_carryover
        if unmapped_concepts:
            ledger['confirmReasons'].append(
                f"概念重映射多命中/零命中 {len(unmapped_concepts)} 条（宁缺不猜，人工过台账）",
            )
        if fig_carryover:
            total_figs = sum(f['figCount'] for f in fig_carryover)
            print(f'ℹ fig 插图搬运：{len(fig_carryover)} 章共 {total_figs} 张（fig 重映射推迟 P2，原样搬运）')
    else:
        print('ℹ prose 草稿不存在，跳过映射计算——先跑 kg:reoutline:ocr 再重跑本命令')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'✅ 台账已写出：{out}')
    print(f'   idDiff: kept={len(id_diff["kept"])} replaced={len(id_diff["replaced"])} added={len(id_diff["added"])} dropped={len(id_diff["dropped"])}')
    for ch in chapters_out:
        n_ocr = sum(1 for s in ch['sections'] if s['proseSource'] == 'ocr')
        n_h2 = sum(1 for s in ch['sections'] if s['proseSource'] == 'h2_block')
        n_missing = sum(1 for s in ch['sections'] if s['proseSource'] == 'missing')
        print(f'   {ch["chapterId"]}: {len(ch["sections"])} 节（h2_block={n_h2} ocr={n_ocr} missing={n_missing}）')
    if reasons:
        print('\n⚠ 需人工确认（命中设计 §5.2 三条件）：')
        for r in reasons:
            print(f'  - {r}')
        print('  下一步：人工核对台账 → 跑 kg:reoutline:ocr → 重跑 propose（补映射）→ 台账置 confirmed: true')
        return 1
    print('\n下一步：跑 kg:reoutline:ocr → 重跑 propose（补映射）→ 台账置 confirmed: true → kg:reoutline:apply')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
