#include "patch_text.h"

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern void text_sys_init(void);
extern void func_801366FC(s32);
extern s32 strlen(u8 *);
extern void strncpy(u8 *, u8 *, s32);
extern void strncat(u8 *, u8 *, s32);
extern void printf(u8 *, ...);

extern u8 patch_fixed_cell;

extern u8 D_8014CC70;
extern u8 D_8014CC74[];
extern u8 D_8014CC7C[];
extern u8 D_8014CC84[];
extern s32 D_8014CCAC;
extern s32 D_8014CCB4;
extern s32 D_8014CCC0;
extern s32 D_8014CCC4;
extern s32 D_8014CCC8;
extern u8 *D_8014CD6C[];
extern u8 *D_8014CDB0[];
extern u16 *D_8014CE64;
extern u8 **D_8014CE68;
extern u8 space_str[];
extern s32 pad_trig;
extern s16 D_801271D6;
extern s16 D_801271DA;

typedef struct {
    u8 pad0[2];
    u8 f2;
    u8 pad3[21];
    s16 f24;
    u8 pad26[42];
} PtRec68;
extern PtRec68 class_w[];

extern u8 screen_w[];
extern u8 p_sei[];
extern u8 p_mei[];
extern u8 p_adana[];
extern u8 D_800EE824[];
extern u8 D_8014B530[];
extern u8 D_8014B53C[];
extern u8 D_8014B548[];
extern u8 D_8014B554[];
extern u8 D_8014CC90;
extern u8 D_8014CC94;
extern u8 D_8014CC98;
extern u8 D_8014CC9C;
extern u8 D_8014CCA0;
extern u8 D_8014CCA4;
extern u8 D_800EE858;
extern u8 D_800EE92C;

#define PT_FIELDS 3
static const u8 pt_field_max[PT_FIELDS] = { 7, 7, 15 };
static const u8 pt_field_first[PT_FIELDS] = { 0, 3, 6 };

static const u8 pt_latin_keys[17][6] = {
    "ABCDE", "FGHIJ", "KLMNO",
    "PQRST", "UVWXY", "Z.-' ",
    "abcde", "fghij", "klmno",
    "pqrst", "uvwxy", "z,!?:",
    "01234", "56789", "&+=/*",
    "()[]@", "#<>~^",
};

static u8 *pt_field_buf(s32 field)
{
    if (field == 0) return D_8014CC74;
    if (field == 1) return D_8014CC7C;
    return D_8014CC84;
}

static s32 pt_field_of(s32 idx)
{
    if (idx < 3) return 0;
    if (idx < 6) return 1;
    if (idx < 11) return 2;
    return -1;
}

static s32 pt_field_is_ascii(u8 *b)
{
    return PT_IS_ASCII(b[0]);
}

static void pt_field_blank(u8 *b, s32 pairs, s32 size)
{
    s32 i;

    for (i = 0; i < size; i++) {
        b[i] = 0;
    }
    for (i = 0; i < pairs; i++) {
        b[i * 2] = space_str[0];
        b[i * 2 + 1] = space_str[1];
    }
}

void pt_name_page_latin(u8 *title)
{
    s32 blk;
    s32 row;
    s32 col;

    text_sys_init();
    set_kanji_string(-152, -104, 0, title, 0);
    patch_fixed_cell = 1;
    for (blk = 0; blk < 17; blk++) {
        row = blk / 3;
        col = blk % 3;
        set_kanji_string((s16)(-120 + col * 96), (s16)(-48 + row * 16), 10,
                         (u8 *)pt_latin_keys[blk], 0);
    }
    patch_fixed_cell = 0;
}

extern s32 D_8014CCCC;
extern s32 D_8014CCD0[];

static s32 pt_in_band(s32 top, s32 y)
{
    return top < y && y < top + 16;
}

void pt_name_band(void)
{
    s32 y = D_801271DA;
    s32 band = -1;

    if (D_801271D6 >= -157 && D_801271D6 < -128) {
        if (pt_in_band(D_8014CCD0[0], y)) band = 0;
        if (pt_in_band(D_8014CCD0[1], y)) band = 1;
        if (pt_in_band(D_8014CCD0[2], y)) band = 2;

        if (pt_in_band(D_8014CCD0[4], y)) band = 4;
    }
    D_8014CCCC = band;
}

