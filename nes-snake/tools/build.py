#!/usr/bin/env python3
"""把 ld65 产出的 32KB PRG 与 8KB CHR 拼成 iNES ROM。"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRG_PATH = os.path.join(ROOT, "build", "snake.prg")
CHR_PATH = os.path.join(ROOT, "chr.bin")
OUT_PATH = os.path.join(ROOT, "snake.nes")

with open(PRG_PATH, "rb") as f:
    prg = f.read()
with open(CHR_PATH, "rb") as f:
    chrrom = f.read()

if len(prg) != 32768:
    raise SystemExit(f"PRG 应为 32768 字节，实际 {len(prg)}；检查链接配置 fill")
if len(chrrom) != 8192:
    raise SystemExit(f"CHR 应为 8192 字节，实际 {len(chrrom)}")

# iNES header: NROM (mapper 0), 2x16KB PRG, 1x8KB CHR, vertical mirroring
header = b"NES\x1a" + bytes([
    2,          # PRG-ROM units (16KB)
    1,          # CHR-ROM units (8KB)
    0x01,       # flags6: vertical mirroring, mapper low nibble = 0
    0x00,       # flags7: mapper high nibble = 0
    0x00,       # flags8: PRG-RAM size
    0x00,       # flags9: NTSC
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
])
assert len(header) == 16

reset_vec = prg[0x7FFC:0x7FFE]
nmi_vec = prg[0x7FFA:0x7FFC]
reset_addr = reset_vec[0] | (reset_vec[1] << 8)
nmi_addr = nmi_vec[0] | (nmi_vec[1] << 8)
if not (0x8000 <= reset_addr <= 0xFFFF) or not (0x8000 <= nmi_addr <= 0xFFFF):
    raise SystemExit(f"复位/NMI 向量异常: reset=${reset_addr:04X} nmi=${nmi_addr:04X}")

rom = header + prg + chrrom
with open(OUT_PATH, "wb") as f:
    f.write(rom)

print(f"snake.nes 生成完毕：{len(rom)} 字节")
print(f"  PRG 32768 / CHR 8192 / mapper 0 (NROM-256) / 垂直镜像 / NTSC")
print(f"  RESET=${reset_addr:04X}  NMI=${nmi_addr:04X}")
