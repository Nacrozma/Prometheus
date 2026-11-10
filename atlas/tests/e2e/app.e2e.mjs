// End-to-end tests of the real desktop app (Rust core + SQLite + React UI) over WebDriver.
// Run via tests/e2e/run.sh, which builds the `e2e` binary (scripted provider, in-memory keys),
// isolates HOME and the data dir, and starts tauri-driver under a virtual display.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { Builder, By, Key, until } from "selenium-webdriver";

const AXE = fs.readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf8");

const APP = path.resolve(process.platform === "win32" ? "target/debug/atlas-desktop.exe" : "target/debug/atlas-desktop");
const SHOTS = process.env.ATLAS_SCREENSHOTS; // optional directory for real screenshots
let driver;
let WORKSPACE = "";
/** The workspace folder as the app itself reports it (Documents differs per OS and setup). */
async function loadWorkspace() {
  const settings = await driver.executeAsyncScript(
    "const done = arguments[arguments.length - 1]; window.__TAURI_INTERNALS__.invoke('settings_get').then(done, (e) => done(null));",
  );
  WORKSPACE = settings?.workspace_dir ?? "";
  assert.ok(WORKSPACE, "the app reports a workspace folder");
}
const workspaceDir = () => WORKSPACE;

const xpText = (tag, text) => By.xpath(`//${tag}[contains(normalize-space(.), ${JSON.stringify(text)})]`);
async function find(locator, ms = 15000) {
  return driver.wait(until.elementLocated(locator), ms);
}
async function click(text, tag = "button") {
  const el = await find(xpText(tag, text));
  await driver.wait(until.elementIsEnabled(el), 15000);
  try {
    await el.click();
  } catch (e) {
    // A transient toast can sit over the target; the element itself is enabled, so click it directly.
    if (e?.name !== "ElementClickInterceptedError") throw e;
    await driver.executeScript("arguments[0].click()", el);
  }
}
/** Wait until `text` is visible on the page (matches across text nodes, unlike an XPath text() test). */
async function waitText(text, ms = 15000) {
  try {
    await driver.wait(async () => (await driver.executeScript("return document.body.innerText")).includes(text), ms, `text "${text}"`);
  } catch (e) {
    const dir = process.env.ATLAS_FAILSHOTS ?? "test-results";
    fs.mkdirSync(dir, { recursive: true });
    const base = path.join(dir, `fail-${text.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}`);
    fs.writeFileSync(`${base}.png`, await driver.takeScreenshot(), "base64");
    fs.writeFileSync(`${base}.txt`, await driver.executeScript("return document.body.innerText"));
    throw e;
  }
}
async function shot(name) {
  if (!SHOTS) return;
  await driver.sleep(400);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.writeFileSync(path.join(SHOTS, `${name}.png`), await driver.takeScreenshot(), "base64");
}
const pageText = () => driver.executeScript("return document.body.innerText");
/**
 * True when nothing matches `selector`. Checked inside the page: asking WebDriver for elements that
 * are being removed at that moment can fail with a stale-element error (seen with the splash).
 */
const gone = (selector) => driver.executeScript(`return document.querySelector(${JSON.stringify(selector)}) === null`);
/** Navigate with the app's own keyboard shortcuts (Ctrl+1…9, Ctrl+,). */
async function go(key) {
  await driver.actions().keyDown(Key.CONTROL).sendKeys(key).keyUp(Key.CONTROL).perform();
  await driver.sleep(250);
}
/** Occurrences of `text` on the page, to wait for a new reply rather than matching an earlier one. */
async function countText(text) {
  return (await pageText()).split(text).length - 1;
}
async function waitForMore(text, before, ms = 20000) {
  await driver.wait(async () => (await countText(text)) > before, ms, `a new "${text}"`);
}
/** Atlas ignores Enter while it is responding (the composer shows Stop), so wait until it is idle. */
async function waitIdle(ms = 20000) {
  await driver.wait(
    () => driver.executeScript(`return ![...document.querySelectorAll("button")].some((b) => b.textContent.replace(/\\s+/g, " ").includes("Stop"))`),
    ms,
    "Atlas idle",
  );
}
async function send(text) {
  await waitIdle();
  // The composer can re-render between lookup and typing; retry on a stale reference.
  for (let attempt = 0; ; attempt++) {
    try {
      const box = await find(By.id("composer"));
      await driver.wait(until.elementIsEnabled(box), 15000);
      await box.sendKeys(text, Key.ENTER);
      return;
    } catch (e) {
      if (e?.name !== "StaleElementReferenceError" || attempt >= 4) throw e;
      await driver.sleep(200);
    }
  }
}

