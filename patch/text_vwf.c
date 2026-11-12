#include "patch_text.h"

extern PtEntry disp_string_tbl0[];
extern s16 disp_string_state;
extern s16 check_end_k_tbl0;
extern u8 k_cell_w;
extern u16 load_string_tbl0;
extern u16 load_string_tbl1[];
extern u16 load_string_tbl2;
extern u8 melt_font_tbl0[];

extern void load_image_rect(s32, s32, s32, s32, void *);
extern void DrawSync(s32);

u8 *patch_dte_table[PT_DTE_COUNT];
u8 *patch_str_table[PT_STR_COUNT];

u8 *pt_str(u32 idx)
{
    if (idx >= PT_STR_COUNT || patch_str_table[idx] == 0) {
        return (u8 *)"";
    }
    return patch_str_table[idx];
}

u8 patch_entry_adv[PT_MAX_ENTRIES + 1];

u16 patch_glyph_x[PT_MAX_CELLS];
u32 patch_glyph_fallbacks;
u32 patch_glyph_drops;
s32 patch_kanji_limit = 3418;
u8 patch_fixed_cell;

static u32 pt_cell[24];
static s32 pt_pen;
static s32 pt_glyph_cell_mode;
static u8 *pt_dte_p;

void pt_reset(void)
{
    pt_dte_p = 0;
}

s32 pt_next(u8 **pp, PtChar *out)
{
    u8 *p;
    u32 b;
    u32 lo;

    for (;;) {
        if (pt_dte_p != 0) {
            b = *pt_dte_p;
            if (b == 0) {
                pt_dte_p = 0;
                continue;
            }
            pt_dte_p++;
            if (b == PT_C_DST) {
                continue;
            }
            out->code = (u16)b;
            out->is_sjis = 0;
            out->is_ctrl = PT_IS_CTRL(b);
            return 1;
        }
        p = *pp;
        b = *p;
        if (b == 0) {
            return 0;
        }
        if (b == PT_C_REF) {

            *pp = pt_long_name(p[1]);
            continue;
        }
        if (PT_IS_DTE(b)) {
            *pp = p + 1;
            pt_dte_p = patch_dte_table[PT_DTE_INDEX(b)];
            continue;
        }
        if (b == PT_C_STR) {

            if (p[1] == 0) {
                return 0;
            }
            *pp = p + 2;
            pt_dte_p = pt_str(p[1] - PT_STR_BASE);
            continue;
        }
        if (PT_IS_SJIS_LEAD(b)) {
            lo = p[1];
            if (lo == 0) {
                return 0;
            }
            *pp = p + 2;
            out->code = (u16)((b << 8) | lo);
            out->is_sjis = 1;
            out->is_ctrl = 0;
            return 1;
        }
        *pp = p + 1;
        out->code = (u16)b;
        out->is_sjis = 0;
        out->is_ctrl = PT_IS_CTRL(b);
        return 1;
    }
}

s32 pt_is_packed(u8 *s)
{
    u32 b;

    while ((b = *s) != 0) {
        if (b == PT_C_REF) {
            s = pt_long_name(s[1]);
            continue;
        }
        if (PT_IS_ASCII(b) || PT_IS_DTE(b) || b == 0x7F || b == PT_C_STR) {
            return 1;
        }
        if (PT_IS_SJIS_LEAD(b)) {
            if (s[1] == 0) {
                return 0;
            }
            s += 2;
        } else {
            s += 1;
        }
    }
    return 0;
}

static s32 pt_sjis_glyph(u32 code)
{
    s32 i;

    if (code < load_string_tbl0) {
        return -1;
    }
    i = 0;
    do {
        if (code < load_string_tbl1[i]) {
            return (s32)load_string_tbl1[i - 1] + ((s32)code - (s32)load_string_tbl1[i - 2]);
        }
        i += 2;
    } while (&load_string_tbl1[i] != &load_string_tbl2);
    return -1;
}

static u32 pt_kanji_row(u8 *g, s32 r)
{
    s32 bit = r * 12;
    s32 byte = bit >> 3;
    u32 w = ((u32)g[byte] << 16) | ((u32)g[byte + 1] << 8) | g[byte + 2];

    w >>= 24 - 12 - (bit & 7);
    return (w & 0xFFF) << 4;
}

static void pt_box_rows(u16 *rows)
{
    s32 r;

    for (r = 0; r < 12; r++) {
        rows[r] = 0;
    }

    rows[1] = 0x7FC0;
    for (r = 2; r < 9; r++) {
        rows[r] = (u16)(0x4040 | (0x2000 >> (r - 2)));
    }
    rows[9] = 0x7FC0;
}

