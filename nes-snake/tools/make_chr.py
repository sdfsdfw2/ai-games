#!/usr/bin/env python3
"""生成《NES 贪吃蛇》的 8KB CHR-ROM 图块表。

每个 tile 为 8x8 像素、2bit 色深，共 16 字节（低位平面 8 字节 + 高位平面 8 字节）。
颜色索引：0=黑(通用底色) 1=白 2=绿 3=红，对应汇编里 palette 的 4 个条目。

同时产出：
  chr.bin           供 build.py 拼进 .nes
  src/tiles.inc     ca65 图块索引常量，保证 Python 与汇编两侧一致
  tools/chr_preview.png  图块预览，便于目视检查
"""

import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CN_FONT_SPEC = "Noto Sans CJK SC:style=Regular"   # 简体中文黑体，16px 即 16x16 点阵
CN_THRESHOLD = 110

TILE_COUNT = 512
TILE_BYTES = 16

C2V = {".": 0, "W": 1, "G": 2, "R": 3}
V2C = {1: "W", 2: "G", 3: "R"}
PREVIEW_RGB = [(16, 16, 20), (238, 238, 238), (86, 214, 96), (226, 62, 62)]

# ---------------- 图块索引分配 ----------------
T_BLANK = 0x00
T_DIGITS = 0x01          # 0-9  -> 0x01..0x0A
T_LETTERS = 0x0B         # A-Z  -> 0x0B..0x24
SYMBOLS = ":-.!?/+<>*()=%#,"
T_SYMBOLS = 0x25         # 16 个符号 -> 0x25..0x34

ASSIGNED = {
    "T_BLANK": T_BLANK,
    "T_DIGITS": T_DIGITS,
    "T_LETTERS": T_LETTERS,
    "T_SYMBOLS": T_SYMBOLS,
}
_nxt = T_SYMBOLS + len(SYMBOLS)


def alloc(name):
    global _nxt
    ASSIGNED[name] = _nxt
    v = _nxt
    _nxt += 1
    return v


T_BORDER_H = alloc("T_BORDER_H")
T_BORDER_V = alloc("T_BORDER_V")
T_CORNER_TL = alloc("T_CORNER_TL")
T_CORNER_TR = alloc("T_CORNER_TR")
T_CORNER_BL = alloc("T_CORNER_BL")
T_CORNER_BR = alloc("T_CORNER_BR")
T_HEAD_U = alloc("T_HEAD_U")
T_HEAD_R = alloc("T_HEAD_R")
T_HEAD_D = alloc("T_HEAD_D")
T_HEAD_L = alloc("T_HEAD_L")
T_BODY = alloc("T_BODY")
T_FOOD = alloc("T_FOOD")
T_FOOD_ALT = alloc("T_FOOD_ALT")
T_STAR = alloc("T_STAR")
T_DOT = alloc("T_DOT")
# 大字表只包含标题/结束画面实际用到的字母（nametable 索引只有 8 位）
BIG_LETTERS = "AEGKMNORSV"
T_BIG = _nxt  # 每个字母 3x3=9 个 tile
ASSIGNED["T_BIG"] = T_BIG
_nxt += len(BIG_LETTERS) * 9

# ---------------- 中文点阵 ----------------
# NES 没有中文字库，这里自己把汉字画成 16x16 点阵（2x2 个 tile）。
# 顺序即 CHR 索引顺序，make_screens.py 会按同样的表把字排进 nametable。
CN_DIGITS = "206"                       # "2026" 用到的数字（去重）
CN_CHARS = "年新作方向键移动吃红色宝石别撞墙咬到自己"
CN_MAP = CN_DIGITS + CN_CHARS
T_CN = _nxt                             # 每个字符 4 个 tile：左上/右上/左下/右下
ASSIGNED["T_CN"] = T_CN
_nxt += len(CN_MAP) * 4

assert _nxt <= TILE_COUNT, "图块数量超出 CHR-ROM 容量"
assert _nxt <= 256, "图块索引超出 nametable 的 8 位上限"


# ---------------- 基础工具 ----------------
def from_rows(rows):
    assert len(rows) == 8 and all(len(r) == 8 for r in rows), rows
    lo, hi = [], []
    for r in rows:
        b0 = b1 = 0
        for ch in r:
            v = C2V[ch]
            b0 = (b0 << 1) | (v & 1)
            b1 = (b1 << 1) | ((v >> 1) & 1)
        lo.append(b0)
        hi.append(b1)
    return bytes(lo + hi)


def from_grid(grid, x0, y0, w=8, h=8):
    return from_rows(["".join(grid[y0 + y][x0 + x] for x in range(w)) for y in range(h)])


def blank_tile():
    return from_rows(["........"] * 8)


def grid_new(w, h, fill="."):
    return [[fill] * w for _ in range(h)]


_font_cache = {}


def get_font(size):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
    return _font_cache[size]