/** The core's own command, called from the page (read-only checks). */
const invoke = (cmd, args = {}) =>
  driver.executeAsyncScript(
    "const [c, a, done] = arguments; window.__TAURI_INTERNALS__.invoke(c, a).then(done, (e) => done({ __error: e }));",
    cmd,
    args,
  );
const exactButton = (text) => By.xpath(`//button[normalize-space()=${JSON.stringify(text)}]`);
const isVisible = (sel) => driver.executeScript(`return document.querySelector(${JSON.stringify(sel)})?.style.visibility === "visible"`);
const introGone = () => gone("[data-first-launch]");
/** Exact text content (WebDriver's getText is empty while text is still fading in). */
const textOf = (sel) => driver.executeScript(`return document.querySelector(${JSON.stringify(sel)})?.textContent ?? null`);

before(async () => {
  driver = await new Builder()
    .usingServer("http://127.0.0.1:4444/")
    // On Windows, `webviewOptions` puts msedgedriver into WebView2 mode; without it msedgedriver treats the
    // app as an Edge browser binary and waits for a DevToolsActivePort file that never appears.
    .withCapabilities({
      browserName: "wry",
      "tauri:options": process.platform === "win32" ? { application: APP, webviewOptions: {} } : { application: APP },
    })
    .build();
});

after(async () => {
  await driver?.quit();
});

test("the introduction plays once on first launch, with the dedication exactly as written", async () => {
  await find(By.css("[data-first-launch='first']"), 30000);
  await driver.wait(() => isVisible("[data-dedication]"), 15000, "dedication shown");
  assert.equal(await textOf("[data-dedication]"), "Created with love.");
  await shot("00-introduction-dedication");
  await driver.wait(() => isVisible("[data-welcome]"), 10000, "welcome shown");
  assert.equal(await textOf("[data-welcome]"), "Welcome. I'm Atlas. It's good to finally meet you.");
  assert.equal(await isVisible("[data-dedication]"), false, "one line at a time");
  // It ends by itself and the core records it.
  await driver.wait(introGone, 15000, "introduction ended");
  const s = await invoke("settings_get");
  assert.ok(s.first_launch.completed_at, "completion recorded by the core");
  // Reloading the window (as on the next launch) does not play it again.
  await driver.navigate().refresh();
  await waitText("Hello. I'm Atlas.", 30000);
  await driver.sleep(1500);
  assert.ok(await introGone(), "the introduction does not repeat");
});

test("first-run onboarding completes and personalises Atlas", async () => {
  await waitText("Hello. I'm Atlas.", 30000);
  // The startup splash fades out over the first screen; wait until it has been removed.
  await driver.wait(() => gone("[data-splash]"), 15000, "splash removed");
  await shot("01-welcome");
  await click("Get started");
  const name = await find(By.id("ob-name"));
  await name.sendKeys("Sam");
  await click("Continue");
  await waitText("Where your data lives");
  await shot("02-data");
  await click("Continue");
  await waitText("Connect an AI model");
  await waitText("E2E scripted provider");
  await click("Continue");
  await waitText("Choose a workspace folder");
  await click("Use Documents/Atlas Workspace");
  await waitText("Workspace:");
  await loadWorkspace();
  await click("Add a sample file (demo data)");
  await waitText("Demo file added");
  const sample = path.join(workspaceDir(), "Atlas Sample (demo data)", "household-budget-DEMO.csv");
  assert.ok(fs.existsSync(sample), "sample file must exist on disk");
  await click("Continue");
  await waitText("Meet the Atlas Map");
  await click("Continue");
  await waitText("Prometheus (optional sibling)");
  await click("Continue");
  await waitText("You're all set, Sam.");
  await shot("03-ready");
  await click("Start your first conversation");
  await waitText("Echo: Hi Atlas! I'm Sam.", 20000);
  await shot("04-first-conversation");
});

test("a read-only tool runs without approval and the result is verified", async () => {
  const before = await countText("Done. Tool result:");
  await send("calculate 6*7");
  await waitForMore("Done. Tool result:", before);
  // The reply streams word by word; wait for the full result rather than racing the stream.
  await driver.wait(async () => /"result":\s*42/.test(await pageText()), 10000, "calculator result 42 shown");
  await shot("05-tool-run");
});

