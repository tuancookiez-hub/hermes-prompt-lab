"""Prompt Lab triage: decide whether a prompt needs help, and if so, how little.

Flow: local pre-check (free) -> one structured model call -> verdict.
  clear -> send the prompt unchanged
  ask   -> at most 3 questions only the user can answer
  edit  -> at most 4 short additions, each labelled user / project / assumption
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

SOURCES = ("user", "project", "assumption")
CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md", "README.md")
CONTEXT_CHARS_PER_FILE = 2000

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reason", "questions", "edits"],
    "properties": {
        "verdict": {"type": "string", "enum": ["clear", "ask", "edit"]},
        "reason": {"type": "string"},
        "questions": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
        "edits": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source"],
                "properties": {
                    "text": {"type": "string"},
                    "source": {"type": "string", "enum": list(SOURCES)},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}

INSTRUCTIONS = """You review a prompt a user is about to send to a coding/ops agent that can read their files and run tools.
The agent already receives the project's AGENTS.md automatically and can open any file itself.
Decide the SMALLEST intervention that would make the agent succeed on the first try.

verdict:
- "clear": the agent can do this correctly as written (it can discover files/context itself). Return no questions, no edits. Prefer this when in doubt.
- "ask": a decision only the user can make is missing and a wrong guess would waste the run or destroy data (which target, what scope, destructive choice, success criterion, something "we discussed"). Ask at most 3 short questions. Never ask what the agent can look up.
- "edit": one to four short additions would clearly help and are safe to state.

Each edit is ONE short clause to append, labelled with its source:
- "user": restates something the user already said in the provided context.
- "project": a fact from PROJECT CONTEXT that disambiguates the request; quote the line in evidence.
- "assumption": your guess; keep these rare and phrase them so the agent can override them.
Never rewrite the user's words, never add sections, roles, or templates, never answer the task."""

_SPECIFIC = re.compile(
    r"[\w./-]+\.(?:py|js|ts|tsx|jsx|json|md|ya?ml|toml|go|rs|java|kt|swift|css|html|sh|sql|rb|php|c|cpp|h)\b"
    r"|--[\w-]{2,}|`[^`]+`|\b\w+\(\)"
)


def precheck(prompt: str) -> str | None:
    """Free local verdict. Returns "clear" for long prompts that name concrete targets, else None."""
    words = len(prompt.split())
    if words >= 12 and _SPECIFIC.search(prompt):
        return "clear"
    return None


def gather_project_context(cwd: str | Path | None) -> str:
    """Read the first part of AGENTS.md / CLAUDE.md / README.md in the session folder, if present."""
    if not cwd:
        return ""
    parts = []
    root = Path(cwd)
    for name in CONTEXT_FILES:
        p = root / name
        try:
            if p.is_file():
                parts.append(f"--- {name} ---\n{p.read_text(encoding='utf-8', errors='replace')[:CONTEXT_CHARS_PER_FILE]}")
        except OSError:
            continue
    return "\n\n".join(parts)


def build_input(prompt: str, project_context: str = "") -> list[dict[str, str]]:
    body = f"PROMPT:\n{prompt}"
    if project_context.strip():
        body += f"\n\nPROJECT CONTEXT:\n{project_context.strip()}"
    return [{"type": "text", "text": body}]


def _clean(parsed: dict[str, Any]) -> dict[str, Any]:
    verdict = parsed.get("verdict") if parsed.get("verdict") in ("clear", "ask", "edit") else "clear"
    questions = [q for q in parsed.get("questions") or [] if isinstance(q, str) and q.strip()][:3]
    edits = [e for e in parsed.get("edits") or []
             if isinstance(e, dict) and isinstance(e.get("text"), str) and e.get("source") in SOURCES][:4]
    if verdict == "ask" and not questions:
        verdict = "clear"
    if verdict == "edit" and not edits:
        verdict = "clear"
    if verdict == "clear":
        questions, edits = [], []
    return {"verdict": verdict, "reason": str(parsed.get("reason", "")), "questions": questions, "edits": edits}


def triage(llm, prompt: str, project_context: str = "", *, task: str | None = None,
           use_precheck: bool = True, timeout: float | None = 120) -> dict[str, Any]:
    started = time.time()
    if use_precheck and precheck(prompt) == "clear":
        return {"verdict": "clear", "reason": "names concrete targets; left alone without a model call",
                "questions": [], "edits": [], "path": "precheck",
                "usage": {"input_tokens": 0, "output_tokens": 0}, "secs": round(time.time() - started, 2)}
    kwargs: dict[str, Any] = {"timeout": timeout} if timeout else {}
    if task:
        kwargs["task"] = task
    result = llm.complete_structured(
        instructions=INSTRUCTIONS,
        input=build_input(prompt, project_context),
        json_schema=SCHEMA,
        schema_name="prompt_lab_triage",
        temperature=0.0,
        max_tokens=800,
        purpose="prompt-lab.triage",
        **kwargs,
    )
    parsed = result.parsed if getattr(result, "content_type", "") == "json" else None
    if not isinstance(parsed, dict):
        try:
            parsed = json.loads(result.text)
        except Exception:  # noqa: BLE001 - fail open: never block the user's prompt
            parsed = {"verdict": "clear", "reason": "unparseable triage; leaving prompt alone"}
    out = _clean(parsed)
    usage = getattr(result, "usage", None)
    out["path"] = "model"
    out["model"] = getattr(result, "model", "")
    out["usage"] = {"input_tokens": getattr(usage, "input_tokens", 0) or 0,
                    "output_tokens": getattr(usage, "output_tokens", 0) or 0}
    out["secs"] = round(time.time() - started, 2)
    return out


def apply_edits(prompt: str, edits: list[dict[str, Any]]) -> str:
    if not edits:
        return prompt
    lines = [prompt.rstrip(), ""]
    for e in edits:
        lines.append(f"- {e['text']} [{e['source']}]")
    return "\n".join(lines)

