; ============================================================================
;  NES MUSIC BOX  -  Family Computer / NES, mapper 0 (NROM-256)
;  Pure 6502 assembly. 32KB PRG-ROM + 8KB CHR-ROM, NTSC.
;
;  20 首曲目：公有领域古典/传统旋律的 8-bit 改编 + 2026 原创芯片音乐。
;  4 声道 APU：方波 1 主旋律 / 方波 2 和声 / 三角波低音 / 噪声打击。
;  曲目数据由 tools/make_songs.py 编译成 6 字节事件流，按 tick 推进。
;
;  操作（播放页）：左右切歌，上下音量，A 播放/暂停，B 停止，
;                 START 随机播放，SELECT 打开曲目表。
;  操作（列表页）：上下选曲，左右翻页，A/START 播放选中，
;                 SELECT/B 返回播放页。
; ============================================================================

.include "tiles.inc"
.include "layout.inc"

; ------------------------- hardware registers -------------------------
PPU_CTRL    = $2000
PPU_MASK    = $2001
PPU_STATUS  = $2002
PPU_SCROLL  = $2005
PPU_ADDR    = $2006
PPU_DATA    = $2007

SQ1_VOL     = $4000
SQ1_SWEEP   = $4001
SQ1_LO      = $4002
SQ1_HI      = $4003
SQ2_VOL     = $4004
SQ2_SWEEP   = $4005
SQ2_LO      = $4006
SQ2_HI      = $4007
TRI_LINEAR  = $4008
TRI_LO      = $400A
TRI_HI      = $400B
NOISE_VOL   = $400C
NOISE_LO    = $400E
NOISE_HI    = $400F
APU_STATUS  = $4015
JOY1        = $4016
FRAME_CTR   = $4017

; ------------------------- controller bits ---------------------------
BTN_A       = $80
BTN_B       = $40
BTN_SELECT  = $20
BTN_START   = $10
BTN_UP      = $08
BTN_DOWN    = $04
BTN_LEFT    = $02
BTN_RIGHT   = $01

; ------------------------- states ------------------------------------
ST_PLAYER   = 0
ST_LIST     = 1

CH_SLASH    = T_SYMBOLS + 5         ; SYMBOLS = ":-.!?/+<>*=,()"

; ============================================================================
;  Zero page  (前几个变量地址固定，供网页试玩页读取状态)
;  $0004 state / $0005 playing / $0006 song_idx
; ============================================================================
.segment "ZEROPAGE"
frame:       .res 1
blink:       .res 1
joy:         .res 1
joy_prev:    .res 1
state:       .res 1
playing:     .res 1
song_idx:    .res 1
volume:      .res 1
tick_frames: .res 1
tick_cnt:    .res 1
ev_dur:      .res 1
bar:         .res 1
loop_left:   .res 1
song_end:    .res 1
skip_viz:    .res 1
list_sel:    .res 1
list_page:   .res 1
rng:         .res 1
kind:        .res 1
name_len:    .res 1
total_lo:    .res 1
total_hi:    .res 1
ev_ptr_lo:   .res 1                 ; 必须与 ev_ptr_hi 相邻
ev_ptr_hi:   .res 1
data_ptr_lo: .res 1                 ; 曲目事件流起始（循环用）
data_ptr_hi: .res 1
name_ptr_lo: .res 1                 ; 必须与 name_ptr_hi 相邻
name_ptr_hi: .res 1
label_ptr_lo:.res 1                 ; 必须与 label_ptr_hi 相邻
label_ptr_hi:.res 1
ptr_lo:      .res 1                 ; 必须与 ptr_hi 相邻
ptr_hi:      .res 1
tmp:         .res 1
tmp2:        .res 1
tmp3:        .res 1
tmp4:        .res 1
mask:        .res 1
save_x:      .res 1
save_y:      .res 1
tx:          .res 1
ty:          .res 1
draw_n:      .res 1
queue_busy:  .res 1                 ; 主循环正在压队列，NMI 本帧跳过 flush
direct_mode: .res 1                 ; 1 = queue_tile 直写 PPU（渲染关闭时做整屏刷新）