test("a local write pauses for approval and runs exactly once when approved", async () => {
  const before = await countText("Done. Tool result:");
  await send("please create a note");
  await waitText("Approval needed", 20000);
  await shot("06-approval");
  await click("Approve");
  await waitForMore("Done. Tool result:", before);
  await waitIdle();
  const file = path.join(workspaceDir(), "e2e", "hello.md");
  assert.equal(fs.readFileSync(file, "utf8"), "# Hello from Atlas\n");
});

test("declining an approval performs nothing", async () => {
  const before = fs.readdirSync(path.join(workspaceDir(), "e2e"));
  await send("create a note again");
  await waitText("Approval needed", 20000);
  await click("Decline");
  await waitText("The action did not complete", 20000);
  await waitIdle();
  const after = fs.readdirSync(path.join(workspaceDir(), "e2e"));
  assert.deepEqual(after, before);
});

test("a running response can be stopped", async () => {
  await send("wait for me");
  const stop = await find(xpText("button", "Stop"));
  await driver.sleep(300);
  await stop.click();
  await waitText("Stopped by you.", 15000);
});

test("Esc stops a running reply, and a text reply can be regenerated in place", async () => {
  await send("wait for me");
  await find(xpText("button", "Stop"));
  await driver.sleep(300);
  const stopped = await countText("Stopped by you.");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await waitForMore("Stopped by you.", stopped, 15000);
  await waitIdle();

  await driver.actions().keyDown(Key.CONTROL).sendKeys("n").keyUp(Key.CONTROL).perform();
  await driver.sleep(300);
  await send("regenerate me");
  await waitText("Echo: regenerate me", 20000);
  await waitIdle();
  const conv = (await invoke("conversations_list", { projectId: null, includeArchived: false, limit: 1, offset: 0 }))[0];
  const before = (await invoke("conversation_messages", { id: conv.id })).filter((m) => m.role !== "notice");
  assert.deepEqual(before.map((m) => m.role), ["user", "assistant"]);
  // The action row appears on hover; click it directly.
  await driver.executeScript("arguments[0].click()", await find(exactButton("Regenerate")));
  await driver.wait(async () => {
    const now = (await invoke("conversation_messages", { id: conv.id })).filter((m) => m.role !== "notice");
    return now.length === 2 && now[1].role === "assistant" && now[1].id !== before[1].id;
  }, 20000, "reply replaced");
  const after = (await invoke("conversation_messages", { id: conv.id })).filter((m) => m.role !== "notice");
  assert.equal(after[0].id, before[0].id, "the question is kept, not duplicated");
  await waitIdle();
  assert.equal(await countText("Echo: regenerate me"), 1, "one reply on screen");
});

test("Mission Control shows the real execution history", async () => {
  await go("5");
  await waitText("Execution timeline");
  await driver.sleep(300);
  const body = await pageText();
  assert.match(body, /files\.create|calc\.evaluate/);
  assert.match(body, /Completed/);
  await shot("07-mission-control");
});

test("the Atlas Map renders nodes from live state", async () => {
  await go("3");
  await waitText("ATLAS CORE", 20000);
  await waitText("Calculator");
  await waitText("E2E scripted provider");
  await shot("08-atlas-map");
  await click("Calculator", "p");
  await waitText("Connections");
  await shot("09-map-inspector");
});

test("memory can be added, found and deleted", async () => {
  await go("7");
  await click("Add memory");
  const box = await find(By.id("mem-c"));
  await box.sendKeys("Prefers metric units for measurements");
  await click("Save");
  await waitText("Prefers metric units for measurements");
  await shot("10-memory");
  await driver.findElement(By.css('[aria-label="Delete memory"]')).click();
  await click("Delete", "button[ancestor::*[@role='dialog']]");
  await driver.wait(async () => !(await pageText()).includes("Prefers metric units"), 10000);
});

test("integrations show honest states and settings persist", async () => {
  await go("9");
  await waitText("Web search (Tavily)");
  await waitText("Planned — not available in this version");
  await shot("11-integrations");
  await go(",");
  await click("Permissions");
  await waitText("Always denied");
  await shot("12-settings-permissions");
  await click("Appearance");
  await click("Daylight");
  await driver.wait(async () => (await driver.executeScript("return document.documentElement.dataset.theme")) === "light", 5000);
  await click("Companion", "button");
  await shot("13-settings-light");
  await click("Appearance");
  await click("Deep Orbit");
});

