#!/usr/bin/env python3
"""Build `graph/chapter-standards.yaml` by aligning every Chapter entity to one
or more curriculum standards.

Strategy:
  1. For each textbook, read standardEdition from its book-level index.md
     front-matter (v3+ single source; the old graph/entities/structure/ YAML
     is gone — reading it silently produced an empty mapping, fixed 2026-10-01).
  2. Load all chapters' titles from the same front-matter (grades 7-9 only;
     primary grades wait for P1.6 primary standards).
  3. Apply per-(subject, edition) keyword rules to map chapter title
     keywords → standard shortCodes, then resolve to full standard IDs
     in `graph/curriculum-standards.yaml`.
  4. Fallback: if no rule matches, assign all standards for the
     (subject, edition, gradeBand) of the chapter's textbook.

Output: `graph/chapter-standards.yaml`
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

from book_frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parents[3]
GRAPH = REPO / "graph"
CONTENT = REPO / "content"
# 小学（1-6）课标条目要到 P1.6 才补；现在纳入会被兜底逻辑挂上初中课标，故先只收 7-9
GRADES = {"7", "8", "9"}
STANDARDS_PATH = GRAPH / "curriculum-standards.yaml"
OUT_PATH = GRAPH / "chapter-standards.yaml"

# -----------------------------------------------------------------------------
# Per (subject, edition) keyword → standard shortCode rules
# -----------------------------------------------------------------------------
# 通用规则：subject + edition 适用的 (keyword regex) → shortCode 列表
# keyword 用正则（非锚定），命中任一即纳入

RULES: dict[tuple[str, str], list[tuple[str, str]]] = {
    # -------------------- 数学 (both editions share themes) --------------------
    ("Math", "2022版"): [
        (r"二次函数|一次函数|反比例|函数|方程|不等式|代数式|实数|有理数|分式|根式|整式|乘法公式|因式分解|幂|指数|对数", "DA"),
        (r"三角形|四边形|圆|平行|相似|勾股|视图|对称|旋转|平移|坐标|几何|角|线|面|体|面积|体积|尺规|投影|位似|展开图|轴|矩形|菱形|正方形|梯形|直角|等腰|等边|全等|线段|周长|弧|弦|扇形|切线|内切|外接|外切|圆周率|圆心角|圆锥|圆柱|球|证明", "GG"),
        (r"统计|概率|数据|抽样|方差|频率|众数|中位数|平均数|随机|可能性", "SP"),
        (r"综合与实践|课题|探究", "IP"),
    ],
    ("Math", "2011版"): [
        (r"二次函数|一次函数|反比例|函数|方程|不等式|代数式|实数|有理数|分式|根式|整式|乘法公式|因式分解|幂|指数|对数", "DA"),
        (r"直角三角形|三角函数|锐角三角|解直角|特殊角|三角形|四边形|圆|平行|相似|勾股|视图|对称|旋转|平移|坐标|几何|角|线|面积|体积|尺规|投影|位似|展开图|矩形|菱形|正方形|梯形|直角|等腰|等边|全等|线段|周长|弧|弦|扇形|切线|外接|外切|圆周率|圆心角|圆锥|圆柱|球|证明", "GG"),
        (r"统计|概率|数据|抽样|方差|频率|众数|中位数|平均数|随机|可能性", "SP"),
        (r"综合与实践|课题|探究", "IP"),
    ],
    # -------------------- 物理 (2022版: 8-9年级) --------------------
    ("Physics", "2022版"): [
        (r"声|光|透镜|反射|折射|视觉|色散|眼镜|凸透镜|凹透镜|显微镜|望远镜", "MI"),
        (r"运动|速度|参照|惯性|牛顿|力|二力|弹力|重力|摩擦|浮力|压强|大气压|流体|杠杆|滑轮|斜面|机械|功|功率|机械效率|简单机械", "MI"),
        (r"物质|密度|状态|分子|原子|物态|熔化|凝固|汽化|液化|升华|凝华|比热|内能|热机|热值", "MA"),
        (r"电|电路|欧姆|电功|电功率|电流|电压|电阻|电磁|磁|磁场|电磁铁|发电机|电动机|能量|能守恒|热力学|能源", "EN"),
    ],
    # -------------------- 化学 (2022版: 9年级) --------------------
    ("Chemistry", "2022版"): [
        (r"大家都来学化学|化学实验|实验基本|探究|科学探究|观察|记录|测定|仪|器|装置", "SE"),
        (r"空气|氧气|水|金属|溶液|酸|碱|盐|氧化物|燃料|二氧化碳|有机|化合|性质", "PP"),
        (r"元素|原子|分子|离子|化学式|相对原子|结构|周期|化合价|组成|构成", "CS"),
        (r"化学反应|化学方程式|质量守恒|反应类型|置换|复分解|金属活动性|催化", "CC"),
        (r"化学与社会|跨学科|材料|能源|环境|健康|化学与", "SO"),
    ],
    # -------------------- 生物 (2022版: 7-8年级) --------------------
    ("Biology", "2022版"): [
        (r"细胞|组织|器官|系统|显微镜|观察|结构层次|生物体", "ST"),
        # 不收裸「植物|动物」：会把「植物的生活」等生理单元误判为多样性（2026-10-01），类群单元靠「类群」命中
        (r"多样性|多种多样|分类|种子|蕨|苔藓|藻类|类群|微生物|细菌|真菌|病毒|检索表|物种", "DV"),
        (r"环境|生态|食物链|食物网|生态系统|保护|生物圈(?!中的人)", "EN"),
        (r"光合|蒸腾|植物的|植物体|开花|结果|萌发|根|茎|叶|花|果实|种子", "PL"),
        (r"生物圈中的人|人体|消化|呼吸|循环|血液|心脏|泌尿|神经|内分泌|生殖|健康|传染病|免疫|青春期", "PH"),
        (r"遗传|进化|基因|DNA|染色体|变异|物种起源|生命起源", "GE"),
    ],
    # -------------------- 历史 (按年级粗对齐) --------------------
    ("History", "2022版"): [],
    ("History", "2011版"): [],
    # -------------------- 地理 --------------------
    ("Geography", "2022版"): [
        (r"地球|地图|经纬|宇宙|公转|自转|地图|等高线|比例尺|图例|方向", "EM"),
        (r"亚洲|欧洲|非洲|美洲|大洋|极地|国家|地区|撒哈拉|西亚|南亚|东南亚|中亚|日本|印度|俄罗斯|美国|巴西|澳大利亚", "WG"),
        (r"中国|疆域|人口|民族|地形|气候|河流|自然资源|经济|交通|农业|工业|四大地理|南方|北方|青藏|西北|省级|跨省|长江|黄河|黄土|塞外|新疆|台湾|香港|澳门|家乡", "CG"),
        (r"家乡|乡土地理|本省|本市|本县", "HG"),
    ],
    ("Geography", "2011版"): [
        (r"地球|地图|经纬|宇宙|公转|自转|比例尺|图例|方向", "EM"),
        (r"亚洲|欧洲|非洲|美洲|大洋|极地|国家|地区|西亚|南亚|东南亚|日本|印度|俄罗斯|美国|巴西|澳大利亚|海陆|气候|人种|宗教|聚落", "WG"),
        (r"中国|疆域|人口|民族|地形|气候|河流|自然资源|经济|交通|农业|工业|四大地理|南方|北方|青藏|西北|省级|长江|黄河", "CG"),
        (r"家乡|乡土地理|本省|本市|本县", "HG"),
    ],
    # -------------------- 道德与法治 (chapter 多为"单元/课"；按单元标题关键词精对齐，无命中再兜底) --------------------
    ("Politics", "2022版"): [
        (r"青春|少年|生命|人生|成长|自我|梦想|情绪|心理|健康", "MH"),
        (r"中华|传统|美德|道德|诚信|责任|孝敬|友善", "MR"),
        (r"宪法|法治|法律|权利|义务|规则|维权|司法|法院|依法|犯罪|民法", "LR"),
        (r"国家制度|国家机构|国家利益|国情|政治制度|经济制度|生态文明|民族|安全", "NL"),
        (r"世界|全球|国际|人类命运|和平", "IV"),
    ],
    ("Politics", "2011版"): [
        (r"青春|少年|生命|人生|成长|自我|心理|健康", "MH"),
        (r"中华|传统|美德|道德|诚信|孝敬|友善|责任", "MR"),
        (r"宪法|法治|法律|权利|义务|规则|维权|依法|犯罪", "LR"),
        (r"国家|国情|政治|经济|民族|制度|安全", "NL"),
        (r"世界|全球|国际|和平|发展", "WG"),
    ],
    # -------------------- 语文 (chapter 多为"第N单元"，无主题词，兜底对齐) --------------------
    ("Chinese", "2022版"): [],
    ("Chinese", "2011版"): [],
    # -------------------- 英语 (兜底) --------------------
    ("English", "2022版"): [],
    ("English", "2011版"): [],
}


# 简易 YAML 解析（仅用于 standards 与 chapter 列表）
def parse_simple_yaml_list(path: Path) -> list[dict]:
    """极简 YAML 列表解析：支持顶层 list[dict]，值含 | 块字符串。
    不依赖 PyYAML，避免引入依赖。
    """
    text = path.read_text(encoding="utf-8")
    items: list[dict] = []
    cur: dict | None = None
    cur_key: str | None = None
    block_indent: int | None = None
    block_lines: list[str] = []
    in_block = False

    def commit_block():
        nonlocal cur, cur_key, in_block, block_lines, block_indent
        if cur is not None and cur_key is not None and in_block:
            cur[cur_key] = "\n".join(block_lines).strip()
        in_block = False
        block_lines = []
        block_indent = None

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("- "):
            commit_block()
            cur = {}
            items.append(cur)
            # inline `- key: value` form
            rest = line[2:].strip()
            if ":" in rest:
                k, v = rest.split(":", 1)
                cur[k.strip()] = v.strip().strip('"').strip("'")
        elif cur is not None:
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if stripped.startswith("|"):
                in_block = True
                block_indent = indent + 2
                block_lines = []
            elif ":" in stripped and not in_block:
                k, v = stripped.split(":", 1)
                cur[k.strip()] = v.strip().strip('"').strip("'")
            elif in_block:
                if indent >= (block_indent or indent):
                    block_lines.append(line[block_indent:] if block_indent else line)
                else:
                    commit_block()
                    if ":" in stripped:
                        k, v = stripped.split(":", 1)
                        cur[k.strip()] = v.strip().strip('"').strip("'")
    commit_block()
    return items


def write_simple_yaml_list(path: Path, items: list[dict]) -> None:
    lines: list[str] = []
    for it in items:
        first = True
        for k, v in it.items():
            if isinstance(v, list):
                if first:
                    lines.append(f"- {k}:")
                    first = False
                else:
                    lines.append(f"  {k}:")
                for item in v:
                    lines.append(f"    - {item}")
            else:
                prefix = "- " if first else "  "
                lines.append(f"{prefix}{k}: {v}")
                first = False
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_standards_index() -> dict[tuple[str, str, str], str]:
    """{(subjectEn, edition, shortCode): standardId}"""
    items = parse_simple_yaml_list(STANDARDS_PATH)
    idx: dict[tuple[str, str, str], str] = {}
    for it in items:
        idx[(it["subjectEn"], it["edition"], it["shortCode"])] = it["id"]
    return idx


def collect_chapters(content_root: Path = CONTENT) -> list[dict]:
    """从书级 index.md front-matter 收集 7-9 年级章节。一章都没收到即退出非 0——
    宁可失败，也不把 chapter-standards.yaml 静默写成空列表。"""
    chapters: list[dict] = []
    for path in sorted(content_root.glob("*/*/*/*/index.md")):
        tb = parse_frontmatter(path.read_text(encoding="utf-8"), str(path))
        if str(tb.get("grade")) not in GRADES:
            continue
        edition = tb.get("standardEdition") or "2022版"
        subject_en = subject_en_from_cn(tb["subject"])
        for ch in tb.get("chapters") or []:
            chapters.append({
                "chapterId": f"{tb['textbookId']}-{ch['id']}",
                "textbookId": tb["textbookId"],
                "title": ch["title"],
                "grade": str(tb["grade"]),
                "term": str(tb["term"]),
                "subject": tb["subject"],
                "subjectEn": subject_en,
                "edition": edition,
            })
    if not chapters:
        sys.exit(f"在 {content_root} 下没有收集到任何 7-9 年级章节，拒绝写出空的 chapter-standards.yaml")
    return chapters


SUBJECT_CN_TO_EN = {
    "数学": "Math", "语文": "Chinese", "英语": "English",
    "物理": "Physics", "化学": "Chemistry", "生物": "Biology",
    "历史": "History", "地理": "Geography", "道德与法治": "Politics",
}


def subject_en_from_cn(cn: str) -> str:
    return SUBJECT_CN_TO_EN.get(cn, cn)


def chapter_grade_band(grade: str, subject_en: str) -> str:
    """课程标准的学段范围。"""
    if subject_en == "Chemistry":
        return "9"
    if subject_en == "Physics":
        return "8-9"
    if subject_en == "Biology":
        return "7-8"
    if subject_en == "History":
        return {"7": "7", "8": "8", "9": "9"}.get(grade, "7-9")
    if subject_en == "Geography":
        return {"7": "7", "8": "8"}.get(grade, "7-8")
    return "7-9"


def align_chapter(ch: dict, std_index: dict) -> list[str]:
    """返回对齐到的 standard id 列表（去重保序）。"""
    key = (ch["subjectEn"], ch["edition"])
    rules = RULES.get(key, [])
    title = ch["title"]
    codes: list[str] = []
    if rules:
        for pattern, code in rules:
            if re.search(pattern, title):
                if code not in codes:
                    codes.append(code)
    # 兜底：按 (subjectEn, edition, gradeBand) 全部纳入
    band = chapter_grade_band(ch["grade"], ch["subjectEn"])
    if not codes:
        for (subj_en, ed, code), sid in std_index.items():
            if subj_en == ch["subjectEn"] and ed == ch["edition"]:
                # 用 chapter title 反推 band 太复杂，统一收所有 band = ch["grade"] 的标准
                std_band = code_band_for_subject(subj_en, ed, code)
                if std_band == band or std_band == "7-9" or band == "7-9":
                    if code not in codes:
                        codes.append(code)
    # 解析成 id
    ids: list[str] = []
    for c in codes:
        sid = std_index.get((ch["subjectEn"], ch["edition"], c))
        if sid and sid not in ids:
            ids.append(sid)
    return ids


# 简易反查：给定标准 id 推断其 band（通过 standards_index 的 value→lookup metadata）
def build_band_lookup() -> dict[str, tuple[str, str, str, str]]:
    """{standardId: (subjectEn, edition, shortCode, gradeBand)}"""
    items = parse_simple_yaml_list(STANDARDS_PATH)
    out: dict[str, tuple[str, str, str, str]] = {}
    for it in items:
        out[it["id"]] = (
            it["subjectEn"], it["edition"], it["shortCode"], it["gradeBand"],
        )
    return out


_BAND_LOOKUP: dict[str, tuple[str, str, str, str]] | None = None


def code_band_for_subject(subject_en: str, edition: str, code: str) -> str:
    global _BAND_LOOKUP
    if _BAND_LOOKUP is None:
        _BAND_LOOKUP = build_band_lookup()
    for sid, (s, e, c, b) in _BAND_LOOKUP.items():
        if s == subject_en and e == edition and c == code:
            return b
    return "7-9"


def main() -> None:
    std_index = load_standards_index()
    chapters = collect_chapters()
    print(f"标准数: {len(std_index)}")
    print(f"章节数: {len(chapters)}")
    rows: list[dict] = []
    empty = 0
    for ch in chapters:
        ids = align_chapter(ch, std_index)
        if not ids:
            empty += 1
        rows.append({
            "chapterId": ch["chapterId"],
            "textbookId": ch["textbookId"],
            "subject": ch["subject"],
            "grade": ch["grade"],
            "edition": ch["edition"],
            "standards": ids,
        })
    write_simple_yaml_list(OUT_PATH, rows)
    print(f"写出 {len(rows)} 条 → {OUT_PATH.relative_to(REPO)}")
    print(f"无对齐: {empty}")
    # 抽样
    print("\n抽样 5 条:")
    for r in rows[:5]:
        print(f"  {r['chapterId']}: {r['standards']}")


if __name__ == "__main__":
    main()