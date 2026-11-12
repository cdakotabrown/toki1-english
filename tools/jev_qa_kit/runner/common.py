"""Shared pieces of the Jev QA kit: config, lines, context, the per-question
state builder, predicates, filters, stratified sampling, the results store
and the deterministic lint.  Python 3.8+, standard library only."""
import fnmatch
import json
import random
import re
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "backend": "mock",
    "workers": 4,
    "rate_limit_per_sec": 5.0,
    "max_retries": 5,
    "backoff_base_sec": 1.0,
    "backoff_max_sec": 60.0,
    "timeout_sec": 60.0,
    "state_format": "json",
    "results_path": "results/results.jsonl",
    "errors_path": "results/errors.jsonl",
    "store_raw_response": False,
    "progress_every_sec": 5.0,
    "estimate": {"seconds_per_call": 1.0, "cost_per_call": 0.0, "currency": "USD"},
    "http": {},
    "custom": {},
}


def deep_merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path=None):
    """config.json (or config.toml when Python has tomllib), merged over the
    defaults; ${ENV} in strings is expanded at request time, not here"""
    cands = [Path(path)] if path else [KIT / "config.toml", KIT / "config.json"]
    for p in cands:
        if not p.exists():
            continue
        if p.suffix == ".toml":
            try:
                import tomllib
            except ImportError:
                if path:
                    raise SystemExit(f"{p}: TOML needs Python 3.11+ (tomllib); use config.json")
                continue
            with open(p, "rb") as fh:
                return deep_merge(DEFAULT_CONFIG, tomllib.load(fh)), p
        return deep_merge(DEFAULT_CONFIG, json.loads(p.read_text(encoding="utf-8"))), p
    return dict(DEFAULT_CONFIG), None


def kit_path(p):
    p = Path(p)
    return p if p.is_absolute() else KIT / p


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

def load_lines(path=None):
    path = Path(path) if path else KIT / "data" / "lines.jsonl"
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_questions(path=None):
    path = Path(path) if path else KIT / "questions" / "questions.json"
    q = json.loads(path.read_text(encoding="utf-8"))
    for item in q["questions"]:
        item.setdefault("version", 1)
    return q["questions"]


class Context:
    """the context files a state may quote (voice notes, style excerpts)"""

    def __init__(self, kit=KIT):
        ctx = kit / "context"
        self.bibles = json.loads((ctx / "characters" / "index.json").read_text(encoding="utf-8"))
        self.style = json.loads((ctx / "style_excerpts.json").read_text(encoding="utf-8"))
        self.policy = condense_policy(self.style.get("names_honorifics", ""))
        self.tone = condense_tone(self.style.get("voice_principles", ""))


def condense_policy(sec):
    """STYLE-GUIDE section 3, the bullets about honorifics and address"""
    keep = []
    for para in re.split(r"\n(?=- )", sec):
        if re.search(r"[Hh]onorific|Senpai|先輩|先生|address|token|name", para):
            keep.append(re.sub(r"\s+", " ", para).strip())
    return "\n".join(keep)[:1800]


def condense_tone(sec):
    keep = []
    for para in re.split(r"\n(?=\d\. )", sec):
        if re.match(r"(2|4|5|6)\. ", para.strip()):
            keep.append(re.sub(r"\s+", " ", para).strip())
    return "\n".join(keep)[:1500]


ALLOWED_TERMS = ["Senpai (Yumi Saotome only)", "Sensei (coaches)", "giri-choco", "bunkasai",
                 "omikuji", "prf (the in-game band)", "Kirameki High"]
TOKEN_LEGEND = {
    "[PLAYER, as she addresses him]": "the player's name in the form this heroine uses",
    "[HEROINE'S GIVEN NAME]": "the current heroine's given name",
    "[PLAYER'S FAMILY NAME]": "the player's family name",
    "[PLAYER'S GIVEN NAME]": "the player's given name",
    "[PLAYER'S FULL NAME]": "the player's full name",
    "[RUNTIME TEXT S]": "text the scene fills in (subject, year, item...)",
    "[COMPOSED TEXT]": "the piece the game splices in here",
    " / ": "a line break in the message box",
    "Reply N:": "one entry of the player's reply menu",
    "Alt N:": "one of several alternative lines; the game shows one",
}
HONORIFIC_JP = re.compile(r"さん|君|くん|ちゃん|先輩|先生|様|さま")
HONORIFIC_EN = re.compile(r"-(san|kun|chan|sama|senpai|sensei)\b|\b(senpai|sensei)\b", re.I)
DIALOGUE_KINDS = {"line", "choice", "alternatives", "tagged"}