test("personality presets apply their settings, and the introduction replays as a still scene under reduced motion", async () => {
  await go(",");
  await click("Companion", "button");
  await driver.findElement(By.xpath("//button[@role='radio'][.//span[normalize-space()='Concise']]")).click();
  await driver.wait(async () => (await invoke("settings_get")).companion.personality === "concise", 5000, "preset saved");
  const c = (await invoke("settings_get")).companion;
  assert.deepEqual([c.tone, c.verbosity, c.proactivity], ["precise", "concise", "reserved"]);
  await driver.findElement(By.xpath("//button[@role='radio'][.//span[normalize-space()='Professional']]")).click();
  await driver.wait(async () => (await invoke("settings_get")).companion.personality === "professional", 5000);

  await click("Appearance");
  await driver.findElement(exactButton("Reduced")).click();
  await driver.wait(async () => (await driver.executeScript("return document.documentElement.dataset.motion")) === "reduced", 5000);
  await driver.findElement(exactButton("About")).click();
  await click("Replay");
  const intro = await find(By.css("[data-first-launch='replay']"));
  assert.equal(await intro.getAttribute("data-reduced"), "true");
  await driver.wait(() => isVisible("[data-dedication]"), 5000, "dedication shown");
  assert.equal(await textOf("[data-dedication]"), "Created with love.");
  await shot("14-introduction-replay-reduced");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await driver.wait(introGone, 5000, "skipped with Esc");
  await click("Appearance");
  await driver.findElement(exactButton("System")).click();
});

/** Voice checks read what the app measured from real Web Audio (stand-in engines; see VoiceProvider). */
const voice = (expr) => driver.executeScript(`return window.__atlasVoice ? window.__atlasVoice.${expr} : null`);
const composerValue = () => driver.executeScript("return document.getElementById('composer')?.value ?? ''");
function wavFiles(dir) {
  const out = [];
  const walk = (d) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(wav|pcm|webm|ogg)$/i.test(e.name)) out.push(p);
    }
  };
  walk(dir);
  return out;
}

