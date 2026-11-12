#include "patch_text.h"

#define PT_LOG_N     64
#define PT_LOG_TEXT  20

typedef struct {
    u16 seq;
    u8 scene;
    u8 step;
    s16 x;
    s16 y;
    u32 ptr;
    u8 flags;
    u8 sub;
    u8 text[PT_LOG_TEXT + 2];
} PtLogEntry;

typedef struct {
    u32 magic;
    u32 head;
    u32 n_japanese;
    u32 n_english;
    u32 n_entries;
    PtLogEntry e[PT_LOG_N];
    u16 scene_en[256];
    u16 scene_jp[256];
} PtLog;

extern u8 D_800EF86E;
extern u8 now_step;
extern u8 now_sub_step;

PtLog pt_draw_log_ring;
static u16 pt_log_seq;

static s32 pt_has_sjis(u8 *s)
{
    u32 b;

    while ((b = *s) != 0) {
        if (PT_IS_SJIS_LEAD(b) && s[1] != 0) {
            return 1;
        }
        s++;
    }
    return 0;
}

void pt_draw_log(s16 x, s16 y, u8 *str)
{
    PtLog *L = &pt_draw_log_ring;
    PtLogEntry *e;
    PtLogEntry *prev;
    s32 i;

    L->magic = 0x33474C44;
    L->n_entries = PT_LOG_N;
    pt_log_seq++;
    if (!pt_has_sjis(str)) {
        L->n_english++;
        if (L->scene_en[now_step] != 0xFFFF) {
            L->scene_en[now_step]++;
        }
        return;
    }
    if (L->scene_jp[now_step] != 0xFFFF) {
        L->scene_jp[now_step]++;
    }

    for (i = 0; i < PT_LOG_N; i++) {
        prev = &L->e[i];
        if (prev->ptr == (u32)str && prev->text[0] == str[0] && prev->text[1] == str[1] &&
            prev->text[2] == str[2] && prev->text[3] == str[3]) {
            return;
        }
    }
    L->n_japanese++;
    e = &L->e[L->head % PT_LOG_N];
    e->seq = pt_log_seq;
    e->scene = D_800EF86E;
    e->step = now_step;
    e->sub = now_sub_step;
    e->x = x;
    e->y = y;
    e->ptr = (u32)str;
    e->flags = (u8)(pt_is_packed(str) ? 1 : 0);
    for (i = 0; i < PT_LOG_TEXT && str[i] != 0; i++) {
        e->text[i] = str[i];
    }
    for (; i < PT_LOG_TEXT + 2; i++) {
        e->text[i] = 0;
    }
    L->head = (L->head + 1) % PT_LOG_N;
}
