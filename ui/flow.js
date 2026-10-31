/* TESTIGO+ interface: the landing, the guided demo, the results page and the
 * router. Loaded after app.js (state, helpers, approval, mandate, presenter).
 *
 * Routes (URL hash):
 *   #/                landing (#/how, #/attacks scroll to a section)
 *   #/results         WitnessBench, simply
 *   #/demo/rules      1 Your rules
 *   #/demo/run        2 Run the agent
 *   #/demo/watch      3 Watching
 *   #/demo/result     4 Result
 *   #/present[/0-8]   the presenter views for recording (not linked anywhere)
 */
"use strict";

const STEPS = [
  { key: "rules", name: "Your rules" },
  { key: "run", name: "Run the agent" },
  { key: "watch", name: "Watching" },
  { key: "result", name: "Result" },
];
const SITUATIONS = [
  { key: "clean", name: "Normal order", text: "An honest supplier page. The order should reach your shop." },
  { key: "a1", name: "Hidden order in the page code", text: "Invisible text tells the agent to deliver somewhere else." },
  { key: "a2", name: "Order painted in an image", text: "A banner image carries a faint instruction to change the address." },
  { key: "a3", name: "Address changed at the last second", text: "The review screen swaps in another address just before Confirm." },
];
function situation(key) { return SITUATIONS.find(x => x.key === key) || { key, name: key || "—", text: "" }; }

// -- routes -----------------------------------------------------------------
function parseRoute() {
  const parts = (location.hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "present") {
    const n = parseInt(parts[1] || "0", 10);
    return { name: "present", view: Number.isInteger(n) && n >= 0 && n < VIEWS.length ? n : 0 };
  }
  if (/^[0-8]$/.test(parts[0] || "")) return { name: "present", view: Number(parts[0]) };   // old #/N links
  if (parts[0] === "demo") {
    return { name: "demo", step: STEPS.some(x => x.key === parts[1]) ? parts[1] : "rules" };
  }
  if (parts[0] === "results") return { name: "results" };
  if (["how", "attacks", "start", "bench"].includes(parts[0])) return { name: "landing", section: parts[0] };
  return { name: "landing" };
}
function sameRoute(a, b) {
  return !!a && !!b && a.name === b.name && a.step === b.step && a.view === b.view && a.section === b.section;
}
function nav(hash) {
  if (location.hash === hash) onRoute(true);
  else location.hash = hash;
}
function onRoute(force) {
  const prev = S.route;
  S.route = parseRoute();
  if (S.route.name === "present") S.view = S.route.view;
  draw();
  loadForRoute();
  if (force || !sameRoute(prev, S.route)) arrive(prev);
}
// after a route change: a section scrolls into view; a new page starts at the
// top with focus on its heading, so screen readers hear where they are
function arrive(prev) {
  if (S.route.name === "landing" && S.route.section) {
    const el = document.getElementById("sec-" + S.route.section);
    if (el) { el.scrollIntoView({ block: "start" }); el.focus({ preventScroll: true }); }
    return;
  }
  if (!prev) return;                    // the first load keeps the browser's focus
  window.scrollTo(0, 0);
  const h = document.querySelector("#main h1, #view h1");
  if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
}
// presenter navigation (arrow keys, 0-8, follow)
function go(i) {
  i = Math.max(0, Math.min(VIEWS.length - 1, i));
  const h = "#/present/" + i;
  if (location.hash !== h) history.replaceState(null, "", h);
  S.route = { name: "present", view: i }; S.view = i;
  draw(); loadFor(i);
}
function follow(i) { if (S.auto && S.route.name === "present") S.pendingView = i; }

async function loadForRoute() {
  const r = S.route;
  try {
    if (r.name === "present") return loadFor(S.view);
    if (r.name === "landing" && !S.benchComplete) { S.benchComplete = await getJSON("/api/bench?complete=1"); draw(); }
    if (r.name === "results" && !S.bench) { S.bench = await getJSON("/api/bench"); draw(); }
    if (r.name === "landing" || r.name === "results") return;
    if (r.name === "demo") {
      if (!S.policy || r.step === "rules") await loadPolicy();
      if (r.step === "result") {
        const run = curRun();
        if (run && run.mode === "supervised") loadReceipt(true);
      }
      if (r.step === "watch") loadDesk();
    }
  } catch (err) { console.error(err); }
}
async function loadPolicy() {
  try { S.policy = await getJSON("/api/policy"); S.policyError = ""; }
  catch (err) { S.policyError = err.message; }
  draw();
}

// -- the run of the guided demo -----------------------------------------------
// The run on screen: the newest one that started (supervised or not), unless the
// page just asked for a new run that has not reported yet.
function curRun() {
  if (S.waitingFor) return null;
  const r = S.runs[S.current];
  return r && r.mode ? r : null;
}
function procFor(r) { return S.proc && r && S.proc.mode === r.mode && S.proc.state !== "idle" && S.proc.state !== "orphaned" ? S.proc : null; }
function procRunning() { return !!S.proc && (S.proc.state === "running" || S.proc.state === "orphaned"); }
function procEnded() { return !!S.proc && ["finished", "failed", "cancelled"].includes(S.proc.state); }
function lastStep(r, f) { for (let i = r.log.length - 1; i >= 0; i--) if (r.log[i].type === "agent.step" && f(r.log[i].label || "")) return r.log[i]; return null; }