test("voice: verified downloads, push-to-talk into an editable message, a spoken reply through real playback, and Esc stops it", async () => {
  await go(",");
  await (await find(exactButton("Voice"))).click();
  await find(By.css("[data-voice-settings]"));
  await (await find(By.css('[data-voice-settings] [role=switch][aria-label="Voice"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).voice.enabled === true, 5000, "voice enabled");
  await waitText("Test build: stand-in engines, not real speech");

  // A download whose checksum does not match is refused and nothing is installed.
  await (await find(By.css('[data-artifact="voice-en_US-ryan-medium"] [data-action="download"]'))).click();
  await waitText("failed its integrity check", 20000);
  assert.equal(await (await find(By.css('[data-artifact="voice-en_US-ryan-medium"]'))).getAttribute("data-state"), "not_installed");

  // Speech output and recognition set up through the real download, checksum and unpack path.
  await click("Set up speech output");
  await find(By.css('[data-artifact="voice-en_GB-alba-medium"][data-state="installed"]'), 30000);
  assert.deepEqual(await invoke("voice_verify", { id: "voice-en_GB-alba-medium" }), []);
  await click("Set up speech recognition");
  await find(By.css('[data-artifact="stt-whisper-base"][data-state="installed"]'), 30000);
  await (await find(By.css('[role=switch][aria-label="Read replies aloud"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).voice.speak_responses === true, 5000);
  await shot("15-voice-settings");

  // Voice check (stand-in engines here, so this proves the flow and the capture path, not hardware).
  await click("Play test sentence");
  await find(By.css("[data-speaker-question]"), 20000);
  await click("Clearly");
  await find(By.css('[data-check-results] [data-result="speaker"]'));
  await driver.actions().sendKeys(Key.ESCAPE).perform(); // stop the test sentence
  await driver.executeScript("arguments[0].click()", await find(By.xpath("//*[@data-voice-check]//button[normalize-space(.)='Start']")));
  await find(By.xpath("//*[@data-voice-check]//button[normalize-space(.)='Stop']"));
  await driver.sleep(1000);
  await driver.executeScript("arguments[0].click()", await find(By.xpath("//*[@data-voice-check]//button[normalize-space(.)='Stop']")));
  await find(By.css('[data-check-results] [data-result="microphone"]'), 15000);
  await waitText("Heard: “What is 6 times 7?”");
  // The maintained capture API (an audio worklet) is what actually ran in this web view.
  assert.equal(await voice("backend()"), "worklet", "microphone capture uses the audio worklet");
  assert.equal(await voice("capturing()"), false);
  await shot("15b-voice-check");

  // Push-to-talk: the stand-in microphone is a test tone; the ring measures it.
  await driver.actions().keyDown(Key.CONTROL).sendKeys("n").keyUp(Key.CONTROL).perform();
  await driver.sleep(400);
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-mic]"))); // toasts can cover the composer
  await find(By.css('[data-mic][data-capture="listening"]'));
  await waitText("Microphone on");
  await find(By.css('[data-voice-bar] [data-voice-ring][data-state="listening"]'));
  // The analyser window is ~12 ms, so sample until the signal shows (speech has gaps between syllables).
  await driver.wait(async () => (await voice("level()")) > 0.01, 3000, "the ring reads real microphone-path audio");
  await driver.sleep(1000); // speak for a moment (recordings under 0.3 s are refused as too short)
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-mic]"))); // toasts can cover the composer
  await driver.wait(async () => (await composerValue()) === "What is 6 times 7?", 10000, "transcript in the composer for review");
  assert.equal(await voice("capturing()"), false, "the microphone is released");

  // The transcript is edited, then sent through the normal pipeline; the reply is spoken.
  const box = await find(By.id("composer"));
  await box.sendKeys(" Thanks.", Key.ENTER);
  await waitText("Echo: What is 6 times 7? Thanks.", 20000);
  await driver.wait(async () => (await voice("playback()")) === "speaking", 15000, "speaking");
  await find(By.css('[data-voice-bar] [data-voice-ring][data-state="speaking"]'));
  await driver.wait(async () => (await voice("level()")) > 0.01, 3000, "the ring reads the real playback signal");
  await find(By.css("[data-voice-caption]"));
  await shot("16-voice-speaking");

  // Esc interrupts at once; the reply text stays exactly as written and nothing is re-sent.
  const conv = (await invoke("conversations_list", { projectId: null, includeArchived: false, limit: 1, offset: 0 }))[0];
  const before = (await invoke("conversation_messages", { id: conv.id })).length;
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await driver.wait(async () => (await voice("playback()")) === "idle", 2000, "speech stopped promptly");
  await driver.sleep(300);
  assert.equal(await voice("level()"), 0, "silence after the stop");
  assert.equal(await countText("Echo: What is 6 times 7? Thanks."), 1, "the reply text is intact");
  assert.equal((await invoke("conversation_messages", { id: conv.id })).length, before, "no new request after the interruption");
});

test("voice: settings persist, offline speech still works but downloads are refused, microphone loss is handled, reduced motion stills the ring, and no audio is stored", async () => {
  await driver.navigate().refresh();
  await find(By.css("nav"), 30000);
  await driver.wait(() => gone("[data-splash]"), 15000, "splash removed after the reload");
  const s = await invoke("settings_get");
  assert.equal(s.voice.enabled, true);
  assert.equal(s.voice.speak_responses, true);
  const st = await invoke("voice_status");
  assert.ok(st.tts_ready && st.stt_ready);
  assert.equal(st.voices.find((v) => v.id === "voice-en_GB-alba-medium").state, "installed");

  // Offline mode: local speech keeps working; downloads are refused with a clear reason.
  await invoke("settings_update", { settings: { ...s, network: { ...s.network, offline_mode: true } } });
  await go("2");
  // After a reload no conversation is open; open the one from the previous test.
  await click("What is 6 times 7? Thanks.");
  await waitText("Echo: What is 6 times 7? Thanks.", 15000);
  await driver.executeScript("arguments[0].click()", await find(exactButton("Speak")));
  await driver.wait(async () => (await voice("playback()")) === "speaking", 15000, "speaks offline");
  await driver.executeScript("arguments[0].click()", await find(By.css('[aria-label="Stop speaking (Esc)"]')));
  await driver.wait(async () => (await voice("playback()")) === "idle", 2000);
  await go(",");
  await (await find(exactButton("Voice"))).click();
  await (await find(By.css('[data-artifact="stt-whisper-tiny"] [data-action="download"]'))).click();
  await waitText("offline mode is on", 10000);
  const s2 = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...s2, network: { ...s2.network, offline_mode: false } } });

  // The microphone disappears mid-recording: listening stops with a clear message; typing still works.
  await go("2");
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-mic]"))); // toasts can cover the composer
  await find(By.css('[data-mic][data-capture="listening"]'));
  await driver.executeScript("window.__atlasVoice.micLost('The microphone was disconnected.')");
  await waitText("The microphone was disconnected.");
  assert.equal(await voice("capturing()"), false);
  const echoes = await countText("Echo: typed after the microphone left");
  await send("typed after the microphone left");
  await waitForMore("Echo: typed after the microphone left", echoes);
  await driver.actions().sendKeys(Key.ESCAPE).perform(); // stop the spoken reply

  // Reduced motion: the ring is still (no animation frames while idle).
  await go(",");
  await click("Appearance");
  await (await find(exactButton("Reduced"))).click();
  await driver.executeScript("arguments[0].click()", await find(By.css('nav[aria-label="Main"] button[aria-label="Voice"]')));
  const ring = await find(By.css("[data-voice-ring]"));
  await driver.wait(async () => (await ring.getAttribute("data-reduced")) === "true", 5000);
  // A still frame is drawn on each state change; let pending changes settle, then expect none.
  let f1 = await ring.getAttribute("data-frames");
  await driver.wait(async () => {
    await driver.sleep(800);
    const f = await ring.getAttribute("data-frames");
    if (f === f1) return true;
    f1 = f;
    return false;
  }, 8000);
  await driver.sleep(1500);
  assert.equal(await ring.getAttribute("data-frames"), f1, "no animation loop under reduced motion");
  await shot("17-voice-page-reduced");
  await go(",");
  await click("Appearance");
  await (await find(exactButton("System"))).click();

  // Nothing recorded or synthesised was left on disk.
  assert.equal((await invoke("voice_status")).temp_audio_files, 0);
  if (process.env.ATLAS_DATA_DIR) assert.deepEqual(wavFiles(process.env.ATLAS_DATA_DIR), [], "no audio files in Atlas's data folder");
});

