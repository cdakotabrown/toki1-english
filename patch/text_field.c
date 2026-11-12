#include "patch_text.h"

extern u8 now_girl;
extern u8 k_cnt;
extern u8 k_no;
extern s8 k_mode;
extern u8 sndi_str0[];
extern u8 sndi_str1[];
extern u8 sndi_str2[];

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern u8 check_set_k(void);
extern void k_disp_switch(s32, s32);
extern void get_p_name(u8 *, s32);
extern s32 get_g_name(u8 *, s32);
extern s32 pt_legacy_to_patch(u8 *);

#define PT_FIELD_MAX   512
#define PT_FIELD_RIGHT 129

static u8 pt_field_buf[PT_FIELD_MAX];
static u8 pt_field_line_buf[PT_FIELD_MAX];
static u8 pt_name_buf[64];
static u8 pt_field_ascii_prefix[2];

static s32 pt_field_hang;

static s32 pt_cat(u8 *dst, s32 n, u8 *src, s32 cap)
{
    while (*src != 0 && n < cap - 1) {
        dst[n++] = *src++;
    }
    dst[n] = 0;
    return n;
}

static void pt_field_expand(u8 *dst, u8 *src, s32 kind)
{
    s32 n = 0;
    u32 b;

    dst[0] = 0;
    while ((b = *src) != 0) {
        if (b == PT_C_PNAME) {
            get_p_name(pt_name_buf, ((kind & 0xF) == 15) ? 15 : now_girl);
            n = pt_cat(dst, n, pt_name_buf, PT_FIELD_MAX);
            src++;
        } else if (b == PT_C_GNAME) {
            get_g_name(pt_name_buf, now_girl);
            n = pt_cat(dst, n, pt_name_buf, PT_FIELD_MAX);
            src++;
        } else if (b == PT_C_REF) {
            n = pt_cat(dst, n, pt_long_name(src[1]), PT_FIELD_MAX);
            src += 2;
        } else if (b == PT_C_STR && src[1] != 0) {

            u8 *t = pt_str(src[1] - PT_STR_BASE);
            while (*t != 0 && n < PT_FIELD_MAX - 1) {
                if (*t != PT_C_DST) {
                    dst[n++] = *t;
                }
                t++;
            }
            dst[n] = 0;
            src += 2;
        } else if (PT_IS_CTRL(b)) {
            src++;
        } else if (PT_IS_DTE(b)) {

            if (patch_dte_table[PT_DTE_INDEX(b)] != 0) {
                n = pt_cat(dst, n, patch_dte_table[PT_DTE_INDEX(b)], PT_FIELD_MAX);
            }
            src++;
        } else if (PT_IS_SJIS_LEAD(b) && src[1] != 0) {
            if (n < PT_FIELD_MAX - 2) {
                dst[n++] = b;
                dst[n++] = src[1];
                dst[n] = 0;
            }
            src += 2;
        } else {
            if (n < PT_FIELD_MAX - 1) {
                dst[n++] = b;
                dst[n] = 0;
            }
            src++;
        }
    }
}

static s32 pt_field_x(s32 row, s32 kind)
{
    if (kind == 255) {
        return -128;
    }
    if (row == 0 && pt_field_hang) {
        return -72 - pt_text_width(pt_field_ascii_prefix) - 1;
    }
    return row == 0 ? -86 : -72;
}

static s16 pt_field_y(s32 row)
{
    return (s16)(row < 2 ? 50 + row * 16 : 82);
}

static void pt_field_place(s32 x, s32 row, u8 *text)
{
    set_kanji_string((s16)x, pt_field_y(row), 0, text, 0);
    if (row >= 3) {
        k_disp_switch(check_set_k() - 1, 0);
    }
}

static u8 *pt_field_prefix(s32 kind)
{
    if (kind == 15) {
        return sndi_str0;
    }
    if (kind == 31) {
        return sndi_str1;
    }
    if (kind == 47 || kind == 255) {
        return 0;
    }
    return sndi_str2;
}

