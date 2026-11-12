"""Backends: each module exposes make_backend(config) -> object with

    classify(items) -> list of answers, one per item, same order

where an item is {"line_id", "question" (questions.json entry), "payload"
(the question as sent), "state" (dict or text)} and an answer is the
NORMALISED form:

    boolean: {"p_true": float}
    choice:  {"probs": {option: float, ...}}
    score:   {"value": float, "probs": {"0": p, "1": p, ...} (optional)}

plus optional "raw" (the backend's raw reply, stored when
store_raw_response is on).  Raise backends.RetryableError for anything
worth retrying (timeouts, 429, 5xx); any other exception fails the item
(it is logged to errors.jsonl and retried on the next run).

    batch_size     how many items one classify() call receives (default 1)
"""


class RetryableError(Exception):
    pass


def get_backend(name, config):
    if name == "mock":
        from . import mock_backend as m
    elif name == "http":
        from . import http_backend as m
    elif name == "custom":
        from . import custom as m
    else:
        raise SystemExit(f"unknown backend {name!r} (mock | http | custom)")
    return m.make_backend(config)


def normalise_probs(probs, options):
    """{label: p} or [{label|option|answer: x, probability|p|score: p}] -> {option: p}
    restricted to the question's options and renormalised"""
    if isinstance(probs, list):
        d = {}
        for e in probs:
            if isinstance(e, dict):
                k = e.get("label", e.get("option", e.get("answer", e.get("name"))))
                v = e.get("probability", e.get("p", e.get("score", e.get("value"))))
                if k is not None and v is not None:
                    d[str(k)] = float(v)
            elif isinstance(e, (list, tuple)) and len(e) == 2:
                d[str(e[0])] = float(e[1])
        probs = d
    if not isinstance(probs, dict):
        raise ValueError(f"cannot read probabilities from {probs!r}")
    out = {str(o): float(probs.get(str(o), probs.get(o, 0.0)) or 0.0) for o in options}
    s = sum(out.values())
    if s <= 0:
        raise ValueError(f"no probability on any option: {probs!r}")
    return {k: v / s for k, v in out.items()}