; ============================================================================
;  RAM ($0300-$07FF)
; ============================================================================
.segment "BSS"
draw_hi:    .res DRAW_MAX
draw_lo:    .res DRAW_MAX
draw_tl:    .res DRAW_MAX
cur_sq1:    .res 1
cur_sq2:    .res 1
cur_tri:    .res 1
cur_noise:  .res 1
viz_h:      .res 16

; ============================================================================
;  Code
; ============================================================================
.segment "CODE"

; ---------------------------------------------------------------------------
;  RESET
; ---------------------------------------------------------------------------
reset:
    sei
    cld
    ldx #$FF
    txs

    lda #$00
    sta PPU_CTRL
    sta PPU_MASK
    sta APU_STATUS
    lda #$40
    sta FRAME_CTR               ; 禁止 APU 帧中断

    bit PPU_STATUS              ; 等两次 vblank
@v1:
    bit PPU_STATUS
    bpl @v1
@v2:
    bit PPU_STATUS
    bpl @v2

    lda #$00                    ; 清零页与 RAM
    ldx #$00
@zp:
    sta $00,x
    inx
    bne @zp
@ram:
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @ram

    lda #$0F
    sta APU_STATUS              ; 使能 4 个声道
    lda #$08                    ; 禁用 sweep，避免音高漂移
    sta SQ1_SWEEP
    sta SQ2_SWEEP
    lda #$A5
    sta rng
    lda #5
    sta volume
    lda #1
    sta playing                 ; 开机自动播放

    lda #0
    sta song_idx
    jsr load_song
    lda #0
    jsr show_screen             ; 播放界面（含曲名/标签/进度直写）
    jmp main

; ---------------------------------------------------------------------------
;  NMI：只负责在 vblank 里消费绘制队列。
;  所有 queue_tile 调用都集中在主循环，避免 NMI 与主循环同时写队列造成
;  draw_hi / draw_lo / draw_tl 三项错配（曾导致曲名标签被写到频谱区）。
; ---------------------------------------------------------------------------
nmi:
    pha
    txa
    pha
    tya
    pha

    ; 若主循环正处在 queue_tile 中间，本帧不 flush，
    ; 否则会读到「地址已写、数据未写」的半成品项
    lda queue_busy
    bne @qdone
    lda draw_n                  ; ---- flush draw queue ----
    beq @qdone
    ldx #0
@qloop:
    lda draw_hi,x
    sta PPU_ADDR
    lda draw_lo,x
    sta PPU_ADDR
    lda draw_tl,x
    sta PPU_DATA
    inx
    cpx draw_n
    bne @qloop
    lda #0
    sta draw_n
@qdone:

    lda #$00                    ; 恢复滚动
    sta PPU_SCROLL
    sta PPU_SCROLL

    inc frame
    inc blink

    pla
    tay
    pla
    tax
    pla
    rti

irq:
    rti

; ---------------------------------------------------------------------------
;  PPU 整屏重画（渲染与 NMI 都关闭时调用）
;  输入：ptr_lo/hi -> 960 字节 nametable
; ---------------------------------------------------------------------------
redraw:
    lda #$00
    sta PPU_CTRL
    sta PPU_MASK

    lda #$3F                    ; 调色板
    sta PPU_ADDR
    lda #$00
    sta PPU_ADDR
    ldx #0
@pal:
    lda palette,x
    sta PPU_DATA
    inx
    cpx #32
    bne @pal

    lda #$20                    ; nametable
    sta PPU_ADDR
    lda #$00
    sta PPU_ADDR
    ldy #0
    ldx #3
@full:
    lda (ptr_lo),y
    sta PPU_DATA
    iny
    bne @full
    inc ptr_hi
    dex
    bne @full
    ldx #192
@rest:
    lda (ptr_lo),y
    sta PPU_DATA
    iny
    dex
    bne @rest

    lda #$23                    ; 属性表全 0
    sta PPU_ADDR
    lda #$C0
    sta PPU_ADDR
    lda #$00
    ldx #64
