#include "patch_text.h"

extern u8 msg_str_disp_str0[];
extern u8 msg_str_disp_str5[];
extern u8 msg_str_disp_str6[];
extern u8 p_name[];
extern u8 pp_name[];
extern u8 p_name2[];
extern u8 g_name2[];
extern u8 shu_name[];
extern u8 oname[];
extern u8 wname[];
extern u8 aname[];
extern u8 mname[];
extern s16 last_x_y;
extern s32 mugon_flag;
extern u8 junban[3];

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern s32 strlen(u8 *);

#define PT_LINE_MAX     256
#define PT_WIN_RIGHT    129
#define PT_LINE_PITCH   16

#define PT_C_NOP 0x1E

static s32 pt_legacy_letter(u32 b)
{
    switch (b) {
    case ' ': return PT_C_NEWLINE;
    case 'q': return PT_C_BREAK;
    case 'P': return PT_C_PNAME;
    case 'G': return PT_C_GNAME;
    case 'p': return PT_C_PFAMILY;
    case 'm': return PT_C_PGIVEN;
    case 'F': return PT_C_PFULL;
    case 'Y': return PT_C_YOSHIO;
    case 'S': return PT_C_TOK_S;
    case 'O': return PT_C_TOK_O;
    case 'W': return PT_C_TOK_W;
    case 'A': return PT_C_TOK_A;
    case 'M': return PT_C_TOK_M;
    }
    return 0;
}

s32 pt_is_legacy(u8 *s)
{
    u32 b;
    s32 pairs = 0;

    while ((b = *s) != 0) {
        if (b < 0x20) {
            return 0;
        }
        if (PT_IS_SJIS_LEAD(b)) {
            if (s[1] == 0) {
                return 0;
            }
            pairs++;
            s += 2;
            continue;
        }
        if (b >= 0x80 || pt_legacy_letter(b) == 0) {
            return 0;
        }
        s++;
    }
    return pairs > 0;
}

void pt_legacy_letters(u8 *s)
{
    u32 b;
    s32 c;

    while ((b = *s) != 0) {
        if (PT_IS_SJIS_LEAD(b) && s[1] != 0) {
            s += 2;
            continue;
        }
        c = pt_legacy_letter(b);
        if (c != 0) {
            *s = (u8)c;
        }
        s++;
    }
}

s32 pt_legacy_to_patch(u8 *s)
{
    if (!pt_is_legacy(s)) {
        return 0;
    }
    pt_legacy_letters(s);
    return 1;
}

static s32 pt_append(u8 *dst, s32 n, u8 *src)
{
    while (*src != 0 && n < PT_LINE_MAX - 1) {
        dst[n++] = *src++;
    }
    dst[n] = 0;
    return n;
}

static u8 *pt_token_string(u32 ctrl)
{
    switch (ctrl) {
    case PT_C_PNAME:   return p_name2;
    case PT_C_TOK_S:   return shu_name;
    case PT_C_GNAME:   return g_name2;
    case PT_C_PFAMILY: return p_name;
    case PT_C_YOSHIO:  return msg_str_disp_str6;
    case PT_C_PGIVEN:  return pp_name;
    case PT_C_TOK_O:   return oname;
    case PT_C_TOK_W:   return wname;
    case PT_C_TOK_A:   return aname;
    case PT_C_TOK_M:   return mname;
    default:           return 0;
    }
}

static s32 pt_expand_line(u8 *dst, u8 *src, u8 *end)
{
    s32 n = 0;
    u32 b;
    u8 *t;

    dst[0] = 0;
    while (src < end && (b = *src) != 0) {
        if (b == PT_C_REF) {
            n = pt_append(dst, n, pt_long_name(src[1]));
            src += 2;
            continue;
        }
        if (b == PT_C_STR && src[1] != 0) {

            t = pt_str(src[1] - PT_STR_BASE);
            while (*t != 0 && n < PT_LINE_MAX - 1) {
                if (*t != PT_C_DST) {
                    dst[n++] = *t;
                }
                t++;
            }
            dst[n] = 0;
            src += 2;
            continue;
        }
        if (PT_IS_CTRL(b)) {
            if (b == PT_C_PFULL) {
                n = pt_append(dst, n, pp_name);
                if (n < PT_LINE_MAX - 1) {
                    dst[n++] = ' ';
                    dst[n] = 0;
                }
                n = pt_append(dst, n, p_name);
            } else {
                t = pt_token_string(b);
                if (t != 0) {
                    n = pt_append(dst, n, t);
                }
            }
            src++;
            continue;
        }
        if (PT_IS_DTE(b)) {

            t = patch_dte_table[PT_DTE_INDEX(b)];
            if (t != 0) {
                n = pt_append(dst, n, t);
            }
            src++;
            continue;
        }
        if (PT_IS_SJIS_LEAD(b)) {
            if (src[1] == 0 || n >= PT_LINE_MAX - 2) {
                break;
            }
            dst[n++] = b;
            dst[n++] = src[1];
            src += 2;
        } else {
            if (n >= PT_LINE_MAX - 1) {
                break;
            }
            dst[n++] = b;
            src++;
        }
    }
    dst[n] = 0;
    return n;
}

