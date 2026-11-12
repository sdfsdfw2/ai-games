#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《NES 音乐盒》曲库定义与 APU 曲目编译器（全工程的单一数据源）。

版权说明
--------
本曲库只收录两类旋律：
  1) 公有领域的古典 / 传统民谣主题（作者逝世已久，旋律本身进入公有领域），
     这里的 8-bit 编曲与配器为本项目重新制作；
  2) 本项目 2026 年原创的芯片音乐旋律（基于音阶与和弦进行写作，
     不对应任何现有流行歌曲）。
不含任何受版权保护的当代流行歌曲旋律。

记谱法
------
每个 token 形如 ``E4/4``（音名 + 八度 / 时值），时值单位 = tick：
  4 = 四分音符, 2 = 八分, 1 = 十六分, 8 = 二分, 16 = 全音符
  ``R`` = 休止, ``-`` = 延续上一个音
  ``#`` / ``b`` = 升 / 降半音
每首只写主旋律；和声、低音、打击由编译器按调性与风格自动生成，
再把 4 个声部按时间轴对齐、RLE 压缩成固定 6 字节事件流：

    [dur, sq1, sq2, tri, noise, bar]

  dur   = 该事件持续的 tick 数（0 = 曲目结束标记）
  sq*   = 0 静音 / 1..60 音符索引 / $FE 保持上一音符
  noise = 0 静音 / 1..8 打击类型 / $FE 保持
  bar   = 进度条位置 0..20，由编译器按累计 tick 预先算好，运行时零计算
