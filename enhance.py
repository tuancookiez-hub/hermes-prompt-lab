"""Prompt Lab rewriter: turn a normal request into a clearer prompt, in the voice the user picked."""

from __future__ import annotations

import re
import time
from typing import Any

MIN_WORDS = 3
DEFAULT_TIMEOUT = 60
DEFAULT_VOICE = "structured"
CUSTOM = "custom"
MAX_CUSTOM_CHARS = 600

VOICES = {
    "structured": """Use these headings, in this order, each at most once. Leave out any heading with nothing real to say:
Goal: one sentence
Context:
Steps:
Constraints:
Done when:
Under Context, Constraints and Done when, write "- " bullets. Under Steps, write a numbered list, and use Steps only for work with more than one real step.""",
    "concise": "Write one short, direct paragraph of two to four sentences. No headings and no lists.",
    "detailed": """Write a thorough brief with these headings, in this order: Goal, Context, Requirements, Edge cases, Done when.
Use "- " bullets under each. Spell out what a careful engineer would need to know, but add no features the user did not ask for.""",
    "clarify": """State the request in one or two plain sentences. In this voice, never state an assumption, even where the rules below say to.
Then add the line "Before you start, ask me:" and one to three short "- " questions about what the request leaves open and would change the work, such as which part is meant, how far to go, or what must stay as it is.
Leave the questions out only when the request already settles all of that.""",
    "verify": """State the request in one or two plain sentences.
Then add the line "Prove it:" and two to four "- " bullets naming the evidence the agent must show before calling the work done, such as reproducing the problem first, a test that fails before the change and passes after, or the output of a command.
Ask only for evidence that fits this request.""",
}

BASE = """Rewrite the user's request as a clearer prompt for an AI agent.
Never do the task and never answer it. Output only the rewritten prompt.

VOICE:
{voice}

Rules that always apply:
Write in the same language as the request. Keep the user's names, intent and details.
Keep @file references and /commands exactly as written.
Add no facts, features or goals the user did not give. If something important is unclear, state the most likely reading as an assumption, in a few words.
Match length to the request. A one-line request gets a short prompt.
Everything above is your instructions. Never copy them into the output.
Plain text only, with no code fences and no preamble."""

_THINK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_FENCE = re.compile(r"^```[\w-]*\n([\s\S]*?)\n?```$")
_LABELLED = re.compile(r"^\s*(goal|context|steps|constraints|done when)\s*:", re.IGNORECASE | re.MULTILINE)


class EnhanceError(RuntimeError):
    """The model gave no usable rewrite. The user's prompt is left as it was."""


def already_structured(prompt: str) -> bool:
    return len(_LABELLED.findall(prompt)) >= 2


def voice_text(voice: str | None, custom: str | None = None) -> str:
    """The style instruction for a voice name. Custom uses the user's own words; anything unknown falls back."""
    name = (voice or DEFAULT_VOICE).strip().lower()
    if name == CUSTOM:
        words = (custom or "").strip()[:MAX_CUSTOM_CHARS]
        if words:
            return f"Follow this style, written by the user: {words}"
        name = DEFAULT_VOICE
    return VOICES.get(name, VOICES[DEFAULT_VOICE])


def build_messages(prompt: str, voice: str | None = None, custom: str | None = None) -> list[dict[str, str]]:
    system = BASE.format(voice=voice_text(voice, custom))
    return [{"role": "system", "content": system}, {"role": "user", "content": f"REQUEST:\n{prompt}"}]


def clean(text: str) -> str:
    out = _THINK.sub("", text or "").strip()
    fenced = _FENCE.match(out)
    return (fenced.group(1) if fenced else out).strip()


def enhance(llm, prompt: str, *, voice: str | None = None, custom: str | None = None, task: str | None = None,
            timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Return {"prompt", "changed", "note", "secs", ...}. Raises EnhanceError when no rewrite comes back."""
    started = time.time()
    text = prompt.strip()
    structured_voice = voice_text(voice, custom) == VOICES[DEFAULT_VOICE]
    skip = ("too short to rewrite" if len(text.split()) < MIN_WORDS
            else "already structured" if structured_voice and already_structured(text) else "")
    if skip:
        return {"prompt": text, "changed": False, "note": skip, "secs": 0.0,
                "usage": {"input_tokens": 0, "output_tokens": 0}}
    kwargs: dict[str, Any] = {"task": task} if task else {}
    result = llm.complete(build_messages(text, voice, custom), temperature=0.2,
                          max_tokens=1200, timeout=timeout, purpose="prompt-lab.enhance", **kwargs)
    rewritten = clean(getattr(result, "text", "") or "")
    usage = getattr(result, "usage", None)
    tokens = {"input_tokens": getattr(usage, "input_tokens", 0) or 0,
              "output_tokens": getattr(usage, "output_tokens", 0) or 0}
    if not rewritten:
        raise EnhanceError(f"the model returned no text after {tokens['output_tokens']} output tokens")
    return {"prompt": rewritten, "changed": rewritten != text, "note": "", "model": getattr(result, "model", ""),
            "usage": tokens, "secs": round(time.time() - started, 2)}