// The one outcome of a run, in plain words. kind: running | blocked | paused |
// denied | shop | attacker | flagged | stopped | ended | error
function outcome(r) {
  if (!r || !r.mode) return null;
  const sup = r.mode === "supervised";
  const allowed = allowedAddresses();
  const order = r.order;
  const toShop = order && allowed.length ? allowed.includes(normRead("address", order.address)) : null;
  const where = order ? `${cop(order.amount_cop)} · ${order.address}` : "";
  const c = r.check;
  if (sup && c && c.status !== "ok") {
    if (c.status === "cannot_verify") return { kind: "paused", cls: "warn", icon: ICON.ask,
      title: "Paused: the screen could not be read clearly",
      text: "TESTIGO+ could not read the total or the address with confidence, so it did not let the agent confirm. Nothing was ordered." };
    if (c.status === "policy_violation") return { kind: "blocked", cls: "bad", icon: ICON.stop,
      title: "Blocked: the order breaks your rules",
      text: "The screen showed an order your rules do not allow. TESTIGO+ stopped it before Confirm. Nothing was ordered." };
    const painted = (c.pixels_only_text || []).length > 0;
    return { kind: "blocked", cls: "bad", icon: ICON.stop,
      title: painted ? "Blocked: an instruction was painted into the page" : "Blocked: the page hid an instruction for the agent",
      text: painted
        ? "The screen showed text that is not in the page code, an order aimed at the agent. TESTIGO+ stopped before Confirm. Nothing was ordered."
        : "The page code carried text you could not see on screen, an order aimed at the agent. TESTIGO+ stopped before Confirm. Nothing was ordered." };
  }
  const vo = verifyOutcome(r);
  if (sup && vo.kind === "blocked") return { kind: "blocked", cls: "bad", icon: ICON.stop,
    title: "Blocked: the address changed after you approved",
    text: `On the review screen the ${diffFields(vo.event).join(" and ") || "order"} no longer matched what you approved, so the order was never confirmed.` };
  if (sup && vo.kind === "cannot" && vo.moment === "review") return { kind: "paused", cls: "warn", icon: ICON.ask,
    title: "Paused: the review screen could not be read clearly",
    text: "Without a clear match to what you approved, TESTIGO+ did not click Confirm. Nothing was ordered." };
  if (r.granted && !isGranted(r.granted)) return { kind: "denied", cls: "off", icon: ICON.stop,
    title: "Not approved: nothing was ordered",
    text: "The order was not approved, so the agent did not confirm it." };
  if (order) {
    if (toShop === false) return { kind: "attacker", cls: "bad", icon: ICON.stop,
      title: sup && vo.kind === "flagged" ? "Delivered to the attacker, and flagged" : "Delivered to the attacker",
      text: sup ? `The order was confirmed for ${where}, which is not your shop.${vo.kind === "flagged" ? " TESTIGO+ saw after the click that it differs from what you approved; the receipt says so." : ""}`
                : `With nothing checking the screen, the agent confirmed the order for ${where}. The goods go to the attacker.` };
    if (sup && vo.kind === "flagged") return { kind: "flagged", cls: "bad", icon: ICON.stop,
      title: "Delivered, but flagged",
      text: "After the click, what was ordered is not what you approved. The signed receipt says so." };
    if (sup && vo.kind === "cannot") return { kind: "flagged", cls: "warn", icon: ICON.ask,
      title: "Delivered, but not verified",
      text: "The result screen could not be read clearly after the click. The receipt is marked for a person to check." };
    return { kind: "shop", cls: "ok", icon: ICON.check, title: "Delivered to your shop",
      text: sup ? `${where}. Checked before and after the click${r.receipt ? ", and signed" : ""}.`
                : `${where}. Nothing checked the screen, but this time the order went to the shop.` };
  }
  if (lastStep(r, l => l === "proposed: done")) return { kind: "stopped", cls: "off", icon: ICON.user,
    title: "The agent stopped on its own",
    text: sup ? "The agent ended without confirming an order. Nothing was ordered."
              : "The agent ended without confirming an order: it did not fall for the page this time. Nothing was ordered." };
  if (lastStep(r, l => /^stopped: max_steps/.test(l))) return { kind: "stopped", cls: "off", icon: ICON.dot,
    title: "The agent ran out of steps", text: "It never confirmed an order. Nothing was ordered." };
  const p = procFor(r);
  if (p && p.state !== "running") return p.state === "finished"
    ? { kind: "ended", cls: "off", icon: ICON.dot, title: "The run ended", text: "It ended without confirming an order." }
    : { kind: "error", cls: "warn", icon: ICON.warn,
        title: p.state === "cancelled" ? "You stopped the run" : "The run stopped with an error",
        text: p.state === "cancelled" ? "Nothing more will happen in this run." : "The agent did not finish. The last lines it printed are in the details." };
  return { kind: "running", cls: "info", icon: ICON.eye, title: "The agent is working", text: "" };
}
function needsYou(r) {
  if (!r || r.mode !== "supervised" || !r.approval || r.granted) return false;
  const p = procFor(r);
  return !(p && p.state !== "running");      // a stopped run waits for nobody
}

// one line of the Watching timeline, in plain words; null to leave it out
function plainLine(e, r) {
  const sup = r.mode === "supervised";
  switch (e.type) {
    case "run.started": return [ICON.dot, "info", sup ? "The agent started restocking the shop. TESTIGO+ is watching." : "The agent started restocking the shop, with TESTIGO+ switched off."];
    case "agent.step": {
      const l = e.label || "";
      if (l === "proposed: done") return [ICON.user, "info", "The agent says it is finished."];
      if (/^stopped: max_steps/.test(l)) return [ICON.dot, "warn", "The agent ran out of steps."];
      if (/^sensitive/.test(l)) return [ICON.eye, "info", "This click would confirm the order. Checking the screen first."];
      if (/without a check or approval/.test(l)) return [ICON.warn, "bad", "The order was confirmed with nobody checking it."];
      if (/^receipt not/.test(l)) return [ICON.warn, "warn", "The receipt could not be signed on this machine."];
      if (/^proposed: /.test(l) && e.detail) return [ICON.dot, "info", "Agent: “" + clip(e.detail, 160) + "”"];
      return null;
    }
    case "check.result":
      if (e.status === "ok") return [ICON.check, "ok", "Checked the screen: the total and the address follow your rules."];
      if (e.status === "cannot_verify") return [ICON.ask, "warn", "Could not read the screen clearly, so the agent was not allowed to confirm."];
      if (e.status === "policy_violation") return [ICON.stop, "bad", "Stopped: the screen shows an order your rules do not allow."];
      return [ICON.stop, "bad", (e.pixels_only_text || []).length
        ? "Stopped: the screen shows an instruction that is not in the page code."
        : "Stopped: the page code hides an instruction you cannot see."];
    case "approval.requested": return [ICON.pause, "warn", `Asked you to approve ${cop(e.amount_cop)} to ${e.address}.`];
    case "approval.granted": return isGranted(e) ? [ICON.check, "ok", "You approved by reading it aloud."] : [ICON.stop, "bad", "The order was not approved."];
    case "order.confirmed": return [ICON.box, "info", `The supplier confirmed the order: ${cop(e.amount_cop)}, deliver to ${e.address}.`];
    case "verify.result": {
      const review = e.moment === "review";
      if (e.status === "match") return [ICON.check, "ok", review
        ? "Checked the review screen: the address matches what you approved."
        : "Checked after the click: the order is what you approved."];
      if (e.status === "cannot_verify") return [ICON.ask, "warn", review
        ? "Could not read the review screen clearly, so it did not click Confirm."
        : "Could not read the result clearly. Flagged for a person."];
      return [ICON.stop, "bad", review
        ? "Stopped: the address on the review screen changed after you approved."
        : "After the click, the order differs from what you approved. Flagged."];
    }
    case "explain.result": return [ICON.eye, "info", e.status === "none"
      ? "After the run, TESTIGO+ looked at the screen the agent confirmed: nothing suspicious."
      : "After the run, TESTIGO+ looked at the screen the agent confirmed and found the attack (see the result)."];
    case "receipt.signed": return isPlaceholder(e.signature)
      ? [ICON.warn, "warn", "A receipt was built but could not be signed."]
      : [ICON.seal, "ok", "Signed a receipt you can verify."];
  }
  return null;
}
function clip(t, n) { t = String(t || ""); return t.length > n ? t.slice(0, n - 1) + "…" : t; }

