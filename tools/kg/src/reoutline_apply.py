#!/usr/bin/env python3
"""重切 apply：只认 confirmed 台账，全部确定性写盘、逐字节幂等。

写盘顺序固定（设计 §5.3）：章级 index.md 补齐 → sections 派生 → 书级 front-matter 重写
→ items（词书/插图区块搬运）→ YAML 行级重映射（covered_by/concepts）。
2026-09-27 刷题层移除：原 items 习题重桶、命中率闸门与 exercises/assesses/exemplifies 重写随之删除。

用法（在 knowledge 仓根）:
  pnpm kg:reoutline:apply -- --textbook BSDU-8-2-Math           # dry-run，只打印写盘清单
  pnpm kg:reoutline:apply -- --textbook BSDU-8-2-Math --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_frontmatter import parse_frontmatter  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]  # knowledge 仓根
GATE_THRESHOLD = 0.8


# ---- 工具：id 替换的严格正则（防 E1 吃 E11） ----
def replace_id_strict(text: str, old: str, new: str) -> str:
    """行级 id 替换，用 re.escape(old)+(?!\\d) 防止 E1 误匹配 E11。"""
    return re.sub(re.escape(old) + r'(?!\d)', new, text)


def _unmapped_ids(unmapped_concepts: list) -> set[str]:
    """归一化 unmapped_concepts 为 id 集合：元素为 dict 取 conceptId，str 直接用。"""
    ids = set()
    for item in unmapped_concepts:
        if isinstance(item, dict):
            if 'conceptId' in item:
                ids.add(item['conceptId'])
        elif isinstance(item, str):
            ids.add(item)
    return ids


# ---- front-matter 解析 ----
def split_fm_body(text: str) -> tuple[str, str]:
    """把 md 分成 front-matter 块（含 --- 包围）和 body。"""
    m = re.match(r'^---\n.*?\n---\n', text, re.S)
    if not m:
        return '', text
    return m.group(0), text[m.end():]


def strip_before_first_h2(body: str) -> str:
    """返回第一个 `^## ` 之前的全部内容（含 H1 和导语）。"""
    lines = body.split('\n')
    cut = len(lines)
    for i, line in enumerate(lines):
        if re.match(r'^##\s', line):
            cut = i
            break
    return '\n'.join(lines[:cut])


# ---- 章级 index.md 生成 ----
def render_chapter_index(
    chapter: dict,
    original_text: str,
    prose_by_sid: dict[str, str],
) -> str:
    """生成章级 index.md 全文。保留原 front-matter + 第一个 H2 之前内容，H2 起全部替换为台账节。"""
    fm, body = split_fm_body(original_text)
    preamble = strip_before_first_h2(body)
    preamble = preamble.rstrip('\n') + '\n\n'

    sections_md = []
    for s in chapter['sections']:
        prose = prose_by_sid.get(s['sId'], '')
        sections_md.append(f"## {s['title']}\n\n{prose.rstrip()}\n")
    return fm + preamble + '\n\n'.join(sections_md) + '\n'


# ---- 节级 sections/S<m>.md 生成 ----
def render_section_md(section: dict, chapter_dir_rel: str, prose: str) -> str:
    """节 md 渲染。frontmatter 附 sectionId/pageRange/derivedFrom（页图链接已移出 md，
    构建期由 load.ts 按 KG_PAGE_IMAGE_BASE_URL 派生，本函数不再产出任何 CDN 字串）。"""
    lines = [f'sectionId: {section["id"]}']
    if section.get('pageRange'):
        lo, hi = section['pageRange']
        lines.append(f'pageRange: [{lo}, {hi}]')
    lines.append(f'derivedFrom: {chapter_dir_rel}/index.md')
    fm = '---\n' + '\n'.join(lines) + '\n---\n'
    return f'{fm}\n# {section["title"]}\n\n{prose.rstrip()}\n'


# ---- items 文件生成 ----
def render_items_file(section_id: str) -> str:
    """生成空的 items/<sectionKey>.md 载体（仅 front-matter）。
    2026-09-27 刷题层移除：不再生成 ## 习题 段；
    词书/插图区块由调用方以 extract_illustration_blocks / extract_vocab_blocks 原样追加。"""
    return f'---\nsectionId: {section_id}\n---\n'


def extract_illustration_blocks(text: str) -> list[str]:
    """从 items md 文本中提取全部「## 插图」区块（含该行，直到文件尾/下一个 H2）。
    无插图区块则返回空列表。逐字节保真：返回的各区块文本与原文对应区间完全一致。
    多区块支持：apply 二次执行时目标节(S1)已并入多个来源的插图表，
    单区块提取会丢失第 2..N 块（2026-09-18 7-2-Math 二次 apply 幂等破坏暴露）。"""
    lines = text.split('\n')
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        if re.match(r'^##\s+插图\s*$', lines[i]):
            fig_start = i
            fig_end = len(lines)
            for j in range(fig_start + 1, len(lines)):
                if re.match(r'^##\s', lines[j]):
                    fig_end = j
                    break
            # 还原区块文本：去掉尾部空行（块间分隔由搬运时的 '\n' 统一补齐，
            # 否则二次执行时会把上一次的分隔空行吸进区块，破坏逐字节幂等）
            seg = lines[fig_start:fig_end]
            while seg and seg[-1] == '':
                seg.pop()
            blocks.append('\n'.join(seg))
            i = fig_end
        else:
            i += 1
    return blocks


def extract_vocab_blocks(text: str) -> list[str]:
    """提取全部「## 单词 / ## 短语 / ## 句子」区块（英语书 UNIT 级词汇表）。
    apply 重写 items 时原样搬运到同号新节（缺则章首节），防止词汇实体悬空
    （2026-09-18 8-1-English 247 条 word/phrase/sentence from 端点悬空暴露）。"""
    titles = {'单词', '短语', '句子', '汉字'}
    lines = text.split('\n')
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        m = re.match(r'^##\s+(.+?)\s*$', lines[i])
        if m and m.group(1).strip() in titles:
            start = i
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if re.match(r'^##\s', lines[j]):
                    end = j
                    break
            seg = lines[start:end]
            while seg and seg[-1] == '':
                seg.pop()
            blocks.append('\n'.join(seg))
            i = end
        else:
            i += 1
    return blocks


def extract_illustration_block(text: str) -> str:
    """单区块版（兼容保留）：返回第一个「## 插图」区块。"""
    blocks = extract_illustration_blocks(text)
    return blocks[0] if blocks else ''


