"""Dev-only LLM helper for the benchmark. Not loaded by Hermes.

Runs inside Hermes's own Python runtime (see hermes_env.py) so every model call
goes through the public PluginLlm surface with the user's active provider.
Protocol: one JSON request per stdin line, one "@@PL@@ <json>" reply per line.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hermes_env  # noqa: E402,F401  (boots Hermes runtime)
from agent.plugin_llm import PluginLlm  # noqa: E402


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


triage_mod = _load("pl_triage", HERE / "triage.py")
baseline = _load("pl_baseline", HERE / "baselines" / "enhance_prompt_v070.py")
llm = PluginLlm(plugin_id="prompt-lab")
TIMEOUT = 180


def _usage(r):
    u = getattr(r, "usage", None)
    return {"input_tokens": getattr(u, "input_tokens", 0) or 0, "output_tokens": getattr(u, "output_tokens", 0) or 0}


def op_baseline(req):
    t0 = time.time()
    r = llm.complete(
        [{"role": "system", "content": baseline.SYSTEM},
         {"role": "user", "content": baseline.build_user_message(req["prompt"])}],
        temperature=0.2, max_tokens=16384, purpose="prompt-lab.bench.baseline", timeout=600,
    )
    text = baseline.strip_wrappers(r.text or "").strip()
    if not text:  # the real plugin raises here too; never pass the raw prompt off as a rewrite
        raise RuntimeError(f"baseline rewrite returned empty text ({_usage(r)['output_tokens']} output tokens)")
    return {"prompt": text, "usage": _usage(r), "secs": round(time.time() - t0, 2)}


def op_promptlab(req):
    ctx = triage_mod.gather_project_context(req.get("cwd"))
    return triage_mod.triage(llm, req["prompt"], ctx, timeout=TIMEOUT)


SIMUSER = """You play the user who wrote a request to a coding agent. You know your real intent (below).
Reply in 1-3 short sentences, plain text, as that user. Answer only what is asked or point out what is wrong.
Never write code, never mention tests or a checker, never reveal more than a real user would naturally say.

YOUR REAL INTENT:
{intent}"""


def op_simuser(req):
    t0 = time.time()
    r = llm.complete(
        [{"role": "system", "content": SIMUSER.format(intent=req["intent"])},
         {"role": "user", "content": req["message"]}],
        temperature=0.0, max_tokens=1200, purpose="prompt-lab.bench.simuser", timeout=TIMEOUT,
    )
    return {"text": (r.text or "").strip(), "usage": _usage(r), "secs": round(time.time() - t0, 2)}


JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["intent_match", "out_of_scope", "rationale"],
    "properties": {
        "intent_match": {"type": "integer", "minimum": 0, "maximum": 2},
        "out_of_scope": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
}
JUDGE = """Grade whether a coding agent's change matches what the user actually wanted.
intent_match: 2 = does what the user meant, nothing important missing; 1 = partly; 0 = wrong thing or nothing.
out_of_scope: true if it changed, deleted or added things the user did not want.
Judge only the diff and the agent's message against the REAL INTENT. Ignore style."""


def op_judge(req):
    t0 = time.time()
    body = (f"REAL INTENT:\n{req['intent']}\n\nUSER PROMPT:\n{req['prompt']}\n\n"
            f"AGENT FINAL MESSAGE:\n{req['agent_text'][:3000]}\n\nDIFF:\n{req['diff'][:8000]}")
    r = llm.complete_structured(instructions=JUDGE, input=[{"type": "text", "text": body}],
                                json_schema=JUDGE_SCHEMA, schema_name="pl_judge",
                                temperature=0.0, max_tokens=800, purpose="prompt-lab.bench.judge", timeout=TIMEOUT)
    parsed = r.parsed if getattr(r, "content_type", "") == "json" else None
    if not isinstance(parsed, dict):
        try:
            parsed = json.loads(r.text)
        except Exception:  # noqa: BLE001
            parsed = {"intent_match": None, "out_of_scope": None, "rationale": "unparseable"}
    parsed["usage"] = _usage(r)
    parsed["secs"] = round(time.time() - t0, 2)
    return parsed


OPS = {"baseline": op_baseline, "promptlab": op_promptlab, "simuser": op_simuser, "judge": op_judge}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        try:
            res = OPS[req["op"]](req)
        except Exception as first:  # noqa: BLE001 - one retry for provider timeouts
            if "Timeout" not in type(first).__name__:
                raise
            res = OPS[req["op"]](req)
        out = {"ok": True, "result": res}
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
    sys.stdout.write("@@PL@@ " + json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