def speaker_label(line):
    s = line["speaker"]
    if s.get("name"):
        return f"{s['name']} ({s.get('role')})"
    return f"unknown speaker (candidates: {s.get('candidates', 'unknown')})"


def short_scene(line):
    sc = line["scene"]
    d = sc.get("description") or ""
    d = d if len(d) <= 220 else d[:217] + "..."
    girl = f" Heroine: {sc['girl']}." if sc.get("girl") else ""
    return f"{d}{girl}"


def nb_text(n):
    who = n.get("speaker") or "?"
    return {"speaker": who, "jp": n.get("jp"), "en": n.get("en")}


def split_replies(text):
    return [t.strip() for t in (text or "").split("{opt}")]


def readable_simple(text):
    t = (text or "").replace("{br}", " / ")
    for k, v in (("{P}", "[PLAYER, as she addresses him]"), ("{G}", "[HEROINE'S GIVEN NAME]"),
                 ("{p}", "[PLAYER'S FAMILY NAME]"), ("{m}", "[PLAYER'S GIVEN NAME]"),
                 ("{F}", "[PLAYER'S FULL NAME]"), ("{Y}", "Yoshio")):
        t = t.replace(k, v)
    return re.sub(r"\{([SOWAM])\}", r"[RUNTIME TEXT \1]", t)


# ---------------------------------------------------------------------------
# predicates (questions.json applies_when)
# ---------------------------------------------------------------------------

PREDICATES = {
    "always": lambda l, ctx: True,
    "has_english": lambda l, ctx: bool((l.get("en") or "").strip()),
    "speaker_has_voice_note": lambda l, ctx: bool(l["speaker"].get("bible")) and
    l["speaker"]["bible"] in ctx.bibles,
    "is_dialogue": lambda l, ctx: l["kind"] in DIALOGUE_KINDS,
    "has_glossary_hits": lambda l, ctx: bool(l.get("glossary_hits")),
    "has_honorific_signal": lambda l, ctx: bool(HONORIFIC_JP.search(l.get("jp") or "")) or
    bool(HONORIFIC_EN.search(l.get("en") or "")),
    "is_reply_menu": lambda l, ctx: l["kind"] == "choice" and len(split_replies(l.get("en"))) >= 2,
}


def applies(q, line, ctx):
    for p in q.get("applies_when", ["always"]):
        if p not in PREDICATES:
            raise SystemExit(f"questions.json: {q['id']}: unknown predicate {p!r} "
                             f"(known: {', '.join(sorted(PREDICATES))})")
        if not PREDICATES[p](line, ctx):
            return False
    return True


# ---------------------------------------------------------------------------
# state fields
# ---------------------------------------------------------------------------

def field_value(name, line, ctx):
    nbs = line.get("neighbours") or {"prev": [], "next": []}
    if name == "jp_readable":
        return line.get("jp_readable") or line.get("jp")
    if name == "en_readable":
        return line.get("en_readable") or line.get("en")
    if name == "en_raw":
        return line.get("en")
    if name == "kind":
        return {"line": "dialogue line", "choice": "player reply menu",
                "alternatives": "alternative lines (the game shows one)",
                "tagged": "dialogue line with a speaker label", "ui": "UI / system text",
                "art": "text lettered into a picture", "composition": "text the game assembles from pieces"
                }.get(line["kind"], line["kind"])
    if name == "speaker":
        return speaker_label(line)
    if name == "speaker_role":
        return line["speaker"].get("role")
    if name == "voice_note":
        b = ctx.bibles.get(line["speaker"].get("bible") or "")
        if not b:
            return None
        return {"character": b["title"], "role": b["role"], "japanese_voice": b["japanese_voice"],
                "english_voice": b["english_voice"]}
    if name == "previous_line":
        p = nbs["prev"][-1:] if nbs["prev"] else []
        return [nb_text(x) for x in p] or None
    if name == "previous_lines":
        return [nb_text(x) for x in nbs["prev"][-2:]] or None
    if name == "neighbours_short":
        return {"before": [nb_text(x) for x in nbs["prev"][-2:]],
                "after": [nb_text(x) for x in nbs["next"][:1]]}
    if name == "neighbours_full":
        return {"before": [nb_text(x) for x in nbs["prev"]], "after": [nb_text(x) for x in nbs["next"]]}
    if name == "token_legend":
        text = (line.get("en_readable") or "") + "\n" + (line.get("jp_readable") or "")
        used = {}
        for k, v in TOKEN_LEGEND.items():
            probe = {"Reply N:": "Reply 1:", "Alt N:": "Alt 1:",
                     "[RUNTIME TEXT S]": "[RUNTIME TEXT"}.get(k, k)
            if probe in text:
                used[k] = v
        return used or None
    if name == "glossary_entries":
        return [{"japanese": g["jp"], "english": g["en"], "note": g.get("notes") or ""}
                for g in line.get("glossary_hits", [])]
    if name == "scene_short":
        return short_scene(line)
    if name == "allowed_japanese_terms":
        return ALLOWED_TERMS
    if name == "policy_excerpt":
        return ctx.policy
    if name == "tone_principles":
        return ctx.tone
    if name == "tokens":
        return line.get("tokens") or []
    if name == "jp_replies":
        return [readable_simple(x) for x in split_replies(line.get("jp"))]
    if name == "en_replies":
        return [readable_simple(x) for x in split_replies(line.get("en"))]
    if name == "known_flags":
        return [f"{f['flag']}: {f['detail']}"[:200] for f in line.get("flags", [])] or None
    if name == "constraints":
        return line.get("constraints")
    raise SystemExit(f"unknown state field {name!r}")


