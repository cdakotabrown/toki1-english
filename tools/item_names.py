#!/usr/bin/env python3
"""item_names.py - ONE table of record for the names the game repeats in
many tables (gift names, club names, date-spot names), and the generator of
the English of every copy.

The same item is spelled in several binaries: a gift is a reply of the
birthday gift menu (SERIFU/G_BIRTH), a record of GEKO's {A} table ("Okay,
I'll give her {A}."), of BUNKAKEN's / BUNKASAI's festival gift table, of the
DATE / DATE2 / KANGEI / MASTER / SHUGAKU / SHOUGATU copies; a date spot is
an entry of the main table D_800B9918 (menus, the phone date picker), a DATE
banner, a GEKO meeting spot ("Meet at {M}, okay?"); a club is the main
table D_800B9DF4 (album card, club menus) and the X部 strings of GEKO's {M}
table ("Come hang out at {M}."), KANGEI ("{A} Secret Art"), JOHO.NBN.  The
first drafts spelled them independently ("Pierced earrings" in the menu,
"Earrings" in the sentence; "Ice Rink" / "Skating rink"; "Brass Band" /
"Brass band").

Records (the strings already chosen):
  gifts   the gift menu replies of SERIFU/G_BIRTH (sheet English, or the
          row of config/patch/choice_overrides.json), read at run time;
  places  PLACES below (the main date-spot table's labels, Title Case);
  clubs   CLUBS below (the main club table's labels; X部 takes the same
          label: KANGEI / JOHO.NBN keep 8- and 11-byte slots).
Forms:
  label   the record itself, for every copy whose Japanese IS the item
          -- tables, menus, banners: one by_addr entry per copy, found by
          matching the record against every row of the draft sheets
          (build/patch/gen/sheets, read from the player's disc) that no
          other fragment's by_addr already names;
  phrase  the record as a noun phrase for the tables a script token puts
          inside a sentence (by_addr): "a classical CD", "the Literature
          Club", "the aquarium entrance".
Output: config/patch/overlay_drafts.d/items.json (generated, committed;
draft_check.py fits it, overlay_sheets.py places it).  It is keyed by
address only and holds no Japanese (the public tree carries no retail text,
D4(a)): the gift names come from the disc at run time.  --check regenerates
in memory and fails when the committed file differs (the build's text
gates run it), so a menu edit cannot leave the sentence spelling behind.

  python3 tools/patch/item_names.py            # write items.json
  python3 tools/patch/item_names.py --check    # exit 1 when stale
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT, SHEETS, PATCH_CONFIG  # noqa: E402  (this checkout, either layout)
from roots import DECOMP                          # noqa: E402
import retail_text  # noqa: E402

OUT = PATCH_CONFIG / "overlay_drafts.d/items.json"
OVB = 0x80132000

# --- places: the main date-spot table D_800B9918 (Japanese -> label) -------
PLACES = {
    "近所の公園": "Local Park",
    "きらめき中央公園": "Kirameki Central Park",
    "ショッピング街": "Shopping District",
    "水族館": "Aquarium",
    "動物園": "Zoo",
    "植物園": "Botanical Garden",
    "プラネタリウム": "Planetarium",
    "美術館": "Art Museum",
    "図書館": "Library",
    "ゲームセンター": "Arcade",
    "ボーリング場": "Bowling Alley",
    "カラオケ屋": "Karaoke Box",
    "カラオケ": "Karaoke Box",
    "遊園地": "Amusement Park",
    "スタジアム": "Stadium",
    "映画館": "Cinema",
    "コンサート会場": "Concert Hall",
    "プール": "Pool",
    "海": "Beach",
    "海岸": "Beach",
    "神社": "Shrine",
    "スケート場": "Ice Rink",
    "スキー場": "Ski Resort",
}
# GEKO's meeting spots (33-byte records at 0x801478B8, the {M} of "Meet at
# {M}, okay?"): the place in front of which they meet -> phrase
MEETING_SPOTS = {
    "ショッピング街": "the shopping district",
    "海岸": "the beach",
}
PLACE_PROPER = {"Kirameki Central Park"}

# --- clubs: the main club table D_800B9DF4 ---------------------------------
CLUBS = {
    "文芸": "Literature", "演劇": "Drama", "科学": "Science", "電脳": "Computer",
    "美術": "Art", "吹奏楽": "Brass Band", "野球": "Baseball", "サッカー": "Soccer",
    "テニス": "Tennis", "水泳": "Swimming", "バスケ": "Basketball",
}
NO_CLUB = ("無所属", "None")

# --- gifts: phrase forms the article rule does not get right ---------------
GIFT_PHRASE = {
    "Complete Shakespeare": "the Complete Shakespeare",
    "Star of the Kyojin box set": "the Star of the Kyojin box set",
    "Iron Cook videos, vols 1-4": "the Iron Cook videos, vols 1-4",
    "Fighting Spirit History Set": "the Fighting Spirit history set",
    "Chichibinta Rika Transformation Set": "a Chichibinta Rika transformation set",
    "Goethe's poems": "a book of Goethe's poems",
    "Munch's Scream doll": "a doll of Munch's Scream",
    "A very sinister book": "a very sinister book",
    "Imported Gaugie art book": "an imported Gaugie art book",
    "Manga": "some manga",
    "Frozen crab": "a frozen crab",
}
MASS = {"Perfume", "Softshell turtle blood", "Hand cream", "Anemia medicine", "Lip gloss"}
KEEP_CASE = ("TwinBee", "Nijino", "Chichibinta", "R20000", "Shakespeare", "Kyojin",
             "Goethe", "Munch", "Gaugie", "CD", "T-shirt")

# the tables that put a gift / club / spot inside a sentence: (overlay,
# address, record count, stride, kind)
PHRASE_TABLES = [
    ("GEKO", 0x80145130, 99, 33, "gift"),        # geko_name_set: aname ({A})
    ("BUNKAKEN", 0x8015637C, 9, 33, "gift"),     # bunkaken_msg_set: aname
    ("BUNKASAI", 0x801606EC, 9, 33, "gift"),     # bunkasai_msg_set: aname
    ("GEKO", 0x80144CBC, 12, 20, "club"),        # geko_reaction: mname ({M})
    ("GEKO", 0x801478B8, 19, 33, "spot"),        # geko_girl_pick_init: mname
    ("DATE", 0x8015B9BC, 21, 33, "place"),       # func_8013EF2C: aname / mname
]


def gift_record():
    """{Japanese gift: English label} from the birthday gift menus"""
    import inject
    over = {}
    p = PATCH_CONFIG / "choice_overrides.json"
    if p.exists():
        over = json.loads(p.read_text()).get("rows", {})
    out = {}
    for r in retail_text.read_sheet(SHEETS / "SERIFU" / "G_BIRTH.csv"):
            if r.get("Kind") != "choice" or "{opt}" not in r["Japanese"]:
                continue
            en = over.get(inject.choice_key(r["ID"])) or r.get("English") or ""
            js, es = r["Japanese"].split("{opt}"), en.split("{opt}")
            if len(js) != len(es) or not en.strip():
                continue
            for j, e in zip(js, es):
                j, e = j.strip(), e.strip()
                if not j or "プレゼント" in j:
                    continue
                if j in out and out[j] != e:
                    raise SystemExit(f"[item_names] gift {j}: the menus spell it "
                                     f"{out[j]!r} and {e!r}")
                out[j] = e
    return out


def gift_phrase(label):
    if label in GIFT_PHRASE:
        return GIFT_PHRASE[label]
    first = label.split(" ")[0]
    if not first.startswith(KEEP_CASE) and not (len(first) > 1 and first[1:2].isupper()):
        label = label[0].lower() + label[1:]
    plain = label.split(",")[0]
    if label in {x[0].lower() + x[1:] for x in MASS} or plain.endswith("s") and not plain.endswith("ss"):
        return label
    return ("an " if label[0].lower() in "aeiou" or label.startswith(("R2", "8")) else "a ") + label


def club_label(base):
    return f"{base} Club"


def spot_phrase(jp):
    if jp in MEETING_SPOTS:
        return MEETING_SPOTS[jp]
    base = jp[:-2] if jp.endswith("の前") else jp
    base = {"カラオケＢＯＸ": "カラオケ屋"}.get(base, base)
    label = PLACES.get(base)
    if label is None:
        raise SystemExit(f"[item_names] meeting spot {jp}: no place record for {base}")
    name = label if label in PLACE_PROPER else label.lower()
    return f"the {name} entrance" if jp.endswith("の前") else f"the {name}"


def read_records(ov, addr, n, stride):
    data = (DECOMP / "assets" / "overlays" / f"{ov}.EXN").read_bytes()
    out = []
    for i in range(n):
        off = addr - OVB + i * stride
        raw = data[off:off + stride].split(b"\0")[0]
        out.append((off, raw.decode("shift_jis") if raw else ""))
    return out


def label_copies(labels, taken):
    """{<rel>:0x<off>: label} for every draft-sheet row whose Japanese is a
    record (the copies a by_text entry used to cover), except the keys in
    `taken` (by_addr drafts that take precedence)"""
    import overlay_sheets
    overlay_sheets.ensure_sheets()
    out = {}
    for p in sorted(overlay_sheets.SHEETS.rglob("*.csv")):
        rel = str(p.relative_to(overlay_sheets.SHEETS))[:-4]
        with open(p, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["Japanese"] in labels:
                    k = f"{rel}:0x{int(r['Offset'], 16):x}"
                    if k not in taken:
                        out[k] = labels[r["Japanese"]]
    return out


def other_drafts():
    """the by_addr keys of every other draft file (they take precedence)"""
    taken = set()
    for f in [PATCH_CONFIG / "overlay_drafts.json"] + \
            sorted(OUT.parent.glob("*.json")):
        if f != OUT and f.exists():
            taken |= set(json.loads(f.read_text()).get("by_addr", {}))
    return taken


def generate():
    gifts = gift_record()
    by_text, by_addr = {}, {}
    for jp, en in gifts.items():
        by_text[jp] = en
    for jp, en in PLACES.items():
        by_text[jp] = en
    for jp, en in CLUBS.items():
        by_text[jp] = en
        by_text[jp + "部"] = en              # X部: the same label (8-byte slots)
    by_text[NO_CLUB[0]] = NO_CLUB[1]
    for ov, addr, n, stride, kind in PHRASE_TABLES:
        for off, jp in read_records(ov, addr, n, stride):
            if not jp:
                continue
            key = f"EXEDIR/{ov}.EXN:0x{off:x}"
            if kind == "gift":
                if jp not in gifts:
                    raise SystemExit(f"[item_names] {key} {jp}: not a gift of the menus")
                by_addr[key] = gift_phrase(gifts[jp])
            elif kind == "club":
                base = jp[:-1] if jp.endswith("部") else jp
                if jp == NO_CLUB[0]:
                    by_addr[key] = "no club"
                else:
                    by_addr[key] = "the " + club_label(CLUBS[base])
            elif kind == "place":
                label = PLACES[jp]
                by_addr[key] = label if label in PLACE_PROPER else "the " + label.lower()
            else:
                by_addr[key] = spot_phrase(jp)
    copies = label_copies(by_text, other_drafts() | set(by_addr))
    by_addr.update(copies)

    def sk(kv):
        rel, _, off = kv[0].rpartition(":")
        return rel, int(off, 16)
    return {
        "note": "GENERATED by tools/patch/item_names.py (do not edit: edit the gift menus' "
                "English, or PLACES / CLUBS in the tool, and rerun it). One table of record "
                "for gift, club and date-spot names: every copy of an item (a draft-sheet "
                "row whose Japanese is the record) gets the record's label, the tables a "
                "script token inserts into a sentence ({A} / {M}) the noun-phrase form. "
                "Keyed by <file>:<0xoffset> only; the Japanese is read from the disc.",
        "by_addr": dict(sorted(by_addr.items(), key=sk)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(generate(), ensure_ascii=False, indent=1) + "\n"
    if a.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"[item_names] {OUT.relative_to(ROOT)} is stale: run tools/patch/item_names.py",
                  file=sys.stderr)
            sys.exit(1)
        print("[item_names] items.json up to date")
        return
    OUT.write_text(text)
    d = json.loads(text)
    print(f"[item_names] {len(d['by_addr'])} label copies and phrase records "
          f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
