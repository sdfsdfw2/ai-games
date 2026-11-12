#!/usr/bin/env python3
"""把 verify.js 导出的 nametable 快照渲染成 PNG（绕过模拟器的帧缓冲）。"""

import os
from pathlib import Path
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = Path(ROOT) / "tools" / "shots"
CHR = (Path(ROOT) / "chr.bin").read_bytes()

RGB = [(16, 16, 20), (238, 238, 238), (86, 214, 96), (226, 62, 62)]

count = 0
for nt_path in sorted(OUT.glob("*.nt")):
    nt = nt_path.read_bytes()
    assert len(nt) == 960
    img = Image.new("RGB", (256, 240))
    px = img.load()
    for ty in range(30):
        for txi in range(32):
            tile = nt[ty * 32 + txi]
            data = CHR[tile * 16: tile * 16 + 16]
            for y in range(8):
                b0, b1 = data[y], data[8 + y]
                for x in range(8):
                    bit = 7 - x
                    v = ((b0 >> bit) & 1) | (((b1 >> bit) & 1) << 1)
                    px[txi * 8 + x, ty * 8 + y] = RGB[v]
    img.resize((512, 480), Image.NEAREST).save(nt_path.with_suffix(".png"))
    count += 1
    print(f"{nt_path.name} -> {nt_path.with_suffix('.png').name}")

print(f"共渲染 {count} 张画面快照")
