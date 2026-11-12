"""HTTP backend: one request per item (or per batch of items), shape fully
driven by config["http"].  Standard library only (urllib).

Templates are JSON values in which a string that is EXACTLY "{{name}}" is
replaced by the value (any JSON type) and "{{name}}" inside a longer
string is replaced by its text.  Names available:

  per item       state            the state (dict, or text when state_format = "text")
                 state_json       the state serialised as a JSON string
                 question         the question object (id, type, question, options|scale ...)
                 question_id, question_type, question_text, options, scale, line_id
  per request    item             the rendered item_template (batch_size 1)
                 items            the list of rendered item_templates (batch_size > 1)

${ENV_VAR} in the endpoint and in header values is read from the
environment at request time (keep keys out of the config file).

The reply is read with the paths under "response" ("a.b.0.c": dict keys
and list indexes; "" = the reply itself):

  items_path          (batch_size 1) where the answer is: a list whose first
                      element is the answer, or the answer object itself
  batch_items_path    (batch_size > 1) the list of per-item results, and
  batch_answer_path   inside each of them, where its answer is
  match_by            "index" (results in request order) or "id" (each
                      result carries id_field = "<line_id>|<question_id>")
  choice_probs_path   inside one result: {option: p} or [{label, probability}]
  boolean_prob_path   inside one result: P(true)  (a number, or {"true": p})
  score_value_path    inside one result: the score (number), optional if
  score_probs_path    the distribution over the scale is given instead
"""
import json
import os
import re
import socket
import urllib.error
import urllib.request

from . import RetryableError, normalise_probs

ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
SLOT_RE = re.compile(r"\{\{([a-z_]+)\}\}")


def expand_env(s):
    return ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), s)


def render(tpl, vars_):
    if isinstance(tpl, dict):
        return {k: render(v, vars_) for k, v in tpl.items()}
    if isinstance(tpl, list):
        out = []
        for v in tpl:
            r = render(v, vars_)
            out.append(r)
        return out
    if isinstance(tpl, str):
        m = SLOT_RE.fullmatch(tpl)
        if m:
            return vars_.get(m.group(1))
        return SLOT_RE.sub(lambda m: v2s(vars_.get(m.group(1))), tpl)
    return tpl


def v2s(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def get_path(obj, path):
    if path in ("", None, "."):
        return obj
    for part in str(path).split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            if part not in obj:
                raise KeyError(f"no {part!r} in reply (keys: {list(obj)[:12]})")
            obj = obj[part]
        else:
            raise KeyError(f"cannot descend into {type(obj).__name__} at {part!r}")
    return obj


def item_vars(it):
    q = it["question"]
    p = it["payload"]
    st = it["state"]
    return {"state": st, "state_json": json.dumps(st, ensure_ascii=False) if not isinstance(st, str) else st,
            "question": p, "question_id": q["id"], "question_type": q["type"],
            "question_text": q["question"], "options": q.get("options"), "scale": q.get("scale"),
            "line_id": it["line_id"]}


class HttpBackend:
    name = "http"

    def __init__(self, config):
        self.cfg = config.get("http", {})
        self.timeout = float(config.get("timeout_sec", 60))
        self.store_raw = bool(config.get("store_raw_response"))
        if not self.cfg.get("endpoint"):
            raise SystemExit("config: http.endpoint is not set (see docs/SETUP.md)")
        self.batch_size = int(self.cfg.get("batch_size", 1))
        self.resp = self.cfg.get("response", {})

    def request_body(self, items):
        rendered = [render(self.cfg.get("item_template", "{{state}}"), item_vars(it)) for it in items]
        if self.batch_size > 1 or len(items) > 1:
            return render(self.cfg["request_template_batch"], {"items": rendered})
        v = item_vars(items[0])
        v["item"] = rendered[0]
        return render(self.cfg["request_template"], v)

    def post(self, body):
        url = expand_env(self.cfg["endpoint"])
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {k: expand_env(str(v)) for k, v in self.cfg.get("headers", {}).items()}
        headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=self.cfg.get("method", "POST"))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                txt = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:500]
            if e.code in (408, 409, 425, 429) or e.code >= 500:
                raise RetryableError(f"HTTP {e.code}: {msg}")
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
            raise RetryableError(f"{type(e).__name__}: {e}")
        try:
            return json.loads(txt)
        except ValueError:
            raise RuntimeError(f"reply is not JSON: {txt[:300]!r}")

    def classify(self, items):
        reply = self.post(self.request_body(items))
        if self.batch_size > 1 or len(items) > 1:
            res = get_path(reply, self.resp.get("batch_items_path", "results"))
            sub = self.resp.get("batch_answer_path", "answers.0")
            res = [get_path(r, sub) if r is not None else None for r in res]
        else:
            res = get_path(reply, self.resp.get("items_path", ""))
            if not isinstance(res, list):
                res = [res]
        if self.resp.get("match_by", "index") == "id":
            idf = self.resp.get("id_field", "id")
            by = {str(get_path(r, idf)): r for r in res}
            res = [by.get(f"{it['line_id']}|{it['question']['id']}") for it in items]
        if len(res) < len(items):
            raise RuntimeError(f"reply has {len(res)} results for {len(items)} items")
        return [self.parse(it, r, reply) for it, r in zip(items, res)]

    def parse(self, it, r, reply):
        if r is None:
            raise RuntimeError("no result for this item in the reply")
        q = it["question"]
        if q["type"] == "boolean":
            v = get_path(r, self.resp.get("boolean_prob_path", "probability"))
            if isinstance(v, dict):
                v = v.get("true", v.get("True", v.get("yes")))
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            ans = {"p_true": float(v)}
        elif q["type"] == "choice":
            ans = {"probs": normalise_probs(get_path(r, self.resp.get("choice_probs_path", "probabilities")),
                                            q["options"])}
        else:
            ans = {}
            try:
                probs = get_path(r, self.resp.get("score_probs_path", "probabilities"))
                ans["probs"] = normalise_probs(probs, [str(x) for x in q["scale"]])
            except (KeyError, ValueError, IndexError, TypeError):
                pass
            try:
                ans["value"] = float(get_path(r, self.resp.get("score_value_path", "value")))
            except (KeyError, ValueError, IndexError, TypeError):
                if "probs" not in ans:
                    raise
                ans["value"] = sum(float(k) * p for k, p in ans["probs"].items())
        if self.store_raw:
            ans["raw"] = r
        return ans


def make_backend(config):
    return HttpBackend(config)
