#include "patch_text.h"

typedef struct {
    u8 f0;
    u8 f1;
    u8 f2;
    u8 f3;
    u8 f4;
    u8 f5;
    u8 pad6[6];
    s32 *f12;
    s32 *f16;
    s16 f20;
    s16 pad22;
    s16 f24;
    u8 pad26[12];
    s16 f38;
    s16 pad40;
    s16 f42;
    u8 pad44[8];
    s32 *f52;
    u32 f56;
    u8 pad60[8];
} PtRec;

typedef struct {
    u8 pad0[204];
    PtRec rec[16];
} PtObj;

extern PtObj class_w;
extern s16 basyo_init_tbl0;
extern s16 mes_base_y;
extern s32 basyo_init_tbl1;
extern s32 basyo_init_tbl2;
extern s32 _sys_default_tpage_set_tbl2;
extern s16 basyo_init_tbl3;
extern void class_clear_n(s32);
extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);

void pt_basyo_init(u8 *str)
{
    s32 i;
    s32 w;

    mes_base_y = -64;
    for (i = 0; i < basyo_init_tbl0 + 2; i++) {
        class_clear_n(i + 3);
    }
    set_kanji_string(-206, -152, 0, str, 0);
    w = pt_text_width(str);
    basyo_init_tbl0 = (s16)((w + 13) / 14);
    if (basyo_init_tbl0 > 13) {
        basyo_init_tbl0 = 13;
    }
    for (i = 0; i < basyo_init_tbl0 + 2; i++) {
        class_clear_n(i + 3);
        class_w.rec[i].f1 = 2;
        class_w.rec[i].f2 = 64;
        class_w.rec[i].f56 = 0x40000000;
        class_w.rec[i].f3 = 164;
        class_w.rec[i].f12 = &basyo_init_tbl1;
        class_w.rec[i].f16 = &basyo_init_tbl2;
        class_w.rec[i].f52 = &_sys_default_tpage_set_tbl2;
        class_w.rec[i].f20 = basyo_init_tbl3;
        class_w.rec[i].f4 = 8;
        class_w.rec[i].f5 = 1;
        class_w.rec[i].f24 = 114;
        class_w.rec[i].f38 = (s16)((basyo_init_tbl0 - i) * 14 + mes_base_y - 135);
        class_w.rec[i].f42 = (s16)(mes_base_y - 81);
    }
    class_w.rec[basyo_init_tbl0 + 1].f24 = 113;
    class_w.rec[basyo_init_tbl0 + 1].f38 += 2;
    class_w.rec[0].f24 = 115;
    class_w.rec[0].f38 -= 2;
}

/* Sunday's own frame for the calendar banner's weekday sprite (hizuke_init:
 * frame now_youbi + 82 of the table D_800CFC5C).  Retail frame 88 draws the
 * 日 cell (MAINROM page 4, tile 0x2a) that the day unit also uses, so the
 * English cell could only read "D" for both.  This frame draws "Su" from
 * the halves of the Sa and Tu cells (src/patch/art/MAINROM: S on tile
 * 0x28, u on tile 0x21, each on the 8-px grid); the table entry for frame
 * 88 is pointed here by a poke in config/patch/english.json.  Layout:
 * s16 count, w, h, pad, then per cel s16 ox, oy, cel, tp, attr, w, h,
 * stored as little-endian half-word pairs so the record stays
 * word-aligned like the retail ones. */
#define PT_H2(a, b) ((u32)(u16)(a) | ((u32)(u16)(b) << 16))
const u32 pt_hud_sunday_frame[9] = {
    PT_H2(2, 0x20), PT_H2(8, 0),
    PT_H2(23, 0), PT_H2(0x28, 0x3100), PT_H2(0, 8), PT_H2(16, 31),
    PT_H2(0, 0x21), PT_H2(0x3100, 0), PT_H2(8, 16)
};

extern void strcpy(void *, s32);
extern void k_disp_start(s32);
extern void menu_set(s32, s32, void *, void *, void *, void *);
extern u8 girl_appear[];
extern s16 girl_menu_set_tbl0[];
extern s16 girl_menu_set_tbl1[];
extern s16 girl_menu_select_tbl0[];
extern s16 girl_menu_set_tbl2[];
extern s32 date_name_set_tbl0[];
extern u8 girl_menu_set_str0[];
extern s8 menu_csr;
extern s32 menu_on;
extern s32 step_counter;

