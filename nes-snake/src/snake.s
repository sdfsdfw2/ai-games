; ============================================================================
;  NES SNAKE  -  Family Computer / NES, mapper 0 (NROM-256)
;  Pure 6502 assembly. 32KB PRG-ROM + 8KB CHR-ROM, NTSC.
;
;  玩法：方向键移动，吃红色宝石加分；撞墙或咬到自己即结束。
;        每吃 5 个升一级并加速。START 暂停/开始，SELECT 回标题。
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

; ------------------------- directions --------------------------------
; 顺序必须与 CHR 中 T_HEAD_U/R/D/L 一致
DIR_U       = 0
DIR_R       = 1
DIR_D       = 2
DIR_L       = 3

; ------------------------- game states -------------------------------
ST_TITLE    = 0
ST_PLAY     = 1
ST_OVER     = 2

; ------------------------- tunables ----------------------------------
DRAW_MAX      = 48
START_LEN     = 4
START_X       = 8
START_Y       = 14
INTERVAL_INIT = 12
INTERVAL_MIN  = 4
MAX_LEN       = 250

; ============================================================================
;  Zero page
; ============================================================================
.segment "ZEROPAGE"
frame:      .res 1
blink:      .res 1
joy:        .res 1
joy_prev:   .res 1
state:      .res 1
paused:     .res 1
dir:        .res 1
newdir:     .res 1
head_x:     .res 1
head_y:     .res 1
nx:         .res 1
ny:         .res 1
food_x:     .res 1
food_y:     .res 1
head_idx:   .res 1
tail_idx:   .res 1
length:     .res 1
tick:       .res 1
interval:   .res 1
level_hi:   .res 1
level_lo:   .res 1
eaten:      .res 1
eat_flag:   .res 1
rng:        .res 1
tmp:        .res 1
tmp2:       .res 1
tmp3:       .res 1
tmp_y:      .res 1
mask:       .res 1
save_x:     .res 1
save_y:     .res 1
ptr_lo:     .res 1           ; 必须与 ptr_hi 相邻，供 (ptr_lo),y 使用
ptr_hi:     .res 1
tx:         .res 1
ty:         .res 1
draw_n:     .res 1
food_frame: .res 1
sfx_type:   .res 1
sfx_timer:  .res 1
pal_state:  .res 1

; ============================================================================
;  RAM ($0300-$07FF)
; ============================================================================
.segment "BSS"
snake_x:      .res 256
snake_y:      .res 256
draw_hi:      .res DRAW_MAX
draw_lo:      .res DRAW_MAX
draw_tl:      .res DRAW_MAX
score_digits: .res 6         ; BCD, 高位在前
hi_digits:    .res 6
food_bcd:     .res 3

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
    sta PPU_CTRL                ; 关 NMI
    sta PPU_MASK                ; 关渲染
    sta APU_STATUS              ; 关所有声道
    lda #$40
    sta FRAME_CTR               ; 禁止 APU 帧中断（没有 IRQ 服务程序）

    bit PPU_STATUS              ; PPU 预热，等两次 vblank
@v1:
    bit PPU_STATUS
    bpl @v1
@v2:
    bit PPU_STATUS
    bpl @v2

    lda #$00                    ; 清零页
    ldx #$00
@zp:
    sta $00,x
    inx
    bne @zp

    ldx #$00                    ; 清 $0300-$07FF
@ram:
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    inx
    bne @ram

    lda #$0F
    sta APU_STATUS              ; 使能 sq1/sq2/tri/noise
    lda #$A5
    sta rng

    jsr show_title
    jmp main                    ; 保持 I=1，只依赖 NMI

; ---------------------------------------------------------------------------
;  NMI：vblank 期间刷新绘制队列、调色板闪烁、音效包络
; ---------------------------------------------------------------------------
nmi:
    pha
    txa
    pha
    tya
    pha

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

    lda blink                   ; ---- 红色装饰闪烁 ----
    and #$0F
    bne @pal_done
    lda pal_state
    eor #1
    sta pal_state
    lda #$3F
    sta PPU_ADDR
    lda #$03
    sta PPU_ADDR
    lda pal_state
    bne @bright
    lda #$0F                    ; 变暗
    .byte $2C                   ; BIT zp，跳过下面 2 字节
@bright:
    lda #$16                    ; 亮红
    sta PPU_DATA