# ---- 书级 front-matter 重写 ----
def rebuild_book_fm(original_fm: dict, ledger: dict) -> dict:
    """保留原 meta 键，新增 outlineSource: catalog-toc，重写 chapters 结构。"""
    out: dict = {}
    for k, v in original_fm.items():
        if k == 'chapters':
            continue
        out[k] = v
    out['outlineSource'] = 'catalog-toc'
    out['chapters'] = [_chapter_fm(ch) for ch in ledger['chapters']]
    return out


def _chapter_fm(ch: dict) -> dict:
    out: dict = {
        'id': ch['chapterId'].rsplit('-', 1)[-1],
        'title': ch['pgTitle'],
        'order': ch['order'],
    }
    if ch.get('pageRange'):
        out['pageRange'] = list(ch['pageRange'])
    sections = [_section_fm(s) for s in ch['sections']]
    if sections:
        out['sections'] = sections
    return out


def _section_fm(s: dict) -> dict:
    out: dict = {'id': s['sId'], 'title': s['title'], 'order': s['order']}
    if s.get('pageRange'):
        out['pageRange'] = list(s['pageRange'])
    return out


def render_book_index(original_text: str, ledger: dict, preserve_chapter_titles: bool = True,
                      skipped_chapter_ids: set[str] | None = None) -> str:
    """重写书级 index.md。preserve_chapter_titles=True 时章 title 保留原值。
    skipped_chapter_ids 中的章保持原 front-matter 不动。"""
    skipped = skipped_chapter_ids or set()
    omitted_chapter_ids: list[str] = []
    fm_text, body = split_fm_body(original_text)
    fm = parse_frontmatter(original_text, 'book_index')
    old_chapters = fm.get('chapters') or []
    old_title_by_id = {c.get('id'): c.get('title') for c in old_chapters if isinstance(c, dict)}
    old_by_id = {c.get('id'): c for c in old_chapters if isinstance(c, dict)}

    new_fm = rebuild_book_fm(fm, ledger)
    skipped_short = {cid.rsplit('-', 1)[-1] for cid in skipped}

    # 混合：未跳过 = 新值，跳过 = 原值
    mixed_chapters = []
    for ch in new_fm['chapters']:
        if ch['id'] in skipped_short:
            old_ch = old_by_id.get(ch['id'])
            if old_ch is None:
                # 跳过章且旧书级无此章（如英语 C11-C14 拓展阅读）：
                # 内容不会落盘，front-matter 不得收录，否则节文件悬空
                # （2026-09-18 PEP-7-1-English 26 条 sourceRef 悬空暴露）
                omitted_chapter_ids.append(ch['id'])
                continue
            mixed_chapters.append(old_ch)
        else:
            if preserve_chapter_titles and ch['id'] in old_title_by_id and old_title_by_id[ch['id']]:
                ch['title'] = old_title_by_id[ch['id']]
            mixed_chapters.append(ch)
    new_fm['chapters'] = mixed_chapters

    dumped = yaml.safe_dump(new_fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f'---\n{dumped}---\n' + body, omitted_chapter_ids


# ---- YAML 行级重映射 ----
def apply_covered_by_remap(text: str, section_id_pairs: list[tuple[str, str]],
                           concept_remap: dict, unmapped_concepts: list,
                           affected_section_ids: set[str] | None = None,
                           concept_to: dict[str, str] | None = None,
                           removed_section_ids: set[str] | None = None) -> tuple[str, int]:
    """covered_by.yaml 行级重写。
    - section_id_pairs: [(old_section_id, new_section_id)]  — 节 id 替换 to 值
    - concept_remap.mapped: {old_cid: new_cid} — 概念自身 id 变化替换 from 值
    - unmapped: 概念在且 to 在 affected_section_ids 中 → 整块两行删除
    - affected_section_ids: 受影响章的全部节 id 集合（用于判断 unmapped 概念是否删除）
    - concept_to: {cid: new_section_full_id} — 概念感知的 to 重写（优先于 section_id_pairs 与 unmapped 判断）
    返回 (新文本, 删除的块数)。
    """
    mapped_concepts = concept_remap.get('mapped', {})
    unmapped = set(concept_remap.get('unmapped', [])) | _unmapped_ids(unmapped_concepts)
    old_to_new_sec = dict(section_id_pairs)
    affected_old_secs = affected_section_ids if affected_section_ids is not None else set(old_to_new_sec.keys())
    removed_secs = removed_section_ids if removed_section_ids is not None else set()
    c_to = concept_to or {}

    lines = text.split('\n')
    out: list[str] = []
    deleted = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^- from: (concept:.+)$', line)
        if m and i + 1 < len(lines):
            cid = m.group(1)
            next_line = lines[i + 1]
            m2 = re.match(r'^(  to: )(.+)$', next_line)
            if m2:
                to_val = m2.group(2).strip()
                # 概念感知 to 重写（优先：mapped 概念绝不可能在 unmapped 集合中）
                if cid in c_to:
                    new_line = line
                    if cid in mapped_concepts:
                        new_line = f'- from: {mapped_concepts[cid]}'
                    new_to_line = m2.group(1) + c_to[cid]
                    out.append(new_line)
                    out.append(new_to_line)
                    i += 2
                    continue
                # to 指向已删除节（idDiff.dropped，PG 换血后无对应新节）→ 一律删除整块，
                # 概念转孤儿警告（积压口径）；保留必产生 to 悬空 error
                # （2026-09-18 PEP-7-2-Chinese C6 课外古诗词诵读首例暴露）
                if to_val in removed_secs:
                    deleted += 1
                    i += 2
                    continue
                # unmapped 且 to 是被替换的节 → 删除整块
                if cid in unmapped and to_val in affected_old_secs:
                    deleted += 1
                    i += 2
                    continue
                # 替换概念 id（from 行）
                new_line = line
                if cid in mapped_concepts:
                    new_line = f'- from: {mapped_concepts[cid]}'
                # 替换节 id（to 行）
                new_to_line = next_line
                if to_val in old_to_new_sec:
                    new_to_line = m2.group(1) + old_to_new_sec[to_val]
                out.append(new_line)
                out.append(new_to_line)
                i += 2
                continue
        out.append(line)
        i += 1
    return '\n'.join(out), deleted


def apply_concepts_source_remap(text: str, old_to_new_section_path: dict[str, str],
                                concept_ref: dict[str, str] | None = None) -> str:
    """concepts/<学科>.yaml：替换 sourceRef 的节路径。行级替换。
    - old_to_new_section_path: 全局节路径替换（原有行为）
    - concept_ref: {concept_id: new_sourceRef_path} — 概念感知的 sourceRef 重写（优先于全局路径替换）。
      行级扫描：遇到 `  id: <cid>` 后，下一行 `  sourceRef: ...` 替换为新路径。
    """
    c_ref = concept_ref or {}
    if not c_ref:
        # 退化到原行为
        result = text
        for old_path, new_path in old_to_new_section_path.items():
            result = replace_id_strict(result, old_path, new_path)
        return result

    lines = text.split('\n')
    out: list[str] = []
    pending_cid: str | None = None
    for line in lines:
        stripped = line.strip()
        # 识别实体 id 行（实体块起始）
        m_id = re.match(r'^\s*-\s*id:\s*(concept:.+?)\s*$', line)
        if m_id:
            pending_cid = m_id.group(1)
            out.append(line)
            continue
        # 识别 sourceRef 行（实体顶层，2 空格缩进；嵌套 4+ 空格不匹配，防 misconceptions 等嵌套字段误命中）
        m_sr = re.match(r'^(  sourceRef:\s*)(.+?)\s*$', line)
        if m_sr and pending_cid and pending_cid in c_ref:
            out.append(m_sr.group(1) + c_ref[pending_cid])
            pending_cid = None
            continue
        # 其他字段行或新实体 → 清除 pending
        if stripped.startswith('- id: '):
            pending_cid = None
        out.append(line)

    result = '\n'.join(out)
    # 全局路径替换作为兜底（处理未被 concept_ref 命中的概念）
    for old_path, new_path in old_to_new_section_path.items():
        result = replace_id_strict(result, old_path, new_path)
    return result


# ---- 学科文件定位 ----
def find_subject_yaml_files(root: Path, textbook_id: str, subject: str | None = None) -> dict[str, Path]:
    """定位学科的 concepts/<学科>.yaml 路径。
    策略：优先用台账 subject 字段；没有则从 concepts/ 下 grep textbookId 路径段定位。
    返回 {'concepts': Path}，文件不存在则缺键。
    （2026-09-27 刷题层移除：原 exercises/<学科>.yaml 定位随之删除。）"""
    result: dict[str, Path] = {}
    concepts_dir = root / 'graph' / 'entities' / 'concepts'

    if subject:
        c_path = concepts_dir / f'{subject}.yaml'
        if c_path.is_file():
            result['concepts'] = c_path
        return result

    # 回退：在 concepts/ 下 grep textbookId（sourceRef 路径段）定位学科文件
    if concepts_dir.is_dir():
        for f in sorted(concepts_dir.glob('*.yaml')):
            content = f.read_text(encoding='utf-8')
            if f'/{textbook_id}/chapters/' in content:
                result['concepts'] = f
                break
    return result


# ---- 后置复核 ----
def verify_written(root: Path, ledger: dict, skipped_chapter_ids: set[str],
                   omitted_chapter_ids: list[str] | None = None) -> None:
    """回读书级 index.md front-matter，断言结构与台账一致（跳过章逻辑保留兼容旧台账；
    omitted=跳过且旧书级无此章，front-matter 不收录，期望章数相应扣减）。"""
    p = root / ledger['contentDir'] / 'index.md'
    fm = parse_frontmatter(p.read_text(encoding='utf-8'), str(p))
    got_chapters = fm.get('chapters') or []
    # 1. 检查总章数是否匹配全部台账章（含跳过章，扣省略章）
    expected_count = len(ledger['chapters']) - len(omitted_chapter_ids or [])
    if len(got_chapters) != expected_count:
        raise SystemExit(f'后置复核失败: 章数 {len(got_chapters)} != 期望总章数 {expected_count}')

    # 建立台账章 id 映射
    want_chapter_by_id = {}
    for ch in ledger['chapters']:
        short_id = ch['chapterId'].rsplit('-', 1)[-1]
        want_chapter_by_id[short_id] = ch

    # 2. 按章 id 逐一对齐
    for got in got_chapters:
        got_id = got.get('id')
        if not got_id:
            raise SystemExit('后置复核失败: 章缺少 id 字段')
        if got_id not in want_chapter_by_id:
            raise SystemExit(f'后置复核失败: 未知章 id {got_id}')
        want_ch = want_chapter_by_id[got_id]

        # 3. 非跳过章：严格校验节数、节 id、节 title
        if want_ch['chapterId'] not in skipped_chapter_ids:
            got_secs = got.get('sections') or []
            want_secs = want_ch['sections']
            if len(got_secs) != len(want_secs):
                raise SystemExit(f'后置复核失败 {want_ch["chapterId"]}: 节数 {len(got_secs)} != {len(want_secs)}')
            for gs, ws in zip(got_secs, want_secs):
                if gs.get('id') != ws['sId']:
                    raise SystemExit(f'后置复核失败: 节 id {gs.get("id")} != 期望 {ws["sId"]}')
                if gs.get('title') != ws['title']:
                    raise SystemExit(f'后置复核失败: 节 title {gs.get("title")} != 期望 {ws["title"]}')
        # 4. 跳过章：只断言章存在且 sections 非空
        else:
            if 'sections' not in got or not got['sections']:
                raise SystemExit(f'后置复核失败: 跳过章 {want_ch["chapterId"]} 缺少 sections 或 sections 为空')


# ---- 计划计算（供 dry-run 与实写共用） ----
def plan_apply(root: Path, ledger: dict, render_only: bool = False) -> dict:
    """计算所有写盘/删除计划，不落盘。返回 {writes, deletes, skipped, warnings}。
    writes: list[(Path, str)] — 全部待写文件（路径相对 root，内容为目标字符串）
    deletes: list[Path] — 待删文件
    skipped: list[str] — 跳过的章 id（刷题层移除后恒为空，保留兼容旧台账）
    warnings: list[str] — 警告信息（如 unmapped 概念找不到）
    """
    if ledger.get('confirmed') is not True:
        raise SystemExit('台账未确认（confirmed != true）——propose 确认流程没走完')

    textbook_id = ledger['textbookId']
    content_dir = root / ledger['contentDir']
    prose_dir = root / 'tools' / 'kg' / 'state' / 'ingest' / textbook_id / 'prose'
    concept_remap = ledger.get('conceptRemap') or {'mapped': {}, 'unmapped': []}
    unmapped_concepts = ledger.get('unmappedConcepts') or []

    warnings: list[str] = []
    skipped: list[str] = []
    writes: list[tuple[Path, str]] = []
    deletes: list[Path] = []

    # 收集映射对（用于 graph YAML 重写）
    section_id_pairs: list[tuple[str, str]] = []  # (old_section_id, new_section_id)
    section_path_pairs: list[tuple[str, str]] = []  # (old_section_sourceRef_path, new)
    affected_section_ids: set[str] = set()  # 受影响章的全部节 id（用于 unmapped 概念删除判断）
    omitted_chapter_ids: list[str] = []  # 跳过且旧书级无此章：front-matter 不收录

    # 原书级 index.md 内容（用于重写 front-matter）
    book_index_path = content_dir / 'index.md'
    original_book_text = book_index_path.read_text(encoding='utf-8') if book_index_path.is_file() else ''

    for chapter in ledger['chapters']:
        ch_id = chapter['chapterId']
        ch_rel_dir = chapter['dir']
        ch_dir = content_dir / ch_rel_dir
        ch_index_path = ch_dir / 'index.md'
        ch_short_id = ch_id.rsplit('-', 1)[-1]

        # ---- 读 prose ----
        prose_by_sid = {}
        for s in chapter['sections']:
            prose_path = prose_dir / f'{ch_short_id}-{s["sId"]}.md'
            if prose_path.is_file():
                prose_by_sid[s['sId']] = prose_path.read_text(encoding='utf-8')
            else:
                prose_by_sid[s['sId']] = ''
                print(f'[reoutline] WARN {s["id"]} prose 缺失')

        # ---- 章级 index.md ----
        original_ch_text = ch_index_path.read_text(encoding='utf-8')
        new_ch_text = render_chapter_index(chapter, original_ch_text, prose_by_sid)
        writes.append((ch_index_path, new_ch_text))

        # ---- 节级 sections/S<m>.md ----
        for s in chapter['sections']:
            sec_path = ch_dir / 'sections' / f'{s["sId"]}.md'
            sec_md = render_section_md(s, f'{ledger["contentDir"]}/{ch_rel_dir}', prose_by_sid[s['sId']])
            writes.append((sec_path, sec_md))

            # 节 id 与路径映射（用于 graph YAML 重写）
            affected_section_ids.add(s['id'])
            # 节路径映射（sourceRef 用）——节短 id 不变时 old=new
            old_sec_path = f'{ledger["contentDir"]}/{ch_rel_dir}/sections/{s["sId"]}.md'
            section_path_pairs.append((old_sec_path, old_sec_path))

        # ---- items 文件 ----
        existing_items_files = set()
        if (content_dir / 'items').is_dir():
            for f in (content_dir / 'items').glob(f'{ch_short_id}-S*.md'):
                existing_items_files.add(f)

        # 收集旧文件中的插图表（逐字节原样；全部区块，排序保证跨次执行确定性）
        old_illustration_tables: list[tuple[str, str]] = []  # (旧文件名短键, 插图区块文本)
        for f in sorted(existing_items_files):
            old_text = f.read_text(encoding='utf-8')
            for fig_block in extract_illustration_blocks(old_text):
                old_key = f.stem  # e.g. "C1-S1"
                old_illustration_tables.append((old_key, fig_block))

        # 本章 figCarryover 目标（台账优先）
        fig_carryover_list = ledger.get('figCarryover') or []
        fig_carryover_target = None
        for fc in fig_carryover_list:
            if fc['chapter'] == ch_short_id:
                fig_carryover_target = fc['carryToSection']  # e.g. "C1-S1"
                break

        # 新节 sId 集合（用于回落匹配）
        new_sec_sids = {s['sId'] for s in chapter['sections']}

        new_items_files: set[Path] = set()
        # items 内容映射：仅承载词书/插图区块搬运（2026-09-27 刷题层移除，无习题 E 块）
        items_content_by_key: dict[str, str] = {}

        # 插图表搬运（逐字节原样追加，幂等）
        for old_key, fig_block in old_illustration_tables:
            # 目标节解析：台账 → 同名新节 → 最后一节
            target_key = None
            if fig_carryover_target:
                target_key = fig_carryover_target
            elif old_key in {f'{ch_short_id}-{sid}' for sid in new_sec_sids}:
                target_key = old_key
            elif chapter['sections']:
                target_key = f'{ch_short_id}-{chapter["sections"][-1]["sId"]}'
            else:
                raise SystemExit(
                    f'{textbook_id}/{ch_short_id}: 旧 items {old_key} 有插图表但本章无任何新节可归属',
                )

            if target_key not in items_content_by_key:
                # 目标节没有 items 文件（无 E 块）→ 建一个空 items 文件承载插图表
                # 找对应 section id
                target_sid = target_key[len(ch_short_id) + 1:]  # strip "C1-"
                target_sec = next((s for s in chapter['sections'] if s['sId'] == target_sid), None)
                if target_sec is None:
                    raise SystemExit(
                        f'{textbook_id}/{ch_short_id}: 插图目标节 {target_key} 不在本章新节列表中',
                    )
                items_content_by_key[target_key] = render_items_file(target_sec['id'])
                items_path = content_dir / 'items' / f'{target_key}.md'
                new_items_files.add(items_path)

            # 幂等：已含则不追加；追加统一 '\n' 前后缀（区块自身已去尾部空行），
            # 保证二次执行提取-再追加逐字节一致
            if fig_block not in items_content_by_key[target_key]:
                items_content_by_key[target_key] = items_content_by_key[target_key] + '\n' + fig_block + '\n'

        # 词汇区块搬运（英语书）：旧文件 UNIT 级表 → 同号新节，缺则章首节
        for f in sorted(existing_items_files):
            vb = extract_vocab_blocks(f.read_text(encoding='utf-8'))
            if not vb:
                continue
            old_key = f.stem
            same = old_key if old_key in {f'{ch_short_id}-{sid}' for sid in new_sec_sids} else None
            target_key = same or (f"{ch_short_id}-{chapter['sections'][0]['sId']}" if chapter['sections'] else None)
            if target_key is None:
                continue
            if target_key not in items_content_by_key:
                target_sid = target_key[len(ch_short_id) + 1:]
                target_sec = next((x for x in chapter['sections'] if x['sId'] == target_sid), None)
                if target_sec is None:
                    continue
                items_content_by_key[target_key] = render_items_file(target_sec['id'])
                new_items_files.add(content_dir / 'items' / f'{target_key}.md')
            for blk in vb:
                if blk not in items_content_by_key[target_key]:
                    items_content_by_key[target_key] = items_content_by_key[target_key] + '\n' + blk + '\n'

        # 写入 items 文件
        for key, content in items_content_by_key.items():
            items_path = content_dir / 'items' / f'{key}.md'
            writes.append((items_path, content))

        # 删除旧 items 文件
        for f in existing_items_files:
            if f not in new_items_files:
                deletes.append(f)

    # ---- 书级 front-matter 重写 ----
    if original_book_text:
        new_book_text, omitted_chapter_ids = render_book_index(
            original_book_text, ledger,
            preserve_chapter_titles=True,
            skipped_chapter_ids=set(skipped),
        )
        writes.append((book_index_path, new_book_text))

    # ---- 概念重映射（conceptSectionMap）构建 concept_to 与 concept_ref ----
    concept_section_map = ledger.get('conceptSectionMap') or {}
    concept_to: dict[str, str] = {}
    concept_ref: dict[str, str] = {}
    if concept_section_map:
        # 构建 节完整id → 节sourceRef路径 的映射（用于 concept_ref）
        sec_id_to_path: dict[str, str] = {}
        for chapter in ledger['chapters']:
            ch_rel_dir = chapter['dir']
            for s in chapter['sections']:
                sec_id_to_path[s['id']] = f"{ledger['contentDir']}/{ch_rel_dir}/sections/{s['sId']}.md"
        # gate 跳过章的节文件不会落盘，概念 sourceRef 不得指向它们
        # （2026-09-18 PEP-7-1-English C11-C14 跳过后 98 条 sourceRef 悬空暴露）
        skipped_sec_prefixes = tuple(f'{cid}-S' for cid in skipped)
        for cid, entry in concept_section_map.items():
            # 兼容新旧格式：entry 可能是 dict（新）或 str（旧）
            if isinstance(entry, dict):
                sec_full = entry.get('section', '')
            else:
                sec_full = entry
            if not sec_full:
                continue
            if sec_full.startswith(skipped_sec_prefixes):
                continue
            concept_to[cid] = sec_full
            if sec_full in sec_id_to_path:
                concept_ref[cid] = sec_id_to_path[sec_full]

    # ---- graph YAML 行级重映射 ----
    # render_only：已 apply 过的书仅需重渲染 md（如注入 pageImages）时，
    # 跳过图谱 YAML 重写——台账与图谱本就一致，不触碰。
    graph_dir = root / 'graph'
    if graph_dir.is_dir() and not render_only:
        # 学科文件定位
        subject = ledger.get('subject')
        yaml_paths = find_subject_yaml_files(root, textbook_id, subject)

        # covered_by.yaml
        covered_by_path = graph_dir / 'relations' / 'covered_by.yaml'
        if covered_by_path.is_file():
            original = covered_by_path.read_text(encoding='utf-8')
            new_text, deleted = apply_covered_by_remap(
                original, section_id_pairs, concept_remap, unmapped_concepts,
                affected_section_ids=affected_section_ids,
                concept_to=concept_to if concept_to else None,
                removed_section_ids=set(ledger.get('idDiff', {}).get('dropped', [])),
            )
            writes.append((covered_by_path, new_text))

        # concepts/<学科>.yaml
        if 'concepts' in yaml_paths:
            cp = yaml_paths['concepts']
            original = cp.read_text(encoding='utf-8')
            old_to_new_path = {old: new for old, new in section_path_pairs if old != new}
            new_text = apply_concepts_source_remap(
                original, old_to_new_path,
                concept_ref=concept_ref if concept_ref else None,
            )
            writes.append((cp, new_text))

    return {
        'writes': writes,
        'deletes': deletes,
        'skipped': skipped,
        'warnings': warnings,
        'omitted_chapters': omitted_chapter_ids,
    }


# ---- 主入口 ----
def apply_ledger(root: Path, ledger: dict, apply: bool = False,
                 render_only: bool = False) -> list[str]:
    """核心函数。apply=True 时真实写盘，apply=False（默认）时只计算不落盘（dry-run 范式）。
    render_only：跳过图谱 YAML 重写，仅重渲染 md。
    返回跳过的章 id 列表（刷题层移除后恒为空）。
    """
    plan = plan_apply(root, ledger, render_only=render_only)
    skipped = plan['skipped']

    if not apply:
        return skipped

    # ---- 写盘 ----
    for p, content in plan['writes']:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')

    for p in plan['deletes']:
        if p.exists():
            p.unlink()

    # ---- 后置复核 ----
    book_index_path = root / ledger['contentDir'] / 'index.md'
    if book_index_path.is_file():
        verify_written(root, ledger, set(skipped), plan.get('omitted_chapters'))

    return skipped


def main() -> int:
    ap = argparse.ArgumentParser(description='重切 apply：confirmed 台账 → 确定性写盘')
    ap.add_argument('--root', default=str(ROOT))
    ap.add_argument('--textbook', required=True)
    ap.add_argument('--apply', action='store_true', help='真实写盘（默认 dry-run 只打印计划）')
    ap.add_argument('--render-only', action='store_true',
                    help='仅重渲染章节/节 md（不动图谱 YAML 与锚点闸门），用于注入 frontmatter 类变更')
    args = ap.parse_args()
    root = Path(args.root)

    ledger_path = root / 'tools' / 'kg' / 'state' / 'ingest' / args.textbook / 'reoutline.json'
    if not ledger_path.is_file():
        raise SystemExit(f'台账不存在：{ledger_path}')
    ledger = json.loads(ledger_path.read_text(encoding='utf-8'))

    if ledger.get('confirmed') is not True:
        raise SystemExit('台账未确认（confirmed != true）——propose 确认流程没走完')

    plan = plan_apply(root, ledger, render_only=args.render_only)

    # 打印完整计划
    prefix = '[dry-run] ' if not args.apply else ''
    print(f'{prefix}写盘清单（{len(plan["writes"])} 个文件）：')
    for p, _ in plan['writes']:
        print(f'  {prefix}{p.relative_to(root)}')

    if plan['deletes']:
        print(f'\n{prefix}将删除的文件（{len(plan["deletes"])} 个）：')
        for p in plan['deletes']:
            print(f'  {prefix}{p.relative_to(root)}')

    if plan['skipped']:
        print(f'\n{prefix}被闸门跳过的章（{len(plan["skipped"])}）：')
        for cid in plan['skipped']:
            print(f'  {prefix}{cid}')

    if plan['warnings']:
        print(f'\n{prefix}警告（{len(plan["warnings"])}）：')
        for w in plan['warnings']:
            print(f'  {prefix}{w}')

    id_diff = ledger.get('idDiff', {})
    print(f'\n{prefix}idDiff: kept={len(id_diff.get("kept", []))} '
          f'replaced={len(id_diff.get("replaced", []))} '
          f'added={len(id_diff.get("added", []))} '
          f'dropped={len(id_diff.get("dropped", []))}')

    if not args.apply:
        print(f'\n[dry-run] 共 {len(plan["writes"])} 写 / {len(plan["deletes"])} 删，未写盘。加 --apply 执行。')
        return 0

    # 真实写盘
    for p, content in plan['writes']:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')

    for p in plan['deletes']:
        if p.exists():
            p.unlink()

    # 后置复核
    book_index_path = root / ledger['contentDir'] / 'index.md'
    if book_index_path.is_file():
        verify_written(root, ledger, set(plan['skipped']), plan.get('omitted_chapters'))

    print(f'\n✅ apply 完成（{len(plan["writes"])} 写 / {len(plan["deletes"])} 删）')
    if plan['skipped']:
        print(f'  被闸门跳过的章（{len(plan["skipped"])}）：{plan["skipped"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
