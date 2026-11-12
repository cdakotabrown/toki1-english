#include "dbg.h"

extern u8 D_800EE855;
extern u8 basyo_flag0[];
extern u8 D_800EE91C[];
extern u8 D_800EEC9C[];
extern u8 D_800F0204[];

#define STAT_COUNT   9
#define REC_STRIDE   56
#define REC_COUNT    13
#define TOKIMEKI     0x02
#define YUUKOU       0x06
#define SYOUSHIN     0x0A
#define FLAGS        0x0C
#define FLAGS2       0x0E

void dbg_unlock_all(void)
{
    s32 i;
    u8 *rec;

    for (i = 0; i < STAT_COUNT - 1; i++) {
        *(s16 *)((u8 *)&D_800EE85E + i * 4) = 999;
    }
    *(s16 *)((u8 *)&D_800EE85E + (STAT_COUNT - 1) * 4) = 0;
    D_800EE855 &= 0xF0;
    for (i = 0; i < 21; i++) {
        basyo_flag0[i] = 1;
    }
    for (i = 0; i < REC_COUNT; i++) {
        rec = D_800EE91C + i * REC_STRIDE;
        *(s16 *)(rec + TOKIMEKI) = 127;
        *(s16 *)(rec + YUUKOU) = 127;
        *(s16 *)(rec + SYOUSHIN) = 0;
        if (i != 11) {
            rec[FLAGS] |= 0xCE;
        }
        rec[FLAGS2] &= 0xFC;
    }
    for (i = 0; i < REC_COUNT; i++) {
        D_800EEC9C[i] = 2;
        D_800F0204[i] = 1;
    }
}