@attr:
    sta PPU_DATA
    dex
    bne @attr
    rts

enable_display:
    lda #$00
    sta PPU_SCROLL
    sta PPU_SCROLL
    lda #$80
    sta PPU_CTRL
    lda #$1E
    sta PPU_MASK
    rts

; A = screen index (0 player / 1 list0 / 2 list1)
; screen_tab_lo/hi 是字节表，直接按 0/1/2 索引，不能乘 2。
; 播放界面在渲染关闭期间直接把动态内容写进 PPU，避免队列分帧 flush 的竞态。
show_screen:
    sta tmp3
    tax
    lda screen_tab_lo,x
    sta ptr_lo
    lda screen_tab_hi,x
    sta ptr_hi
    jsr redraw
    lda tmp3
    bne @no_player
    lda #1
    sta direct_mode
    jsr refresh_player
    lda #0
    sta direct_mode
@no_player:
    jsr enable_display
    rts

show_list_page:
    lda #0                      ; 翻页重画前清空队列，避免旧页残留写入新页
    sta draw_n
    lda list_page
    clc
    adc #1
    jsr show_screen
    rts

; ---------------------------------------------------------------------------
;  绘制队列
; ---------------------------------------------------------------------------
; 输入 A=tile, tx=列, ty=行
queue_tile:
    pha                         ; 先保存 tile，再置忙标志（会改 A）
    lda #1
    sta queue_busy
    stx save_x
    sty save_y
    lda direct_mode
    bne @direct
    ldx draw_n
    cpx #DRAW_MAX
    bcs @drop
    ldy ty
    lda row_off_hi,y
    clc
    adc #$20
    sta draw_hi,x
    lda row_off_lo,y
    clc
    adc tx
    sta draw_lo,x
    pla
    sta draw_tl,x
    inx
    stx draw_n
@exit:
    ldx save_x
    ldy save_y
    lda #0
    sta queue_busy
    rts
@direct:                        ; 渲染已关闭：直接写 PPU，不进队列
    ldy ty
    lda row_off_hi,y
    clc
    adc #$20
    sta PPU_ADDR
    lda row_off_lo,y
    clc
    adc tx
    sta PPU_ADDR
    pla
    sta PPU_DATA
    jmp @exit
@drop:
    pla
    jmp @exit

; 从 tx/ty 起连续写 tmp 个空白 tile（tx 会被推进）
clear_row:
@l:
    lda #T_BLANK
    jsr queue_tile
    inc tx
    dec tmp
    bne @l
    rts

; ASCII -> tile index
char_to_tile:
    cmp #' '
    bne @c1
    lda #T_BLANK
    rts
@c1:
    cmp #'0'
    bcc @letter
    cmp #'9'+1
    bcs @letter
    sec
    sbc #'0'
    clc
    adc #T_DIGITS
    rts
@letter:
    cmp #'A'
    bcc @sym
    cmp #'Z'+1
    bcs @sym
    sec
    sbc #'A'
    clc
    adc #T_LETTERS
    rts
@sym:
    sta tmp2
    ldx #0
@syml:
    lda sym_chars,x
    beq @blank
    cmp tmp2
    beq @found
    inx
    cpx #14
    bne @syml
@blank:
    lda #T_BLANK
    rts
@found:
    txa
    clc
    adc #T_SYMBOLS
    rts

; 输入 ptr_lo/hi -> 0 结尾字符串, tx/ty = 起始格
queue_string:
    ldy #0
@l:
    lda (ptr_lo),y
    beq @done
    sty save_y
    jsr char_to_tile
    jsr queue_tile
    inc tx
    ldy save_y
    iny
    bne @l
@done:
    rts

; ---------------------------------------------------------------------------
;  输入
; ---------------------------------------------------------------------------
read_joy:
    lda joy
    sta joy_prev
    lda #1
    sta JOY1
    lda #0
    sta JOY1
    ldx #8
