#include "types.h"

extern s16 check_end_k_tbl0;
extern u16 load_string_tbl0;
extern u16 load_string_tbl1[];
extern u16 load_string_tbl2;
extern u8 load_string_str0[];

extern void printf(u8 *);
extern void vload_font(s32, s32);

static s32 ascii_glyph(u32 c)
{
    if (c >= 'a' && c <= 'z') {
        return 144 + (c - 'a');
    }
    if (c >= 'A' && c <= 'Z') {
        return 118 + (c - 'A');
    }
    if (c >= '0' && c <= '9') {
        return 108 + (c - '0');
    }

    if (c == ' ') return 0;
    if (c == ',') return 3;
    if (c == '.') return 4;
    if (c == ':') return 6;
    if (c == ';') return 7;
    if (c == '?') return 8;
    if (c == '!') return 9;
    if (c == '\'') return 38;
    if (c == '"') return 40;
    if (c == '(') return 41;
    if (c == ')') return 42;
    if (c == '-') return 60;
    if (c == '&') return 85;
    if (c == '/') return 30;
    return 8;
}

s32 load_string(u8 *str)
{
    u16 *tbl_end = &load_string_tbl2;
    u8 *p = str;
    s32 saved = check_end_k_tbl0;
    u32 hi;
    u32 lo;
    u32 code;
    s32 diff;
    s32 i;

    for (;;) {
        hi = *p++;
        if (hi == 0) {
            break;
        }
        if (hi < 0x80) {

            vload_font(ascii_glyph(hi), 0);
            continue;
        }
        lo = *p++;
        if (lo == 0) {
            break;
        }
        code = lo + (hi << 8);
        if (code < load_string_tbl0) {
            printf(load_string_str0);
            break;
        }
        i = 0;
        do {
            if (code < load_string_tbl1[i]) {
                diff = (s32)code - (s32)load_string_tbl1[i - 2];
                vload_font((s32)load_string_tbl1[i - 1] + diff, diff);
                break;
            }
            i += 2;
        } while (tbl_end != &load_string_tbl1[i]);
    }
    return check_end_k_tbl0 - saved;
}
