// Run from the repo root: node --test tests/desktop.test.mjs
import assert from "node:assert/strict";
import { register } from "node:module";
import { beforeEach, test } from "node:test";

register("./desktop_stubs.mjs", import.meta.url);
const { app } = await import("./desktop_sdk_stub.mjs");
const plugin = (await import("../desktop/plugin.js")).default;

let run;
let openVoice;
let button;
let settingsChanged;
let disposers = [];
function load() {
  plugin.register({
    onDispose: (fn) => disposers.push(fn),
    onEvent: (name, fn) => {
      if (name === "plugin.prompt-lab.settings.changed") settingsChanged = fn;
    },
    setInterval: () => () => {},
    registerMany: (items) => {
      run = items.find((item) => item.id === "palette").data.run;
      openVoice = items.find((item) => item.id === "palette-voice").data.run;
      button = items.find((item) => item.id === "rewrite-button");
    },
  });
}
load();

const REWRITE = "Goal: Fix the login.";
const ok = (text = REWRITE) => async () => ({ text });
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));
const lastNotice = () => app.notices.at(-1)?.message ?? "";
const calls = () => app.requests.filter((request) => request.method === "llm.oneshot");

function buttons() {
  const root = button.render().type({});
  return root.props.children.filter(Boolean).map((element) => element.props);
}

const undoButton = () => buttons().find((props) => props.label === "Undo rewrite");

beforeEach(() => {
  disposers.forEach((dispose) => dispose());
  disposers = [];
  load();
  Object.assign(app, { profile: "", sessionId: "s1", draft: "fix the login page", requests: [], notices: [], navigations: [], settings: {}, settingsFail: false, respond: ok(), acceptDraft: true });
});

test("a rewrite is one stateless model call and never sends", async () => {
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.deepEqual(app.requests.map((request) => request.method), ["plugins.manage", "llm.oneshot"]);
  const { instructions, ...rest } = calls()[0].params;
  assert.deepEqual(rest, { session_id: "s1", input: "REQUEST:\nfix the login page", task: "prompt_lab", temperature: 0.2, max_tokens: 1200 });
  assert.match(instructions, /Goal: one sentence/);
  assert.doesNotMatch(instructions, /\{voice\}/);
});

test("a new chat needs no session at all", async () => {
  app.sessionId = null;
  app.profile = "work";
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.deepEqual(app.requests.map((request) => request.method), ["plugins.manage", "llm.oneshot"]);
  assert.equal(app.requests[0].params.profile, "work");
  assert.equal(calls()[0].params.profile, "work");
  assert.equal("session_id" in calls()[0].params, false);
});

test("a chat the gateway no longer knows retries without it", async () => {
  app.respond = async (_method, params) => {
    if (params.session_id) throw new Error("session not found");
    return ok()();
  };
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.equal(calls().length, 2);
  assert.equal("session_id" in calls()[1].params, false);
});

test("the voice saved in Settings shapes the instructions", async () => {
  app.settings = { voice: "friendly" };
  run();
  await settle();
  assert.match(calls()[0].params.instructions, /warm, conversational tone/);
  assert.doesNotMatch(calls()[0].params.instructions, /Goal: one sentence/);
});

test("a custom voice uses the user's own words, kept literal", async () => {
  app.settings = { voice: "custom", custom_voice: "Sound like a pirate. Costs $& more." };
  run();
  await settle();
  assert.match(calls()[0].params.instructions, /written by the user: Sound like a pirate\. Costs \$& more\./);
});

test("an empty custom voice falls back to structured", async () => {
  app.settings = { voice: "custom", custom_voice: "  " };
  run();
  await settle();
  assert.match(calls()[0].params.instructions, /Goal: one sentence/);
});

test("settings are read once, then again after a save", async () => {
  run();
  await settle();
  app.draft = "fix the login page";
  run();
  await settle();
  assert.equal(app.requests.filter((request) => request.method === "plugins.manage").length, 1);
  app.settings = { voice: "concise" };
  settingsChanged();
  app.draft = "fix the login page";
  run();
  await settle();
  assert.equal(app.requests.filter((request) => request.method === "plugins.manage").length, 2);
  assert.match(calls().at(-1).params.instructions, /one short, direct paragraph/);
});

