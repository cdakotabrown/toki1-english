#!/usr/bin/env python3
"""build_jev_qa_kit.py - the Jev QA triage kit: every English line the patch
ships, with its Japanese, its speaker, its scene, its neighbours and its
constraints, plus the voice bibles, the question set, a stdlib-only runner
and the report / calibration tools, zipped for a LOCAL Jev run.

Which English ships is decided the way the patch builder decides it, by
calling the builder's own code, not by re-reading the sheets:

  containers   tools/patch/inject.py: load_containers() over the profile's
               container dirs (sheets + tagged rows + choice_overrides /
               choice_edits), then prepare() + pack() with the run's DTE
               table; a row ships when it is still `translated` after the
               pack (no token mismatch, not immutable, not fallen back);
               the English is the FITTED text (normalised, reflowed)
  overlays     tools/patch/ui_strings.py and tools/patch/overlay_sheets.py
               are run as the build runs them (build/patch/gen/*.json);
               each entry they emit is one line (profile strings in
               config/patch/english.json first, ui_strings next, the
               draft-sheet strings last: the builder's precedence)
  art          src/patch/art/*/manifest.json cells / sprite segments
  compositions config/patch/compositions.json: one sample rendering per
               composition alternative, from the shipped pieces

The kit template (runner, report, questions, docs) lives next to this
file in tools/translation/jev_qa_kit/; the data and the context are
generated.  Output: build/jev-qa/toki-jev-qa/ and build/jev-qa/toki-jev-qa.zip
(gitignored: the zip holds the game's Japanese script, never commit it).

    python3 tools/translation/build_jev_qa_kit.py            # build + zip
    python3 tools/translation/build_jev_qa_kit.py --no-zip   # directory only
    python3 tools/translation/build_jev_qa_kit.py --selftest # + runner/selftest.py

Needs the extracted disc (assets/extracted_iso/CDROM, assets/overlays,
disks/SLPS_000.65 and the Track 1 image for the draft sheets), like the
patch build.
"""
import argparse
import csv
import json
import re
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "patch")]   # roots.py: tools/patch, or tools/ (public)
from roots import ROOT, GUIDE, ART, PATCH_CONFIG, SHEETS, CONTAINERS  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate, rel as _rel  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "jev_qa_kit"
LOC = GUIDE
PROFILE = PATCH_CONFIG / "english.json"
GEN = ROOT / "build" / "patch" / "gen"
OUT = ROOT / "build" / "jev-qa"
KIT_NAME = "toki-jev-qa"
MAIN_BASE = 0x80041000 - 0x800
OV_BASE = 0x80132000
NEIGHBOURS = 3

# ---------------------------------------------------------------------------
# people and places
# ---------------------------------------------------------------------------

GIRLS = OrderedDict([
    ("FU", "Shiori Fujisaki"), ("NI", "Saki Nijino"), ("KI", "Mio Kisaragi"),
    ("HI", "Yuina Himoo"), ("KA", "Ayako Katagiri"), ("KY", "Nozomi Kiyokawa"),
    ("KG", "Mira Kagami"), ("AS", "Yuko Asahina"), ("KO", "Yukari Koshiki"),
    ("MI", "Megumi Mikihara"), ("SA", "Yumi Saotome"),
])
NAME_TO_CODE = {v: k for k, v in GIRLS.items()}
# BUNKA uses two codes of its own for the two girls whose SERIFU code is
# taken by another file family: KT_S6* is Ayako Katagiri's art-club booth
# (her "Bonjour" voice), KS_S6* Mio Kisaragi's literature-club booth.
# Inferred from the content; the sheets leave their speaker blank.
BUNKA_CODES = {"KT": "KA", "KS": "KI"}

# bible slug per speaker key
BIBLE_SLUG = {name: name.lower().replace(" ", "-") for name in GIRLS.values()}
BIBLE_SLUG.update({"player": "player", "other": "others", "Yoshio Saotome": "yoshio-saotome"})

SPEAKER_ROLE = {"player": "player", "player (choice)": "player",
                "narrator": "narrator", "system": "system", "announcer": "npc",
                "other (Rei/Miharu/NPC)": "npc", "Yoshio Saotome": "friend"}

# container -> what scene it is.  "docs" = stated in the project's
# documentation; "name" = inferred from the file name and its lines.
SCENES = {
    "SERIFU/DATE_": ("Date with {girl}: the date script, organised by date spot (museum, bowling, "
                     "concert, zoo, ...) in file order; heroine lines, the player's lines and his "
                     "reply menus", "docs"),
    "SERIFU/EVENT_OT": ("Events with the other characters (Rei Ijuin, Miharu Tatebayashi, NPCs), "
                        "e.g. Yoshio bringing news", "docs"),
    "SERIFU/EVENT_": ("{girl}'s own story events", "name"),
    "SPEAKTST/TEST_OT": ("Conversation bank for the other characters (speech-test container; "
                         "mirrors the SERIFU scripts)", "docs"),
    "SPEAKTST/TEST_": ("Conversation bank for {girl} (speech-test container that mirrors the SERIFU "
                       "scripts: greetings, reactions, phone and walk-home lines)", "docs"),
    "SERIFU/GEKO": ("Walking home together after school (下校), several heroines; the player's "
                    "reply menus", "name"),
    "SERIFU/GASSHUKU": ("Summer club training camp (合宿), several speakers", "name"),
    "SERIFU/GASSH_FU": ("Summer training camp: Shiori Fujisaki's lines", "name"),
    "SERIFU/G_APPEAR": ("First meetings: how each heroine first appears to the player", "name"),
    "SERIFU/G_BIRTH": ("Heroines' birthdays: the player gives a present, her reaction", "name"),
    "SERIFU/P_BIRTH": ("The player's birthday: heroines give him presents", "name"),
    "SERIFU/G_INVITE": ("A heroine invites the player out (date invitations)", "name"),
    "SERIFU/GROUP_D": ("Group dates", "name"),
    "SERIFU/HAGEMASI": ("Encouragement (励まし): chat lines heroines use to cheer the player / "
                        "small talk", "name"),
    "SERIFU/KARADATA": ("Karaoke date lines", "name"),
    "SERIFU/NYUBU": ("Joining a club (入部)", "name"),
    "SERIFU/OMIMAI": ("Sick visit (お見舞い): a heroine visits the sick player (OMIMAI overlay)",
                      "docs"),
    "SERIFU/SHOGATU": ("New Year (正月): shrine visit, omikuji (SHOUGATU overlay)", "docs"),
    "SERIFU/SHUGAKU": ("The school trip (修学旅行, SHUGAKU overlay)", "docs"),
    "SERIFU/VALEN": ("Valentine's Day (girls give chocolate; VALEN overlay)", "docs"),
    "SERIFU/WHITE": ("White Day (the player returns gifts)", "name"),
    "SERIFU/XMAS": ("The Christmas party", "name"),
    "SERIFU/ENDING": ("Graduation day: confessions under the Legendary Tree (ENDING overlay)",
                      "docs"),
    "SERIFU/EPILOG": ("Epilogue after the ending", "name"),
    "SERIFU/ZAKOSEN": ("Thugs pick a fight during a date (ザコ戦)", "name"),
    "SERIFU/SERIFU": ("Date-spot blurbs: who is performing at the concert hall etc.", "name"),
    "BUNKA/BUN_FU": ("Culture festival: Shiori Fujisaki's visit lines", "name"),
    "BUNKA/BUN_PC": ("Culture festival: computer-club booth", "name"),
    "BUNKA/TWINBEE": ("Culture festival: the TwinBee Time Attack game booth (instructions)", "name"),
    "BUNKA/URANAI": ("Culture festival: computer fortune-telling booth (BUNKASAI)", "docs"),
    "BUNKA/": ("Culture festival (bunkasai) club booth visit with {girl}; file suffix = "
               "variant (W/S/B/I/O/1/2/3)", "docs"),
    "MASTER/KOSIEN": ("Club finals: the high-school baseball tournament (Koshien) lines", "docs"),
    "MASTER/": ("Club finals and contest results (MASTER overlay, scenes 116-118): the player's "
                "club achievement (prize, contest, tournament)", "docs"),
    "TAIIKU/F_DANCE": ("Sports day: the folk dance", "name"),
    "TAIIKU/KISA23": ("Sports day: Mio Kisaragi's scene", "name"),
    "TAIIKU/KIYOTAI": ("Sports day: Nozomi Kiyokawa's scene", "name"),
    "TAIIKU/": ("Sports day (体育祭, TAIIKU overlay): event announcements", "docs"),
    "SHIAI/": ("Club practice matches (試合)", "name"),
    "TARA_OBJ/KARAKASI": ("Karaoke lyrics (DATE2 scene 92)", "docs"),
}
OVERLAY_SCENES = {
    "PSX.EXE": "Main executable: system UI (memory card, settings, clubs, calendar, name tables)",
    "NAME_ENT": "Name entry screen and the opening lyric",
    "OPTION": "Options / settings menu (OPTION overlay)",
    "ETC": "Status, club and miscellaneous screens (ETC overlay)",
    "OLH": "Exam week / study screens (OLH overlay, scene 58)",
    "TEL": "Phone calls: the phone book and call lines (TEL overlay)",
    "DATE": "Date overlay: date-spot labels and in-date UI",
    "DATE2": "Date overlay 2 (karaoke and special dates)",
    "SHUGAKU": "School trip UI",
    "SHOUGATU": "New Year (shrine, omikuji)",
    "VALEN": "Valentine's Day",
    "GEKO": "Weekly schedule / walking home",
    "KANGEI": "Welcome events (KANGEI overlay, scenes 95-96)",
    "OMIMAI": "Sick visit",
    "ENDING": "Ending and credits UI",
    "BUNKASAI": "Culture festival",
    "BUNKAKEN": "Culture festival club booths",
    "BUNKA_SD": "Culture festival stage drama",
    "TAIIKU": "Sports day",
    "RENSYU": "Club practice",
    "MASTER": "Club finals",
    "RPG_BAT": "Culture festival RPG battle mini-game",
    "EN_NICHI": "Summer festival (fair) mini-games",
    "FUKUTEST/JOHO.NBN": "Information magazine records (data file)",
}

