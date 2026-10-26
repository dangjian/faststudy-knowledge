"""
从课文 prose markdown 中提取 Concept 实体。
"""
import re
import os
import yaml
from pathlib import Path

# 各学科的关键词提取规则
SUBJECT_RULES = {
    '数学': {
        'keywords': ['定理', '公式', '公理', '定义', '性质', '判定', '法则'],
        'entities': ['三角形', '四边形', '圆', '函数', '方程', '实数', '勾股', '全等', '相似', '平行', '垂直', '轴对称', '统计', '概率'],
    },
    '物理': {
        'keywords': ['定律', '定理', '原理', '公式', '定义'],
        'entities': ['力', '速度', '加速度', '密度', '压强', '浮力', '功', '能', '功率', '机械', '光', '声', '热', '电'],
    },
    '语文': {
        'keywords': ['手法', '修辞', '文体', '题材', '表达方式', '表现手法'],
        'entities': ['散文', '诗歌', '小说', '戏剧', '记叙', '说明', '议论', '描写', '抒情', '比喻', '拟人', '排比', '夸张', '对偶'],
    },
    '英语': {
        'keywords': ['时态', '语态', '词性', '句式'],
        'entities': ['名词', '动词', '形容词', '副词', '介词', '连词', '冠词', '代词', '现在时', '过去时', '将来时', '完成时', '被动', '从句'],
    },
    '生物': {
        'keywords': ['作用', '系统', '器官', '组织', '细胞'],
        'entities': ['消化', '呼吸', '循环', '泌尿', '神经', '激素', '生殖', '发育', '遗传', '变异', '生态'],
    },
    '历史': {
        'keywords': ['变法', '革命', '改革', '运动', '条约'],
        'entities': ['秦朝', '汉朝', '唐朝', '宋朝', '元朝', '明朝', '清朝', '洋务', '戊戌', '辛亥', '鸦片', '太平'],
    },
    '地理': {
        'keywords': ['气候', '地形', '河流', '资源', '工业', '农业', '交通', '城市'],
        'entities': ['亚洲', '欧洲', '非洲', '北美洲', '南美洲', '大洋洲', '南极洲', '太平洋', '印度洋', '北冰洋'],
    },
    '道德与法治': {
        'keywords': ['道德', '法律', '权利', '义务', '制度'],
        'entities': ['规则', '法律', '道德', '集体', '个人', '国家', '社会', '公民', '权利', '义务', '宪法', '法治', '自由', '平等', '公平', '正义'],
    },
}

def extract_concepts_from_md(md_path: Path, subject: str) -> list:
    """从 markdown 中提取概念"""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 移除 front matter
    content = re.sub(r'^---.*?---', '', content, flags=re.DOTALL)
    
    extracted = []
    
    rules = SUBJECT_RULES.get(subject, {})
    entities = rules.get('entities', [])
    keywords = rules.get('keywords', [])
    
    # 1. 标题中提取 H1-H4
    for match in re.finditer(r'^#{1,4}\s*(.+?)\s*$', content, re.MULTILINE):
        title = match.group(1).strip()
        # 清理 Markdown 格式
        title = re.sub(r'[#*`]', '', title)
        if len(title) > 2 and len(title) < 30:
            extracted.append({
                'name': title,
                'source': 'title',
                'context': title,
            })
    
    # 2. 关键词匹配提取
    for entity in entities:
        if entity in content:
            # 找包含这个 entity 的上下文句子
            lines = content.split('\n')
            for line in lines:
                if entity in line and len(line) < 200:
                    extracted.append({
                        'name': entity,
                        'source': 'entity_match',
                        'context': line.strip(),
                    })
                    break
    
    return extracted

def extract_items_from_md(md_path: Path, subject: str) -> list:
    """从 markdown 中提取 items（生词/短语/概念）"""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = re.sub(r'^---.*?---', '', content, flags=re.DOTALL)
    
    items = []
    
    # 提取加粗的术语 **term**
    for match in re.finditer(r'\*\*([^*]+)\*\*', content):
        term = match.group(1).strip()
        if 1 < len(term) < 30:
            items.append({
                'name': term,
                'type': 'term',
            })
    
    return items

def find_all_content_files(knowledge_root: Path) -> list:
    """找出所有 content/ 下的课文 markdown 文件"""
    # content/<年级>/<册>/<学科>/<教材>/chapters/Cn/sections/Sm.md，年级/册不设白名单
    return sorted((knowledge_root / 'content').glob('*/*/*/*/chapters/*/sections/*.md'))

def main():
    knowledge_root = Path(__file__).parents[4]
    files = find_all_content_files(knowledge_root)
    print(f"找到 {len(files)} 篇课文")
    
    all_concepts = []
    
    for md_file in files:
        # 解析路径中的科目名
        parts = md_file.parts
        try:
            content_idx = parts.index('content')
            subject = parts[content_idx + 3]
        except (ValueError, IndexError):
            continue
            
        concepts = extract_concepts_from_md(md_file, subject)
        if concepts:
            print(f"{md_file.name}: {len(concepts)} 个概念")
            all_concepts.extend(concepts)
    
    print(f"\n总计提取到 {len(all_concepts)} 个概念候选")

if __name__ == '__main__':
    main()