"""

import math

CPU_HZ = 1789772.727          # NTSC 2A03 主频
NOTE_LO_MIDI = 36             # 音符索引 1 = MIDI 36 (C2)
NOTE_HI_MIDI = 95             # 音符索引 60 = MIDI 95 (B6)
NOTE_COUNT = NOTE_HI_MIDI - NOTE_LO_MIDI + 1
HOLD = 0xFE                   # 保持上一音符，不重写 APU 寄存器

NOTE_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# 噪声打击类型 1..8 -> $400E 的周期/模式字节（索引 0 对应类型 1）
NOISE_PERIOD = [0x0F, 0x08, 0x03, 0x01, 0x1C, 0x0B, 0x05, 0x00]
# 各打击类型的音量（写入 $400C 时使用恒定音量模式）
NOISE_VOLUME = [3, 5, 7, 4, 2, 6, 4, 3]

# 标题画面 / 曲目表需要的额外汉字（曲名之外的用字）
EXTRA_CN = "年新作芯片音乐盒曲目表"

# kind: 0 = 古典, 1 = 传统民谣, 2 = 2026 原创
KIND_CLASSIC, KIND_FOLK, KIND_ORIGINAL = 0, 1, 2

SONGS = [
    # ---------------- 公有领域：古典 ----------------
    dict(
        cn="欢乐颂", en="ODE TO JOY", kind=KIND_CLASSIC,
        key=60, chords=[0, 7, 9, 5], style="march", tempo=8, loop=2,
        lead=(
            "E4/4 E4/4 F4/4 G4/4 G4/4 F4/4 E4/4 D4/4 "
            "C4/4 C4/4 D4/4 E4/4 E4/6 D4/2 D4/8 "
            "E4/4 E4/4 F4/4 G4/4 G4/4 F4/4 E4/4 D4/4 "
            "C4/4 C4/4 D4/4 E4/4 D4/6 C4/2 C4/8"
        ),
    ),
    dict(
        cn="爱丽丝", en="FUR ELISE", kind=KIND_CLASSIC,
        key=57, chords=[0, 7, 5, 7], style="ballad", tempo=7, loop=2,
        lead=(
            "E5/2 D#5/2 E5/2 D#5/2 E5/2 B4/2 D5/2 C5/2 "
            "A4/4 C4/2 E4/2 A4/2 B4/4 E4/2 G#4/2 B4/2 "
            "C5/4 E4/2 E5/2 D#5/2 E5/2 D#5/2 E5/2 B4/2 "
            "D5/2 C5/2 A4/4 C4/2 E4/2 A4/2 B4/4 E4/2 C5/2 B4/2 A4/8"
        ),
    ),
    dict(
        cn="卡农", en="CANON", kind=KIND_CLASSIC,
        key=62, chords=[0, 7, 9, 5], style="waltz", tempo=8, loop=2,
        lead=(
            "F#5/4 E5/4 D5/4 C#5/4 B4/4 A4/4 B4/4 C#5/4 "
            "D5/4 C#5/4 B4/4 A4/4 G4/4 F#4/4 G4/4 E4/4 "
            "F#5/4 E5/4 D5/4 C#5/4 B4/4 A4/4 B4/4 C#5/4 "
            "D5/4 E5/4 F#5/4 G5/4 A5/4 G5/4 F#5/4 E5/8"
        ),
    ),
    dict(
        cn="小步舞", en="MINUET", kind=KIND_CLASSIC,
        key=55, chords=[0, 7, 9, 5], style="waltz", tempo=8, loop=2,
        lead=(
            "D5/4 G4/2 A4/2 B4/2 C5/2 D5/4 G4/4 G4/4 "
            "E5/4 C5/2 D5/2 E5/2 F#5/2 G5/4 G4/4 G4/4 "
            "D5/4 B4/2 C5/2 D5/2 E5/2 C5/4 D5/4 C5/4 "
            "B4/4 A4/4 G4/8"
        ),
    ),
    dict(
        cn="进行曲", en="TURKISH MARCH", kind=KIND_CLASSIC,
        key=57, chords=[0, 7, 5, 7], style="march", tempo=6, loop=2,
        lead=(
            "B4/2 A4/2 G#4/2 A4/2 C5/4 A4/2 C5/2 E5/4 "
            "D5/2 C5/2 B4/4 A4/2 B4/2 C5/4 E5/2 D5/2 "
            "C5/4 B4/2 A4/2 B4/2 C5/2 A4/2 B4/2 C5/2 "
            "E5/4 C5/4 A4/4 B4/8"
        ),
    ),
    # ---------------- 公有领域：传统民谣 ----------------
    dict(
        cn="小星星", en="TWINKLE", kind=KIND_FOLK,
        key=60, chords=[0, 7, 9, 7], style="march", tempo=9, loop=2,
        lead=(
            "C4/4 C4/4 G4/4 G4/4 A4/4 A4/4 G4/8 "
            "F4/4 F4/4 E4/4 E4/4 D4/4 D4/4 C4/8 "
            "G4/4 G4/4 F4/4 F4/4 E4/4 E4/4 D4/8 "
            "G4/4 G4/4 F4/4 F4/4 E4/4 E4/4 D4/8 "
            "C4/4 C4/4 G4/4 G4/4 A4/4 A4/4 G4/8 "
            "F4/4 F4/4 E4/4 E4/4 D4/4 D4/4 C4/8"
        ),
    ),
    dict(
        cn="绿袖子", en="GREENSLEEVES", kind=KIND_FOLK,
        key=57, chords=[0, 5, 7, 3], style="waltz", tempo=9, loop=2,
        lead=(
            "A4/4 C5/4 D5/6 E5/2 F5/4 E5/4 D5/6 B4/2 "
            "G4/4 A4/4 B4/6 C5/2 A4/4 A4/4 G#4/6 A4/2 "
            "B4/4 G#4/4 E4/8 A4/4 C5/4 D5/6 E5/2 "
            "F5/4 E5/4 D5/6 B4/2 G4/4 A4/4 B4/6 C5/2 "
            "A4/4 A4/4 G#4/6 A4/2 B4/4 G#4/4 A4/8"
        ),
    ),
    dict(
        cn="铃儿响", en="JINGLE BELLS", kind=KIND_FOLK,
        key=60, chords=[0, 7, 9, 5], style="march", tempo=6, loop=2,
        lead=(
            "E4/4 E4/4 E4/8 E4/4 E4/4 E4/8 "
            "E4/4 G4/4 C4/4 D4/4 E4/16 "
            "F4/4 F4/4 F4/4 F4/4 F4/4 E4/4 E4/4 "
            "E4/2 E4/2 E4/4 G4/4 G4/4 E4/4 D4/4 C4/8"
        ),
    ),
    dict(
        cn="送别", en="FAREWELL", kind=KIND_FOLK,
        key=60, chords=[0, 5, 7, 5], style="ballad", tempo=11, loop=2,
        lead=(
            "G4/4 E4/2 G4/2 C5/8 A4/4 C5/4 G4/8 "
            "G4/4 C4/2 E4/2 D4/8 "
            "G4/4 E4/2 G4/2 C5/8 B4/4 A4/4 G4/4 E4/4 D4/8"
        ),
    ),
    # ---------------- 2026 原创芯片音乐 ----------------
    # 以下旋律均为本项目按音阶/和弦进行写作的原创句子，不对应任何现有歌曲。
    dict(
        cn="星海", en="STAR VOYAGE", kind=KIND_ORIGINAL,
        key=62, chords=[0, 5, 7, 3], style="ambient", tempo=10, loop=2,
        lead=(
            "D5/8 F5/8 A5/8 G5/8 F5/4 E5/4 D5/8 "
            "C5/8 D5/8 F5/8 A5/8 C6/8 A5/8 G5/8 "
            "F5/8 E5/8 D5/16"
        ),
    ),
    dict(
        cn="夜曲", en="NOCTURNE", kind=KIND_ORIGINAL,
        key=57, chords=[0, 3, 7, 5], style="ballad", tempo=11, loop=2,
        lead=(
            "A4/6 C5/2 B4/4 A4/4 E4/8 "
            "A4/6 C5/2 E5/4 D5/4 C5/8 "
            "B4/4 A4/4 G4/4 E4/4 A4/8 "
            "C5/6 E5/2 D5/4 C5/4 B4/8 "
            "A4/4 C5/4 B4/4 G#4/4 A4/16"
        ),
    ),
    dict(
        cn="像素心", en="PIXEL HEART", kind=KIND_ORIGINAL,
        key=60, chords=[0, 7, 9, 5], style="dance", tempo=5, loop=2,
        lead=(
            "C5/2 E5/2 G5/2 C6/4 G5/2 E5/2 C5/4 "
            "D5/2 F5/2 A5/2 D6/4 A5/2 F5/2 D5/4 "
            "E5/2 G5/2 B5/2 E6/4 G5/2 E5/2 C5/8"
        ),
    ),
    dict(
        cn="霓虹", en="NEON RUN", kind=KIND_ORIGINAL,
        key=64, chords=[0, 7, 5, 3], style="dance", tempo=5, loop=2,
        lead=(
            "E5/2 G5/2 B5/2 E6/4 B5/2 G5/2 E5/4 "
            "D5/2 F#5/2 A5/2 D6/4 A5/2 F#5/2 D5/4 "
            "C5/2 E5/2 G5/2 C6/4 B5/4 G5/4 E5/8"
        ),
    ),
    dict(
        cn="晨雾", en="MISTY WOODS", kind=KIND_ORIGINAL,
        key=53, chords=[0, 7, 9, 5], style="waltz", tempo=9, loop=2,
        lead=(
            "F5/6 A5/2 C6/4 A5/4 F5/8 "
            "C5/4 F5/4 A5/4 C6/8 A5/6 G5/2 "
            "F5/4 E5/4 D5/8 F5/4 A5/4 C6/4 A5/4 F5/16"
        ),
    ),
    # 以下 6 首刻意复用已有汉字命名：PRG 尚有余量，而 CHR 中文字表已固定，
    # 这样可以在不增加任何图块占用的前提下把曲库扩到 20 首。
    dict(
        cn="星夜", en="STARRY NIGHT", kind=KIND_ORIGINAL,
        key=62, chords=[0, 5, 7, 9], style="ambient", tempo=10, loop=2,
        lead=(
            "A4/8 D5/8 F#5/8 E5/8 D5/4 C#5/4 B4/8 "
            "A4/8 B4/8 C#5/8 D5/8 F#5/8 A5/8 F#5/8 E5/8 D5/16"
        ),
    ),
    dict(
        cn="晨星", en="MORNING STAR", kind=KIND_ORIGINAL,
        key=53, chords=[0, 7, 9, 5], style="waltz", tempo=8, loop=2,
        lead=(
            "C5/4 F5/4 A5/4 C6/8 A5/4 F5/4 G5/8 "
            "A5/4 C5/4 F5/4 A5/4 G5/8 F5/4 E5/4 F5/16"
        ),
    ),
    dict(
        cn="海雾", en="SEA MIST", kind=KIND_ORIGINAL,
        key=57, chords=[0, 3, 7, 5], style="ambient", tempo=11, loop=2,
        lead=(
            "A4/8 C5/8 E5/8 D5/8 C5/8 B4/8 A4/8 "
            "G4/8 A4/8 C5/8 E5/8 A5/8 G5/8 E5/8 C5/8 A4/16"
        ),
    ),
    dict(
        cn="霓虹夜", en="NEON NIGHT", kind=KIND_ORIGINAL,
        key=64, chords=[0, 7, 5, 3], style="dance", tempo=6, loop=2,
        lead=(
            "E5/2 G5/2 B5/2 G5/2 E5/4 D5/2 E5/2 G5/2 "
            "B5/2 E6/4 B5/2 G5/2 E5/4 D5/2 F#5/2 A5/2 "
            "D6/4 A5/2 F#5/2 E5/8"
        ),
    ),
    dict(
        cn="小夜曲", en="SERENADE", kind=KIND_ORIGINAL,
        key=55, chords=[0, 7, 9, 5], style="ballad", tempo=10, loop=2,
        lead=(
            "G4/6 B4/2 D5/4 B4/4 G4/8 "
            "D5/6 G5/2 F#5/4 E5/4 D5/8 "
            "B4/4 D5/4 G5/4 F#5/4 E5/8 "
            "D5/4 B4/4 G4/4 A4/4 G4/16"
        ),
    ),
    dict(
        cn="像素曲", en="PIXEL GROOVE", kind=KIND_ORIGINAL,
        key=60, chords=[0, 7, 9, 5], style="dance", tempo=5, loop=2,
        lead=(
            "G5/2 C6/2 E6/2 G6/4 E6/2 C6/2 G5/4 "
            "A5/2 C6/2 F6/2 A6/4 F6/2 C6/2 A5/4 "
            "G5/2 B5/2 D6/2 G6/4 E6/4 C6/4 G5/8"
        ),
    ),
]


# ---------------------------------------------------------------------------
#  记谱解析
# ---------------------------------------------------------------------------
def name_to_midi(name):
    letter = name[0].upper()
    i = 1
    acc = 0
    if i < len(name) and name[i] in "#b":
        acc = 1 if name[i] == "#" else -1
        i += 1
    octave = int(name[i:])
    return 12 * (octave + 1) + NOTE_OFFSETS[letter] + acc


def clamp_idx(midi):
    return max(NOTE_LO_MIDI, min(NOTE_HI_MIDI, midi)) - NOTE_LO_MIDI + 1


def note_idx(name):
    return clamp_idx(name_to_midi(name))


def parse_lead(s, total):
    """把主旋律记谱展开成逐 tick 的音符索引数组。"""
    arr = []
    for token in s.split():
        if "/" in token:
            note, dur_s = token.rsplit("/", 1)
            dur = int(dur_s)
        else:
            note, dur = token, 4
        if note == "R":
            v = 0
        elif note == "-":
            v = None                     # 占位，稍后展开为上一个实际音
        else:
            v = note_idx(note)
        arr.extend([v] * dur)
    last = 0
    for i, v in enumerate(arr):
        if v is None:
            arr[i] = last
        else:
            last = v
    if len(arr) < total:
        arr.extend([0] * (total - len(arr)))
    return arr[:total]


def lead_length(s):
    n = 0
    for token in s.split():
        n += int(token.rsplit("/", 1)[1]) if "/" in token else 4
    return n


def make_drum(style, total):
    """按风格生成打击声部；每个打击只占 1 tick，后面自然接静音形成短音。"""
    arr = [0] * total
    hat_period = {"ambient": 8, "ballad": 4, "waltz": 4,
                  "march": 2, "dance": 2}[style]
    for t in range(total):
        if t % hat_period == 0:
            arr[t] = 1                                   # hi-hat
    for t in range(total):
        beat = t % 8
        if style == "dance":
            if beat == 0:
                arr[t] = 3                               # kick
            elif beat == 4:
                arr[t] = 2                               # snare
        elif style == "march":
            if beat == 0:
                arr[t] = 3
            elif beat == 4:
                arr[t] = 2
        elif style == "waltz":
            if beat == 0:
                arr[t] = 3
        elif style == "ballad":
            if beat == 0 and (t // 8) % 2 == 0:
                arr[t] = 3
        elif style == "ambient":
            if t % 16 == 0:
                arr[t] = 5
    return arr


def make_voices(song, total):
    """返回 4 个逐 tick 数组：主旋律 / 和声 / 低音 / 打击。"""
    lead = parse_lead(song["lead"], total)
    chords = song["chords"]
    key = song["key"]
    bass, harm = [], []
    for t in range(total):
        root = key + chords[(t // 8) % len(chords)]
        bass.append(clamp_idx(root - 12))               # 三角波低一个八度
        harm.append(clamp_idx(root + 7 - 12))           # 方波 2 奏和弦五度
    return [lead, harm, bass, make_drum(song["style"], total)]


def compile_events(voices, total):
    """4 声部对齐 -> 变化点 RLE 压缩 -> 6 字节事件流。"""
    events = []
    prev = [None] * 4
    for t in range(total):
        cur = [voices[i][t] for i in range(4)]
        delta = [HOLD if cur[i] == prev[i] else cur[i] for i in range(4)]
        bar = min(20, (t * 20) // total)
        if all(d == HOLD for d in delta):
            if events[-1][0] < 8:
                events[-1][0] += 1                     # 合并进上一事件
            else:
                # 强制打断长事件，保证进度条每 <=8 tick 就能刷新一次
                events.append([1, HOLD, HOLD, HOLD, HOLD, bar])
        else:
            events.append([1, delta[0], delta[1], delta[2], delta[3], bar])
        prev = cur
    return events


def period_tables():
    sq, tri = [], []
    for m in range(NOTE_LO_MIDI, NOTE_HI_MIDI + 1):
        f = 440.0 * (2.0 ** ((m - 69) / 12.0))
        sq.append(round(CPU_HZ / (16.0 * f)) - 1)
        tri.append(round(CPU_HZ / (32.0 * f)) - 1)
    return sq, tri


def cn_charset():
    """全部曲名 + 标题用字，去重后保持顺序；即 CHR 里 16x16 汉字点阵的字表。"""
    seen = []
    for ch in EXTRA_CN + "".join(s["cn"] for s in SONGS):
        if ch not in seen:
            seen.append(ch)
    return "".join(seen)


def build():
    """编译全部曲目，返回可供生成 songs.inc 的中间结构。"""
    sq, tri = period_tables()
    CN = cn_charset()
    out_songs = []
    for s in SONGS:
        total = lead_length(s["lead"])
        voices = make_voices(s, total)
        events = compile_events(voices, total)
        out_songs.append(dict(
            meta=s, total=total, events=events,
            name=[CN.index(ch) for ch in s["cn"]],
        ))
    return dict(period_sq=sq, period_tri=tri, CN=CN, songs=out_songs)


def stats(data):
    ev_bytes = sum(len(s["events"]) * 6 + 1 for s in data["songs"])
    table_bytes = 4 * NOTE_COUNT + len(NOISE_PERIOD) * 2 + 16 * len(data["songs"])
    name_bytes = sum(len(s["name"]) + 1 + len(s["meta"]["en"]) + 1
                     for s in data["songs"])
    return dict(
        songs=len(data["songs"]),
        cn_chars=len(data["CN"]),
        cn_tiles=len(data["CN"]) * 4,
        events=sum(len(s["events"]) for s in data["songs"]),
        song_bytes=ev_bytes + table_bytes + name_bytes,
        detail=dict(events=ev_bytes, tables=table_bytes, names=name_bytes),
    )


if __name__ == "__main__":
    d = build()
    st = stats(d)
    print(f"曲目: {st['songs']} 首 | 汉字: {st['cn_chars']} 字 "
          f"({st['cn_tiles']} tile) | 事件: {st['events']} 个")
    print(f"曲目数据约 {st['song_bytes']} 字节 ({st['song_bytes']/1024:.1f} KB)")
    for s in d["songs"]:
        m = s["meta"]
        print(f"  {m['cn']:<4} {m['en']:<16} {s['total']:>4} tick "
              f"-> {len(s['events']):>3} 事件")
