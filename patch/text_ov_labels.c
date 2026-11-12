#include "patch_text.h"

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern s32 pt_schedule_analyze(s16, s16, u8, u8 *, s32, u8 *, u8 *, u8);
extern void k_reset(s32);
extern void k_disp_start(s32);
extern void k_disp_inc(void);
extern s32 check_end_k(void);
extern s32 get_CD_State(void);
extern void set_XAsector(u32, u32, u8);
extern void func_80044980(s32);
extern void sub_step_up(void);
extern void sub_sub_step_up(void);
extern void k_scroll_set(void);
extern void strcpy(u8 *, u8 *);
extern void strcat(u8 *, u8 *);

extern u8 p_name[];
extern u8 now_girl;
extern u8 now_sub_sub_step;
extern u8 step_mode;
extern u8 D_801436B8[];
extern u8 D_801436BC[];
extern u8 D_801436C0[];
extern u8 D_801436DC[];
extern u8 D_801436E0[];
extern u8 ***D_80143BB4;
extern u8 **D_80143BB8;
extern s16 D_80143BC0;
extern s16 D_80143BC4;
extern void func_801323D4(void);

void pt_shougatu_greeting(void)
{
    u8 b0 = D_801436B8[0];
    u8 b1 = D_801436B8[1];
    s32 saved;

    if (now_girl == 0) {
        sub_sub_step_up();
        return;
    }
    if (step_mode == 0) {
        set_kanji_string((s16)(-90 - pt_text_width(p_name)), 48, 0,
                         p_name, 0);
        set_kanji_string(-86, 48, 0, D_801436BC, 0);
        pt_schedule_analyze(-72, 48, 0, D_801436C0, 0, D_801436DC, D_801436E0, 0);
        D_80143BC0 = 0;
        D_80143BC4 = 0;
        **D_80143BB8 = 7;
        (**D_80143BB4)[0] = b0;
        (**D_80143BB4)[1] = b1;
        (**D_80143BB4)[2] = 0;
        step_mode = 1;
    }
    saved = now_sub_sub_step;
    func_801323D4();
    if (now_sub_sub_step != saved) {
        sub_step_up();
    }
}

extern s32 bunka_sd_kind;
extern u8 p_sei[];
extern u8 p_mei[];
extern u8 D_80139EF4[];
extern u8 D_80139EF8[];
extern u8 D_80139F04[];
extern u8 D_80139F10[];
extern u8 D_80139F1C[];
extern u8 D_80139F24[];
extern u8 D_80139F2C[];
extern u8 D_80139F34[];
extern u8 D_80139F3C[];
extern u8 D_80139F44[];
extern s32 D_8013B75C;
extern u8 **D_8013B760;
extern u32 *D_8013B764;
extern u8 step_mode;
extern s32 pad_data;
extern s32 step_counter;

void pt_bunka_sd_rollcall(void)
{
    s32 row;
    s32 charId;
    u8 *s;
    u32 *p;

    if (step_counter == 1) {
        k_reset(1);
        switch ((u32)bunka_sd_kind) {
        case 0:
            set_kanji_string((s16)(-90 - pt_text_width(p_sei)), 48, 0,
                             p_sei, 0);
            break;
        case 1:
            set_kanji_string(-128, 48, 0, D_80139F24, 0);
            break;
        case 2:
            set_kanji_string(-120, 48, 0, D_80139F2C, 0);
            break;
        case 3:
            set_kanji_string(-120, 48, 0, D_80139F34, 0);
            break;
        default:
            set_kanji_string(-128, 48, 0, D_80139F3C, 0);
            break;
        }
        set_kanji_string(-86, 48, 0, D_80139F44, 0);

        for (row = D_8013B75C; row < 100; row++) {
            s = D_8013B760[row];
            set_kanji_string(-72, (s16)((row - D_8013B75C) * 16 + 48), 0, s + 1, 0);
            charId = s[0];
            if (charId == 103 || charId == 69) {
                if ((pad_data & 0x20) == 0 && bunka_sd_kind != 0) {
                    p = &D_8013B764[step_mode];
                    set_XAsector(p[0], p[1], now_girl);
                    func_80044980(768);
                }
                if (charId == 103) {
                    step_mode = (u8)(step_mode + 2);
                } else {
                    step_mode = 255;
                }
                D_8013B75C = row + 1;
                break;
            }
        }
    }
    if (get_CD_State() == 2 && check_end_k() != 0) {
        if (step_mode == 255) {
            k_reset(1);
            sub_sub_step_up();
        }
        step_counter = 0;
    }
    k_scroll_set();
    k_disp_inc();
}

void pt_bunka_sd_announcer(void)
{
    u8 buf[64];

    if (step_counter == 1) {
        switch ((u32)bunka_sd_kind) {
        case 0:

            if (PT_IS_ASCII(p_sei[0]) && PT_IS_ASCII(p_mei[0])) {
                strcpy(buf, p_mei);
                strcat(buf, D_80139EF4);
                strcat(buf, p_sei);
            } else {
                strcpy(buf, p_sei);
                strcat(buf, D_80139EF4);
                strcat(buf, p_mei);
            }
            set_kanji_string((s16)(96 - pt_text_width(buf)), 64, 0, buf, 0);
            break;
        case 1:
            if ((pad_data & 0x20) == 0) {
                set_XAsector(0x0B00001B, 0x05000020, 14);
                func_80044980(768);
            }
            set_kanji_string(54, 64, 0, D_80139EF8, 0);
            break;
        case 2:
            if ((pad_data & 0x20) == 0) {
                set_XAsector(0x1D00005B, 0x0B000061, 0);
                func_80044980(768);
            }
            set_kanji_string(40, 64, 0, D_80139F04, 0);
            break;
        case 3:
            set_kanji_string(40, 64, 0, D_80139F10, 0);
            break;
        default:
            set_kanji_string(68, 64, 0, D_80139F1C, 0);
            break;
        }
    } else if (get_CD_State() == 2 && check_end_k() != 0) {
        sub_sub_step_up();
    }
    k_scroll_set();
    k_disp_inc();
}

extern u8 D_8013CC78[];

void pt_ending_song(s16 idx)
{
    u8 *s = &D_8013CC78[idx * 25];

    k_disp_start(set_kanji_string((s16)(-pt_text_width(s) / 2), 80, 0, s, 0));
}