static void pt_pair_key(u8 *base, s32 a1, u8 *pair)
{
    base[a1 * 2] = pair[0];
    base[a1 * 2 + 1] = pair[1];
}

static void pt_retail_key(s32 sel, u8 *base, s32 a1)
{
    s32 col = D_8014CCC0;
    s32 row = D_8014CCC4;
    s32 idx;
    u8 *src;

    switch (D_8014CCC8) {
    case 1:
        if (col % 6 == 5 || (row == 2 && (col == 9 || col == 10)) ||
            (row == 3 && (col == 3 || col == 4)) || (row == 5 && col >= 11)) {
            pt_pair_key(base, a1, space_str);
        } else {
            src = D_8014CD6C[col / 6 + row * 3] + (col % 6) * 2;
            pt_pair_key(base, a1, src);
        }
        break;
    case 2:
        if (col >= 16) return;
        idx = row * 16 + D_8014CCAC * 16 + col;
        if (idx < D_8014CE64[38]) {
            pt_pair_key(base, a1, D_8014CE68[38] + idx * 2);
        } else {
            pt_pair_key(base, a1, space_str);
        }
        break;
    case 3:
        if (col >= 16) return;
        if (D_8014CCB4 == 38) {
            idx = row * 16 + D_8014CCAC * 16 + col;
            if (idx < D_8014CE64[D_8014CCB4]) {
                pt_pair_key(base, a1, D_8014CE68[D_8014CCB4] + idx * 2);
            } else {
                pt_pair_key(base, a1, space_str);
            }
        } else if (row == 0) {
            if (col < strlen(D_8014CDB0[D_8014CCB4]) / 2) {
                pt_pair_key(base, a1, D_8014CDB0[D_8014CCB4] + col * 2);
            } else {
                pt_pair_key(base, a1, space_str);
            }
        } else {
            idx = row * 16 + D_8014CCAC * 16 + col - 16;
            if (idx < D_8014CE64[D_8014CCB4]) {
                pt_pair_key(base, a1, D_8014CE68[D_8014CCB4] + idx * 2);
            } else {
                pt_pair_key(base, a1, space_str);
            }
        }
        break;
    default:
        return;
    }
    (void)sel;
}

void pt_name_key(s32 sel)
{
    u8 *base = pt_field_buf(sel);
    s32 a1 = D_8014CC70 - pt_field_first[sel];
    s32 cells = (sel == 2) ? 5 : 3;
    s32 col = D_8014CCC0;
    s32 row = D_8014CCC4;
    s32 blk;
    u32 key;
    s32 n;

    if (a1 < 0) {
        a1 = 0;
    }
    if (a1 >= cells) {
        a1 = cells - 1;
    }
    if (D_8014CCC8 == 0) {
        if (col < 0 || row < 0 || col % 6 == 5) {
            return;
        }
        blk = col / 6 + row * 3;
        if (blk >= 17) {
            return;
        }
        key = pt_latin_keys[blk][col % 6];
        if (key == 0) {
            return;
        }
        if (!pt_field_is_ascii(base)) {

            for (n = 0; n < (sel == 2 ? 12 : 8); n++) {
                base[n] = 0;
            }
        }
        n = strlen(base);
        if (n < pt_field_max[sel]) {
            base[n] = (u8)key;
            base[n + 1] = 0;

            if (pt_text_width(base) > cells * 16) {
                base[n] = 0;
            }
        }
        D_8014CC70++;
        return;
    }
    if (pt_field_is_ascii(base)) {

        pt_field_blank(base, cells, sel == 2 ? 12 : 8);
        a1 = 0;
    }
    pt_retail_key(sel, base, a1);
    D_8014CC70++;
}

