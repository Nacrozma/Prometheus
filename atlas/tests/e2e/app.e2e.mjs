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
    // The Focus bar's own Stop (and Home's "Stop focus") are not a reply in progress.
    () => driver.executeScript(`return ![...document.querySelectorAll("button")].some((b) => !b.closest("[data-focus-bar]") && !b.textContent.includes("Stop focus") && b.textContent.replace(/\\s+/g, " ").includes("Stop"))`),
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
  // Atlas's voice ring surrounds the globe. No voice is installed yet, so it rests: no sound, no movement from audio.
  assert.equal(await (await find(By.css("[data-intro-ring]"))).getAttribute("data-intro-ring"), "idle");
  assert.equal(Number(await (await find(By.css("[data-intro-ring] [data-voice-ring]"))).getAttribute("data-level")), 0, "the ring shows no audio when none is playing");
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
  await shot("13b-personality-presets");

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
  await driver.executeScript("document.querySelector('[data-voice-check]').scrollIntoView({ block: 'center' })");
  await driver.wait(async () => (await driver.executeScript("return document.querySelectorAll('[data-sonner-toast]').length")) === 0, 8000).catch(() => {});
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

  // The guided setup walks through speakers and microphone (everything is already downloaded here).
  await go(",");
  await (await find(exactButton("Voice"))).click();
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-open-wizard]")));
  await find(By.css('[data-audio-wizard][data-step="Welcome"]'));
  await click("Continue");
  await find(By.css('[data-audio-wizard][data-step="Speakers"]'));
  await click("Play a test sentence");
  await driver.wait(async () => (await voice("playback()")) === "speaking", 15000, "the test sentence plays");
  await click("Yes");
  await shot("17b-audio-wizard-speakers");
  await click("Continue");
  await find(By.css('[data-audio-wizard][data-step="Microphone"]'));
  assert.equal(await voice("playback()"), "speaking", "moving on does not cut the sentence off");
  await driver.actions().sendKeys(Key.ESCAPE).perform(); // Esc stops speech first, not the dialog
  await driver.wait(async () => (await voice("playback()")) === "idle", 3000);
  await find(By.css("[data-audio-wizard]"));
  await click("Test the microphone");
  await find(By.css('[data-mic-result="heard"]'), 10000);
  await shot("17b2-audio-wizard-microphone");
  assert.equal(await voice("capturing()"), false, "the microphone is released after the test");
  await click("Continue");
  await find(By.css('[data-audio-wizard][data-step="Done"]'));
  await waitText("Speaking: ready");
  await waitText("Listening: ready");
  await shot("17b3-audio-wizard-done");
  await click("Finish");
  await driver.wait(() => gone("[data-audio-wizard]"), 5000);

  // With a voice ready, Atlas speaks its welcome in the introduction and the ring shows that real sound.
  await (await find(exactButton("About"))).click();
  await click("Replay");
  await find(By.css("[data-first-launch='replay']"));
  assert.equal(await (await find(By.css("[data-intro-ring]"))).getAttribute("data-intro-ring"), "idle", "silent until Atlas actually speaks");
  await find(By.css('[data-intro-ring="speaking"]'), 30000);
  await driver.wait(async () => (await voice("level()")) > 0.01, 3000, "the introduction's ring reads the real playback signal");
  await shot("17c-introduction-speaking");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await driver.wait(introGone, 5000, "skipped with Esc");
  await driver.wait(async () => (await voice("playback()")) === "idle", 3000, "skipping the introduction stops its speech");

  // Nothing recorded or synthesised was left on disk.
  assert.equal((await invoke("voice_status")).temp_audio_files, 0);
  if (process.env.ATLAS_DATA_DIR) assert.deepEqual(wavFiles(process.env.ATLAS_DATA_DIR), [], "no audio files in Atlas's data folder");
});