@l:
    lda JOY1
    lsr a
    rol joy
    dex
    bne @l
    rts

; A = 按键掩码，返回 A=1 表示刚按下
just_pressed:
    sta mask
    lda joy
    and mask
    beq @no
    lda joy_prev
    and mask
    bne @no
    lda #1
    rts
@no:
    lda #0
    rts

; ---------------------------------------------------------------------------
;  APU 声道
; ---------------------------------------------------------------------------
silence_all:
    lda #$30
    sta SQ1_VOL
    sta SQ2_VOL
    sta NOISE_VOL
    lda #$00
    sta TRI_LINEAR
    rts

; A = 事件字节：0 静音 / 1..60 音符 / $FE 保持
set_sq1:
    cmp #$FE
    beq @done
    sta cur_sq1
    bne @note
    lda #$30
    sta SQ1_VOL
    rts
@note:
    tax
    lda period_sq_lo,x
    sta SQ1_LO
    lda period_sq_hi,x
    ora #$08
    sta SQ1_HI
    lda volume
    ora #$B0                    ; duty 50%, halt length, constant vol
    sta SQ1_VOL
@done:
    rts

set_sq2:
    cmp #$FE
    beq @done
    sta cur_sq2
    bne @note
    lda #$30
    sta SQ2_VOL
    rts
@note:
    tax
    lda period_sq_lo,x
    sta SQ2_LO
    lda period_sq_hi,x
    ora #$08
    sta SQ2_HI
    lda volume                  ; 和声音量减半，突出主旋律
    lsr a
    ora #$B0
    sta SQ2_VOL
@done:
    rts

set_tri:
    cmp #$FE
    beq @done
    sta cur_tri
    bne @note
    lda #$00
    sta TRI_LINEAR
    rts
@note:
    tax
    lda period_tri_lo,x
    sta TRI_LO
    lda period_tri_hi,x
    ora #$08
    sta TRI_HI
    lda #$81                    ; linear counter halt = 持续发声
    sta TRI_LINEAR
@done:
    rts

set_noise:
    cmp #$FE
    beq @done
    sta cur_noise
    bne @note
    lda #$30
    sta NOISE_VOL
    rts
@note:
    tax
    lda noise_period,x
    sta NOISE_LO
    lda #$08
    sta NOISE_HI
    lda noise_volume,x
    cmp volume
    bcc @ok
    lda volume
@ok:
    ora #$30
    sta NOISE_VOL
@done:
    rts

; 8 位 LFSR，用于频谱动画与随机选曲
lfsr:
    lda rng
    asl a
    bcc @noc
    eor #$1D
@noc:
    sta rng
    rts

; ---------------------------------------------------------------------------
;  曲目装载
; ---------------------------------------------------------------------------
load_song:
    lda song_idx
    asl a
    asl a
    asl a
    asl a                       ; *16
    tax
    lda song_table+0,x
    sta data_ptr_lo
    sta ev_ptr_lo
    lda song_table+1,x
    sta data_ptr_hi
    sta ev_ptr_hi
    lda song_table+2,x
    sta tick_frames
    lda song_table+3,x
    sta kind
    lda song_table+4,x
    sta total_lo
    lda song_table+5,x
    sta total_hi
    lda song_table+6,x
    sta name_ptr_lo
    lda song_table+7,x
    sta name_ptr_hi
    lda song_table+8,x
    sta name_len
    lda song_table+9,x
    sta loop_left
    lda song_table+10,x
    sta label_ptr_lo
    lda song_table+11,x
    sta label_ptr_hi

    lda #1
    sta tick_cnt
    sta ev_dur                  ; 下一 tick 立即读第一个事件
    lda #0
    sta bar
    lda #0
    sta song_end
    jsr silence_all
    rts

; 读取并应用下一个 6 字节事件
next_event:
    ldy #0
    lda (ev_ptr_lo),y
    bne @have
    ; dur = 0 -> 曲目结束
    dec loop_left
    beq @song_end
    lda data_ptr_lo             ; 再循环一遍
    sta ev_ptr_lo
    lda data_ptr_hi
    sta ev_ptr_hi
    ldy #0
    lda (ev_ptr_lo),y
