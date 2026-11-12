#!/usr/bin/env python3
"""build_report.py - turn results/results.jsonl into the review queue.

    python3 report/build_report.py                       # -> report/out/
    python3 report/build_report.py --results results/results.jsonl --out report/out --html-rows 5000

Writes:
  review_queue.csv          every answered line, riskiest first, with the
                            per-question problem probabilities, the reasons
                            it was flagged and WHERE TO EDIT IT (file + key)
  summary_by_character.csv  flagged share per speaker / heroine
  summary_by_scene.csv      flagged share per container
  summary.md                the headline numbers
  report.html               one self-contained page: filters, JP / EN side
                            by side, neighbours, probabilities

Risk: for each answered question p = P(something is wrong) (questions.json
"problem"); risk = mix * max(weight * p) + (1 - mix) * mean(p), and a
deterministic lint finding (token mismatch, Japanese left, too wide)
raises it to at least lint_risk_floor.  A line is FLAGGED for a question
when p >= that question's threshold (report/thresholds.json, or
report/thresholds.calibrated.json from calibrate.py when present).
Standard library only.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT / "runner"))
import common  # noqa: E402


def load_thresholds(path=None):
    base = json.loads((HERE / "thresholds.json").read_text(encoding="utf-8"))
    cal = Path(path) if path else HERE / "thresholds.calibrated.json"
    if cal.exists():
        c = json.loads(cal.read_text(encoding="utf-8"))
        base["thresholds"].update(c.get("thresholds", {}))
        base["_calibrated_from"] = str(cal)
    return base


def score_lines(lines_by_id, results, questions, th):
    qby = {q["id"]: q for q in questions}
    per_line = defaultdict(dict)
    for (lid, qid, ver), r in results.items():
        q = qby.get(qid)
        if not q or q["version"] != ver or lid not in lines_by_id:
            continue
        p = r.get("problem_p")
        if p is None:
            p = common.problem_probability(q, r["answer"])
        per_line[lid][qid] = {"p": p, "answer": r["answer"]}
    rows = []
    for lid, ans in per_line.items():
        l = lines_by_id[lid]
        ps = {k: v["p"] for k, v in ans.items() if v["p"] is not None}
        w = th["weights"]
        mx = max((w.get(k, 1.0) * p for k, p in ps.items()), default=0.0)
        mean = sum(ps.values()) / len(ps) if ps else 0.0
        risk = th["mix"] * mx + (1 - th["mix"]) * mean
        lint = common.lint(l)
        if lint:
            risk = max(risk, th.get("lint_risk_floor", 0.9))
        reasons = [k for k, p in sorted(ps.items(), key=lambda kv: -kv[1])
                   if p >= th["thresholds"].get(k, 0.5)]
        detail = {}
        for k, v in ans.items():
            a = v["answer"]
            if "probs" in a and qby[k]["type"] == "choice":
                detail[k] = max(a["probs"], key=a["probs"].get)
            elif qby[k]["type"] == "score":
                detail[k] = round(a.get("value", 0.0), 2)
            elif "p_true" in a:
                detail[k] = round(a["p_true"], 3)
        rows.append({"line": l, "risk": round(risk, 4), "p": ps, "reasons": reasons, "lint": lint,
                     "detail": detail})
    rows.sort(key=lambda r: (-r["risk"], r["line"]["id"]))
    return rows


def write_csv(rows, questions, out):
    qids = [q["id"] for q in questions]
    with open(out / "review_queue.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "risk", "flagged_by", "lint", "line_id", "container", "girl", "speaker",
                     "kind", "status", "japanese", "english", "edit_file", "edit_key"] +
                    [f"p_{q}" for q in qids] + [f"answer_{q}" for q in qids] + ["scene"])
        for i, r in enumerate(rows, 1):
            l = r["line"]
            w.writerow([i, r["risk"], " ".join(r["reasons"]), " ".join(r["lint"]), l["id"], l["container"],
                        l["scene"].get("girl") or "", l["speaker"].get("name") or
                        f"? ({l['speaker'].get('candidates', '')})", l["kind"], l["status"],
                        l.get("jp_readable") or l["jp"], l.get("en_readable") or l["en"],
                        l["edit"]["file"], l["edit"]["key"]] +
                       [("" if q not in r["p"] else round(r["p"][q], 4)) for q in qids] +
                       [r["detail"].get(q, "") for q in qids] + [l["scene"].get("description", "")[:200]])


def summaries(rows, questions, out):
    qids = [q["id"] for q in questions]

    def table(keyf, name):
        agg = defaultdict(lambda: {"lines": 0, "flagged": 0, "lint": 0, "risk_sum": 0.0,
                                   **{q: 0 for q in qids}})
        for r in rows:
            k = keyf(r["line"])
            a = agg[k]
            a["lines"] += 1
            a["flagged"] += bool(r["reasons"] or r["lint"])
            a["lint"] += bool(r["lint"])
            a["risk_sum"] += r["risk"]
            for q in r["reasons"]:
                a[q] += 1
        with open(out / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "lines", "flagged", "flagged_pct", "mean_risk", "lint"] +
                       [f"flag_{q}" for q in qids])
            for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["flagged"] / max(1, kv[1]["lines"])):
                w.writerow([k, a["lines"], a["flagged"], round(100 * a["flagged"] / max(1, a["lines"]), 1),
                            round(a["risk_sum"] / max(1, a["lines"]), 3), a["lint"]] + [a[q] for q in qids])
        return agg
    by_char = table(lambda l: l["speaker"].get("name") or f"unresolved ({l['scene'].get('girl') or '-'} file)",
                    "summary_by_character.csv")
    by_scene = table(lambda l: l["container"], "summary_by_scene.csv")
    return by_char, by_scene


def write_md(rows, questions, th, by_char, by_scene, out, n_lines_total):
    flagged = [r for r in rows if r["reasons"] or r["lint"]]
    qcount = defaultdict(int)
    for r in rows:
        for q in r["reasons"]:
            qcount[q] += 1
    md = ["# Jev QA triage summary", "",
          f"- lines in the kit: {n_lines_total}",
          f"- lines with at least one answer: {len(rows)}",
          f"- flagged (any question over threshold, or a lint finding): {len(flagged)} "
          f"({100 * len(flagged) / max(1, len(rows)):.1f}%)",
          f"- thresholds: {th.get('_calibrated_from', 'report/thresholds.json (defaults, NOT calibrated)')}",
          "", "## Flags per question", "", "| question | flagged | threshold |", "|---|---:|---:|"]
    for q in questions:
        md.append(f"| {q['id']} | {qcount.get(q['id'], 0)} | {th['thresholds'].get(q['id'], 0.5)} |")
    md += ["", "## Top 25 lines by risk", "", "| risk | id | speaker | EN | why |", "|---:|---|---|---|---|"]
    for r in rows[:25]:
        l = r["line"]
        md.append(f"| {r['risk']:.2f} | `{l['id']}` | {l['speaker'].get('name') or '?'} | "
                  f"{(l.get('en_readable') or '')[:70].replace('|', '/')} | "
                  f"{', '.join(r['reasons'] + r['lint'])} |")
    md += ["", "## Worst scenes (flagged share, >= 20 answered lines)", "", "| container | lines | flagged % |",
           "|---|---:|---:|"]
    worst = sorted(((k, a) for k, a in by_scene.items() if a["lines"] >= 20),
                   key=lambda kv: -kv[1]["flagged"] / kv[1]["lines"])[:20]
    for k, a in worst:
        md.append(f"| {k} | {a['lines']} | {100 * a['flagged'] / a['lines']:.1f} |")
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jev QA review queue</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e3e0d8;--card:#fff;--hi:#b3261e;--mid:#b26b00;--lo:#2e7d32;--acc:#284b8f}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--mut:#a3a19a;--line:#33322f;--card:#1f1f1d;--hi:#ff8a80;--mid:#ffb74d;--lo:#81c784;--acc:#9bb7f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:16px;border-bottom:1px solid var(--line)}h1{font-size:18px;margin:0 0 4px}.mut{color:var(--mut)}
.bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);max-width:100%}
main{padding:12px 16px}.row{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:0 0 10px;padding:10px 12px}
.head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}.risk{font-weight:700;min-width:3.2em}.r-hi{color:var(--hi)}.r-mid{color:var(--mid)}.r-lo{color:var(--lo)}
.id{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--mut);word-break:break-all}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:6px}@media (max-width:700px){.pair{grid-template-columns:1fr}}
.jp,.en{white-space:pre-wrap;word-break:break-word}.lab{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
.tags span{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin:2px 4px 0 0}
.tags .flag{border-color:var(--hi);color:var(--hi)}.ps{font-size:12px;color:var(--mut);margin-top:6px}
details{margin-top:6px}summary{cursor:pointer;color:var(--acc)}table{border-collapse:collapse;width:100%;font-size:12px}td{border-top:1px solid var(--line);padding:3px 4px;vertical-align:top}
#more{margin:8px 0 24px;padding:8px 14px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg);cursor:pointer}
</style></head><body>
<header><h1>Jev QA review queue</h1><div class="mut" id="sub"></div></header>
<div class="bar">
<input id="q" placeholder="search JP / EN / id" size="24">
<select id="cont"><option value="">all containers</option></select>
<select id="girl"><option value="">all heroines</option></select>
<select id="spk"><option value="">all speakers</option></select>
<select id="flag"><option value="">any / no flag</option><option value="__any">flagged only</option><option value="__lint">lint finding</option></select>
<select id="st"><option value="">all statuses</option></select>
<label class="mut">min risk <input id="min" type="number" min="0" max="1" step="0.05" value="0" style="width:5em"></label>
</div>
<main><div id="count" class="mut"></div><div id="list"></div><button id="more">show more</button></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const R=D.rows;let shown=200;
const $=id=>document.getElementById(id);
$('sub').textContent=D.meta;
function fill(id,vals){const s=$(id);[...new Set(vals)].filter(Boolean).sort().forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;s.appendChild(o)})}
fill('cont',R.map(r=>r.c));fill('girl',R.map(r=>r.g));fill('spk',R.map(r=>r.s));fill('st',R.map(r=>r.st));
D.questions.forEach(q=>{const o=document.createElement('option');o.value=q;o.textContent='flag: '+q;$('flag').appendChild(o)});
function esc(t){return (t==null?'':String(t)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function cls(x){return x>=.66?'r-hi':x>=.33?'r-mid':'r-lo'}
function filt(){const q=$('q').value.toLowerCase(),c=$('cont').value,g=$('girl').value,s=$('spk').value,f=$('flag').value,st=$('st').value,m=parseFloat($('min').value)||0;
return R.filter(r=>(!q||(r.jp+' '+r.en+' '+r.id).toLowerCase().includes(q))&&(!c||r.c===c)&&(!g||r.g===g)&&(!s||r.s===s)&&(!st||r.st===st)&&r.risk>=m&&
(!f||(f==='__any'?(r.why.length||r.lint.length):f==='__lint'?r.lint.length:r.why.includes(f))))}
function render(){const L=filt();$('count').textContent=L.length+' of '+R.length+' lines';const out=[];
L.slice(0,shown).forEach(r=>{const nb=(r.nb||[]).map(n=>'<tr><td>'+esc(n.w)+'</td><td>'+esc(n.s)+'</td><td>'+esc(n.jp)+'</td><td>'+esc(n.en)+'</td></tr>').join('');
out.push('<div class="row"><div class="head"><span class="risk '+cls(r.risk)+'">'+r.risk.toFixed(2)+'</span><b>'+esc(r.s||'?')+'</b><span class="mut">'+esc(r.k)+' · '+esc(r.st)+(r.g?' · '+esc(r.g):'')+'</span><span class="id">'+esc(r.id)+'</span></div>'+
'<div class="pair"><div><div class="lab">Japanese</div><div class="jp">'+esc(r.jp)+'</div></div><div><div class="lab">English (as shipped)</div><div class="en">'+esc(r.en)+'</div></div></div>'+
'<div class="tags">'+r.why.map(w=>'<span class="flag">'+esc(w)+'</span>').join('')+r.lint.map(w=>'<span class="flag">lint: '+esc(w)+'</span>').join('')+'</div>'+
'<div class="ps">'+Object.entries(r.p).map(([k,v])=>esc(k)+' '+v.toFixed(2)).join(' · ')+'</div>'+
'<details><summary>context & where to edit</summary><div class="mut">'+esc(r.scene)+'</div><div>edit: <span class="id">'+esc(r.ef)+' — '+esc(r.ek)+'</span></div>'+(nb?'<table>'+nb+'</table>':'')+'</details></div>')});
$('list').innerHTML=out.join('');$('more').style.display=L.length>shown?'':'none'}
['q','cont','girl','spk','flag','st','min'].forEach(id=>$(id).addEventListener('input',()=>{shown=200;render()}));
$('more').onclick=()=>{shown+=200;render()};render();
</script></body></html>
"""