test("unreadable settings still rewrite, in the default voice", async () => {
  app.settingsFail = true;
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.match(calls()[0].params.instructions, /Goal: one sentence/);
});

test("an empty draft makes no model call", async () => {
  app.draft = "   ";
  run();
  await settle();
  assert.equal(app.requests.length, 0);
  assert.match(lastNotice(), /Type a request/);
});

test("slash commands are not rewritten", async () => {
  app.draft = "/goal ship it";
  run();
  await settle();
  assert.equal(app.requests.length, 0);
  assert.equal(app.draft, "/goal ship it");
});

test("a two-word draft is too short and makes no model call", async () => {
  app.draft = "fix login";
  run();
  await settle();
  assert.equal(calls().length, 0);
  assert.match(lastNotice(), /too short/);
});

test("a draft that is already structured is left alone in the structured voice", async () => {
  app.draft = "Goal: fix it\nConstraints:\n- keep the API";
  run();
  await settle();
  assert.equal(calls().length, 0);
  assert.match(lastNotice(), /already structured/);
  assert.equal(undoButton(), undefined);
});

test("another voice still rewrites a structured draft", async () => {
  app.settings = { voice: "concise" };
  app.draft = "Goal: fix it\nConstraints:\n- keep the API";
  app.respond = ok("Fix it and keep the API.");
  run();
  await settle();
  assert.equal(app.draft, "Fix it and keep the API.");
});

test("thinking tags and code fences are stripped from the reply", async () => {
  app.respond = ok("<think>hm</think>\n```text\nGoal: Fix the login.\n```");
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
});

test("a draft edited during the rewrite is kept", async () => {
  app.respond = async () => {
    app.draft = "fix the login page and the footer";
    return ok()();
  };
  run();
  await settle();
  assert.equal(app.draft, "fix the login page and the footer");
  assert.match(lastNotice(), /draft changed/);
});

test("switching chats during the rewrite drops it", async () => {
  app.respond = async () => {
    app.sessionId = "s2";
    return ok()();
  };
  run();
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.match(lastNotice(), /switched chats/);
});

test("clicking while it runs cancels the rewrite", async () => {
  let finish;
  app.respond = () => new Promise((resolve) => { finish = resolve; });
  run();
  await settle();
  assert.equal(buttons()[0].label, "Cancel rewrite");
  buttons()[0].onClick();
  await settle();
  finish(await ok()());
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.equal(buttons()[0].label, "Rewrite as a clearer prompt");
});

test("a failed rewrite says so and keeps the draft", async () => {
  app.sessionId = null;
  app.respond = async () => { throw new Error("one-shot generation failed: provider down"); };
  run();
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.equal(app.notices.at(-1).kind, "error");
  assert.match(lastNotice(), /provider down/);
});

test("an empty reply is an error, not a blank draft", async () => {
  app.respond = ok("   ");
  run();
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.match(lastNotice(), /returned no text/);
});

test("a reply equal to the draft leaves it and offers no undo", async () => {
  app.respond = ok("fix the login page");
  run();
  await settle();
  assert.match(lastNotice(), /Left unchanged/);
  assert.equal(undoButton(), undefined);
});

test("undo restores exactly what was typed", async () => {
  app.draft = "  fix the login page\n";
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  undoButton().onClick();
  await settle();
  assert.equal(app.draft, "  fix the login page\n");
  assert.equal(undoButton(), undefined);
});

test("undo keeps a rewrite the user went on to edit", async () => {
  run();
  await settle();
  app.draft = `${REWRITE} Also check Safari.`;
  undoButton().onClick();
  await settle();
  assert.equal(app.draft, `${REWRITE} Also check Safari.`);
  assert.match(lastNotice(), /kept/);
});

test("the choose-voice command opens Prompt Lab's settings page", () => {
  openVoice();
  assert.deepEqual(app.navigations, ["/settings?tab=plugins&plugin=prompt-lab"]);
});