u16 *patch_kanji_sub_codes;
u8 *patch_kanji_sub_glyphs;
s32 patch_kanji_sub_count;

static u8 *pt_kanji_sub_find(u32 code)
{
    s32 lo = 0;
    s32 hi = patch_kanji_sub_count - 1;
    s32 mid;

    if (patch_kanji_sub_codes == 0) {
        return 0;
    }
    while (lo <= hi) {
        mid = (lo + hi) >> 1;
        if (patch_kanji_sub_codes[mid] == code) {
            return patch_kanji_sub_glyphs + mid * 18;
        }
        if (patch_kanji_sub_codes[mid] < code) {
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    return 0;
}

static void pt_sjis_rows(u32 code, u16 *rows)
{
    s32 g = pt_sjis_glyph(code);
    s32 r;
    u8 *src;

    if (g < 0) {
        g = (s32)code - PT_ICON_FIRST;
        if (g < 0 || g >= patch_icon_count) {
            pt_box_rows(rows);
            return;
        }
        for (r = 0; r < 12; r++) {
            rows[r] = patch_icon_rows[g][r];
        }
        return;
    }
    if (g >= patch_kanji_limit) {
        src = pt_kanji_sub_find(code);
        if (src == 0) {
            pt_box_rows(rows);
            return;
        }
    } else {
        src = &melt_font_tbl0[g * 18];
    }
    for (r = 0; r < 12; r++) {
        rows[r] = (u16)pt_kanji_row(src, r);
    }
}

static void pt_ascii_rows(u32 code, u16 *rows)
{
    const u16 *src;
    s32 r;

    if (code < 0x20 || code > 0x7E) {
        code = '?';
    }
    src = patch_font_rows[code - 0x20];
    for (r = 0; r < 12; r++) {
        rows[r] = src[r];
    }
}

s32 pt_char_width(u16 code, s32 is_sjis)
{
    if (is_sjis) {
        return 14;
    }
    if (code < 0x20 || code > 0x7E) {
        return patch_font_adv['?' - 0x20];
    }
    return patch_font_adv[code - 0x20];
}

static void pt_cell_clear(void)
{
    s32 i;

    for (i = 0; i < 24; i++) {
        pt_cell[i] = 0;
    }
    pt_pen = 0;
}

static void pt_flush(void)
{
    s32 idx = check_end_k_tbl0;
    s32 x;
    s32 y;

    if (idx < 0 || idx >= PT_MAX_CELLS) {
        patch_glyph_drops++;
        pt_cell_clear();
        return;
    }
    if (idx < 128) {
        x = ((idx & 7) << 2) + 800;
    } else if (idx < 256) {
        x = ((idx & 7) << 2) + 864;
    } else {
        x = ((idx & 7) << 2) + 928;
    }
    y = ((idx & 0x78) << 1) + 256;
    if (!pt_glyph_cell_mode) {
        patch_glyph_x[idx] = 0;
    }
    load_image_rect(x, y, 4, 12, pt_cell);
    DrawSync(0);
    check_end_k_tbl0 = (s16)(idx + 1);
    pt_cell_clear();
}

static void pt_blit(u16 *rows, s32 adv)
{
    s32 r;
    s32 x;
    s32 room;
    s32 take;
    u32 bits;

    while (adv > 0) {
        room = PT_CELL_W - pt_pen;
        take = adv < room ? adv : room;
        for (r = 0; r < 12; r++) {
            bits = rows[r];
            if (bits == 0) {
                continue;
            }
            for (x = 0; x < take; x++) {
                if (bits & (0x8000 >> x)) {
                    if (pt_pen + x < 8) {
                        pt_cell[r * 2] |= 1u << ((pt_pen + x) * 4);
                    } else {
                        pt_cell[r * 2 + 1] |= 1u << ((pt_pen + x - 8) * 4);
                    }
                }
            }
            rows[r] = (u16)((bits << take) & 0xFFFF);
        }
        pt_pen += take;
        adv -= take;
        if (pt_pen >= PT_CELL_W) {
            pt_flush();
        }
    }
}

static void pt_draw_char(u32 code, s32 is_sjis)
{
    u16 rows[12];

    if (is_sjis) {
        pt_sjis_rows(code, rows);
        pt_blit(rows, 14);
    } else {
        pt_ascii_rows(code, rows);
        pt_blit(rows, pt_char_width((u16)code, 0));
    }
}

s32 pt_text_width(u8 *s)
{
    PtChar c;
    u8 *p = s;
    s32 w = 0;
    s32 packed = pt_is_packed(s);

    pt_reset();
    while (pt_next(&p, &c)) {
        if (c.is_ctrl) {
            continue;
        }
        if (packed) {
            w += pt_char_width(c.code, c.is_sjis);
        } else {
            w += k_cell_w;
        }
    }
    return w;
}

static s32 pt_glyph_count(u8 *str)
{
    u8 *p = str;
    PtChar c;
    s32 n = 0;

    pt_reset();
    while (pt_next(&p, &c)) {
        if (!c.is_ctrl) {
            n++;
        }
    }
    return n;
}

static s32 pt_cache_overflow(void)
{
    u16 rows[12];

    patch_glyph_drops++;
    if (check_end_k_tbl0 >= PT_MAX_CELLS) {
        return 0;
    }
    pt_box_rows(rows);
    pt_blit(rows, PT_CELL_W);
    return 1;
}

s32 load_string(u8 *str)
{
    PtChar c;
    u8 *p = str;
    s32 saved = check_end_k_tbl0;
    s32 entry = disp_string_state;
    s32 count;
    s32 packed_count;
    s32 x;
    u16 rows[12];

    if (entry < 0 || entry > PT_MAX_ENTRIES) {
        entry = PT_MAX_ENTRIES;
    }
    pt_cell_clear();
    pt_reset();
    pt_glyph_cell_mode = 0;
    if (!pt_is_packed(str)) {

        patch_entry_adv[entry] = 0;
        count = pt_glyph_count(str);
        if (count > 255 || count > PT_MAX_CELLS - saved) {
            return pt_cache_overflow();
        }
        pt_reset();
        while (pt_next(&p, &c)) {
            if (!c.is_sjis) {
                continue;
            }
            pt_sjis_rows(c.code, rows);
            pt_blit(rows, PT_CELL_W);
        }
        return check_end_k_tbl0 - saved;
    }
    patch_entry_adv[entry] = PT_CELL_W;
    count = pt_glyph_count(str);
    if (patch_fixed_cell) {

        if (count > 255 || count > PT_MAX_CELLS - saved) {
            return pt_cache_overflow();
        }
        pt_reset();
        while (pt_next(&p, &c)) {
            if (c.is_ctrl) {
                continue;
            }
            pt_cell_clear();
            if (!c.is_sjis) {
                pt_pen = (PT_CELL_W - pt_char_width(c.code, 0)) / 2;
            }
            pt_draw_char(c.code, c.is_sjis);
            if (pt_pen > 0) {
                pt_flush();
            }
        }
        return check_end_k_tbl0 - saved;
    }
    if (count <= 255 && count <= PT_MAX_CELLS - saved) {

        patch_entry_adv[entry] = 0xFF;
        pt_glyph_cell_mode = 1;
        x = 0;
        pt_reset();
        while (pt_next(&p, &c)) {
            if (c.is_ctrl) {
                continue;
            }
            patch_glyph_x[check_end_k_tbl0] = (u16)(0x8000 | x);
            pt_draw_char(c.code, c.is_sjis);
            if (pt_pen > 0) {
                pt_flush();
            }
            x += pt_char_width(c.code, c.is_sjis);
        }
        pt_glyph_cell_mode = 0;
        return check_end_k_tbl0 - saved;
    }
    packed_count = (pt_text_width(str) + PT_CELL_W - 1) / PT_CELL_W;
    if (packed_count > 255 || packed_count > PT_MAX_CELLS - saved) {
        return pt_cache_overflow();
    }
    patch_glyph_fallbacks++;
    pt_reset();
    while (pt_next(&p, &c)) {
        if (c.is_ctrl) {
            continue;
        }
        pt_draw_char(c.code, c.is_sjis);
    }
    if (pt_pen > 0) {
        pt_flush();
    }
    return check_end_k_tbl0 - saved;
}

u32 patch_draw_hook = 1;

typedef void (*PtDrawHook)(s16, s16, u8 *);

s16 set_kanji_string(s16 x, s16 y, u8 attr, u8 *str, s32 ot)
{
    PtEntry *e;
    s32 n;

    if ((patch_draw_hook & 3) == 0 && str != 0 && str[0] != 0) {
        ((PtDrawHook)patch_draw_hook)(x, y, str);
    }

    if (disp_string_state >= PT_MAX_ENTRIES) {
        return -1;
    }
    e = &disp_string_tbl0[disp_string_state];
    if (str == 0 || str[0] == 0) {
        e->flag = 0;
        e->count = 0;
    } else {
        e->y = y;
        e->tp = attr;
        e->x = x;
        n = load_string(str);
        e = &disp_string_tbl0[disp_string_state];
        e->count = (u8)n;
        e->flag = 1;
        e->ot = (u8)ot;
    }
    disp_string_state = disp_string_state + 1;
    return disp_string_state;
}
