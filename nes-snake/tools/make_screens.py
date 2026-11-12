#!/usr/bin/env python3
"""生成三张静态 nametable 画面（标题 / 游戏 / 结束）与 HUD 坐标常量。

画面为 32x30 个 tile，正好一屏 NES nametable（960 字节）。
运行时只需增量改写分数、蛇、食物等少数格子，避免 vblank 带宽不足。
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 从 tiles.inc 解析图块常量，保证两侧永远一致
T = {}
BIG_LETTERS = None
CN_MAP = None
with open(os.path.join(ROOT, "src", "tiles.inc"), encoding="ascii") as f:
    for line in f:
        m = re.match(r"^\s*(\w+)\s*=\s*\$?([0-9A-Fa-f]+)", line)
        if m:
            T[m.group(1)] = int(m.group(2), 16)
        mb = re.match(r"^;\s*BIG_LETTERS\s*=\s*([A-Z]+)", line)
        if mb:
            BIG_LETTERS = mb.group(1)
        mh = re.match(r"^;\s*CN_MAP_HEX\s*=\s*([0-9A-Fa-f\s]+)", line)
        if mh:
            CN_MAP = "".join(chr(int(h, 16)) for h in mh.group(1).split())
assert BIG_LETTERS, "tiles.inc 缺少 BIG_LETTERS 定义"
assert CN_MAP, "tiles.inc 缺少 CN_MAP_HEX 定义"

SYMBOLS = ":-.!?/+<>*()=%#,"

W, H = 32, 30
PLAY_LEFT, PLAY_RIGHT = 1, 30
PLAY_TOP, PLAY_BOTTOM = 3, 26


def new_screen():
    return [[T["T_BLANK"]] * W for _ in range(H)]


def char_tile(ch):
    if ch == " ":
        return T["T_BLANK"]
    if "0" <= ch <= "9":
        return T["T_DIGITS"] + ord(ch) - ord("0")
    if "A" <= ch <= "Z":
        return T["T_LETTERS"] + ord(ch) - ord("A")
    if ch in SYMBOLS:
        return T["T_SYMBOLS"] + SYMBOLS.index(ch)
    return T["T_BLANK"]


def text(g, x, y, s):
    for i, ch in enumerate(s):
        if 0 <= x + i < W:
            g[y][x + i] = char_tile(ch)


def big(g, x, y, s):
    """3x3 大字，每个字母占 3 列 3 行。"""
    for i, ch in enumerate(s):
        assert ch in BIG_LETTERS, f"大字字母 {ch} 不在 CHR 大字表中"
        base = T["T_BIG"] + BIG_LETTERS.index(ch) * 9
        for r in range(3):
            for c in range(3):
                g[y + r][x + i * 3 + c] = base + r * 3 + c


def cn_text(g, x, y, s):
    """16x16 中文点阵：每个字占 2 列 x 2 行 tile；空格占 2 列空白。"""
    for i, ch in enumerate(s):
        cx = x + i * 2
        if cx + 1 >= W:
            break
        if ch == " ":
            for r in range(2):
                for c in range(2):
                    g[y + r][cx + c] = T["T_BLANK"]
            continue
        assert ch in CN_MAP, f"缺中文图块: {ch}"
        base = T["T_CN"] + CN_MAP.index(ch) * 4
        g[y][cx]         = base
        g[y][cx + 1]     = base + 1
        g[y + 1][cx]     = base + 2
        g[y + 1][cx + 1] = base + 3


def border(g, top=2, bottom=27, left=0, right=31):
    g[top][left] = T["T_CORNER_TL"]
    g[top][right] = T["T_CORNER_TR"]
    g[bottom][left] = T["T_CORNER_BL"]
    g[bottom][right] = T["T_CORNER_BR"]
    for x in range(left + 1, right):
        g[top][x] = T["T_BORDER_H"]
        g[bottom][x] = T["T_BORDER_H"]
    for y in range(top + 1, bottom):
        g[y][left] = T["T_BORDER_V"]
        g[y][right] = T["T_BORDER_V"]


def footer(g, hint):
    # 只占 y=28 一行；y=29 留空，避免 8px 字模上下笔画相接
    text(g, max(0, (W - len(hint)) // 2), 28, hint)


# ---------------- 标题画面 ----------------
# 每行文字之间至少隔一个空行（字模占满 8px 高，紧邻会糊在一起）
title = new_screen()
text(title, 8, 0, "***  NES SNAKE  ***")
border(title)
big(title, 8, 4, "SNAKE")                 # y=4..6
# 中文主界面：2026 创作年份 + 游戏说明（每字 16x16，占 2 行 tile）
cn_text(title, 10, 8,  "2026年新作")           # y=8..9，数字绿色
cn_text(title, 5, 11, "方向键移动 吃红色宝石")  # y=11..12
cn_text(title, 7, 14, "别撞墙 别咬到自己")     # y=14..15
text(title, 10, 18, "PRESS START")
text(title, 11, 21, "HI 000000")          # 数字位于 x=14..19, y=21
# 装饰：星星 + 一条小蛇 + 红色食物（配合调色板闪烁）
title[3][12] = T["T_STAR"]
title[3][21] = T["T_STAR"]
for x in range(9, 16):
    title[24][x] = T["T_BODY"]
title[24][16] = T["T_HEAD_R"]
title[24][19] = T["T_FOOD"]
title[24][22] = T["T_STAR"]
title[25][12] = T["T_STAR"]
title[25][21] = T["T_STAR"]
footer(title, "PRESS START TO PLAY")

# ---------------- 游戏画面 ----------------
play = new_screen()
text(play, 0, 0, "SCORE 000000  HI 000000  LV 01")
# y=1 留空，暂停时在此显示 PAUSED
border(play)
footer(play, "FOOD 000  START PAUSE  SEL TITLE")

# ---------------- 结束画面 ----------------
over = new_screen()
text(over, 0, 0, "SCORE 000000  HI 000000  LV 01")
border(over)
big(over, 4, 9, "GAMEOVER")               # y=9..11
# 分数与最高分并排一行，避免两行小字贴在一起
text(over, 4, 14, "SCORE 000000   HI 000000")   # 数字 x=10..15 / x=22..27
text(over, 6, 19, "PRESS START TO RETRY")
text(over, 9, 22, "SELECT: TITLE")
for x in range(10, 22, 3):
    over[25][x] = T["T_DOT"]
footer(over, "START: RETRY    SELECT: TITLE")

# ---------------- 导出 ----------------
consts = {
    "PLAY_LEFT": PLAY_LEFT,
    "PLAY_RIGHT": PLAY_RIGHT,
    "PLAY_TOP": PLAY_TOP,
    "PLAY_BOTTOM": PLAY_BOTTOM,
    "HUD_SCORE_X": 6,
    "HUD_SCORE_Y": 0,
    "HUD_HI_X": 17,
    "HUD_HI_Y": 0,
    "HUD_LV_X": 28,
    "HUD_LV_Y": 0,
    "HUD_FOOD_X": 5,
    "HUD_FOOD_Y": 28,
    "HUD_PAUSE_X": 26,
    "HUD_PAUSE_Y": 1,
    "TITLE_HI_X": 14,
    "TITLE_HI_Y": 21,
    "OVER_SCORE_X": 10,
    "OVER_SCORE_Y": 14,
    "OVER_HI_X": 22,
    "OVER_HI_Y": 14,
    "SCREEN_SIZE": W * H,
}

layout = [
    "; Generated by tools/make_screens.py - do not edit by hand",
    "; Playfield bounds and HUD coordinates",
]
for k, v in consts.items():
    layout.append(f"{k} = {v}")
with open(os.path.join(ROOT, "src", "layout.inc"), "w", encoding="ascii") as f:
    f.write("\n".join(layout) + "\n")

out = [
    "; Generated by tools/make_screens.py - do not edit by hand",
    "; 32x30 nametable maps, 960 bytes each",
]

for name, g in (("screen_title", title), ("screen_play", play), ("screen_over", over)):
    out.append(f"{name}:")
    flat = [v for row in g for v in row]
    assert len(flat) == 960
    assert max(flat) <= 255, f"{name} 含超出 8 位的 tile 索引"
    for i in range(0, 960, 16):
        out.append("    .byte " + ",".join(f"${v:02X}" for v in flat[i:i + 16]))
    out.append("")

with open(os.path.join(ROOT, "src", "screens.inc"), "w", encoding="ascii") as f:
    f.write("\n".join(out) + "\n")

print("screens.inc 生成完毕：3 张画面 x 960 字节")
print("HUD 坐标：" + ", ".join(f"{k}={v}" for k, v in consts.items() if k.startswith("HUD") or k.startswith("OVER")))
