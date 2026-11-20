// Screenshots of the ATLAS ORBIT page rendered by the harness (visual QA). Needs a Vite dev server:
//   npx vite --port 5179 &   then   node tests/visual/orbit-shots.mjs <out-dir>
import fs from "node:fs";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const out = process.argv[2] ?? "test-results/orbit";
fs.mkdirSync(out, { recursive: true });
const plan = {
  title: "Rocket-sim public release", objective: "Publish rocket-sim with docs and a tested installer", outcome: "A tagged release people can install",
  brief: "Rocket-sim is a small two-stage trajectory model. This project turns it into something other people can install and trust.",
  ideas: ["Ship a one-file Windows installer", "Add a gallery of example trajectories", "Publish the docs as a static site"],
  phases: ["Understand", "Build", "Verify", "Release"],
  tasks: [["u1", "Review the trajectory model", "Understand"], ["u2", "List what users need", "Understand"], ["b1", "Write the user guide", "Build"], ["b2", "Package the installer", "Build"], ["v1", "Run the test suite", "Verify"], ["r1", "Tag and publish", "Release"]].map(([id, title, phase]) => ({ id, title, phase, detail: "", priority: "normal", estimate: "", status: "confirmed", operation: id === "r1" ? "manual" : "atlas" })),
  deps: [{ from: "u1", to: "b1" }, { from: "b1", to: "v1" }, { from: "b2", to: "v1" }, { from: "v1", to: "r1" }],
  assumptions: ["The model code is the current source of truth"], questions: ["Which hosting?", "Launch date?"], risks: ["Installer signing is not set up"],
};
const node = (id, title, status, output = "") => ({ id, title, detail: "", phase: "Build", operation: "atlas", deps: [], status, conversation_id: null, output, error: "", history: [{ at: "2026-11-20T10:00:00Z", event: status, status }] });
const base = { id: "s1", title: "Rocket-sim public release", created_at: "", updated_at: "", conversation_id: "c1", autonomy: "balanced", allowed: [], versions: [{ version: 1, plan, author: "atlas", why: "Proposed in conversation", at: "2026-11-20T10:00:00Z" }], active_version: 1, approved_version: 1, workflow: null, events: [{ at: "2026-11-20T10:00:00Z", kind: "plan.approved", detail: "version 1 approved by you" }], archived: false, reviewed: false, completed: false, layout: null };
const running = { ...base, workflow: { id: "w", plan_version: 1, autonomy: "balanced", allowed: [], paused: false, state: "awaiting_approval", created_at: "", nodes: [node("u1", "Review the trajectory model", "completed", "Assumptions: fixed Isp per stage, no wind."), node("u2", "List what users need", "completed"), node("b1", "Write the user guide", "awaiting_approval"), node("b2", "Package the installer", "ready"), node("v1", "Run the test suite", "waiting"), node("r1", "Tag and publish", "waiting")] } };
const scenes = [
  ["orbit-01-entry", null, "command", 700, false],
  ["orbit-02-empty", null, "command", 3200, false],
  ["orbit-03-command", base, "command", 1600, true],
  ["orbit-04-intelligence", base, "intelligence", 1600, true],
  ["orbit-05-design", base, "design", 1600, true],
  ["orbit-06-operations-approval", running, "operations", 1600, true],
  ["orbit-07-reduced-motion", running, "operations", 900, true, "reduce"],
  ["orbit-08-immersive", base, "command", 1600, true, undefined, true],
];
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
for (const [name, session, env, wait, seen, motion, immersive] of scenes) {
  for (const [w, h, suffix] of [[1440, 900, ""], ...(name === "orbit-03-command" ? [[1280, 800, "-1280x800"]] : [])]) {
    const page = await browser.newPage({ viewport: { width: w, height: h }, reducedMotion: motion ?? "no-preference" });
    await page.addInitScript(([s, e, seen]) => {
      window.__ORBIT_SESSION__ = s ? { ...s, layout: { env: e } } : null;
      localStorage.setItem("orbit.introSeen", seen ? "1" : "0");
      localStorage.setItem("orbit.fx", JSON.stringify({ cinematic: !seen }));
      if (s) localStorage.setItem("orbit.session", "s1");
    }, [session, env, seen]);
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`http://localhost:5179/tests/visual/orbit-harness.html?env=${env}${immersive ? "&immersive=1" : ""}`);
    await page.waitForTimeout(wait);
    await page.screenshot({ path: `${out}/${name}${suffix}.png` });
    console.log(name + suffix, errors.length ? `ERRORS: ${errors.join(" | ")}` : "ok");
    await page.close();
  }
}
await browser.close();
