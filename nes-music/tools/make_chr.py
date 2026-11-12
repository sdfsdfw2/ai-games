#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《NES 音乐盒》的 8KB CHR-ROM 图块表。

每个 tile 8x8 / 2bit，16 字节。颜色索引 0=黑 1=白 2=绿 3=红，
与汇编 palette 的 4 个条目、网页渲染器的 PAL 表一致。

图块预算受 nametable 的 8 位索引限制（最多 256 个）：
  ASCII 字模 51 + UI 图块 25 + 41 个汉字 x 4 = 240 个，留 16 个余量。
"""

import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from songlib import cn_charset

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CN_FONT_SPEC = "Noto Sans CJK SC:style=Regular"
CN_THRESHOLD = 110

TILE_COUNT = 512
C2V = {".": 0, "W": 1, "G": 2, "R": 3}
V2C = {1: "W", 2: "G", 3: "R"}
PREVIEW_RGB = [(16, 16, 20), (238, 238, 238), (86, 214, 96), (226, 62, 62)]

# ---------------- 图块索引分配 ----------------
SYMBOLS = ":-.!?/+<>*=,()"
T_BLANK = 0x00
T_DIGITS = 0x01
T_LETTERS = T_DIGITS + 10
T_SYMBOLS = T_LETTERS + 26

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


# 边框
T_BORDER_H = alloc("T_BORDER_H")
T_BORDER_V = alloc("T_BORDER_V")
T_CORNER_TL = alloc("T_CORNER_TL")
T_CORNER_TR = alloc("T_CORNER_TR")
T_CORNER_BL = alloc("T_CORNER_BL")
T_CORNER_BR = alloc("T_CORNER_BR")

# 频谱柱：8 种高度，索引 T_VIZ + (h-1)
T_VIZ = _nxt
ASSIGNED["T_VIZ"] = T_VIZ
_nxt += 8

# 进度条
T_BAR_EMPTY = alloc("T_BAR_EMPTY")
T_BAR_FULL = alloc("T_BAR_FULL")
T_BAR_HEAD = alloc("T_BAR_HEAD")

# 控制图标
T_PLAY = alloc("T_PLAY")
T_PAUSE = alloc("T_PAUSE")
T_STOP = alloc("T_STOP")
T_NOTE = alloc("T_NOTE")
T_ARROW = alloc("T_ARROW")
T_CURSOR = alloc("T_CURSOR")

# 装饰
T_STAR = alloc("T_STAR")
T_DOT = alloc("T_DOT")

# 中文点阵：每个 16x16 汉字占 2x2 = 4 个 tile
CN_MAP = cn_charset()
T_CN = _nxt
ASSIGNED["T_CN"] = T_CN
_nxt += len(CN_MAP) * 4

assert _nxt <= 256, f"图块索引超出 nametable 8 位上限: {_nxt}"
assert _nxt <= TILE_COUNT, "图块数量超出 CHR-ROM 容量"


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


def grid_new(w, h):
    return [["."] * w for _ in range(h)]


_font_cache = {}


def get_font(size):
    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(FONT_PATH, size)
    return _font_cache[size]


def get_cn_font():
    if "cn" not in _font_cache:
        try:
            spec = subprocess.check_output(
                ["fc-match", "-f", "%{file}|%{index}", CN_FONT_SPEC], text=True
            )
            path, idx = spec.split("|")
            _font_cache["cn"] = ImageFont.truetype(path, 16, index=int(idx))
        except Exception:
            _font_cache["cn"] = ImageFont.truetype(
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 16, index=2
            )
    return _font_cache["cn"]


def glyph_grid(ch, size, box_w, box_h, threshold=110):
    f = get_font(size)
    canvas = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(canvas).text((size, size), ch, font=f, fill=255)
    bbox = canvas.getbbox()
    g = grid_new(box_w, box_h)
    if not bbox:
        return g
    glyph = canvas.crop(bbox)
    scale = min(box_w / glyph.width, box_h / glyph.height)
    nw = max(1, min(box_w, round(glyph.width * scale)))
    nh = max(1, min(box_h, round(glyph.height * scale)))
    glyph = glyph.resize((nw, nh), Image.LANCZOS)
    ox, oy = (box_w - nw) // 2, (box_h - nh) // 2
    px = glyph.load()
    for y in range(nh):
        for x in range(nw):
            if px[x, y] >= threshold:
                g[oy + y][ox + x] = "W"
    return g


def cn_glyph(ch, color="G"):
    """汉字渲染成 16x16 颜色网格；绿色字面在黑底上最醒目。"""
    f = get_cn_font()
    canvas = Image.new("L", (16, 16), 0)
    ImageDraw.Draw(canvas).text((0, 0), ch, font=f, fill=255, anchor="lt")
    px = canvas.load()
    g = grid_new(16, 16)
    for y in range(16):
        for x in range(16):
            if px[x, y] >= CN_THRESHOLD:
                g[y][x] = color
    return g


# ---------------- 生成图块 ----------------
tiles = [blank_tile() for _ in range(TILE_COUNT)]


def put(idx, data):
    assert 0 <= idx < TILE_COUNT
    tiles[idx] = data


for i in range(10):
    put(T_DIGITS + i, from_grid(glyph_grid(str(i), 10, 8, 8), 0, 0))
for i in range(26):
    put(T_LETTERS + i, from_grid(glyph_grid(chr(ord("A") + i), 10, 8, 8), 0, 0))
for i, ch in enumerate(SYMBOLS):
    put(T_SYMBOLS + i, from_grid(glyph_grid(ch, 10, 8, 8), 0, 0))

# 边框
put(T_BORDER_H, from_rows([
    "........", "........", "........", "WWWWWWWW",
    "WWWWWWWW", "........", "........", "........",
]))
put(T_BORDER_V, from_rows(["...WW..."] * 8))


def corner(kind):
    g = grid_new(8, 8)
    for y in range(8):
        for x in range(8):
            h, v = y in (3, 4), x in (3, 4)
            if kind == "tl":
                ok = (h and x >= 3) or (v and y >= 3)
            elif kind == "tr":
                ok = (h and x <= 4) or (v and y >= 3)
            elif kind == "bl":
                ok = (h and x >= 3) or (v and y <= 4)
            else:
                ok = (h and x >= 3) or (v and y <= 4)
            if ok:
                g[y][x] = "W"
    return from_grid(g, 0, 0)


put(T_CORNER_TL, corner("tl"))
put(T_CORNER_TR, corner("tr"))
put(T_CORNER_BL, corner("bl"))
put(T_CORNER_BR, corner("br"))

# 频谱柱：高度 1..8，柱体绿色，顶端一格红色高亮
for h in range(1, 9):
    rows = []
    for y in range(8):
        if y >= 8 - h:
            rows.append(".RRRRRR." if y == 8 - h else ".GGGGGG.")
        else:
            rows.append("........")
    put(T_VIZ + h - 1, from_rows(rows))

# 进度条
# 空槽只留上下两条细线，横向拼接成一条「轨道」；填充与游标为实心块
put(T_BAR_EMPTY, from_rows([
    "........", "GGGGGGGG", "........", "........",
    "........", "........", "GGGGGGGG", "........",
]))
put(T_BAR_FULL, from_rows(["GGGGGGGG"] * 8))
put(T_BAR_HEAD, from_rows(["WWWWWWWW"] * 8))

# 控制图标
put(T_PLAY, from_rows([
    "........", ".GG.....", ".GGG....", ".GGGG...",
    ".GGGGG..", ".GGGG...", ".GGG....", ".GG.....",
]))
put(T_PAUSE, from_rows([
    "........", ".GG.GG..", ".GG.GG..", ".GG.GG..",
    ".GG.GG..", ".GG.GG..", ".GG.GG..", "........",
]))
put(T_STOP, from_rows([
    "........", ".RRRRRR.", ".RRRRRR.", ".RRRRRR.",
    ".RRRRRR.", ".RRRRRR.", ".RRRRRR.", "........",
]))
put(T_NOTE, from_rows([
    "....WW..", "...WWW..", "...W.W..", "...W.W..",
    "...W.WW.", "..WWW.WW", ".WWW..W.", ".WW.....",
]))
put(T_ARROW, from_rows([
    "........", "........", ".W......", ".WW.....",
    ".WWWWWW.", ".WW.....", ".W......", "........",
]))
put(T_CURSOR, from_rows([
    "........", ".RR.....", ".RRR....", ".RRRR...",
    ".RRRRR..", ".RRRR...", ".RRR....", ".RR.....",
]))

put(T_STAR, from_rows([
    "........", "...W....", "..WWW...", ".WWWWW..",
    "..WWW...", "...W....", "........", "........",
]))
put(T_DOT, from_rows([
    "........", "........", "...WW...", "...WW...",
    "........", "........", "........", "........",
]))

# 中文点阵（绿色）
for i, ch in enumerate(CN_MAP):
    g = cn_glyph(ch, "G")
    base = T_CN + i * 4
    put(base + 0, from_grid(g, 0, 0))
    put(base + 1, from_grid(g, 8, 0))
    put(base + 2, from_grid(g, 0, 8))
    put(base + 3, from_grid(g, 8, 8))

# ---------------- 输出 ----------------
chr_data = b"".join(tiles)
assert len(chr_data) == 8192
with open(os.path.join(ROOT, "chr.bin"), "wb") as f:
    f.write(chr_data)

inc = [
    "; Generated by tools/make_chr.py - do not edit by hand",
    "; Tile indices in CHR-ROM (each tile occupies 16 bytes)",
]
for name, val in ASSIGNED.items():
    inc.append(f"{name} = ${val:02X}")
inc.append(f'; SYMBOLS = "{SYMBOLS}"')
inc.append("T_VIZ_COUNT = 8         ; spectrum bar heights 1..8")
inc.append("T_CN_COUNT = 4          ; 2x2 tiles per 16x16 CJK glyph")
inc.append("; CN_MAP_HEX = " + " ".join(f"{ord(c):04X}" for c in CN_MAP))
inc.append("")
inc.append("; 4-color palette indices")
inc.append("COL_BG    = 0")
inc.append("COL_WHITE = 1")
inc.append("COL_GREEN = 2")
inc.append("COL_RED   = 3")
with open(os.path.join(ROOT, "src", "tiles.inc"), "w", encoding="ascii") as f:
    f.write("\n".join(inc) + "\n")

# 预览图：前 256 个 tile
SCALE, COLS, ROWS, CELL = 5, 16, 16, 40
img = Image.new("RGB", (COLS * CELL, ROWS * CELL), (24, 24, 30))
d = ImageDraw.Draw(img)
for idx in range(COLS * ROWS):
    data = tiles[idx]
    cx, cy = (idx % COLS) * CELL, (idx // COLS) * CELL
    for y in range(8):
        b0, b1 = data[y], data[8 + y]
        for x in range(8):
            v = ((b0 >> (7 - x)) & 1) | (((b1 >> (7 - x)) & 1) << 1)
            d.rectangle(
                [cx + x * SCALE, cy + y * SCALE,
                 cx + (x + 1) * SCALE - 1, cy + (y + 1) * SCALE - 1],
                fill=PREVIEW_RGB[v],
            )
    d.rectangle([cx, cy, cx + CELL - 1, cy + CELL - 1], outline=(70, 70, 90))
    d.text((cx + 2, cy + 1), f"{idx:02X}", fill=(255, 210, 80))
img.save(os.path.join(HERE, "chr_preview.png"))

print(f"CHR 生成完毕：8192 字节，已用图块 {_nxt}/256（剩余 {256 - _nxt}）")
print(f"  ASCII {T_SYMBOLS + len(SYMBOLS)} + UI {T_CN - T_SYMBOLS - len(SYMBOLS)} "
      f"+ 汉字 {len(CN_MAP)}x4 = {_nxt}")
print("  图块分配：" + ", ".join(f"{k}=${v:02X}" for k, v in ASSIGNED.items()))
