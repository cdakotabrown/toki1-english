#include "patch_text.h"

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern void k_disp_start(s32);
extern void k_reset(s32);
extern s32 check_end_k(void);
extern void sub_sub_step_up(void);
extern void goto_sub_step(s32);
extern void goto_sub_sub_step(s32);
extern void func_80044980(s32);
extern void func_80044AC0(s32, s32, s32, s32, s32, s32);
extern s32 device_load_poll(void);
extern s32 get_CD_State2(void);
extern void func_80046660(s32, s32, s32);
extern void func_80046840(void);
extern void set_dec_bri(s32);
extern void dec_bg_reset(void);
extern void indexed_byte_lsb_set(s32, s32);
extern void value_cache_find_or_load(s32, s32);
extern s32 dec_bg_init(s32);
extern void hizuke_init(void);
extern void message_window_init(void);
extern void bustup_ptr_init(void);
extern void fade_down_main(void);
extern void fade_in_step(void);
extern void fade_in(void);
extern void fade_out_step(void);
extern void fade_out(void);
extern void menu2_main(void);
extern void zyotai_sprite_set_chk(void);
extern void date_name_set(s32);
extern void yazirushi_off(void);
extern void serifu_run(void);
extern void func_80086050(s32, s32);
extern s32 get_g_zyotai_low(s32);
extern void func_80086828(s32);
extern void func_80142BC8(void);
extern void func_801431D4(void);
extern void func_80153FA4(void);

extern s16 now_serifu;
extern u8 ret_step;
extern u8 ret_sub_step;
extern u8 ret_sub_sub_step;
extern u8 now_girl;
extern s32 pad_trig;
extern u8 now_step;
extern u8 now_sub_step;
extern u8 now_sub_sub_step;
extern u8 step_mode;
extern u8 tt_result;
extern u8 bunkaken_flags;
extern u8 yazirushi_cw_disp;
extern s32 serifu_no;
extern s32 common_disp_off;
extern s32 bunka_ret_sub_step;
extern s32 bunka_ret_sub_sub_step;
extern s16 mes_base_y;
extern u8 D_8015F1D0[];
extern u8 D_80160AE0;
extern u8 p_sei[];

static void pt_bunkasai_bg_select(s32 base0, s32 base2, s32 base3, s32 base4)
{
    switch (get_g_zyotai_low(0)) {
    case 0:
    case 1:
        now_serifu = (s16)base0;
        break;
    case 2:
        now_serifu = (s16)base2;
        break;
    case 3:
        now_serifu = (s16)base3;
        break;
    case 4:
        now_serifu = (s16)base4;
        break;
    }
}

void pt_bunkasai_photo(void)
{
    s32 n;

    switch (now_sub_sub_step) {
    case 0:
        value_cache_find_or_load(16645, 1);
        sub_sub_step_up();
        break;
    case 1:
        fade_out_step();
        break;
    case 2:
        if (get_CD_State2() & 1) {
            indexed_byte_lsb_set(1, dec_bg_init(1));
            sub_sub_step_up();
        }
        break;
    case 3:
        func_80086828(21578);
        break;
    case 4:
        bustup_ptr_init();
        now_girl = 0;
        zyotai_sprite_set_chk();
        func_801431D4();
        func_80046660(24, (s32)0x801E8000, 18896);
        break;
    case 5:
        fade_in();
        break;
    case 6:
        if (get_CD_State2() & 1) {
            pt_bunkasai_bg_select(103, 108, 113, 118);
            func_80153FA4();
        }
        break;
    case 7:
    case 9:
    case 26:
    case 29:
        serifu_run();
        break;
    case 8:
        if (get_g_zyotai_low(0) == 4) {
            fade_down_main();
        } else {
            goto_sub_sub_step(11);
        }
        break;
    case 10:
        goto_sub_sub_step(16);
        break;
    case 11:
    case 13:
        menu2_main();
        break;
    case 12:
    case 14:
        if (serifu_no != 0) {
            serifu_run();
        } else {
            goto_sub_sub_step(16);
        }
        break;
    case 15:
        goto_sub_sub_step(27);
        break;
    case 16:
        if (get_g_zyotai_low(0) == 4) {
            sub_sub_step_up();
            break;
        }
        switch (step_mode) {
        case 0:
            k_reset(1);
            set_kanji_string((s16)(-90 - pt_text_width(p_sei)), 50, 0,
                             p_sei, 0);
            set_kanji_string(-86, 50, 0, D_8015F1D0, 0);
            k_disp_start(2);
            step_mode = (u8)(step_mode + 1);
            D_80160AE0 = 0;
            break;
        case 1:
            n = (u8)(D_80160AE0 + 1);
            D_80160AE0 = (u8)n;
            if ((u32)n >= 16 && check_end_k() != 0) {
                yazirushi_cw_disp ^= 0x80;
                D_80160AE0 = 0;
            }
            if ((pad_trig & 0xF0) != 0 && check_end_k() != 0) {
                k_reset(1);
                yazirushi_cw_disp &= 0x7F;
                step_mode = (u8)(step_mode + 1);
            }
            break;
        case 2:
            fade_down_main();
            break;
        }
        break;
    case 17:
        ret_step = now_step;
        ret_sub_step = now_sub_step;
        ret_sub_sub_step = (u8)(now_sub_sub_step + 1);
        bunkaken_flags = (u8)((bunkaken_flags | 3) & 0xFFE3);
        goto_sub_step(164);
        break;
    case 18:
        common_disp_off = 1;
        bunka_ret_sub_step = now_sub_step;
        bunka_ret_sub_sub_step = now_sub_sub_step + 1;
        goto_sub_step(163);
        break;
    case 19:
        func_80044980(191);
        func_80044AC0(1, 0xC486, 0xC459, 0xD266, 0xD216, 0xD20E);
        func_80086050(1, 0);
        func_801431D4();
        mes_base_y = 192;
        message_window_init();
        hizuke_init();
        yazirushi_off();
        date_name_set(0);
        common_disp_off = 0;
        sub_sub_step_up();
        break;
    case 20:
        if (device_load_poll() == 1) {
            func_80044980(512);
            dec_bg_reset();
            set_dec_bri(0);
            value_cache_find_or_load(16645, 1);
            sub_sub_step_up();
        }
        break;
    case 21:
        if (get_CD_State2() & 1) {
            indexed_byte_lsb_set(1, dec_bg_init(1));
            sub_sub_step_up();
        }
        break;
    case 22:
        func_80086828(21578);
        break;
    case 23:
        bustup_ptr_init();
        now_girl = 0;
        zyotai_sprite_set_chk();
        func_80046660(24, (s32)0x801E8000, 18896);
        break;
    case 24:
        if (get_g_zyotai_low(0) == 4) {
            fade_in_step();
        } else {
            fade_in();
        }
        break;
    case 25:
        if (get_CD_State2() & 1) {
            pt_bunkasai_bg_select(106, 111, 116, 178);
            if ((u32)tt_result < 2 && (u32)get_g_zyotai_low(0) < 4) {
                now_serifu = (s16)(now_serifu + 1);
            }
            func_80153FA4();
        }
        break;
    case 27:
        if (get_g_zyotai_low(0) == 4) {
            fade_out_step();
        } else {
            fade_out();
        }
        break;
    case 28:
        now_serifu = 1;
        sub_sub_step_up();
        break;
    case 30:
        func_80142BC8();
        break;
    default:
        func_80046840();
        break;
    }
}