test("tasks: plain-language entry, day views, overdue, steps and history, completion, a task added from a conversation, and deletion that asks first", async () => {
  const navTasks = async () => (await find(By.css('nav[aria-label="Main"] button[aria-label="Tasks"]'))).click();
  const row = (title) => By.css(`[data-task=${JSON.stringify(title)}]`);
  await navTasks();
  await find(By.css("[data-tasks-page]"));
  await waitText("Nothing due today");

  // A plain-language line is shown as it will be understood, then saved.
  const entry = await find(By.css('input[aria-label="New task"]'));
  await entry.sendKeys("Call the dentist tomorrow 9am !high #health");
  await find(By.css("[data-quick-preview]"));
  await waitText("Tomorrow 09:00");
  await shot("18-tasks-quick-entry");
  await entry.sendKeys(Key.ENTER);
  const dentist = await find(row("Call the dentist"));
  assert.equal(await dentist.getAttribute("data-overdue"), "false");
  await find(By.css('[data-task-group="Tomorrow"]'));
  const saved = (await invoke("todos_list", { filter: { view: "open" } })).find((t) => t.title === "Call the dentist");
  assert.equal(saved.due_time, "09:00");
  assert.equal(saved.priority, "high");
  assert.equal(saved.category, "health");
  assert.ok(saved.remind_at, "a timed task gets a reminder");

  // An undated task, a weekly one, and one that was due last week.
  await (await find(By.css('input[aria-label="New task"]'))).sendKeys("Buy milk", Key.ENTER);
  await find(row("Buy milk"));
  await (await find(By.css('input[aria-label="New task"]'))).sendKeys("Water the plants every week", Key.ENTER);
  const lastWeek = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  await invoke("todo_create", { task: { title: "Renew the car insurance", due_date: lastWeek, priority: "urgent" } });
  await (await find(exactButton("Today"))).click();
  const late = await find(row("Renew the car insurance"));
  assert.equal(await late.getAttribute("data-overdue"), "true");
  await find(By.css('[data-task-group="Overdue"]'));
  await waitText("1 overdue");
  await shot("18b-tasks-today");

  // Steps and history live inside the task.
  await driver.executeScript("arguments[0].click()", await find(By.css('[data-task="Renew the car insurance"] [data-open]')));
  await find(By.css("[data-task-dialog]"));
  // No time was given, so no time is shown (only a way to add one).
  await find(By.css("[data-add-time]"));
  assert.equal(await gone('input[aria-label="Due time"]'), true);
  await (await find(By.css('input[aria-label="New step"]'))).sendKeys("Compare three quotes", Key.ENTER);
  await find(By.css('[data-task-dialog] [data-task="Compare three quotes"]'));
  await (await find(By.css('input[aria-label="New step"]'))).sendKeys("Call the broker", Key.ENTER);
  await find(By.css('[data-task-dialog] [data-task="Call the broker"]'));
  await driver.executeScript("arguments[0].click()", await find(By.css('[data-task-dialog] button[aria-label="Complete Compare three quotes"]')));
  await driver.wait(async () => (await invoke("todos_list", { filter: { view: "open", search: "insurance" } }))[0]?.subtasks_done === 1, 5000);
  await shot("18c-task-details");
  await driver.executeScript("arguments[0].click()", await find(By.xpath("//div[@role='dialog']//button[normalize-space()='Done']")));
  await driver.wait(() => gone("[data-task-dialog]"), 5000);
  await waitText("1 of 2 steps");

  // Completing a repeating task brings its next occurrence; the finished one is kept under Done.
  await (await find(exactButton("All open"))).click();
  await driver.executeScript("arguments[0].click()", await find(By.css('button[aria-label="Complete Water the plants"]')));
  await driver.wait(async () => (await invoke("todos_list", { filter: { view: "done" } })).some((t) => t.title === "Water the plants"), 5000);
  const plants = (await invoke("todos_list", { filter: { view: "open", search: "plants" } }));
  assert.equal(plants.length, 1, "exactly one next occurrence");
  assert.equal(plants[0].recurrence, "weekly");
  assert.ok(plants[0].due_date > new Date().toISOString().slice(0, 10) || plants[0].due_date >= lastWeek);

  // Asking in a conversation adds a real task, without an approval prompt.
  await go("2");
  await driver.actions().keyDown(Key.CONTROL).sendKeys("n").keyUp(Key.CONTROL).perform();
  await driver.sleep(400);
  await send("Remind me to book the flights tomorrow at 8am");
  await waitText("Done. Tool result:", 20000);
  assert.equal((await invoke("approvals_pending")).length, 0, "adding a task does not ask");
  const flights = (await invoke("todos_list", { filter: { view: "open", search: "flights" } }))[0];
  assert.equal(flights.title, "book the flights");
  assert.equal(flights.source, "atlas");
  assert.equal(flights.due_time, "08:00");
  await navTasks();
  await (await find(exactButton("This week"))).click();
  await find(row("book the flights"));
  await waitText("added by Atlas");
  await shot("18d-task-from-conversation");

  // Deleting asks first; Cancel keeps the task.
  await driver.executeScript("arguments[0].click()", await find(By.css('button[aria-label="Delete book the flights"]')));
  await waitText("Delete this task?");
  await click("Cancel");
  await driver.sleep(300);
  assert.equal((await invoke("todos_list", { filter: { view: "open", search: "flights" } })).length, 1);
  await driver.executeScript("arguments[0].click()", await find(By.css('button[aria-label="Delete book the flights"]')));
  await waitText("Delete this task?");
  await driver.executeScript("arguments[0].click()", await find(By.xpath("//div[@role='dialog']//button[normalize-space()='Delete']")));
  await driver.wait(async () => (await invoke("todos_list", { filter: { view: "open", search: "flights" } })).length === 0, 5000);

  // The core refuses what the page would never send.
  assert.ok((await invoke("todo_create", { task: { title: "   " } })).__error);
  assert.ok((await invoke("todo_create", { task: { title: "x", due_date: "2026-02-31" } })).__error);
  assert.ok((await invoke("todo_set_status", { id: saved.id, status: "sideways" })).__error);
  assert.ok((await invoke("todo_postpone", { id: saved.id, days: 100000 })).__error);
});

