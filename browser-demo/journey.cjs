// One customer journey in a real Chromium on the real test bank, filmed beside the demo's terminal.
// Demo only, not evidence. Uses the container's existing Playwright and Chromium; installs nothing.
//
//   node browser-demo/journey.cjs --url http://127.0.0.1:27830 --terminal-log <demo log> --out <folder>
//
// The journey follows the demo by reading its terminal log: it pays during the warm-up, is refused
// once the faults land, retries the same payment every 5 s until it is paid, retries once more to
// show the bank answers "replayed" with the same payment id, then pays twice more after the
// incident commander hands over, inside the window the checker scores.

const fs = require("fs");
const path = require("path");
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || "playwright");

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
}
const URL_BASE = arg("url", "http://127.0.0.1:27830");
const TERMINAL = arg("terminal-log");
const OUT = path.resolve(arg("out", "browser-demo-out"));
const RETRY_EVERY_MS = 5000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(path.join(OUT, "shots"), { recursive: true });
const journal = fs.createWriteStream(path.join(OUT, "journey.jsonl"));
let t0 = Date.now();
function note(event, extra = {}) {
  const rec = { t: Date.now() / 1000, video_s: (Date.now() - t0) / 1000, event, ...extra };
  journal.write(JSON.stringify(rec) + "\n");
  console.log(`${rec.video_s.toFixed(1).padStart(6)}s  ${event} ${JSON.stringify(extra)}`);
}

const terminalText = () => { try { return fs.readFileSync(TERMINAL, "utf8"); } catch (e) { return ""; } };
async function waitFor(pattern, timeoutMs = 240000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { if (pattern.test(terminalText())) return true; await sleep(150); }
  throw new Error(`timed out waiting for ${pattern} in the terminal log`);
}

(async () => {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined;
  const browser = await chromium.launch({ executablePath });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }, serviceWorkers: "block",
    recordVideo: { dir: path.join(OUT, "video-raw"), size: { width: 1920, height: 1080 } },
  });
  // Locked to the local demo server: anything else is refused, and so are WebSockets.
  await context.route("**/*", (route) =>
    route.request().url().startsWith(URL_BASE + "/") ? route.continue() : route.abort("blockedbyclient"));
  await context.addInitScript(() => { window.WebSocket = undefined; });
  await context.tracing.start({ screenshots: false, snapshots: true });   // the video already has the pixels
  const page = await context.newPage();
  t0 = Date.now();   // the video starts with the page
  const customer = page.frameLocator("#customer");
  let shot = 0;
  const snap = async (name) => {
    const file = path.join("shots", `${String(++shot).padStart(2, "0")}-${name}.png`);
    await page.screenshot({ path: path.join(OUT, file) });
    note("screenshot", { file });
  };
  const caption = async (step, text) => { await page.evaluate(([s, t]) => window.setCaption(s, t), [step, text]); note("caption", { step, text }); };
  const result = async () => ({
    outcome: (await customer.locator("[data-testid=last-result]").getAttribute("class")).replace("result", "").trim(),
    title: await customer.locator("[data-testid=result-title]").textContent(),
    detail: await customer.locator("[data-testid=result-detail]").textContent(),
    http: await customer.locator("[data-testid=result-http]").textContent(),
  });
  const click = async (testid, label) => {
    const before = (await customer.locator("[data-testid=last-result]").getAttribute("data-n")) || "0";
    note("click", { button: testid, label });
    await customer.locator(`[data-testid=${testid}]`).click();
    await page.waitForFunction((b) => document.querySelector("#customer").contentDocument
      .querySelector("[data-testid=last-result]").dataset.n !== b, before, { timeout: 15000 });
    const r = await result();
    note("result", r);
    return r;
  };
  const amount = async (sar) => customer.locator("[data-testid=amount]").fill(String(sar));

  try {
    await page.goto(URL_BASE + "/stage");
    await caption("", "Starting a fresh copy of the test bank, with its 20 simulated customers…");
    await waitFor(/starting a fresh/);
    // The bank is up when the balance answers through the gateway.
    for (;;) {
      const ok = await page.evaluate(async () => (await fetch("/api/balance")).ok).catch(() => false);
      if (ok) break;
      await sleep(300);
    }
    note("bank_up");
    await sleep(1200);
    await caption("1 ·", "Warm-up: everything is healthy. The customer pays SAR 400.");
    await amount(400);
    await click("pay", "warm-up payment");
    await snap("warmup-paid");
    await customer.locator("[data-testid=payment-status]", { hasText: "cleared" }).first()
      .waitFor({ timeout: 8000 }).then(() => note("cleared")).catch(() => note("not_cleared_yet"));

    await waitFor(/fault\(s\) injected/);
    note("faults_injected");
    await caption("2 ·", "The incident: a pipeline change cuts the transfer limit, and fraud screening slows down.");
    await sleep(1500);
    await amount(400);
    let r = await click("pay", "new payment during the incident");
    await snap("incident-refused");

    await caption("3 ·", "The customer retries the same payment every 5 s while the incident commander works.");
    for (let tries = 0; r.outcome !== "ok" && tries < 24; tries++) {
      await sleep(RETRY_EVERY_MS);
      r = await click("retry", "retry same payment");
      if (r.outcome !== "ok") await snap("retry-not-yet");
    }
    await caption("4 ·", "Paid. The payment posted once, under the same reference.");
    await snap("retry-paid");

    // One more retry shows the bank does not pay twice. Only before the handover, so the checker's
    // window (which starts 1 s after the handover) holds only fresh payments from this customer.
    await sleep(2500);
    if (!/^Outcome:/m.test(terminalText())) {
      await caption("4 ·", "Retrying once more: the bank answers “already paid” with the same payment id. Paid exactly once.");
      await click("retry", "retry after success (shows replayed)");
      await snap("replayed");
    } else {
      note("skipped_replay_retry", { reason: "the handover came first" });
    }

    await waitFor(/^Outcome:/m);
    note("handover");
    await caption("5 ·", "The incident commander hands over. The customer keeps banking normally.");
    await sleep(3000);
    await amount(250);
    await click("pay", "fresh payment after recovery");
    await sleep(7000);
    await amount(120);
    await click("pay", "second fresh payment after recovery");
    await snap("after-recovery");

    await caption("6 ·", "The independent checker scores every customer's own log, this browser customer included.");
    await waitFor(/^CHECKER:/m);
    const verdict = terminalText().match(/^CHECKER:.*$/m)[0];
    note("checker", { verdict });
    await caption("6 ·", verdict.startsWith("CHECKER: RECOVERED")
      ? "CHECKER: RECOVERED, with the browser customer counted. Paid exactly once."
      : verdict);
    await sleep(1500);
    await snap("checker");
    await sleep(4000);
  } catch (e) {
    note("error", { message: String(e && e.message || e) });
    process.exitCode = 1;
  } finally {
    await context.tracing.stop({ path: path.join(OUT, "trace.zip") });
    const video = page.video();
    await context.close();
    await browser.close();
    if (video) fs.renameSync(await video.path(), path.join(OUT, "browser-demo.webm"));
    note("done");
    journal.end();
  }
})();
