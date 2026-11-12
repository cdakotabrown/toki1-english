#!/usr/bin/env python3
"""run.py - ask Jev the triage questions about the English script.

    python3 runner/run.py --estimate                      # calls, time, cost; asks nothing
    python3 runner/run.py --dry-run --sample 20           # write the states it WOULD send
    python3 runner/run.py --sample 200 --backend mock     # a pilot on the fake backend
    python3 runner/run.py --ids-file labels/pilot_ids.txt # exactly the hand-labelled pilot
    python3 runner/run.py                                 # everything (resumes)

Results go to results/results.jsonl, one JSON object per (line, question,
question version), append-only: a rerun skips what is done, so Ctrl-C and
start again at any time.  Failed items go to results/errors.jsonl and are
retried by the next run.  Standard library only.
"""
import argparse
import concurrent.futures as cf
import json
import random
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from backends import RetryableError, get_backend  # noqa: E402


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="config.json / config.toml (default: the kit's)")
    ap.add_argument("--backend", help="override config backend: mock | http | custom")
    ap.add_argument("--lines", help="lines.jsonl (default data/lines.jsonl)")
    ap.add_argument("--questions-file", help="questions.json (default questions/questions.json)")
    ap.add_argument("--results", help="results.jsonl (default from config)")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--rate", type=float, help="requests per second (all workers)")
    g = ap.add_argument_group("selection")
    g.add_argument("--container", nargs="*", help="container prefixes / globs, e.g. SERIFU/DATE_AS 'BUNKA/*'")
    g.add_argument("--girl", nargs="*", help="heroine name or code (FU, Shiori, ...)")
    g.add_argument("--status", nargs="*", help="draft | edited | engineering | final")
    g.add_argument("--source-kind", nargs="*", help="container_sheet | container_tagged | overlay_string | "
                   "ui_string | profile_string | file_string | art | composition")
    g.add_argument("--kind", nargs="*", help="line | choice | alternatives | tagged | ui | art | composition")
    g.add_argument("--speaker", nargs="*", help="speaker name substring")
    g.add_argument("--question", nargs="*", help="question ids (default: all)")
    g.add_argument("--ids-file", help="a file with one line id per row")
    g.add_argument("--sample", type=int, help="stratified sample of N lines (group x status x role x kind)")
    g.add_argument("--seed", type=int, default=1234)
    g.add_argument("--limit", type=int, help="stop after N calls")
    m = ap.add_argument_group("modes")
    m.add_argument("--estimate", action="store_true", help="count calls, time and cost; ask nothing")
    m.add_argument("--dry-run", action="store_true", help="build the states, write them, ask nothing")
    m.add_argument("--dry-run-out", default="results/dry_run_states.jsonl")
    m.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def select(a, cfg):
    lines = common.load_lines(a.lines)
    questions = common.load_questions(Path(a.questions_file) if a.questions_file else None)
    ctx = common.Context()
    sel = common.filter_lines(lines, a)
    if a.sample:
        sel = common.stratified_sample(sel, a.sample, a.seed)
    items = common.work_items(sel, questions, ctx, set(a.question) if a.question else None)
    return lines, sel, questions, ctx, items


def human(sec):
    sec = int(sec)
    if sec < 90:
        return f"{sec}s"
    if sec < 5400:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def estimate(a, cfg, sel, items, store):
    todo = [it for it in items if common.item_key(it[0]["id"], it[1]) not in store.done]
    est = cfg.get("estimate", {})
    spc = float(est.get("seconds_per_call", 1.0))
    workers = max(1, int(a.workers or cfg["workers"]))
    rate = float(a.rate or cfg.get("rate_limit_per_sec") or 0)
    per_sec = workers / spc if spc > 0 else float("inf")
    if rate > 0:
        per_sec = min(per_sec, rate)
    bs = int(cfg.get("http", {}).get("batch_size", 1)) if (a.backend or cfg["backend"]) == "http" else 1
    requests = (len(todo) + bs - 1) // bs
    secs = requests / per_sec if per_sec else 0
    cost = requests * float(est.get("cost_per_call", 0.0))
    byq = Counter(q["id"] for _, q in items)
    print(f"lines selected:    {len(sel)}")
    print(f"questions:         {len(byq)}  " + ", ".join(f"{k}={v}" for k, v in byq.items()))
    print(f"calls (line x applicable question): {len(items)}; already done: {len(items) - len(todo)}; "
          f"to do: {len(todo)}" + (f" in {requests} requests (batch {bs})" if bs > 1 else ""))
    print(f"time at {spc:g} s/call, {workers} workers" + (f", <= {rate:g} req/s" if rate else "") +
          f": ~{human(secs)}")
    if cost:
        print(f"cost at {est.get('cost_per_call')} {est.get('currency', '')}/call: "
              f"~{cost:.2f} {est.get('currency', '')}")
    return len(todo)


