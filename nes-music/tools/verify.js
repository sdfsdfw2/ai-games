#!/usr/bin/env node
/**
 * 用 jsnes 实际运行 music.nes，验证 APU 发声、播放时钟、切歌与曲目表，
 * 并导出 nametable / 调色板快照供 render_shots.py 渲染。
 *
 * 零页地址（ld65 按声明顺序分配，ZEROPAGE 段共 $2A 字节）：
 *   state=$04 playing=$05 song_idx=$06 volume=$07
 *   tick_frames=$08 bar=$0B loop_left=$0C song_end=$0D
 *   list_sel=$0F list_page=$10 kind=$12 name_len=$13
 *   ev_ptr_lo=$16 ev_ptr_hi=$17
 */
const fs = require('fs');
const path = require('path');
const jsnes = require('../vendor/jsnes.min.js');

const ROOT = path.dirname(__dirname);
const OUT = path.join(ROOT, 'tools', 'shots');
fs.mkdirSync(OUT, { recursive: true });

const A = {
  state: 0x04, playing: 0x05, song_idx: 0x06, volume: 0x07,
  tick_frames: 0x08, bar: 0x0B, loop_left: 0x0C, song_end: 0x0D,
  list_sel: 0x0F, list_page: 0x10, kind: 0x12, name_len: 0x13,
  ev_ptr_lo: 0x16, ev_ptr_hi: 0x17,
};
const NAME_X = 12, NAME_Y = 11, BAR_Y = 16;

let samples = 0, nonZero = 0, peak = 0;
const nes = new jsnes.NES({
  onFrame: () => {},
  onAudioSample: (l, r) => {
    samples++;
    const v = Math.max(Math.abs(l), Math.abs(r));
    if (v > 0.0005) nonZero++;
    if (v > peak) peak = v;
  },
  emulateSound: true,
});

const rom = fs.readFileSync(path.join(ROOT, 'music.nes'));
nes.loadROM(rom.toString('latin1'));
const mem = nes.cpu.mem;

function run(n) { for (let i = 0; i < n; i++) nes.frame(); }
function tap(btn) {
  nes.buttonDown(1, btn);
  nes.frame();
  nes.buttonUp(1, btn);
  run(4);
}
function shot(name) {
  const vm = nes.ppu.vramMem;
  fs.writeFileSync(path.join(OUT, name + '.nt'),
    Buffer.from(vm.buffer, vm.byteOffset + 0x2000, 960));
  fs.writeFileSync(path.join(OUT, name + '.pal'),
    Buffer.from(vm.buffer, vm.byteOffset + 0x3F00, 32));
}
function nt(x, y) { return nes.ppu.vramMem[0x2000 + y * 32 + x]; }