TOKEN_READABLE = {
    "{br}": " / ", "{P}": "[PLAYER, as she addresses him]", "{G}": "[HEROINE'S GIVEN NAME]",
    "{p}": "[PLAYER'S FAMILY NAME]", "{m}": "[PLAYER'S GIVEN NAME]",
    "{F}": "[PLAYER'S FULL NAME]", "{Y}": "Yoshio", "{S}": "[RUNTIME TEXT S]",
    "{O}": "[RUNTIME TEXT O]", "{W}": "[RUNTIME TEXT W]", "{A}": "[RUNTIME TEXT A]",
    "{M}": "[RUNTIME TEXT M]", "{dst}": "[COMPOSED TEXT]",
}
TOKEN_RE = re.compile(r"\{(?:br|opt|P|G|p|m|F|Y|S|O|W|A|M|dst)\}")
JP_CHAR_RE = re.compile(r"[぀-ヿ一-鿿]")


def readable(text, kind=""):
    """control codes as plain words: {br} -> ' / ', name tokens -> [ROLE],
    {opt} -> numbered replies"""
    if text is None:
        return None
    parts = text.split("{opt}")

    def one(s):
        s = s.replace("\t", " ")
        for t, r in TOKEN_READABLE.items():
            s = s.replace(t, r)
        return re.sub(r" {2,}", " ", s).strip(" /") if s.strip() else s
    if len(parts) > 1:
        label = "Reply" if kind == "choice" else "Alt"
        return " || ".join(f"{label} {i + 1}: {one(p)}" for i, p in enumerate(parts))
    return one(text)


def tokens_in(text):
    return sorted(set(TOKEN_RE.findall(text or "")) - {"{br}"})


def short_id(sheet_id):
    """sheet ID 'assets/extracted_iso/CDROM/SERIFU/X.BIN:0xe70' -> 'SERIFU/X.BIN:0xe70'"""
    rel, _, off = sheet_id.rpartition(":")
    return f"{rel.split('CDROM/', 1)[-1]}:0x{int(off, 16):x}"