def write_html(rows, questions, out, max_rows, meta):
    data = []
    for r in rows[:max_rows]:
        l = r["line"]
        nb = [{"w": "before", "s": n.get("speaker"), "jp": n.get("jp"), "en": n.get("en")}
              for n in l.get("neighbours", {}).get("prev", [])]
        nb += [{"w": "THIS", "s": l["speaker"].get("name"), "jp": l["jp"], "en": l["en"]}]
        nb += [{"w": "after", "s": n.get("speaker"), "jp": n.get("jp"), "en": n.get("en")}
               for n in l.get("neighbours", {}).get("next", [])]
        data.append({"id": l["id"], "risk": r["risk"], "why": r["reasons"], "lint": r["lint"],
                     "p": {k: round(v, 3) for k, v in r["p"].items()},
                     "c": l["container"], "g": l["scene"].get("girl") or "",
                     "s": l["speaker"].get("name") or "", "k": l["kind"], "st": l["status"],
                     "jp": l.get("jp_readable") or l["jp"], "en": l.get("en_readable") or l["en"],
                     "scene": l["scene"].get("description", ""), "ef": l["edit"]["file"],
                     "ek": l["edit"]["key"], "nb": nb})
    blob = json.dumps({"rows": data, "questions": [q["id"] for q in questions], "meta": meta},
                      ensure_ascii=False).replace("</", "<\\/")
    (out / "report.html").write_text(HTML.replace("__DATA__", blob), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=None, help="results.jsonl (default from config.json)")
    ap.add_argument("--lines", default=None)
    ap.add_argument("--questions-file", default=None)
    ap.add_argument("--thresholds", default=None, help="a calibrated thresholds file")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--html-rows", type=int, default=5000, help="riskiest N lines in report.html")
    a = ap.parse_args(argv)
    cfg, _ = common.load_config()
    results = common.load_results(common.kit_path(a.results or cfg["results_path"]))
    lines = common.load_lines(a.lines)
    by_id = {l["id"]: l for l in lines}
    questions = common.load_questions(Path(a.questions_file) if a.questions_file else None)
    th = load_thresholds(a.thresholds)
    rows = score_lines(by_id, results, questions, th)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(rows, questions, out)
    by_char, by_scene = summaries(rows, questions, out)
    write_md(rows, questions, th, by_char, by_scene, out, len(lines))
    meta = (f"{len(rows)} answered lines of {len(lines)}; thresholds: "
            f"{th.get('_calibrated_from', 'defaults (not calibrated)')}; showing the riskiest {min(len(rows), a.html_rows)}")
    write_html(rows, questions, out, a.html_rows, meta)
    flagged = sum(1 for r in rows if r["reasons"] or r["lint"])
    print(f"[report] {len(rows)} lines scored, {flagged} flagged -> {out}/review_queue.csv, "
          f"summary.md, report.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
