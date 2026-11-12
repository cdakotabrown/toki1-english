"""custom.py - the ONE file to edit when the http backend's templates cannot
describe your local Jev API (a client library, a gRPC stub, a Mastra
scorer, a different auth flow ...).  Select it with "backend": "custom".

Contract (see backends/__init__.py): classify(items) returns one
normalised answer per item, in order:

    boolean -> {"p_true": 0.83}
    choice  -> {"probs": {"matches_voice": 0.7, "too_formal": 0.1, ...}}
    score   -> {"value": 2.4, "probs": {"0": 0.05, "1": 0.1, "2": 0.25, "3": 0.6}}

Each item: {"line_id", "question" (the questions.json entry: id, type,
question, options | scale ...), "payload" (the question as sent:
id, type, question, options/option_descriptions or scale/scale_labels),
"state" (dict, or text when state_format = "text")}.

Raise RetryableError for transient failures (the runner backs off and
retries); any other exception marks the item failed (errors.jsonl) and
the next run retries it.  Settings for this file go under "custom" in
config.json and arrive as self.cfg.

Two worked examples follow; the default below is example A.
"""
import json
import os
import urllib.error
import urllib.request

from . import RetryableError, normalise_probs


class CustomBackend:
    name = "custom"

    def __init__(self, config):
        self.cfg = config.get("custom", {})
        self.timeout = float(config.get("timeout_sec", 60))

    # -- example A: a local server that takes one state + one question ----
    #    POST {endpoint}  {"state": ..., "question": {...}}
    #    ->  {"type": "boolean", "probability": 0.8}
    #        {"type": "choice", "distribution": [{"label": "...", "p": 0.4}, ...]}
    #        {"type": "score", "expected": 2.3, "distribution": [...]}
    def classify(self, items):
        out = []
        for it in items:
            body = {"state": it["state"], "question": it["payload"]}
            reply = self._post(self.cfg.get("endpoint", "http://127.0.0.1:8080/classify"), body)
            q = it["question"]
            if q["type"] == "boolean":
                out.append({"p_true": float(reply["probability"])})
            elif q["type"] == "choice":
                out.append({"probs": normalise_probs(reply["distribution"], q["options"])})
            else:
                ans = {"value": float(reply["expected"])}
                if "distribution" in reply:
                    ans["probs"] = normalise_probs(reply["distribution"], [str(s) for s in q["scale"]])
                out.append(ans)
        return out

    def _post(self, url, body):
        headers = {"Content-Type": "application/json"}
        if os.environ.get("JEV_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["JEV_API_KEY"]
        req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                raise RetryableError(f"HTTP {e.code}")
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise RetryableError(str(e))

    # -- example B: a Python client you installed yourself -----------------
    #    from jev_client import Client                     # hypothetical
    #    def __init__(self, config):
    #        self.client = Client(base_url=config["custom"]["endpoint"])
    #    def classify(self, items):
    #        out = []
    #        for it in items:
    #            r = self.client.classify(state=it["state"], questions=[it["payload"]])
    #            a = r.answers[0]
    #            if a.type == "boolean":
    #                out.append({"p_true": a.probability})
    #            elif a.type == "choice":
    #                out.append({"probs": dict(a.probabilities)})
    #            else:
    #                out.append({"value": a.value})
    #        return out


def make_backend(config):
    return CustomBackend(config)
