/**
 * Prompt Lab: a button beside Send that rewrites the draft as a clearer prompt, in the voice set in Settings.
 *
 * It only changes the draft. It never sends. Undo restores what you typed.
 *
 * Every rewrite runs the /promptlab command. A new chat has no session yet, so
 * it opens a hidden one for the call, then ends and deletes it. It is never
 * given a prompt, so the only thing removed is that session's empty record.
 */

import { jsx, jsxs } from "react/jsx-runtime";
import { useEffect, useSyncExternalStore } from "react";
import {
  Button,
  Codicon,
  COMPOSER_AREAS,
  KEYBINDS_AREA,
  PALETTE_AREA,
  Tip,
  cn,
  host,
  pluginSettingsHref,
  useValue,
} from "@hermes/plugin-sdk";

const REQUEST_TIMEOUT_MS = 200000;
const UNDO_CHECK_MS = 1500;

const busy = new Map();
const undo = new Map();
const listeners = new Set();
let version = 0;
let scheduleCheck = null;

function emit() {
  version += 1;
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getVersion = () => version;
const focusedSession = () => host.state.focusedSessionId.get() || null;
const keyFor = (sessionId) => sessionId || "new";
const normalize = (text) => String(text ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
const tell = (message, kind = "info") => host.notify({ kind, message });

function parseCommandOutput(output) {
  try {
    const parsed = JSON.parse(output);
    if (parsed && typeof parsed === "object") return parsed;
  } catch {
    // Reported below.
  }
  throw new Error("Prompt Lab isn't active in this profile. Enable it under Capabilities > Plugins.");
}

async function runCommand(sessionId, text, scope = {}) {
  const result = await host.request(
    "slash.exec",
    { ...scope, session_id: sessionId, command: `/promptlab --json ${text}` },
    REQUEST_TIMEOUT_MS,
  );
  const parsed = parseCommandOutput(result?.output);
  if (parsed.ok === false) throw new Error(parsed.error || "the rewrite failed");
  return parsed;
}

async function removeHiddenSession(session, scope) {
  const remove = (revision, generation) =>
    host.request("session.mutate", {
      ...scope,
      session_id: session.stored_session_id || session.session_id,
      request_id: crypto.randomUUID(),
      expected_revision: revision,
      expected_generation: generation,
      operation: "delete",
      payload: {},
    });
  try {
    await host.request("session.detach", {
      ...scope,
      session_id: session.session_id,
      subscription_id: session.subscription_id,
      end_reason: "prompt_lab_done",
    });
    try {
      await remove(session.revision, session.execution_generation);
    } catch (error) {
      // Hermes refuses a stale revision and names the current one.
      const current = error?.data;
      if (typeof current?.revision !== "number") throw error;
      await remove(current.revision, current.execution_generation ?? session.execution_generation);
    }
  } catch {
    // The rewrite is already done. An empty record left behind does no harm.
  }
}

async function runInHiddenSession(text) {
  // Without a profile, the session would open in the launch profile, not the one on screen.
  const profile = host.state.focusedSessionProfile.get();
  const scope = profile ? { profile } : {};
  const session = await host.request("session.create", { ...scope, hidden: true });
  try {
    return await runCommand(session.session_id, text, scope);
  } finally {
    void removeHiddenSession(session, scope);
  }
}

async function requestRewrite(sessionId, text) {
  if (!sessionId) return runInHiddenSession(text);
  try {
    return await runCommand(sessionId, text);
  } catch (error) {
    if (/session/i.test(String(error?.message ?? error))) return runInHiddenSession(text);
    throw error;
  }
}

async function rewrite() {
  const sessionId = focusedSession();
  const key = keyFor(sessionId);
  if (busy.has(key)) {
    busy.delete(key);
    emit();
    return;
  }
  const draft = (await host.composer.getDraft(sessionId)) ?? "";
  const text = draft.trim();
  if (!text) {
    tell("Type a request first.");
    return;
  }
  if (text.startsWith("/")) {
    tell("Slash commands are left as they are.");
    return;
  }

  const token = {};
  busy.set(key, token);
  emit();
  try {
    const result = await requestRewrite(sessionId, text);
    if (busy.get(key) !== token) return;
    if (!result.changed) {
      tell(`Left unchanged: ${result.note || "nothing to improve"}.`);
      return;
    }
    if (focusedSession() !== sessionId) {
      tell("You switched chats, so the rewrite was dropped.");
      return;
    }
    if (normalize(await host.composer.getDraft(sessionId)) !== normalize(text)) {
      tell("Your draft changed, so it was kept as it is.");
      return;
    }
    if (!(await host.composer.setDraft(sessionId, result.prompt))) {
      throw new Error("the message box is not available");
    }
    undo.set(key, { original: draft, rewritten: result.prompt });
    host.composer.focus(sessionId);
  } catch (error) {
    if (busy.get(key) === token) {
      tell(`Couldn't rewrite: ${error?.message ?? error}. Your draft is unchanged.`, "error");
    }
  } finally {
    if (busy.get(key) === token) busy.delete(key);
    emit();
  }
}

async function restore() {
  const sessionId = focusedSession();
  const key = keyFor(sessionId);
  const entry = undo.get(key);
  if (!entry) return;
  undo.delete(key);
  emit();
  if (normalize(await host.composer.getDraft(sessionId)) !== normalize(entry.rewritten)) {
    tell("The draft changed after the rewrite, so it was kept.");
    return;
  }
  if (await host.composer.setDraft(sessionId, entry.original)) host.composer.focus(sessionId);
  else tell("Couldn't restore your draft.", "error");
}

async function checkUndo(sessionId) {
  const key = keyFor(sessionId);
  const entry = undo.get(key);
  if (!entry) return;
  const draft = await host.composer.getDraft(sessionId);
  if (undo.get(key) === entry && normalize(draft) !== normalize(entry.rewritten)) {
    undo.delete(key);
    emit();
  }
}

function ActionButton({ active, icon, label, onClick, spinning }) {
  return jsx(Tip, {
    label,
    children: jsx(Button, {
      "aria-label": label,
      className: cn(
        "size-(--composer-control-size) shrink-0 rounded-md",
        "text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground",
        active && "text-foreground",
      ),
      onClick,
      size: "icon-xs",
      type: "button",
      variant: "ghost",
      children: jsx(Codicon, { name: icon, size: 14, spinning }),
    }),
  });
}

function PromptLabButton() {
  useSyncExternalStore(subscribe, getVersion);
  const sessionId = useValue(host.state.focusedSessionId) || null;
  const key = keyFor(sessionId);
  const rewriting = busy.has(key);
  const canUndo = undo.has(key) && !rewriting;

  useEffect(() => {
    if (!canUndo || !scheduleCheck) return undefined;
    return scheduleCheck(() => void checkUndo(sessionId));
  }, [canUndo, sessionId]);

  return jsxs("div", {
    className: "flex h-(--composer-control-size) items-center gap-1",
    children: [
      jsx(ActionButton, {
        active: rewriting,
        icon: rewriting ? "sync" : "sparkle",
        label: rewriting ? "Cancel rewrite" : "Rewrite as a clearer prompt",
        onClick: () => void rewrite(),
        spinning: rewriting,
      }),
      canUndo
        ? jsx(ActionButton, { icon: "discard", label: "Undo rewrite", onClick: () => void restore() })
        : null,
    ],
  });
}

export default {
  id: "prompt-lab",
  name: "Prompt Lab",
  description: "A button beside Send that rewrites your draft as a clearer prompt, in the voice you pick in its settings. It never sends.",

  register(ctx) {
    scheduleCheck = (check) => ctx.setInterval(check, UNDO_CHECK_MS);
    ctx.onDispose(() => {
      scheduleCheck = null;
      busy.clear();
      undo.clear();
      emit();
    });
    ctx.registerMany([
      {
        id: "rewrite-button",
        area: COMPOSER_AREAS.actions,
        order: 40,
        render: () => jsx(PromptLabButton, {}),
      },
      {
        id: "palette",
        area: PALETTE_AREA,
        data: {
          id: "prompt-lab.rewrite",
          label: "Rewrite draft as a clearer prompt",
          keywords: ["prompt", "rewrite", "enhance", "structure"],
          run: () => void rewrite(),
        },
      },
      {
        id: "palette-voice",
        area: PALETTE_AREA,
        data: {
          id: "prompt-lab.voice",
          label: "Prompt Lab: choose voice",
          keywords: ["prompt", "voice", "tone", "style", "settings"],
          run: () => host.navigate(pluginSettingsHref("prompt-lab")),
        },
      },
      {
        id: "keybind",
        area: KEYBINDS_AREA,
        data: {
          id: "prompt-lab.rewrite",
          label: "Rewrite draft as a clearer prompt",
          category: "Prompt Lab",
          defaults: ["mod+alt+e"],
          run: () => void rewrite(),
        },
      },
    ]);
  },
};
