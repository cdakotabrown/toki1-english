#include "dbg.h"

#define ROW_SCENE   0
#define ROW_GIRL    1
#define ROW_SUB     2
#define ROW_SUBSUB  3
#define ROW_YEAR    4
#define ROW_MONTH   5
#define ROW_DAY     6
#define ROW_COUNT   7

#define GIRL_MAX    12

u8 dbg_open;
u8 dbg_row;
s16 dbg_scene_idx;
u8 dbg_girl;
u8 dbg_sub;
u8 dbg_subsub;
static u8 dbg_repeat;
static s16 dbg_pending_scene;
static u8 dbg_pending_sub;
static u8 dbg_pending_subsub;
static u8 dbg_init_done;
u8 dbg_unlocked;
static u8 dbg_saved_class;
static u8 dbg_last_step;
static u32 dbg_frames;
s32 dbg_jumps;

static const u8 s_title[]  = "KONAMI DEBUG = SCENE SELECT";
static const u8 s_help1[]  = "UP DOWN ROW   LEFT RIGHT CHANGE   L R TRIG BY TEN";
static const u8 s_help2[]  = "CIRCLE JUMP   TRIANGLE UNLOCK   CROSS CLOSE";
static const u8 s_scene[]  = "SCENE";
static const u8 s_girl[]   = "GIRL";
static const u8 s_sub[]    = "SUB STEP";
static const u8 s_subsub[] = "SUB SUB";
static const u8 s_year[]   = "YEAR";
static const u8 s_month[]  = "MONTH";
static const u8 s_day[]    = "DAY";
static const u8 s_now[]    = "NOW STEP";
static const u8 s_cursor[] = ">";
static const u8 s_unl[]    = "UNLOCKED";
static const u8 s_jumps[]  = "JUMPS";

void dbg_str(const u8 *s, s32 x, s32 y, s32 pal)
{
    _debug_string_show((u8 *)s, x, y, pal);
}

void dbg_num(s32 v, s32 x, s32 y, s32 pal)
{
    _debug_number_show(v, x, y, pal);
}

void dbg_font_load(void)
{
    if (D_800B9710 != 0) {
        load_image_rect(704, 480, 64, 32, (s32)dbg_font_image);
    }
}

static s32 dbg_find_scene(s32 id)
{
    s32 i;
    for (i = 0; i < dbg_scene_count; i++) {
        if (dbg_scenes[i].id == id) {
            return i;
        }
    }
    return 0;
}

static void dbg_menu_close(void)
{
    dbg_open = 0;
    D_800EF872 = dbg_saved_class;
}

static void dbg_menu_open(void)
{
    dbg_open = 1;

    dbg_saved_class = D_800EF872;
    D_800EF872 = 0;
    dbg_font_load();
    dbg_row = ROW_SCENE;
    dbg_repeat = 0;
    dbg_girl = now_girl;
    if (dbg_girl > GIRL_MAX) {
        dbg_girl = 0;
    }
    dbg_sub = 0;
    dbg_subsub = 0;
    if (dbg_scene_idx < 0 || dbg_scene_idx >= dbg_scene_count) {
        dbg_scene_idx = dbg_find_scene(49);
    }
}

static void dbg_jump(void)
{
    const DbgScene *sc = &dbg_scenes[dbg_scene_idx];

    now_girl = dbg_girl;
    D_800BD234 = 0;
    dbg_pending_scene = sc->id;
    dbg_pending_sub = dbg_sub;
    dbg_pending_subsub = dbg_subsub;
    dbg_jumps++;
    dbg_menu_close();
    goto_step(sc->id);
}

static s32 dbg_delta(s32 trig, s32 held)
{
    s32 d = 0;

    if (trig & PAD_LEFT) {
        d = -1;
    } else if (trig & PAD_RIGHT) {
        d = 1;
    } else if (trig & PAD_L1) {
        d = -10;
    } else if (trig & PAD_R1) {
        d = 10;
    }

    if (d == 0 && (held & (PAD_LEFT | PAD_RIGHT | PAD_L1 | PAD_R1))) {
        dbg_repeat++;
        if (dbg_repeat > 20 && (dbg_repeat & 3) == 0) {
            if (held & PAD_LEFT) {
                d = -1;
            } else if (held & PAD_RIGHT) {
                d = 1;
            } else if (held & PAD_L1) {
                d = -10;
            } else if (held & PAD_R1) {
                d = 10;
            }
        }
    } else if (d != 0) {
        dbg_repeat = 0;
    } else {
        dbg_repeat = 0;
    }
    return d;
}

static s32 dbg_wrap(s32 v, s32 lo, s32 hi)
{
    if (v < lo) {
        return hi;
    }
    if (v > hi) {
        return lo;
    }
    return v;
}

static void dbg_edit(s32 d)
{
    switch (dbg_row) {
    case ROW_SCENE:
        dbg_scene_idx = dbg_wrap(dbg_scene_idx + d, 0, dbg_scene_count - 1);
        break;
    case ROW_GIRL:
        dbg_girl = dbg_wrap(dbg_girl + d, 0, GIRL_MAX);
        break;
    case ROW_SUB:
        dbg_sub = dbg_wrap(dbg_sub + d, 0, 255);
        break;
    case ROW_SUBSUB:
        dbg_subsub = dbg_wrap(dbg_subsub + d, 0, 255);
        break;
    case ROW_YEAR:
        now_year = dbg_wrap(now_year + d, 95, 98);
        break;
    case ROW_MONTH:
        now_month = dbg_wrap(now_month + d, 1, 12);
        break;
    case ROW_DAY:
        now_day = dbg_wrap(now_day + d, 1, 31);
        break;
    }
}