const checks = [];
function expect(label, cond) {
  checks.push([label, !!cond]);
  console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${label}`);
}
function report(label) {
  console.log(`${label.padEnd(22)} state=${mem[A.state]} playing=${mem[A.playing]} ` +
    `song=${mem[A.song_idx]} vol=${mem[A.volume]} bar=${mem[A.bar]} ` +
    `list=${mem[A.list_sel]} evptr=$${mem[A.ev_ptr_hi].toString(16)}` +
    `${mem[A.ev_ptr_lo].toString(16).padStart(2, '0')}`);
}

console.log('=== NES MUSIC BOX ROM 运行验证 ===\n');

// 1) 冷启动：自动播放 + 画面就绪
run(90);
report('冷启动');
shot('01_player');
expect('冷启动进入播放界面', mem[A.state] === 0);
expect('开机自动播放', mem[A.playing] === 1);
expect('初始曲目为 00', mem[A.song_idx] === 0);
expect('初始音量为 5', mem[A.volume] === 5);
expect('中文曲名已写入 nametable', nt(NAME_X, NAME_Y) >= 0x4C);
expect('进度条已绘制', nt(6, BAR_Y) !== 0);

// 2) APU 确实在输出声音
const s0 = samples, nz0 = nonZero;
run(120);
const produced = samples - s0, audible = nonZero - nz0;
console.log(`  音频样本 ${produced} 个，其中非静音 ${audible} 个，峰值 ${peak.toFixed(3)}`);
expect('APU 产生音频样本', produced > 0);
expect('APU 输出非静音波形', audible > 0);

// 3) 播放时钟推进：ev_ptr 前进、bar 变化
const ptr0 = mem[A.ev_ptr_lo] | (mem[A.ev_ptr_hi] << 8);
const bar0 = mem[A.bar];
run(180);
const ptr1 = mem[A.ev_ptr_lo] | (mem[A.ev_ptr_hi] << 8);
report('播放 180 帧后');
expect('事件指针向前推进', ptr1 !== ptr0);
expect('进度条随播放变化', mem[A.bar] !== bar0);

// 4) 切歌 / 音量
tap(jsnes.Controller.BUTTON_RIGHT);
expect('右键切到下一首', mem[A.song_idx] === 1);
const name1 = nt(NAME_X, NAME_Y);
shot('02_song01');
tap(jsnes.Controller.BUTTON_LEFT);
expect('左键切回上一首', mem[A.song_idx] === 0);
expect('切歌后中文曲名改变', nt(NAME_X, NAME_Y) !== name1);
tap(jsnes.Controller.BUTTON_UP);
expect('上键音量 +1', mem[A.volume] === 6);
tap(jsnes.Controller.BUTTON_DOWN);
expect('下键音量 -1', mem[A.volume] === 5);

// 5) 暂停 / 恢复 / 停止
tap(jsnes.Controller.BUTTON_A);
expect('A 暂停播放', mem[A.playing] === 0);
const ptrPause = mem[A.ev_ptr_lo] | (mem[A.ev_ptr_hi] << 8);
run(60);
expect('暂停时事件指针冻结',
  (mem[A.ev_ptr_lo] | (mem[A.ev_ptr_hi] << 8)) === ptrPause);
tap(jsnes.Controller.BUTTON_A);
expect('A 恢复播放', mem[A.playing] === 1);
tap(jsnes.Controller.BUTTON_B);
expect('B 停止并归零进度', mem[A.playing] === 0 && mem[A.bar] === 0);

// 6) 曲目表
tap(jsnes.Controller.BUTTON_SELECT);
expect('SELECT 打开曲目表', mem[A.state] === 1);
shot('03_list');
tap(jsnes.Controller.BUTTON_DOWN);
expect('曲目表下移选中', mem[A.list_sel] === 1);
tap(jsnes.Controller.BUTTON_RIGHT);
expect('右键翻页 / 跳 10 首', mem[A.list_sel] === 11 && mem[A.list_page] === 1);
shot('04_list_page2');
tap(jsnes.Controller.BUTTON_UP);
expect('第二页上移选中', mem[A.list_sel] === 10);
tap(jsnes.Controller.BUTTON_A);
expect('A 播放选中曲目', mem[A.state] === 0 && mem[A.song_idx] === 10);
expect('选中后恢复播放', mem[A.playing] === 1);

// 7) 自动续播：用按键切到短曲 PIXEL HEART（58 tick x 5 帧/遍）
//    必须通过按键触发 load_song，直接改 song_idx 不会重置事件指针
let guard = 0;
while (mem[A.song_idx] !== 11 && guard++ < 25) tap(jsnes.Controller.BUTTON_RIGHT);
expect('按键切到第 11 首', mem[A.song_idx] === 11);
mem[A.loop_left] = 1;                 // 只播一遍以缩短等待
let switched = false, barAtSwitch = -1;
for (let i = 0; i < 400; i++) {
  nes.frame();
  if (!switched && mem[A.song_idx] === 12) {
    switched = true;
    barAtSwitch = mem[A.bar];         // 切歌当帧的进度，应为 0
  }
}
report('等待自动续播后');
expect('播完自动切到下一首', switched && mem[A.song_idx] === 12);
expect('切歌瞬间进度条归零', barAtSwitch === 0);
expect('续播后恢复循环计数', mem[A.loop_left] === 2);

// 8) 崩溃检查
expect('运行期间未崩溃', !nes.crashed);

console.log('\n=== 汇总 ===');
const failed = checks.filter(([, ok]) => !ok);
console.log(`${checks.length - failed.length}/${checks.length} 项通过`);
console.log(`音频总样本 ${samples} / 非静音 ${nonZero} / 峰值 ${peak.toFixed(3)}`);
console.log(`nametable 快照目录: ${OUT}`);
process.exit(failed.length ? 1 : 0);