test("Atlas Forge: explorer, approved edit with revertible snapshot, terminal", async () => {
  await go("4");
  await waitText("e2e-sample");
  await click("main.py", "button");
  await waitText("return a - b");
  await click("Session", "button");
  await send("Please fix the bug in add");
  await waitText("Waiting for your approval", 20000);
  await waitText("+    return a + b");
  // The floating approval dock can overlap the card in the session pane; use the in-pane button.
  const approve = await find(By.xpath("//section[@aria-label='Forge workspace']//button[normalize-space()='Approve']"));
  await driver.executeScript("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", approve);
  await waitText("Done. Tool result", 20000);
  await click("Changes", "button");
  await waitText("edited");
  await shot("15-forge");
  await click("Terminal", "button");
  const cmd = await find(By.css('input[aria-label="Command"]'));
  await cmd.sendKeys("git --version", Key.ENTER);
  await waitText("git version", 20000);
  await shot("16-forge-terminal");
});

test("Siblings: honest unpaired state, nothing shown as connected", async () => {
  await (await find(By.css('nav[aria-label="Main"] button[aria-label="Siblings"]'))).click();
  await waitText("No sibling paired");
  const state = await driver.executeScript("return document.querySelector('[data-avatar-state]')?.dataset.avatarState");
  assert.equal(state, "offline");
  await click("Pair with Prometheus");
  await waitText("python sibling_adapter.py --pair");
  await shot("17-siblings-pair");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
});

test("home dashboard reflects state", async () => {
  await go("1");
  await waitText("Recent conversations");
  await shot("14-home");
});

/** Run axe-core inside the real webview; fail on serious or critical violations. */
async function audit(page) {
  await driver.executeScript(AXE);
  const result = await driver.executeAsyncScript(`
    const done = arguments[arguments.length - 1];
    axe.run(document, { resultTypes: ["violations"] }).then(r => done(JSON.stringify(r.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map(n => n.target.join(" "))
    }))))).catch(e => done(JSON.stringify([{ id: "axe-error", impact: "critical", help: String(e), nodes: [] }])));
  `);
  const violations = JSON.parse(result);
  const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (violations.length) console.log(`[a11y] ${page}:`, JSON.stringify(violations));
  return blocking;
}

test("accessibility audit (axe-core) finds no serious or critical issues", async () => {
  const failures = {};
  for (const [key, page] of [["1", "home"], ["2", "companion"], ["4", "forge"], ["siblings", "siblings"], ["5", "mission-control"], ["7", "memory"], ["9", "integrations"], [",", "settings"]]) {
    if (key === "siblings") await (await find(By.css('nav[aria-label="Main"] button[aria-label="Siblings"]'))).click();
    else await go(key);
    await driver.sleep(500);
    const blocking = await audit(page);
    if (blocking.length) failures[page] = blocking;
  }
  assert.deepEqual(failures, {});
});
