"""Deterministic fake answers for dry runs and the self-test.

Every answer is a pure function of (line id, question id, state), so two
runs give the same results.  A few cheap heuristics make the report
non-trivial (Japanese left in the English raises untranslated_or_garbled,
a very short English for a long Japanese lowers meaning_preserved), but
the numbers MEAN NOTHING: never read a mock run as QA."""
import hashlib
import json
import re

JP = re.compile(r"[぀-ヿ一-鿿]")


def _u(*parts):
    h = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


class MockBackend:
    name = "mock"

    def __init__(self, config):
        self.config = config

    def classify(self, items):
        return [self._one(it) for it in items]

    def _one(self, it):
        q = it["question"]
        st = it["state"]
        text = st if isinstance(st, str) else json.dumps(st, ensure_ascii=False)
        u = _u(it["line_id"], q["id"])
        if q["type"] == "boolean":
            p = 0.05 + 0.9 * u ** 3                 # mostly "no"
            if q.get("problem", {}).get("when") == "false":
                p = 1.0 - p                         # mostly "yes, fine"
            en = st.get("en_readable") or st.get("en_raw") or "" if isinstance(st, dict) else text
            if q["id"] == "untranslated_or_garbled" and JP.search(str(en)):
                p = 0.97
            if q["id"] == "meaning_preserved" and isinstance(st, dict):
                jp, en2 = str(st.get("jp_readable", "")), str(st.get("en_readable", ""))
                if len(jp) > 12 and len(en2) < len(jp) * 0.6:
                    p = min(p, 0.35)
            return {"p_true": round(p, 4)}
        if q["type"] == "choice":
            opts = q["options"]
            w = [(_u(it["line_id"], q["id"], o) ** 4) for o in opts]
            w[0] += 2.5                              # the "ok" option dominates
            s = sum(w)
            return {"probs": {o: round(x / s, 4) for o, x in zip(opts, w)}}
        if q["type"] == "score":
            scale = q["scale"]
            w = [(_u(it["line_id"], q["id"], str(v)) ** 3) for v in scale]
            w[-1] += 1.5
            w[-2] += 1.0
            s = sum(w)
            probs = {str(v): round(x / s, 4) for v, x in zip(scale, w)}
            value = sum(float(k) * p for k, p in probs.items())
            return {"value": round(value, 4), "probs": probs}
        raise ValueError(f"unknown question type {q['type']}")


def make_backend(config):
    return MockBackend(config)
