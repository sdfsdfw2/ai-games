#!/usr/bin/env bash
# 一键构建 music.nes（需要 cc65 工具链与 Python 3 + Pillow + Noto CJK 字体）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build

python3.11 tools/make_songs.py
python3.11 tools/make_chr.py
python3.11 tools/make_screens.py

ca65 --cpu 6502 -I src -o build/music.o src/music.s
ld65 -C src/music.cfg -m build/music.map -o build/music.prg build/music.o
python3.11 tools/build.py
