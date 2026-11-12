#!/usr/bin/env python3
"""把 ld65 产出的 32KB PRG 与 8KB CHR 拼成 iNES ROM。"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRG_PATH = os.path.join(ROOT, "build", "music.prg")
CHR_PATH = os.path.join(ROOT, "chr.bin")
OUT_PATH = os.path.join(ROOT, "music.nes")

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
    2, 1, 0x01, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
])
assert len(header) == 16

reset_vec = prg[0x7FFC:0x7FFE]
nmi_vec = prg[0x7FFA:0x7FFC]
irq_vec = prg[0x7FFE:0x8000]
reset_addr = reset_vec[0] | (reset_vec[1] << 8)
nmi_addr = nmi_vec[0] | (nmi_vec[1] << 8)
irq_addr = irq_vec[0] | (irq_vec[1] << 8)
if not (0x8000 <= reset_addr <= 0xFFFF) or not (0x8000 <= nmi_addr <= 0xFFFF):
    raise SystemExit(f"复位/NMI 向量异常: reset=${reset_addr:04X} nmi=${nmi_addr:04X}")

# 统计 PRG 实际使用量：末尾 6 字节是中断向量（恒非零），先排除再去掉填充
body = prg[:-6]
used = len(body.rstrip(b"\x00")) + 6

rom = header + prg + chrrom
with open(OUT_PATH, "wb") as f:
    f.write(rom)

print(f"music.nes 生成完毕：{len(rom)} 字节")
print(f"  PRG 32768 / CHR 8192 / mapper 0 (NROM-256) / 垂直镜像 / NTSC")
print(f"  RESET=${reset_addr:04X}  NMI=${nmi_addr:04X}  IRQ=${irq_addr:04X}")
print(f"  PRG 有效数据约 {used} 字节 ({used/1024:.1f} KB / 32 KB, "
      f"剩余 {(32768-used)/1024:.1f} KB)")
