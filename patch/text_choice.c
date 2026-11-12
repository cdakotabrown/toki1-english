#include "patch_text.h"

extern void menu_set(s32, s32, s16 *, s16 *, s16 *, s16 *);
extern u8 menu_csr;
extern s32 menu_on;
extern s32 step_counter;
extern s16 patch_choice_y[4];
extern u8 patch_choice_rows[4];
extern u8 patch_choice_count;
extern u8 patch_choice_pitch;

static void pt_choice_menu(s32 count)
{
    s16 xs[4];
    s16 ys[4];
    s16 ws[4];
    s16 hs[4];
    s32 i;

    for (i = 0; i < count; i++) {
        xs[i] = -128;
        ws[i] = 252;
        if (patch_choice_count == count && patch_choice_rows[i] != 0) {
            ys[i] = patch_choice_y[i];
            hs[i] = (s16)(patch_choice_rows[i] * patch_choice_pitch);
        } else {
            ys[i] = (s16)(48 + 16 * i);
            hs[i] = 16;
        }
    }
    menu_set(1, count, xs, ys, ws, hs);
    menu_csr = 0;
    menu_on = 1;
    step_counter++;
}

void pt_menu2_init(void)
{
    pt_choice_menu(2);
}

void pt_menu3_init(void)
{
    pt_choice_menu(3);
}