@pal_done:

    jsr sfx_update

    lda #$00                    ; 恢复滚动（写 PPU_ADDR 会破坏）
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
;  PPU：整屏重画（渲染与 NMI 都关闭时调用，结束后仍保持关闭）
; ---------------------------------------------------------------------------
redraw:
    lda #$00
    sta PPU_CTRL
    sta PPU_MASK

    lda #$3F                    ; ---- 调色板 $3F00 ----
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

    lda #$20                    ; ---- nametable $2000, 960 bytes ----
    sta PPU_ADDR
    lda #$00
    sta PPU_ADDR
    ldy #0
    ldx #3                      ; 3 个整页 = 768
@full:
    lda (ptr_lo),y
    sta PPU_DATA
    iny
    bne @full
    inc ptr_hi
    dex
    bne @full
    ldx #192                    ; 余下 192
@rest:
    lda (ptr_lo),y
    sta PPU_DATA
    iny
    dex
    bne @rest

    lda #$23                    ; ---- 属性表 $23C0，全 0 ----
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
    lda #$80                    ; NMI 开，背景图案表 $0000
    sta PPU_CTRL
    lda #$1E                    ; 背景 + 精灵全开
    sta PPU_MASK
    rts

; ---------------------------------------------------------------------------
;  绘制队列：主循环压入，NMI 消费
;  输入 A=tile, tx=列, ty=行；保存/恢复 X、Y 方便调用方循环
; ---------------------------------------------------------------------------
queue_tile:
    stx save_x
    sty save_y
    pha
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
    adc tx                     ; row_off_lo 恒为 32 的倍数，+tx 不会进位
    sta draw_lo,x
    pla
    sta draw_tl,x
    inx
    stx draw_n
@exit:
    ldx save_x
    ldy save_y
    rts
@drop:
    pla
    jmp @exit

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
    sta tmp
    ldx #0
@syml:
    lda sym_chars,x
    beq @blank
    cmp tmp
    beq @found
    inx
    cpx #16
    bne @syml
@blank:
    lda #T_BLANK
    rts
@found:
    txa
    clc
    adc #T_SYMBOLS
    rts

; 输入：ptr_lo/hi -> 0 结尾字符串，tx/ty = 起始格
queue_string:
    ldy #0
@l:
    lda (ptr_lo),y
    beq @done
    sty tmp_y
    jsr char_to_tile
    jsr queue_tile
    inc tx
    ldy tmp_y
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

; A = 按键掩码，返回 A=1 表示"刚按下"
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

; A = 新方向，拒绝 180 度掉头
set_dir:
    sta tmp
    eor dir
    cmp #$02
    beq @reject
    lda tmp
    sta newdir
@reject:
    rts

handle_dirs:
    lda joy
    and #BTN_UP
    beq @nu
    lda #DIR_U
    jsr set_dir
@nu:
    lda joy
    and #BTN_DOWN
    beq @nd
    lda #DIR_D
    jsr set_dir
@nd:
    lda joy
    and #BTN_LEFT
    beq @nl
    lda #DIR_L
    jsr set_dir
@nl:
    lda joy
    and #BTN_RIGHT
    beq @done
    lda #DIR_R
    jsr set_dir
@done:
    rts

; ---------------------------------------------------------------------------
;  随机数（8-bit LFSR，混入帧计数）
; ---------------------------------------------------------------------------
rand:
    lda rng
    clc
    adc frame
    asl a
    bcc @no
    eor #$CF
@no:
    sta rng
    rts

; ---------------------------------------------------------------------------
;  HUD：把 BCD 数字压进绘制队列
; ---------------------------------------------------------------------------
queue_hud:
    ldx #0                      ; SCORE
@s:
    lda score_digits,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #HUD_SCORE_X
    sta tx
    lda #HUD_SCORE_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #6
    bne @s

    ldx #0                      ; HI
@h:
    lda hi_digits,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #HUD_HI_X
    sta tx
    lda #HUD_HI_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #6
    bne @h

    lda level_hi                ; LV
    clc
    adc #T_DIGITS
    sta tmp2
    lda #HUD_LV_X
    sta tx
    lda #HUD_LV_Y
    sta ty
    lda tmp2
    jsr queue_tile
    lda level_lo
    clc
    adc #T_DIGITS
    sta tmp2
    lda #HUD_LV_X+1
    sta tx
    lda #HUD_LV_Y
    sta ty
    lda tmp2
    jsr queue_tile

    ldx #0                      ; FOOD
@f:
    lda food_bcd,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #HUD_FOOD_X
    sta tx
    lda #HUD_FOOD_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #3
    bne @f
    rts

queue_over_hud:
    ldx #0
