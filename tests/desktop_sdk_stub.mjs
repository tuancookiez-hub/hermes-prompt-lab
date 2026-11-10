// Stand-ins for @hermes/plugin-sdk and react. The test sets the fake app state on `app`.
export const app = {
  cwd: "",
  profile: "",
  sessionId: "s1",
  draft: "",
  requests: [],
  notices: [],
  navigations: [],
  respond: async () => ({}),
  acceptDraft: true,
  detachFails: false,
  staleRevision: false,
  afterFirstRead: null,
};

export const host = {
  state: {
    cwd: { get: () => app.cwd },
    focusedSessionId: { get: () => app.sessionId },
    focusedSessionProfile: { get: () => app.profile },
  },
  notify: (notice) => app.notices.push(notice),
  navigate: (path) => app.navigations.push(path),
  request: (method, params) => {
    app.requests.push({ method, params });
    if (method === "session.create") {
      return Promise.resolve({ session_id: "hidden", stored_session_id: "stored", subscription_id: "sub", revision: 3, execution_generation: 1 });
    }
    if (method === "session.detach") return app.detachFails ? Promise.reject(new Error("detach failed")) : Promise.resolve({});
    if (method === "session.mutate" && app.staleRevision) {
      app.staleRevision = false;
      return Promise.reject(Object.assign(new Error("revision_conflict"), { data: { revision: 5, execution_generation: 2 } }));
    }
    if (method === "session.mutate") return Promise.resolve({});
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
