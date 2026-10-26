#!/usr/bin/env python3
"""
从 content sections 抽取 Concept / Items / covered_by（LLM）——内容注入管线的第 ③ 步。

**本脚本不写图谱。** 它只产 `state/ingest/<textbookId>/extract/<sectionId>.json`，
形状即 ingest.ts 的 `ExtractResult`；写盘由第 ④ 步 `pnpm kg:ingest --textbook <id>` 负责。

这样分工的原因（见 spec「决策 2」）：ingest.ts 的 `writeExtract()` 已经是完全正确的 v3 写侧
（概念按学科聚合、items 渲染成 md、习题正文进锚点而标注进 graph 存根），而本脚本原先那套
write_concept / write_items / append_relation 是同一件事的第二份实现、且停留在 v2 形状
（每概念一个文件、items 写 YAML dict），load.ts 已经拒绝加载。与其迁移，不如删掉，
让 python 只当 LLM 调用方、TS 当唯一写盘方。

幂等：已有同 title 概念复用；extract JSON 已存在则跳过（--force 覆盖）。

用法:
  python llm_extract_graph.py knowledge/content/八年级/上册/数学/BSDU-8-1-Math/chapters/C2
  python llm_extract_graph.py knowledge/content/八年级/上册 --batch
  python llm_extract_graph.py ... --force --sleep 0.2
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml
from openai import OpenAI

REPO = Path(__file__).resolve().parents[4]
KNOWLEDGE = REPO / 'knowledge'

JUNK_TITLES = {
    '例题', '随堂练习', '知识技能', '数学理解', '问题解决', '联系拓广',
    '思考·交流', '尝试·思考', '阅读·思考', '回顾与思考', '回顾·反思',
    '练习与应用', '实践与练习', '活动', '讨论', '试一试', '想一想',
    '做一做', '议一议', '读一读', '材料研读', '相关史事', '人物扫描',
    # 小学栏目（P1.2，2026-10-01 按小学节标题频次统计）
    '练一练', '活动园', '研讨', '探索', '聚焦', '拓展', '阅读角', '日积月累', '巩固与应用',
    '课后题', '课后练习', '相关链接', '词句段运用', '字词句运用', '我的收获', '识字加油站',
    '整理与复习', '语文园地', '梳理与交流', '回顾与交流', '识字', '练习', '写一写', '书写提示',
    '单元小结', '阅读链接', '资料', '交流平台', '快乐读书吧', '口语交际', '习作',
}

SYSTEM = """你是初中教材知识图谱抽取助手。根据给定课文节选，抽取知识点与学习项。

规则：
1. concepts：真正的知识点（定义/定理/法则/核心史实/语法点等），不要栏目名（例题、随堂练习、知识技能等）。
2. 每个 concept 含 title（中文）、category、explanation（1-2句）、aliases（可空数组）。
3. coveredSection：布尔，本节是否讲授该概念（用于 covered_by）。
4. prerequisites：可选，本节概念依赖的其它概念 title 列表（仅明显前置）。
5. items 按学科：
   - 英语：words[{word,ipa,pos,meaning}]、phrases[{en,cn}]、sentences[{english:词数组,cn}]
   - 语文：characters[{char,pinyin,definition,example}]
   - 图注不建实体（content v4：插图区块降级为纯文本图注，随正文走）
