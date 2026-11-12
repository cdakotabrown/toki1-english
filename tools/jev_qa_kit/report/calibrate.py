#!/usr/bin/env python3
"""calibrate.py - how far can Jev's answers be trusted, per question, and
where should each flag threshold sit?  Compares results/results.jsonl
with the hand labels in labels/pilot_labels.csv.

    python3 report/calibrate.py                               # recall-first thresholds
    python3 report/calibrate.py --policy f1                   # best-F1 thresholds
    python3 report/calibrate.py --recall-target 0.9 --min-labels 25

Everything is computed on the PROBLEM event of each question (questions.json
"problem": e.g. meaning_preserved = no, register != matches_voice,
naturalness <= 1) against Jev's P(problem):

  agreement      accuracy and Cohen's kappa at threshold 0.5
  ranking        AUC (P(a problem line scores above a fine line))
  calibration    Brier score, expected calibration error (10 bins) and the
                 reliability curve (mean predicted vs observed per bin)
  thresholds     precision / recall / F1 / flag rate from 0.05 to 0.95
  choice / score accuracy of the top option, confusion matrix / MAE

Writes report/calibration/{calibration.json, calibration_report.md,
calibration_report.html} and report/thresholds.calibrated.json (used by
build_report.py).  A question with fewer than --min-labels labels (or no
positive / no negative label) keeps its default threshold, with a warning.
"""
import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT / "runner"))
import common  # noqa: E402

YES = {"yes", "y", "true", "1", "t"}
NO = {"no", "n", "false", "0", "f"}


def label_problem(q, raw):
    """hand label -> (problem: bool, normalised label) or None if blank / n/a"""
    v = (raw or "").strip()
    if not v or v.lower() in ("n/a", "na", "-", "skip"):
        return None
    pr = q.get("problem", {})
    if q["type"] == "boolean":
        lv = v.lower()
        if lv in YES:
            b = True
        elif lv in NO:
            b = False
        else:
            raise ValueError(f"{q['id']}: {v!r} is not yes/no")
        return (b if pr.get("when") == "true" else not b), ("yes" if b else "no")
    if q["type"] == "choice":
        if v not in q["options"]:
            raise ValueError(f"{q['id']}: {v!r} is not one of {q['options']}")
        return v != pr.get("answer"), v
    if q["type"] == "score":
        x = float(v)
        return x <= float(pr.get("value", 1)), x
    return None


def auc(pairs):
    pos = [p for p, y in pairs if y]
    neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return None
    # rank-sum (ties count half)
    allv = sorted([(p, 1) for p in pos] + [(p, 0) for p in neg])
    ranks = {}
    i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        ranks[allv[i][0]] = (i + j + 1) / 2.0
        i = j
    rs = sum(ranks[p] for p in pos)
    return (rs - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def reliability(pairs, bins=10):
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if sel:
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel),
                        "mean_pred": sum(p for p, _ in sel) / len(sel),
                        "observed": sum(1 for _, y in sel if y) / len(sel)})
    ece = sum(abs(r["mean_pred"] - r["observed"]) * r["n"] for r in out) / max(1, len(pairs))
    return out, ece


def sweep(pairs):
    rows = []
    P = sum(1 for _, y in pairs if y)
    for k in range(1, 20):
        t = k / 20
        tp = sum(1 for p, y in pairs if p >= t and y)
        fp = sum(1 for p, y in pairs if p >= t and not y)
        fn = P - tp
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / P if P else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
        rows.append({"threshold": t, "precision": prec, "recall": rec, "f1": f1,
                     "flag_rate": (tp + fp) / len(pairs), "tp": tp, "fp": fp, "fn": fn})
    return rows


def kappa(pairs, t=0.5):
    n = len(pairs)
    a = sum(1 for p, y in pairs if (p >= t) == y) / n
    py = sum(1 for _, y in pairs if y) / n
    pp = sum(1 for p, _ in pairs if p >= t) / n
    pe = py * pp + (1 - py) * (1 - pp)
    return a, ((a - pe) / (1 - pe) if pe < 1 else None)


