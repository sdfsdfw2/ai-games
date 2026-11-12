#!/usr/bin/env python3
"""生成自包含的「NES 双卡带合集」试玩页。

内联 jsnes、两枚 .nes ROM 与两套 CHR-ROM。网页不依赖模拟器的帧缓冲，
而是读取 PPU nametable + 当前卡带的 CHR 逐 tile 还原画面。

输出：
  /workspace/nes-snake/play.html   （用户熟悉的路径）
  /workspace/index.html            （工作区顶层入口）

若音乐盒 ROM 尚未构建，自动降级为只含贪吃蛇的单卡带页。
"""

import base64
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
MUSIC = os.path.join(WORKSPACE, "nes-music")


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def song_count():
    """从 songs.inc 解析曲目数，保证网页显示的 x/20 与 ROM 一致。"""
    p = os.path.join(MUSIC, "src", "songs.inc")
    if not os.path.exists(p):
        return 20
    with open(p, encoding="ascii") as f:
        for line in f:
            m = re.match(r"^\s*song_count\s*=\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return 20


with open(os.path.join(ROOT, "vendor", "jsnes.min.js"), encoding="utf-8") as f:
    jsnes_lib = f.read()
with open(os.path.join(ROOT, "tools", "arcade.template.html"), encoding="utf-8") as f:
    html = f.read()

games = [{
    "id": "snake",
    "title": "贪吃蛇 SNAKE",
    "sub": "红白机原生贪吃蛇 · 2026 中文标题",
    "rom": b64(os.path.join(ROOT, "snake.nes")),
    "chr": b64(os.path.join(ROOT, "chr.bin")),
    "tracks": 0,
}]

rom_music = os.path.join(MUSIC, "music.nes")
chr_music = os.path.join(MUSIC, "chr.bin")
if os.path.exists(rom_music) and os.path.exists(chr_music):
    n = song_count()
    games.append({
        "id": "music",
        "title": "音乐盒 MUSIC BOX",
        "sub": f"{n} 首芯片音乐 · 4 声道 APU · 2026",
        "rom": b64(rom_music),
        "chr": b64(chr_music),
        "tracks": n,
    })

payload = json.dumps(games, ensure_ascii=False, separators=(",", ":"))
html = (html
        .replace("__JSNES_LIB__", jsnes_lib)
        .replace("__GAMES_JSON__", payload))

for out in (os.path.join(ROOT, "play.html"),
            os.path.join(WORKSPACE, "index.html")):
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

names = " + ".join(g["title"] for g in games)
print(f"合集试玩页生成完毕：{len(html)} 字节（自包含，无外部依赖）")
print(f"  卡带：{names}")
print(f"  输出：{os.path.join(ROOT, 'play.html')} / {os.path.join(WORKSPACE, 'index.html')}")