@have:
    sta ev_dur
    iny
    lda (ev_ptr_lo),y
    jsr set_sq1
    iny
    lda (ev_ptr_lo),y
    jsr set_sq2
    iny
    lda (ev_ptr_lo),y
    jsr set_tri
    iny
    lda (ev_ptr_lo),y
    jsr set_noise
    iny
    lda (ev_ptr_lo),y
    sta bar
    jsr draw_bar
    ; ev_ptr += 6
    lda ev_ptr_lo
    clc
    adc #6
    sta ev_ptr_lo
    bcc @done
    inc ev_ptr_hi
@done:
    rts
@song_end:
    lda #1
    sta song_end
    lda #0
    sta playing                 ; 等主循环切歌
    jsr silence_all
    rts

; 每个 vblank 帧调用；到 tick 边界才推进事件
music_tick:
    lda playing
    beq @done
    dec tick_cnt
    bne @done
    lda tick_frames
    sta tick_cnt
    dec ev_dur
    bne @done
    jsr next_event
@done:
    rts

do_next_song:
    inc song_idx
    lda song_idx
    cmp #song_count
    bcc @ok
    lda #0
    sta song_idx
@ok:
    lda #1
    sta playing
    jsr load_song
    lda #0
    jsr show_screen             ; 整屏刷新：曲名/标签/进度直写 PPU
    rts

; ---------------------------------------------------------------------------
;  播放界面绘制
; ---------------------------------------------------------------------------
draw_bar:
    ; 曲目表页不画播放页的进度条，避免污染列表画面
    lda state
    cmp #ST_LIST
    bne @go
    rts
@go:
    ldx #0
@l:
    txa
    cmp bar
    bcc @full
    bne @empty
    lda #T_BAR_HEAD
    jmp @put
@full:
    lda #T_BAR_FULL
    jmp @put
@empty:
    lda #T_BAR_EMPTY
@put:
    pha
    lda #BAR_Y
    sta ty
    txa
    clc
    adc #BAR_X
    sta tx
    pla
    jsr queue_tile
    inx
    cpx #BAR_LEN
    bne @l
    rts

draw_volume:
    ldx #0
@l:
    txa
    cmp volume
    bcc @full
    lda #T_BAR_EMPTY
    jmp @put
@full:
    lda #T_BAR_FULL
@put:
    pha
    lda #VOL_Y
    sta ty
    txa
    clc
    adc #VOL_X
    sta tx
    pla
    jsr queue_tile
    inx
    cpx #VOL_LEN
    bne @l
    rts

draw_icon:
    lda #ICON_X
    sta tx
    lda #ICON_Y
    sta ty
    lda playing
    bne @play
    lda #T_PAUSE
    jmp @put
@play:
    lda #T_PLAY
@put:
    jsr queue_tile
    rts

; A = 0..99，在 tx/ty 处写两位数字，tx 前进 2
draw_2digits:
    ldx #0
@ten:
    cmp #10
    bcc @got
    sec
    sbc #10
    inx
    jmp @ten
@got:
    sta tmp2
    txa
    clc
    adc #T_DIGITS
    jsr queue_tile
    inc tx
    lda tmp2
    clc
    adc #T_DIGITS
    jsr queue_tile
    inc tx
    rts

draw_number:
    lda #NUM_X
    sta tx
    lda #NUM_Y
    sta ty
    lda song_idx
    clc
    adc #1
    jsr draw_2digits
    lda #CH_SLASH
    jsr queue_tile
    inc tx
    lda #song_count
    jsr draw_2digits
    rts

draw_name:
    ; 先清空 8 列 x 2 行
    lda #NAME_X
    sta tx
    lda #NAME_Y
    sta ty
    lda #NAME_MAX*2
    sta tmp
    jsr clear_row
    lda #NAME_X
    sta tx
    lda #NAME_Y+1
    sta ty
    lda #NAME_MAX*2
    sta tmp
    jsr clear_row
    ; 每个汉字 2x2 tile
    ldy #0
