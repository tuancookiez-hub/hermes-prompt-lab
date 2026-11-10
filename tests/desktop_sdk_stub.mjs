// Stand-ins for @hermes/plugin-sdk and react. The test sets the fake app state on `app`.
export const app = {
  profile: "",
  sessionId: "s1",
  draft: "",
  requests: [],
  notices: [],
  navigations: [],
  settings: {},
  settingsFail: false,
  respond: async () => ({}),
  acceptDraft: true,
};

const settingsRow = () => ({
  key: "prompt-lab",
  name: "prompt-lab",
  settings_schema: [
    { key: "voice", value: app.settings.voice ?? "structured" },
    { key: "custom_voice", value: app.settings.custom_voice ?? "" },
  ],
});

export const host = {
  state: {
    focusedSessionId: { get: () => app.sessionId },
    focusedSessionProfile: { get: () => app.profile },
  },
  notify: (notice) => app.notices.push(notice),
  navigate: (path) => app.navigations.push(path),
  request: (method, params) => {
    app.requests.push({ method, params });
    if (method === "plugins.manage") {
      return app.settingsFail ? Promise.reject(new Error("unavailable")) : Promise.resolve({ plugins: [{ key: "other" }, settingsRow()] });
    }
    return app.respond(method, params);
  },
  composer: {
    getDraft: async () => app.draft,
    setDraft: async (_sessionId, text) => {
      if (app.acceptDraft) app.draft = text;
      return app.acceptDraft;
    },
    focus: () => {},
  },
};

export const jsx = (type, props) => ({ type, props });
export const jsxs = jsx;
export const useValue = (atom) => atom.get();
export const useSyncExternalStore = () => 0;
export const useEffect = () => {};
export const cn = (...parts) => parts.filter(Boolean).join(" ");
export const Button = "button";
export const Codicon = "icon";
export const Tip = "tip";
export const COMPOSER_AREAS = { actions: "composer.actions" };
export const KEYBINDS_AREA = "keybinds";
export const PALETTE_AREA = "palette";
export const pluginSettingsHref = (plugin) => `/settings?tab=plugins&plugin=${plugin}`;