async function startRun(req) {
  if (S.runReq.busy) return;
  S.runReq = { busy: true, error: "", busyRun: false }; draw();
  try {
    S.proc = await getJSON("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
    S.waitingFor = S.proc.mode;
    S.runReq = { busy: false, error: "", busyRun: false };
    nav("#/demo/watch");
  } catch (err) {
    S.runReq = { busy: false, error: err.message, busyRun: err.status === 409 };
    if (err.status === 409) refreshProc();
    draw();
  }
}
function startPicked() {
  const p = S.pick;
  const req = { scenario: p.scenario, variant: p.variant, supervised: p.supervised };
  if (p.headed) req.headed = true;
  startRun(req);
}
async function cancelRun() {
  try {
    S.proc = await getJSON("/api/run/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (err) { S.runReq = Object.assign({}, S.runReq, { error: err.message }); }
  draw();
}
// After a reload: a run started here that has not reported run.started yet is
// still "starting" (same clock on both sides, so the ISO times compare).
function syncWaiting() {
  const p = S.proc;
  if (!p || p.state !== "running" || !p.started) return;
  const first = (S.runs[p.mode] || {}).log || [];
  const started = first.length && first[0].type === "run.started" ? first[0].ts : "";
  if (!started || started < p.started) S.waitingFor = p.mode;
}
async function refreshProc() {
  try { S.proc = await getJSON("/api/run"); } catch (err) { console.error(err); }
}
// while a run started here is alive, ask how it is doing
setInterval(async () => {
  if (!S.proc || S.proc.state !== "running") return;
  await refreshProc();
  if (S.proc.state !== "running") draw();
}, 1500);

// -- small pieces -----------------------------------------------------------------
const LOGO = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.3 8 11 4.6-1.7 8-6 8-11V5z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>`;
function more(id, summary, body) {
  return `<details class="more" id="${id}"${S.open[id] ? " open" : ""}><summary id="${id}-s">${summary}</summary><div class="more-body">${body}</div></details>`;
}
function askBefore(v) {
  return v === "new_address" ? "Ask you before delivering to a new address" : "Ask you before: " + String(v || "").replace(/_/g, " ");
}
function shortDate(iso) {
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(iso || "");
  if (!m) return "";
  return `${Number(m[3])} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1]}`;
}
const secs = ms => Number.isFinite(ms) ? Math.round(ms / 1000) + " s" : "—";

// The headline numbers of WitnessBench, from the file only.
function benchFacts(b) {
  const s = b && b.available && b.data && b.data.summary;
  const counted = x => x && Number.isFinite(x.succeeded) && Number.isFinite(x.runs);
  if (!s || !counted(s.attacks_succeed_without) || !counted(s.attacks_succeed_with)) return null;
  const rows = Array.isArray(b.data.rows) ? b.data.rows : [];
  const hp = rows.filter(x => x.mode === "supervised" && (x.scenario === "a1" || x.scenario === "a2"));
  const fp = s.false_positives || {};
  return {
    wo: s.attacks_succeed_without, wi: s.attacks_succeed_with,
    stopped: hp.filter(x => x.blocked).length, hidden: hp.length,
    fp, fpUnread: Array.isArray(fp.statuses) && fp.statuses.length > 0 && fp.statuses.every(x => x === "cannot_verify"),
    perCheck: (s.per_check_latency_ms || {}).median, perRun: (s.added_latency_ms || {}).median,
    date: shortDate(b.data.generated), source: b.source || "", rows, summary: s,
    incomplete: b.data.complete === false, missing: Array.isArray(b.data.missing) ? b.data.missing.length : null,
  };
}
function benchCards(f, cls, loaded) {
  if (!f) {
    const msg = !loaded ? "Loading the results…" : "No WitnessBench results yet. They are read from the benchmark file, never typed in.";
    return `<p class="${cls}-note">${esc(msg)}</p>`;
  }
  const card = (big, text) => `<div class="${cls}-card"><span class="big">${big}</span><span>${text}</span></div>`;
  const cards = [];
  if (f.hidden) cards.push(card(`${esc(f.stopped)} of ${esc(f.hidden)}`, "pages with a hidden or painted order stopped before Confirm"));
  if (f.wo.succeeded === 0 && f.wi.succeeded === 0) {
    cards.push(card(`0 of ${esc(f.wo.runs)}`, "orders reached the attacker, with or without TESTIGO+: Muse Wonder resisted every attack on its own"));
  } else {
    cards.push(card(`${esc(f.wi.succeeded)} of ${esc(f.wi.runs)}`,
      `orders reached the attacker with TESTIGO+, against ${esc(f.wo.succeeded)} of ${esc(f.wo.runs)} without it`));
  }
  if (Number.isFinite(f.fp.count) && Number.isFinite(f.fp.clean_runs)) {
    cards.push(card(`${esc(f.fp.count)} of ${esc(f.fp.clean_runs)}`,
      `clean orders ${f.fpUnread ? "paused for a human because the pixels could not be read" : "stopped although nothing was wrong"}` +
      (Number.isFinite(f.perCheck) ? ` · ${esc(secs(f.perCheck))} median per check` : "")));
  }
  return `<div class="${cls}-cards">${cards.join("")}</div>`;
}

// -- shell ------------------------------------------------------------------------
function siteHeader() {
  const r = S.route;
  const cur = k => (k === "results" && r.name === "results") || (k === "demo" && r.name === "demo") ? ' aria-current="page"' : "";
  return `<header class="site-head"><nav class="site-nav" aria-label="Main">
      <a class="site-brand" id="nav-home" href="#/">${LOGO}<span>TESTIGO<span class="plus">+</span></span></a>
      <div class="site-links">
        <a id="nav-how" href="#/how">How it works</a>
        <a id="nav-attacks" href="#/attacks">Attacks</a>
        <a id="nav-results" href="#/results"${cur("results")}>Results</a>
      </div>
      ${r.name === "demo" ? "" : `<a class="btn-primary" id="nav-try" href="#/demo/rules">Try the demo</a>`}
    </nav></header>`;
}
function testBanner() {
  return `<div class="testdata" id="testdata" ${S.test ? "" : "hidden"}>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 21h20L12 3Zm0 6v5m0 3v.5" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>
    <span><b>Test data.</b> These events come from the offline fixtures, not a real run. Do not record them for the video.</span></div>`;
}
function siteFooter() {
  return `<footer class="site-foot"><div class="wrap-w">
      <span>TESTIGO+ · simulation only: simulated shop, supplier and addresses, no real brands.</span>
      <span>Open source · receipts verify with <span class="mono">testigo verify</span></span>
    </div></footer>`;
}

// -- landing ------------------------------------------------------------------------
const page = {
  landing() {
    return `
<section class="hero wrap-w" aria-labelledby="hero-h">
  <div class="hero-copy">
    <p class="eyebrow">A witness for computer-use agents</p>
    <h1 id="hero-h">Your agent can be tricked. The screen can’t lie.</h1>
    <p class="hero-lede">A web page can hide an order for your AI agent: “deliver this somewhere else.” TESTIGO+ sits between the agent and the browser, reads the screen in pixels like a person would, and stops the order unless it matches the rules you said out loud.</p>
    <div class="cta-row">
      <a class="btn-primary lg" id="hero-try" href="#/demo/rules">Try the demo</a>
      <a class="btn-secondary lg" id="hero-how" href="#/how">See how it works</a>
    </div>
    <p class="fine-print">Runs on Meta’s Muse Wonder, SAM 3.1, Muse Spark and Muse Voice. Simulated shop and supplier.</p>
  </div>
  <figure class="mock" aria-label="Example: a review screen where the delivery address was swapped, blocked by TESTIGO+">
    <div class="mock-bar" aria-hidden="true"><i></i><i></i><i></i><span>Distribuidora X · Review order</span></div>
    <div class="mock-body">
      <div class="mock-row"><span class="muted">Order DX-2041 · 3 items</span><b>COP 120,000</b></div>
      <div class="mock-field bad"><span class="lbl">Deliver to · on screen</span><span class="val">Bodega Norte · Carrera 80 # 7-15</span></div>
      <div class="mock-field"><span class="lbl ok-t">Your signed rule</span><span class="val">Tienda Doña Marta · Calle 45 # 12-30</span></div>
      <div class="mock-stop">${ICON.stop}<div><b>Blocked before the click</b><span>The address on screen is not the one you signed.</span></div></div>
    </div>
  </figure>
</section>

<section class="band" id="sec-attacks" tabindex="-1" aria-labelledby="att-h">
  <div class="wrap-w stack-l">
    <div class="sec-head">
      <h2 id="att-h">Three ways a page fools an agent</h2>
      <p>Agents trust two things an attacker controls: what the agent says it will do, and the page’s code. TESTIGO+ trusts neither.</p>
    </div>
    <div class="cards3">
      <div class="card"><span class="tag">A1</span><h3>Hidden in the page code</h3><p>Invisible text tells the agent to change the delivery address. You never see it; the agent reads it.</p></div>
      <div class="card"><span class="tag">A2</span><h3>Painted inside an image</h3><p>The order is drawn faintly in a promo banner. It is in the pixels, not in the code, so code checks miss it.</p></div>
      <div class="card"><span class="tag">A3</span><h3>Changed at the last second</h3><p>A script swaps the address on the review screen, right before the agent clicks Confirm.</p></div>
    </div>
  </div>
</section>

<section class="wrap-w stack-l sec" id="sec-how" tabindex="-1" aria-labelledby="how-h">
  <div class="sec-head">
    <h2 id="how-h">How it works</h2>
    <p>Four steps. You only act in the first and the third.</p>
  </div>
  <ol class="how">
    <li><span class="num">1</span><h3>Say your rules</h3><p>“Only deliver to the shop, at most 150,000 pesos per order.” Your words become a signed policy the agent cannot change.</p></li>
    <li><span class="num">2</span><h3>The agent works</h3><p>Muse Wonder restocks the shop on the supplier’s portal, click by click.</p></li>
    <li><span class="num">3</span><h3>Pixels are checked, you confirm</h3><p>Before Confirm, TESTIGO+ crops the total and the address from the screen. You read them aloud to approve.</p></li>
    <li><span class="num">4</span><h3>A receipt anyone can check</h3><p>It reads the screen again after the click and signs a receipt. One command verifies it, without trusting us.</p></li>
  </ol>
</section>

<section class="dark" id="sec-bench" tabindex="-1" aria-labelledby="res-h">
  <div class="wrap-w stack-m">
    <h2 id="res-h">WitnessBench, with real models</h2>
    ${landingBenchIntro()}
    ${benchCards(benchFacts(S.benchComplete), "dark", !!S.benchComplete)}
    <p><a class="on-dark" id="l-results" href="#/results">See every result</a></p>
  </div>
</section>

<section class="wrap-w sec start" id="sec-start" tabindex="-1" aria-labelledby="start-h">
  <div>
    <h2 id="start-h">See it stop an attack</h2>
    <p>Record your rules, pick an attack, and watch the agent run with and without TESTIGO+. About two minutes.</p>
  </div>
  <a class="btn-primary xl" id="start-demo" href="#/demo/rules">Start the demo</a>
</section>`;
  },

  results() {
    const f = benchFacts(S.bench);
    let table = "";
    if (f) {
      const rows = f.rows;
      const count = (sc, mode, fn) => rows.filter(x => x.scenario === sc && x.mode === mode && fn(x)).length;
      const n = (sc, mode) => rows.filter(x => x.scenario === sc && x.mode === mode).length;
      const line = (sc, mode) => {
        const total = n(sc, mode);
        if (!total) return `<td colspan="4">—</td>`;
        const att = count(sc, mode, x => x.delivered_to_attacker);
        const shop = count(sc, mode, x => x.confirmed && !x.delivered_to_attacker);
        const stopped = count(sc, mode, x => x.blocked);
        const own = count(sc, mode, x => !x.confirmed && !x.blocked);
        return `<td>${att} of ${total}</td><td>${stopped}</td><td>${own}</td><td>${shop}</td>`;
      };
      const body = SITUATIONS.map(x => ["no_supervisor", "supervised"].map((mode, i) =>
        `<tr>${i === 0 ? `<th scope="row" rowspan="2">${esc(x.name)}</th>` : ""}<td>${mode === "supervised" ? "With TESTIGO+" : "Without"}</td>${line(x.key, mode)}</tr>`).join("")).join("");
      table = rows.length ? `<div class="table-wrap" id="rtable-wrap" role="region" aria-label="Results per situation" tabindex="0"><table class="rtable">
          <caption>Each situation ran ${esc(n("a1", "supervised") || 5)} times with and without TESTIGO+.</caption>
          <thead><tr><th scope="col">Situation</th><th scope="col">Run</th><th scope="col">Reached the attacker</th><th scope="col">Stopped by TESTIGO+</th><th scope="col">Agent stopped on its own</th><th scope="col">Delivered to the shop</th></tr></thead>
          <tbody>${body}</tbody></table></div>` : "";
    }
    const s = f && f.summary;
    const edges = s && Array.isArray(s.edge_cases) && s.edge_cases.length
      ? `<p>Known limit, counted apart: an attack written only in words (“carrera ochenta número siete quince”) slips past the hidden-text filter. ${s.edge_cases.map(x => `${esc(x.mode === "supervised" ? "With" : "Without")} TESTIGO+: ${x.delivered_to_attacker ? "delivered to the attacker" : "not delivered to the attacker"}.`).join(" ")}</p>` : "";
    const details = f ? more("res-more", "How this was measured", `
        <p>Every number is read from <span class="mono">${esc(f.source)}</span>, written by the benchmark itself${f.date ? ` on ${esc(f.date)}` : ""}. Model: <span class="mono">${esc((S.bench.data || {}).model || "—")}</span>.</p>
        <p>TESTIGO+ adds a median of ${esc(secs(f.perRun))} per run and ${esc(secs(f.perCheck))} per screen check (p90 ${esc(secs((s.per_check_latency_ms || {}).p90))}).</p>
        ${edges}
        ${Number(s.errors) > 0 ? `<p>${esc(s.errors)} runs failed and are left out.</p>` : ""}
        <p>The full view with bars is in the <a id="res-present" href="#/present/8">presenter</a>.</p>`) : "";
    return `<div class="wrap-n page">
      <h1>WitnessBench results</h1>
      <p class="lede">${f ? `${esc(f.wo.runs)} attacks and ${esc(f.fp.clean_runs ?? "—")} clean orders, each run with and without TESTIGO+, with Meta’s real models${f.date ? ` on ${esc(f.date)}` : ""}. Counts, not percentages.` : "The benchmark runs every attack with and without TESTIGO+ using Meta’s real models."}</p>
      ${f && f.incomplete ? `<div class="callout warn">${ICON.warn}<div><b>This benchmark run is incomplete.</b>
        <p>${f.missing != null ? `${esc(f.missing)} configurations are missing. ` : ""}These numbers come from an unfinished local run (<span class="mono">${esc(f.source)}</span>); the landing shows the last complete results.</p></div></div>` : ""}
      ${benchCards(f, "light", !!S.bench)}
      ${table}${details}
      <p class="next-row"><a class="btn-primary" id="results-try" href="#/demo/rules">Try the demo</a></p>
    </div>`;
  },

  demo() {
    const step = S.route.step;
    return `<div class="wrap-n page">${stepper(step)}${steps[step]()}</div>`;
  },
};
function landingBenchIntro() {
  const f = benchFacts(S.benchComplete);
  if (!f) return `<p>Every attack, run with and without TESTIGO+, with Meta’s real models. Counts, not percentages.</p>`;
  return `<p>${esc(f.wo.runs)} attacks and ${esc(f.fp.clean_runs ?? "—")} clean orders, each run with and without TESTIGO+, with Meta’s real models${f.date ? ` on ${esc(f.date)}` : ""}. Counts, not percentages.</p>`;
}

// -- the guided demo --------------------------------------------------------------------
function stepper(step) {
  const at = STEPS.findIndex(x => x.key === step);
  const r = curRun();
  const reach = { rules: true, run: true, watch: !!r || !!S.waitingFor, result: !!r && outcome(r).kind !== "running" };
  return `<nav class="stepper" aria-label="Demo progress"><ol>${STEPS.map((x, i) => {
    const state = i === at ? "current" : i < at ? "done" : "todo";
    const inner = `<span class="n" aria-hidden="true">${i < at ? "✓" : i + 1}</span><span class="t">${esc(x.name)}</span>`;
    const label = `<span class="sr-only">Step ${i + 1} of ${STEPS.length}${i < at ? ", done" : ""}: </span>`;
    return `<li class="${state}">${reach[x.key] || i === at
      ? `<a id="step-${x.key}" href="#/demo/${x.key}"${i === at ? ' aria-current="step"' : ""}>${label}${inner}</a>`
      : `<span class="off-step">${label}${inner}</span>`}</li>`;
  }).join("")}</ol></nav>`;
}

const steps = {
  rules() {
    const p = S.policy;
    const head = `<h1>Your rules</h1>
      <p class="lede">The agent may only place orders that follow these rules. They are signed, so the agent cannot change them.</p>`;
    if (!p && S.policyError) return head + `<div class="callout bad">${ICON.stop}<div><b>Your rules could not be trusted.</b>
        <p>${esc(S.policyError)}</p><p>Record new rules to continue.</p></div></div>
        <div class="actions"><button class="btn-primary" id="showmandate" type="button">${ICON.mic} Record new rules</button></div>
        ${S.showMandate ? mandateLive({ transcript: "", deliver_only: [], max_per_order_cop: null, ask_before: "", short_sha: "" }) : ""}`;
    if (!p) return head + `<div class="loading">Loading your rules…</div>`;
    const ok = p.hash_ok && p.signed && p.signature_valid !== false;
    const sig = p.signature_valid === true ? "Signature valid" : p.signature_valid === false ? "Signature NOT valid"
      : "Signature present (the owner key is not on this machine to check it)";
    const rule = (icon, text, sub) => `<li>${icon}<div><span class="rt">${text}</span>${sub ? `<span class="rs">${sub}</span>` : ""}</div></li>`;
    return head + `<div class="card rules-card">
        <ul class="rules-list">
          ${p.deliver_only.map(x => rule(ICON.box, `Deliver only to ${esc(x.name)}`, `${esc(x.address)} · simulated address`)).join("")}
          ${rule(ICON.check, `At most ${esc(cop(p.max_per_order_cop))} per order`)}
          ${rule(ICON.ask, esc(askBefore(p.ask_before)))}
        </ul>
        <div class="sealrow ${ok ? "ok" : "bad"}">${ok ? ICON.seal : ICON.stop}<span>${ok ? `Signed by ${esc(p.owner || "the owner")}` : "These rules are not trusted: the signature or the content does not check out"}</span></div>
        ${more("rules-more", "Show the signed policy", `
          ${p.transcript ? `<p>You said: <q>${esc(p.transcript)}</q></p>` : ""}
          <dl class="kv"><dt>Fingerprint</dt><dd class="mono">sha256 ${esc(p.short_sha)}</dd>
            <dt>Content</dt><dd>${p.hash_ok ? "matches its fingerprint" : "does NOT match its fingerprint"}</dd>
            <dt>Signature</dt><dd>${esc(sig)} · ${esc(p.signed_by || "")}</dd>
            <dt>File</dt><dd class="mono">${esc(p.path || "")}${p.active === "signed_here" ? " · signed in this interface" : " · the demo’s committed policy"}</dd></dl>`)}
      </div>
      <div class="actions">
        <a class="btn-primary" href="#/demo/run" id="userules">Use these rules</a>
        <button class="btn-secondary" id="showmandate" type="button" aria-expanded="${S.showMandate}" aria-controls="mlive">${ICON.mic} Record new rules</button>
      </div>
      ${S.showMandate ? `<div class="mandate-wrap"><p class="muted">Say your limits out loud, for example: <q>Solo pide con entrega en la tienda, máximo ciento cincuenta mil pesos por pedido</q>. Your words become a draft; nothing changes until you sign it.</p>${mandateLive(p)}</div>` : ""}`;
  },

  run() {
    const p = S.pick;
    const busyRun = procRunning();
    const cards = SITUATIONS.map(x => `<label class="pick${p.scenario === x.key ? " on" : ""}">
        <input type="radio" name="situation" id="sit-${x.key}" value="${x.key}"${p.scenario === x.key ? " checked" : ""}>
        <span class="pt">${esc(x.name)}</span><span class="pd">${esc(x.text)}</span></label>`).join("");
    const err = S.runReq.error ? `<div class="callout ${S.runReq.busyRun ? "warn" : "bad"}">${S.runReq.busyRun ? ICON.pause : ICON.warn}<div>
        <b>${S.runReq.busyRun ? "Another run is already in progress." : "The run could not start."}</b>
        <p>${S.runReq.busyRun ? "Only one run at a time. Watch it, or stop it first." : esc(S.runReq.error)}</p>
        ${S.runReq.busyRun ? `<p><a id="watch-current" href="#/demo/watch">Watch the current run</a></p>` : ""}</div></div>` : "";
    const orphan = S.proc && S.proc.state === "orphaned" ? `<div class="callout warn">${ICON.warn}<div><b>A run from before the service restarted is still going.</b>
        <p>Stop it before starting another.</p><div class="actions tight"><button class="btn-secondary" id="cancelorphan" type="button">Stop that run</button></div></div></div>` : "";
    const inProgress = busyRun && !S.runReq.error ? `<div class="callout info">${ICON.eye}<div><b>A run is in progress.</b>
        <p><a id="watch-it" href="#/demo/watch">Watch it</a> or wait until it ends to start another.</p></div></div>` : "";
    return `<h1>Run the agent</h1>
      <p class="lede">Pick a situation. The agent will try to restock Doña Marta’s shop on the supplier’s page.</p>
      ${orphan}${inProgress}
      <form id="runform" class="runform" novalidate>
        <fieldset class="picks"><legend>Situation</legend>${cards}</fieldset>
        <div class="switchrow">
          <label class="switch"><input type="checkbox" role="switch" id="protect"${p.supervised ? " checked" : ""} aria-describedby="protect-help">
            <span class="track" aria-hidden="true"><span class="knob"></span></span><span class="sl">Protect with TESTIGO+</span></label>
          <p id="protect-help" class="muted">${p.supervised ? "TESTIGO+ checks the screen before every sensitive click and asks you before the order is confirmed."
            : "Off: the agent runs alone, to see what would happen without TESTIGO+."}</p>
        </div>
        ${more("run-more", "More options", `
          <label class="field">Page version <select id="variant">${[1, 2, 3, 4, 5].map(v => `<option value="${v}"${p.variant === v ? " selected" : ""}>Version ${v}</option>`).join("")}</select></label>
          <p class="muted small">Each situation has five versions of the page (different wording or timing).</p>
          <label class="check"><input type="checkbox" id="headed"${p.headed ? " checked" : ""}> Show the agent’s browser window</label>`)}
        ${err}
        <div class="actions">
          <button class="btn-primary" type="submit" id="runbtn"${S.runReq.busy || busyRun ? " disabled" : ""}>${S.runReq.busy ? "Starting…" : "Run the agent"}</button>
          <a class="btn-link" id="backrules" href="#/demo/rules">Back to your rules</a>
        </div>
        <p class="muted small">This runs the real agent with Meta’s models: it takes a minute or two and uses API credit. Simulation only: the shop, the supplier and the addresses are not real.</p>
      </form>`;
  },

  watch() {
    const r = curRun();
    if (S.waitingFor) {
      const p = S.proc;
      if (p && p.state !== "running") {
        return `<h1>Watching</h1>${runFailed(p)}`;
      }
      return `<h1>Watching</h1>
        <div class="status-line info">${ICON.eye}<span>Starting the agent and opening the supplier’s page…</span></div>
        <div class="loading">This usually takes a few seconds.</div>
        <div class="actions"><button class="btn-secondary" id="cancelrun" type="button">Stop the run</button></div>`;
    }
    if (!r) return `<h1>Watching</h1>
      <div class="empty-state"><b>No run yet.</b><p>Choose a situation and start the agent to watch it here.</p>
        <a class="btn-primary" id="choose-run" href="#/demo/run">Choose a situation</a></div>`;
    const o = outcome(r);
    const sup = r.mode === "supervised";
    const you = needsYou(r);
    const done = o.kind !== "running";
    const status = you ? { cls: "warn", icon: ICON.pause, text: "TESTIGO+ needs you: approve or deny the order below." }
      : done ? { cls: o.cls, icon: o.icon, text: o.title + "." }
      : { cls: "info", icon: ICON.eye, text: sup ? "The agent is working. TESTIGO+ is checking each sensitive step." : "The agent is working, with TESTIGO+ switched off." };
    const lines = r.log.map(e => plainLine(e, r)).filter(Boolean);
    const list = lines.length ? `<ol class="plainlog">${lines.map(([ic, cls, t]) => `<li><span class="ic ${cls}">${ic}</span><span>${esc(t)}</span></li>`).join("")}</ol>`
      : `<p class="muted pad">Nothing yet.</p>`;
    const proc = procFor(r);
    const capsule = you ? `<section class="needs-you" aria-labelledby="ny-h">
        <h2 id="ny-h">Approve what will really happen</h2>
        <p class="muted">These are exact crops of the screen, not the agent’s summary. Read the total and the address aloud, then approve.</p>
        ${approvalCapsule()}</section>` : "";
    return `<h1>Watching</h1>
      <p class="lede">${esc(situation(r.scenario).name)} · ${sup ? "protected by TESTIGO+" : "without TESTIGO+"}</p>
      <div class="status-line ${status.cls}">${status.icon}<span>${esc(status.text)}</span></div>
      ${capsule}
      <div class="watch-grid">
        <section class="card" aria-labelledby="scr-h"><h2 id="scr-h" class="card-h">The agent’s screen</h2>${shot(r, r.lastFrame, [])}</section>
        <section class="card" aria-labelledby="chk-h"><h2 id="chk-h" class="card-h">${sup ? "What TESTIGO+ checked" : "What happened"}</h2>
          ${sup ? "" : `<p class="muted pad">TESTIGO+ is off for this run: nothing is checked.</p>`}${list}</section>
      </div>
      <div class="actions">
        ${done ? `<a class="btn-primary" href="#/demo/result" id="seeresult">See the result</a>` : ""}
        ${proc && proc.state === "running" ? `<button class="btn-secondary" id="cancelrun" type="button">Stop the run</button>` : ""}
      </div>`;
  },

  result() {
    const r = curRun();
    if (!r) return `<h1>Result</h1>${S.waitingFor && S.proc && S.proc.state !== "running" ? runFailed(S.proc)
      : `<div class="empty-state"><b>No result yet.</b><p>Run the agent first; its result appears here.</p><a class="btn-primary" id="choose-run" href="#/demo/run">Choose a situation</a></div>`}`;
    const o = outcome(r);
    const sup = r.mode === "supervised";
    if (o.kind === "running") return `<h1>Result</h1>
      <div class="empty-state"><b>The run is not over yet.</b><p>Watch it until it ends.</p><a class="btn-primary" id="back-watch" href="#/demo/watch">Back to watching</a></div>`;
    const other = S.runs[sup ? "no_supervisor" : "supervised"];
    const oo = other && other.mode && other.scenario === r.scenario && (other.variant || 1) === (r.variant || 1) ? outcome(other) : null;
    const compare = oo && oo.kind !== "running" ? `<div class="compare">
        <span class="muted">${sup ? "Without TESTIGO+" : "With TESTIGO+"}, same situation:</span>
        <span class="chip ${oo.cls}">${oo.icon}${esc(oo.title)}</span></div>` : "";
    const proc = procFor(r);
    const tail = proc && proc.tail && proc.tail.length && (o.kind === "error" || o.kind === "ended")
      ? more("res-log", "Last lines the run printed", `<pre class="tail">${esc(proc.tail.join("\n"))}</pre>`) : "";
    const ev = [];
    if (sup && r.check) ev.push(more("res-check", "What TESTIGO+ saw on the screen", `
        <p class="muted">The screen as the agent saw it, with the regions the pixel reader found. Left, text only in the page code; right, text only on screen.</p>${divergeBody(r)}`));
    if (sup && verifyOutcome(r).event) ev.push(more("res-after", "What you approved vs. what happened", afterBody(r)));
    if (!sup && r.explain) ev.push(more("res-explain", "Where the attack was", explainPanel(r)));
    if (!sup && !r.explain && proc && proc.state === "running") ev.push(`<p class="muted">Looking for where the attack was…</p>`);
    ev.push(more("res-steps", "Every step, in detail", timeline(r)));
    const again = sup ? "Compare without TESTIGO+" : "Run it with TESTIGO+";
    const busy = procRunning();
    return `<h1>Result</h1>
      <p class="lede">${esc(situation(r.scenario).name)} · ${sup ? "protected by TESTIGO+" : "without TESTIGO+"}</p>
      <div class="outcome-card ${o.cls}">${o.icon}<div><p class="ot">${esc(o.title)}</p><p class="os">${esc(o.text)}</p></div></div>
      ${compare}
      ${sup ? receiptCard(r) : ""}
      ${S.runReq.error ? `<div class="callout bad">${ICON.warn}<div><b>The run could not start.</b><p>${esc(S.runReq.error)}</p></div></div>` : ""}
      <div class="actions">
        <a class="btn-primary" id="runanother" href="#/demo/run">Run another</a>
        <button class="btn-secondary" id="compare" type="button"${busy || S.runReq.busy ? " disabled" : ""}>${again}</button>
      </div>
      <h2 class="sub">The evidence</h2>
      ${ev.join("")}${tail}`;
  },
};

function runFailed(p) {
  const why = p.state === "cancelled" ? "You stopped the run before it reported anything."
    : p.state === "finished" ? "The run ended, but none of its steps reached this page."
    : "The agent could not start. Check that the Meta API key is set in .env and that the supplier portal is running (make run).";
  return `<div class="callout ${p.state === "cancelled" ? "info" : "bad"}">${ICON.warn}<div>
      <b>${p.state === "cancelled" ? "Run stopped" : "The run did not work"}</b><p>${esc(why)}</p></div></div>
    ${p.tail && p.tail.length ? more("fail-log", "Last lines the run printed", `<pre class="tail">${esc(p.tail.join("\n"))}</pre>`) : ""}
    <div class="actions"><a class="btn-primary" id="back-run" href="#/demo/run">Back to Run the agent</a></div>`;
}

function receiptCard(r) {
  const ev = r.receipt;
  if (!ev) return `<div class="card receipt-card"><h2 class="card-h">Receipt</h2><p class="pad muted">No receipt for this run: receipts are signed only for an order you approved.</p></div>`;
  if (isPlaceholder(ev.signature) || !ev.path) return `<div class="card receipt-card"><h2 class="card-h">Receipt</h2>
      <p class="pad muted">A receipt was built but not signed on this machine (the owner key is missing), so there is nothing to verify.</p></div>`;
  const rc = S.receipt, vo = S.verify;
  let body;
  if (!rc) body = `<p class="pad muted">Loading the receipt…</p>`;
  else if (rc.error) body = `<p class="pad">The receipt file could not be read: ${esc(rc.error)}</p>`;
  else {
    const d = rc.receipt;
    const res = S.verifying ? `<p class="verify-res">Checking the signature and the evidence…</p>`
      : vo ? `<p class="verify-res ${vo.exit_code === 0 ? "ok" : "bad"}">${vo.exit_code === 0 ? ICON.check : ICON.stop}<span>${vo.exit_code === 0
          ? "Valid: the signature and the evidence match." : "Not valid: the receipt or its evidence does not check out."}</span></p>
          ${more("verify-out", "Command output", `<pre class="tail"><span class="mono">$ testigo verify runs/${esc(rc.path)}</span>\n${esc(vo.output)}</pre>`)}` : "";
    body = `<div class="pad">
        <p>Receipt <span class="mono">${esc(d.id || ev.id)}</span>${d.status === "blocked" ? " · records a blocked order (nothing executed)" : ""}. It binds your rules, the screen crops you approved and what executed. Anyone can check it without trusting us.</p>
        <div class="actions tight"><button class="btn-secondary" id="verifybtn" type="button"${S.verifying ? " disabled" : ""}>${ICON.seal} Verify receipt</button></div>
        ${res}
        ${more("rc-json", "Receipt contents", `<dl class="kv mono small">${["id", "time", "agent", "action", "status", "policy_sha256", "signed_by", "signature"].filter(k => d[k] != null)
          .map(k => `<dt>${esc(k)}</dt><dd>${esc(d[k])}</dd>`).join("")}</dl><p class="muted small">File: runs/${esc(rc.path)}</p>`)}
      </div>`;
  }
  return `<div class="card receipt-card"><h2 class="card-h">${ICON.seal} Signed receipt</h2>${body}</div>`;
}

// -- the live status for screen readers -------------------------------------------
function alertMessage() {
  if (S.route.name !== "demo") return "";
  const st = S.route.step;
  if (st === "rules" && !S.policy && S.policyError) return "Your rules could not be trusted: " + S.policyError;
  if ((st === "run" || st === "result") && S.runReq.error) return (S.runReq.busyRun ? "Another run is already in progress." : "The run could not start: " + S.runReq.error);
  if (S.waitingFor && S.proc && !["running", "orphaned"].includes(S.proc.state)) return "The run did not work.";
  return "";
}
function liveMessage() {
  if (S.route.name !== "demo") return "";
  if (S.route.step === "result" && (S.verifying || S.verify)) {
    return S.verifying ? "Checking the receipt." : S.verify.exit_code === 0 ? "Receipt valid: the signature and the evidence match." : "Receipt not valid.";
  }
  if (S.waitingFor) return S.proc && S.proc.state !== "running" ? "The run did not start." : "Starting the agent.";
  const r = curRun();
  if (!r) return "";
  if (needsYou(r)) return "TESTIGO+ needs you to approve the order.";
  const o = outcome(r);
  return o.kind === "running" ? "The agent is working." : o.title + ".";
}
// The live regions live outside #app and are never re-created: their text
// changes only when the message does, so nothing is announced twice.
function announce() {
  const set = (id, key, msg) => {
    if (msg === S[key]) return;
    S[key] = msg;
    const el = document.getElementById(id);
    if (el) el.textContent = msg;
  };
  set("announce", "lastAnnounce", liveMessage());
  set("alertmsg", "lastAlert", alertMessage());
}

// -- drawing ----------------------------------------------------------------------
function presentShell() {
  return `<div class="present">
    <header class="topbar" id="topbar">
      <a class="brand" id="pnav-home" href="#/" title="Leave the presenter"><svg class="logo" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z" fill="currentColor"/><circle cx="12" cy="11" r="3.2" fill="#fff"/><circle cx="12" cy="11" r="1.4" fill="currentColor"/></svg>
        <span class="wordmark">TESTIGO<b>+</b></span></a>
      <div class="runinfo" id="runinfo"></div>
      <div class="agentstate" id="agentstate"></div>
      <nav class="views" id="nav" aria-label="Views"></nav>
      <button class="auto" id="auto" type="button" title="Follow events (A)"></button>
      <span class="conn" id="conn"></span>
    </header>${testBanner()}<main id="view" class="view"></main></div>`;
}
function hasNews(i) {
  const r = S.runs.supervised;
  return { 2: r.log.length, 3: S.runs.no_supervisor.log.length, 4: r.check, 5: r.approval,
           6: r.verify, 7: r.receipt }[i];
}
// the run a view is about: view 3 is the unsupervised run, 2 and 4-7 the supervised one
function runFor(i) {
  if (i === 3) return S.runs.no_supervisor;
  if (i >= 2 && i <= 7) return S.runs.supervised;
  return run();
}
function drawPresent() {
  const r = runFor(S.view), st = agentState(r);
  document.getElementById("topbar").classList.toggle("off", r.mode === "no_supervisor");
  document.getElementById("runinfo").textContent = r.mode ? `${r.scenario || ""}${r.variant ? " v" + r.variant : ""}` : "";
  document.getElementById("agentstate").innerHTML = chip(st.cls, st.icon, st.text);
  document.getElementById("nav").innerHTML = VIEWS.map((v, i) =>
    `<a id="pnav-${i}" href="#/present/${i}" ${i === S.view ? 'aria-current="page"' : ""}><span class="n">${i || "·"}</span>${esc(v.name)}${hasNews(i) && i !== S.view ? '<span class="dot"></span>' : ""}</a>`).join("");
  const auto = document.getElementById("auto");
  auto.textContent = S.auto ? "Follow: on" : "Follow: off";
  auto.setAttribute("aria-pressed", String(S.auto));
  const conn = document.getElementById("conn");
  conn.className = "conn " + (S.conn === "live" ? "live" : S.conn === "down" ? "down" : "");
  conn.textContent = S.conn === "live" ? "Live" : S.conn === "down" ? "Reconnecting" : "Connecting";
  document.getElementById("view").innerHTML = `<div class="wrap">${render[VIEWS[S.view].key]()}</div>` +
    `<div class="keys"><kbd>←</kbd><kbd>→</kbd> views · <kbd>0</kbd>–<kbd>8</kbd> jump · <kbd>A</kbd> follow</div>`;
}

const TITLES = { rules: "Your rules", run: "Run the agent", watch: "Watching", result: "Result" };
function draw() {
  const app = document.getElementById("app");
  const active = document.activeElement;
  const keep = active && active.id && app.contains(active) ? active.id : null;
  const r = S.route;
  if (r.name === "present") {
    PLAIN = false;
    app.innerHTML = presentShell();
    drawPresent();
    document.title = "TESTIGO+ · presenter";
  } else {
    PLAIN = true;
    const body = r.name === "landing" ? page.landing() : r.name === "results" ? page.results() : page.demo();
    app.innerHTML = siteHeader() + testBanner() +
      `<main id="main" class="site-main ${r.name}" tabindex="-1">${body}</main>` + siteFooter();
    document.title = r.name === "demo" ? `${TITLES[r.step]} · TESTIGO+ demo`
      : r.name === "results" ? "Results · TESTIGO+" : "TESTIGO+ · a witness for AI agents";
  }
  bind();
  if (keep) {
    const el = document.getElementById(keep);
    if (el && el !== document.activeElement) el.focus({ preventScroll: true });
  }
  document.body.dataset.conn = S.conn;
  announce();
}

function bind() {
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("runverify", runVerify); on("verifybtn", runVerify);
  on("vrec", startRecording); on("vstop", () => stopRecording(false));
  on("vapprove", () => decide("approve")); on("vdeny", () => decide("deny"));
  on("mrec", startMandate); on("mstop", () => stopMandate(false));
  on("msign", signMandate); on("mdiscard", discardMandate);
  on("auto", () => { S.auto = !S.auto; draw(); });
  on("showmandate", () => { S.showMandate = !S.showMandate; draw(); });
  on("cancelrun", cancelRun); on("cancelorphan", cancelRun);
  on("compare", () => {
    const r = curRun();
    if (r) startRun({ scenario: r.scenario, variant: r.variant || 1, supervised: r.mode !== "supervised" });
  });
  const form = document.getElementById("runform");
  if (form) {
    form.onsubmit = e => { e.preventDefault(); startPicked(); };
    form.querySelectorAll('input[name="situation"]').forEach(el => {
      el.onchange = () => { S.pick.scenario = el.value; draw(); };
    });
    const protect = document.getElementById("protect");
    protect.onchange = () => { S.pick.supervised = protect.checked; draw(); };
    const variant = document.getElementById("variant");
    if (variant) variant.onchange = () => { S.pick.variant = Number(variant.value); };
    const headed = document.getElementById("headed");
    if (headed) headed.onchange = () => { S.pick.headed = headed.checked; };
  }
}

// remember which disclosures are open across redraws (toggle does not bubble)
document.addEventListener("toggle", e => {
  const t = e.target;
  if (t && t.tagName === "DETAILS" && t.id) S.open[t.id] = t.open;
}, true);

// -- live events ---------------------------------------------------------------------
let backoff = 500;
function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.onopen = () => { S.conn = "live"; backoff = 500; draw(); };
  ws.onmessage = m => {
    const e = JSON.parse(m.data);
    S.pendingView = undefined;
    if (e.type === "hub.history") {
      S.runs = { supervised: freshRun(), no_supervisor: freshRun() };
      S.current = null; S.test = false;
      e.events.forEach(x => apply(x, () => {}));   // replay without jumping views
      syncWaiting();
    } else {
      if (e.type === "run.started" && S.waitingFor === e.mode) S.waitingFor = null;
      apply(e, follow);
    }
    if (S.route.name === "present" && S.pendingView !== undefined && S.pendingView !== S.view) { go(S.pendingView); return; }
    draw();
    const reload = ["receipt.signed", "hub.reset", "hub.history", "run.started"];
    if (!reload.includes(e.type)) return;
    if (S.route.name === "present" && VIEWS[S.view].key === "receipt") loadFor(S.view);
    if (S.route.name === "demo" && S.route.step === "result") loadForRoute();
  };
  ws.onclose = () => { S.conn = "down"; draw(); setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 8000); };
}

window.addEventListener("hashchange", () => onRoute(false));
document.addEventListener("keydown", e => {
  if (S.route.name !== "present" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(e.target.tagName) && e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  if (e.key === "ArrowRight") go(S.view + 1);
  else if (e.key === "ArrowLeft") go(S.view - 1);
  else if (/^[0-8]$/.test(e.key)) go(Number(e.key));
  else if (e.key === "a" || e.key === "A") { S.auto = !S.auto; draw(); }
});
document.getElementById("skip").onclick = e => {
  e.preventDefault();
  const m = document.getElementById("main") || document.getElementById("view");
  if (m) { m.setAttribute("tabindex", "-1"); m.focus(); }
};

S.route = parseRoute();
if (S.route.name === "present") S.view = S.route.view;
getJSON("/api/policy").then(p => { S.policy = p; draw(); }).catch(err => { S.policyError = err.message; draw(); });
refreshProc().then(() => { if (S.proc && S.proc.state === "running") { syncWaiting(); draw(); } });
draw();
loadForRoute();
if (S.route.section) arrive(null);
connect();
