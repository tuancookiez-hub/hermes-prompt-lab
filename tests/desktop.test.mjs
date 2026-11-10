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
let disposers = [];
plugin.register({
  onDispose: (fn) => disposers.push(fn),
  setInterval: () => () => {},
  registerMany: (items) => {
    run = items.find((item) => item.id === "palette").data.run;
    openVoice = items.find((item) => item.id === "palette-voice").data.run;
    button = items.find((item) => item.id === "rewrite-button");
  },
});

const REWRITE = "Goal: Fix the login.";
const ok = (prompt = REWRITE) => async () => ({ output: JSON.stringify({ ok: true, prompt, changed: true, note: "" }) });
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));
const lastNotice = () => app.notices.at(-1)?.message ?? "";

function buttons() {
  const root = button.render().type({});
  return root.props.children.filter(Boolean).map((element) => element.props);
}

const undoButton = () => buttons().find((props) => props.label === "Undo rewrite");

beforeEach(() => {
  disposers.forEach((dispose) => dispose());
  Object.assign(app, { cwd: "", profile: "", sessionId: "s1", draft: "fix the login page", requests: [], notices: [], navigations: [], respond: ok(), acceptDraft: true, detachFails: false, staleRevision: false });
});

test("an open chat rewrites through /promptlab and never sends", async () => {
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.equal(app.requests.length, 1);
  assert.deepEqual(app.requests[0].params, { session_id: "s1", command: "/promptlab --json fix the login page" });
});

test("a new chat runs in a hidden session, then ends and deletes it", async () => {
  app.sessionId = null;
  app.cwd = "E:/project";  // project folders are no longer sent
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.deepEqual(app.requests.map((request) => request.method), ["session.create", "slash.exec", "session.detach", "session.mutate"]);
  assert.deepEqual(app.requests[0].params, { hidden: true });
  assert.equal(app.requests[1].params.session_id, "hidden");
  assert.deepEqual(app.requests[2].params, { session_id: "hidden", subscription_id: "sub", end_reason: "prompt_lab_done" });
  const { request_id: requestId, ...removal } = app.requests[3].params;
  assert.ok(requestId);
  assert.deepEqual(removal, { session_id: "stored", expected_revision: 3, expected_generation: 1, operation: "delete", payload: {} });
});

test("a hidden session that won't end is not deleted, and the rewrite still lands", async () => {
  app.sessionId = null;
  app.detachFails = true;
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.equal(app.requests.at(-1).method, "session.detach");
  assert.equal(app.notices.length, 0);
});

test("a stale revision is retried once with the one Hermes names", async () => {
  app.sessionId = null;
  app.staleRevision = true;
  run();
  await settle();
  const removals = app.requests.filter((request) => request.method === "session.mutate");
  assert.equal(removals.length, 2);
  assert.equal(removals[1].params.expected_revision, 5);
  assert.equal(removals[1].params.expected_generation, 2);
});

test("the hidden session opens in the profile on screen", async () => {
  app.sessionId = null;
  app.profile = "work";
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.deepEqual(app.requests.map((request) => request.params.profile), ["work", "work", "work", "work"]);
});

test("the hidden session is removed when the rewrite fails", async () => {
  app.sessionId = null;
  app.respond = async () => ({ output: JSON.stringify({ ok: false, error: "provider down" }) });
  run();
  await settle();
  assert.deepEqual(app.requests.slice(-2).map((request) => request.method), ["session.detach", "session.mutate"]);
  assert.equal(app.draft, "fix the login page");
});

test("a session the gateway no longer knows falls back to a hidden session", async () => {
  app.respond = async (_method, params) => {
    if (params.session_id === "s1") throw new Error("session not found");
    return ok()();
  };
  run();
  await settle();
  assert.equal(app.draft, REWRITE);
  assert.deepEqual(app.requests.map((request) => request.method), ["slash.exec", "session.create", "slash.exec", "session.detach", "session.mutate"]);
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
  app.respond = async () => ({ output: JSON.stringify({ ok: false, error: "provider down" }) });
  run();
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.equal(app.notices.at(-1).kind, "error");
  assert.match(lastNotice(), /provider down/);
});

test("output that is not JSON means the agent side is not active", async () => {
  app.respond = async () => ({ output: "Unknown command `/promptlab`." });
  run();
  await settle();
  assert.equal(app.draft, "fix the login page");
  assert.match(lastNotice(), /isn't active in this profile/);
});

test("an unchanged result leaves the draft and offers no undo", async () => {
  app.respond = async () => ({ output: JSON.stringify({ ok: true, prompt: "fix the login page", changed: false, note: "already structured" }) });
  run();
  await settle();
  assert.match(lastNotice(), /already structured/);
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