def scene_for(container):
    """(description, confidence, girl code) for 'SERIFU/DATE_AS' etc."""
    stem = container.split("/", 1)[1] if "/" in container else container
    d = container.split("/")[0]
    girl = None
    m = re.match(r"(?:DATE|EVENT|TEST)_([A-Z]{2})$", stem)
    if m and m.group(1) in GIRLS:
        girl = m.group(1)
    m = re.match(r"([A-Z]{2})_S6", stem)
    if d == "BUNKA" and m:
        girl = BUNKA_CODES.get(m.group(1), m.group(1) if m.group(1) in GIRLS else None)
    if stem in ("GASSH_FU", "BUN_FU"):
        girl = "FU"
    if stem == "KISA23":
        girl = "KI"
    if stem == "KIYOTAI":
        girl = "KY"
    for key in sorted(SCENES, key=len, reverse=True):
        if container.startswith(key):
            desc, conf = SCENES[key]
            return desc.replace("{girl}", GIRLS.get(girl, "a heroine")), conf, girl
    return f"{container} (no scene note)", "none", girl


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def run_tool(args, what):
    r = subprocess.run([sys.executable, str(locate(args[0]).relative_to(ROOT))] + args[1:], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise SystemExit(f"[jev-kit] {what} failed ({r.returncode}):\n{r.stdout[-1500:]}\n"
                         f"{r.stderr[-1500:]}")
    return r


def load_glossary():
    rows = []
    for r in read_csv(LOC / "GLOSSARY.csv"):
        jp = (r.get("Japanese") or "").strip()
        if jp:
            rows.append({"jp": jp, "en": r.get("English", ""), "category": r.get("Category", ""),
                         "notes": r.get("Notes", ""), "status": r.get("Status", "")})
    rows.sort(key=lambda g: -len(g["jp"]))
    return rows


def glossary_hits(glossary, jp):
    hits = []
    seen = set()
    for g in glossary:
        if g["jp"] in (jp or "") and g["jp"] not in seen:
            # a shorter term inside an already-matched longer one is noise
            if any(g["jp"] in s for s in seen):
                continue
            seen.add(g["jp"])
            hits.append({k: g[k] for k in ("jp", "en", "category", "notes")})
    return hits


def audit_flags():
    """the localization audits keyed by sheet ID"""
    flags = defaultdict(list)
    A = LOC / "audit"
    for p in sorted(A.glob("speaker-flags-*.csv")):
        for r in read_csv(p):
            flags[r["ID"]].append({"source": f"translation/localization/audit/{p.name}",
                                   "flag": "speaker_suspect",
                                   "detail": f"sheet says {r['Speaker']!r}, suspected "
                                             f"{r['suspected']!r}: {r['evidence']}"})
    for p in sorted(A.glob("voice-*.csv")):
        for r in read_csv(p):
            flags[r["ID"]].append({"source": f"translation/localization/audit/{p.name}",
                                   "flag": "voice_fix_applied", "detail": r.get("reason", "")})
    for p in sorted(A.glob("consistency-*.csv")):
        if "skipped" in p.name:
            continue
        for r in read_csv(p):
            flags[r["ID"]].append({"source": f"translation/localization/audit/{p.name}",
                                   "flag": "consistency_unified", "detail": r.get("reason", "")})
    for p in sorted(A.glob("glossary-*.csv")):
        for r in read_csv(p):
            flags[r["ID"]].append({"source": f"translation/localization/audit/{p.name}",
                                   "flag": "glossary_term_fixed",
                                   "detail": f"term {r.get('term', '')}"})
    return flags


# main-exe ranges that went back to Japanese on the PC port before the
# 2026-11-02 fix
BLANK_AT = set()     # (target, addr) of strings the patch blanks on purpose

BROKEN_RANGES = [((0x800B7240, 0x800B72A0), "join-club template / captain's line"),
                 ((0x800B9D90, 0x800B9E22), "club-name strings")]


# ---------------------------------------------------------------------------
# 1. script containers (inject.py)
# ---------------------------------------------------------------------------

def collect_containers(glossary, aflags, dte_path, rebuild_dte, log):
    import inject
    prof = json.loads(PROFILE.read_text())
    dirs = prof.get("containers", {}).get("dirs", inject.DEFAULT_DIRS)
    accept = prof.get("containers", {}).get("status", list(inject.ACCEPT_STATUS))
    conts = inject.load_containers(dirs, set(), set(accept), False)
    dte = None
    if dte_path.exists() and not rebuild_dte:
        dte = json.loads(dte_path.read_text())["entries"]
        log(f"containers: DTE table reused from {dte_path.relative_to(ROOT)}")
    else:
        corpus = [inject.fit_text(inject.normalise(r.en.strip()), r.kind, Counter())[0]
                  for c in conts for r in c.rows if r.translated]
        log(f"containers: building the DTE table over {len(corpus)} rows (inject.build_dte) ...")
        dte = inject.build_dte(corpus)
        dte_path.parent.mkdir(parents=True, exist_ok=True)
        dte_path.write_text(json.dumps({"entries": dte, "count": len(dte),
                                        "note": "built by build_jev_qa_kit.py with "
                                                "inject.build_dte (same as the patch build)"},
                                       indent=1) + "\n")
    choice_over = json.loads((PATCH_CONFIG / "choice_overrides.json").read_text()).get("rows", {})
    extra = json.loads((PATCH_CONFIG / "containers_extra.json").read_text())
    extra_rel = {k.split("extracted_iso/")[1]: v for k, v in extra.items()}
    groups = OrderedDict()
    sheet_counts = {}
    for c in conts:
        c.prepare(dte, None)
        c.pack()
        cdrom = c.cdrom                                   # CDROM/SERIFU/X.BIN
        container = cdrom[len("CDROM/"):].rsplit(".", 1)[0]  # SERIFU/X
        is_extra = cdrom in extra_rel
        sheet_rel = (extra_rel[cdrom]["sheet"] if is_extra else
                     str((SHEETS / (container + ".csv")).relative_to(ROOT)))
        sheet_rows = read_csv(ROOT / sheet_rel)
        n_sheet = len(sheet_rows)
        sheet_counts[container] = {"sheet": sheet_rel, "sheet_rows": n_sheet,
                                   "scanned_rows": len(c.rows) - n_sheet, "extra": is_extra}
        scanned = {id(r) for r in c.rows[n_sheet:]}   # tagged_rows.scan_container rows
        desc, conf, girl = scene_for(container)
        seq = []
        for r in sorted(c.rows, key=lambda r: r.off):
            sid = short_id(r.id)
            is_tagged = id(r) in scanned
            ships = bool(r.translated)
            en_ship = r.text if ships else None
            spk_raw = r.speaker or ""
            # speaker
            if r.tag:
                spk = {"raw": spk_raw, "name": r.speaker_en or spk_raw, "role": "npc",
                       "source": "tagged row label"}
                if r.speaker_en in NAME_TO_CODE:
                    spk["role"] = "heroine"
            elif spk_raw in NAME_TO_CODE:
                spk = {"raw": spk_raw, "name": spk_raw, "role": "heroine", "source": "sheet"}
            elif spk_raw in SPEAKER_ROLE:
                name = {"player": "Player", "player (choice)": "Player (reply menu)",
                        "other (Rei/Miharu/NPC)": "Other (Rei / Miharu / NPC)"}.get(spk_raw, spk_raw)
                spk = {"raw": spk_raw, "name": name, "role": SPEAKER_ROLE[spk_raw], "source": "sheet"}
            elif r.kind == "choice":
                spk = {"raw": "", "name": "Player (reply menu)", "role": "player",
                       "source": "row kind (choice)"}
            else:
                cand = f"{GIRLS[girl]} or the player" if girl else "unknown"
                spk = {"raw": "", "name": None, "role": "unknown", "source": "unresolved",
                       "candidates": cand}
            bible = None
            if spk["role"] == "heroine":
                bible = BIBLE_SLUG.get(spk["name"])
            elif spk["role"] == "player":
                bible = "player"
            elif spk_raw == "other (Rei/Miharu/NPC)":
                bible = "others"
            elif spk_raw == "Yoshio Saotome":
                bible = "yoshio-saotome"
            spk["bible"] = bible
            # where the English comes from / where to edit it
            ck = inject.choice_key(r.id)
            notes = list(r.notes)
            if is_tagged:
                origin = "config/patch/tagged_rows_en.json"
                edit = {"file": "config/patch/tagged_rows_en.json",
                        "key": f"rows[\"{r.id.rpartition(':')[0].split('CDROM/', 1)[-1]}:0x{r.off:x}\"]"}
            elif ck in choice_over:
                origin = "config/patch/choice_overrides.json"
                edit = {"file": "config/patch/choice_overrides.json", "key": f"rows[\"{ck}\"]",
                        "also": f"{sheet_rel} row ID={r.id} (the sheet text, overridden)"}
            elif any("choice_edits.json" in n for n in notes):
                origin = "config/patch/choice_edits.json"
                edit = {"file": "config/patch/choice_edits.json", "key": "by_text / by_id",
                        "also": f"{sheet_rel} row ID={r.id}"}
            elif is_extra:
                origin = "config/patch/overlay_drafts.json (+ overlay_drafts.d/)"
                edit = {"file": "config/patch/overlay_drafts.d/*.json",
                        "key": f"by_addr[\"{sid}\"]",
                        "note": "the sheet under build/ is generated by overlay_sheets.py --containers"}
            else:
                origin = "sheet"
                edit = {"file": sheet_rel, "key": f"ID={r.id}", "column": "English"}
            flags = []
            for n in notes:
                low = n.lower()
                if "token mismatch" in low:
                    flags.append({"source": "inject.py", "flag": "token_mismatch_kept_japanese", "detail": n})
                elif "does not fit" in low:
                    flags.append({"source": "inject.py", "flag": "no_room_kept_japanese", "detail": n})
                elif low.startswith("choice "):
                    flags.append({"source": "inject.py", "flag": "choice_too_wide", "detail": n})
                elif "speaker label" in low or "has no english" in low:
                    flags.append({"source": "inject.py", "flag": "speaker_label", "detail": n})
                elif "draft shortened" in low:
                    flags.append({"source": "inject.py", "flag": "shortened_reply_override", "detail": n})
                elif "leftover" in low:
                    flags.append({"source": "inject.py", "flag": "relocated_in_container", "detail": n})
            flags += aflags.get(r.id, [])
            en_src = (r.en or "").strip()
            if ships and en_ship and inject.normalise(en_src).replace("{br}", " ").split() != \
                    en_ship.replace("{br}", " ").split():
                flags.append({"source": "inject.py", "flag": "reflowed_or_overridden",
                              "detail": "the shipped text differs from the sheet beyond line breaks"})
            # constraints
            cons = {"retail_slot_bytes": r.slot, "max_bytes_sheet": r.maxbytes}
            if ships and r.enc is not None:
                cons["encoded_bytes_with_dte"] = len(r.enc) - 1
            if r.kind == "choice":
                reps = (en_ship or en_src).split("{opt}") if (en_ship or en_src) else []
                cons.update({"box": "reply menu", "max_px_per_row": inject.CHOICE_PX,
                             "rows_per_reply": inject.CHOICE_ROWS_PER_REPLY if len(reps) <= 2 else 1,
                             "rows_per_menu": max(inject.CHOICE_ROWS_PER_MENU, len(reps)),
                             "reply_px": [inject.line_width(x) for x in reps],
                             "char_budget_per_reply": 32})
            else:
                rows = (en_ship or "").split("{opt}")[0].split("{br}") if en_ship else []
                cons.update({"box": "event message window" if r.kind != "alternatives" else
                             "event message window (one alternative is picked)",
                             "max_px_per_row": inject.LINE_PX, "rows_per_page": 3,
                             "scrolls": True, "rows": len(rows),
                             "widest_row_px": max((inject.line_width(x) for x in rows), default=0),
                             "char_budget_per_row": 32})
            rec = {
                "id": sid, "source_kind": "container_tagged" if is_tagged else "container_sheet",
                "sheet_id": r.id, "group": container.split("/")[0], "container": container,
                "offset": f"0x{r.off:x}",
                "scene": {"container": container, "description": desc, "confidence": conf,
                          "girl": GIRLS.get(girl), "girl_code": girl,
                          "event": None, "location": None, "date": None},
                "speaker": spk, "kind": "tagged" if is_tagged else r.kind,
                "jp": r.jp, "jp_readable": readable(r.jp, r.kind),
                "en_source": en_src or None, "en": en_ship,
                "en_readable": readable(en_ship, r.kind) if en_ship else None,
                "en_origin": origin, "edit": edit,
                "status": r.status, "status_class": status_class(r.status),
                "sheet_notes": None, "tokens": tokens_in(r.jp),
                "constraints": cons, "flags": flags, "ships": ships,
            }
            if not ships:
                if not en_src:
                    why = "no English yet (untranslated)"
                elif any("token mismatch" in n for n in notes):
                    why = "token mismatch: kept Japanese"
                elif any("does not fit" in n for n in notes):
                    why = "no room in the container: kept Japanese"
                elif en_src == r.jp:
                    why = "token-only / script-node row (English equals the Japanese)"
                elif r.status not in accept:
                    why = f"status {r.status!r} not accepted by the build"
                else:
                    why = "immutable slot (script-node word / 1-byte string): never rewritten"
                rec["not_shipped_why"] = why
            seq.append(rec)
        groups[container] = seq
    # sheet notes (Row does not keep them)
    for container, seq in groups.items():
        p = ROOT / sheet_counts[container]["sheet"]
        if p.exists():
            notes = {short_id(r["ID"]): r.get("Notes", "") for r in read_csv(p)}
            for rec in seq:
                rec["sheet_notes"] = notes.get(rec["id"]) or None
    return groups, dte, sheet_counts


def status_class(st):
    st = (st or "").lower()
    if st in ("final", "qa"):
        return "final"
    if st in ("edited", "translated"):
        return "edited"
    if st == "draft":
        return "draft"
    if st == "engineering":
        return "engineering"
    return st or "unknown"


# ---------------------------------------------------------------------------
# 2. overlay / main / data-file strings (ui_strings.py, overlay_sheets.py)
# ---------------------------------------------------------------------------

def draft_fragment_index():
    idx = {}
    frags = [PATCH_CONFIG / "overlay_drafts.json"] + \
        sorted((PATCH_CONFIG / "overlay_drafts.d").glob("*.json"))
    for f in frags:
        d = json.loads(f.read_text())
        for kind in ("by_addr", "by_text"):
            for k in d.get(kind, {}):
                idx.setdefault((kind, k), str(f.relative_to(ROOT)))
    return idx


def ui_table_of(target, addr):
    import ui_strings
    for name, table in ui_strings.TABLES.items():
        if name == target and addr in table:
            return name
    for ov, t in ui_strings.SPEAKERS.items():
        if ov == target and addr in t:
            return f"SPEAKERS[{ov!r}]"
    return target


def collect_strings(glossary, dte, log):
    import ui_strings
    import overlay_sheets
    dte_arg = str((GEN / "dte.json").relative_to(ROOT))
    r = run_tool(["tools/patch/ui_strings.py", "--dte", dte_arg, "--out",
                  "build/patch/gen/ui_strings.json"], "ui_strings.py")
    log("ui_strings: " + (r.stdout.strip().splitlines() or ["?"])[-1])
    r = run_tool(["tools/patch/overlay_sheets.py", "--dte", dte_arg, "--out",
                  "build/patch/gen/overlay_sheets.json"], "overlay_sheets.py")
    log("overlay_sheets: " + (r.stdout.strip().splitlines() or ["?"])[-2:][0])
    ui = json.loads((GEN / "ui_strings.json").read_text())
    ovs = json.loads((GEN / "overlay_sheets.json").read_text())
    prof = json.loads(PROFILE.read_text())
    by_text, by_addr = overlay_sheets.load_drafts()
    frag_idx = draft_fragment_index()
    images = {}

    def image(target):
        if target not in images:
            images[target] = ui_strings.load_target(target)
        return images[target]

    def rel_of(target):
        return "PSX.EXE" if target == "main" else f"EXEDIR/{target}.EXN"

    def jp_at(target, addr):
        data, base = image(target)
        off = addr - base
        e = data.find(b"\0", off)
        try:
            import tagged_rows
            return tagged_rows.retail_to_sheet(data[off:e])
        except Exception:
            return data[off:e].decode("shift_jis", "replace")

    def deref(target, ptr_at):
        data, base = image(target)
        return struct.unpack_from("<I", data, ptr_at - base)[0]

    # draft-sheet rows by (rel, offset) for the full Japanese and the origin
    draft_rows = {}
    for sheet in sorted(overlay_sheets.SHEETS.rglob("*.csv")):
        rel = str(sheet.relative_to(overlay_sheets.SHEETS))[:-4]
        for row in read_csv(sheet):
            draft_rows[(rel, int(row["Offset"], 16))] = row
    lines = OrderedDict()                           # id -> record

    def add(target_rel, off, addr, en, jp, origin, edit, kind, status, cons, extra_flags=()):
        lid = f"{target_rel}:0x{off:x}"
        if lid in lines:
            return
        if not (en or "").strip():
            # an explicit "" draft: a joiner the patch blanks on purpose
            # (the English of the neighbouring piece carries it)
            BLANK_AT.add(("main" if target_rel == "PSX.EXE" else Path(target_rel).stem, addr))
            return
        ov = Path(target_rel).stem if target_rel.endswith(".EXN") else None
        scene_key = ov if ov else ("PSX.EXE" if target_rel == "PSX.EXE" else target_rel.replace("CDROM/", ""))
        desc = OVERLAY_SCENES.get(scene_key, f"{scene_key} strings")
        flags = list(extra_flags)
        if target_rel == "PSX.EXE" and addr is not None:
            for (a0, a1), what in BROKEN_RANGES:
                if a0 <= addr < a1:
                    flags.append({"source": "docs/translation/BROKEN-STRINGS-AUDIT.md",
                                  "flag": "pc_boot_overwrite_fixed",
                                  "detail": f"{what}: went back to Japanese on the PC port "
                                            f"until the 2026-11-02 fix; check it on screen"})
        if en and JP_CHAR_RE.search(en):
            flags.append({"source": "kit", "flag": "japanese_in_english",
                          "detail": "the shipped English still holds Japanese characters"})
        lines[lid] = {
            "id": lid, "source_kind": kind, "sheet_id": None,
            "group": "EXEDIR" if ov else ("PSX.EXE" if target_rel == "PSX.EXE" else target_rel.split("/")[1]),
            "container": target_rel, "offset": f"0x{off:x}",
            "addr": f"0x{addr:08X}" if addr is not None else None,
            "scene": {"container": target_rel, "description": desc, "confidence": "docs",
                      "girl": None, "girl_code": None, "event": None, "location": None, "date": None},
            "speaker": {"raw": "", "name": "UI / system text", "role": "ui", "source": "string kind",
                        "bible": None},
            "kind": "ui", "jp": jp, "jp_readable": readable(jp),
            "en_source": en, "en": en, "en_readable": readable(en),
            "en_origin": origin, "edit": edit, "status": status,
            "status_class": status_class(status), "sheet_notes": None,
            "tokens": tokens_in(jp), "constraints": cons, "flags": flags, "ships": True,
        }

    # (a) the profile's own strings (config/patch/english.json)
    targets = [("main", prof.get("main", {}).get("strings", []))] + \
        [(ov, spec.get("strings", [])) for ov, spec in prof.get("overlays", {}).items()]
    blanks = 0
    for target, lst in targets:
        for i, s in enumerate(lst):
            text = s.get("text", "")
            if not text.strip():
                blanks += 1
                BLANK_AT.add((target, int(s["addr"], 16) if "addr" in s
                              else deref(target, int(s["ptr_at"], 16))))
                continue
            if "addr" in s:
                addr = int(s["addr"], 16)
                cons = {"slot_bytes": s.get("max_bytes"), "placement": "in place"}
            else:
                addr = deref(target, int(s["ptr_at"], 16))
                cons = {"placement": "relocated (string pool, no size limit)",
                        "pointer_word": s["ptr_at"]}
            data, base = image(target)
            sect = "main.strings" if target == "main" else f"overlays.{target}.strings"
            add(rel_of(target), addr - base, addr, text, jp_at(target, addr),
                "config/patch/english.json",
                {"file": "config/patch/english.json", "key": f"{sect}[{i}] ({s.get('addr') or 'ptr_at ' + s['ptr_at']})"},
                "profile_string", "engineering", cons)
    # (b) ui_strings.py
    for target, lst in [("main", ui.get("main", []))] + list(ui.get("overlays", {}).items()):
        for s in lst:
            text = s.get("text", "")
            if not text.strip():
                blanks += 1
                BLANK_AT.add((target, int(s["addr"], 16) if "addr" in s
                              else deref(target, int(s["ptr_at"], 16))))
                continue
            if "addr" in s:
                addr = int(s["addr"], 16)
                cons = {"slot_bytes": s.get("max_bytes"),
                        "placement": "module string" if s.get("module") else "in place"}
            else:
                addr = deref(target, int(s["ptr_at"], 16))
                cons = {"placement": "relocated (string pool, no size limit)",
                        "pointer_word": s["ptr_at"]}
            data, base = image(target)
            add(rel_of(target), addr - base, addr, text, jp_at(target, addr),
                "tools/patch/ui_strings.py",
                {"file": "tools/patch/ui_strings.py", "key": f"{ui_table_of(target, addr)}[0x{addr:08X}]"},
                "ui_string", "engineering", cons)
    # (c) overlay_sheets.py (draft sheets + overlay_drafts + editor sheets)
    for target, lst in [("main", ovs.get("main", []))] + list(ovs.get("overlays", {}).items()):
        data, base = image(target)
        rel = rel_of(target)
        for s in lst:
            if "addr" in s:
                addr = int(s["addr"], 16)
                cons = {"slot_bytes": s.get("max_bytes"),
                        "placement": "module string" if s.get("module") else "in place"}
            else:
                addr = deref(target, int(s["ptr_at"], 16))
                cons = {"placement": "relocated (string pool, no size limit)",
                        "pointer_word": s["ptr_at"]}
            off = addr - base
            row = draft_rows.get((rel, off))
            jp = row["Japanese"] if row else jp_at(target, addr)
            origin, edit = string_origin(rel, off, row, by_text, by_addr, frag_idx, overlay_sheets)
            add(rel, off, addr, s.get("text", ""), jp, origin, edit, "overlay_string", "draft", cons)
    for cdrom, lst in ovs.get("files", {}).items():
        rel = cdrom[len("CDROM/"):]
        for s in lst:
            off = int(s["offset"], 16)
            row = draft_rows.get((rel, off))
            jp = row["Japanese"] if row else s.get("note", "")
            origin, edit = string_origin(rel, off, row, by_text, by_addr, frag_idx, overlay_sheets)
            add(cdrom, off, None, s.get("text", ""), jp, origin, edit, "file_string", "draft",
                {"slot_bytes": s.get("max_bytes"), "placement": "in place (data file)"})
    rep = json.loads((GEN / "overlay_sheets.report.json").read_text())
    not_shipped = [{"id": f"{o['source']}:{o['offset']}", "why": "does not fit its slot",
                    "en": o["text"], "jp": o["japanese"]} for o in rep.get("overflow", [])]
    not_shipped += [{"id": f"{u['source']}:{u['offset']}", "why": u["class"], "jp": u["japanese"]}
                    for u in rep.get("rows_without_english", []) if u["class"] == "untranslated_visible"]
    # neighbours are by offset inside one file
    groups = defaultdict(list)
    for rec in lines.values():
        groups[rec["container"]].append(rec)
    out = OrderedDict()
    for k in sorted(groups):
        out[k] = sorted(groups[k], key=lambda r: int(r["offset"], 16))
    return out, not_shipped, blanks


def string_origin(rel, off, row, by_text, by_addr, frag_idx, overlay_sheets):
    editor = overlay_sheets.EDITOR / (rel + ".csv")
    if editor.exists():
        for e in read_csv(editor):
            if int(e["Offset"], 16) == off and (e.get("English") or "").strip():
                return ("editor sheet", {"file": str(editor.relative_to(ROOT)),
                                         "key": f"ID={e['ID']}", "column": "English"})
    k = f"{rel}:0x{off:x}"
    if k in by_addr:
        return ("overlay_drafts by_addr", {"file": frag_idx.get(("by_addr", k), "config/patch/overlay_drafts.d/"),
                                           "key": f"by_addr[\"{k}\"]"})
    jp = row["Japanese"] if row else None
    if jp and jp in by_text:
        return ("overlay_drafts by_text (shared by every copy of this Japanese)",
                {"file": frag_idx.get(("by_text", jp), "config/patch/overlay_drafts.d/"),
                 "key": f"by_text[{jp!r}]"})
    return ("auto (full-width digits transliterated)", {"file": "tools/patch/overlay_sheets.py",
                                                         "key": "FW_DIGITS"})


# ---------------------------------------------------------------------------
# 3. art lettering
# ---------------------------------------------------------------------------

def collect_art():
    out = OrderedDict()
    for man in sorted((ART).glob("*/manifest.json")):
        d = json.loads(man.read_text())
        name = man.parent.name
        recs = []
        seen = set()
        items = [("cells", i, c) for i, c in enumerate(d.get("cells", []))]
        for fi, fr in enumerate(d.get("sprite_frames", {}).get("frames", []) or []):
            for si, sg in enumerate(fr.get("segs", [])):
                items.append((f"sprite_frames.frames[{fi}].segs", si, sg))
        for where, i, c in items:
            text = (c.get("text") or "").strip()
            if not text:
                continue
            key = (text, c.get("jp", ""))
            if key in seen:
                continue
            seen.add(key)
            cname = c.get("name") or f"{where}[{i}]"
            lid = f"ART/{name}:{cname}"
            recs.append({
                "id": lid, "source_kind": "art", "sheet_id": None, "group": "ART",
                "container": f"ART/{name}", "offset": None, "addr": None,
                "scene": {"container": d.get("file"), "description": (d.get("note") or "")[:400],
                          "confidence": "docs", "girl": None, "girl_code": None,
                          "event": None, "location": None, "date": None},
                "speaker": {"raw": "", "name": "Art lettering", "role": "ui", "source": "art",
                            "bible": None},
                "kind": "art", "jp": c.get("jp", ""), "jp_readable": c.get("jp", ""),
                "en_source": text, "en": text, "en_readable": text,
                "en_origin": "art manifest",
                "edit": {"file": str(man.relative_to(ROOT)), "key": f"{where}[{i}] name={cname}"},
                "status": "engineering", "status_class": "engineering", "sheet_notes": None,
                "tokens": [], "constraints": {"cell_px": [c.get("w"), c.get("h")]},
                "flags": [], "ships": True,
            })
        out[f"ART/{name}"] = recs
    return out


# ---------------------------------------------------------------------------
# 4. compositions (sample renderings from the shipped pieces)
# ---------------------------------------------------------------------------

def collect_compositions(string_groups):
    import ui_strings
    spec = json.loads((PATCH_CONFIG / "compositions.json").read_text())
    en_at = {}
    for recs in string_groups.values():
        for r in recs:
            if r.get("addr"):
                tgt = "main" if r["container"] == "PSX.EXE" else Path(r["container"]).stem
                en_at[(tgt, int(r["addr"], 16))] = r["en"]
                if r["constraints"].get("pointer_word"):
                    en_at[(tgt, "ptr", int(r["constraints"]["pointer_word"], 16))] = r["en"]
    for t, a in BLANK_AT:
        en_at.setdefault((t, a), "")
    samples = {"p_sei": "Tanaka", "p_mei": "Taro", "p_adana": "Taro", "girl_given": "Shiori",
               "girl_family": "Fujisaki", "girl_full": "Shiori Fujisaki", "digits": "3"}
    jp_samples = {"p_sei": "田中", "p_mei": "太郎", "p_adana": "タロー", "girl_given": "詩織",
                  "girl_family": "藤崎", "girl_full": "藤崎詩織", "digits": "３"}
    images = {}

    def image(t):
        if t not in images:
            images[t] = ui_strings.load_target(t)
        return images[t]

    def raw_jp(t, addr):
        data, base = image(t)
        off = addr - base
        return data[off:data.find(b"\0", off)].decode("shift_jis", "replace")

    def tgt_of(comp, addr):
        ov = comp.get("ov")
        return ov if ov and OV_BASE <= addr < OV_BASE + 192 * 1024 else "main"

    def word(t, addr):
        data, base = image(t)
        return struct.unpack_from("<I", data, addr - base)[0]

    def piece(comp, p, english):
        if "s" in p:
            a = int(p["s"], 16)
            t = tgt_of(comp, a)
            return [en_at.get((t, a), raw_jp(t, a)) if english else raw_jp(t, a)]
        if "t" in p:
            base = int(p["t"], 16)
            t = tgt_of(comp, base)
            idx = p.get("pick", range(int(p.get("n", 1))))
            out = []
            for i in list(idx)[:3]:
                w = base + 4 * i
                tgt_addr = word(t, w)
                if english:
                    out.append(en_at.get((t, "ptr", w)) or en_at.get((t, tgt_addr)) or raw_jp(t, tgt_addr))
                else:
                    out.append(raw_jp(t, tgt_addr))
            return out
        if "rec" in p:
            base, stride = int(p["rec"], 16), int(p["stride"])
            t = tgt_of(comp, base)
            out = []
            for i in list(p.get("pick", range(int(p.get("n", 1)))))[:3]:
                a = base + i * stride
                data, b0 = image(t)
                jp = data[a - b0:a - b0 + stride].split(b"\0")[0].decode("shift_jis", "replace")
                out.append(en_at.get((t, a), jp) if english else jp)
            return out
        if "v" in p:
            name = p["v"]
            if name in spec.get("vars", {}):
                return [str(x) for x in spec["vars"][name][:2]]
            if name in ("club", "place"):
                base = 0x800B9DF4 if name == "club" else 0x800B9918
                out = []
                for i in range(2):
                    a = word("main", base + 4 * i)
                    out.append(en_at.get(("main", a), raw_jp("main", a)) if english else raw_jp("main", a))
                return out
            return [(samples if english else jp_samples).get(name, f"[{name}]")]
        if "lit" in p:
            return [p["lit"]]
        if "fmt" in p:
            a = int(p["fmt"], 16)
            t = tgt_of(comp, a)
            fmt = en_at.get((t, a), raw_jp(t, a)) if english else raw_jp(t, a)
            args = [piece(comp, x, english)[0] for x in p.get("args", [])]
            segs = re.split(r"%[-0-9]*[sd]", fmt)
            out = segs[0]
            for i, seg in enumerate(segs[1:]):
                out += (args[i] if i < len(args) else "[?]") + seg
            return [out]
        return ["[?]"]

    def render(comp, pieces, english):
        acc = ""
        for p in pieces:
            v = piece(comp, p, english)[0]
            if "{dst}" in v:
                before, _, after = v.partition("{dst}")
                acc = before + acc + after.replace("{dst}", "")
            else:
                acc += (" " if comp.get("row") and acc and english else "") + v
        return acc

    recs = []
    for comp in spec.get("compositions", []):
        alts = comp.get("alts") or [comp.get("pieces", [])]
        seen_render = set()
        for ai, pieces in enumerate(alts[:6]):
            try:
                en = render(comp, pieces, True)
                jp = render(comp, pieces, False)
                err = None
            except Exception as e:                       # noqa: BLE001
                en, jp, err = None, None, f"{type(e).__name__}: {e}"
            if not en or (en, jp) in seen_render:
                continue
            seen_render.add((en, jp))
            lid = f"COMPOSED/{comp['id']}#{ai}"
            ov = comp.get("ov")
            flags = [{"source": "kit", "flag": "composition_sample",
                      "detail": "a sample rendering with sample names/values; the pieces are "
                                "separate lines; review how they join"}]
            if err:
                flags.append({"source": "kit", "flag": "render_error", "detail": err})
            if JP_CHAR_RE.search(en):
                flags.append({"source": "kit", "flag": "japanese_in_english",
                              "detail": "a piece of this composition has no English"})
            recs.append({
                "id": lid, "source_kind": "composition", "sheet_id": None, "group": "COMPOSED",
                "container": f"COMPOSED/{ov or 'main'}", "offset": None, "addr": None,
                "scene": {"container": comp.get("src"), "description": comp.get("note", ""),
                          "confidence": "docs", "girl": None, "girl_code": None,
                          "event": None, "location": None, "date": None},
                "speaker": {"raw": "", "name": "UI / composed text", "role": "ui",
                            "source": "composition", "bible": None},
                "kind": "composition", "jp": jp, "jp_readable": readable(jp),
                "en_source": en, "en": en, "en_readable": readable(en),
                "en_origin": "composed at run time from the pieces",
                "edit": {"file": "config/patch/compositions.json", "key": f"id={comp['id']}",
                         "note": "fix the wording in the PIECES (their own lines); the composition "
                                 "only describes how the game joins them"},
                "status": "engineering", "status_class": "engineering", "sheet_notes": None,
                "tokens": [], "constraints": {"max_px": comp.get("max_px"), "buf_bytes": comp.get("buf")},
                "flags": flags, "ships": True,
            })
    return {"COMPOSED": recs}


# ---------------------------------------------------------------------------
# neighbours, glossary, manifest
# ---------------------------------------------------------------------------

def attach_context(groups, glossary):
    for gname, seq in groups.items():
        n = len(seq)
        for i, rec in enumerate(seq):
            def nb(j):
                o = seq[j]
                return {"id": o["id"],
                        "speaker": o["speaker"].get("name") or o["speaker"].get("candidates"),
                        "kind": o["kind"], "jp": o["jp"], "en": o["en"]}
            rec["seq"] = {"group": gname, "index": i, "of": n}
            rec["neighbours"] = {"prev": [nb(j) for j in range(max(0, i - NEIGHBOURS), i)],
                                 "next": [nb(j) for j in range(i + 1, min(n, i + 1 + NEIGHBOURS))]}
            rec["glossary_hits"] = glossary_hits(glossary, rec["jp"]) if rec["kind"] != "art" else []


def manifest_of(lines, not_shipped, sheet_counts, extra):
    by = lambda f: dict(sorted(Counter(f(r) for r in lines).items(), key=lambda kv: (-kv[1], str(kv[0]))))
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_lines": len(lines),
        "by_source_kind": by(lambda r: r["source_kind"]),
        "by_group": by(lambda r: r["group"]),
        "by_container": by(lambda r: r["container"]),
        "by_girl": by(lambda r: r["scene"]["girl"] or "(none)"),
        "by_speaker_role": by(lambda r: r["speaker"]["role"]),
        "by_status": by(lambda r: r["status"]),
        "by_status_class": by(lambda r: r["status_class"]),
        "by_kind": by(lambda r: r["kind"]),
        "lines_with_flags": sum(1 for r in lines if r["flags"]),
        "not_shipped": {"count": len(not_shipped),
                        "by_reason": dict(Counter(n["why"] for n in not_shipped))},
        "sheets": sheet_counts,
        **extra,
    }


