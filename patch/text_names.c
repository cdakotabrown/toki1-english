#include "patch_text.h"

extern u8 p_name[];
extern u8 pp_name[];
extern u8 p_name2[];
extern u8 g_name[];
extern u8 g_name2[];
extern u8 shu_name[];
extern u8 oname[];
extern u8 wname[];
extern u8 D_8012B604[];

#define PT_NAME_SLOTS 8
#define PT_NAME_LONG  40

static u8 *const pt_watch[PT_NAME_SLOTS] = {
    p_name, pp_name, p_name2, g_name, g_name2, shu_name, oname, wname
};
static const u8 pt_watch_size[PT_NAME_SLOTS] = { 8, 8, 12, 8, 12, 12, 8, 12 };
u8 patch_long_names[PT_NAME_SLOTS][PT_NAME_LONG];

u8 *pt_long_name(u32 slot)
{
    if (slot >= PT_NAME_SLOTS) {
        return (u8 *)"";
    }
    return patch_long_names[slot];
}

static s32 pt_slot_of(u8 *dst)
{
    s32 i;
    for (i = 0; i < PT_NAME_SLOTS; i++) {
        if (dst == pt_watch[i]) {
            return i;
        }
    }
    return -1;
}

static s32 pt_nlen(u8 *s)
{
    s32 n = 0;
    while (s[n] != 0) {
        n++;
    }
    return n;
}

static void pt_copy_resolved(u8 *dst, u8 *src, s32 cap)
{
    s32 n = 0;
    if (src[0] == PT_C_REF) {
        src = pt_long_name(src[1]);
    }
    while (src[n] != 0 && n < cap - 1) {
        dst[n] = src[n];
        n++;
    }
    dst[n] = 0;
}

static void pt_set_redirect(u8 *dst, s32 slot)
{
    dst[0] = PT_C_REF;
    dst[1] = (u8)slot;
    dst[2] = 0;
}

#define PT_COMPOSE_MAX 160
static u8 pt_compose_buf[PT_COMPOSE_MAX];

static u8 *pt_plain_src(u8 *src)
{
    u8 *t;
    s32 n = 0;

    if (src[0] != PT_C_STR) {
        return src;
    }
    t = pt_str(src[1] - PT_STR_BASE);
    while (*t != 0 && n < PT_COMPOSE_MAX - 1) {
        if (*t != PT_C_DST) {
            pt_compose_buf[n++] = *t;
        }
        t++;
    }
    pt_compose_buf[n] = 0;
    return pt_compose_buf;
}

static u8 *pt_splice(u8 *dst, u8 *tmpl)
{
    u8 *cur = dst;
    s32 n = 0;
    s32 k;

    if (cur[0] == PT_C_REF) {
        cur = pt_long_name(cur[1]);
    }
    for (; *tmpl != 0 && n < PT_COMPOSE_MAX - 1; tmpl++) {
        if (*tmpl != PT_C_DST) {
            pt_compose_buf[n++] = *tmpl;
            continue;
        }
        for (k = 0; cur[k] != 0 && n < PT_COMPOSE_MAX - 1; k++) {
            pt_compose_buf[n++] = cur[k];
        }
    }
    pt_compose_buf[n] = 0;
    return pt_compose_buf;
}

static s32 pt_has_splice(u8 *t)
{
    for (; *t != 0; t++) {
        if (*t == PT_C_DST) {
            return 1;
        }
    }
    return 0;
}

u8 *pt_strcpy(u8 *dst, u8 *src)
{
    s32 slot;
    s32 n;
    u8 *s;

    if (dst == 0 || src == 0) {
        return 0;
    }
    s = pt_plain_src(src);
    slot = pt_slot_of(dst);
    if (slot < 0) {

        n = 0;
        while ((dst[n] = s[n]) != 0) {
            n++;
        }
        return dst;
    }
    if (s[0] == PT_C_REF) {
        s = pt_long_name(s[1]);
    }
    n = pt_nlen(s);
    if (n < pt_watch_size[slot]) {
        pt_copy_resolved(dst, s, pt_watch_size[slot]);
        return dst;
    }
    pt_copy_resolved(patch_long_names[slot], s, PT_NAME_LONG);
    pt_set_redirect(dst, slot);
    return dst;
}

u8 *pt_strcat(u8 *dst, u8 *src)
{
    s32 slot;
    s32 n;
    s32 m;
    u8 *s = src;
    u8 *cur;
    u8 tmp[PT_NAME_LONG];

    if (dst == 0 || src == 0) {
        return 0;
    }
    if (src[0] == PT_C_STR) {
        if (pt_has_splice(pt_str(src[1] - PT_STR_BASE))) {

            return pt_strcpy(dst, pt_splice(dst, pt_str(src[1] - PT_STR_BASE)));
        }
        s = pt_plain_src(src);
    }
    slot = pt_slot_of(dst);
    if (slot < 0) {
        n = pt_nlen(dst);
        m = 0;
        while ((dst[n + m] = s[m]) != 0) {
            m++;
        }
        return dst;
    }
    if (s[0] == PT_C_REF) {
        s = pt_long_name(s[1]);
    }
    cur = (dst[0] == PT_C_REF) ? patch_long_names[slot] : dst;
    pt_copy_resolved(tmp, cur, PT_NAME_LONG);
    n = pt_nlen(tmp);
    m = 0;
    while (s[m] != 0 && n + m < PT_NAME_LONG - 1) {
        tmp[n + m] = s[m];
        m++;
    }
    tmp[n + m] = 0;
    if (n + m < pt_watch_size[slot]) {
        pt_copy_resolved(dst, tmp, pt_watch_size[slot]);
        return dst;
    }
    pt_copy_resolved(patch_long_names[slot], tmp, PT_NAME_LONG);
    pt_set_redirect(dst, slot);
    return dst;
}

u8 *pt_strncat(u8 *dst, u8 *src, s32 n)
{
    s32 d;
    s32 i;

    if (dst == 0 || src == 0) {
        return 0;
    }
    d = pt_nlen(dst);
    for (i = 0; i < n && src[i] != 0; i++) {
        if (dst == D_8012B604 && src[i] >= '0' && src[i] <= '9') {
            dst[d++] = 0x82;
            dst[d++] = (u8)(0x4F + (src[i] - '0'));
        } else {
            dst[d++] = src[i];
        }
    }
    dst[d] = 0;
    return dst;
}