@s:
    lda score_digits,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #OVER_SCORE_X
    sta tx
    lda #OVER_SCORE_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #6
    bne @s

    ldx #0
@h:
    lda hi_digits,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #OVER_HI_X
    sta tx
    lda #OVER_HI_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #6
    bne @h
    rts

update_pause_hud:
    lda #HUD_PAUSE_X
    sta tx
    lda #HUD_PAUSE_Y
    sta ty
    lda paused
    beq @blank
    lda #<str_paused
    sta ptr_lo
    lda #>str_paused
    sta ptr_hi
    jmp queue_string
@blank:
    lda #<str_blank6
    sta ptr_lo
    lda #>str_blank6
    sta ptr_hi
    jmp queue_string

; ---------------------------------------------------------------------------
;  音效（触发 + NMI 包络）
; ---------------------------------------------------------------------------
sfx_eat:
    lda #$30
    sta SQ2_VOL
    lda #%10110111              ; 50% duty, 恒定音量 7
    sta SQ1_VOL
    lda #$08
    sta SQ1_SWEEP
    lda #$A0
    sta SQ1_LO
    lda #$88
    sta SQ1_HI
    lda #1
    sta sfx_type
    lda #10
    sta sfx_timer
    rts

sfx_start:
    lda #$30
    sta SQ2_VOL
    lda #%10110111
    sta SQ1_VOL
    lda #$08
    sta SQ1_SWEEP
    lda #$60
    sta SQ1_LO
    lda #$88
    sta SQ1_HI
    lda #1
    sta sfx_type
    lda #12
    sta sfx_timer
    rts

sfx_die:
    lda #$30
    sta SQ1_VOL
    lda #%10110111
    sta SQ2_VOL
    lda #$08
    sta SQ2_SWEEP
    lda #$80
    sta SQ2_LO
    lda #$90
    sta SQ2_HI
    lda #%10110111
    sta NOISE_VOL
    lda #$00
    sta NOISE_LO
    lda #$50
    sta NOISE_HI
    lda #2
    sta sfx_type
    lda #40
    sta sfx_timer
    rts

sfx_update:
    lda sfx_timer
    beq @done
    dec sfx_timer
    bne @cont
    lda #$30                    ; 结束：三个声道归零音量
    sta SQ1_VOL
    sta SQ2_VOL
    sta NOISE_VOL
    rts
@cont:
    lda sfx_type
    cmp #2
    bne @env
    lda sfx_timer               ; 死亡：下降扫频
    asl a
    clc
    adc #$40
    sta SQ2_LO
    lda #$90
    sta SQ2_HI
    lda sfx_timer
    lsr a
    lsr a
    and #$07
    ora #$30
    sta SQ2_VOL
    rts
@env:
    lda sfx_timer               ; 吃/开始：音量渐弱
    and #$07
    ora #$30
    sta SQ1_VOL
@done:
    rts

; ---------------------------------------------------------------------------
;  计分 / 等级
; ---------------------------------------------------------------------------
add10:
    ldx #4
@l:
    inc score_digits,x
    lda score_digits,x
    cmp #10
    bcc @done
    lda #0
    sta score_digits,x
    dex
    bpl @l
@done:
    rts

add_food_bcd:
    ldx #2
@l:
    inc food_bcd,x
    lda food_bcd,x
    cmp #10
    bcc @done
    lda #0
    sta food_bcd,x
    dex
    bpl @l
@done:
    rts

inc_level_bcd:
    inc level_lo
    lda level_lo
    cmp #10
    bcc @done
    lda #0
    sta level_lo
    inc level_hi
@done:
    rts

on_eat:
    jsr add10
    jsr add_food_bcd
    inc eaten
    lda eaten
    cmp #5
    bcc @done
    lda #0
    sta eaten
    jsr inc_level_bcd
    lda interval
    cmp #INTERVAL_MIN+1
    bcc @done
    dec interval
@done:
    rts

update_hi:
    ldx #0
@cmp:
    lda score_digits,x
    cmp hi_digits,x
    bcc @done                   ; score < hi
    bne @greater                ; score > hi
    inx
    cpx #6
    bne @cmp
    rts                         ; 相等
@greater:
    ldx #0
@copy:
    lda score_digits,x
    sta hi_digits,x
    inx
    cpx #6
    bne @copy
@done:
    rts

; ---------------------------------------------------------------------------
;  食物：随机找一格不与蛇身重叠的位置（不负责绘制）
; ---------------------------------------------------------------------------
spawn_food:
@try:
    jsr rand
    and #$1F
    cmp #PLAY_LEFT
    bcc @try
    cmp #PLAY_RIGHT+1
    bcs @try
    sta food_x