static s32 pt_is_pause_char(PtChar *c)
{
    s32 i;

    if (c->is_sjis) {
        for (i = 0; i < 5; i++) {
            if (((msg_str_disp_str0[i * 4] << 8) | msg_str_disp_str0[i * 4 + 1]) == c->code) {
                return 1;
            }
        }
        return 0;
    }
    switch (c->code) {
    case ' ': case '.': case ',': case '-': case '!': case '?':
    case '\'': case '"': case '(': case ')': case ':': case ';':
        return 1;
    }
    return 0;
}

static s32 pt_silent_message(u8 *s)
{
    PtChar c;
    s32 any = 0;

    pt_reset();
    while (pt_next(&s, &c)) {
        if (c.is_ctrl) {
            continue;
        }
        any = 1;
        if (!pt_is_pause_char(&c)) {
            return 0;
        }
    }
    return any;
}

static s32 pt_queue_row(s16 x, s16 y, u8 color, u8 *row, s32 ot)
{
    if (row[0] == msg_str_disp_str5[0] && row[1] == msg_str_disp_str5[1]) {
        return set_kanji_string((s16)(x - 14), y, color, row, ot);
    }
    if (row[0] == '(') {
        return set_kanji_string((s16)(x - 6), y, color, row, ot);
    }
    return set_kanji_string(x, y, color, row, ot);
}

s16 patch_first_row_x;

static s32 pt_queue_wrapped(s16 x, s16 y, u8 color, u8 *line, s32 ot,
                            s32 max_px, s16 *dy, s32 pitch, s32 measure)
{
    u8 *p = line;
    u8 *seg = line;
    u8 *last_space = 0;
    u8 *prev = line;
    u8 *q;
    PtChar c;
    s32 w = 0;
    s32 ret = 0;
    s32 cw;
    s32 packed = pt_is_packed(line);
    s32 pass;
    s16 rx = x;
    s32 rmax = max_px;

    if (*dy == 0 && patch_first_row_x != 0) {

        rx = patch_first_row_x;
        rmax = max_px - (patch_first_row_x - x);
        if (rmax < 48) {
            rmax = 48;
        }
    }
    pt_reset();
    for (;;) {
        q = p;
        if (!pt_next(&p, &c)) {
            break;
        }
        if (c.is_ctrl) {
            continue;
        }
        cw = packed ? pt_char_width(c.code, c.is_sjis) : 14;
        if (w + cw > rmax && q > seg) {
            if (last_space != 0 && last_space > seg) {
                if (measure) {
                    seg = last_space + 1;
                } else {
                    *last_space = 0;
                    ret = pt_queue_row(rx, (s16)(y + *dy), color, seg, ot);
                    seg = last_space + 1;
                }
                p = seg;
            } else {

                if (!measure) {
                    u8 saved = *q;
                    *q = 0;
                    ret = pt_queue_row(rx, (s16)(y + *dy), color, seg, ot);
                    *q = saved;
                }
                seg = q;
                p = seg;
            }
            *dy += (s16)pitch;
            rx = x;
            rmax = max_px;
            w = 0;
            last_space = 0;
            pt_reset();
            continue;
        }
        if (!c.is_sjis && c.code == ' ') {
            last_space = q;
        }
        w += cw;
        prev = q;
    }
    (void)prev;
    (void)pass;

    if (!measure) {
        ret = pt_queue_row(rx, (s16)(y + *dy), color, seg, ot);
    }
    *dy += (s16)pitch;
    return ret;
}

#define PT_CHOICE_PLAIN  1
#define PT_CHOICE_ROWS_MAX 3
#define PT_CHOICE_PITCH_TIGHT 12
s16 patch_choice_y[4];
u8 patch_choice_rows[4];
u8 patch_choice_count;
u8 patch_choice_pitch = PT_LINE_PITCH;