class Progress:
    def __init__(self, total, every, quiet):
        self.total, self.every, self.quiet = total, every, quiet
        self.done = self.failed = 0
        self.t0 = time.monotonic()
        self.last = 0.0
        self.lock = threading.Lock()

    def tick(self, ok, n=1):
        with self.lock:
            if ok:
                self.done += n
            else:
                self.failed += n
            now = time.monotonic()
            if not self.quiet and (now - self.last >= self.every or self.done + self.failed >= self.total):
                self.last = now
                el = now - self.t0
                rate = (self.done + self.failed) / el if el > 0 else 0
                left = self.total - self.done - self.failed
                eta = left / rate if rate > 0 else 0
                print(f"[run] {self.done + self.failed}/{self.total} ({self.failed} failed)  "
                      f"{rate:.2f}/s  elapsed {human(el)}  ETA {human(eta)}", file=sys.stderr, flush=True)


def call_with_retries(backend, batch, cfg, limiter):
    tries = int(cfg.get("max_retries", 5))
    base = float(cfg.get("backoff_base_sec", 1.0))
    cap = float(cfg.get("backoff_max_sec", 60.0))
    attempt = 0
    while True:
        limiter.wait()
        t = time.monotonic()
        try:
            return backend.classify(batch), time.monotonic() - t, attempt
        except RetryableError as e:
            attempt += 1
            if attempt > tries:
                raise RuntimeError(f"gave up after {tries} retries: {e}")
            time.sleep(min(cap, base * 2 ** (attempt - 1)) * (0.5 + random.random()))


def main(argv=None):
    a = parse_args(argv)
    cfg, cfg_path = common.load_config(a.config)
    if a.backend:
        cfg["backend"] = a.backend
    results = common.kit_path(a.results or cfg["results_path"])
    errors = results.with_name("errors.jsonl") if a.results else common.kit_path(cfg["errors_path"])
    store = common.Store(results, errors)
    lines, sel, questions, ctx, items = select(a, cfg)
    if a.estimate:
        estimate(a, cfg, sel, items, store)
        return 0
    todo = [it for it in items if common.item_key(it[0]["id"], it[1]) not in store.done]
    if a.limit:
        todo = todo[:a.limit]
    fmt = cfg.get("state_format", "json")
    if a.dry_run:
        out = common.kit_path(a.dry_run_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            for l, q in todo:
                fh.write(json.dumps({"line_id": l["id"], "question": common.question_payload(q),
                                     "state": common.build_state(q, l, ctx, fmt)},
                                    ensure_ascii=False) + "\n")
        sizes = [len(json.dumps(common.build_state(q, l, ctx, fmt), ensure_ascii=False)) for l, q in todo[:2000]]
        print(f"[dry-run] {len(todo)} requests written to {out}"
              + (f"; state size avg {sum(sizes) // max(1, len(sizes))} chars, max {max(sizes)}" if sizes else ""))
        return 0
    if not todo:
        print(f"[run] nothing to do: {len(items)} calls selected, all already in {results}")
        return 0
    backend = get_backend(cfg["backend"], cfg)
    bs = int(cfg.get("http", {}).get("batch_size", 1)) if cfg["backend"] == "http" else 1
    batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
    workers = max(1, int(a.workers or cfg["workers"]))
    rate = a.rate if a.rate is not None else cfg.get("rate_limit_per_sec")
    if cfg["backend"] == "mock" and a.rate is None:
        rate = 0                    # the fake backend needs no throttling
    limiter = common.RateLimiter(rate)
    prog = Progress(len(todo), float(cfg.get("progress_every_sec", 5)), a.quiet)
    if not a.quiet:
        print(f"[run] backend {cfg['backend']} ({cfg_path.name if cfg_path else 'defaults'}), "
              f"{len(todo)} calls in {len(batches)} requests, {workers} workers -> {results}",
              file=sys.stderr)

    def work(batch):
        items_ = [{"line_id": l["id"], "question": q, "payload": common.question_payload(q),
                   "state": common.build_state(q, l, ctx, fmt)} for l, q in batch]
        try:
            answers, dt, retries = call_with_retries(backend, items_, cfg, limiter)
        except Exception as e:  # noqa: BLE001
            for l, q in batch:
                store.error({"line_id": l["id"], "question_id": q["id"], "question_version": q["version"],
                             "error": f"{type(e).__name__}: {e}"[:800], "time": time.time()})
            prog.tick(False, len(batch))
            return
        for (l, q), ans in zip(batch, answers):
            rec = {"line_id": l["id"], "question_id": q["id"], "question_version": q["version"],
                   "type": q["type"], "answer": ans,
                   "problem_p": common.problem_probability(q, ans),
                   "backend": cfg["backend"], "latency_sec": round(dt / len(batch), 4),
                   "retries": retries, "time": time.time()}
            store.write(rec)
        prog.tick(True, len(batch))

    try:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(work, batches))
    except KeyboardInterrupt:
        print("\n[run] interrupted; rerun to resume", file=sys.stderr)
        return 130
    print(f"[run] done: {prog.done} answered, {prog.failed} failed"
          + (f" (see {errors})" if prog.failed else ""), file=sys.stderr)
    return 0 if not prog.failed else 2


if __name__ == "__main__":
    sys.exit(main())
