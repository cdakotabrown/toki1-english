#ifndef PATCH_TEXT_H
#define PATCH_TEXT_H

#include "types.h"

#define PT_C_NEWLINE   0x01
#define PT_C_BREAK     0x02
#define PT_C_PNAME     0x03
#define PT_C_GNAME     0x04
#define PT_C_PFAMILY   0x05
#define PT_C_PGIVEN    0x06
#define PT_C_PFULL     0x07
#define PT_C_YOSHIO    0x08
#define PT_C_TOK_S     0x09
#define PT_C_TOK_O     0x0A
#define PT_C_TOK_W     0x0B
#define PT_C_TOK_A     0x0C
#define PT_C_TOK_M     0x0D
#define PT_C_REF       0x1C
#define PT_C_STR       0x1D
#define PT_C_DST       0x1A
#define PT_STR_COUNT   64
#define PT_STR_BASE    0x20
#define PT_C_LAST      0x1F

#define PT_IS_CTRL(b)   ((b) >= 0x01 && (b) <= PT_C_LAST)
#define PT_IS_ASCII(b)  ((b) >= 0x20 && (b) <= 0x7E)
#define PT_IS_SJIS_LEAD(b) (((b) >= 0x81 && (b) <= 0x9F) || ((b) >= 0xE0 && (b) <= 0xEF))
#define PT_IS_DTE(b)    (((b) >= 0xA0 && (b) <= 0xDF) || ((b) >= 0xF0 && (b) <= 0xFE))
#define PT_DTE_INDEX(b) ((b) >= 0xF0 ? 64 + ((b) - 0xF0) : (b) - 0xA0)
#define PT_DTE_COUNT    79

#define PT_CELL_W       16
#define PT_CELL_H       12
#define PT_MAX_CELLS    384
#define PT_MAX_ENTRIES  52

typedef struct {
    s16 x;
    s16 y;
    u8 tp;
    u8 count;
    u8 ot;
    u8 flag;
} PtEntry;

typedef struct {
    u8 *next;
    u16 code;
    u8 is_sjis;
    u8 is_ctrl;
} PtChar;

extern s32 pt_next(u8 **pp, PtChar *out);

extern s32 pt_text_width(u8 *s);
extern s32 pt_char_width(u16 code, s32 is_sjis);
extern s32 pt_is_packed(u8 *s);

extern const u16 patch_font_rows[95][12];
extern const u8 patch_font_adv[95];

/* button icons for the private Shift-JIS codes PT_ICON_FIRST.. (one per
   code, in order: tools/patch/font/icons12.txt via fontgen.py) */
#define PT_ICON_FIRST  0xEF40
extern const s32 patch_icon_count;
extern const u16 patch_icon_rows[][12];

extern u8 *pt_long_name(u32 slot);

extern u8 *pt_fit_label_w(u8 *name, s32 budget);

extern u8 *patch_str_table[PT_STR_COUNT];
extern u8 *pt_str(u32 idx);

extern u8 *patch_dte_table[PT_DTE_COUNT];

extern u8 patch_entry_adv[PT_MAX_ENTRIES + 1];

extern s32 patch_kanji_limit;

#endif
