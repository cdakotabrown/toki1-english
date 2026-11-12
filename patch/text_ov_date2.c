#include "patch_text.h"

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern void k_disp_start(s32);
extern void strcpy(u8 *, u8 *);

extern u8 D_8013B5A4;
extern u8 **D_8013B5B4;
extern u8 **D_8013B5B8;
extern u8 **D_8013B5BC;
extern u8 **D_8013B5C0;

static u8 pt_karaoke_buf[81][31];

static s32 pt_karaoke_row(s32 first, s32 lit, s16 x0, s16 y)
{
    s32 x = x0;
    s32 k;
    s32 r = 0;

    for (k = 0; k < 3; k++) {
        u8 *s = pt_karaoke_buf[first + k];
        r = set_kanji_string((s16)x, y, (first + k) <= lit ? 2 : 0, s, 0);
        x += pt_text_width(s);

        if (k < 2 && s[0] != 0 && pt_karaoke_buf[first + k + 1][0] != 0 &&
            pt_is_packed(s) && pt_is_packed(pt_karaoke_buf[first + k + 1])) {
            x += pt_char_width(' ', 0);
        }
    }
    return r;
}

void pt_date2_lyrics(s16 n)
{
    s16 i;
    s32 page;
    s32 r;

    switch (D_8013B5A4) {
    case 2:
        for (i = 0; i < 30; i++) {
            strcpy(pt_karaoke_buf[i], D_8013B5B4[i]);
        }
        break;
    case 0:
        for (i = 0; i < 51; i++) {
            strcpy(pt_karaoke_buf[i], D_8013B5B8[i]);
        }
        break;
    case 3:
        for (i = 0; i < 39; i++) {
            strcpy(pt_karaoke_buf[i], D_8013B5BC[i]);
        }
        break;
    default:
        for (i = 0; i < 81; i++) {
            strcpy(pt_karaoke_buf[i], D_8013B5C0[i]);
        }
        break;
    }

    page = n - (n % 6);
    pt_karaoke_row((n % 6) < 3 ? page : page + 6, n, -116, 54);
    r = pt_karaoke_row(page + 3, n, -84, 74);
    k_disp_start(r);
}

typedef struct {
    s32 w[21];
} PtDate2Blk;

extern PtDate2Blk D_8013B614;
extern s16 D_8013B5C4[4];
extern u8 D_8013B5AC;
extern u8 D_800F0214;
extern u8 now_icon;
extern u8 step_mode;
extern s32 menu_on;
extern u8 D_8013A2FC[];
extern u8 D_8013A310[];
extern void k_reset(s32);
extern void menu_set(s32, s32, s16 *, s16 *, s16 *, s16 *);

static s16 pt_song_box(u8 *s)
{
    return (s16)(*s == 0 ? 0 : pt_text_width(s) + 2);
}

void pt_date2_song_menu(void)
{
    PtDate2Blk buf;
    s16 xs[4];
    s16 ys[4];
    s16 hs[4];
    u8 *p;
    s16 i;

    buf = D_8013B614;
    p = (u8 *)&buf;
    xs[0] = -128; ys[0] = 52;
    xs[1] = 0;    ys[1] = 52;
    xs[2] = -128; ys[2] = 76;
    xs[3] = -32;  ys[3] = 76;
    D_8013B5C4[1] = pt_song_box(p + 21);
    hs[0] = hs[1] = hs[2] = hs[3] = 16;
    D_8013B5C4[0] = 0;
    D_8013B5C4[2] = 0;
    D_8013B5C4[3] = 0;
    k_reset(1);
    if ((D_800F0214 & 1) || D_8013B5AC != 0) {
        if (D_8013B5AC >= 2U) {
            strcpy(p, D_8013A2FC);
        }
        D_8013B5C4[0] = pt_song_box(p);
        k_disp_start(set_kanji_string(xs[0], ys[0], 0, p, 0));
    }
    k_disp_start(set_kanji_string(xs[1], ys[1], 0, p + 21, 0));
    if ((D_800F0214 & 4) || D_8013B5AC != 0) {
        D_8013B5C4[2] = pt_song_box(p + 42);
        k_disp_start(set_kanji_string(xs[2], ys[2], 0, p + 42, 0));
    }
    if ((D_800F0214 & 8) || D_8013B5AC != 0) {
        if (D_8013B5AC >= 2U) {
            strcpy(p + 63, D_8013A310);
        }
        D_8013B5C4[3] = pt_song_box(p + 63);
        k_disp_start(set_kanji_string(xs[3], ys[3], 0, p + 63, 0));
    }
    menu_set(0, 4, xs, ys, D_8013B5C4, hs);
    menu_on = 1;
    for (i = 0; i < 4; i++) {
        if (D_8013B5C4[i] != 0) {
            now_icon = (u8)i;
            break;
        }
    }
    step_mode++;
}
