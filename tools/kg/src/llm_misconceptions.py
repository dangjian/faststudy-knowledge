#!/usr/bin/env python3
"""llm_misconceptions.py — LLM 补齐 Concept.misconceptions(易错点)。

两个 agent 工具(kg_review_unit / kg_section_brief)的 description 都承诺"含易错点",
但全库 6790 个 Concept 只有 4 个有——agent 每次拿到的都是空数组。本脚本补齐其余。

按 section 分组调用(同节概念共享上下文,输出质量更高),写回
graph/entities/concepts/<学科>.yaml。（2026-09-27 content v4：ExamModel 层退役，
解题模型易错点随 ## 解题模型 区块迁入章节正文，不再有独立水化机制。）

用法:
  python llm_misconceptions.py [--subject 化学] [--limit 3] [--root <knowledge>] [--workers 6] [--dry] [--force]
"""
import os, sys, json, time, argparse, random, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from llm_relations_hierarchy import make_client, _reasoning_kw, extract_json

HERE = Path(__file__).resolve()
ROOT_DEFAULT = HERE.parents[3]

# yaml 中的字段顺序,与现有条目保持一致(朴素赋值会把 misconceptions 追加到末尾)
FIELD_ORDER = ['id', 'type', 'subject', 'title', 'aliases', 'category',
               'explanation', 'misconceptions', 'confidence', 'sourceRef']

MAX_PER_BATCH = 12

# 学科自适应:易错点的形态因学科而异,通用 prompt 会让文科输出空泛
SUBJECT_GUIDE = {
    '数学': '条件误用(如忽略 a<0)、符号与变号错误、公式适用范围、计算陷阱、分类讨论漏情形',
    '物理': '受力分析漏力、单位换算、矢量方向、公式适用条件、理想模型与实际混淆',
    '化学': '配平与守恒、反应条件遗漏、离子共存判断、实验操作顺序、物质状态标注',
    '生物': '结构与功能对应错乱、过程顺序颠倒、概念层级混淆(细胞/组织/器官)、特例当通例',
    '语文': '字形字音混淆、近义词误用、修辞手法辨识错误、文言实词虚词一词多义、作者与作品张冠李戴',
    '历史': '时间先后颠倒、人物与事件张冠李戴、因果倒置、以偏概全、朝代与制度对应错误',
    '地理': '经纬度与方向判断、气候类型与成因混淆、地形与地貌术语混用、图表判读错误',
    '道德与法治': '法律概念近义混用(权利/权力)、责任主体认错、条件与结论倒置、以偏概全',
    '英语': '词形与词性误用、时态语态混淆、中式英语搭配、易混词对、单复数与可数性',
}

# 空泛祈使句开头——这类"易错点"等于没说
VAGUE_PREFIX = ('注意', '理解', '掌握', '记住', '牢记', '容易混淆', '需要注意',
                '要注意', '应当', '应该', '认真', '仔细')


# 英语的易错点必须嵌英文例句才说得清（"混淆whose与who's，如'The man who's car is red'应为whose"），
# 拉丁字母逐个计入长度，60 字上限会把好条目一起毙掉——首轮英语拒绝率 32% 全出在这里。
MAX_LEN = {'英语': 80}
DEFAULT_MAX_LEN = 60


def quality_check(text, concept):
    """返回拒绝原因;通过则返回 None。"""
    t = (text or '').strip()
    cap = MAX_LEN.get(concept.get('subject'), DEFAULT_MAX_LEN)
    if not (12 <= len(t) <= cap):
        return 'length'
    if t.startswith(VAGUE_PREFIX):
        return 'vague'
    title = (concept.get('title') or '').strip()
    if title and t == title:
        return 'echo_title'
    expl = (concept.get('explanation') or '').strip()
    # 只是把释义抄一遍
    if expl and (t in expl or (len(t) > 20 and t[:20] in expl)):
        return 'echo_explanation'
    return None