@try_y:
    jsr rand
    and #$1F
    cmp #PLAY_TOP
    bcc @try_y
    cmp #PLAY_BOTTOM+1
    bcs @try_y
    sta food_y
    ldx tail_idx
    ldy #0
@chk:
    lda snake_x,x
    cmp food_x
    bne @next
    lda snake_y,x
    cmp food_y
    beq @try
@next:
    inx
    iny
    cpy length
    bne @chk
    lda #0
    sta food_frame
    rts

food_blink:
    lda frame
    and #$07
    bne @done
    lda food_frame
    eor #1
    sta food_frame
    lda food_x
    sta tx
    lda food_y
    sta ty
    lda food_frame
    bne @alt
    lda #T_FOOD
    jmp queue_tile
@alt:
    lda #T_FOOD_ALT
    jmp queue_tile
@done:
    rts

; ---------------------------------------------------------------------------
;  一步移动
; ---------------------------------------------------------------------------
do_move:
    lda newdir
    sta dir

    lda head_x                  ; 计算 nx, ny
    sta nx
    lda head_y
    sta ny
    lda dir
    cmp #DIR_U
    bne @d1
    dec ny
    jmp @calc
@d1:
    cmp #DIR_R
    bne @d2
    inc nx
    jmp @calc
@d2:
    cmp #DIR_D
    bne @d3
    inc ny
    jmp @calc
@d3:
    dec nx
@calc:
    lda nx                      ; 撞墙
    cmp #PLAY_LEFT
    bcc @dead1
    cmp #PLAY_RIGHT+1
    bcs @dead1
    lda ny
    cmp #PLAY_TOP
    bcc @dead1
    cmp #PLAY_BOTTOM+1
    bcs @dead1
    jmp @walls_ok
@dead1:
    jmp dead                    ; 跳板：条件分支够不到远处的 dead
@walls_ok:

    lda #0                      ; 是否吃到食物
    sta eat_flag
    lda nx
    cmp food_x
    bne @self
    lda ny
    cmp food_y
    bne @self
    lda #1
    sta eat_flag
@self:
    ldx tail_idx                ; 自撞检查；不吃时尾格会腾空，跳过尾段
    lda eat_flag
    bne @cnt_all
    inx
    lda length
    sec
    sbc #1
    jmp @cnt_done
@cnt_all:
    lda length
@cnt_done:
    sta tmp3
    ldy #0
@chk:
    lda tmp3
    beq @alive
    lda snake_x,x
    cmp nx
    bne @next
    lda snake_y,x
    cmp ny
    beq @dead2
@next:
    inx
    iny
    cpy tmp3
    bne @chk
    jmp @alive
@dead2:
    jmp dead
@alive:
    lda head_x                  ; 旧头 -> 身体
    sta tx
    lda head_y
    sta ty
    lda #T_BODY
    jsr queue_tile

    lda eat_flag                ; 不吃则擦掉尾巴
    bne @no_tail
    ldx tail_idx
    lda snake_x,x
    sta tx
    lda snake_y,x
    sta ty
    lda #T_BLANK
    jsr queue_tile
    inc tail_idx
@no_tail:
    inc head_idx                ; 新头入环形队列
    ldx head_idx
    lda nx
    sta snake_x,x
    sta head_x
    lda ny
    sta snake_y,x
    sta head_y
    lda eat_flag
    beq @no_grow
    lda length
    cmp #MAX_LEN
    bcs @no_grow
    inc length
@no_grow:
    lda head_x                  ; 画新头
    sta tx
    lda head_y
    sta ty
    lda dir
    clc
    adc #T_HEAD_U
    jsr queue_tile

    lda eat_flag
    beq @done
    jsr sfx_eat
    jsr on_eat
    jsr update_hi
    jsr spawn_food
    lda food_x
    sta tx
    lda food_y
    sta ty
    lda #T_FOOD
    jsr queue_tile
    jsr queue_hud
@done:
    rts

dead:
    lda #ST_OVER
    sta state
    jsr sfx_die
    jsr update_hi
    lda #0
    sta draw_n
    lda #<screen_over
    sta ptr_lo
    lda #>screen_over
    sta ptr_hi
    jsr redraw
    jsr queue_over_hud
    jsr enable_display
    rts

