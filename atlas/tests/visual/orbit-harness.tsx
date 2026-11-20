/**
 * Visual QA harness: renders the real ORBIT page (React, canvas core, voice ring) in a browser with the Tauri
 * IPC replaced by fixed sample answers, so screenshots can be taken without building the desktop app.
 * The sample session goes through the real zod schemas; nothing here ships in the app.
 */
import "@/styles/globals.css";
import { createRoot } from "react-dom/client";
import { OrbitPage } from "@/features/orbit/Orbit";
import { useUi } from "@/state/ui";

declare global {
  interface Window {
    __ORBIT_SESSION__: unknown;
    __TAURI_INTERNALS__: unknown;
  }
}

const params = new URLSearchParams(location.search);
const session = window.__ORBIT_SESSION__;
let cb = 0;
window.__TAURI_INTERNALS__ = {
  transformCallback: () => ++cb,
  invoke: async (cmd: string) => {
    if (cmd === "orbit_sessions") return session ? [{ id: "s1", title: "Rocket-sim public release", updated_at: "", versions: 1, workflow_state: null }] : [];
    if (cmd === "orbit_get") return session;
    if (cmd === "orbit_apply") return { session, message: "ok" };
    if (cmd === "grants_list") return [{ id: "g1", path: "C:/Users/me/Documents/rocket-sim/README.md", label: "README.md", created_at: "" }];
    if (cmd === "conversation_messages")
      return session ? [{ id: "m1", conversation_id: "c1", seq: 2, role: "assistant", content: "Here is a first plan. Two things I still need: which hosting you prefer, and the launch date.", parts: null, provider_id: null, model: null, status: "complete", task_id: null, usage: null, created_at: "" }] : [];
    return null;
  },
};
if (params.get("env")) localStorage.setItem("orbit.session", "s1");
if (params.get("immersive")) useUi.getState().setImmersive(true);
createRoot(document.getElementById("root")!).render(<div className="h-full bg-bg-1 text-text-1">{<OrbitPage />}</div>);