@l:
    cpy name_len
    bcs @done
    lda (name_ptr_lo),y
    asl a
    asl a
    clc
    adc #T_CN
    sta tmp2
    tya
    asl a
    clc
    adc #NAME_X
    sta tx
    lda #NAME_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inc tx
    lda tmp2
    clc
    adc #1
    jsr queue_tile
    lda #NAME_Y+1
    sta ty
    dec tx
    lda tmp2
    clc
    adc #2
    jsr queue_tile
    inc tx
    lda tmp2
    clc
    adc #3
    jsr queue_tile
    iny
    jmp @l
@done:
    rts

draw_label:
    lda #LABEL_X
    sta tx
    lda #LABEL_Y
    sta ty
    lda #LABEL_MAX
    sta tmp
    jsr clear_row
    lda #LABEL_X
    sta tx
    ldy #0
@l:
    lda (label_ptr_lo),y
    beq @done
    sty save_y
    jsr char_to_tile
    jsr queue_tile
    inc tx
    ldy save_y
    iny
    jmp @l
@done:
    rts

draw_kind:
    lda #KIND_X
    sta tx
    lda #KIND_Y
    sta ty
    lda #13                     ; CLASSIC / FOLK / ORIGINAL 2026 最长 13 字符
    sta tmp
    jsr clear_row
    lda #KIND_X
    sta tx
    ldx kind
    lda kind_str_lo,x
    sta ptr_lo
    lda kind_str_hi,x
    sta ptr_hi
    jsr queue_string
    rts

refresh_player:
    jsr draw_name
    jsr draw_label
    jsr draw_number
    jsr draw_kind
    jsr draw_icon
    jsr draw_bar
    jsr draw_volume
    rts

; ---------------------------------------------------------------------------
;  频谱可视化：16 柱 x 3 行，随当前音符与 LFSR 缓动
; ---------------------------------------------------------------------------
; tmp2 = 柱高 h, tmp3 = 行偏移 -> A = tile index
fill_tile:
    lda tmp2
    sec
    sbc tmp3
    bcs @pos
    lda #0
@pos:
    cmp #9
    bcc @ok
    lda #8
@ok:
    ; 注意：此处不能直接用 beq（零标志来自 cmp #9 / lda #8，不是 A 的值）
    cmp #1
    bcc @blank
    clc
    adc #T_VIZ-1
    rts
@blank:
    lda #T_BLANK
    rts

viz_col:
    ; row 0 (顶): offset 16
    lda #16
    sta tmp3
    jsr fill_tile
    pha
    lda #VIZ_Y
    sta ty
    txa
    clc
    adc #VIZ_X
    sta tx
    pla
    jsr queue_tile
    ; row 1 (中): offset 8
    lda #8
    sta tmp3
    jsr fill_tile
    pha
    lda #VIZ_Y+1
    sta ty
    txa
    clc
    adc #VIZ_X
    sta tx
    pla
    jsr queue_tile
    ; row 2 (底): offset 0
    lda #0
    sta tmp3
    jsr fill_tile
    pha
    lda #VIZ_Y+2
    sta ty
    txa
    clc
    adc #VIZ_X
    sta tx
    pla
    jsr queue_tile
    rts

viz_update:
    ; 切歌那一帧让位给整屏刷新；曲目表页也不做频谱
    lda skip_viz
    bne @skip
    lda state
    cmp #ST_LIST
    bne @go
@skip:
    lda #0
    sta skip_viz
    rts
@go:
    jsr lfsr
    lda rng
    sta tmp4
    ldx #0
@col:
    lda cur_sq1
    clc
    adc tmp4
    and #$1F                    ; 目标高度 0..31，柱高起伏更明显
    sta tmp
    lda viz_h,x
    clc
    adc tmp
    lsr a                       ; 缓动
    sta viz_h,x
    sta tmp2
    jsr viz_col
    lda tmp4
    clc
    adc #13
    sta tmp4
    inx
    cpx #VIZ_COLS
    bne @col
    rts

