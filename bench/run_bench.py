"""Prompt Lab A/B benchmark runner (dev-only).

For each case x arm: copy the fixture into a fresh git repo, build the prompt for
the arm, run a real headless Hermes agent on it, check the result, allow ONE
simulated-user follow-up if it failed, then have a judge grade intent match.

Arms:
  raw        the prompt exactly as written
  baseline   enhance-prompt v0.7.0 rewrite (bench/baselines)
  promptlab  Prompt Lab triage (../triage.py): clear -> unchanged, edit -> labelled
             additions, ask -> simulated user answers the questions first

Usage:
  python run_bench.py [--cases c01,c02] [--arms raw,baseline,promptlab]
                      [--repeats 1] [--workers 3] [--profile plbench]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import triage as T  # noqa: E402  (pure stdlib; same code the plugin ships)

HERMES_PY = os.environ.get(
    "HERMES_PY", r"C:\Users\tuanc\AppData\Local\hermes\tools\python-3.14.9+20261021-win32-x64\python.exe")
HERMES = shutil.which("hermes") or "hermes"
ARMS = ("raw", "baseline", "promptlab")
HELPER_LOG: pathlib.Path | None = None
GIT_ID = ["-c", "user.name=bench", "-c", "user.email=bench@localhost", "-c", "core.autocrlf=false"]


# --------------------------------------------------------------------------- helper
class Helper:
    """One long-lived llm_helper.py process (Hermes runtime) per worker."""

    def __init__(self):
        self.err = open(HELPER_LOG, "a", encoding="utf-8") if HELPER_LOG else subprocess.DEVNULL
        self.p = subprocess.Popen([HERMES_PY, "-I", str(HERE / "llm_helper.py")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=self.err, text=True,
                                  encoding="utf-8", bufsize=1)

    def call(self, op: str, **kw):
        self.p.stdin.write(json.dumps({"op": op, **kw}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        for line in self.p.stdout:
            if line.startswith("@@PL@@ "):
                out = json.loads(line[7:])
                if not out["ok"]:
                    raise RuntimeError(f"helper {op}: {out['error']}\n{out.get('trace', '')}")
                return out["result"]
        raise RuntimeError("helper exited")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:  # noqa: BLE001
            self.p.kill()


_local = threading.local()


def helper() -> Helper:
    if not hasattr(_local, "h") or _local.h.p.poll() is not None:
        _local.h = Helper()
    return _local.h


# --------------------------------------------------------------------------- git / fixture
def git(cwd, *args, check=True):
    return subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def prepare(case_dir: pathlib.Path, run_dir: pathlib.Path):
    shutil.copytree(case_dir / "fixture", run_dir)
    git(run_dir, "init", "-q")
    (run_dir / ".git" / "info" / "exclude").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    git(run_dir, "add", "-A")
    git(run_dir, "commit", "-qm", "fixture")


def diff(run_dir) -> tuple[str, str]:
    git(run_dir, "add", "-A", "-N", check=False)
    full = git(run_dir, "diff", "HEAD", check=False).stdout
    stat = git(run_dir, "diff", "HEAD", "--stat", check=False).stdout
    return full, stat


def run_check(case_dir, run_dir) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, str(case_dir / "check.py")], cwd=run_dir, capture_output=True,
                       text=True, timeout=300)
    return r.returncode == 0, (r.stderr or r.stdout)[-400:]


# --------------------------------------------------------------------------- agent
def agent(run_dir, prompt: str, profile: str, resume: str | None = None) -> dict:
    qf = pathlib.Path(run_dir).parent / f".{pathlib.Path(run_dir).name}.{int(time.time()*1000)}.q.txt"
    qf.write_text(prompt, encoding="utf-8")
    cmd = [HERMES, "-p", profile, "chat", "--query-file", str(qf), "--format", "stream-json",
           "--max-turns", "40", "--source", "tool", "--in", str(run_dir)]
    if resume:
        cmd += ["--resume", resume]
    for attempt in range(12):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)
            out = r.stdout
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        events = []
        for line in out.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        result = next((e for e in reversed(events) if e.get("type") == "result"), None) or {}
        err = result.get("error") or ""
        if "Gateway draining" in err or "update_paused" in err:
            time.sleep(20)
            continue
        tools = [e.get("name") for e in events if e.get("type") == "tool_use"]
        tok = result.get("tokens") or {}
        return {
            "ok": result.get("exit_code") == 0, "error": err or None,
            "session_id": result.get("session_id") or resume,
            "text": result.get("text") or "",
            "tokens": tok.get("total", 0) or 0, "tokens_in": tok.get("input", 0) or 0,
            "tokens_out": tok.get("output", 0) or 0, "cache_read": tok.get("cache_read", 0) or 0,
            "agent_secs": round((result.get("duration_ms") or 0) / 1000, 1),
            "wall_secs": round(time.time() - t0, 1),
            "tool_calls": len(tools), "asked_clarify": "clarify" in tools,
        }
    return {"ok": False, "error": "gateway stayed draining", "session_id": resume, "text": "", "tokens": 0,
            "tokens_in": 0, "tokens_out": 0, "cache_read": 0, "agent_secs": 0, "wall_secs": 0,
            "tool_calls": 0, "asked_clarify": False}


# --------------------------------------------------------------------------- arms
def build_prompt(arm: str, case: dict, run_dir) -> dict:
    p = case["prompt"]
    if arm == "raw":
        return {"prompt": p, "presend_tokens": 0, "presend_secs": 0.0, "detail": None, "questions": 0}
    if arm == "baseline":
        r = helper().call("baseline", prompt=p)
        return {"prompt": r["prompt"], "presend_tokens": r["usage"]["input_tokens"] + r["usage"]["output_tokens"],
                "presend_secs": r["secs"], "detail": None, "questions": 0}
    t = helper().call("promptlab", prompt=p, cwd=str(run_dir))
    tokens = t["usage"]["input_tokens"] + t["usage"]["output_tokens"]
    final, nq = p, 0
    if t["verdict"] == "edit":
        final = T.apply_edits(p, t["edits"])
    elif t["verdict"] == "ask":
        qs = t["questions"]
        nq = len(qs)
        ans = helper().call("simuser", intent=case["intent"],
                            message="Before running your request, the assistant asks:\n"
                                    + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs))
                                    + "\nAnswer each briefly, numbered.")
        final = (p.rstrip() + "\n\nYou asked:\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs))
                 + "\n\nMy answers [user]:\n" + ans["text"])
    return {"prompt": final, "presend_tokens": tokens, "presend_secs": t["secs"], "detail": t, "questions": nq}


def one_run(case_dir: pathlib.Path, case: dict, arm: str, rep: int, runs_root: pathlib.Path, profile: str) -> dict:
    run_dir = runs_root / f"{case['id']}__{arm}__r{rep}"
    rec = {"case": case["id"], "kind": case["kind"], "arm": arm, "rep": rep, "run_dir": str(run_dir)}
    try:
        prepare(case_dir, run_dir)
        b = build_prompt(arm, case, run_dir)
        rec.update({k: b[k] for k in ("presend_tokens", "presend_secs", "questions")})
        rec["final_prompt"] = b["prompt"]
        rec["triage"] = b["detail"]
        a1 = agent(run_dir, b["prompt"], profile)
        if a1["error"] and not a1["tokens"]:
            raise RuntimeError(f"infra: agent run failed before inference: {a1['error'][:300]}")
        ok1, why1 = run_check(case_dir, run_dir)
        rec.update({"agent1": a1, "success_first": ok1, "check1": why1})
        followups, a2 = 0, None
        if not ok1:
            _, stat = diff(run_dir)
            msg = (f"The agent replied:\n{a1['text'][:2500]}\n\nFiles changed:\n{stat or '(none)'}\n\n"
                   "It is not done the way you wanted yet (or it asked you something). Write your reply to it.")
            fb = helper().call("simuser", intent=case["intent"], message=msg)
            rec["followup_msg"] = fb["text"]
            a2 = agent(run_dir, fb["text"], profile, resume=a1.get("session_id"))
            if a2["error"] and not a2["tokens"]:
                raise RuntimeError(f"infra: follow-up run failed before inference: {a2['error'][:300]}")
            followups = 1
        ok2, why2 = run_check(case_dir, run_dir)
        rec.update({"agent2": a2, "followups": followups, "success_final": ok2, "check_final": why2})
        full, _ = diff(run_dir)
        texts = a1["text"] + ("\n\n[after follow-up]\n" + a2["text"] if a2 else "")
        j = helper().call("judge", intent=case["intent"], prompt=case["prompt"], agent_text=texts, diff=full)
        rec["intent_match"], rec["out_of_scope"], rec["judge_rationale"] = (
            j.get("intent_match"), j.get("out_of_scope"), j.get("rationale"))
        rec["agent_tokens"] = a1["tokens"] + (a2["tokens"] if a2 else 0)
        rec["agent_uncached"] = sum(x["tokens"] - x["cache_read"] for x in (a1, a2) if x)
        rec["tool_calls"] = a1["tool_calls"] + (a2["tool_calls"] if a2 else 0)
        rec["agent_secs"] = a1["agent_secs"] + (a2["agent_secs"] if a2 else 0)
        rec["total_secs"] = round(rec["agent_secs"] + rec["presend_secs"], 1)
        rec["errors"] = [e for e in (a1.get("error"), a2.get("error") if a2 else None) if e]
    except Exception as exc:  # noqa: BLE001
        rec["crash"] = f"{type(exc).__name__}: {str(exc)[:600]}"
    return rec


# --------------------------------------------------------------------------- report
def report(recs: list[dict]) -> str:
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    lines = ["| arm | n | success 1st try | success after <=1 follow-up | follow-ups | intent match (0-2) "
             "| out of scope | pre-send questions | agent tokens (all) | agent tokens (uncached) | pre-send tokens "
             "| time s (pre-send + agent) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        rs = [r for r in recs if r["arm"] == arm and "crash" not in r]
        if not rs:
            continue
        n = len(rs)
        lines.append(
            f"| {arm} | {n} | {sum(r['success_first'] for r in rs)}/{n} | {sum(r['success_final'] for r in rs)}/{n} "
            f"| {sum(r['followups'] for r in rs)} | {mean([r['intent_match'] for r in rs]):.2f} "
            f"| {sum(bool(r['out_of_scope']) for r in rs)} | {sum(r['questions'] for r in rs)} "
            f"| {mean([r['agent_tokens'] for r in rs]):,.0f} | {mean([r['agent_uncached'] for r in rs]):,.0f} "
            f"| {mean([r['presend_tokens'] for r in rs]):,.0f} "
            f"| {mean([r['presend_secs'] for r in rs]):.0f} + {mean([r['agent_secs'] for r in rs]):.0f} |")
    lines += ["", "Per case (first-try success / final success / intent / follow-ups):", "",
              "| case | kind | " + " | ".join(ARMS) + " |", "|---|---|" + "---|" * len(ARMS)]
    for cid in sorted({r["case"] for r in recs}):
        cells = []
        kind = next(r["kind"] for r in recs if r["case"] == cid)
        for arm in ARMS:
            rs = [r for r in recs if r["case"] == cid and r["arm"] == arm]
            cells.append(", ".join(
                "crash" if "crash" in r else
                f"{'Y' if r['success_first'] else 'n'}/{'Y' if r['success_final'] else 'n'}/{r['intent_match']}/{r['followups']}"
                for r in rs) or "-")
        lines.append(f"| {cid} | {kind} | " + " | ".join(cells) + " |")
    crashes = [r for r in recs if "crash" in r]
    if crashes:
        lines += ["", "Crashes:"] + [f"- {r['case']} {r['arm']}: {r['crash'][:300]}" for r in crashes]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--profile", default="plbench")
    ap.add_argument("--runs-dir", default=os.environ.get("PL_RUNS_DIR", tempfile.gettempdir()))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--resume", default="", help="results/<stamp> folder to continue")
    a = ap.parse_args()

    global HELPER_LOG
    version = subprocess.run([HERMES, "--version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout
    version = next((ln for ln in version.splitlines() if ln.startswith("Hermes Agent")), "unknown")
    prior: list[dict] = []
    if a.resume:
        out_dir = pathlib.Path(a.resume).resolve()
        stamp = out_dir.name
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        if meta["hermes"] != version:
            sys.exit(f"refusing to resume: results used {meta['hermes']!r}, this is {version!r}")
        prior = [r for r in map(json.loads, (out_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines())
                 if "crash" not in r]
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = HERE / "results" / stamp
        out_dir.mkdir(parents=True)
        (out_dir / "meta.json").write_text(json.dumps({"hermes": version, "profile": a.profile, "seed": a.seed}),
                                           encoding="utf-8")
    runs_root = pathlib.Path(a.runs_dir) / f"promptlab-runs-{stamp}-{int(time.time())}"
    runs_root.mkdir(parents=True)
    HELPER_LOG = out_dir / "helper.log"
    want = {c for c in a.cases.split(",") if c}
    cases = []
    for d in sorted((HERE / "cases").iterdir()):
        if d.is_dir() and (not want or d.name in want or d.name.split("_")[0] in want):
            cases.append((d, yaml.safe_load((d / "case.yaml").read_text(encoding="utf-8"))))
    jobs = [(d, c, arm, rep) for rep in range(a.repeats) for d, c in cases for arm in a.arms.split(",")]
    random.Random(a.seed).shuffle(jobs)
    done = {(r["case"], r["arm"], r["rep"]) for r in prior}
    jobs = [j for j in jobs if (j[1]["id"], j[2], j[3]) not in done]
    print(f"{version}\n{len(jobs)} runs to do, {len(done)} already done -> {out_dir}  (fixtures in {runs_root})",
          flush=True)

    recs, lock = list(prior), threading.Lock()
    total = len(jobs) + len(prior)
    with open(out_dir / "runs.jsonl", "w", encoding="utf-8") as fh, cf.ThreadPoolExecutor(a.workers) as ex:
        for r in prior:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush()
        futs = {ex.submit(one_run, d, c, arm, rep, runs_root, a.profile): (c["id"], arm) for d, c, arm, rep in jobs}
        for f in cf.as_completed(futs):
            r = f.result()
            with lock:
                recs.append(r)
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
            status = r.get("crash") or (f"first={r['success_first']} final={r['success_final']} "
                                        f"intent={r['intent_match']} tok={r['agent_tokens']} t={r['total_secs']}s")
            print(f"[{len(recs)}/{total}] {r['case']} {r['arm']}: {status}", flush=True)
    md = (f"# Prompt Lab A/B pilot {stamp}\n\n{version}\n\nProfile: `{a.profile}`, repeats: {a.repeats}\n\n"
          + report(recs))
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
