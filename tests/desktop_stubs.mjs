// Loader hook: runs desktop/plugin.js in plain Node with small stand-ins for what the app provides.
const stubUrl = new URL("./desktop_sdk_stub.mjs", import.meta.url).href;
const STUBBED = new Set(["@hermes/plugin-sdk", "react", "react/jsx-runtime"]);

export async function resolve(specifier, context, next) {
  return STUBBED.has(specifier) ? { url: stubUrl, shortCircuit: true } : next(specifier, context);
}
