"""Prompt Lab: /promptlab <request> rewrites a request as a clearer prompt, in the voice set in Settings."""

from __future__ import annotations

import json
import logging
import time

from .enhance import DEFAULT_VOICE, EnhanceError, enhance

logger = logging.getLogger(__name__)

PLUGIN = "prompt-lab"
AUX_TASK = "prompt_lab"
JSON_FLAG = "--json"


def _log(original: str, result: dict, session_id: str) -> None:
    try:
        from plugins.plugin_storage import plugin_db

        conn = plugin_db(PLUGIN)
        conn.execute("CREATE TABLE IF NOT EXISTS rewrites (ts REAL, session_id TEXT, original TEXT, rewritten TEXT, "
                     "changed INTEGER, detail TEXT)")
        conn.execute("INSERT INTO rewrites VALUES (?,?,?,?,?,?)",
                     (time.time(), session_id, original, result["prompt"], int(result["changed"]),
                      json.dumps({k: result.get(k) for k in ("model", "secs", "usage")})))
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - logging must never break the command
        logger.debug("prompt-lab: rewrite log failed: %s", exc)


def register(ctx) -> None:
    try:
        ctx.register_auxiliary_task(
            AUX_TASK,
            display_name="Prompt Lab",
            description="Rewrites requests into structured prompts. Uses your main model unless you change it.",
            defaults={"reasoning_effort": "none"},  # a short rewrite needs no reasoning; hy4 can stall without this
        )
        task = AUX_TASK
    except Exception as exc:  # noqa: BLE001 - older Hermes: use the active model
        logger.debug("prompt-lab: auxiliary task unavailable: %s", exc)
        task = None

    def _cmd(raw: str, *, session_id: str = "", **_kw) -> str:
        text = (raw or "").strip()
        as_json = text == JSON_FLAG or text.startswith(JSON_FLAG + " ") or text.startswith(JSON_FLAG + chr(10))
        if as_json:  # the Desktop button reads this form; people use the plain one
            text = text[len(JSON_FLAG):].strip()
        if not text:
            return json.dumps({"ok": False, "error": "nothing to rewrite"}) if as_json else "Usage: /promptlab <request>"
        try:
            # Read on every call, so a change in Settings applies to the next rewrite.
            result = enhance(ctx.llm, text, voice=ctx.get_config("voice", DEFAULT_VOICE),
                             custom=ctx.get_config("custom_voice", ""), task=task)
        except Exception as exc:  # noqa: BLE001 - a provider failure should read as a message, not a crash
            if not isinstance(exc, EnhanceError):
                logger.warning("prompt-lab: rewrite failed: %s", exc)
            if as_json:
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            return f"Prompt Lab could not rewrite this: {exc}. Your request was not changed."
        _log(text, result, session_id)
        if as_json:
            return json.dumps({"ok": True, "prompt": result["prompt"], "changed": result["changed"],
                               "note": result["note"]}, ensure_ascii=False)
        if not result["changed"]:
            return f"Left unchanged ({result['note'] or 'nothing to improve'})."
        return result["prompt"]

    ctx.register_command("promptlab", _cmd, description="Rewrite a request as a clearer prompt",
                         args_hint="<request>")
