#!/usr/bin/env bash
# 一键构建 snake.nes（需要 cc65 工具链与 Python 3 + Pillow）
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build

python3.11 tools/make_chr.py
python3.11 tools/make_screens.py

ca65 --cpu 6502 -I src -o build/snake.o src/snake.s
ld65 -C src/snake.cfg -m build/snake.map -o build/snake.prg build/snake.o
python3.11 tools/build.py
python3.11 tools/make_play.py
