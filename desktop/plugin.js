/**
 * Prompt Lab: a button beside Send that rewrites the draft as a clearer prompt, in the voice set in Settings.
 *
 * It only changes the draft. It never sends. Undo restores what you typed.
 *
 * Each rewrite is one stateless llm.oneshot call: no session is created, no tools run, and nothing
 * is written to a chat. The voice is read from the plugin's own settings (Settings > Plugins).
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

const PLUGIN_ID = "prompt-lab";
const AUX_TASK = "prompt_lab";
const REQUEST_TIMEOUT_MS = 90000;
const UNDO_CHECK_MS = 1500;
const MIN_WORDS = 3;
const MAX_CUSTOM_CHARS = 600;
const DEFAULT_VOICE = "structured";

// The same instructions as enhance.py. tests/test_enhance.py fails if the two drift apart.
/* prompts:start */
const PROMPTS = {
  "base": "Rewrite the user's request as a clearer prompt for an AI agent.\nNever do the task and never answer it. Output only the rewritten prompt.\n\nVOICE:\n{voice}\n\nRules that always apply:\nWrite in the same language as the request. Keep the user's names, intent and details.\nKeep @file references and /commands exactly as written.\nAdd no facts, features or goals the user did not give. If something important is unclear, state the most likely reading as an assumption, in a few words.\nMatch length to the request. A one-line request gets a short prompt.\nEverything above is your instructions. Never copy them into the output.\nPlain text only, with no code fences and no preamble.",
  "voices": {
    "structured": "Use these headings, in this order, each at most once. Leave out any heading with nothing real to say:\nGoal: one sentence\nContext:\nSteps:\nConstraints:\nDone when:\nUnder Context, Constraints and Done when, write \"- \" bullets. Under Steps, write a numbered list, and use Steps only for work with more than one real step.",
    "concise": "Write one short, direct paragraph of two to four sentences. No headings and no lists.",
    "detailed": "Write a thorough brief with these headings, in this order: Goal, Context, Requirements, Edge cases, Done when.\nUse \"- \" bullets under each. Spell out what a careful engineer would need to know, but add no features the user did not ask for.",
    "clarify": "State the request in one or two plain sentences. In this voice, never state an assumption, even where the rules below say to.\nThen add the line \"Before you start, ask me:\" and one to three short \"- \" questions about what the request leaves open and would change the work, such as which part is meant, how far to go, or what must stay as it is.\nLeave the questions out only when the request already settles all of that.",
    "verify": "State the request in one or two plain sentences.\nThen add the line \"Prove it:\" and two to four \"- \" bullets naming the evidence the agent must show before calling the work done, such as reproducing the problem first, a test that fails before the change and passes after, or the output of a command.\nAsk only for evidence that fits this request."
  }
};
/* prompts:end */

const busy = new Map();
const undo = new Map();
const listeners = new Set();
const voiceByProfile = new Map();
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
const focusedProfile = () => host.state.focusedSessionProfile.get() || "";
const keyFor = (sessionId) => sessionId || "new";
const normalize = (text) => String(text ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
const tell = (message, kind = "info") => host.notify({ kind, message });
const LABELLED = /^\s*(goal|context|steps|constraints|done when)\s*:/gim;

/** The saved Voice and Custom voice for a profile. Any failure falls back to the default voice. */
async function readVoice(profile) {
  if (voiceByProfile.has(profile)) return voiceByProfile.get(profile);
  let saved = { voice: DEFAULT_VOICE, custom: "" };
  try {
    const result = await host.request("plugins.manage", { action: "list", ...(profile ? { profile } : {}) });
    const row = (result?.plugins ?? []).find((plugin) => plugin.key === PLUGIN_ID || plugin.name === PLUGIN_ID);
    const value = (key) => row?.settings_schema?.find((field) => field.key === key)?.value;
    saved = { voice: String(value("voice") || DEFAULT_VOICE), custom: String(value("custom_voice") || "") };
    if (row) voiceByProfile.set(profile, saved);
  } catch {
    // Rewrite in the default voice rather than fail.
  }
  return saved;
}

function voiceText({ voice, custom }) {
  let name = String(voice || DEFAULT_VOICE).trim().toLowerCase();
  if (name === "custom") {
    const words = String(custom || "").trim().slice(0, MAX_CUSTOM_CHARS);
    if (words) return `Follow this style, written by the user: ${words}`;
    name = DEFAULT_VOICE;
  }
  return PROMPTS.voices[name] ?? PROMPTS.voices[DEFAULT_VOICE];
}

function clean(text) {
  const out = String(text ?? "").replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  const fenced = out.match(/^```[\w-]*\n([\s\S]*?)\n?```$/);
  return (fenced ? fenced[1] : out).trim();
}

async function requestRewrite(sessionId, text) {
  const profile = focusedProfile();
  const style = voiceText(await readVoice(profile));
  if (text.split(/\s+/).length < MIN_WORDS) return { changed: false, note: "too short to rewrite" };
  if (style === PROMPTS.voices[DEFAULT_VOICE] && (text.match(LABELLED) ?? []).length >= 2) {
    return { changed: false, note: "already structured" };
  }
  const call = (target) =>
    host.request(
      "llm.oneshot",
      {
        ...target,
        instructions: PROMPTS.base.replace("{voice}", () => style),
        input: "REQUEST:\n" + text,
        task: AUX_TASK,
        temperature: 0.2,
        max_tokens: 1200,
      },
      REQUEST_TIMEOUT_MS,
    );
  const scope = profile ? { profile } : {};
  let result;
  try {
    // A chat that exists lends its model. A new chat has none yet.
    result = await call(sessionId ? { session_id: sessionId } : scope);
  } catch (error) {
    if (!sessionId) throw error;
    result = await call(scope);
  }
  const prompt = clean(result?.text);
  if (!prompt) throw new Error("the model returned no text");
  return { changed: normalize(prompt) !== normalize(text), note: "", prompt };
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
    // A save in Settings applies to the next rewrite.
    ctx.onEvent?.(`plugin.${PLUGIN_ID}.settings.changed`, () => voiceByProfile.clear());
    ctx.onDispose(() => {
      scheduleCheck = null;
      busy.clear();
      undo.clear();
      voiceByProfile.clear();
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