def svg_curve(rel, w=220, h=220):
    pts = " ".join(f"{20 + r['mean_pred'] * (w - 30):.1f},{h - 20 - r['observed'] * (h - 30):.1f}" for r in rel)
    dots = "".join(f'<circle cx="{20 + r["mean_pred"] * (w - 30):.1f}" cy="{h - 20 - r["observed"] * (h - 30):.1f}" '
                   f'r="{2 + min(6, math.sqrt(r["n"])):.1f}" fill="currentColor" opacity=".7"/>' for r in rel)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="reliability curve">'
            f'<rect x="20" y="10" width="{w - 30}" height="{h - 30}" fill="none" stroke="#999" stroke-width=".5"/>'
            f'<line x1="20" y1="{h - 20}" x2="{w - 10}" y2="10" stroke="#999" stroke-dasharray="3 3"/>'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>{dots}'
            f'<text x="20" y="{h - 4}" font-size="10" fill="#888">predicted P(problem) →</text>'
            f'<text x="2" y="12" font-size="10" fill="#888">obs</text></svg>')


def fmt(x, d=2):
    return "-" if x is None else f"{x:.{d}f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(KIT / "labels" / "pilot_labels.csv"))
    ap.add_argument("--results", default=None)
    ap.add_argument("--out", default=str(HERE / "calibration"))
    ap.add_argument("--thresholds-out", default=str(HERE / "thresholds.calibrated.json"))
    ap.add_argument("--policy", choices=("recall", "f1"), default="recall",
                    help="recall: the highest threshold that still reaches --recall-target "
                         "(a triage queue should miss little); f1: the best-F1 threshold")
    ap.add_argument("--recall-target", type=float, default=0.85)
    ap.add_argument("--min-labels", type=int, default=20)
    a = ap.parse_args(argv)
    cfg, _ = common.load_config()
    questions = common.load_questions()
    results = common.load_results(common.kit_path(a.results or cfg["results_path"]))
    with open(a.labels, encoding="utf-8", newline="") as fh:
        labels = list(csv.DictReader(fh))
    defaults = json.loads((HERE / "thresholds.json").read_text(encoding="utf-8"))["thresholds"]
    report = {"labels_file": a.labels, "policy": a.policy, "recall_target": a.recall_target, "questions": {}}
    chosen = {}
    md = ["# Calibration report", "",
          f"Labels: `{a.labels}` ({len(labels)} rows). Policy: **{a.policy}**"
          + (f" (recall target {a.recall_target})" if a.policy == "recall" else "") + ".", ""]
    html_parts = []
    bad_labels = []
    for q in questions:
        col = f"label_{q['id']}"
        pairs, extra = [], []
        missing = 0
        for row in labels:
            if col not in row:
                continue
            try:
                lab = label_problem(q, row[col])
            except ValueError as e:
                bad_labels.append(f"{row['line_id']}: {e}")
                continue
            if lab is None:
                continue
            r = results.get((row["line_id"], q["id"], q["version"]))
            if not r:
                missing += 1
                continue
            p = r.get("problem_p")
            if p is None:
                p = common.problem_probability(q, r["answer"])
            pairs.append((float(p), lab[0]))
            extra.append((lab[1], r["answer"]))
        info = {"n": len(pairs), "labelled_but_no_result": missing}
        if not pairs:
            info["note"] = "no labelled lines with results"
            report["questions"][q["id"]] = info
            md += [f"## {q['id']}", "", "No labelled lines with a Jev answer.", ""]
            chosen[q["id"]] = defaults.get(q["id"], 0.5)
            continue
        npos = sum(1 for _, y in pairs if y)
        rel, ece = reliability(pairs)
        brier = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs) / len(pairs)
        acc, kap = kappa(pairs)
        sw = sweep(pairs)
        best = max(sw, key=lambda r: (r["f1"], r["threshold"]))
        rec_ok = [r for r in sw if r["recall"] is not None and r["recall"] >= a.recall_target]
        rec_pick = max(rec_ok, key=lambda r: r["threshold"]) if rec_ok else sw[0]
        info.update({"positives": npos, "base_rate": npos / len(pairs), "accuracy_at_0.5": acc,
                     "kappa_at_0.5": kap, "auc": auc(pairs), "brier": brier, "ece": ece,
                     "reliability": rel, "sweep": sw, "best_f1": best, "recall_pick": rec_pick})
        if q["type"] == "choice":
            top = [(lab, max(ans.get("probs", {"?": 1}), key=ans.get("probs", {"?": 1}).get)) for lab, ans in extra]
            info["top_option_accuracy"] = sum(1 for l_, t in top if l_ == t) / len(top)
            cm = Counter(top)
            info["confusion"] = {f"{l_} -> {t}": n for (l_, t), n in sorted(cm.items())}
        if q["type"] == "score":
            vals = [(lab, ans.get("value")) for lab, ans in extra if ans.get("value") is not None]
            if vals:
                info["mae"] = sum(abs(l_ - v) for l_, v in vals) / len(vals)
                info["exact_rounded"] = sum(1 for l_, v in vals if round(v) == l_) / len(vals)
        enough = len(pairs) >= a.min_labels and 0 < npos < len(pairs)
        pick = (rec_pick if a.policy == "recall" else best)["threshold"] if enough else defaults.get(q["id"], 0.5)
        chosen[q["id"]] = pick
        info["chosen_threshold"] = pick
        info["enough_labels"] = enough
        report["questions"][q["id"]] = info
        md += [f"## {q['id']} ({q['type']})", "",
               f"- labelled lines with an answer: {len(pairs)} (problems: {npos}, base rate "
               f"{100 * npos / len(pairs):.0f}%); labelled but not yet answered: {missing}",
               f"- agreement at 0.5: accuracy {fmt(acc)}, kappa {fmt(kap)}; AUC {fmt(info['auc'])}",
               f"- calibration: Brier {fmt(brier, 3)}, ECE {fmt(ece, 3)}"
               + (f"; top-option accuracy {fmt(info.get('top_option_accuracy'))}" if "top_option_accuracy" in info else "")
               + (f"; MAE {fmt(info.get('mae'))}" if "mae" in info else ""),
               f"- best F1 {fmt(best['f1'])} at {best['threshold']:.2f} (precision {fmt(best['precision'])}, "
               f"recall {fmt(best['recall'])}, flags {100 * best['flag_rate']:.0f}% of lines)",
               f"- recall >= {a.recall_target}: threshold {rec_pick['threshold']:.2f} (precision "
               f"{fmt(rec_pick['precision'])}, recall {fmt(rec_pick['recall'])}, flags "
               f"{100 * rec_pick['flag_rate']:.0f}%)",
               f"- **chosen threshold: {pick:.2f}**" + ("" if enough else
                                                         f" (DEFAULT: fewer than {a.min_labels} labels or one class only)"),
               "", "Reliability (predicted P(problem) vs observed share of problems):", "",
               "| bin | n | mean predicted | observed |", "|---|---:|---:|---:|"]
        md += [f"| {r['bin']} | {r['n']} | {r['mean_pred']:.2f} | {r['observed']:.2f} |" for r in rel]
        md += ["", "| threshold | precision | recall | F1 | flag rate |", "|---:|---:|---:|---:|---:|"]
        md += [f"| {r['threshold']:.2f} | {fmt(r['precision'])} | {fmt(r['recall'])} | {fmt(r['f1'])} | "
               f"{100 * r['flag_rate']:.0f}% |" for r in sw[::2]]
        if info.get("confusion"):
            md += ["", "Confusion (label -> Jev's top option): " +
                   ", ".join(f"{k}: {v}" for k, v in info["confusion"].items())]
        md.append("")
        html_parts.append(f"<section><h2>{q['id']}</h2><p>n={len(pairs)}, problems={npos}, AUC {fmt(info['auc'])}, "
                          f"Brier {fmt(brier, 3)}, ECE {fmt(ece, 3)}, chosen threshold <b>{pick:.2f}</b></p>"
                          f"{svg_curve(rel)}</section>")
    if bad_labels:
        md += ["## Labels that could not be read", ""] + [f"- {b}" for b in bad_labels[:100]]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "calibration.json").write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "calibration_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "calibration_report.html").write_text(
        "<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
        "initial-scale=1'><title>Jev calibration</title><style>:root{--bg:#fff;--fg:#1d1d1b}"
        "@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6}}body{background:var(--bg);"
        "color:var(--fg);font:14px system-ui,sans-serif;margin:16px}section{display:inline-block;vertical-align:top;"
        "margin:0 16px 16px 0;max-width:260px}h2{font-size:15px}</style></head><body><h1>Reliability curves</h1>"
        "<p>Dots above the dashed diagonal: Jev under-predicts problems; below: over-predicts. Dot size = lines "
        "in the bin. Full numbers: calibration_report.md.</p>" + "".join(html_parts) + "</body></html>\n",
        encoding="utf-8")
    Path(a.thresholds_out).write_text(json.dumps({"policy": a.policy, "recall_target": a.recall_target,
                                                  "thresholds": chosen}, indent=1) + "\n", encoding="utf-8")
    print(f"[calibrate] {sum(1 for v in report['questions'].values() if v.get('n'))} questions measured -> "
          f"{out}/calibration_report.md; thresholds -> {a.thresholds_out}"
          + (f"; {len(bad_labels)} unreadable labels" if bad_labels else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