def build_prompt(subject, section_title, concepts):
    guide = SUBJECT_GUIDE.get(subject, '概念混淆、条件误用、以偏概全')
    lines = []
    for i, c in enumerate(concepts, 1):
        expl = (c.get('explanation') or '').strip().replace('\n', ' ')
        lines.append(f"{i}. 【{c['title']}】{expl[:120]}")
    return (
        f"学科：{subject}\n"
        f"所属节：{section_title}\n"
        f"以下是该节的概念（编号.【标题】释义）：\n" + "\n".join(lines) + "\n\n"
        f"请为每个概念写 2-3 条【学生真实会犯的错】，该学科常见错误类型：{guide}\n\n"
        "输出 JSON：{\"items\": [{\"index\": 1, \"misconceptions\": [\"…\", \"…\"]}, ...]}\n\n"
        "硬性要求：\n"
        "1. 写【具体的错误做法或错误认知】，能让人一眼看出错在哪，最好带反例。\n"
        "   好例：\"方程两边同除以含字母的式子会丢解（如 2x=5x 两边除以 x 得 2=5）\"\n"
        "   好例：\"认为 |a| 永远等于 a，忽略 a<0 时 |a|=-a\"\n"
        "   坏例：\"注意理解概念的含义\" \"容易混淆相关知识点\"（空泛，禁止）\n"
        "2. 每条 12-60 字，禁止以\"注意/理解/掌握/记住/容易混淆\"开头。\n"
        "3. 禁止复述上面给出的释义——要写的是【错误】，不是【正确定义】。\n"
        "4. 确实想不出真实易错点的概念，该项 misconceptions 给空数组，不要硬凑。"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subject', help='只处理某学科（试跑）')
    ap.add_argument('--limit', type=int, help='只处理前 N 个批次（试跑）')
    ap.add_argument('--root', default=str(ROOT_DEFAULT))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true', help='覆盖已有 misconceptions')
    args = ap.parse_args()

    root = Path(args.root)
    graph = json.load(open(root / 'dist' / 'graph.json', encoding='utf-8'))
    nodes = graph['nodes']

    sec_title = {n['id']: n.get('title', '') for n in nodes if n['type'] == 'Section'}
    # concept -> section（走 covered_by）
    cov = {}
    for e in graph['edges']:
        if e['type'] == 'covered_by':
            cov.setdefault(e['from'], []).append(e['to'])

    # 读 yaml 源（真值所在；dist 只用来拿 covered_by 拓扑）
    cdir = root / 'graph' / 'entities' / 'concepts'
    subjects = [args.subject] if args.subject else sorted(p.stem for p in cdir.glob('*.yaml'))

    client, model = (None, None) if args.dry else make_client()
    grand = {'todo': 0, 'filled': 0, 'rejected': 0, 'empty': 0, 'batches': 0}

    for subject in subjects:
        path = cdir / f'{subject}.yaml'
        if not path.is_file():
            print(f'跳过 {subject}: 文件不存在'); continue
        items = yaml.safe_load(path.read_text(encoding='utf-8')) or []
        by_id = {c['id']: c for c in items}

        todo = [c for c in items if args.force or not c.get('misconceptions')]
        if not todo:
            print(f'{subject}: 已全部覆盖，跳过'); continue

        # 按 section 分组，超 MAX_PER_BATCH 则拆
        groups = {}
        for c in todo:
            sid = (cov.get(c['id']) or ['<无节>'])[0]
            groups.setdefault(sid, []).append(c)
        batches = []
        for sid, cs in groups.items():
            for i in range(0, len(cs), MAX_PER_BATCH):
                batches.append((sid, cs[i:i + MAX_PER_BATCH]))
        if args.limit:
            batches = batches[:args.limit]

        grand['todo'] += len(todo)
        print(f'{subject}: 待补 {len(todo)}/{len(items)}，{len(batches)} 批')
        if args.dry:
            grand['batches'] += len(batches)
            continue

        stats = {'filled': 0, 'rejected': 0, 'empty': 0, 'reasons': {}}

        def work(batch):
            sid, cs = batch
            user = build_prompt(subject, sec_title.get(sid, sid), cs)
            for attempt in range(3):
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "你是初中学科教研老师，最懂学生会在哪里出错。只输出 JSON，不要解释。"},
                            {"role": "user", "content": user},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.3, **_reasoning_kw(model))
                    return cs, extract_json(resp.choices[0].message.content or "") or {}
                except Exception as ex:
                    print(f'  [retry {attempt+1}] {ex}'); time.sleep(2 + attempt * 2)
            return cs, {}

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(work, b) for b in batches]
            for fut in as_completed(futs):
                cs, res = fut.result()
                grand['batches'] += 1
                for row in (res.get('items') or []):
                    try:
                        idx = int(row.get('index', 0)) - 1
                    except (TypeError, ValueError):
                        continue
                    if not (0 <= idx < len(cs)):
                        continue
                    concept = cs[idx]
                    good = []
                    for m in (row.get('misconceptions') or []):
                        if not isinstance(m, str):
                            continue
                        reason = quality_check(m, concept)
                        if reason:
                            stats['rejected'] += 1
                            stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
                            continue
                        good.append(m.strip())
                    if good:
                        by_id[concept['id']]['misconceptions'] = good[:3]
                        stats['filled'] += 1
                    else:
                        stats['empty'] += 1

        # 按字段顺序重建后落盘（每学科处理完即写，中断只损失当前学科未完成批次）
        rebuilt = []
        for c in items:
            d = {k: c[k] for k in FIELD_ORDER if k in c}
            for k, v in c.items():
                if k not in d:
                    d[k] = v
            rebuilt.append(d)
        path.write_text(yaml.safe_dump(rebuilt, allow_unicode=True, sort_keys=False), encoding='utf-8')

        total_out = stats['filled'] + stats['rejected'] + stats['empty']
        rate = stats['rejected'] / max(1, stats['rejected'] + stats['filled'])
        print(f"  {subject} 完成: 补齐 {stats['filled']} 个概念，拒绝 {stats['rejected']} 条"
              f"{stats['reasons']}，空手 {stats['empty']} 个")
        if rate > 0.2:
            print(f"  ⚠️  {subject} 拒绝率 {rate:.0%} > 20%——prompt 需要调，别硬灌")
        for k in ('filled', 'rejected', 'empty'):
            grand[k] += stats[k]

    if args.dry:
        print(f"[dry] 待补 {grand['todo']} 个概念，共 {grand['batches']} 批")
        return
    print(f"\n合计: 补齐 {grand['filled']} 个概念 / 待补 {grand['todo']}，"
          f"拒绝 {grand['rejected']} 条，空手 {grand['empty']} 个，{grand['batches']} 批")


if __name__ == '__main__':
    main()
