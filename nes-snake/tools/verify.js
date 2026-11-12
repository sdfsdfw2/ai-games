#!/usr/bin/env node
/**
 * 用 jsnes 实际运行 snake.nes，验证状态机与画面，并导出截图。
 *
 * 零页 / BSS 变量地址来自 ld65 的段布局（见 build/snake.map）：
 *   state=$0004 paused=$0005 dir=$0006 head_x=$0008 head_y=$0009
 *   food_x=$000C food_y=$000D length=$0010 interval=$0012
 *   score_digits=$0590..$0595 (BCD, 高位在前)
 */
const fs = require('fs');
const path = require('path');
const jsnes = require('../vendor/jsnes.min.js');

const ROOT = path.dirname(__dirname);
const OUT = path.join(ROOT, 'tools', 'shots');
fs.mkdirSync(OUT, { recursive: true });

const A = {
  state: 0x0004, paused: 0x0005, dir: 0x0006,
  head_x: 0x0008, head_y: 0x0009,
  food_x: 0x000C, food_y: 0x000D,
  length: 0x0010, interval: 0x0012,
  score: 0x0590,
};

const rom = fs.readFileSync(path.join(ROOT, 'snake.nes'));
const C = jsnes.Controller;
let frameNo = 0;
let fbInfo = null;

const nes = new jsnes.NES({
  onFrame: (fb) => {
    if (!fbInfo) fbInfo = { len: fb.length, ctor: fb.constructor.name };
    frameNo++;
  },
  onAudioSample: () => {},
});

nes.loadROM(rom.toString('latin1'));
const mem = nes.cpu.mem;

function run(n) {
  for (let i = 0; i < n; i++) nes.frame();
}
function shot(name) {
  nes.frame();
  // jsnes 在 Node 下惰性渲染，frameBuffer 常为空；直接导出 PPU nametable/palette 更可靠
  const vm = nes.ppu.vramMem;
  fs.writeFileSync(
    path.join(OUT, name + '.nt'),
    Buffer.from(vm.buffer, vm.byteOffset + 0x2000, 960)
  );
  fs.writeFileSync(
    path.join(OUT, name + '.pal'),
    Buffer.from(vm.buffer, vm.byteOffset + 0x3F00, 32)
  );
}
function tap(btn) {
  nes.buttonDown(1, btn);
  nes.frame();
  nes.buttonUp(1, btn);
}
function bcd(addr, n) {
  return Array.from({ length: n }, (_, i) => mem[addr + i]).join('');
}
function report(label) {
  console.log(
    `${label.padEnd(24)} frame=${String(frameNo).padStart(4)} ` +
    `state=${mem[A.state]} paused=${mem[A.paused]} dir=${mem[A.dir]} ` +
    `head=(${mem[A.head_x]},${mem[A.head_y]}) len=${mem[A.length]} ` +
    `food=(${mem[A.food_x]},${mem[A.food_y]}) score=${bcd(A.score, 6)}`
  );
}

const checks = [];
function expect(label, cond) {
  checks.push([label, !!cond]);
  console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${label}`);
}

console.log('=== NES SNAKE ROM 运行验证 ===\n');

// 1) 标题画面
run(60);
report('标题画面');
shot('01_title');
expect('冷启动进入标题状态', mem[A.state] === 0);

// 2) START 开始游戏
tap(C.BUTTON_START);
run(6);
report('按下 START 后');
shot('02_play_start');
expect('START 进入游戏状态', mem[A.state] === 1);
expect('初始蛇长为 4', mem[A.length] === 4);
expect('初始方向为右', mem[A.dir] === 1);

// 3) 强制把食物放到蛇头正前方，验证吃食物逻辑
const hx0 = mem[A.head_x], hy0 = mem[A.head_y];
mem[A.food_x] = hx0 + 1;
mem[A.food_y] = hy0;
const score0 = bcd(A.score, 6);
run(mem[A.interval] + 2);
report('吃到食物后');
shot('03_after_eat');
expect('蛇长度 +1', mem[A.length] === 5);
expect('分数 +10', Number(bcd(A.score, 6)) === Number(score0) + 10);
expect('食物已重新生成', !(mem[A.food_x] === hx0 + 1 && mem[A.food_y] === hy0));

// 4) 方向输入：按上，蛇应向上移动
tap(C.BUTTON_UP);
const hy1 = mem[A.head_y];
run(mem[A.interval] * 3);
report('按上方向 3 步后');
shot('04_turn_up');
expect('方向变为上', mem[A.dir] === 0);
expect('Y 坐标减小', mem[A.head_y] < hy1);

// 5) START 暂停
tap(C.BUTTON_START);
run(30);
const hp = mem[A.head_y];
run(30);
report('暂停 60 帧后');
shot('05_paused');
expect('暂停标志置位', mem[A.paused] === 1);
expect('暂停时蛇不移动', mem[A.head_y] === hp);
tap(C.BUTTON_START);
run(2);
expect('再次 START 恢复', mem[A.paused] === 0);

// 6) 一直向右撞墙 -> GAME OVER
nes.buttonDown(1, C.BUTTON_RIGHT);
run(400);
nes.buttonUp(1, C.BUTTON_RIGHT);
report('撞墙之后');
shot('06_game_over');
expect('撞墙进入结束状态', mem[A.state] === 2);

// 7) 结束画面按 START 重开
tap(C.BUTTON_START);
run(6);
report('结束后重开');
shot('07_restart');
expect('可以重新开始', mem[A.state] === 1 && mem[A.length] === 4);

// 8) SELECT 回标题
tap(C.BUTTON_SELECT);
run(6);
report('SELECT 回标题');
shot('08_back_to_title');
expect('SELECT 回到标题', mem[A.state] === 0);

console.log('\n=== 汇总 ===');
const failed = checks.filter(([, ok]) => !ok);
console.log(`${checks.length - failed.length}/${checks.length} 项通过`);
console.log(`frameBuffer: ${fbInfo ? fbInfo.ctor + ' / ' + fbInfo.len + ' 元素' : 'n/a'}`);
console.log(`nametable 快照目录: ${OUT}`);
process.exit(failed.length ? 1 : 0);