void pt_name_cursor(s32 mode)
{
    s32 i;
    s32 field;
    u8 *b;
    s32 n;

    if (mode == 0 && D_8014CC70 >= 3) {
        D_8014CC70 = 12;
    }
    if (mode == 1 && D_8014CC70 >= 6) {
        D_8014CC70 = 12;
    }
    if (mode == 2 && D_8014CC70 >= 11) {
        D_8014CC70 = 12;
    }
    if (pad_trig & 0x20) {
        if (mode == 0) {
            for (i = 0; i < 3; i++) {
                if (D_801271D6 < i * 16 - 88 && i * 16 - 104 < D_801271D6 &&
                    D_801271DA < -70 && D_801271DA >= -85) {
                    D_8014CC70 = (u8)i;
                }
            }
        } else if (mode == 1) {
            for (i = 0; i < 3; i++) {
                if (D_801271D6 < i * 16 - 32 && i * 16 - 48 < D_801271D6 &&
                    D_801271DA < -70 && D_801271DA >= -85) {
                    D_8014CC70 = (u8)(i + 3);
                }
            }
        } else if (mode == 2) {
            for (i = 0; i < 5; i++) {
                if (D_801271D6 < i * 16 + 88 && i * 16 < D_801271D6 - 72 &&
                    D_801271DA < -70 && D_801271DA >= -85) {
                    D_8014CC70 = (u8)(i + 6);
                }
            }
        }
    }

    field = pt_field_of(D_8014CC70);
    if (field == mode) {
        b = pt_field_buf(field);
        if (pt_field_is_ascii(b)) {
            D_8014CC70 = pt_field_first[field];
            if (pad_trig & 0x40) {
                n = strlen(b);
                if (n > 0) {
                    b[n - 1] = 0;
                }
                if (b[0] == 0) {
                    pt_field_blank(b, field == 2 ? 5 : 3, field == 2 ? 12 : 8);
                }
            }
        }
    }
    for (i = 0; i < 11; i++) {
        if (i == D_8014CC70) {
            if (class_w[i + 98].f24 == 13) {
                class_w[i + 98].f24 = 0;
            }
            func_801366FC(i + 98);
        } else {
            class_w[i + 98].f2 = 64;
            class_w[i + 98].f24 = 13;
        }
    }
}

static void pt_commit_field(u8 *dst, u8 *src, s32 pairs, s32 maxascii)
{
    s32 n = 0;
    s32 k;
    u8 c0;

    if (pt_field_is_ascii(src)) {
        while (src[n] != 0 && n < maxascii) {
            dst[n] = src[n];
            n++;
        }
        dst[n] = 0;
        return;
    }
    for (k = 0; k < pairs; k++) {
        c0 = src[k * 2];
        if (c0 == space_str[0] && src[k * 2 + 1] == space_str[1]) {
            continue;
        }
        if (c0 == 0 && src[k * 2 + 1] == 0) {
            continue;
        }
        dst[n * 2] = c0;
        dst[n * 2 + 1] = src[k * 2 + 1];
        n++;
    }
}

void pt_name_commit(void)
{
    u8 buf[16];
    s32 i;

    for (i = 0; i < 8; i++) {
        screen_w[212 + i] = 0;
        screen_w[220 + i] = 0;
    }
    for (i = 0; i < 16; i++) {
        screen_w[228 + i] = 0;
    }
    pt_commit_field(screen_w + 212, D_8014CC74, 3, 7);
    pt_commit_field(screen_w + 220, D_8014CC7C, 3, 7);
    pt_commit_field(screen_w + 228, D_8014CC84, 5, 15);

    if (PT_IS_ASCII(p_sei[0]) && PT_IS_ASCII(p_mei[0])) {

        strncpy(buf, p_mei, 8);
        strncat(buf, (u8 *)" ", 1);
        strncat(buf, p_sei, (s32)(15 - strlen(buf)));
    } else {
        strncpy(buf, p_sei, 8);
        strncat(buf, p_mei, (s32)(15 - strlen(buf)));
    }
    strncpy(D_800EE824, buf, 16);

    printf(D_8014B530, p_sei);
    printf(D_8014B53C, p_mei);
    printf(D_8014B548, p_adana);
    printf(D_8014B554, D_800EE824);

    D_800EE858 = (u8)(((D_8014CC90 + 1) & 0xF) | (D_800EE858 & 0xF0));
    *(u16 *)(screen_w + 248) = (u16)((((D_8014CC94 + 1) << 4) & 0x1F0)
                               | (*(u16 *)(screen_w + 248) & 0xFE0F));
    screen_w[249] = (u8)((((D_8014CC98 + 1) << 1) & 0x6)
                     | (screen_w[249] & 0xF9));
    D_800EE92C = (u8)(((D_8014CC9C + 1) & 0xF) | (D_800EE92C & 0xF0));
    *(u16 *)(screen_w + 460) = (u16)((((D_8014CCA0 + 1) << 4) & 0x1F0)
                               | (*(u16 *)(screen_w + 460) & 0xFE0F));
    screen_w[461] = (u8)((((D_8014CCA4 + 1) << 1) & 0x6)
                     | (screen_w[461] & 0xF9));
}