; ---------------------------------------------------------------------------
;  曲目表
; ---------------------------------------------------------------------------
calc_page:
    lda list_sel
    ldx #0
@l:
    cmp #LIST_PAGE_SIZE
    bcc @done
    sec
    sbc #LIST_PAGE_SIZE
    inx
    jmp @l
@done:
    stx list_page
    rts

draw_list_cursor:
    lda #LIST_CURSOR_X
    sta tx
    lda #LIST_ROW_Y0
    sta ty
    ldx #0
@clr:
    lda #T_BLANK
    jsr queue_tile
    lda ty
    clc
    adc #LIST_ROW_STEP
    sta ty
    inx
    cpx #LIST_PAGE_SIZE
    bne @clr
    ; 当前选中行 = list_sel - list_page*10
    lda list_sel
    ldx list_page
    beq @got
@sub:
    sec
    sbc #LIST_PAGE_SIZE
    dex
    bne @sub
@got:
    asl a
    clc
    adc #LIST_ROW_Y0
    sta ty
    lda #LIST_CURSOR_X
    sta tx
    lda #T_CURSOR
    jsr queue_tile
    rts

open_list:
    lda #0                      ; 丢弃播放页残留的绘制请求
    sta draw_n
    lda #ST_LIST
    sta state
    jsr calc_page
    jsr show_list_page
    jsr draw_list_cursor
    rts

close_list:
    lda #0
    sta draw_n
    lda #ST_PLAYER
    sta state
    lda #0
    jsr show_screen             ; 回到播放界面（含动态内容直写）
    rts

list_refresh:
    jsr calc_page
    lda list_page
    cmp tmp2
    beq @same
    jsr show_list_page
@same:
    jsr draw_list_cursor
    rts

list_up:
    jsr calc_page
    lda list_page
    sta tmp2
    dec list_sel
    lda list_sel
    bpl @ok
    lda #song_count-1
    sta list_sel
@ok:
    jmp list_refresh

list_down:
    jsr calc_page
    lda list_page
    sta tmp2
    inc list_sel
    lda list_sel
    cmp #song_count
    bcc @ok
    lda #0
    sta list_sel
@ok:
    jmp list_refresh

list_page_next:
    jsr calc_page
    lda list_page
    sta tmp2
    lda list_sel
    clc
    adc #LIST_PAGE_SIZE
    cmp #song_count
    bcc @ok
    lda #0
@ok:
    sta list_sel
    jmp list_refresh

list_page_prev:
    jsr calc_page
    lda list_page
    sta tmp2
    lda list_sel
    sec
    sbc #LIST_PAGE_SIZE
    bcs @ok
    lda #song_count-1
@ok:
    sta list_sel
    jmp list_refresh

select_song:
    lda list_sel
    sta song_idx
    lda #1
    sta playing
    jsr load_song
    jsr close_list
    rts

; ---------------------------------------------------------------------------
;  播放页输入
; ---------------------------------------------------------------------------
prev_song:
    dec song_idx
    lda song_idx
    bpl @ok
    lda #song_count-1
    sta song_idx
@ok:
    jsr load_song
    lda #0
    jsr show_screen             ; 整屏刷新：曲名/标签/进度直写 PPU
    rts

next_song_manual:
    inc song_idx
    lda song_idx
    cmp #song_count
    bcc @ok
    lda #0
    sta song_idx
@ok:
    jsr load_song
    lda #0
    jsr show_screen             ; 整屏刷新：曲名/标签/进度直写 PPU
    rts

toggle_play:
    lda playing
    eor #1
    sta playing
    bne @resume
    jsr silence_all
    jmp @icon
@resume:
    lda #1                      ; 下一 tick 立即恢复发声
    sta ev_dur
@icon:
    jsr draw_icon
    rts