static s32 pt_field_queue(u8 *text, s32 row, s32 kind)
{
    u8 *seg = text;
    u8 *p = text;
    u8 *q;
    u8 *last_space = 0;
    PtChar c;
    s32 w = 0;
    s32 cw;
    s32 x;
    s32 max_px;
    s32 packed = pt_is_packed(text);
    u8 saved;

    pt_reset();
    for (;;) {
        q = p;
        if (!pt_next(&p, &c)) {
            break;
        }
        if (c.is_ctrl) {
            continue;
        }
        cw = packed ? pt_char_width(c.code, c.is_sjis) : 14;
        x = pt_field_x(row, kind);
        max_px = PT_FIELD_RIGHT - x;
        if (w + cw > max_px && q > seg) {
            if (last_space != 0 && last_space > seg) {
                *last_space = 0;
                pt_field_place(x, row, seg);
                seg = last_space + 1;
            } else {
                saved = *q;
                *q = 0;
                pt_field_place(x, row, seg);
                *q = saved;
                seg = q;
            }
            p = seg;
            row++;
            w = 0;
            last_space = 0;
            pt_reset();
            continue;
        }
        if (!c.is_sjis && c.code == ' ') {
            last_space = q;
        }
        w += cw;
    }
    x = pt_field_x(row, kind);
    pt_field_place(x, row, seg);
    return row + 1;
}

s32 pt_field_line(u8 *src, s32 mode, s32 kind)
{
    u8 *prefix;
    s32 n = 0;

    k_mode = 0;
    pt_field_hang = 0;
    pt_field_expand(pt_field_line_buf + 8, src, kind);

    prefix = (mode == 0) ? pt_field_prefix(kind) : 0;
    if (prefix != 0 && pt_is_packed(pt_field_line_buf + 8)) {

        pt_field_ascii_prefix[0] = (kind == 31) ? '(' : '"';
        pt_field_ascii_prefix[1] = 0;
        prefix = pt_field_ascii_prefix;
        pt_field_hang = 1;
    }
    if (prefix != 0) {
        n = pt_cat(pt_field_line_buf, 0, prefix, 8);
        {
            u8 *s = pt_field_line_buf + 8;
            u8 *d = pt_field_line_buf + n;
            while (*s != 0) {
                *d++ = *s++;
            }
            *d = 0;
        }
        return pt_field_queue(pt_field_line_buf, mode, kind);
    }
    return pt_field_queue(pt_field_line_buf + 8, mode, kind);
}

void pt_field_message(u8 *str, s32 y, s32 kind)
{
    u8 *p;
    u8 *start;
    u32 b;
    s32 row = 0;

    (void)y;
    {
        s32 i = 0;
        while (str[i] != 0 && i < PT_FIELD_MAX - 1) {
            pt_field_buf[i] = str[i];
            i++;
        }
        pt_field_buf[i] = 0;
    }
    pt_legacy_to_patch(pt_field_buf);
    k_no = check_set_k();
    start = pt_field_buf;
    p = pt_field_buf;
    for (;;) {
        b = *p;
        if (b == PT_C_NEWLINE || b == PT_C_BREAK || b == 0) {
            *p = 0;
            row = pt_field_line(start, row, kind);
            if (b == 0) {
                break;
            }
            p++;
            start = p;
            continue;
        }
        if (PT_IS_SJIS_LEAD(b) && p[1] != 0) {
            p += 2;
        } else {
            p++;
        }
    }
    k_cnt = check_set_k();
    k_mode = (s8)0x80;
}

void pt_speaker_label(u8 *name)
{
    s32 w;
    s32 x;

    name = pt_fit_label_w(name, 46);
    w = pt_text_width(name);
    x = -128 + (42 - w) / 2;

    if (x > -114) {
        x = -114;
    }
    if (x < -128) {
        x = -128;
    }
    set_kanji_string((s16)x, 50, 0, name, 0);
}