6. 只输出 JSON：
{"concepts":[{"title":"","category":"","explanation":"","aliases":[],"covered":true,"prerequisites":[]}],"words":[],"phrases":[],"sentences":[],"characters":[]}
"""


def load_dotenv_keys() -> None:
    for path in (Path(__file__).resolve().parents[3] / '.env', Path.cwd() / '.env'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def make_client() -> tuple[OpenAI, str]:
    """凭据统一走 AI_*（任意 OpenAI 兼容服务）：AI_BASE_URL 缺省=OpenAI 官方端点，AI_MODEL 必填。"""
    load_dotenv_keys()
    if not os.environ.get('AI_API_KEY'):
        raise SystemExit('缺少 AI_API_KEY（另可配 AI_BASE_URL 指向兼容服务端点、AI_MODEL 指定模型）')
    if not os.environ.get('AI_MODEL'):
        raise SystemExit('缺少 AI_MODEL')
    return (
        OpenAI(
            api_key=os.environ['AI_API_KEY'],
            base_url=os.environ.get('AI_BASE_URL') or None,
        ),
        os.environ['AI_MODEL'],
    )
def _reasoning_kw(model: str) -> dict:
    """DeepSeek v4 推理开关：默认关闭推理以省 token/提速。

    由 .env 的 AI_REASONING_EFFORT 控制：
      none            -> 关闭推理（默认，抽取/润色无需推理）
      low/medium/high -> 开启对应强度推理
    仅对 deepseek-v4* 模型生效，旧 deepseek-chat 不受影响。
    """
    eff = os.environ.get('AI_REASONING_EFFORT')
    if eff:
        return {'reasoning_effort': eff}
    return {}


def parse_fm(text: str) -> tuple[dict, str]:
    if not text.startswith('---'):
        return {}, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    return fm, parts[2].lstrip('\n')


def subject_from_path(path: Path) -> tuple[str, str, str, str]:
    """返回 grade, term, subject, textbookId"""
    parts = path.parts
    i = parts.index('content')
    grade, term, subject, textbook = parts[i + 1 : i + 5]
    return grade, term, subject, textbook


def load_existing_concepts(subject: str) -> dict[str, str]:
    """title -> id（只认标题，别名不参与复用：同学科泛称别名会把小学概念误并进初中概念，门 C 第 1 轮）。"""
    f = KNOWLEDGE / 'graph' / 'entities' / 'concepts' / f'{subject}.yaml'
    mapping: dict[str, str] = {}
    if not f.is_file():
        return mapping
    data = yaml.safe_load(f.read_text(encoding='utf-8')) or []
    if not isinstance(data, list):
        raise ValueError(f'{f}: 概念聚合文件应是裸 YAML list，实际 {type(data).__name__}')
    for item in data:
        if not isinstance(item, dict):
            continue
        title = (item.get('title') or '').strip()
        cid = item.get('id')
        if title and cid:
            mapping[title] = cid
    return mapping


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '-', s)
    return s.strip('-')[:40] or 'item'


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        m = re.search(r'\{[\s\S]*\}', fixed)
        if not m:
            raise
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', m.group(0)))


def _split_body_chunks(body: str, max_chars: int = 5500) -> list[str]:
    """按页注释或长度切块，避免整章 pack 只抽前 6k 字。"""
    body = body.strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]
    parts = re.split(r'(?=<!--\s*page\s+\d+\s*-->)', body)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        # 无页标记：硬切
        return [body[i : i + max_chars] for i in range(0, len(body), max_chars)]
    chunks: list[str] = []
    buf = ''
    for p in parts:
        if buf and len(buf) + len(p) + 1 > max_chars:
            chunks.append(buf)
            buf = p
        else:
            buf = f'{buf}\n{p}'.strip() if buf else p
    if buf:
        chunks.append(buf)
    # 单页仍超长则再切
    out: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            out.append(c)
        else:
            out.extend(c[i : i + max_chars] for i in range(0, len(c), max_chars))
    return out


def _merge_extract(parts: list[dict]) -> dict:
    merged = {
        'concepts': [],
        'words': [],
        'phrases': [],
        'sentences': [],
        'characters': [],
    }
    seen_c: set[str] = set()
    seen_w: set[str] = set()
    seen_p: set[str] = set()
    seen_s: set[str] = set()
    seen_ch: set[str] = set()
    for data in parts:
        for c in data.get('concepts') or []:
            if not isinstance(c, dict):
                continue
            t = (c.get('title') or '').strip()
            if not t or t in seen_c:
                continue
            seen_c.add(t)
            merged['concepts'].append(c)
        for w in data.get('words') or []:
            if not isinstance(w, dict):
                continue
            k = (w.get('word') or '').strip().lower()
            if not k or k in seen_w:
                continue
            seen_w.add(k)
            merged['words'].append(w)
        for p in data.get('phrases') or []:
            if not isinstance(p, dict):
                continue
            k = (p.get('en') or '').strip().lower()
            if not k or k in seen_p:
                continue
            seen_p.add(k)
            merged['phrases'].append(p)
        for s in data.get('sentences') or []:
            if not isinstance(s, dict):
                continue
            eng = s.get('english')
            k = ' '.join(eng) if isinstance(eng, list) else str(eng or '')
            k = k.strip().lower()
            if not k or k in seen_s:
                continue
            seen_s.add(k)
            merged['sentences'].append(s)
        for ch in data.get('characters') or []:
            if not isinstance(ch, dict):
                continue
            k = (ch.get('char') or '').strip()
            if not k or k in seen_ch:
                continue
            seen_ch.add(k)
            merged['characters'].append(ch)
    return merged


def call_extract(client: OpenAI, model: str, *, subject: str, section_id: str, body: str) -> dict:
    chunks = _split_body_chunks(body)
    if not chunks:
        return {}
    parts: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        suffix = f'（块 {i}/{len(chunks)}）' if len(chunks) > 1 else ''
        user = f'学科：{subject}\nsectionId：{section_id}{suffix}\n\n课文：\n{chunk}'
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': user},
            ],
            response_format={'type': 'json_object'},
            **_reasoning_kw(model),
        )
        parts.append(extract_json(resp.choices[0].message.content or '{}'))
    return _merge_extract(parts) if len(parts) > 1 else parts[0]


def build_concept(subject: str, concept: dict, source_ref: str, existing: dict[str, str]) -> tuple[str, dict | None]:
    """返回 (概念 id, 新建的实体 dict 或 None)。已存在同 title 则复用，不产新实体。

    **不写盘。** 写盘统一由 ingest.ts 的 writeExtract 负责——本脚本只当 extract JSON 的生产者。
    """
    title = (concept.get('title') or '').strip()
    if not title or title in JUNK_TITLES or len(title) < 2:
        return '', None
    if title in existing:
        return existing[title], None
    cid = f'concept:{subject}:{title}'
    existing[title] = cid
    return cid, {
        'id': cid,
        'type': 'Concept',
        'subject': subject,
        'title': title,
        'aliases': concept.get('aliases') or [],
        'category': concept.get('category') or '核心概念',
        'explanation': (concept.get('explanation') or '').strip(),
        'sourceRef': source_ref,
    }


def build_items(
    *,
    textbook: str,
    section_id: str,
    source_ref: str,
    data: dict,
    item_seen: dict[str, set[str]] | None = None,
) -> list[dict]:
    """把 LLM 返回的五类学习项归一为实体 list。**不写盘**（v3 起 items 是 md，由 writeExtract 渲染）。"""
    unit = re.search(r'-C(\d+)', section_id)
    unit_n = unit.group(1) if unit else '1'

    # 跨节去重：同一 textbook 下 word/phrase/sentence 只在首次出现节写入，避免 ID 冲突
    seen: set[str] = item_seen.setdefault(textbook, set()) if item_seen is not None else set()

    def dedupe(items: list[dict]) -> list[dict]:
        out_items: list[dict] = []
        for it in items:
            iid = it.get('id')
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out_items.append(it)
        return out_items

    words = []
    for w in data.get('words') or []:
        if not isinstance(w, dict) or not w.get('word'):
            continue
        word = str(w['word'])
        words.append(
            {
                'id': f'word:{textbook}:U{unit_n}:{slugify(word)}',
                'type': 'Word',
                'word': word,
                'ipa': w.get('ipa') or '',
                'pos': w.get('pos') or '',
                'meaning': w.get('meaning') or '',
                'sourceRef': source_ref,
            }
        )
    words = dedupe(words)

    phrases = []
    for p in data.get('phrases') or []:
        if not isinstance(p, dict) or not p.get('en'):
            continue
        en = str(p['en'])
        phrases.append(
            {
                'id': f'phrase:{textbook}:U{unit_n}:{slugify(en)}',
                'type': 'Phrase',
                'en': en,
                'cn': p.get('cn') or '',
                'sourceRef': source_ref,
            }
        )
    phrases = dedupe(phrases)

    sentences = []
    for i, s in enumerate(data.get('sentences') or [], 1):
        if not isinstance(s, dict):
            continue
        eng = s.get('english')
        if isinstance(eng, str):
            eng = eng.split()
        if not isinstance(eng, list) or not eng:
            continue
        eng = [str(x) for x in eng]
        # YAML boolean 保留词加引号由 yaml dump 处理；此处确保是字符串
        sentences.append(
            {
                'id': f'sentence:{textbook}:U{unit_n}:s{i}',
                'type': 'Sentence',
                'english': eng,
                'cn': s.get('cn') or '',
                'sourceRef': source_ref,
            }
        )
    sentences = dedupe(sentences)

    characters = []
    for ch in data.get('characters') or []:
        if not isinstance(ch, dict) or not ch.get('char'):
            continue
        c = str(ch['char'])
        characters.append(
            {
                'id': f'character:{textbook}:{section_id}:{c}',
                'type': 'Character',
                'char': c,
                'pinyin': ch.get('pinyin') or '',
                'definition': ch.get('definition') or '',
                'example': ch.get('example') or '',
                'sourceRef': source_ref,
            }
        )
    # 同节去重
    seen_c: set[str] = set()
    uniq_chars = []
    for ch in characters:
        if ch['char'] in seen_c:
            continue
        seen_c.add(ch['char'])
        uniq_chars.append(ch)
    characters = uniq_chars

    # 图注不再建 Figure 实体（content v4：插图区块降级为纯文本图注，随正文走）

    return [*words, *phrases, *sentences, *characters]


def process_section(
    path: Path,
    *,
    client: OpenAI,
    model: str,
    sleep_s: float,
    concept_cache: dict[str, dict[str, str]],
    item_seen: dict[str, set[str]] | None = None,
    write_prereq: bool = False,
    from_raw: bool = False,
) -> dict:
    _grade, _term, subject, textbook = subject_from_path(path)
    text = path.read_text(encoding='utf-8')
    fm, body = parse_fm(text)
    section_id = resolve_section_id(path, fm, textbook)
    if not section_id:
        return {'status': 'skip', 'reason': 'no sectionId'}

    try:
        source_ref = str(path.relative_to(KNOWLEDGE))
    except ValueError:
        source_ref = str(path)

    if subject not in concept_cache:
        concept_cache[subject] = load_existing_concepts(subject)

    print(f'  → {section_id}', flush=True)
    data = (load_raw(textbook, section_id) if from_raw
            else call_extract(client, model, subject=subject, section_id=section_id, body=body))

    relations: list[dict] = []
    concepts: list[dict] = []
    title_to_id = concept_cache[subject]

    for c in data.get('concepts') or []:
        if not isinstance(c, dict):
            continue
        # 顺带提到（covered=false）的不建实体、不连边：新概念没有 covered_by 就是孤儿
        if not c.get('covered', True):
            continue
        cid, entity = build_concept(subject, c, source_ref, title_to_id)
        if not cid:
            continue
        if entity is not None:
            concepts.append(entity)
        relations.append({'type': 'covered_by', 'from': cid, 'to': section_id})
        if write_prereq:
            for pre in c.get('prerequisites') or []:
                if not isinstance(pre, str) or not pre.strip():
                    continue
                pid = title_to_id.get(pre.strip())
                if pid and pid != cid:
                    relations.append({'type': 'prerequisite', 'from': cid, 'to': pid})

    items = [] if from_raw else build_items(
        textbook=textbook,
        section_id=section_id,
        source_ref=source_ref,
        data=data,
        item_seen=item_seen,
    )
    if sleep_s and not from_raw:
        time.sleep(sleep_s)
    # 形状即 ingest.ts 的 ExtractResult。prose 留空——正文已在 content 的 section md 里，
    # writeExtract 只在目标 md 不存在时才用 prose 建档，重抽既有节不该覆盖正文。
    return {
        'status': 'ok',
        'sectionId': section_id,
        'pageRange': fm.get('pageRange'),
        'prose': '',
        'concepts': concepts,
        'items': items,
        'relations': relations,
    }


def collect_sections(root: Path) -> list[Path]:
    if root.is_file() and root.name.endswith('.md') and 'sections' in root.parts:
        return [root]
    if (root / 'sections').is_dir():
        return sorted((root / 'sections').glob('S*.md'))
    return sorted(root.rglob('chapters/*/sections/S*.md'))


def extract_dir(textbook_id: str) -> Path:
    """extract JSON 的约定位置：state/ingest/<textbookId>/extract/。"""
    return KNOWLEDGE / 'tools' / 'kg' / 'state' / 'ingest' / textbook_id / 'extract'


def raw_dir(textbook_id: str) -> Path:
    """agent 抽取结果（raw）的约定位置：state/ingest/<textbookId>/raw/。
    P1.2 起由 agent 阅读节正文直接产出（不调 LLM API），本脚本 --from-raw 读它转 extract。"""
    return KNOWLEDGE / 'tools' / 'kg' / 'state' / 'ingest' / textbook_id / 'raw'


def load_raw(textbook_id: str, section_id: str) -> dict:
    """读 agent 产的 raw JSON，只保留 concepts；缺文件/sectionId 不符即抛错（不静默当 0 概念）。"""
    f = raw_dir(textbook_id) / f'{section_id}.json'
    data = json.loads(f.read_text(encoding='utf-8'))
    if data.get('sectionId') != section_id:
        raise ValueError(f'{f}: sectionId={data.get("sectionId")!r} 与文件名不符')
    if not isinstance(data.get('concepts'), list):
        raise ValueError(f'{f}: 缺 concepts 数组')
    return {'concepts': data['concepts']}


def resolve_section_id(path: Path, fm: dict, textbook: str) -> str:
    """front-matter sectionId 优先；否则从路径 chapters/C2/sections/S1.md 推 <textbook>-C2-S1；推不出返回 ''。"""
    if fm.get('sectionId'):
        return fm['sectionId']
    m = re.search(r'/chapters/(C\d+)/sections/(S\d+)\.md$', str(path).replace('\\', '/'))
    return f'{textbook}-{m.group(1)}-{m.group(2)}' if m else ''


def main() -> int:
    ap = argparse.ArgumentParser(
        description='content sections → extract JSON（第 ③ 步，不写图谱；写盘由 kg:ingest 负责）'
    )
    ap.add_argument('path', type=Path)
    ap.add_argument('--batch', action='store_true')
    ap.add_argument('--force', action='store_true', help='覆盖已存在的 extract JSON')
    ap.add_argument('--sleep', type=float, default=0.2)
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--prereq', action='store_true', help='产出 prerequisite 候选（默认关闭，避免环）')
    ap.add_argument('--from-raw', action='store_true',
                    help='读 agent 产的 state/ingest/<tb>/raw/<sid>.json，不调 LLM API（P1.2）')
    args = ap.parse_args()
    root = args.path if args.path.is_absolute() else REPO / args.path
    sections = collect_sections(root)
    if args.limit:
        sections = sections[: args.limit]
    if not sections:
        print('未找到 sections', file=sys.stderr)
        return 1

    client, model = (None, '') if args.from_raw else make_client()
    cache: dict[str, dict[str, str]] = {}
    item_seen: dict[str, set[str]] = {}
    summary = []
    for i, sec in enumerate(sections, 1):
        print(f'[{i}/{len(sections)}] {sec.relative_to(KNOWLEDGE)}', flush=True)
        _g, _t, _s, textbook = subject_from_path(sec)
        fm, _ = parse_fm(sec.read_text(encoding='utf-8'))
        sid = resolve_section_id(sec, fm, textbook)
        out = extract_dir(textbook) / f'{sid}.json'
        if sid and out.exists() and not args.force:
            # 先判后做：续跑不重复（LLM 模式也省调用）
            print(f'    · 已存在，跳过（--force 覆盖）: {out.name}', flush=True)
            summary.append({'status': 'skip', 'sectionId': sid, 'reason': 'exists'})
            continue
        try:
            r = process_section(
                sec,
                client=client,
                model=model,
                sleep_s=args.sleep,
                concept_cache=cache,
                item_seen=item_seen,
                write_prereq=args.prereq,
                from_raw=args.from_raw,
            )
            if r.get('status') == 'ok':
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        except Exception as e:  # noqa: BLE001
            print(f'    ! {e}', file=sys.stderr, flush=True)
            r = {'status': 'error', 'error': str(e)}
        summary.append({k: v for k, v in r.items() if k in ('status', 'sectionId', 'reason', 'error')}
                       | ({'concepts': len(r['concepts']), 'items': len(r['items']), 'relations': len(r['relations'])}
                          if r.get('status') == 'ok' else {}))

    ok = sum(1 for s in summary if s.get('status') == 'ok')
    print(f'完成 {ok}/{len(summary)}，extract JSON 在 state/ingest/<textbookId>/extract/', flush=True)
    print('下一步：pnpm kg:ingest --textbook <textbookId>', flush=True)
    errors = [s for s in summary if s.get('status') == 'error']
    if errors:
        print(f'有 {len(errors)} 节失败（见上方 ! 行），退出码 1', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