test("scheduler: a reminder arrives on time with Done and Snooze, a missed one is reported once, and the global pause holds", async () => {
  const soon = (sec) => new Date(Date.now() + sec * 1000).toISOString();
  const jobs = async () => (await invoke("schedule_jobs", { limit: 100 })).jobs;
  const toastOf = (title) => By.xpath(`//li[@data-sonner-toast][.//*[contains(normalize-space(.), ${JSON.stringify(title)})]]`);
  await (await find(By.css('nav[aria-label="Main"] button[aria-label="Tasks"]'))).click();

  // A reminder a few seconds away: delivered at its time, shown in Atlas with Done and Snooze.
  const t = await invoke("todo_create", { task: { title: "Stretch and drink water", remind_at: soon(4) } });
  assert.ok(t.id, JSON.stringify(t));
  const toast = await find(toastOf("Stretch and drink water"), 30000);
  await shot("19-reminder-toast");
  const delivered = (await jobs()).find((j) => j.subject === t.id);
  assert.equal(delivered.status, "done");
  assert.equal(delivered.kind, "reminder");
  await driver.executeScript("arguments[0].click()", await toast.findElement(By.xpath(".//button[normalize-space()='Snooze 10 min']")));
  await driver.wait(async () => {
    const r = (await invoke("todo_detail", { id: t.id })).task.remind_at;
    return r && Date.parse(r) - Date.now() > 8 * 60 * 1000;
  }, 5000, "snoozed ten minutes");
  await driver.wait(async () => (await jobs()).some((j) => j.subject === t.id && j.status === "pending"), 10000, "the snoozed reminder is scheduled again");

  // A reminder set for three days ago was never "missed": no job, no notice, no noise.
  // (Reminders that fall due while Atlas is closed are grouped into one notice: covered by the core tests.)
  const old = await invoke("todo_create", { task: { title: "Return the library books", remind_at: new Date(Date.now() - 3 * 86400000).toISOString() } });
  await driver.sleep(5000);
  assert.equal((await jobs()).some((j) => j.subject === old.id), false, "nothing scheduled for a moment long past");
  const notices = (await invoke("notifications_list", { limit: 20 })).items;
  assert.equal(notices.some((n) => n.detail.startsWith("Return the library books") || n.title.includes("missed")), false);

  // The global pause holds a due reminder; resuming delivers it (it is within the grace period).
  await go(",");
  await (await find(exactButton("Reminders & schedule"))).click();
  await find(By.css("[data-schedule-settings]"));
  await (await find(By.css('[role=switch][aria-label="Pause proactive activity"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).schedule.paused === true, 5000);
  const held = await invoke("todo_create", { task: { title: "Held while paused", remind_at: soon(2) } });
  await driver.sleep(6000);
  assert.equal((await jobs()).find((j) => j.subject === held.id)?.status, "pending", "nothing runs while paused");
  await waitText("Paused");
  await shot("19b-schedule-settings-paused");
  await (await find(By.css('[role=switch][aria-label="Pause proactive activity"]'))).click();
  await driver.wait(async () => (await jobs()).find((j) => j.subject === held.id)?.status === "done", 15000, "delivered after resuming");
  await find(By.css('[data-job="reminder"][data-job-status="done"]'));
  await find(By.css('[data-job="reminder"][data-job-status="pending"]'));
  await shot("19c-schedule-history");
  const audit = await invoke("recent_errors", { limit: 50 });
  assert.ok(Array.isArray(audit));

  // The core refuses bad schedule settings.
  const s = await invoke("settings_get");
  assert.ok((await invoke("settings_update", { settings: { ...s, schedule: { ...s.schedule, deadline_hour: 30 } } })).__error);
  assert.ok((await invoke("todo_snooze", { id: t.id, minutes: 0 })).__error);

  // Tidy up so later tests start quiet.
  for (const x of [t, old, held]) await invoke("todo_delete", { id: x.id });
  await invoke("notifications_clear");
  await driver.wait(() => gone("[data-sonner-toast]"), 40000).catch(() => {});
});

test("Command Center: today's briefing and priorities come from real tasks, ticking one completes it, Home can be customized, and the daily briefing arrives on time", async () => {
  const ymd = (offset) => {
    const d = new Date(Date.now() + offset * 86400000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  // Start from an empty list (earlier tests leave tasks behind; this data folder is a throwaway).
  for (const t of await invoke("todos_list", { filter: { view: "open" } })) await invoke("todo_delete", { id: t.id });
  const made = [];
  for (const task of [
    { title: "Send the invoice to Marta", due_date: ymd(-2), priority: "high" },
    { title: "Water the plants", due_date: ymd(0) },
    { title: "Call the dentist", due_date: ymd(0), priority: "urgent" },
    { title: "Renew the passport", due_date: ymd(3) },
  ]) {
    const t = await invoke("todo_create", { task });
    assert.ok(t.id, JSON.stringify(t));
    made.push(t);
  }
  const finished = await invoke("todo_create", { task: { title: "Back up the laptop" } });
  await invoke("todo_set_status", { id: finished.id, status: "done" });
  made.push(finished);

  // The core's view, which the page shows as it is.
  const cc = await invoke("command_center");
  assert.equal(cc.briefing.overdue.length, 1);
  assert.equal(cc.briefing.today.length, 2);
  assert.ok(cc.briefing.upcoming.some((t) => t.title === "Renew the passport"));
  assert.ok(cc.briefing_text.startsWith("2 tasks are due today"), cc.briefing_text);
  assert.ok(cc.briefing_text.includes("No calendar is connected"), "says what it cannot see");

  await go("1");
  await find(By.css("[data-command-center]"));
  await waitText("2 tasks are due today");
  await find(By.css('[data-priorities] [data-cc-task="Send the invoice to Marta"]'));
  await find(By.css('[data-priorities] [data-cc-task="Call the dentist"]'));
  await find(By.css('[data-coming-up] [data-cc-task="Renew the passport"]'));
  await find(By.css("[data-accomplished]"));
  await waitText("Back up the laptop");
  await shot("20-command-center");

  // Ticking a priority completes the real task and the briefing updates.
  await driver.executeScript("arguments[0].click()", await find(By.css('button[aria-label="Complete Water the plants"]')));
  await driver.wait(async () => (await invoke("todo_detail", { id: made[1].id })).task.status === "done", 5000, "the task is done");
  await waitText("Due today: Call the dentist.");

  // Customize: hiding the briefing is saved in settings and removes it from Home.
  await click("Customize");
  await find(By.css("[data-customize-home]"));
  await shot("20b-customize-home");
  await (await find(By.css('[data-customize-home] [role=switch][aria-label="Today\'s briefing"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).home.show_briefing === false, 5000);
  await click("Done");
  await driver.wait(() => gone("[data-briefing]"), 5000);
  const s1 = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...s1, home: { ...s1.home, show_briefing: true } } });
  await find(By.css("[data-briefing]"));

  // The daily briefing: off by default; on, at a time a minute away, it is scheduled and delivered.
  assert.equal(s1.briefing.enabled, false, "off until the owner turns it on");
  await go(",");
  await (await find(exactButton("Reminders & schedule"))).click();
  await find(By.css("[data-briefing-settings]"));
  await (await find(By.css('[data-briefing-settings] [role=switch][aria-label="Daily briefing"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).briefing.enabled === true, 5000);
  await shot("20c-briefing-settings");
  const next = new Date(Date.now() + 65000);
  const hhmm = `${String(next.getHours()).padStart(2, "0")}:${String(next.getMinutes()).padStart(2, "0")}`;
  const s2 = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...s2, briefing: { ...s2.briefing, time: hhmm } } });
  const jobs = async () => (await invoke("schedule_jobs", { limit: 100 })).jobs;
  await driver.wait(async () => (await jobs()).some((j) => j.kind === "briefing" && j.status === "pending"), 40000, "the briefing is scheduled");
  await driver.wait(async () => (await jobs()).some((j) => j.kind === "briefing" && j.status === "done"), 150000, "the briefing is delivered at its time");
  const notes = (await invoke("notifications_list", { limit: 20 })).items;
  const brief = notes.find((n) => n.category === "briefing");
  assert.ok(brief, JSON.stringify(notes.map((n) => [n.category, n.title])));
  assert.ok(brief.detail.includes("Call the dentist"), brief.detail);

  // The core refuses a briefing time that is not a time.
  assert.ok((await invoke("settings_update", { settings: { ...s2, briefing: { ...s2.briefing, time: "25:99" } } })).__error);

  // Tidy up so later tests start quiet.
  const s3 = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...s3, briefing: { ...s3.briefing, enabled: false } } });
  for (const t of made) await invoke("todo_delete", { id: t.id });
  await invoke("notifications_clear");
  await driver.wait(() => gone("[data-sonner-toast]"), 40000).catch(() => {});
});

test("Focus Mode holds what can wait and lets approvals through, ends with a summary, and the recap shows what happened while away", async () => {
  const soon = (sec) => new Date(Date.now() + sec * 1000).toISOString();
  const toastOf = (title) => By.xpath(`//li[@data-sonner-toast][.//*[contains(normalize-space(.), ${JSON.stringify(title)})]]`);
  await invoke("notifications_clear");

  // Start from Tasks: a task's Focus button opens the dialog with that task chosen.
  const d0 = new Date();
  const today = `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, "0")}-${String(d0.getDate()).padStart(2, "0")}`;
  const essay = await invoke("todo_create", { task: { title: "Outline the essay", due_date: today } });
  await (await find(By.css('nav[aria-label="Main"] button[aria-label="Tasks"]'))).click();
  // The row's buttons appear on hover or keyboard focus; click it directly.
  await driver.executeScript("arguments[0].click()", await find(By.css('button[aria-label="Focus on Outline the essay"]')));
  await find(By.css("[data-focus-dialog]"));
  await driver.wait(async () => (await (await find(By.css('select[aria-label="Task to focus on"]'))).getAttribute("value")) === essay.id, 5000, "the task is preselected");
  for (const preset of ["15 min", "25 min", "50 min", "90 min"]) await find(exactButton(preset));
  await (await find(By.css('input[aria-label="Other length in minutes"]'))).sendKeys("40");
  await click("Start focusing");
  await find(By.css("[data-focus-bar]"));
  const onTask = (await invoke("focus_status")).active;
  assert.equal(onTask.todo_title, "Outline the essay");
  assert.equal(Math.round((Date.parse(onTask.planned_end) - Date.parse(onTask.started_at)) / 60000), 40, "custom length");
  // What the bar shows, and that it is really laid out (not squeezed to nothing).
  const what = await driver.executeScript(`const e = document.querySelector("[data-focus-what]"); const r = e?.getBoundingClientRect(); const b = document.querySelector("[data-focus-bar]").getBoundingClientRect(); return { text: e?.textContent, width: r?.width ?? 0, bar: b.width, win: window.innerWidth, html: document.querySelector("[data-focus-bar]").outerHTML.slice(0, 600) }`);
  assert.equal(what.text, "Outline the essay", JSON.stringify(what));
  assert.ok(what.width > 40, `title laid out: ${JSON.stringify(what)}`);
  await invoke("focus_stop");
  await driver.wait(() => gone("[data-focus-bar]"), 5000);
  await invoke("notifications_clear");

  // Start from Home: 15 minutes, with a label.
  await go("1");
  await click("Focus");
  await find(By.css("[data-focus-dialog]"));
  await (await find(exactButton("15 min"))).click();
  await (await find(By.css('input[aria-label="Focus label"]'))).sendKeys("Draft the essay");
  await shot("21-focus-start");
  await click("Start focusing");
  const bar = await find(By.css("[data-focus-bar]"));
  await driver.wait(async () => (await driver.executeScript(`return document.querySelector("[data-focus-what]")?.textContent`)) === "Draft the essay", 5000, "the label is shown");
  const st = await invoke("focus_status");
  assert.equal(st.active.label, "Draft the essay");
  assert.equal(Math.round((Date.parse(st.active.planned_end) - Date.parse(st.active.started_at)) / 60000), 15);

  // A second session and impossible lengths are refused by the core.
  assert.ok((await invoke("focus_start", { minutes: 25 })).__error, "only one session at a time");
  await invoke("focus_stop");
  assert.ok((await invoke("focus_start", { minutes: 2 })).__error);
  assert.ok((await invoke("focus_start", { minutes: 600 })).__error);
  await invoke("focus_start", { minutes: 15, label: "Draft the essay" });
  await find(By.css("[data-focus-bar]"));

  // A reminder falls due during the session: listed (held), but no toast.
  const t = await invoke("todo_create", { task: { title: "Stretch break", remind_at: soon(3) } });
  await driver.wait(async () => (await invoke("notifications_list", { limit: 20 })).items.some((n) => n.detail.includes("Stretch break")), 30000, "the reminder was raised");
  const held = (await invoke("notifications_list", { limit: 20 })).items.find((n) => n.detail.includes("Stretch break"));
  assert.equal(held.held, true, "held while focusing");
  assert.equal(held.shown_by_system, false);
  await driver.sleep(1500);
  assert.equal((await driver.findElements(toastOf("Stretch break"))).length, 0, "no toast while focusing");
  // An approval during the session still comes through: listed unheld (and shown, when allowed).
  await go("2");
  await send("create a note during focus");
  await waitText("Approval needed", 20000);
  await driver.wait(async () => (await invoke("notifications_list", { limit: 20 })).items.some((n) => n.category === "approval"), 10000, "approval raised");
  const appr = (await invoke("notifications_list", { limit: 20 })).items.find((n) => n.category === "approval");
  assert.equal(appr.held, false, "approvals are never held");
  await click("Decline");
  await waitText("The action did not complete", 20000);
  await go("1");
  await waitText("Stop focus");
  // The countdown is coherent with the session the core reports.
  const left = await (await find(By.css("[data-focus-left]"))).getText();
  const [mm, ss] = left.split(":").map(Number);
  const coreLeft = (Date.parse((await invoke("focus_status")).active.planned_end) - Date.now()) / 1000;
  assert.ok(Math.abs(mm * 60 + ss - coreLeft) < 5, `countdown ${left} vs ${Math.round(coreLeft)}s left`);
  await shot("21b-focus-running");

  // Stopping releases what waited and says so: exactly what was held, nothing else.
  const heldBefore = (await invoke("notifications_list", { limit: 50 })).items.filter((n) => n.held);
  assert.ok(heldBefore.some((n) => n.detail.includes("Stretch break")) && heldBefore.every((n) => n.category !== "approval"), JSON.stringify(heldBefore));
  await (await bar.findElement(By.xpath(".//button[normalize-space()='Stop']"))).click();
  await driver.wait(() => gone("[data-focus-bar]"), 5000);
  await driver.wait(async () => (await invoke("notifications_list", { limit: 20 })).items.some((n) => n.category === "focus"), 5000);
  const items = (await invoke("notifications_list", { limit: 20 })).items;
  const summary = items.find((n) => n.category === "focus");
  assert.match(summary.title, /^Focus session stopped: Draft the essay$/);
  assert.match(summary.detail, heldBefore.length === 1 ? /1 notification waited: Reminder: Stretch break\./ : new RegExp(`${heldBefore.length} notifications waited, latest: `), "the approval came through, so it did not wait");
  assert.ok(items.every((n) => !n.held), "nothing is held after the session");
  await find(toastOf("Focus session stopped"));
  await shot("21c-focus-summary");
  const hist = (await invoke("focus_status")).history;
  assert.equal(hist[0].outcome, "stopped");

  // The recap: as if Atlas had been away for two hours (test-build stand-in for a real absence).
  await invoke("e2e_recap_since", { minutes: 120 });
  await go("2");
  await go("1");
  const card = await find(By.css("[data-recap]"));
  assert.match(await card.getText(), /While you were away/);
  assert.match(await card.getText(), /Stretch break/);
  await (await find(By.css('button[aria-label="Dismiss the recap"]'))).click();
  await driver.wait(() => gone("[data-recap]"), 5000);
  assert.equal(await invoke("recap_get"), null);

  await invoke("todo_delete", { id: t.id });
  await invoke("todo_delete", { id: essay.id });
  await invoke("notifications_clear");
  await driver.wait(() => gone("[data-sonner-toast]"), 40000).catch(() => {});
});

test("desktop presence: nothing is on by default, the shortcut is validated and never duplicated, notifications need permission, and the bell lists them", async () => {
  const s0 = await invoke("settings_get");
  assert.equal(s0.desktop.shortcut_enabled, false);
  assert.equal(s0.desktop.notifications.system, false);
  assert.equal(s0.desktop.close_to_tray, false);
  const st0 = await invoke("desktop_status");
  assert.equal(st0.shortcut_registered, null, "no system-wide shortcut until the owner enables it");
  // The backend refuses a test notification while they are off, and refuses unsafe shortcuts.
  assert.match(String((await invoke("notification_test")).__error?.message ?? ""), /system notifications are off/);
  for (const bad of ["Ctrl+C", "Alt+F4", "Space", "Ctrl+Shift+Space"]) {
    const r = await invoke("settings_update", { settings: { ...s0, desktop: { ...s0.desktop, shortcut: bad, shortcut_enabled: true } } });
    assert.ok(r.__error, `${bad} must be refused`);
  }
  assert.equal((await invoke("desktop_status")).shortcut_registered, null, "a refused shortcut registers nothing");
  // The window has no direct access to the desktop plugins: only the core's validated settings can reach them.
  for (const [cmd, args] of [
    ["plugin:global-shortcut|register", { shortcuts: ["Ctrl+Alt+J"], handler: 0 }],
    ["plugin:notification|notify", { options: { title: "x", body: "y" } }],
    ["plugin:notification|request_permission", {}],
  ]) {
    assert.ok((await invoke(cmd, args)).__error, `${cmd} must be refused from the window`);
  }
  assert.equal((await invoke("desktop_status")).shortcut_registered, null);
  assert.equal((await invoke("desktop_status")).test_notifications_shown, 0, "no notification was shown behind the core's back");

  await go(",");
  await (await find(exactButton("Desktop"))).click();
  await find(By.css("[data-desktop-settings]"));
  assert.equal(await (await find(By.css("[data-shortcut-value]"))).getAttribute("data-shortcut-value"), "Ctrl+Alt+Space");

  // Turn the shortcut on: it is either registered, or Atlas says plainly why not. Never silently missing.
  await (await find(By.css('[role=switch][aria-label="Global shortcut"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).desktop.shortcut_enabled === true, 5000);
  const st1 = await invoke("desktop_status");
  assert.ok(st1.shortcut_registered === "Ctrl+Alt+Space" || st1.shortcut_error, JSON.stringify(st1));
  await find(By.css(st1.shortcut_registered ? "[data-shortcut-active]" : "[data-shortcut-error]"));
  await shot("17d0-desktop-settings");
  // Saving other settings does not register it again or change it.
  await (await find(By.css('[role=switch][aria-label="Start listening when summoned"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).desktop.shortcut_starts_listening === true, 5000);
  assert.equal((await invoke("desktop_status")).shortcut_registered, st1.shortcut_registered);
  // Change it with the keyboard: the next combination becomes the shortcut.
  await click("Change…");
  await driver.actions().keyDown(Key.CONTROL).keyDown(Key.ALT).sendKeys("k").keyUp(Key.ALT).keyUp(Key.CONTROL).perform();
  await driver.wait(async () => (await invoke("settings_get")).desktop.shortcut === "Ctrl+Alt+K", 5000, "captured shortcut saved");
  const st2 = await invoke("desktop_status");
  assert.ok(st2.shortcut_registered === "Ctrl+Alt+K" || st2.shortcut_error);
  // Turn it off: nothing stays registered.
  await (await find(By.css('[role=switch][aria-label="Global shortcut"]'))).click();
  await driver.wait(async () => (await invoke("desktop_status")).shortcut_registered === null, 5000);
  assert.equal((await invoke("desktop_status")).shortcut_error, null);

  // Tray: follows the setting where the system has one; hiding to it is refused when it is off.
  const tray = await invoke("desktop_status");
  if (tray.tray_supported) assert.equal(tray.tray_visible, true);
  await (await find(By.css('[role=switch][aria-label="Tray icon"]'))).click();
  await driver.wait(async () => (await invoke("desktop_status")).tray_visible === false, 5000);
  assert.ok((await invoke("window_hide")).__error, "Atlas cannot hide in a tray that is off");
  await (await find(By.css('[role=switch][aria-label="Tray icon"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).desktop.tray === true, 5000);

  // Notifications: with permission, the test is delivered once and listed under the bell.
  await (await find(By.css('[role=switch][aria-label="System notifications"]'))).click();
  await driver.wait(async () => (await invoke("settings_get")).desktop.notifications.system === true, 5000);
  const shownBefore = (await invoke("desktop_status")).test_notifications_shown;
  await click("Send a test notification");
  await driver.wait(async () => (await invoke("desktop_status")).test_notifications_shown === shownBefore + 1, 5000, "exactly one system notification");
  await driver.wait(async () => Number(await (await find(By.css("[data-bell]"))).getAttribute("data-unread")) >= 1, 5000);
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-bell]")));
  await find(By.css("[data-notification-panel]"));
  await waitText("Atlas notifications are working");
  await shot("17d-desktop-notifications");
  await click("Mark all read");
  await driver.wait(async () => (await invoke("notifications_list", { limit: 10 })).unread === 0, 5000);
  // Esc stops Atlas speaking before it closes anything else; wait until nothing is being read aloud.
  const speaking = await voice("playback()");
  if (speaking && speaking !== "idle") console.log(`# note: voice playback was "${speaking}" when the panel was closed`);
  await driver.wait(async () => ["idle", null].includes(await voice("playback()")), 20000, "speech finished");
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await driver.wait(() => gone("[data-notification-panel]"), 3000);

  // Leave the defaults as they were, and check they survived the round trip.
  const s1 = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...s1, desktop: s0.desktop } });
  await invoke("notifications_clear");
  assert.deepEqual((await invoke("settings_get")).desktop, s0.desktop);
  assert.equal((await invoke("desktop_status")).shortcut_registered, null);
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
  // Audit with an unread notification present, so the bell's badge is part of what is checked.
  const before = await invoke("settings_get");
  await invoke("settings_update", { settings: { ...before, desktop: { ...before.desktop, notifications: { ...before.desktop.notifications, system: true } } } });
  await invoke("notification_test");
  await driver.wait(async () => Number(await (await find(By.css("[data-bell]"))).getAttribute("data-unread")) >= 1, 5000);
  const failures = {};
  for (const [key, page] of [["1", "home"], ["2", "companion"], ["tasks", "tasks"], ["4", "forge"], ["siblings", "siblings"], ["5", "mission-control"], ["7", "memory"], ["9", "integrations"], [",", "settings"]]) {
    if (key === "siblings" || key === "tasks") await (await find(By.css(`nav[aria-label="Main"] button[aria-label="${key === "tasks" ? "Tasks" : "Siblings"}"]`))).click();
    else await go(key);
    await driver.sleep(500);
    const blocking = await audit(page);
    if (blocking.length) failures[page] = blocking;
  }
  // The open notification list is audited too.
  await driver.executeScript("arguments[0].click()", await find(By.css("[data-bell]")));
  await find(By.css("[data-notification-panel]"));
  const panel = await audit("notifications-panel");
  if (panel.length) failures["notifications-panel"] = panel;
  await driver.actions().sendKeys(Key.ESCAPE).perform();
  await invoke("settings_update", { settings: { ...(await invoke("settings_get")), desktop: before.desktop } });
  await invoke("notifications_clear");
  assert.deepEqual(failures, {});
});

// Must stay the last test: it leaves Atlas mid-work for the restart phase (tests/e2e/restart.e2e.mjs),
// which relaunches the same app on the same data folder.
test("before closing: a reply in progress and a Focus session on a task (checked after the restart)", async () => {
  const dir = process.env.ATLAS_DATA_DIR;
  assert.ok(dir, "run.sh sets the data folder");
  await invoke("focus_stop"); // independent of earlier tests
  const todo = await invoke("todo_create", { task: { title: "Prepare the slides" } });
  await invoke("notifications_clear");
  await invoke("notification_test").catch(() => {});
  await go("2");
  await driver.actions().keyDown(Key.CONTROL).sendKeys("n").keyUp(Key.CONTROL).perform();
  await driver.sleep(300);
  // A run waiting for approval to write a file: real tool-using work in progress when Atlas closes.
  const note = path.join(workspaceDir(), "e2e", "hello.md");
  const noteBefore = fs.statSync(note).mtimeMs;
  await send("create a note before closing");
  await waitText("Approval needed", 20000);
  const running = (await invoke("tasks_list", { limit: 10 })).find((t) => t.request.includes("before closing"));
  assert.ok(running && !["completed", "failed", "cancelled", "interrupted"].includes(running.status), JSON.stringify(running));
  const f = await invoke("focus_start", { minutes: 15, todoId: todo.id, label: "" });
  assert.ok(!f.__error, JSON.stringify(f));
  const kept = (await invoke("notifications_list", { limit: 50 })).items.map((n) => n.id);
  fs.writeFileSync(path.join(dir, "..", "e2e-handoff.json"), JSON.stringify({ todo: todo.id, task: running.id, conversation: running.conversation_id, focus: f.id, kept, note, noteBefore }));
  // Atlas is closed right after this test; on the next start it behaves as if two hours passed.
  fs.writeFileSync(path.join(dir, "e2e-away-minutes"), "120");
});