void pt_vacation_day_init1(u8 arg0)
{
    s32 ret = 0;
    s16 i;
    u8 name[64];

    for (i = 0; i < 11; i++) {
        girl_menu_set_tbl0[i] = (s16)(((i / 3) << 6) - 128);
        girl_menu_set_tbl1[i] = (s16)(((i % 3) << 4) + 48);
        if (girl_appear[i] != 0) {
            strcpy(name, date_name_set_tbl0[i]);
            ret = set_kanji_string(girl_menu_set_tbl0[i], girl_menu_set_tbl1[i], 0, name, 0);
            girl_menu_select_tbl0[i] = (s16)pt_text_width(name);
            if (girl_menu_select_tbl0[i] > 62) {
                girl_menu_select_tbl0[i] = 62;
            }
        } else {
            girl_menu_select_tbl0[i] = 0;
        }
        girl_menu_set_tbl2[i] = 16;
    }
    girl_menu_set_tbl0[11] = 64;
    girl_menu_set_tbl1[11] = 80;
    girl_menu_select_tbl0[11] = 42;
    girl_menu_set_tbl2[11] = 16;
    if (arg0 != 0) {
        girl_menu_select_tbl0[11] = 0;
    }
    if (arg0 == 0) {
        ret = set_kanji_string(64, 80, 0, girl_menu_set_str0, 0);
    }
    k_disp_start(ret);
    menu_set(1, (12 - arg0) & 0xFF, girl_menu_set_tbl0, girl_menu_set_tbl1, girl_menu_select_tbl0, girl_menu_set_tbl2);
    for (i = 0; i < 11; i++) {
        if (girl_menu_select_tbl0[i] != 0) {
            menu_csr = (s8)i;
            break;
        }
    }
    menu_on = 1;
    step_counter++;
}

extern s32 get_g_zyotai_s(s32);
extern void strcat(u8 *, u8 *);
extern void strncat(u8 *, u8 *, s32);
extern u8 p_adana[];
extern u8 p_mei[];
extern u8 p_sei[];
extern u8 D_800B9B20[];
extern u8 D_800B9B24[];

static void pt_pn(u8 *dst, u8 *name, u8 *suffix)
{
    strcpy(dst, (s32)name);
    if (suffix != 0) {
        strcat(dst, suffix);
    }
}

void pt_get_p_name(u8 *dst, s32 a1)
{
    s32 r;

    switch (a1) {
    case 0:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_adana, 0); else pt_pn(dst, p_mei, D_800B9B20);
        break;
    case 1:
        r = get_g_zyotai_s(a1);
        pt_pn(dst, p_sei, (r & 0x80) ? D_800B9B20 : D_800B9B24);
        break;
    case 2:
    case 7:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_mei, D_800B9B20); else pt_pn(dst, p_sei, D_800B9B20);
        break;
    case 3:
    case 6:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_adana, 0); else pt_pn(dst, p_sei, D_800B9B20);
        break;
    case 4:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_mei, D_800B9B20); else pt_pn(dst, p_sei, D_800B9B20);
        break;
    case 5:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_mei, D_800B9B24); else pt_pn(dst, p_sei, D_800B9B24);
        break;
    case 8:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_adana, 0); else pt_pn(dst, p_mei, D_800B9B20);
        break;
    case 9:
        r = get_g_zyotai_s(a1);
        pt_pn(dst, p_sei, (r & 0x80) ? D_800B9B20 : D_800B9B24);
        break;
    case 10:
        r = get_g_zyotai_s(a1);
        if (r & 0x80) pt_pn(dst, p_mei, D_800B9B24); else pt_pn(dst, p_sei, D_800B9B24);
        break;
    case 13:
        pt_pn(dst, p_mei, 0);
        break;
    case 11:
        pt_pn(dst, p_mei, D_800B9B20);
        break;
    case 12:
        pt_pn(dst, p_sei, D_800B9B20);
        break;
    case 15:
        if (PT_IS_ASCII(p_sei[0])) {
            pt_pn(dst, p_mei, 0);
            strcat(dst, (u8 *)" ");
            strcat(dst, p_sei);
        } else {
            pt_pn(dst, p_sei, 0);
            strncat(dst, p_mei, 6);
        }
        break;
    case 14:
    default:
        pt_pn(dst, p_sei, D_800B9B20);
        break;
    }
}

static u8 *pt_held_family;

static s32 pt_slen(u8 *s)
{
    s32 n = 0;
    while (s[n] != 0) {
        n++;
    }
    return n;
}

static void pt_append_n(u8 *dst, u8 *src, s32 cap)
{
    s32 n = pt_slen(dst);
    s32 k = 0;
    while (src[k] != 0 && k < cap) {
        dst[n++] = src[k++];
    }
    dst[n] = 0;
}

void pt_name_hold(u8 *dst, u8 *src, s32 n)
{
    if (PT_IS_ASCII(src[0])) {
        pt_held_family = src;
        return;
    }
    pt_held_family = 0;
    strncat(dst, src, n);
}

void pt_name_put(u8 *dst, u8 *src, s32 n)
{
    if (pt_held_family == 0 || !PT_IS_ASCII(src[0])) {
        if (pt_held_family != 0) {
            pt_append_n(dst, pt_held_family, 6);
            pt_held_family = 0;
        }
        strncat(dst, src, n);
        return;
    }
    if (pt_slen(dst) > 0 && dst[pt_slen(dst) - 1] != ' ') {
        pt_append_n(dst, (u8 *)" ", 1);
    }
    pt_append_n(dst, src, 7);
    pt_append_n(dst, (u8 *)" ", 1);
    pt_append_n(dst, pt_held_family, 7);
    pt_held_family = 0;
}

