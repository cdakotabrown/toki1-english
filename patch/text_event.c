#define PT_WIN_LEFT     (-128)
#define PT_BODY_X       (-72)
#define PT_LABEL_BUDGET 44
#include "patch_text.h"

#define PT_C_NOSHOW    0x0E
#define PT_C_TAG_GT    0x10
#define PT_C_TAG_MINUS 0x11
#define PT_C_TAG_PLUS  0x12
#define PT_C_TAG_LT    0x13
#define PT_C_SFX       0x14
#define PT_C_SFX2      0x15
#define PT_C_NARR      0x16
#define PT_C_PLAIN     0x17
#define PT_C_SEP       0x1F

extern s32 serifu_voice;
extern s32 serifu_wait;
extern s32 serifu_line;
extern u8 junban[3];
extern u8 sound_seek_wait;
extern s16 last_x_y;
extern s32 serifu_state;
extern s32 serifu_no;
extern s32 msg_wait;
extern u8 p_name[];
extern u8 g_name[];
extern u8 xcut;
extern s16 sound_seek_time;
extern u8 voice_level;
extern u8 now_girl;
extern u8 serifu_cmd_exec_tbl56[];
extern s32 date_name_set_tbl0[];
extern u8 msg_str_disp_str6[];
extern u8 serifu_cmd_exec_str1[];
extern u8 serifu_cmd_exec_tbl0[];
extern u8 serifu_cmd_exec_tbl1[];
extern u8 serifu_cmd_exec_str19[];
extern u8 serifu_cmd_exec_tbl24[];
extern u8 serifu_cmd_exec_tbl25[];
extern u8 serifu_cmd_exec_str21[];
extern u8 serifu_cmd_exec_tbl26[];
extern u8 serifu_cmd_exec_tbl27[];
extern u8 serifu_cmd_exec_str28[];
extern u8 serifu_cmd_exec_tbl31[];
extern u8 serifu_cmd_exec_tbl32[];
extern u8 serifu_cmd_exec_str35[];
extern u8 serifu_cmd_exec_tbl41[];
extern u8 serifu_cmd_exec_tbl42[];
extern u8 serifu_cmd_exec_str36[];
extern u8 serifu_cmd_exec_tbl43[];
extern u8 serifu_cmd_exec_tbl44[];
extern u8 serifu_cmd_exec_tbl16[];
extern u8 serifu_cmd_exec_tbl17[];
extern u8 serifu_cmd_exec_tbl18[];
extern u8 serifu_cmd_exec_tbl19[];
extern u8 serifu_cmd_exec_tbl22[];
extern u8 serifu_cmd_exec_tbl23[];
extern u8 serifu_cmd_exec_str52[];
extern u8 serifu_cmd_exec_str53[];
extern u8 serifu_cmd_exec_str54[];
extern u8 serifu_cmd_exec_str55[];
extern u8 serifu_cmd_exec_str56[];
extern u8 serifu_cmd_exec_str57[];

extern s32 set_kanji_string(s16, s16, u8, u8 *, s32);
extern s32 pt_schedule_analyze(s16, s16, u8, u8 *, s32, u8 *, u8 *, u8);
extern void pt_choice_shuffle(u8 *);
extern s32 k_disp_start(s32);
extern void func_800830BC(void);
extern void sub_sub_step_up(void);
extern void func_80046840(void);
extern void set_XAsector(u32, u32, u8);
extern void func_80044980(s32);
extern s32 get_CD_State(void);
extern void serifu_skip(void);
extern void cmd_que_clear(void);

static u8 pt_ev_buf[512];
static u8 pt_ev_tmp[512];
static u8 pt_ev_prefix[64];

extern s32 pt_is_legacy(u8 *);
extern s32 pt_legacy_to_patch(u8 *);
extern void pt_legacy_letters(u8 *);
extern u8 serifu_cmd_exec_str9[];
extern u8 serifu_cmd_exec_str10[];
extern u8 serifu_cmd_exec_str11[];
extern u8 serifu_cmd_exec_str12[];
extern u8 serifu_cmd_exec_str13[];
extern u8 serifu_cmd_exec_str15[];
extern u8 serifu_cmd_exec_str16[];

