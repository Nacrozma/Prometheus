// Restart phase of the end-to-end suite: relaunches the same desktop app on the same data folder
// that tests/e2e/app.e2e.mjs left behind (a reply in progress, a Focus session on a task), as if
// Atlas had been closed for two hours. The two hours are the only stand-in: the previous run left
// `e2e-away-minutes` in the data folder, and the e2e build alone moves the recorded "last active"
// time (and the running Focus session) back by that much before start-up. Everything after that is
// the real start-up path: task recovery, the recap, the Focus session finishing, persistence.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { Builder, By, until } from "selenium-webdriver";

const APP = path.resolve(process.platform === "win32" ? "target/debug/atlas-desktop.exe" : "target/debug/atlas-desktop");
const SHOTS = process.env.ATLAS_SCREENSHOTS;
const DIR = process.env.ATLAS_DATA_DIR;
let driver;

const invoke = (cmd, args = {}) =>
  driver.executeAsyncScript(
    "const [c, a, done] = arguments; window.__TAURI_INTERNALS__.invoke(c, a).then(done, (e) => done({ __error: e }));",
    cmd,
    args,
  );
const find = (locator, ms = 15000) => driver.wait(until.elementLocated(locator), ms);
const gone = (selector) => driver.executeScript(`return document.querySelector(${JSON.stringify(selector)}) === null`);
const pageText = () => driver.executeScript("return document.body.innerText");
async function shot(name) {
  if (!SHOTS) return;
  await driver.sleep(400);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), await driver.takeScreenshot(), "base64");
}
async function go(key) {
  const { Key } = await import("selenium-webdriver");
  await driver.actions().keyDown(Key.CONTROL).sendKeys(key).keyUp(Key.CONTROL).perform();
  await driver.sleep(250);
}
/** A reply in progress shows a Stop button (the Focus bar's own Stop is not one). */
const replyRunning = () =>
  driver.executeScript(`return [...document.querySelectorAll("button")].some((b) => !b.closest("[data-focus-bar]") && !b.textContent.includes("Stop focus") && b.textContent.replace(/\\s+/g, " ").includes("Stop"))`);

before(async () => {
  assert.ok(DIR, "run.sh sets the data folder");
  driver = await new Builder()
    .usingServer("http://127.0.0.1:4444/")
    .withCapabilities({
      browserName: "wry",
      "tauri:options": process.platform === "win32" ? { application: APP, webviewOptions: {} } : { application: APP },
    })
    .build();
});

after(async () => {
  await driver?.quit();
});

test("after two hours closed: the interrupted reply is listed, not resumed; the Focus session finished on time; the recap opens what was interrupted; data survived", async () => {
  const handoff = JSON.parse(fs.readFileSync(path.join(DIR, "..", "e2e-handoff.json"), "utf8"));

  // Atlas opens to its main view: the introduction played once, on the first launch.
  await find(By.css('nav[aria-label="Main"]'), 30000);
  assert.equal(await gone("[data-first-launch='first']"), true, "no first-launch introduction on a restart");
  assert.equal(fs.existsSync(path.join(DIR, "e2e-away-minutes")), false, "the stand-in is used once");

  // The reply that was running when Atlas closed is marked interrupted. Nothing restarted it.
  const task = (await invoke("tasks_list", { limit: 50 })).find((t) => t.id === handoff.task);
  assert.equal(task?.status, "interrupted", JSON.stringify(task));

  // The Focus session ran out while Atlas was closed: it completes at its planned end, with a summary.
  await driver.wait(async () => (await invoke("focus_status")).active === null, 15000, "the session completed");
  const last = (await invoke("focus_status")).history[0];
  assert.equal(last.id, handoff.focus);
  assert.equal(last.outcome, "completed");
  assert.equal(Math.round((Date.parse(last.ended_at) - Date.parse(last.started_at)) / 60000), 15, "the 15 minutes set, not the time Atlas was closed");
  assert.equal(last.todo_title, "Prepare the slides");
  await driver.wait(async () => (await invoke("notifications_list", { limit: 50 })).items.some((n) => n.category === "focus"), 15000, "focus summary raised");
  const items = (await invoke("notifications_list", { limit: 50 })).items;
  const summary = items.filter((n) => n.category === "focus");
  assert.equal(summary.length, 1, "one summary, not repeated");
  assert.equal(summary[0].title, "Focus session finished: Prepare the slides");
  assert.match(summary[0].detail, /^15 minutes of focus\./);
  // Notifications from before the restart are all still there, none held.
  const ids = new Set(items.map((n) => n.id));
  for (const id of handoff.kept) assert.ok(ids.has(id), `notification ${id} kept across the restart`);
  assert.ok(items.every((n) => !n.held));
  // The task list survived.
  const todos = await invoke("todos_list", { filter: { view: "all" } });
  assert.ok(!todos.__error, JSON.stringify(todos));
  assert.ok(todos.some((t) => t.id === handoff.todo), "the to-do survived the restart");

  // The recap: built from what was recorded. The interrupted reply is listed with Open.
  const r = await invoke("recap_get");
  assert.ok(r && !r.empty, JSON.stringify(r));
  assert.ok(r.interrupted.some(([id]) => id === handoff.task), JSON.stringify(r.interrupted));
  await go("1");
  const card = await find(By.css("[data-recap]"));
  assert.match(await card.getText(), /While you were away/);
  const interrupted = await find(By.css("[data-recap-interrupted]"));
  assert.match(await interrupted.getText(), /wait for me across the restart/);
  assert.match(await interrupted.getText(), /Nothing was resumed/);
  await shot("22-recap");

  // Open takes the owner to the conversation. It does not run anything.
  await (await interrupted.findElement(By.xpath(".//button[normalize-space()='Open']"))).click();
  await find(By.id("composer"));
  await driver.wait(async () => (await pageText()).includes("wait for me across the restart"), 10000, "the interrupted conversation is open");
  await driver.sleep(3000);
  assert.equal(await replyRunning(), false, "opening it did not resume the reply");
  const after = (await invoke("tasks_list", { limit: 50 })).find((t) => t.id === handoff.task);
  assert.equal(after.status, "interrupted", "still interrupted: only the owner can start it again");

  // Dismissed, the recap is gone, and it stays gone.
  await go("1");
  await (await find(By.css('button[aria-label="Dismiss the recap"]'))).click();
  await driver.wait(() => gone("[data-recap]"), 5000);
  assert.equal(await invoke("recap_get"), null);
  await go("2");
  await go("1");
  await driver.sleep(500);
  assert.equal(await gone("[data-recap]"), true, "not shown again after dismissing");
});