def get_cn_font(size=16):
    """取简体中文 face（.ttc 里第几个 face 由 fontconfig 决定）。"""
    if "cn" not in _font_cache:
        try:
            spec = subprocess.check_output(
                ["fc-match", "-f", "%{file}|%{index}", CN_FONT_SPEC], text=True
            )
            path, idx = spec.split("|")
            _font_cache["cn"] = ImageFont.truetype(path, size, index=int(idx))
        except Exception:
            _font_cache["cn"] = ImageFont.truetype(
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", size, index=2
            )
    return _font_cache["cn"]


def cn_glyph(ch, color="W"):
    """把汉字渲染成 16x16 的颜色字符网格；字形本身自带留白，无需缩放。"""
    f = get_cn_font(16)
    canvas = Image.new("L", (16, 16), 0)
    ImageDraw.Draw(canvas).text((0, 0), ch, font=f, fill=255, anchor="lt")
    px = canvas.load()
    g = grid_new(16, 16)
    for y in range(16):
        for x in range(16):
            if px[x, y] >= CN_THRESHOLD:
                g[y][x] = color
    return g


def glyph_grid(ch, size, box_w, box_h, threshold=110):
    """把字符渲染成 box_w x box_h 的颜色字符网格（'.' 或 'W'）。"""
    f = get_font(size)
    canvas = Image.new("L", (size * 4, size * 4), 0)
    d = ImageDraw.Draw(canvas)
    d.text((size, size), ch, font=f, fill=255)
    bbox = canvas.getbbox()
    g = grid_new(box_w, box_h)
    if not bbox:
        return g
    glyph = canvas.crop(bbox)
    scale = min(box_w / glyph.width, box_h / glyph.height)
    nw = max(1, min(box_w, round(glyph.width * scale)))
    nh = max(1, min(box_h, round(glyph.height * scale)))
    glyph = glyph.resize((nw, nh), Image.LANCZOS)
    ox = (box_w - nw) // 2
    oy = (box_h - nh) // 2
    px = glyph.load()
    for y in range(nh):
        for x in range(nw):
            if px[x, y] >= threshold:
                g[oy + y][ox + x] = "W"
    return g


def paint(grid, src, dx=0, dy=0, color=None):
    """把 src 网格叠到 grid 上，'.' 视为透明。"""
    for y, row in enumerate(src):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            ty, tx = y + dy, x + dx
            if 0 <= ty < len(grid) and 0 <= tx < len(grid[0]):
                grid[ty][tx] = V2C[color] if color else ch


# ---------------- 生成图块 ----------------
tiles = [blank_tile() for _ in range(TILE_COUNT)]


def put(idx, data):
    assert 0 <= idx < TILE_COUNT
    tiles[idx] = data


# 0-9 / A-Z / 符号：统一用 8x8 小字模
for i in range(10):
    put(T_DIGITS + i, from_grid(glyph_grid(str(i), 10, 8, 8), 0, 0))
for i in range(26):
    put(T_LETTERS + i, from_grid(glyph_grid(chr(ord("A") + i), 10, 8, 8), 0, 0))
for i, ch in enumerate(SYMBOLS):
    put(T_SYMBOLS + i, from_grid(glyph_grid(ch, 10, 8, 8), 0, 0))

# 边框
put(T_BORDER_H, from_rows([
    "........",
    "........",
    "........",
    "WWWWWWWW",
    "WWWWWWWW",
    "........",
    "........",
    "........",
]))
put(T_BORDER_V, from_rows(["...WW..."] * 8))


def corner(kind):
    g = grid_new(8, 8)
    for y in range(8):
        for x in range(8):
            h = y in (3, 4)
            v = x in (3, 4)
            if kind == "tl":
                ok = (h and x >= 3) or (v and y >= 3)
            elif kind == "tr":
                ok = (h and x <= 4) or (v and y >= 3)
            elif kind == "bl":
                ok = (h and x >= 3) or (v and y <= 4)
            else:
                ok = (h and x <= 4) or (v and y <= 4)
            if ok:
                g[y][x] = "W"
    return from_grid(g, 0, 0)


put(T_CORNER_TL, corner("tl"))
put(T_CORNER_TR, corner("tr"))
put(T_CORNER_BL, corner("bl"))
put(T_CORNER_BR, corner("br"))

# 蛇身：绿色圆角方块 + 白色内框
BODY = [
    ".GGGGGG.",
    "GWWWWWWG",
    "GWGGGGWG",
    "GWGGGGWG",
    "GWGGGGWG",
    "GWGGGGWG",
    "GWWWWWWG",
    ".GGGGGG.",
]
put(T_BODY, from_rows(BODY))


def head(direction):
    g = [list(r) for r in BODY]
    eyes = {
        "U": [(2, 2), (2, 5)],
        "D": [(5, 2), (5, 5)],
        "L": [(2, 2), (5, 2)],
        "R": [(2, 5), (5, 5)],
    }[direction]
    for y, x in eyes:
        g[y][x] = "R"
    # 鼻尖方向加一点白，突出朝向
    if direction == "U":
        g[1][3] = g[1][4] = "R"
    elif direction == "D":
        g[6][3] = g[6][4] = "R"
    elif direction == "L":
        g[3][1] = g[4][1] = "R"
    else:
        g[3][6] = g[4][6] = "R"
    return from_rows(["".join(r) for r in g])


