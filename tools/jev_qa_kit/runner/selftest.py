#!/usr/bin/env python3
"""selftest.py - the whole pipeline end to end, offline, in a temporary
directory (nothing is left behind and the kit's results/ is untouched):

  1. data      lines.jsonl schema, unique ids, questions.json predicates
  2. estimate  the full-run call count
  3. dry run   states for a sample
  4. mock run  a stratified sample, then a rerun that must resume (0 to do)
  5. http      the http backend against an in-process loopback server that
               speaks the DEFAULT request/response mapping of config.json
               (single and batched requests); 127.0.0.1 only
  6. report    review_queue.csv, summaries, report.html
  7. calibrate a label sheet filled with synthetic labels -> thresholds

    python3 runner/selftest.py [--sample 60]

Exit status 0 when every step passed.
"""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(KIT / "report"))
import common  # noqa: E402
import run as runner  # noqa: E402

REQUIRED = ["id", "source_kind", "group", "container", "scene", "speaker", "kind", "jp", "en",
            "en_readable", "status", "status_class", "edit", "constraints", "flags", "neighbours",
            "seq", "glossary_hits", "tokens"]
RESULTS = []


def step(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[selftest] {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def quiet(fn, *a, **k):
    buf_o, buf_e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
        rc = fn(*a, **k)
    return rc, buf_o.getvalue(), buf_e.getvalue()


class FakeJev(BaseHTTPRequestHandler):
    """answers in the shape config.json's default http mapping expects"""

    def log_message(self, *a):
        pass

    def answer(self, q, state):
        u = int(hashlib.sha256(json.dumps([q, state], sort_keys=True, ensure_ascii=False)
                               .encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if q["type"] == "boolean":
            return {"id": q["id"], "probability": round(u, 4)}
        if q["type"] == "choice":
            ps = [1.0 + u] + [0.2] * (len(q["options"]) - 1)
            s = sum(ps)
            return {"id": q["id"], "probabilities": {o: p / s for o, p in zip(q["options"], ps)}}
        return {"id": q["id"], "value": 3 * u}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        if "items" in body:
            out = {"results": [{"answers": [self.answer(q, it["state"]) for q in it["questions"]]}
                               for it in body["items"]]}
        else:
            out = {"answers": [self.answer(q, body["state"]) for q in body["questions"]]}
        data = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--keep", action="store_true", help="keep the temporary directory")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="jev-selftest-"))
    t0 = time.time()
    try:
        # 1. data
        lines = common.load_lines()
        ids = [l["id"] for l in lines]
        missing = [k for k in REQUIRED if any(k not in l for l in lines[:2000])]
        step("lines.jsonl schema", not missing and len(ids) == len(set(ids)) and
             all(l["en"] for l in lines), f"{len(lines)} lines, missing keys {missing}" if missing
             else f"{len(lines)} lines, ids unique, every line has English")
        questions = common.load_questions()
        ctx = common.Context()
        for q in questions:
            common.applies(q, lines[0], ctx)
            common.build_state(q, lines[0], ctx)
        step("questions.json", True, f"{len(questions)} questions, predicates and state fields resolve")

        # 2. estimate
        rc, out, _ = quiet(runner.main, ["--estimate", "--results", str(tmp / "est.jsonl")])
        calls = [l for l in out.splitlines() if l.startswith("calls")]
        step("estimate (full run)", rc == 0 and bool(calls), calls[0] if calls else out[-200:])

        # 3. dry run
        rc, out, _ = quiet(runner.main, ["--dry-run", "--sample", "30", "--results", str(tmp / "dry.jsonl"),
                                         "--dry-run-out", str(tmp / "states.jsonl")])
        n_states = sum(1 for _ in open(tmp / "states.jsonl", encoding="utf-8"))
        step("dry run", rc == 0 and n_states > 0, out.strip())

        # 4. mock run + resume
        res = tmp / "mock" / "results.jsonl"
        rc, _, err = quiet(runner.main, ["--backend", "mock", "--sample", str(a.sample), "--results", str(res),
                                         "--quiet"])
        n1 = sum(1 for _ in open(res, encoding="utf-8"))
        rc2, out2, _ = quiet(runner.main, ["--backend", "mock", "--sample", str(a.sample), "--results",
                                           str(res), "--quiet"])
        n2 = sum(1 for _ in open(res, encoding="utf-8"))
        step("mock run", rc == 0 and n1 > 0, f"{n1} answers for a {a.sample}-line stratified sample")
        step("resume (rerun asks nothing)", rc2 == 0 and n2 == n1 and "nothing to do" in out2, out2.strip())

        # 5. http backend against a loopback fake
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeJev)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            cfg = json.loads((KIT / "config.json").read_text(encoding="utf-8"))
            cfg["backend"] = "http"
            cfg["http"]["endpoint"] = f"http://127.0.0.1:{srv.server_address[1]}/v1/classify"
            cfg["rate_limit_per_sec"] = 0
            cfgp = tmp / "config.http.json"
            cfgp.write_text(json.dumps(cfg), encoding="utf-8")
            hres = tmp / "http" / "results.jsonl"
            rc, _, err = quiet(runner.main, ["--config", str(cfgp), "--sample", "12", "--results", str(hres),
                                             "--quiet"])
            got = [json.loads(l) for l in open(hres, encoding="utf-8")] if hres.exists() else []
            ok = rc == 0 and got and all(r["problem_p"] is not None for r in got)
            step("http backend (default mapping, single)", bool(ok), f"{len(got)} answers" + (f"; {err[-300:]}" if not ok else ""))
            cfg["http"]["batch_size"] = 4
            cfgp.write_text(json.dumps(cfg), encoding="utf-8")
            bres = tmp / "http_batch" / "results.jsonl"
            rc, _, err = quiet(runner.main, ["--config", str(cfgp), "--sample", "12", "--results", str(bres),
                                             "--quiet"])
            gotb = [json.loads(l) for l in open(bres, encoding="utf-8")] if bres.exists() else []
            same = sorted((r["line_id"], r["question_id"], json.dumps(r["answer"], sort_keys=True)) for r in got) == \
                sorted((r["line_id"], r["question_id"], json.dumps(r["answer"], sort_keys=True)) for r in gotb)
            step("http backend (batch_size 4)", rc == 0 and same, f"{len(gotb)} answers, identical to single: {same}")
        finally:
            srv.shutdown()
            srv.server_close()

        # 6. report
        import build_report
        rep = tmp / "report"
        rc, out, _ = quiet(build_report.main, ["--results", str(res), "--out", str(rep),
                                               "--thresholds", str(tmp / "none.json")])
        files = ["review_queue.csv", "summary_by_character.csv", "summary_by_scene.csv", "summary.md", "report.html"]
        have = [f for f in files if (rep / f).exists()]
        with open(rep / "review_queue.csv", encoding="utf-8") as fh:
            q_rows = list(csv.DictReader(fh))
        step("report", rc == 0 and len(have) == len(files) and len(q_rows) > 0,
             f"{len(q_rows)} rows in review_queue.csv; {out.strip()}")

        # 7. labels + calibration (synthetic labels: mock answer, 15 % flipped)
        import make_label_template
        import calibrate
        lab = tmp / "labels.csv"
        idsf = tmp / "ids.txt"
        rc, _, _ = quiet(make_label_template.main, ["--n", "60", "--out", str(lab), "--ids-out", str(idsf)])
        cres = tmp / "cal" / "results.jsonl"
        quiet(runner.main, ["--backend", "mock", "--ids-file", str(idsf), "--results", str(cres), "--quiet"])
        answers = common.load_results(cres)
        with open(lab, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
            cols = list(rows[0].keys())
        filled = 0
        for r in rows:
            for q in questions:
                col = f"label_{q['id']}"
                if r[col] == "n/a":
                    continue
                ans = answers.get((r["line_id"], q["id"], q["version"]))
                if not ans:
                    continue
                flip = int(hashlib.md5((r["line_id"] + q["id"]).encode()).hexdigest()[:2], 16) < 38
                prob = ans["problem_p"] >= 0.5
                problem = prob != flip
                if q["type"] == "boolean":
                    yes = problem if q["problem"]["when"] == "true" else not problem
                    r[col] = "yes" if yes else "no"
                elif q["type"] == "choice":
                    r[col] = q["options"][1] if problem else q["problem"]["answer"]
                else:
                    r[col] = "1" if problem else "3"
                filled += 1
        with open(lab, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        thr = tmp / "thresholds.calibrated.json"
        rc, out, _ = quiet(calibrate.main, ["--labels", str(lab), "--results", str(cres), "--out",
                                            str(tmp / "calibration"), "--thresholds-out", str(thr),
                                            "--min-labels", "5"])
        okc = rc == 0 and thr.exists() and (tmp / "calibration" / "calibration_report.md").exists()
        step("labels + calibration", okc, f"{filled} synthetic labels; {out.strip()}")
        rc, out, _ = quiet(build_report.main, ["--results", str(res), "--out", str(tmp / "report2"),
                                               "--thresholds", str(thr)])
        step("report with calibrated thresholds", rc == 0, out.strip())
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        step("unexpected exception", False, f"{type(e).__name__}: {e}")
    finally:
        if a.keep:
            print(f"[selftest] kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    bad = [r for r in RESULTS if not r[1]]
    print(f"[selftest] {len(RESULTS) - len(bad)}/{len(RESULTS)} steps passed in {time.time() - t0:.1f} s "
          f"(mock backend: the answers are fake; this tests the plumbing, not the translation)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