def split_bible(dst):
    """CHARACTER-BIBLE.md -> context/characters/<slug>.md (verbatim rows)"""
    text = (LOC / "CHARACTER-BIBLE.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    head = [l for l in lines if l.startswith("| Code") or l.startswith("|---")][:2]
    shared = text[text.index("## Forms of address"):] if "## Forms of address" in text else ""
    out = {}
    for l in lines:
        if not l.startswith("| ") or l.startswith("| Code") or l.startswith("|---"):
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        code, name = cells[0], cells[1]
        if code in GIRLS:
            slug = BIBLE_SLUG[GIRLS[code]]
            title = GIRLS[code]
        elif code == "OT":
            slug, title = "others", "Other characters (Rei Ijuin, Miharu Tatebayashi, NPCs)"
        elif "Yoshio" in name:
            slug, title = "yoshio-saotome", "Yoshio Saotome"
        elif "player" in name:
            slug, title = "player", "The player"
        else:
            continue
        body = [f"# {title}", "",
                "Verbatim row of translation/localization/CHARACTER-BIBLE.md (v0.1):", "",
                *head, l, "",
                f"- Role: {cells[2]}", f"- Japanese voice: {cells[3]}",
                f"- English voice (defaults): {cells[4]}", "", shared]
        (dst / f"{slug}.md").write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        out[slug] = {"title": title, "role": cells[2], "japanese_voice": cells[3],
                     "english_voice": cells[4], "code": code}
    return out


def write_context(kit, lines):
    ctx = kit / "context"
    (ctx / "characters").mkdir(parents=True, exist_ok=True)
    bibles = split_bible(ctx / "characters")
    (ctx / "characters" / "index.json").write_text(json.dumps(bibles, indent=1, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
    for name in ("CHARACTER-BIBLE.md", "STYLE-GUIDE.md", "GLOSSARY.csv", "VOICE-NOTES-ADOPTION.md",
                 "CONTROL-CODES.md", "WORKFLOW.md"):
        shutil.copy(LOC / name, ctx / name)
    (ctx / "audit").mkdir(exist_ok=True)
    for p in sorted((LOC / "audit").glob("*")):
        shutil.copy(p, ctx / "audit" / p.name)
    notes = ctx / "notes"
    notes.mkdir(exist_ok=True)
    for rel in ("docs/translation/PS1-PATCH-STATUS.md", "docs/translation/BROKEN-STRINGS-AUDIT.md",
                "docs/translation/VISUAL-SWEEP.md", "docs/translation/TEXT-DRAW-INVENTORY.md",
                "docs/game-flows/README.md", "docs/game-flows/07-date-scenes.md",
                "docs/game-flows/16-seasonal-events.md", "docs/game-flows/10-endings.md",
                "docs/game-flows/15-phone-calls-tel.md"):
        p = locate(rel)
        if p.exists():
            shutil.copy(p, notes / p.name)
    # style-guide excerpts the questions inline (section by heading number)
    sg = (LOC / "STYLE-GUIDE.md").read_text(encoding="utf-8")
    secs = {}
    for m in re.finditer(r"^## (\d+)\. ([^\n]+)\n(.*?)(?=^## |\Z)", sg, re.S | re.M):
        secs[m.group(1)] = f"## {m.group(1)}. {m.group(2)}\n{m.group(3).strip()}\n"
    (ctx / "style_excerpts.json").write_text(json.dumps({
        "voice_principles": secs.get("2", ""), "names_honorifics": secs.get("3", ""),
        "mechanics": secs.get("4", ""), "consistency": secs.get("5", ""),
        "dos_donts": secs.get("6", ""),
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # scene index
    scenes = OrderedDict()
    for r in lines:
        c = r["container"]
        s = scenes.setdefault(c, {"container": c, "description": r["scene"]["description"],
                                  "confidence": r["scene"]["confidence"], "girl": r["scene"]["girl"],
                                  "lines": 0, "edit_file": r["edit"]["file"]})
        s["lines"] += 1
    (ctx / "scene_index.json").write_text(json.dumps(scenes, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    md = ["# Scene index", "", "Container -> what scene it is. `confidence`: `docs` = stated in the "
          "repo's docs, `name` = inferred from the file name and its lines (verify in game).", "",
          "| container | lines | girl | scene | confidence |", "|---|---:|---|---|---|"]
    for s in scenes.values():
        md.append(f"| `{s['container']}` | {s['lines']} | {s['girl'] or ''} | "
                  f"{s['description'].replace('|', '/')[:160]} | {s['confidence']} |")
    (ctx / "SCENE-INDEX.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def collect(rebuild_dte=False, log=print):
    for need in (DECOMP / "assets/extracted_iso/CDROM", DECOMP / "assets/overlays",
                 DECOMP / "disks/SLPS_000.65"):
        if not need.exists():
            raise SystemExit(f"[jev-kit] {_rel(need)} missing: the kit reads the "
                             f"player's extracted disc like the patch build does")
    sheets_dir = GEN / "sheets"
    if not sheets_dir.exists() or not any(sheets_dir.rglob("*.csv")):
        log("draft sheets missing: text_sources.py --draft-sheets (~40 s)")
        run_tool(["tools/patch/text_sources.py", "--draft-sheets", "--quiet"], "text_sources.py")
    run_tool(["tools/patch/overlay_sheets.py", "--containers"], "overlay_sheets.py --containers")
    glossary = load_glossary()
    aflags = audit_flags()
    cont_groups, dte, sheet_counts = collect_containers(glossary, aflags, GEN / "dte.json",
                                                        rebuild_dte, log)
    str_groups, str_not_shipped, blanks = collect_strings(glossary, dte, log)
    art_groups = collect_art()
    comp_groups = collect_compositions(str_groups)
    groups = OrderedDict()
    groups.update(cont_groups)
    groups.update(str_groups)
    groups.update(art_groups)
    groups.update(comp_groups)
    # neighbours over the whole sequence (kept-Japanese rows included, with en null)
    attach_context(groups, glossary)
    lines, not_shipped = [], list(str_not_shipped)
    for g in groups.values():
        for rec in g:
            if rec["ships"] and rec["en"]:
                lines.append(rec)
            else:
                not_shipped.append({"id": rec["id"], "why": rec.get("not_shipped_why") or "no English",
                                    "jp": rec["jp"], "en": rec.get("en_source")})
    ids = Counter(r["id"] for r in lines)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        raise SystemExit(f"[jev-kit] duplicate line ids: {dup[:5]}")
    return lines, not_shipped, sheet_counts, {"profile_blank_strings_skipped": blanks}


def check_counts(lines, not_shipped, sheet_counts):
    """every row of every injected container's sheet (and every scanned
    tagged row) is accounted for exactly once, shipped or not shipped, and
    every container the profile injects is in the kit.  Returns the list of
    problems (empty = consistent)."""
    import inject
    probs = []
    shipped = Counter(r["container"] for r in lines if r["source_kind"].startswith("container"))
    kept = Counter(n["id"].rsplit(":", 1)[0].rsplit(".", 1)[0] for n in not_shipped)
    for c, info in sheet_counts.items():
        want = info["sheet_rows"] + info["scanned_rows"]
        got = shipped[c] + kept[c]
        if want != got:
            probs.append(f"{c}: sheet {info['sheet_rows']} + scanned {info['scanned_rows']} rows = "
                         f"{want}, kit has {shipped[c]} shipped + {kept[c]} not shipped = {got}")
    prof = json.loads(PROFILE.read_text())
    dirs = set(prof.get("containers", {}).get("dirs", inject.DEFAULT_DIRS))
    for rel in json.loads(CONTAINERS.read_text()):
        cdrom = rel.split("CDROM/", 1)[1]
        if cdrom.split("/")[0] in dirs and cdrom.rsplit(".", 1)[0] not in sheet_counts:
            probs.append(f"{cdrom}: injected by the profile but missing from the kit")
    ids = Counter(r["id"] for r in lines)
    probs += [f"{k}: {v} copies" for k, v in ids.items() if v > 1]
    return probs


def build(out=OUT, zip_it=True, rebuild_dte=False, selftest=False, log=print):
    t0 = time.time()
    lines, not_shipped, sheet_counts, extra = collect(rebuild_dte, log)
    probs = check_counts(lines, not_shipped, sheet_counts)
    if probs:
        raise SystemExit("[jev-kit] count check failed:\n  " + "\n  ".join(probs[:20]))
    kit = out / KIT_NAME
    out.mkdir(parents=True, exist_ok=True)
    # build/** is ignored except README.md files; the kit has several and
    # holds game script, so nothing under the output may ever be staged
    (out / ".gitignore").write_text("# generated: the Jev QA kit holds game script; never commit\n*\n")
    if kit.exists():
        shutil.rmtree(kit)
    shutil.copytree(TEMPLATE, kit, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "out",
                                                                 "calibration", "results",
                                                                 "thresholds.calibrated.json"))
    # kept under another name in the repo (a file called REPORT.md reads as
    # a generated report there); the kit's docs refer to docs/REPORT.md
    (kit / "docs" / "READING-THE-QUEUE.md").rename(kit / "docs" / "REPORT.md")
    (kit / "data").mkdir(exist_ok=True)
    with open(kit / "data" / "lines.jsonl", "w", encoding="utf-8") as fh:
        for r in lines:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(kit / "data" / "not_shipped.jsonl", "w", encoding="utf-8") as fh:
        for r in not_shipped:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    man = manifest_of(lines, not_shipped, sheet_counts, extra)
    try:
        man["repo_commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                            capture_output=True, text=True).stdout.strip()
    except OSError:
        man["repo_commit"] = None
    (kit / "data" / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
    write_context(kit, lines)
    log(f"[jev-kit] {len(lines)} shipped lines ({len(not_shipped)} not shipped) -> "
        f"{(kit / 'data' / 'lines.jsonl').relative_to(ROOT)}")
    if selftest:
        r = subprocess.run([sys.executable, str(kit / "runner" / "selftest.py")], cwd=kit,
                           capture_output=True, text=True)
        (kit / "SELFTEST-OUTPUT.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        log(r.stdout.strip())
        if r.returncode != 0:
            raise SystemExit(f"[jev-kit] selftest failed:\n{r.stderr[-2000:]}")
    zpath = None
    if zip_it:
        zpath = out / f"{KIT_NAME}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(kit.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    z.write(p, Path(KIT_NAME) / p.relative_to(kit))
        log(f"[jev-kit] {zpath.relative_to(ROOT)} ({zpath.stat().st_size / 1e6:.1f} MB) "
            f"in {time.time() - t0:.0f} s")
    return kit, zpath, man


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--rebuild-dte", action="store_true",
                    help="rebuild build/patch/gen/dte.json even when it exists")
    ap.add_argument("--selftest", action="store_true",
                    help="run the kit's runner/selftest.py (mock backend) before zipping")
    a = ap.parse_args()
    build(Path(a.out), zip_it=not a.no_zip, rebuild_dte=a.rebuild_dte, selftest=a.selftest)


if __name__ == "__main__":
    main()
