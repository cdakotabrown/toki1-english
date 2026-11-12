#include "patch_text.h"

extern PtEntry disp_string_tbl0[];
extern u8 disp_string_tbl1;
extern s16 disp_string_state;
extern s16 check_end_k_tbl0;
extern s16 check_end_k_tbl1;
extern u8 k_cell_w;
extern s32 activeBuff;
extern u8 screen_w[];
extern u8 screen_bri;
extern u8 ot_buff0[];
extern u16 patch_glyph_x[PT_MAX_CELLS];

extern u8 *prim_alloc(s32, s32);
extern void SetSprt16(u8 *);
extern void SetSemiTrans(u8 *, s32);
extern void SetShadeTex(u8 *, s32);
extern u16 GetClut(s32, s32);
extern void AddPrim(u8 *, u8 *);
extern void goto_tpage(s32, s32, s32, s32, s32);

void disp_string(void)
{
    PtEntry *r;
    u8 *p;
    s32 pal;
    s32 i;
    s32 col;
    s32 first;
    s32 palOff;
    s32 u;
    s32 v;
    s32 adv;
    s32 sx;
    s32 sy;
    u32 tp;

    pal = disp_string_tbl1;
    if (pal == 0) {
        pal = 1;
    }
    first = 1;
    i = 0;
    col = 0;
    if (check_end_k_tbl0 > 0 && check_end_k_tbl1 > 0) {
        r = &disp_string_tbl0[0];
        do {

            while (!((u32)col < r->count)) {
                col = 0;
                r++;
                if (r - disp_string_tbl0 >= disp_string_state ||
                    r - disp_string_tbl0 >= PT_MAX_ENTRIES) {
                    goto done;
                }
            }
            if (r->flag == 1) {
                if (pal != r->ot) {
                    pal = r->ot;
                    first = 1;
                    if (pal == 0) {
                        pal = 1;
                    }
                }
                adv = patch_entry_adv[r - disp_string_tbl0];
                if (adv == 0) {
                    adv = k_cell_w;
                }
                sx = *(s16 *)(screen_w + 20 + activeBuff * 2) + r->x +
                     (adv == 0xFF ? (patch_glyph_x[i] & 0x7FFF) : col * adv);
                sy = *(s16 *)(screen_w + 24 + activeBuff * 2) + r->y;
                u = ((i & 7) << 4) + 128;
                v = (i & 0x78) << 1;
                tp = r->tp;
                palOff = pal << 2;

                p = prim_alloc(16, activeBuff);
                SetSprt16(p);
                SetSemiTrans(p, 0);
                SetShadeTex(p, 0);
                p[4] = screen_bri;
                p[5] = screen_bri;
                p[6] = screen_bri;
                *(s16 *)(p + 8) = (s16)sx;
                *(s16 *)(p + 10) = (s16)sy;
                p[12] = (u8)u;
                p[13] = (u8)v;
                *(u16 *)(p + 14) = GetClut(((tp & 8) << 2) + 256, (tp & 7) + 504);
                AddPrim(ot_buff0 + (activeBuff << 10) + palOff, p);

                p = prim_alloc(16, activeBuff);
                SetSprt16(p);
                SetSemiTrans(p, 0);
                SetShadeTex(p, 0);
                p[4] = 0;
                p[5] = 0;
                p[6] = 0;
                *(s16 *)(p + 8) = (s16)(sx + 1);
                *(s16 *)(p + 10) = (s16)(sy + 1);
                p[12] = (u8)u;
                p[13] = (u8)v;
                *(u16 *)(p + 14) = GetClut(((tp & 8) << 2) + 272, (tp & 7) + 504);
                AddPrim(ot_buff0 + (activeBuff << 10) + palOff, p);

                if (i == 127) {
                    goto_tpage(768, 256, pal, 0, 0);
                    first = 0;
                } else if (i == 255) {
                    goto_tpage(832, 256, pal, 0, 0);
                    first = 0;
                } else if (first != 0) {
                    first = 0;
                    if (i >= 256) {
                        goto_tpage(896, 256, pal, 0, 0);
                    } else if (i >= 128) {
                        goto_tpage(832, 256, pal, 0, 0);
                    } else {
                        goto_tpage(768, 256, pal, 0, 0);
                    }
                }
            }
            i++;
            col++;
        } while (i < check_end_k_tbl0 && i < check_end_k_tbl1);
    }
done:
    if (i >= 256) {
        goto_tpage(896, 256, pal, 0, 0);
    } else if (i >= 128) {
        goto_tpage(832, 256, pal, 0, 0);
    } else {
        goto_tpage(768, 256, pal, 0, 0);
    }
}
