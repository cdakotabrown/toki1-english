#!/usr/bin/env python3
"""ui_strings.py - the English for the game's UI/system strings (main exe
.data and the overlay .data labels: options, save/load, memory card,
calendar monologues, phone, status, name entry, album save, ...), as a
generator for build/patch/gen/ui_strings.json which build_patched.py merges
into the profile (top-level "strings_files").

Every entry is an IN-PLACE override: the slot is measured here from the
retail binary (the string's bytes plus the zero padding up to the next
non-zero byte), the English is encoded with the patch codec and, where
"dte" is set, with the run's DTE dictionary (renderer-only strings).  A
string that does not fit its slot is reported (and left Japanese) rather
than truncated.  Strings reached through a pointer word (`ptr_at`) go to
the string pool and have no size limit.

Not translated on purpose (documented in PS1-PATCH-STATUS.md): the memory
card file titles (the BIOS card manager needs Shift-JIS), the event
dispatcher's strcmp specials (sound-effect literals compared against the
containers), the bracket glyphs, and the information-magazine 17-byte
records.

Usage: ui_strings.py [--dte build/patch/gen/dte.json] [--out build/patch/gen/ui_strings.json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roots import ROOT  # noqa: E402  (this checkout, either layout)
from roots import DECOMP, locate                  # noqa: E402
import textcodec  # noqa: E402
import compose_check  # noqa: E402

EXE = DECOMP / "disks" / "SLPS_000.65"
EXN = DECOMP / "assets" / "overlays"

# ---------------------------------------------------------------------------
# the English (address -> text); a tuple (text, {"dte": False}) turns DTE off
# ---------------------------------------------------------------------------

MAIN = {
    # --- memory card / save / load (main) ---
    0x800B6750: "Data is corrupted",
    0x800B6768: "Cannot read the memory card",
    0x800B6788: "No free space on the memory card",
    0x800B67AC: "Memory card",
    0x800B67BC: "Save",
    0x800B67C4: "Load",
    0x800B67CC: "Choose Save or Load.",
    0x800B67F0: "Choose Save or Load.",
    0x800B6814: "Unformatted memory card.",
    0x800B6834: "Format it?",
    0x800B684C: "Insert another memory",
    0x800B6864: "card in slot 1",
    0x800B6874: "　　　　　　and press",
    0x800B6890: "the ○ button.",
    0x800B68AC: "Save data",
    0x800B68BC: "Choose a file to save to.",
    0x800B68E0: "Overwrite it?",
    0x800B68FC: "Saving data...",
    0x800B6910: "Do not turn off the power",
    0x800B692C: "while the icon flashes.",
    0x800B6944: "Load data",
    0x800B6954: "Choose a file to load.",
    0x800B6978: "Loading data...",
    0x800B698C: "Please wait.",
    0x800B69A4: "Continue from this data?",
    0x800BBEF8: "Checking the memory card",
    0x800BBF1C: "...",
    # --- system settings ---
    0x800B69C8: "System settings",
    0x800B69DC: "Change the system settings.",
    0x800B69F8: "Text speed",
    0x800B6A08: "Icon mode",
    0x800B6A18: "Mouse setup",
    0x800B6A24: "Menu mode",
    0x800B6A34: "Cursor speed",
    0x800B6A44: "Voice mode",
    0x800B6A50: "Mascot",
    0x800B6A5C: "Exit setup",
    0x800B6A68: "Text speed",
    0x800B6A74: "Slow",
    0x800B6A7C: "Normal",
    0x800B6A84: "Fast",
    0x800B6A8C: "Change the text display speed.",
    0x800B6AAC: "Text speed set to slow.",
    0x800B6AD0: "Text speed set to normal.",
    0x800B6AF4: "Text speed set to fast.",
    0x800B6B18: "Icon mode",
    0x800B6B28: "TYPE-A",
    0x800B6B38: "TYPE-B",
    0x800B6B48: "Free",
    0x800B6B50: "Set the icon positions.",
    0x800B6B70: "Icon mode set to",
    0x800B6B84: "TYPE-A.",
    0x800B6B9C: "Icon mode set to",
    0x800B6BB0: "TYPE-B.",
    0x800B6BC8: "Icon mode set to",
    0x800B6BDC: "Free.",
    0x800B6BF0: "Mouse setup",
    0x800B6BFC: "OK button",
    0x800B6C08: "Click mode",
    0x800B6C18: "Click speed",
    0x800B6C2C: "Settings for using a mouse.",
    0x800B6C50: "OK button",
    0x800B6C60: "Right button",
    0x800B6C70: "Left button",
    0x800B6C80: "Choose the OK button.",
    0x800B6C98: "OK is now the right button.",
    0x800B6CB4: "OK is now the left button.",
    0x800B6CD0: "Click mode",
    0x800B6CE4: "Single click",
    0x800B6CF8: "Double click",
    0x800B6D08: "Set the click mode.",
    0x800B6D24: "Set to single click.",
    0x800B6D40: "Set to double click.",
    0x800B6D5C: "Click speed",
    0x800B6D74: "Default",
    0x800B6D80: "Change",
    0x800B6D88: "Set the double-click speed.",
    0x800B6DA8: "To change it, point at Change",
    0x800B6DC8: "and double-click.",
    0x800B6DEC: "Click speed reset to default.",
    0x800B6E14: "Click speed changed.",
    0x800B6E34: "Menu mode",
    0x800B6E48: "1: Mouse-like",
    0x800B6E5C: "2: Pad A",
    0x800B6E6C: "3: Pad B",
    0x800B6E7C: "4: 1+2",
    0x800B6E88: "How the cursor moves between",
    0x800B6EA8: "menu items (choices, icons)",
    0x800B6EC8: "when using the pad.",
    0x800B6EE8: "Pad mode:",
    0x800B6EF8: "Mouse-like",
    0x800B6F08: "selected.",
    0x800B6F14: "Pad mode:",
    0x800B6F24: "Pad A",
    0x800B6F30: "selected.",
    0x800B6F3C: "Pad mode:",
    0x800B6F4C: "Pad B",
    0x800B6F58: "selected.",
    0x800B6F64: "Pad mode:",
    0x800B6F74: "Mouse-like + Pad A",
    0x800B6F8C: "selected.",
    0x800B6F98: "Cursor speed",
    0x800B6FA8: "Slowest",
    0x800B6FB0: "Slow",
    0x800B6FB8: "Normal",
    0x800B6FC0: "Fast",
    0x800B6FC8: "Fastest",
    0x800B6FD0: "Slow",
    0x800B6FD8: "Slowish",
    0x800B6FE4: "Normal",
    0x800B6FEC: "Fastish",
    0x800B6FF8: "Fast",
    0x800B7000: "Set the cursor speed.",
    0x800B7020: "Cursor speed set to",
    0x800B7038: "slowest.",
    0x800B7048: "slow.",
    0x800B7058: "Cursor speed set to",
    0x800B7070: "a bit slower.",
    0x800B7088: "slowish.",
    0x800B709C: "Cursor speed set to",
    0x800B70B4: "normal.",
    0x800B70C8: "Cursor speed set to",
    0x800B70E0: "a bit faster.",
    0x800B70F8: "fastish.",
    0x800B710C: "Cursor speed set to",
    0x800B7124: "fastest.",
    0x800B7134: "fast.",
    0x800B7144: "Voice mode",
    0x800B7150: "Always on",
    0x800B715C: "Always off",
    0x800B7168: "× button skips",
    0x800B717C: "Set the voice mode.",
    0x800B7198: "Voice mode set",
    0x800B71A8: "to always on.",
    0x800B71BC: "Voice mode set",
    0x800B71CC: "to always off.",
    0x800B71E4: "Voice mode set",
    0x800B71F4: "to skip with ×.",
    0x800B7210: "Mascot",
    0x800B721C: "Hide",
    0x800B7228: "Choose a mascot.",
    # --- clubs ---
    0x800B7240: "Joined the {dst} Club.",  # template (module string): club + this
    0x800B7250: "Captain",
    0x800B7258: "\"On the",  # x=-86, 42-px cell
    0x800B7260: "third Sunday",  # x=-44 (colour 1), 70-px cell
    0x800B726C: "of the month,",  # x=26 after the colour-1 piece
    0x800B7274: "it's club day, so",  # row 2 at x=-72
    0x800B7288: "don't skip",
    0x800B7294: "it.",
    0x800B7814: "Clubs",
    0x800B7820: "Cancel",
    0x800B782C: "Choose a club to join.",
    0x800B7EEC: "Do club activities",
    0x800B7F00: "Quit the club",
    0x800B7F10: "Quit the {dst} Club.",  # template (module string): club + this
    # --- calendar monologues (field path) ---
    0x800B65D0: "Weekday commands",
    0x800B65E4: "Exams tomorrow.)",
    0x800B65F8: "Tomorrow: the national baseball tournament at last!)",
    0x800B6620: "Training camp tomorrow.)",
    0x800B6634: "Need club practice for{br}the culture festival.)",
    0x800B6654: "Need club practice for{br}the culture festival...{br}but I am too sick to move.)",
    0x800B668C: "School trip tomorrow.)",
    0x800B66A4: "I'm stuck with a week of remedial classes.)",
    0x800B66CC: "I'm too sick to move.)",
    0x800B6700: "Exams start tomorrow.)",
    0x800B6714: "School trip tomorrow.)",
    0x800B672C: "Calendar",
    0x800B6738: "This/next month: plans/results",
    0x800B72A0: "Home",
    0x800B72A8: "A weird rumor's going around among the girls...)",
    0x800B72D8: "Home",
    0x800B72E0: "Christmas party at the Ijuin house today. Shall I go?)",
    0x800B7320: "Jan. 1",
    0x800B7328: "Ding-dong!",
    0x800B7338: "Hm? Who is it?)",
    0x800B7348: "Mail",
    0x800B7350: "New Year cards!",
    0x800B7360: "Yes! ",
    0x800B736C: " and ",
    0x800B7374: " sent me cards. Lucky!)",
    0x800B7900: "-",
    0x800B7908: "New term tomorrow.)",
    0x800B791C: "New term tomorrow.)",
    0x800B7930: "Summer break soon.)",
    0x800B7944: "Winter break soon.)",
    0x800B7958: "Spring break soon.)",
    0x800B796C: "-",
    0x800B7974: "New term tomorrow.)",
    0x800B7988: "Injury",
    0x800B7990: "I got hurt.)",
    0x800B79A8: "Burnout",
    0x800B79B4: "I'm totally burned out.)",
    0x800B79D4: "Sick",
    0x800B79DC: "I've fallen ill.)",
    0x800B79F4: "Healed",
    0x800B79FC: "All healed.)",
    0x800B7A0C: "Healed",
    0x800B7A14: "I've recovered.)",
    0x800B7A2C: "Healed",
    0x800B7A34: "I'm better now.)",
    0x800B7D50: "Holiday commands",
    0x800B7D64: "I'm stuck with a week of remedial classes.)",
    0x800B7D8C: "I'm too sick to move.)",
    0x800B7DA4: "Today I have a date with ",  # module string: + girl + next
    0x800B7DB0: ".)",
    0x800B7DC4: "A club practice match today.)",
    0x800B7DE0: "A club practice match today.)",
    0x800B7E00: "Club practice today.)",
    0x800B7E1C: "Club practice today.)",
    0x800B7E54: "Where were we meeting again?)",
    0x800B7E8C: "Okay, I'll wait at ",  # module string: + place + next + girl + next
    0x800B7E98: " for ",
    0x800B7EA0: ".)",
    0x800B7EB0: "Magazine",
    0x800B7EB8: "Who should I call?)",
    0x800B7ED4: "Numbers",
    0x800B7EE0: "Cancel",
    0x800B8A2C: "Cancel",
    0x800BCEBC: "Meet at {dst}",  # template (module string): the 5 bracket strings before the place are blank
    0x800B7E78: "",  # machiawase_menu_set 『 before the place (blank: the template words the choice)
    0x800B7E7C: "",
    0x800B7E80: "",
    0x800B7E84: "",
    0x800B7E88: "",
    0x800B7DC0: "(",  # holiday_screen_init: （ drawn straight before the English line (no sndisp conversion)
    0x800B7DFC: "(",
    # --- album card (album_info_disp) ---
    0x800B775C: "System",
    0x800B7768: "Unused",
    0x800B7770: "Bad data",
    0x800B777C: "/",
    0x800B7780: "/",
    0x800B7784: "",
    0x800B7788: "Name:",  # album card: the name join (text_misc.c pt_name_put) adds the space
    0x800B7790: "Nick: ",  # album card label: the value follows directly (strncat)
    0x800B779C: "Club: ",  # album card label: the value follows directly (strncat)
    0x800B77A8: "Cleared: ",  # album card label: the value follows directly (strncat)
    0x800B77B8: "Unused",
    0x800B77C0: "Bad data",
    0x800B77CC: "",  # number + strncat(this, 2): only 2 bytes are copied ('3Al'), the number alone reads right
    0x800B7750: "",  # album_info_disp_str0: the same header (by_text drafted it "Album")
    0x800B77D8: "/",
    0x800B77DC: "/",
    0x800B77E0: "",
    0x800B77E4: "Name:",  # album card: the name join (text_misc.c pt_name_put) adds the space
    0x800B77EC: "Nick: ",  # album card label: the value follows directly (strncat)
    0x800B77F8: "Club: ",  # album card label: the value follows directly (strncat)
    0x800B7804: "Cleared: ",  # album card label: the value follows directly (strncat)
    # --- stat names (pointer table D_800B9804); the date spots (D_800B9918)
    #     and clubs (D_800B9DF4) come from tools/patch/item_names.py (the
    #     table of record, _item_record_labels below) ---
    0x800B97BC: "Health",
    0x800B97C4: "Lit.",
    0x800B97CC: "Science",
    0x800B97D4: "Arts",
    0x800B97DC: "Sports",
    0x800B97E4: "Trivia",
    0x800B97EC: "Looks",
    0x800B97F4: "Guts",
    0x800B97FC: "Stress",
    # --- information magazine monologues (pointer table D_800BCBA4) and
    #     the help monologues (D_800BD1F8) ---
    0x800BC920: "So this is that new info magazine. Oh right, I can check my biorhythm on the calendar.)",
    0x800BC98C: "Kirameki Central Park, huh.)",
    0x800BC9A4: "So there's an art museum now.)",
    0x800BC9BC: "There's an aquarium? Also, a system file makes managing album data easier, apparently.)",
    0x800BCA20: "So the stadium's done. Hm, in free mode you grab an icon by holding L2.)",
    0x800BCA74: "A botanical garden... Come to think of it, Shiori counts sheep at night. Heard it somewhere.)",
    0x800BCACC: "Bowling, huh.)",
    0x800BCAE0: "A planetarium, huh.)",
    0x800BCAF8: "Karaoke, huh.)",
    0x800BCB0C: "If I enter the Konami code while reading the magazine... Up Up Down Down Left Right Left Right × ○)",
    0x800BCB58: "Hmm. A Gaugie exhibition.)",
    0x800BCB74: "So this is the last issue of the magazine...)",
    0x800BCB98: "......)",
    0x800BCF14: "Page center = now. Red: body, yellow: emotion, green: intellect.)",
    0x800BCF58: "Biorhythm 2: crossing the blue line means a bad day.)",
    0x800BCF8C: "Biorhythm 3: far from the blue line is good; at equal distance, higher is better.)",
    0x800BCFD8: "I can use the phone to call a girl directly.)",
    0x800BD010: "This stereo doesn't pick up the radio very well.)",
    0x800BD04C: "Clear the game and you get that girl's mascot doll.)",
    0x800BD08C: "Mascot: hold R1 to move it, hold R2 to stretch its string.)",
    0x800BD0CC: "I think I left the manual for this game on the desk.)",
    0x800BD100: "2P: ○×△□ together -> 1P mash ○)",
    0x800BD128: "Press Square to choose{br}your favorite cursor.)",
    0x800BD150: "The Select button changes the menu mode.)",
    0x800BD180: "2P Start button: changes the SD characters' animation speed.)",
    0x800BD1B8: "Don't panic after clearing the game.)",
    0x800BD1E0: "\"Sleeve Dragon\" takes \"Defend\".)",
}

NAME_ENT = {
    0x8014B448: "Birthday and blood type?",
    0x8014B498: "Is this OK?",
    0x8014B4D4: "Shiori's birthday and blood type?",
    0x8014B4FC: "Is this OK?",
    0x8014B50C: "Fujisaki",
    0x8014B514: "Shiori",
    0x8014B834: "　No memory",
    0x8014B848: "　card found.",
    0x8014B858: "Start a new game?",
    0x8014B874: "Insert a memory card",
    0x8014B888: "in slot 1",
    0x8014B898: "　　　　　　and press",
    # 0x8014B8B4: button_line, below
    0x8014B8DC: "The system file is",
    0x8014B8F0: "corrupted.",
    0x8014B900: "Recreate the",
    0x8014B914: "system file?",
    0x8014B95C: "The data in album {dst}",  # template: album number + this (module string)
    0x8014B974: "is corrupted.",
    0x8014B984: "Loading album {dst}.",  # template: album number + this (module string)
    0x8014B994: "Please wait.",
    0x8014BA38: "　Starting the game",
    0x8014BA54: "without an album.",
    0x8014BAB4: "　A system file lets you",
    0x8014BAD4: "save sub-game data",
    0x8014BAF0: "and more.",
    0x8014BB10: "Create a system file?",
    0x8014BB30: "Creating album {dst}...",  # template: album number + this (module string)
    0x8014BB50: "Creating album {dst}",  # template: album number + this (module string)
    0x8014BB64: "and the system file.",
    0x8014BB78: "Please wait.",
    0x8014BB9C: "　Keep the cleared count",
    0x8014BBB8: "and restart from",
    0x8014BBD0: "the prologue.",
    0x8014BBE4: "　Which album",
    0x8014BBFC: "do you want to redo?",
    0x8014BC10: "Restart album {dst}?",  # template: album number + this (module string)
    0x8014BC20: "Are you sure?",
    0x8014BC74: "Creating album {dst}.",  # template: album number + this (module string)
    0x8014BC88: "Please wait.",
    0x8014BC9C: "Creating album {dst}.",  # template: album number + this (module string)
    0x8014BCB0: "Please wait.",
    0x8014BCC4: "　Which album",
    0x8014BCDC: "do you want to copy?",
    0x8014BCF0: "Point at one and press ○.",
    0x8014BD20: "Copy album {dst}",  # template: album number + this (module string)
    0x8014BD30: "to which album?",
    0x8014BD50: "Point at one and press ○.",
    0x8014BD6C: "Overwrite album {dst}?",  # template: album number + this (module string)
    0x8014BD7C: "Are you sure?",
    0x8014BD98: "Copying to album {dst}.",  # template: album number + this (module string)
    0x8014BDA8: "Please wait.",
    0x8014BDC8: "Copying to album {dst}.",  # template: album number + this (module string)
    0x8014BDD8: "Please wait.",
    0x8014BDF8: "　Which album",
    0x8014BE10: "do you want to delete?",
    0x8014BE20: "Point at one and press ○.",
    0x8014BE3C: "Delete album {dst}?",  # template: album number + this (module string)
    0x8014BE4C: "Are you sure?",
    0x8014BEA8: "Cannot create the file.",
    0x8014BEC4: "Insert another memory card",
    0x8014BEE4: "in slot 1, or delete",
    0x8014BF04: "another game's data.",
    0x8014BF20: "Recreate the system file?",
    0x8014BF40: "",
    0x8014BF50: "It takes about a minute;",
    0x8014BF70: "do not remove the",
    0x8014BF88: "memory card during this time.",
    0x8014BF9C: "When ready, press",
    0x8014BFB0: "any button.",
    0x8014BFD0: "Please wait.",
    0x8014BFE8: "Create the system file?",
    0x8014C004: "",
    0x8014C014: "It takes about a minute;",
    0x8014C034: "do not remove the",
    0x8014C04C: "memory card during this time.",
    0x8014C060: "When ready, press",
    0x8014C074: "any button.",
    0x8014C094: "Please wait.",
    0x8014C0AC: "Unformatted memory card.",
    0x8014C0CC: "Format it?",
    0x8014C0E4: "Insert another memory",
    0x8014C0FC: "card in slot 1",
    0x8014C10C: "　　　　　　and press",
    # 0x8014C128: button_line, below
    0x8014C924: "/",
    0x8014C928: ".",
    0x8014C930: ".",       # blood letter + strncat(this, 4): " type." was cut to "A typ"
}

ETC = {
    0x8014CB40: "Unformatted memory card.",
    0x8014CB60: "Format it?",
    0x8014CB78: "Insert another memory",
    0x8014CB90: "card in slot 1",
    # 0x8014CBA0, 0x8014CBBC: the button line, below
    0x8014CBD8: "Save this album-mode data to the",
    0x8014CBF8: "　Tokimeki Memorial system file?",
    0x8014CC20: "",
    0x8014CC4C: "Checking the memory card.",
    0x8014CCB0: "Saving...",
    0x8014CD18: "There is no system file.",
    0x8014CD38: "(Album mode cannot be saved",
    0x8014CD54: "without a system file.)",
    0x8014CD7C: "Create a system file and",
    0x8014CD98: "save the album-mode data?",
    0x8014CDBC: "Creating the system file.",
    0x8014CDE0: "(After saving the album-mode data,",
    0x8014CE08: "recreate the system file",
    0x8014CE24: "on the file select screen.)",
    0x8014CE4C: "Cannot read the memory card.",
    0x8014CE70: "Check the memory card",
    0x8014CE90: "in slot 1.",
    0x8014CEAC: "Save the data?",
    0x8014CECC: "No free blocks on the memory card.",
    0x8014CEF8: "Please use a memory card",
    0x8014CF20: "with free blocks.",
    0x8014CF34: "Save the data?",
    0x8014CF54: "The system file is corrupted.",
    0x8014CF78: "Recreate the system file?",
    0x8014CFA4: "Creating the system file.",
    0x8014CFC8: "(After saving the album-mode data,",
    0x8014CFF0: "click System on the file",
    0x8014D014: "select screen to recreate",
    0x8014D038: "the system file.)",
    0x8014D170: "Save this play session?",
    0x8014D190: "Checking the memory card",
    0x8014D1F4: "Choose an album to save to.",
    0x8014D218: "Choose an album to save to.",
    0x8014D23C: "Save data",
    0x8014D24C: "Saving data...",
    0x8014D260: "Please wait.",
    0x8014D288: "Cannot read the memory card",
    0x8014D2A8: "Insert a memory card in slot 1",
    0x8014D2C8: "and press a button.",
    0x8014D2EC: "No free space on the memory card",
    0x8014D310: "Save to another",
    0x8014D328: "memory card?",
    0x8014D33C: "Insert another memory card",
    0x8014D354: "in slot 1 and",
    0x8014D370: "press a button.",
    0x8014D38C: "Unformatted memory card.",
    0x8014D3AC: "Format it?",
    0x8014D3C4: "Insert another memory",
    0x8014D3DC: "card in slot 1",
    0x8014D3EC: "　　　　　　and press",
    # 0x8014D408: button_line, below
}

OPTION = {
    0x8013C8A0: "Text speed",
    0x8013C8B0: "Icon mode",
    0x8013C8C0: "Mouse",
    0x8013C8CC: "Menu mode",
    0x8013C8DC: "Cursor speed",
    0x8013C8EC: "Voice",
    0x8013C8F8: "Extras",
    0x8013C900: "Exit options",
    0x8013C980: "　The cursor follows the d-pad in",
    0x8013C9A4: "all four directions.",
    0x8013C9B8: "(Same as a mouse.)",
    0x8013C9D0: "　In a menu, the d-pad moves the",
    0x8013C9F8: "cursor through the items in",
    0x8013CA20: "order.",
    0x8013CA30: "　In a menu, the d-pad moves the",
    0x8013CA58: "cursor to the item in that",
    0x8013CA80: "direction.",
    0x8013CA90: "　Normally works like Mouse-like;",
    0x8013CAB4: "while L1 is held it works",
    0x8013CADC: "like Pad A.",
    0x8013CAF8: "Free talk",
    0x8013CB20: "Ending",
}

TEL = {
    0x801403A0: "How the girls rate you",
    0x801403B4: "How the girls rate you",
    0x801403C8: "Phone",
    0x801403D4: "Birthday",
    0x801403DC: "/",
    0x801403E0: "",
    0x801403E4: "BWH",
    0x801403EC: "Sign",
    0x801403F4: "Blood",
    0x801403FC: "Club",
    0x80140404: "Private club",
    0x8014040C: "Notes",
    0x80140414: "Date spots",
    0x80140424: "Next page",
    0x80140434: "Date spots",
    0x80140444: "Previous page",
    0x8013ECF8: "Choose a day for the date",
    0x8013ED14: "Choose a place for the date",
    0x8013ED34: "Choose a place for the date",
}

DATE = {}

GEKO = {
    0x80144680: "Ding-dong",
    0x80144784: "Ring ring...",
    0x80144794: "Ring ring...",
    0x80144A30: "Thud",
}

SHUGAKU = {
    0x8013ADB4: "Ugh...",
    0x8013ADC0: "I feel terrible.",
    0x8013ADD8: "But it's the school trip,",
    0x8013ADF0: "I have to get to the meeting point.",
    0x8013AE70: "[Group activity]",
}

MASTER = {
    0x8013BB18: "(The frustration of losing",
    0x8013BB34: "　the final awoke the power",
    0x8013BB48: "　sleeping inside me!!)",
    0x8013BB60: "(Ooooooohhh!!!!)",
    0x8013BB80: "    Baseball Secret Art",
    0x8013BB90: "　　　\"Burst Ball\"",
    0x8013BBA8: "　　　　　　mastered.",
    0x8013BBC8: "(The thrill of winning",
    0x8013BBE0: "　gave my",
    0x8013BBEC: "　body a new power!!)",
    0x8013BC08: "(The frustration of losing",
    0x8013BC24: "　the final awoke the power",
    0x8013BC38: "　sleeping inside me!!)",
    0x8013BC50: "(Ooooooohhh!!!!)",
    0x8013BC70: "    Baseball Secret Art",
    0x8013BC80: "　　　\"Burst Ball\"",
    0x8013BC98: "　　　　　　mastered.",
}

BUNKA_SD = {
    0x80139E88: "Topic",
    0x80139E90: "\"My High School Life\"",
    0x80139EA4: "\"My Existence\"",
    0x80139EB4: "\"Looking Back on School\"",
    0x80139ED0: "\"Anemia and Me\"",
    0x80139EE0: "\"Let My Heart Reach You\"",
    0x80139EF8: "Orator",
    0x80139F04: "S. Fujisaki",
    0x80139F10: "Mio Kisaragi",
    0x80139F1C: "A girl",
    0x80139F24: "Orator",
    0x80139F2C: "Fujisaki",
    0x80139F34: "Kisaragi",
    0x80139F3C: "A girl",
}

ENDING = {
    0x8013C290: "\"Song of the Sissy Boys\"",
    0x8013CC78: "The scenery in the window",
    0x8013CC91: "is full of lies",
    0x8013CCAA: "and a cold darkness",
    0x8013CCC3: "closes over my heart",
    0x8013CCDC: "Ah, if only you were here",
}

TAIIKU = {0x80148E84: "Whump"}

# SHOUGATU omikuji result line (func_801350E4): sprintf(buf, FORMAT, rank)
# with the rank word from the 5-byte table D_80143F1C (Best Good Fair Bad
# Worst Minor Later, producer decision D5; written in place by
# overlay_drafts.d/events.json, the words of the OMIKUJI.BIN slip art).
# Rank 0 takes the "Lucky!" format, 3/4 (凶 大凶) the "..." one, the rest
# "Oh, it's".  The formats are rewritten WHOLE here (the inventory splits
# them at the %s, and writing its "おっ、" row up to the NUL dropped the
# rank: "Oh, it's"); no DTE, so the %s stays two plain bytes.  The result
# fits the retail buffer (the longest retail line, 'Lucky! It's great luck!!', is
# 20 bytes).
SHOUGATU = {
    # the rank is the slip's one-word label (Best Good Fair Minor Later Bad
    # Worst): quoted, every rank reads ("Oh, it's Luck." did not), as the
    # {O} lines quote it (config/patch/choice_overrides.json)
    0x80143740: "\"%s\"...",                    # %sだ・・・
    0x8014374C: "It says \"%s\".",              # おっ、%sだ。
    0x8014375C: "Lucky! It's \"%s\"!!",              # ラッキー！%sだ！！
    0x80143950: "%s",                           # %sさん: sprintf(p_name2, ., p_sei), the heroine's {P}
}

# speaker labels the overlays copy into g_name (strcpy sites; in place,
# so they are kept short: the slot is 7 or 11 bytes, and the label must fit
# the retail name column, 44 px: text_event.c PT_LABEL_BUDGET)
SPEAKERS = {
    "DATE": {0x8015AE90: "Punk", 0x8015B4F0: "Mystery"},
    "ENDING": {0x8013BFE0: "Sotoi", 0x8013BFE8: "Ijuin", 0x8013BFF0: "Sotoi"},
    "GEKO": {0x801448B4: "Teacher", 0x80144960: "Boy 1", 0x80144968: "Boy 2",
             0x80144A40: "Mystery", 0x80144A4C: "Miharu"},
    "OMIMAI": {0x801348B8: "Mother"},
    "SHOUGATU": {0x80143820: "Girl", 0x80143A0C: "Butler", 0x80143A14: "Sotoi",
                 0x80143A20: "Ijuin"},
    "SHUGAKU": {0x8013AD10: "Foreigner"},
}
RENSYU = {0x801340DC: "Match"}
RPG_BAT = {0x8015AE98: "Thud"}
BUNKASAI = {
    0x8015F1D0: "\"Well, I guess I'll show you.",
}
# BUNKAKEN's own copies only.  0x8016045C / 7C / 84 are BUNKASAI's
# addresses (overlay_drafts.d translates those); in BUNKAKEN the image ends
# at 0x80156580 and those words are zero fill that no BUNKAKEN code
# references, so an override there was never drawn and only wrote text into
# the overlay's zero area (removed, LQA 2026-11-06).
BUNKAKEN = {
    0x80155E2C: "* PC  NMS-9000 *",
    0x80155E4C: "Blood",
    0x80155E54: "Blood",
}

# Button lines.  The game draws the button itself, with code, as its own
# one-glyph string over the line: get_pad_str / get_pad_str2 (main) and
# get_etc_yes_button / get_etc_no_button (ETC) return the circle or cross
# for a pad, the kanji "left" / "right" for a mouse.  The line's text
# leaves a 14-px cell free at the button's x and goes on after it.
def button_line(head, icon_x, tail):
    """head, padded with ideographic / ASCII spaces so it ends before the
    button drawn at icon_x px, then tail from icon_x + 14"""
    w = textcodec.width(head)
    ideo = (icon_x + 14 - w) // 14              # 14-px ideographic spaces
    asc = round((icon_x + 14 - w - 14 * ideo) / textcodec.width(" "))
    if w > icon_x:
        raise SystemExit(f"[ui_strings] {head!r} ({w} px) runs into the button at {icon_x} px")
    return head + "\u3000" * ideo + " " * asc + tail


# yes/no lines: the button at x+84 (6 cells of 14 px), "button" at +98
def yes_no(word):
    return button_line(word, 84, "button")


# "Insert another memory card in slot 1 and press [button] button." where the
# button opens the third line (x+0: name_ent_card_insert_disp, name_ent_card_format,
# save_card_format).  These read "　the ○ button." until 2026-11-07, which
# drew the code's button over the leading space AND a second circle.
for _t, _a in ((NAME_ENT, 0x8014B8B4), (NAME_ENT, 0x8014C128), (ETC, 0x8014D408)):
    _t[_a] = button_line("", 0, "button.")
# ETC etc_card_format_ask draws its button at x+68 of the third line: the
# line reads "press the [button] button." under "card in slot 1 and"
ETC[0x8014CBA0] = "\u3000" * 6 + "and"
ETC[0x8014CBBC] = button_line("press the", 68, "button.")

# The mouse buttons: the retail strings are the kanji "right" / "left",
# whose glyphs the patch module overwrites (the renderer drew its
# missing-glyph box).  The patch's own icons (tools/patch/font/icons12.txt)
# take their place; the pad's circle and cross stay the retail glyphs.
MAIN[0x800BCC2C] = textcodec.MOUSE_RIGHT     # get_pad_str2_tbl1
MAIN[0x800BCC30] = textcodec.MOUSE_LEFT      # get_pad_str2_tbl2
ETC[0x80150148] = textcodec.MOUSE_RIGHT      # etc_migi_str
ETC[0x8015014C] = textcodec.MOUSE_LEFT       # etc_hidari_str

# the event dispatcher's bracket glyphs: the English label code draws its
# own opening quote (text_event.c), the thought/narration parentheses and
# the hanging "(" prefix glyph become ASCII (the suffix ")" is appended by
# pt_schedule_analyze, the prefix is tested by pt_queue_row)
for _a in (0x800B87F4, 0x800B88C4, 0x800B89D4, 0x800B89FC):
    MAIN[_a] = ("(", {"dte": False})
for _a in (0x800B87F8, 0x800B88C8, 0x800B89D0):
    MAIN[_a] = (")", {"dte": False})
NO_DTE_EXTRA = {0x800B87F4, 0x800B88C4, 0x800B89D4, 0x800B89FC, 0x800B87F8, 0x800B88C8, 0x800B89D0}

MAIN[0x800BA15C] = yes_no("Yes...")
MAIN[0x800BA174] = yes_no("No...")
ETC[0x80150110] = yes_no("Yes...")
ETC[0x8015012C] = yes_no("No...")

# pointer tables (main): string address -> the word that points at it
MAIN_PTR = {}
for base, first, n in ((0x800B9804, 0x800B97BC, 9),      # stat names (8-byte cells)
                       ):
    pass

def _item_record_labels():
    """the main date-spot table D_800B9918 and club table D_800B9DF4 take
    the table of record (tools/patch/item_names.py), so the menus, the
    album card and every other copy of a place / club spell it alike"""
    import struct
    import item_names
    exe = EXE.read_bytes()
    out = {}
    for tab, n in ((0x800B9918, 21), (0x800B9DF4, 12)):
        for i in range(n):
            ptr = struct.unpack_from("<I", exe, tab - 0x80040800 + 4 * i)[0]
            off = ptr - 0x80040800
            jp = exe[off:exe.index(b"\0", off)].decode("shift_jis")
            label = item_names.PLACES.get(jp) or item_names.CLUBS.get(jp) or \
                (item_names.NO_CLUB[1] if jp == item_names.NO_CLUB[0] else None)
            if label is None:
                raise SystemExit(f"[ui_strings] {jp}: not in the item_names records")
            out[ptr] = label
    return out


MAIN.update(_item_record_labels())

TABLES = {
    "main": MAIN, "NAME_ENT": NAME_ENT, "ETC": ETC, "OPTION": OPTION, "TEL": TEL,
    "DATE": DATE, "GEKO": GEKO, "SHUGAKU": SHUGAKU, "MASTER": MASTER,
    "BUNKA_SD": BUNKA_SD, "ENDING": ENDING, "TAIIKU": TAIIKU, "RENSYU": RENSYU,
    "RPG_BAT": RPG_BAT, "BUNKASAI": BUNKASAI, "BUNKAKEN": BUNKAKEN,
    "OMIMAI": {}, "SHOUGATU": dict(SHOUGATU),
}
for _ov, _t in SPEAKERS.items():
    TABLES.setdefault(_ov, {}).update(_t)
NO_DTE = {("main", 0x800B9B30)} | {("main", a) for a in NO_DTE_EXTRA} \
    | {("SHOUGATU", a) for a in SHOUGATU}


# ---------------------------------------------------------------------------

def load_target(name):
    if name == "main":
        return EXE.read_bytes(), 0x80041000 - 0x800
    return (EXN / f"{name}.EXN").read_bytes(), 0x80132000


def slot_of(data, off):
    e = data.find(b"\0", off)
    s = e
    while s + 1 < len(data) and data[s + 1] == 0 and s - off < 300:
        s += 1
    return e - off, s - off          # (len, max_bytes)


def pointer_sites(data, base, addr, lo, hi):
    """words inside [lo, hi) of the image that hold `addr`"""
    import struct
    needle = struct.pack("<I", addr)
    out = []
    i = data.find(needle, lo - base)
    while i != -1 and i < hi - base:
        if i % 4 == 0:
            out.append(base + i)
        i = data.find(needle, i + 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dte", default="build/patch/gen/dte.json")
    ap.add_argument("--out", default="build/patch/gen/ui_strings.json")
    ap.add_argument("--profile", default="config/patch/english.json",
                    help="skip addresses the profile already overrides")
    a = ap.parse_args()
    dte = []
    p = locate(a.dte)
    if p.exists():
        dte = json.loads(p.read_text())["entries"]
    have = {"main": set()}
    prof = json.loads(locate(a.profile).read_text())
    for s in prof.get("main", {}).get("strings", []):
        if "addr" in s:
            have["main"].add(int(s["addr"], 16))
    for ov, spec in prof.get("overlays", {}).items():
        have[ov] = {int(s["addr"], 16) for s in spec.get("strings", []) if "addr" in s}
    out = {"main": [], "overlays": {}}
    overflow = []
    total = 0
    composed = compose_check.composed_slots()
    draw_only = set(compose_check.draw_slots())      # compositions.json "draw_slots"
    for target, table in TABLES.items():
        data, base = load_target(target)
        for addr, text in sorted(table.items()):
            if isinstance(text, tuple):
                text = text[0]
            if addr in have.get(target, set()):
                continue
            use_dte = (target, addr) not in NO_DTE
            off = addr - base
            ln, mx = slot_of(data, off)
            conv_jp = [c.decode() for c in re.findall(rb"%[-0-9]*[sd]", data[off:off + ln])]
            conv_en = re.findall(r"%[-0-9]*[sd]", text)
            if conv_jp != conv_en:
                # sprintf takes its arguments in order: the English format
                # must carry the same conversions in the same order
                raise SystemExit(f"[ui_strings] {target} 0x{addr:08X}: printf conversions "
                                 f"{conv_en} != the retail format's {conv_jp}: {text!r}")
            if "{dst}" in text and (target, addr) not in composed:
                raise SystemExit(f"[ui_strings] {target} 0x{addr:08X}: {{dst}} only works on a "
                                 f"composition piece (config/patch/compositions.json)")
            if ((target, addr) in composed or (target, addr) in draw_only) and mx >= 2 and (
                    "{dst}" in text or len(textcodec.encode(text, dte if use_dte else None)) > mx):
                # a composed string's joiner that does not fit, or a
                # reordering template, or a draw-only slot whose English
                # does not fit (compositions.json "draw_slots"): a module
                # string (text_names.c)
                entry = {"addr": f"0x{addr:08X}", "max_bytes": mx, "text": text,
                         "encoding": "patch", "module": True,
                         "note": data[off:off + ln].decode("shift_jis", "replace")}
                total += 1
                if target == "main":
                    out["main"].append(entry)
                else:
                    out["overlays"].setdefault(target, []).append(entry)
                continue
            if "{dst}" in text:
                raise SystemExit(f"[ui_strings] {target} 0x{addr:08X}: {{dst}} only works on a "
                                 f"composition piece (config/patch/compositions.json)")
            entry = {"addr": f"0x{addr:08X}", "max_bytes": mx, "text": text,
                     "encoding": "patch", "dte": use_dte,
                     "note": data[off:off + ln].decode("shift_jis", "replace")}
            sites = []
            if target == "main":
                sites = pointer_sites(data, base, addr, 0x800B5A60, 0x800BD250)
            if sites and len(sites) == 1:
                # relocated through its pointer word: no size limit
                entry = {"ptr_at": f"0x{sites[0]:08X}", "text": text, "encoding": "patch",
                         "dte": use_dte, "note": entry["note"]}
            else:
                enc = textcodec.encode(text, dte if use_dte else None)
                if len(enc) > mx:
                    overflow.append((target, addr, len(enc), mx, text))
                    continue
            total += 1
            if target == "main":
                out["main"].append(entry)
            else:
                out["overlays"].setdefault(target, []).append(entry)
    dst = locate(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for t, addr, n, mx, text in overflow:
        print(f"OVERFLOW {t} 0x{addr:08X}: {n} > {mx} bytes: {text!r}")
        print(f"OVERFLOW {t} 0x{addr:08X}: {n} > {mx} bytes: {text!r}", file=sys.stderr)
    print(f"[ui_strings] {total} strings -> {dst.relative_to(ROOT)}; {len(overflow)} do not fit")
    if overflow:
        sys.exit(1)


if __name__ == "__main__":
    main()