; ---------------------------------------------------------------------------
;  新开一局
; ---------------------------------------------------------------------------
new_game:
    jsr sfx_start
    lda #0
    sta draw_n
    sta paused
    sta tick
    sta eaten
    sta food_frame
    ldx #5
    lda #0
@clr:
    sta score_digits,x
    dex
    bpl @clr
    ldx #2
@clr2:
    sta food_bcd,x
    dex
    bpl @clr2
    sta level_hi
    sta level_lo
    lda #1
    sta level_lo
    lda #INTERVAL_INIT
    sta interval

    lda #START_LEN
    sta length
    lda #0
    sta tail_idx
    lda #START_LEN-1
    sta head_idx
    ldx #0
@sn:
    txa
    clc
    adc #START_X
    sta snake_x,x
    lda #START_Y
    sta snake_y,x
    inx
    cpx #START_LEN
    bne @sn
    lda #START_X+START_LEN-1
    sta head_x
    lda #START_Y
    sta head_y
    lda #DIR_R
    sta dir
    sta newdir
    jsr spawn_food

    lda #ST_PLAY
    sta state
    lda #<screen_play
    sta ptr_lo
    lda #>screen_play
    sta ptr_hi
    jsr redraw

    ldx tail_idx                ; 初始蛇身
    ldy #0
@ds:
    lda snake_x,x
    sta tx
    lda snake_y,x
    sta ty
    lda #T_BODY
    jsr queue_tile
    inx
    iny
    cpy length
    bne @ds
    lda head_x                  ; 头
    sta tx
    lda head_y
    sta ty
    lda #T_HEAD_R
    jsr queue_tile
    lda food_x                  ; 食物
    sta tx
    lda food_y
    sta ty
    lda #T_FOOD
    jsr queue_tile
    jsr queue_hud
    jsr enable_display
    rts

; ---------------------------------------------------------------------------
;  标题画面
; ---------------------------------------------------------------------------
show_title:
    lda #ST_TITLE
    sta state
    lda #0
    sta draw_n
    lda #<screen_title
    sta ptr_lo
    lda #>screen_title
    sta ptr_hi
    jsr redraw
    ldx #0                      ; 标题上的 HI 分数
@hi:
    lda hi_digits,x
    clc
    adc #T_DIGITS
    sta tmp2
    txa
    clc
    adc #TITLE_HI_X
    sta tx
    lda #TITLE_HI_Y
    sta ty
    lda tmp2
    jsr queue_tile
    inx
    cpx #6
    bne @hi
    jsr enable_display
    rts

; ---------------------------------------------------------------------------
;  状态处理
; ---------------------------------------------------------------------------
handle_title:
    lda #BTN_START
    jsr just_pressed
    beq @done
    jsr new_game
@done:
    rts

handle_over:
    lda #BTN_START
    jsr just_pressed
    beq @no_start
    jsr new_game
    rts
@no_start:
    lda #BTN_SELECT
    jsr just_pressed
    beq @done
    jsr show_title
@done:
    rts

handle_play:
    lda #BTN_SELECT
    jsr just_pressed
    beq @no_sel
    jsr show_title
    rts
@no_sel:
    lda #BTN_START
    jsr just_pressed
    beq @no_start
    lda paused
    eor #1
    sta paused
    jsr update_pause_hud
@no_start:
    lda paused
    bne @done
    jsr handle_dirs
    jsr food_blink
    inc tick
    lda tick
    cmp interval
    bcc @done
    lda #0
    sta tick
    jsr do_move
@done:
    rts

; ---------------------------------------------------------------------------
;  主循环：等一个 NMI 帧，再跑逻辑
; ---------------------------------------------------------------------------
main:
    lda frame
@wait:
    cmp frame
    beq @wait
    jsr read_joy
    lda state
    cmp #ST_TITLE
    beq @title
    cmp #ST_PLAY
    beq @play
    jsr handle_over
    jmp main
@title:
    jsr handle_title
    jmp main
@play:
    jsr handle_play
    jmp main

; ============================================================================
;  Read-only data
; ============================================================================
.segment "RODATA"

palette:
    .byte $0F,$30,$2A,$16       ; BG0: 黑 / 白 / 绿 / 红
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16
    .byte $0F,$30,$2A,$16       ; SP0..SP3
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
    .byte ":-.!?/+<>*()=%#,"
    .byte 0

str_paused:
    .byte "PAUSED",0
str_blank6:
    .byte "      ",0

.include "screens.inc"

; ============================================================================
;  Vectors
; ============================================================================
.segment "VECTORS"
    .word nmi
    .word reset
    .word irq