enum { PT_XA_GO = 0, PT_XA_WAIT = 1, PT_XA_TIMEOUT = 2 };

static s32 pt_strlen(u8 *s)
{
    s32 n = 0;
    while (s[n] != 0) {
        n++;
    }
    return n;
}

static s32 pt_streq(u8 *a, u8 *b)
{
    while (*a != 0 && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

static void pt_event_legacy(void)
{
    u8 *s = pt_ev_buf;
    u8 *d = pt_ev_tmp;
    s32 n;
    s32 plen = 0;
    u32 tag = 0;
    s32 i;

    for (i = 0; s[i] != 0; i++) {
        if (s[i] < 0x20) {
            return;
        }
    }
    n = i;
    if (n == 0) {
        return;
    }

    if (pt_streq(s, serifu_cmd_exec_str9) || pt_streq(s, serifu_cmd_exec_str16)) {
        tag = PT_C_NARR;
    } else if (pt_streq(s, serifu_cmd_exec_str10) || pt_streq(s, serifu_cmd_exec_str11) ||
               pt_streq(s, serifu_cmd_exec_str12) || pt_streq(s, serifu_cmd_exec_str13)) {
        tag = PT_C_SFX;
    } else if (pt_streq(s, serifu_cmd_exec_str15)) {
        tag = PT_C_SFX2;
    } else if (s[0] == '>') {
        tag = PT_C_TAG_GT; plen = 4;
    } else if (s[0] == '-') {
        tag = PT_C_TAG_MINUS; plen = 6;
    } else if (s[0] == '+') {
        tag = PT_C_TAG_PLUS; plen = 2;
    } else if (s[0] == '<') {
        tag = PT_C_TAG_LT; plen = 4;
    }
    if (tag == 0 && !pt_is_legacy(s)) {

        return;
    }
    if (tag >= PT_C_TAG_GT && tag <= PT_C_TAG_LT) {
        *d++ = (u8)tag;
        for (i = 1; i <= plen && s[i] != 0; i++) {
            *d++ = s[i];
        }
        *d++ = PT_C_SEP;
        s += i;
    } else if (tag != 0) {
        *d++ = (u8)tag;
    }

    n = pt_strlen(s);
    if (n >= 2 && s[n - 1] == 'n' && s[n - 2] == 'n') {
        s[n - 2] = 0;
        n -= 2;
    } else {
        n = -1;
    }
    {
        s32 seg_start = 1;
        while (*s != 0) {
            if (seg_start && *s == 'n') {
                *d++ = PT_C_NOSHOW;
                s++;
                seg_start = 0;
                continue;
            }
            seg_start = (*s == 'q');
            if (PT_IS_SJIS_LEAD(*s) && s[1] != 0) {
                *d++ = *s++;
                *d++ = *s++;
            } else {
                *d++ = *s++;
            }
        }
    }
    if (n >= 0) {
        *d++ = PT_C_NOSHOW;
    }
    *d = 0;

    for (i = 0; pt_ev_tmp[i] != 0; i++) {
        pt_ev_buf[i] = pt_ev_tmp[i];
    }
    pt_ev_buf[i] = 0;
    {
        u8 *p = pt_ev_buf;

        if (tag >= PT_C_TAG_GT && tag <= PT_C_TAG_LT) {
            while (*p != 0 && *p != PT_C_SEP) {
                p++;
            }
            if (*p == PT_C_SEP) {
                p++;
            }
        } else if (tag != 0) {
            p++;
        }
        pt_legacy_letters(p);
    }
}

static s32 pt_xa_wait(u32 *e, s32 channel)
{
    if (sound_seek_time++ == 0 && serifu_state == 0) {
        set_XAsector(e[0], e[1], (u8)channel);
        func_80044980(768);
    }
    if (sound_seek_time < 1024) {
        if ((get_CD_State() & 4) == 0 && serifu_state == 0) {
            sound_seek_wait = 1;
            serifu_skip();
            if (sound_seek_wait == 1) {
                return PT_XA_WAIT;
            }
        }
    } else {
        sound_seek_time = 0;
        cmd_que_clear();
        func_80044980(116);
        return PT_XA_TIMEOUT;
    }
    serifu_voice = 1;
    sound_seek_time = 0;
    return PT_XA_GO;
}

static u8 pt_quote[2] = { '"', 0 };
u8 pt_label_buf[32];

static u8 *const pt_label_short[][2] = {
    { (u8 *)"Kiyokawa", (u8 *)"Nozomi" },
    { (u8 *)"Tatebayashi", (u8 *)"Miharu" },
    { 0, 0 }
};

u8 *pt_fit_label_w(u8 *name, s32 budget)
{
    s32 i;
    s32 n;
    s32 w;
    PtChar c;
    u8 *p;
    u8 *q;

    if (name[0] == PT_C_REF) {
        name = pt_long_name(name[1]);
    }
    if (pt_text_width(name) <= budget) {
        return name;
    }
    for (i = 0; pt_label_short[i][0] != 0; i++) {
        if (pt_streq(name, pt_label_short[i][0])) {
            return pt_label_short[i][1];
        }
    }
    n = 0;
    w = pt_text_width(pt_quote) + 2;
    p = name;
    pt_reset();
    for (;;) {
        q = p;
        if (!pt_next(&p, &c)) {
            break;
        }
        if (c.is_ctrl) {
            continue;
        }
        w += pt_char_width(c.code, c.is_sjis);
        if (w > budget || n >= 28) {
            break;
        }
        while (q < p) {
            pt_label_buf[n++] = *q++;
        }
    }
    pt_label_buf[n++] = '.';
    pt_label_buf[n] = 0;
    return pt_label_buf;
}

static u8 *pt_fit_label(u8 *name)
{
    return pt_fit_label_w(name, PT_LABEL_BUDGET);
}

static s16 pt_label(u8 *name, s16 *y, u8 color)
{
    s32 qw = pt_text_width(pt_quote);

    set_kanji_string(PT_WIN_LEFT, *y, color, pt_fit_label(name), 0);
    set_kanji_string((s16)(PT_BODY_X - qw - 1), *y, color, pt_quote, 0);
    return PT_BODY_X;
}

static s32 pt_say(u8 *name, s16 v, u8 color, u8 *body, u8 *suffix, u8 *bullet)
{
    s16 bx = pt_label(name, &v, color);
    return pt_schedule_analyze(bx, v, color, body, 0, suffix, bullet, 0);
}

static s32 pt_strip_noshow(u8 *s)
{
    s32 n = pt_strlen(s);
    if (n > 0 && s[n - 1] == PT_C_NOSHOW) {
        s[n - 1] = 0;
        return 1;
    }
    return 0;
}

static u8 *pt_lift_prefix(u8 *s, s32 *tag)
{
    s32 n = 0;
    u8 *p;

    *tag = 0;
    if (s[0] < PT_C_TAG_GT || s[0] > PT_C_TAG_LT) {
        return 0;
    }
    *tag = s[0];
    p = s + 1;
    while (*p != 0 && *p != PT_C_SEP && n < 63) {
        pt_ev_prefix[n++] = *p++;
    }
    pt_ev_prefix[n] = 0;
    if (*p == PT_C_SEP) {
        p++;
    }
    return p;
}

static u8 *pt_nth_segment(u8 *s, s32 want)
{
    u8 *seg = s;
    s32 cnt = 0;
    u32 b;

    for (;;) {
        b = *s;
        if (b == PT_C_BREAK || b == 0) {
            *s = 0;
            if (cnt == want || b == 0) {
                return seg;
            }
            cnt++;
            s++;
            seg = s;
            continue;
        }
        if (PT_IS_SJIS_LEAD(b) && s[1] != 0) {
            s += 2;
        } else {
            s++;
        }
    }
}

static s32 pt_body_default(u8 *buf, s16 v, u8 color, u8 *suffix, u8 *bullet)
{
    u32 b = buf[0];

    if (b == PT_C_SFX) {
        return pt_schedule_analyze(-128, v, 2, buf + 1, 0, suffix, bullet, 0);
    }
    if (b == PT_C_SFX2) {
        return pt_schedule_analyze(-128, v, 1, buf + 1, 0, suffix, bullet, 0);
    }
    if (b == PT_C_NARR) {
        return pt_schedule_analyze(-40, (s16)(v + 16), color, buf + 1, 0,
                                   suffix, bullet, 0);
    }
    if (b == PT_C_PLAIN) {
        return pt_schedule_analyze(-128, v, color, buf + 1, 0, suffix, bullet, 0);
    }
    return pt_schedule_analyze(-128, v, color, buf, 0, suffix, bullet, 0);
}

s32 pt_event_message(u8 *str, s32 sel, s32 a2, void *voice, u16 i1, u16 i2,
                     u8 color)
{
    u32 *e;
    s16 v;
    s32 r;
    s32 tag;
    u8 *body;
    u8 *seg;
    u32 usel = (u32)(sel & 0xFF);
    u32 ua2 = (u32)(a2 & 0xFF);

    if (usel != 255) {
        s32 i = 0;
        while (str[i] != 0 && i < 511) {
            pt_ev_buf[i] = str[i];
            i++;
        }
        pt_ev_buf[i] = 0;
        pt_event_legacy();
    }
    serifu_voice = 0;
    sound_seek_wait = 0;
    v = (s16)(serifu_line * 16 + 48);
    e = ((u32 ***)voice)[i1][i2];

    switch (usel) {
    case 7:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        body = pt_lift_prefix(pt_ev_buf, &tag);
        if (body != 0) {
            pt_say(pt_ev_prefix, v, color, body, serifu_cmd_exec_tbl0, serifu_cmd_exec_tbl1);
        } else {
            pt_body_default(pt_ev_buf, v, color, serifu_cmd_exec_tbl0, serifu_cmd_exec_tbl1);
        }
        serifu_state = 1;
        break;

    case 16:
        pt_schedule_analyze(-128, v, color, pt_ev_buf, 0, serifu_cmd_exec_tbl16, serifu_cmd_exec_tbl17, 0);
        serifu_wait = 1;
        break;

    case 17:
        pt_schedule_analyze(-72, last_x_y, color, pt_ev_buf, 0, serifu_cmd_exec_tbl18,
                            serifu_cmd_exec_tbl19, 0);
        serifu_wait = 1;
        break;

    case 9:
        if (pt_ev_buf[0] == 0) {
            break;
        }
        pt_body_default(pt_ev_buf, v, color, serifu_cmd_exec_tbl22, serifu_cmd_exec_tbl23);
        return 0;

    case 0:
    case 14:
        if (pt_strip_noshow(pt_ev_buf) && serifu_no != 0 && usel == 0) {
            return 0;
        }
        pt_say(p_name, v, color, pt_ev_buf, serifu_cmd_exec_tbl24, serifu_cmd_exec_tbl25);
        if (usel == 0) {
            serifu_state = 1;
        }
        return 0;

    case 1:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0 &&
            !(pt_ev_buf[pt_strlen(pt_ev_buf) - 1] == PT_C_NOSHOW && serifu_no != 0)) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        if (pt_strip_noshow(pt_ev_buf) && serifu_no != 0) {
            return 0;
        }
        pt_say(g_name, v, color, pt_ev_buf, serifu_cmd_exec_tbl31, serifu_cmd_exec_tbl32);
        serifu_state = 1;
        return 0;

    case 15:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        pt_say(g_name, v, color, pt_ev_buf, serifu_cmd_exec_tbl31, serifu_cmd_exec_tbl32);
        msg_wait = 1;
        return 0;

    case 12:
        xcut = 0;
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        if (pt_strip_noshow(pt_ev_buf) && serifu_no != 0) {
            return 0;
        }
        pt_say(g_name, v, color, pt_ev_buf, serifu_cmd_exec_tbl31, serifu_cmd_exec_tbl32);
        serifu_wait = 1;
        return 0;

    case 13:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0 && xcut == 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        if (pt_strip_noshow(pt_ev_buf)) {
            if (serifu_no != 0) {
                return 0;
            }
            pt_schedule_analyze(-72, last_x_y, color, pt_ev_buf, 0, serifu_cmd_exec_tbl41,
                                serifu_cmd_exec_tbl42, 0);
            serifu_state = 1;
            return 0;
        }
        set_kanji_string(-86, v, color, serifu_cmd_exec_str35, 0);
        pt_schedule_analyze(-72, last_x_y, color, pt_ev_buf, 0, serifu_cmd_exec_tbl41,
                            serifu_cmd_exec_tbl42, 0);
        serifu_state = 1;
        return 0;

    case 18:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0 && xcut == 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        set_kanji_string(-86, v, color, serifu_cmd_exec_str36, 0);
        pt_schedule_analyze(-72, last_x_y, color, pt_ev_buf, 0, serifu_cmd_exec_tbl43,
                            serifu_cmd_exec_tbl44, 0);
        serifu_wait = 1;
        break;

    case 11:
    case 10:
        if ((e[0] != 0 || e[1] != 0) && voice_level != 0) {
            r = pt_xa_wait(e, usel == 11 ? 0 : 13);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        if (pt_strip_noshow(pt_ev_buf) && serifu_no != 0) {
            return 0;
        }

        pt_say(usel == 11 ? (u8 *)date_name_set_tbl0[0] : msg_str_disp_str6, v, color, pt_ev_buf,
               serifu_cmd_exec_tbl31, serifu_cmd_exec_tbl32);
        serifu_state = 1;
        return 0;

    case 4:
    case 6:
        pt_say(p_name, v, color, pt_ev_buf, serifu_cmd_exec_tbl24, serifu_cmd_exec_tbl25);
        serifu_state = 1;
        break;

    case 3:
        if (ua2 != 255) {
            func_800830BC();
            pt_choice_shuffle(pt_ev_buf);
        } else {
            junban[0] = 0;
            junban[1] = 1;
            junban[2] = 2;
        }
        k_disp_start(pt_schedule_analyze(-114, v, color, pt_ev_buf, 0, serifu_cmd_exec_str52,
                                         serifu_cmd_exec_str53, 1));
        return 0;

    case 8:
        junban[0] = 0;
        junban[1] = 1;
        k_disp_start(pt_schedule_analyze(-114, v, color, pt_ev_buf, 0, serifu_cmd_exec_str54,
                                         serifu_cmd_exec_str55, 1));
        return 0;

    case 19:
        junban[0] = 0;
        junban[1] = 1;
        k_disp_start(pt_schedule_analyze(-114, v, color, pt_ev_buf, 0, serifu_cmd_exec_str56,
                                         serifu_cmd_exec_str57, 1));
        return 0;

    case 2:
    case 5:
        e = ((u32 ***)voice)[i1][i2] + serifu_no * 2;
        if (e[0] != 0 && voice_level != 0) {
            r = pt_xa_wait(e, serifu_cmd_exec_tbl56[now_girl]);
            if (r == PT_XA_WAIT) return 0;
            if (r == PT_XA_TIMEOUT) return 100;
        }
        seg = pt_nth_segment(pt_ev_buf, (s32)ua2);
        if (seg[0] == PT_C_NOSHOW) {
            break;
        }
        pt_say(g_name, v, color, seg, serifu_cmd_exec_tbl31, serifu_cmd_exec_tbl32);
        serifu_state = 1;
        break;

    case 255:
        sub_sub_step_up();
        return 0;

    default:
        func_80046840();
        break;
    }
    return 0;
}