static void dbg_draw_row(s32 row, const u8 *label, s32 value, s32 y)
{
    s32 pal = (row == dbg_row) ? 1 : 0;

    if (row == dbg_row) {
        dbg_str(s_cursor, -150, y, 1);
    }
    dbg_str(label, -140, y, pal);
    dbg_num(value, 0, y, pal);
}

typedef struct {
    u32 tag;
    u8 r0, g0, b0, code;
    s16 x0, y0;
    s16 w, h;
} DbgTile;

static void dbg_clear(void)
{
    DbgTile *p = (DbgTile *)prim_alloc(16, activeBuff);

    SetTile(p);
    SetSemiTrans(p, 0);
    p->r0 = 0;
    p->g0 = 0;
    p->b0 = 0;
    p->x0 = *(s16 *)(screen_w + 20 + activeBuff * 2) - 160;
    p->y0 = *(s16 *)(screen_w + 24 + activeBuff * 2) - 120;
    p->w = 320;
    p->h = 240;
    AddPrim(&ot_buff0[(activeBuff << 10) + (2 << 2)], p);
}

static void dbg_draw(void)
{
    const DbgScene *sc = &dbg_scenes[dbg_scene_idx];
    s32 y;

    dbg_clear();
    dbg_str(s_title, -150, -112, 3);
    y = -92;
    dbg_draw_row(ROW_SCENE, s_scene, sc->id, y);
    dbg_str(sc->exn, 16, y, 2);
    dbg_str(sc->label, 80, y, (dbg_row == ROW_SCENE) ? 1 : 0);
    y += 12;
    dbg_draw_row(ROW_GIRL, s_girl, dbg_girl, y);
    y += 12;
    dbg_draw_row(ROW_SUB, s_sub, dbg_sub, y);
    y += 12;
    dbg_draw_row(ROW_SUBSUB, s_subsub, dbg_subsub, y);
    y += 12;
    dbg_draw_row(ROW_YEAR, s_year, now_year, y);
    y += 12;
    dbg_draw_row(ROW_MONTH, s_month, now_month, y);
    y += 12;
    dbg_draw_row(ROW_DAY, s_day, now_day, y);
    y += 20;
    dbg_str(s_now, -140, y, 2);
    dbg_num(now_step, 0, y, 2);
    dbg_num(now_sub_step, 40, y, 2);
    dbg_num(now_sub_sub_step, 80, y, 2);
    dbg_num(step_mode, 120, y, 2);
    y += 12;
    dbg_str(s_jumps, -140, y, 2);
    dbg_num(dbg_jumps, 0, y, 2);
    if (dbg_unlocked) {
        dbg_str(s_unl, 40, y, 1);
    }
    dbg_str(s_help1, -150, 92, 4);
    dbg_str(s_help2, -150, 104, 4);
}

static void dbg_menu_frame(void)
{
    s32 trig = pad_trig & 0xFFFF;
    s32 held = pad_data & 0xFFFF;
    s32 d;

    if (trig & PAD_CROSS) {
        dbg_menu_close();
        return;
    }
    if (trig & PAD_UP) {
        dbg_row = (dbg_row == 0) ? ROW_COUNT - 1 : dbg_row - 1;
    } else if (trig & PAD_DOWN) {
        dbg_row = (dbg_row == ROW_COUNT - 1) ? 0 : dbg_row + 1;
    }
    d = dbg_delta(trig, held);
    if (d != 0) {
        dbg_edit(d);
    }
    if (trig & PAD_TRI) {
        dbg_unlock_all();
        dbg_unlocked = 1;
    }
    if (trig & PAD_CIRCLE) {
        dbg_jump();
        return;
    }
    dbg_draw();
}

void dbg_game_main(void)
{
    if (!dbg_init_done) {
        dbg_init_done = 1;
        dbg_pending_scene = -1;
        dbg_scene_idx = -1;
    }

    if (now_step != 208) {
        D_800B9710 = 1;
    }

    dbg_frames++;
    if (now_step != dbg_last_step || (dbg_frames & 0xFF) == 0) {
        dbg_last_step = now_step;
        dbg_font_load();
    }
    if (dbg_pending_scene >= 0 && now_step == dbg_pending_scene) {
        if (dbg_pending_sub != 0 || dbg_pending_subsub != 0) {
            now_sub_step = dbg_pending_sub;
            now_sub_sub_step = dbg_pending_subsub;
            step_mode = 0;
        }
        dbg_pending_scene = -1;
    }
    if (dbg_open) {
        dbg_menu_frame();
        return;
    }
    if ((pad_data & DBG_OPEN_MASK) == DBG_OPEN_MASK &&
        (pad_trig & DBG_OPEN_MASK) != 0) {

        if (now_step > 2 && now_step < 254 && now_step != 208) {
            dbg_menu_open();
            return;
        }
    }
    game_main();
}