void pt_full_name_cat(u8 *dst, u8 *src, s32 n)
{
    u8 fam[8];
    s32 k;

    if (!PT_IS_ASCII(dst[0]) || !PT_IS_ASCII(src[0])) {
        strncat(dst, src, n);
        return;
    }
    for (k = 0; k < 7 && dst[k] != 0; k++) {
        fam[k] = dst[k];
    }
    fam[k] = 0;
    dst[0] = 0;
    pt_append_n(dst, src, 7);
    pt_append_n(dst, (u8 *)" ", 1);
    pt_append_n(dst, fam, 7);
}

void pt_strncat_nick(u8 *dst, u8 *src, s32 n)
{
    if (PT_IS_ASCII(src[0])) {
        pt_append_n(dst, src, 15);
        return;
    }
    strncat(dst, src, n);
}

#define PT_BOOK_BUDGET 78

extern u32 *telephone_choice_menu_init_tbl0[];
extern s32 telephone_choice_menu_init_tbl1;
extern s32 telephone_choice_menu_init_tbl2;
extern u8 telephone_choice_menu_init_str0;
extern u8 telephone_choice_menu_init_str1;
extern u8 screen_w[];
extern u8 now_icon;
extern s8 cal_cw_prio;
extern u8 cal_cw_mode;
extern u8 cal_cw_disp;
extern u8 cal_cw_flag4;
extern u8 cal_cw_sel;
extern u8 cal_cw_rate;
extern u32 *cal_cw_img;
extern u32 *cal_cw_anim_tbl;
extern u32 *cal_cw_hdr;
extern s32 cal_cw_attr;
extern s16 cal_cw_aux14;
extern s16 cal_cw_anim;
extern s16 cal_cw_frame;
extern s16 cal_cw_x;
extern s16 cal_cw_y;

static u8 pt_book_names[14][24];

static u8 *pt_book_name(s32 i, u8 *name)
{
    u8 *d = pt_book_names[i];
    s32 n = 0;
    u8 *p;

    if (!PT_IS_ASCII(name[0]) || pt_text_width(name) <= PT_BOOK_BUDGET) {
        return name;
    }
    for (p = name; *p != 0 && *p != ' ' && n < 20; p++) {
        d[n++] = *p;
    }
    if (*p == ' ' && p[1] != 0) {
        d[n++] = ' ';
        d[n++] = p[1];
        d[n++] = '.';
    }
    d[n] = 0;
    return d;
}

void pt_telephone_choice_menu_init(void)
{
    s16 spBC[14];
    s16 spA0[14];
    s16 sp84[14];
    s16 sp68[14];
    s32 i;

    set_kanji_string(-128, -84, 3, &telephone_choice_menu_init_str0, 0);
    for (i = 0; i < 14; i++) {
        sp84[i] = 72;
        spBC[i] = (s16)(((i / 5) * 88) - 136);
        sp68[i] = 14;
        spA0[i] = (s16)(((i % 5) * 16) - 56);
        if (i == 0) {
            set_kanji_string(spBC[i], spA0[i], 3,
                             pt_book_name(i, (u8 *)telephone_choice_menu_init_tbl2), 0);
        } else if (i == 13) {
            spA0[i] += 16;
            set_kanji_string(spBC[i], spA0[i], 3, &telephone_choice_menu_init_str1, 0);
        } else if (i == 12) {
            set_kanji_string(spBC[i], spA0[i], 3,
                             pt_book_name(i, (u8 *)telephone_choice_menu_init_tbl1), 0);
        } else if ((*(u32 *)(screen_w + i * 56 + 400) << 28) >> 31) {
            set_kanji_string(spBC[i], spA0[i], 3,
                             pt_book_name(i, (u8 *)telephone_choice_menu_init_tbl0[i]), 0);
        } else {
            sp84[i] = 0;
        }
    }
    menu_set(0, 14, spBC, spA0, sp84, sp68);
    now_icon = 0;
    class_clear_n(96);
    cal_cw_prio = 0;
    cal_cw_mode = 64;
    cal_cw_attr = 0x40000000;
    cal_cw_disp = 132;
    cal_cw_img = (u32 *)&basyo_init_tbl1;
    cal_cw_anim_tbl = (u32 *)&basyo_init_tbl2;
    cal_cw_hdr = (u32 *)&_sys_default_tpage_set_tbl2;
    cal_cw_aux14 = basyo_init_tbl3;
    cal_cw_flag4 = 8;
    cal_cw_sel = 1;
    cal_cw_anim = 0;
    cal_cw_rate = 2;
    cal_cw_frame = 63;
    cal_cw_x = -16;
    cal_cw_y = -19;
}
