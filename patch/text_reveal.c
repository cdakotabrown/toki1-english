#include "patch_text.h"

extern s32 frame_counter;
extern u8 get_k_speed_tbl0;
extern s16 check_end_k_tbl0;
extern s16 check_end_k_tbl1;
extern u16 patch_glyph_x[PT_MAX_CELLS];

s32 pt_k_disp_inc(void)
{
    s32 delay = (s32)get_k_speed_tbl0 + 1;
    s32 cell = check_end_k_tbl1;

    if (cell >= 0 && cell < check_end_k_tbl0 && cell < PT_MAX_CELLS &&
        (patch_glyph_x[cell] & 0x8000)) {
        delay = (delay + 1) / 3;
        if (delay < 1) {
            delay = 1;
        }
    }
    if ((u32)frame_counter % (u32)delay == 0) {
        if (check_end_k_tbl1 < check_end_k_tbl0) {
            check_end_k_tbl1++;
            return 0;
        }
        return 1;
    }
    return check_end_k_tbl1 == check_end_k_tbl0;
}