def build_state(q, line, ctx, fmt="json"):
    st = OrderedDict()
    for f in q["state_fields"]:
        v = field_value(f, line, ctx)
        if v not in (None, [], {}, ""):
            st[f] = v
    if q.get("guidance"):
        st["guidance"] = q["guidance"]
    if fmt == "text":
        return state_as_text(st)
    return st


def state_as_text(st):
    out = []
    for k, v in st.items():
        label = k.replace("_", " ").capitalize()
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, indent=1)
        out.append(f"{label}:\n{v}")
    return "\n\n".join(out)


def question_payload(q):
    """the question as the backend sees it"""
    p = {"id": q["id"], "type": q["type"], "question": q["question"]}
    if q["type"] == "choice":
        p["options"] = q["options"]
        if q.get("option_descriptions"):
            p["option_descriptions"] = q["option_descriptions"]
    if q["type"] == "score":
        p["scale"] = q["scale"]
        if q.get("scale_labels"):
            p["scale_labels"] = q["scale_labels"]
    return p


# ---------------------------------------------------------------------------
# filters, work list, sampling
# ---------------------------------------------------------------------------

def match_any(value, patterns):
    value = value or ""
    return any(fnmatch.fnmatch(value, p) or value.startswith(p) or value == p for p in patterns)


def filter_lines(lines, a):
    out = []
    ids = None
    if getattr(a, "ids_file", None):
        ids = {l.strip() for l in Path(a.ids_file).read_text(encoding="utf-8").splitlines() if l.strip()}
    for l in lines:
        if ids is not None and l["id"] not in ids:
            continue
        if a.container and not match_any(l["container"], a.container):
            continue
        if a.girl:
            g = l["scene"].get("girl") or ""
            code = l["scene"].get("girl_code") or ""
            if not any(x.lower() in (g.lower(), code.lower()) or x.lower() in g.lower() for x in a.girl):
                continue
        if a.status and l["status"] not in a.status and l["status_class"] not in a.status:
            continue
        if a.source_kind and l["source_kind"] not in a.source_kind:
            continue
        if a.kind and l["kind"] not in a.kind:
            continue
        if a.speaker and not any(x.lower() in (l["speaker"].get("name") or "").lower() for x in a.speaker):
            continue
        out.append(l)
    return out


def stratum(l):
    return (l["group"], l["status_class"], l["speaker"].get("role"), l["kind"])


def stratified_sample(lines, n, seed=1234):
    """n lines, every stratum (group x status x speaker role x kind)
    represented in proportion with at least one line each (while n allows)"""
    if n >= len(lines):
        return list(lines)
    rng = random.Random(seed)
    by = defaultdict(list)
    for l in lines:
        by[stratum(l)].append(l)
    keys = sorted(by, key=lambda k: (-len(by[k]), k))
    total = len(lines)
    alloc = {k: max(1, round(n * len(by[k]) / total)) for k in keys}
    # trim the largest strata until the sum fits, then top up
    while sum(alloc.values()) > n:
        k = max((k for k in keys if alloc[k] > 1), key=lambda k: alloc[k], default=None)
        if k is None:
            # more strata than n: keep the n biggest strata, one each
            alloc = {k: (1 if i < n else 0) for i, k in enumerate(keys)}
            break
        alloc[k] -= 1
    i = 0
    while sum(alloc.values()) < n:
        k = keys[i % len(keys)]
        if alloc[k] < len(by[k]):
            alloc[k] += 1
        i += 1
    out = []
    for k in keys:
        pool = by[k]
        out += rng.sample(pool, min(alloc[k], len(pool)))
    out.sort(key=lambda l: l["id"])
    return out


