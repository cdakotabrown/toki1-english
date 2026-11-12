#ifndef DBG_H
#define DBG_H

#include "types.h"

extern void game_main(void);
extern void goto_step(s32 step);
extern void load_image_rect(s32 x, s32 y, s32 w, s32 h, s32 src);
extern void _debug_string_show(u8 *str, s32 x, s32 y, s32 pal);
extern void _debug_number_show(s32 num, s32 x, s32 y, s32 pal);
extern void debug_hex_show(u32 val, s32 x, s32 y);
extern void *prim_alloc(s32 size, s32 buf);
extern void SetTile(void *p);
extern void SetSemiTrans(void *p, s32 on);
extern void AddPrim(void *ot_entry, void *p);

extern u8 D_800B9710;
extern u8 D_800BA280;
extern u8 D_800BA158;
extern u8 D_800BD234;
extern s32 pad_data;
extern s32 pad_trig;
extern u8 now_step;
extern u8 now_sub_step;
extern u8 now_sub_sub_step;
extern u8 step_mode;
extern u8 D_800EF86E;
extern u8 now_girl;
extern u8 now_year;
extern u8 now_month;
extern u8 now_day;
extern u8 screen_w[];
extern s16 D_800EE85E;
extern s32 activeBuff;
extern u8 ot_buff0[];
extern u8 D_800EF872;

#define PAD_L2       0x0001
#define PAD_R2       0x0002
#define PAD_L1       0x0004
#define PAD_R1       0x0008
#define PAD_TRI      0x0010
#define PAD_CIRCLE   0x0020
#define PAD_CROSS    0x0040
#define PAD_SQUARE   0x0080
#define PAD_SELECT   0x0100
#define PAD_START    0x0800
#define PAD_UP       0x1000
#define PAD_RIGHT    0x2000
#define PAD_DOWN     0x4000
#define PAD_LEFT     0x8000

#define DBG_OPEN_MASK   (PAD_L2 | PAD_R2)

typedef struct {
    u8 id;
    u8 girl;
    u8 exn[9];
    u8 label[15];
} DbgScene;

extern const DbgScene dbg_scenes[];
extern const s32 dbg_scene_count;
extern const u8 dbg_font_image[4096];

void dbg_game_main(void);
void dbg_font_load(void);
void dbg_unlock_all(void);
void dbg_str(const u8 *s, s32 x, s32 y, s32 pal);
void dbg_num(s32 v, s32 x, s32 y, s32 pal);

#endif
