#!/usr/bin/env python3
"""outline.json 的唯一读写与校验入口（内容注入管线的中间台账）。

管线形状：

    md → book_propose.py → outline.json → [agent 填 chapters，人确认] → book_apply.py → content/

outline.json 是 LLM 判断的**落盘形态**：可 diff、可复核、可重放。沿用本仓 export/apply 两段式
（difficulty 打标的 labels.tsv、字符清洗规范（2026-08） 的候选清单）的同一范式。

fail-loud 纪律（CLAUDE.md §4.3）：任何形态不合法一律抛错，不做兜底修补。outline 写错的代价是
一本书结构错乱，而错得很像对的——宁可拒绝，不要猜。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CHAPTER_ID_RE = re.compile(r'^C\d+$')
SECTION_ID_RE = re.compile(r'^S\w+$')
EXT_PREFIX = 'EXT-'

# 书级 front-matter 的必填字段（与 lint rule 16 book-frontmatter-schema 对齐）
META_KEYS = ('title', 'grade', 'term', 'subject', 'publisher', 'origin', 'totalPages')


def outline_path(root: Path, textbook_id: str) -> Path:
    """outline.json 的约定位置：state/ingest/<textbookId>/outline.json。"""
    return root / 'tools' / 'kg' / 'state' / 'ingest' / textbook_id / 'outline.json'


def load_outline(path: Path) -> dict:
    """读 outline.json 并全量校验。校验不过即抛错。"""
    if not path.is_file():
        raise FileNotFoundError(f'{path} 不存在。先跑 book_propose.py 生成骨架')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: 顶层不是对象，实际 {type(data).__name__}')
    validate_outline(data, str(path))
    return data


def dump_outline(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def validate_outline(data: dict, where: str) -> None:
    """全量校验。propose 产出的骨架 chapters 为空，此时只校验 meta 部分。"""
    tb_id = data.get('textbookId')
    if not isinstance(tb_id, str) or not tb_id:
        raise ValueError(f'{where}: 缺 textbookId')

    meta = data.get('meta')
    if not isinstance(meta, dict):
        raise ValueError(f'{where}: 缺 meta 对象')
    for k in META_KEYS:
        if meta.get(k) in (None, ''):
            raise ValueError(f'{where}: meta.{k} 缺失')
    if meta['origin'] not in ('textbook', 'extension'):
        raise ValueError(f'{where}: meta.origin 必须是 textbook 或 extension，实际 {meta["origin"]!r}')

    # EXT- 前缀 ↔ origin 双向互锁（与 lint rule 15 extension-provenance 同一口径，
    # 在写盘前就拦住，而不是等 lint 事后报）
    prefixed = tb_id.startswith(EXT_PREFIX)
    is_ext = meta['origin'] == 'extension'
    if prefixed and not is_ext:
        raise ValueError(f'{where}: id 以 {EXT_PREFIX} 开头必须 origin: extension')
    if is_ext and not prefixed:
        raise ValueError(f'{where}: origin: extension 的 id 必须以 {EXT_PREFIX} 开头')
    if is_ext and not meta.get('source'):
        raise ValueError(f'{where}: 扩展知识必须填 meta.source（来源出处）')
    if not is_ext and meta.get('source'):
        raise ValueError(f'{where}: 原始教材不应有 meta.source')

    if not isinstance(data.get('sourceMd'), list) or not data['sourceMd']:
        raise ValueError(f'{where}: sourceMd 必须是非空数组')

    # contentDir 显式落在 outline 里而不是由 grade/term/subject 现算：既有库的学科目录名
    # 与 subject 字段并不一一对应（数学/Math、道德与法治/Politics 并存），现算必然猜错。
    cd = data.get('contentDir')
    if not isinstance(cd, str) or not cd.startswith('content/'):
        raise ValueError(f'{where}: contentDir 必须是以 content/ 开头的路径，实际 {cd!r}')
    if not cd.endswith('/' + tb_id):
        raise ValueError(f'{where}: contentDir 必须以 /{tb_id} 结尾，实际 {cd!r}')

    chapters = data.get('chapters')
    if not isinstance(chapters, list):
        raise ValueError(f'{where}: chapters 必须是数组')
    if chapters:
        _validate_chapters(chapters, where)


def _validate_chapters(chapters: list, where: str) -> None:
    seen_ids: set[str] = set()
    prev_to = 0
    for i, ch in enumerate(chapters, start=1):
        if not isinstance(ch, dict):
            raise ValueError(f'{where}: chapters[{i - 1}] 不是对象')
        cid = ch.get('id')
        if not isinstance(cid, str) or not CHAPTER_ID_RE.match(cid):
            raise ValueError(f'{where}: 章 id 必须是 C<n> 形态，实际 {cid!r}')
        if cid in seen_ids:
            raise ValueError(f'{where}: 章 id 重复 {cid}')
        seen_ids.add(cid)
        if not ch.get('title'):
            raise ValueError(f'{where}: {cid} 缺 title')
        if ch.get('order') != i:
            raise ValueError(f'{where}: {cid} 的 order 应为 {i}（须从 1 连续），实际 {ch.get("order")!r}')

        lo, hi = _line_span(ch, f'{where} {cid}')
        if lo <= prev_to:
            raise ValueError(f'{where}: {cid} 的 fromLine {lo} 与上一章区间重叠（上一章止于 {prev_to}）')
        prev_to = hi

        sections = ch.get('sections') or []
        if not isinstance(sections, list):
            raise ValueError(f'{where}: {cid}.sections 必须是数组')
        _validate_sections(sections, cid, lo, hi, where)


def _validate_sections(sections: list, cid: str, ch_lo: int, ch_hi: int, where: str) -> None:
    seen: set[str] = set()
    prev_to = ch_lo - 1
    for j, s in enumerate(sections, start=1):
        if not isinstance(s, dict):
            raise ValueError(f'{where}: {cid}.sections[{j - 1}] 不是对象')
        sid = s.get('id')
        if not isinstance(sid, str) or not SECTION_ID_RE.match(sid):
            raise ValueError(f'{where}: {cid} 下节 id 必须是 S<n> 形态，实际 {sid!r}')
        if sid in seen:
            raise ValueError(f'{where}: {cid} 下节 id 重复 {sid}')
        seen.add(sid)
        if not s.get('title'):
            raise ValueError(f'{where}: {cid}-{sid} 缺 title')
        if s.get('order') != j:
            raise ValueError(f'{where}: {cid}-{sid} 的 order 应为 {j}，实际 {s.get("order")!r}')

        lo, hi = _line_span(s, f'{where} {cid}-{sid}')
        if lo <= prev_to:
            raise ValueError(f'{where}: {cid}-{sid} 的 fromLine {lo} 与上一节区间重叠')
        if lo < ch_lo or hi > ch_hi:
            raise ValueError(
                f'{where}: {cid}-{sid} 的行区间 [{lo},{hi}] 超出所属章 [{ch_lo},{ch_hi}]'
            )
        prev_to = hi


def _line_span(node: dict, where: str) -> tuple[int, int]:
    """取 fromLine/toLine 并校验。这是 md 里的**行号**，只用于切片，
    与实体上的 pageRange（教材页号）严格区分，绝不互相冒充。"""
    lo, hi = node.get('fromLine'), node.get('toLine')
    if not isinstance(lo, int) or not isinstance(hi, int):
        raise ValueError(f'{where}: fromLine/toLine 必须是整数，实际 {lo!r}/{hi!r}')
    if lo < 1 or hi < lo:
        raise ValueError(f'{where}: 行区间不合法 [{lo},{hi}]')
    return lo, hi
