"""逐句朗读音频 + 逐字时间生成（edge-tts）

每个参数一句，依次输出 0.mp3、1.mp3……（0 = 标题句，1..n = 正文各句，与页面句序对齐），
并输出 timings.json：timings[i] = 第 i 句的 token 列表 [{"t": 字, "s": 起秒, "e": 止秒}]，时间相对该句 mp3 开头。
中文一字一个 token（edge-tts 按词给边界，词内均分），英文一词一个 token；标点不算 token。
逗号 = 节奏停顿；多音字用**等长**同音字替换保证读音（页面显示原字，按 token 下标对齐，不等长会错位）。

用法：
  python3 -m venv /tmp/ttsvenv && /tmp/ttsvenv/bin/pip install -r requirements.txt
  /tmp/ttsvenv/bin/python gen-tts.py <输出目录> '使至塞上。唐，王维。' '单车，欲问边，' ...
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import edge_tts

VOICE = 'zh-CN-YunjianNeural'
RATE = '-25%'
TICK = 1e7  # edge-tts 的 offset/duration 单位是 100ns
CJK = re.compile(r'[㐀-鿿]')


def tokens(word: str, start: float, end: float) -> list[dict]:
    chars = CJK.findall(word)
    if not chars:  # 英文等：整词一个 token
        return [{'t': word, 's': round(start, 2), 'e': round(end, 2)}]
    d = (end - start) / len(chars)
    return [{'t': c, 's': round(start + k * d, 2), 'e': round(start + (k + 1) * d, 2)} for k, c in enumerate(chars)]


async def synth(text: str, path: Path) -> list[dict]:
    out = []
    with path.open('wb') as f:
        async for chunk in edge_tts.Communicate(text, VOICE, rate=RATE, boundary='WordBoundary').stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                s = chunk['offset'] / TICK
                out += tokens(chunk['text'], s, s + chunk['duration'] / TICK)
    return out


async def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    timings = []
    for i, text in enumerate(sys.argv[2:]):
        toks = await synth(text, out_dir / f'{i}.mp3')
        timings.append(toks)
        print(f'{i}.mp3  {"".join(t["t"] for t in toks)}')
    (out_dir / 'timings.json').write_text(json.dumps(timings, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(out_dir / 'timings.json')


asyncio.run(main())