put(T_HEAD_U, head("U"))
put(T_HEAD_R, head("R"))
put(T_HEAD_D, head("D"))
put(T_HEAD_L, head("L"))

# 食物：红宝石（两种帧用于闪烁）
put(T_FOOD, from_rows([
    "..RRRR..",
    ".RWWRRR.",
    "RWWRRRRR",
    "RRRRRRRR",
    "RRRRRRRR",
    "RRRRRRRR",
    ".RRRRRR.",
    "..RRRR..",
]))
put(T_FOOD_ALT, from_rows([
    "..WWWW..",
    ".WWWRWW.",
    "WWWRRRWW",
    "WWRRRRRW",
    "WWRRRRRW",
    "WWRRRRRW",
    ".WRRRRW.",
    "..WWWW..",
]))

put(T_STAR, from_rows([
    "........",
    "...W....",
    "..WWW...",
    ".WWWWW..",
    "..WWW...",
    "...W....",
    "........",
    "........",
]))
put(T_DOT, from_rows([
    "........",
    "........",
    "...WW...",
    "...WW...",
    "........",
    "........",
    "........",
    "........",
]))

# 大字表：24x24，白色右下阴影 + 绿色字面
# 用于标题 SNAKE 与结束画面 GAME OVER
for li, ch in enumerate(BIG_LETTERS):
    g = grid_new(24, 24)
    glyph = glyph_grid(ch, 26, 22, 22, threshold=100)
    paint(g, glyph, dx=1, dy=2, color=1)   # 白色阴影
    paint(g, glyph, dx=0, dy=0, color=2)   # 绿色字面
    for r in range(3):
        for c in range(3):
            put(T_BIG + li * 9 + r * 3 + c, from_grid(g, c * 8, r * 8))

# 中文点阵：数字用绿色突出年份，汉字用白色
for i, ch in enumerate(CN_MAP):
    g = cn_glyph(ch, "G" if ch in CN_DIGITS else "W")
    base = T_CN + i * 4
    put(base + 0, from_grid(g, 0, 0))      # 左上
    put(base + 1, from_grid(g, 8, 0))      # 右上
    put(base + 2, from_grid(g, 0, 8))      # 左下
    put(base + 3, from_grid(g, 8, 8))      # 右下

# ---------------- 输出 ----------------
chr_data = b"".join(tiles)
assert len(chr_data) == 8192, len(chr_data)
with open(os.path.join(ROOT, "chr.bin"), "wb") as f:
    f.write(chr_data)

inc = [
    "; Generated by tools/make_chr.py - do not edit by hand",
    "; Tile indices in CHR-ROM (each tile occupies 16 bytes)",
]
for name, val in ASSIGNED.items():
    inc.append(f"{name} = ${val:02X}")
inc.append("T_BIG_COUNT = 9        ; 3x3 tiles per big letter")
inc.append(f"; BIG_LETTERS = {BIG_LETTERS}")
inc.append("; CN_MAP_HEX = " + " ".join(f"{ord(c):04X}" for c in CN_MAP))
inc.append("T_CN_COUNT = 4         ; 2x2 tiles per 16x16 CJK glyph")
inc.append("")
inc.append("; 4-color palette indices")
inc.append("COL_BG   = 0")
inc.append("COL_WHITE = 1")
inc.append("COL_GREEN = 2")
inc.append("COL_RED   = 3")
with open(os.path.join(ROOT, "src", "tiles.inc"), "w", encoding="ascii") as f:
    f.write("\n".join(inc) + "\n")

# 预览图：前 256 个 tile（含中文点阵），16 列，放大 6 倍
SCALE = 6
COLS = 16
ROWS = 16
CELL = 8 * SCALE
img = Image.new("RGB", (COLS * CELL, ROWS * CELL), (24, 24, 30))
d = ImageDraw.Draw(img)
for idx in range(COLS * ROWS):
    data = tiles[idx]
    cx, cy = (idx % COLS) * CELL, (idx // COLS) * CELL
    for y in range(8):
        b0, b1 = data[y], data[8 + y]
        for x in range(8):
            bit = 7 - x
            v = ((b0 >> bit) & 1) | (((b1 >> bit) & 1) << 1)
            d.rectangle(
                [cx + x * SCALE, cy + y * SCALE,
                 cx + (x + 1) * SCALE - 1, cy + (y + 1) * SCALE - 1],
                fill=PREVIEW_RGB[v],
            )
    d.rectangle([cx, cy, cx + CELL - 1, cy + CELL - 1], outline=(70, 70, 90))
    d.text((cx + 2, cy + 1), f"{idx:02X}", fill=(255, 210, 80))
img.save(os.path.join(HERE, "chr_preview.png"))

print(f"CHR 生成完毕：{len(chr_data)} 字节，已用图块 {_nxt}/512")
print("图块分配：" + ", ".join(f"{k}=${v:02X}" for k, v in ASSIGNED.items()))