s32 pt_schedule_analyze(s16 x, s16 y, u8 color, u8 *str, s32 ot,
                        u8 *suffix, u8 *bullet, u8 show)
{
    static u8 work[PT_LINE_MAX];
    static u8 msg[512];
    u8 *p;
    u8 *start;
    u32 b;
    s16 dy = 0;
    s16 dy0;
    s32 ret = 0;
    s32 n;
    s32 i;
    s32 max_px;
    s32 plain = (show != 0 && PT_CHOICE_PLAIN);
    s32 pitch = PT_LINE_PITCH;
    s32 pass;

    if (*str == 0) {
        return 0;
    }
    if (plain) {
        x = (s16)(x - 14);
        patch_choice_count = 0;
        patch_choice_pitch = PT_LINE_PITCH;
    }
    max_px = PT_WIN_RIGHT - x;
    if (max_px < 64) {
        max_px = 64;
    }
    for (i = 0; str[i] != 0 && i < 511; i++) {
        msg[i] = str[i];
    }
    msg[i] = 0;
    pt_legacy_to_patch(msg);
    if (msg[0] == PT_C_NOP) {
        str = msg + 1;
    } else {
        str = msg;
    }
    mugon_flag = pt_silent_message(str);

    for (pass = plain ? 0 : 1; pass < 2; pass++) {
        dy = 0;
        start = str;
        p = str;
        for (;;) {
            b = *p;
            if (b == PT_C_NEWLINE || b == PT_C_BREAK || b == 0) {
                if (show != 0 && !plain) {
                    set_kanji_string((s16)(x - 14), (s16)(y + dy), color, bullet, ot);
                }
                n = pt_expand_line(work, start, p);
                if ((show != 0 && !plain) || (show == 0 && b == 0 && *suffix != 0)) {
                    n = pt_append(work, n, suffix);
                }
                dy0 = dy;
                ret = pt_queue_wrapped(x, y, color, work, ot, max_px, &dy, pitch,
                                       pass == 0);
                if (plain && pass == 1 && patch_choice_count < 4) {
                    patch_choice_y[patch_choice_count] = (s16)(y + dy0);
                    patch_choice_rows[patch_choice_count] = (u8)((dy - dy0) / pitch);
                    patch_choice_count++;
                }
                if (b == 0) {
                    break;
                }
                p++;
                start = p;
                continue;
            }
            if (PT_IS_SJIS_LEAD(b)) {
                if (p[1] == 0) {
                    p++;
                    continue;
                }
                p += 2;
            } else {
                p++;
            }
        }
        if (pass == 0 && dy > PT_CHOICE_ROWS_MAX * PT_LINE_PITCH) {
            pitch = PT_CHOICE_PITCH_TIGHT;
            patch_choice_pitch = PT_CHOICE_PITCH_TIGHT;
        }
    }
    last_x_y = (s16)(y + dy);
    patch_first_row_x = 0;
    return ret;
}

void pt_choice_shuffle(u8 *msg)
{
    static u8 seg[4][PT_LINE_MAX];
    s32 count = 0;
    s32 n = 0;
    u8 *p = msg;
    u32 b;
    s32 i;
    s32 k;

    pt_legacy_to_patch(msg);
    for (;;) {
        b = *p;
        if (b == PT_C_BREAK || b == PT_C_NEWLINE || b == 0) {
            seg[count][n] = 0;
            count++;
            n = 0;
            if (b == 0 || count >= 4) {
                break;
            }
            p++;
            continue;
        }
        if (PT_IS_SJIS_LEAD(b) && p[1] != 0) {
            if (n < PT_LINE_MAX - 2) {
                seg[count][n++] = b;
                seg[count][n++] = p[1];
            }
            p += 2;
        } else {
            if (n < PT_LINE_MAX - 1) {
                seg[count][n++] = b;
            }
            p++;
        }
    }
    while (count < 3) {
        seg[count][0] = 0;
        count++;
    }
    n = 0;
    for (i = 0; i < 3; i++) {
        k = junban[i];
        if (k > 2) {
            k = i;
        }
        if (i > 0) {
            msg[n++] = PT_C_BREAK;
        }
        n = pt_append(msg, n, seg[k]) ;
        if (n >= PT_LINE_MAX - 1) {
            break;
        }
    }
    msg[n] = 0;
}