def work_items(lines, questions, ctx, qids=None):
    """[(line, question)] the run would ask"""
    qs = [q for q in questions if not qids or q["id"] in qids]
    return [(l, q) for l in lines for q in qs if applies(q, l, ctx)]


def item_key(line_id, q):
    return f"{line_id}\t{q['id']}\tv{q['version']}"


# ---------------------------------------------------------------------------
# results store (append-only, resumable)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, path, errors_path):
        self.path = Path(path)
        self.errors_path = Path(errors_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.errors_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.done = set()
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for l in fh:
                    try:
                        r = json.loads(l)
                    except ValueError:
                        continue            # a torn last line from a killed run
                    self.done.add(f"{r['line_id']}\t{r['question_id']}\tv{r['question_version']}")

    def write(self, rec):
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.done.add(f"{rec['line_id']}\t{rec['question_id']}\tv{rec['question_version']}")

    def error(self, rec):
        with self.lock:
            with open(self.errors_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_results(path):
    """latest answer per (line id, question id, version)"""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, encoding="utf-8") as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except ValueError:
                continue
            out[(r["line_id"], r["question_id"], r["question_version"])] = r
    return out


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, per_sec):
        self.interval = 1.0 / per_sec if per_sec and per_sec > 0 else 0.0
        self.lock = threading.Lock()
        self.next = time.monotonic()

    def wait(self):
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.interval
        if t > now:
            time.sleep(t - now)


# ---------------------------------------------------------------------------
# answers: normalised form + the "problem" probability
# ---------------------------------------------------------------------------

def problem_probability(q, ans):
    """P(something is wrong) from a normalised answer"""
    pr = q.get("problem", {})
    if q["type"] == "boolean":
        p = ans.get("p_true")
        if p is None:
            return None
        return p if pr.get("when") == "true" else 1.0 - p
    if q["type"] == "choice":
        probs = ans.get("probs") or {}
        if not probs:
            return None
        ok = pr.get("answer")
        return 1.0 - float(probs.get(ok, 0.0))
    if q["type"] == "score":
        probs = ans.get("probs")
        limit = pr.get("value", 1)
        if probs:
            return sum(float(v) for k, v in probs.items() if float(k) <= limit)
        v = ans.get("value")
        if v is None:
            return None
        lo, hi = min(q["scale"]), max(q["scale"])
        return max(0.0, min(1.0, (hi - v) / (hi - lo)))
    return None


# ---------------------------------------------------------------------------
# deterministic lint (no model involved)
# ---------------------------------------------------------------------------

JP_RE = re.compile(r"[぀-ヿ一-鿿]")
TOK_RE = re.compile(r"\{(?:opt|P|G|p|m|F|Y|S|O|W|A|M)\}")


def lint(line):
    """findings that need no model: tokens, Japanese left, widths"""
    out = []
    en, jp = line.get("en") or "", line.get("jp") or ""
    if line["kind"] in DIALOGUE_KINDS and Counter(TOK_RE.findall(en)) != Counter(TOK_RE.findall(jp)):
        out.append("token_mismatch")
    if JP_RE.search(en) and line["kind"] not in ("art",):
        out.append("japanese_in_english")
    c = line.get("constraints") or {}
    mx = c.get("max_px_per_row")
    if line["kind"] == "choice" and mx and any(px > mx * c.get("rows_per_reply", 1) for px in c.get("reply_px", [])):
        out.append("reply_too_wide")
    if c.get("widest_row_px") and mx and c["widest_row_px"] > mx:
        out.append("row_too_wide")
    if "  " in en.replace("{br}", " ").strip():
        out.append("double_space")
    for f in line.get("flags", []):
        if f["flag"] in ("token_mismatch_kept_japanese", "choice_too_wide", "japanese_in_english",
                         "render_error", "speaker_suspect"):
            out.append(f["flag"])
    return sorted(set(out))