stop_song:
    lda #0
    sta playing
    jsr load_song
    lda #0
    jsr show_screen             ; 整屏刷新：曲名/标签/进度直写 PPU
    rts

volume_up:
    lda volume
    cmp #VOL_MAX
    bcs @done
    inc volume
    jsr draw_volume
@done:
    rts

volume_down:
    lda volume
    beq @done
    dec volume
    jsr draw_volume
@done:
    rts

random_song:
    jsr lfsr
    lda rng
@mod:
    cmp #song_count
    bcc @ok
    sec
    sbc #song_count
    jmp @mod
@ok:
    sta song_idx
    jsr load_song
    lda #0
    jsr show_screen             ; 整屏刷新：曲名/标签/进度直写 PPU
    rts

handle_player:
    lda #BTN_LEFT
    jsr just_pressed
    beq @n1
    jmp prev_song
@n1:
    lda #BTN_RIGHT
    jsr just_pressed
    beq @n2
    jmp next_song_manual
@n2:
    lda #BTN_UP
    jsr just_pressed
    beq @n3
    jmp volume_up
@n3:
    lda #BTN_DOWN
    jsr just_pressed
    beq @n4
    jmp volume_down
@n4:
    lda #BTN_A
    jsr just_pressed
    beq @n5
    jmp toggle_play
@n5:
    lda #BTN_B
    jsr just_pressed
    beq @n6
    jmp stop_song
@n6:
    lda #BTN_START
    jsr just_pressed
    beq @n7
    jmp random_song
@n7:
    lda #BTN_SELECT
    jsr just_pressed
    beq @done
    jmp open_list
@done:
    rts

handle_list:
    lda #BTN_UP
    jsr just_pressed
    beq @n1
    jmp list_up
@n1:
    lda #BTN_DOWN
    jsr just_pressed
    beq @n2
    jmp list_down
@n2:
    lda #BTN_LEFT
    jsr just_pressed
    beq @n3
    jmp list_page_prev
@n3:
    lda #BTN_RIGHT
    jsr just_pressed
    beq @n4
    jmp list_page_next
@n4:
    lda #BTN_A
    jsr just_pressed
    beq @n5
    jmp select_song
@n5:
    lda #BTN_START
    jsr just_pressed
    beq @n6
    jmp select_song
@n6:
    lda #BTN_SELECT
    jsr just_pressed
    beq @n7
    jmp close_list
@n7:
    lda #BTN_B
    jsr just_pressed
    beq @done
    jmp close_list
@done:
    rts

; ---------------------------------------------------------------------------
;  主循环
; ---------------------------------------------------------------------------
main:
    lda frame
@wait:
    cmp frame
    beq @wait
    jsr read_joy
    lda song_end
    beq @no_end
    jsr do_next_song
@no_end:
    lda state
    cmp #ST_LIST
    beq @list
    jsr handle_player
    jmp @tick
@list:
    jsr handle_list
@tick:
    jsr music_tick              ; 按帧推进 APU 事件
    jsr viz_update              ; 频谱动画（仅在播放页）
    jmp main

; ============================================================================
;  Read-only data
; ============================================================================
.segment "RODATA"

palette:
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16

row_off_lo:
    .repeat 30, I
        .byte <(I*32)
    .endrepeat
row_off_hi:
    .repeat 30, I
        .byte >(I*32)
    .endrepeat

sym_chars:
    .byte ":-.!?/+<>*=,()"
    .byte 0

str_classic:    .byte "CLASSIC",0
str_folk:       .byte "FOLK",0
str_original:   .byte "ORIGINAL 2026",0
kind_str_lo:    .byte <str_classic, <str_folk, <str_original
kind_str_hi:    .byte >str_classic, >str_folk, >str_original

screen_tab_lo:  .byte <screen_player, <screen_list0, <screen_list1
screen_tab_hi:  .byte >screen_player, >screen_list0, >screen_list1

.include "screens.inc"
.include "songs.inc"

; ============================================================================
;  Vectors
; ============================================================================
.segment "VECTORS"
    .word nmi
    .word reset
    .word irq
