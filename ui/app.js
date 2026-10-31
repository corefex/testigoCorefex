/* TESTIGO+ interface (F11).
 *
 * Shows, never decides. Every value on screen comes from an event on /ws or a
 * file the service reads (policy, receipt, bench). State is rebuilt from the
 * events; nothing is stored in the browser except the current view (URL hash).
 */
"use strict";

const VIEWS = [
  { key: "cover", name: "Cover" },
  { key: "mandate", name: "Mandate" },
  { key: "agent", name: "Agent" },
  { key: "nosup", name: "No supervisor" },
  { key: "diverge", name: "Divergence" },
  { key: "approve", name: "Approval" },
  { key: "after", name: "After click" },
  { key: "receipt", name: "Receipt" },
  { key: "bench", name: "WitnessBench" },
];
const REQUIRED = ["amount", "address", "confirm button"];
const SHOT_W = 1280, SHOT_H = 800;   // portal capture size (F11-D3)

// -- icons ---------------------------------------------------------------
const P = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
const ICON = {
  check: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>`,
  stop: `<svg viewBox="0 0 24 24" ${P}><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M12 8v5M12 16.5v.5"/></svg>`,
  warn: `<svg viewBox="0 0 24 24" ${P}><path d="M12 3 2 21h20z"/><path d="M12 10v4M12 17.5v.5"/></svg>`,
  eye: `<svg viewBox="0 0 24 24" ${P}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>`,
  mic: `<svg viewBox="0 0 24 24" ${P}><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>`,
  finger: `<svg viewBox="0 0 24 24" ${P}><path d="M12 11v3a8 8 0 0 1-1.2 4.2M8.5 8.6A4 4 0 0 1 16 11v1.5M7.8 13a12 12 0 0 1-1 4M16 15.5a15 15 0 0 1-.8 3.5M5 10a7 7 0 0 1 12.6-4.2M19 10v2"/></svg>`,
  pause: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/></svg>`,
  dot: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="3"/></svg>`,
  ask: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.4M12 17v.5"/></svg>`,
  user: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>`,
  coin: `<svg viewBox="0 0 24 24" ${P}><circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.5-.5-3-1.5M12 6v2M12 16v2"/></svg>`,
  file: `<svg viewBox="0 0 24 24" ${P}><path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 13h6M9 17h6"/></svg>`,
  seal: `<svg viewBox="0 0 24 24" ${P}><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>`,
  term: `<svg viewBox="0 0 24 24" ${P}><path d="m5 8 4 4-4 4M12 16h7"/></svg>`,
};

// -- state, rebuilt from events ------------------------------------------
function freshRun() {
  return { mode: null, scenario: null, variant: null, log: [], frames: {}, lastFrame: null,
           check: null, approval: null, granted: null, order: null, verify: null, verifies: [],
           receipt: null, explain: null };
}
const S = {
  conn: "connecting", test: false, current: null,
  runs: { supervised: freshRun(), no_supervisor: freshRun() },
  view: viewFromHash(), auto: true,
  policy: null, receipt: null, receiptFor: undefined, verify: null, verifying: false, bench: null,
  // view 5: the approval as the service holds it (/api/approval) and the microphone
  desk: null, deskChecked: false, deskBusy: false, rec: { state: "idle", error: "" },
  // view 1: a mandate recorded live. idle | starting | recording | transcribing |
  // draft | refused | signing | signed. The draft lives in the service; the page
  // only shows it and asks the service to sign exactly that draft.
  mandate: { state: "idle", draft: null, reason: "", transcript: "", error: "" },
};

function run() { return S.runs[S.current] || S.runs.supervised; }
// approval.granted carries the person's answer; older events only had voice_match
function isGranted(g) { return !!g && g.granted !== false && g.voice_match === true; }
// the loop's receipt is an unsigned preview until F9 signs it
function isPlaceholder(sig) { return /PLACEHOLDER/i.test(sig || ""); }
function forgetReceipt() { S.receipt = null; S.receiptFor = undefined; S.verify = null; S.loadSeq = (S.loadSeq || 0) + 1; }

function apply(e, follow) {
  if (e.test_data) S.test = true;
  if (e.type === "hub.reset") {
    S.runs = { supervised: freshRun(), no_supervisor: freshRun() };
    S.current = null; S.test = false; forgetReceipt();
    return;
  }
  if (e.type === "run.started") {
    if (!(e.mode in S.runs) || !Object.prototype.hasOwnProperty.call(S.runs, e.mode)) return;
    if (e.mode === "supervised") forgetReceipt();
    const r = freshRun();
    r.mode = e.mode; r.scenario = e.scenario; r.variant = e.variant;
    S.runs[e.mode] = r; S.current = e.mode;
    r.log.push(e);
    follow(e.mode === "no_supervisor" ? 3 : 2);
    return;
  }
  if (e.type === "explain.result") {          // after an unsupervised run, observe only
    const nr = S.runs.no_supervisor;
    nr.log.push(e); nr.explain = e;
    if (e.image && !(nr.frames[e.frame] || {}).image) nr.frames[e.frame] = { sha: null, image: e.image };
    return;
  }
  const r = run();
  r.log.push(e);
  switch (e.type) {
    case "frame.captured":
      r.frames[e.frame] = { sha: e.sha256, image: e.image || null };
      r.lastFrame = e.frame;
      break;
    case "check.result":
      r.check = e;
      if (e.status !== "ok") follow(4);
      break;
    // a new approval: any earlier answer was for the earlier approval
    case "approval.requested": r.approval = e; r.granted = null; follow(5); loadDesk(); break;
    case "approval.granted": r.granted = e; stopRecording(true); loadDesk(); break;
    case "order.confirmed":
      r.order = e;
      if (r.mode === "no_supervisor") follow(3);
      break;
    case "verify.result": r.verifies.push(e); r.verify = e; follow(6); break;
    case "receipt.signed": r.receipt = e; forgetReceipt(); break;
  }
}

function agentState(r) {
  if (!r.mode) return { cls: "off", icon: ICON.dot, text: "Idle" };
  if (r.mode === "no_supervisor") return { cls: "off", icon: ICON.warn, text: "No supervisor" };
  if (r.check && r.check.status === "cannot_verify") return { cls: "warn", icon: ICON.ask, text: "Blocked · ask a human" };
  if (r.check && r.check.status !== "ok") return { cls: "bad", icon: ICON.stop, text: "Blocked" };
  const vo = verifyOutcome(r);
  if (vo.kind === "blocked") return { cls: "bad", icon: ICON.stop, text: "Blocked at review" };
  if (vo.kind === "flagged") return { cls: "bad", icon: ICON.stop, text: "Flagged for review" };
  if (vo.kind === "cannot") return { cls: "warn", icon: ICON.ask, text: vo.moment === "review" ? "Blocked · could not verify" : "Flagged · could not verify" };
  if (r.granted && !isGranted(r.granted)) return { cls: "bad", icon: ICON.stop, text: "Denied" };
  if (r.approval && !r.granted) return { cls: "warn", icon: ICON.pause, text: "Paused · approval" };
  return { cls: "ok", icon: ICON.eye, text: r.receipt ? "Done" : "Running" };
}

// -- helpers -------------------------------------------------------------
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function cop(n) { return n == null ? "—" : "COP " + Number(n).toLocaleString("en-US"); }
function short(h) { return h ? h.slice(0, 4) + "…" + h.slice(-4) : "—"; }
function time(ts) { const m = /T(\d\d:\d\d:\d\d)/.exec(ts || ""); return m ? m[1] : ""; }
function runUrl(p) { return "/runs/" + String(p).split("/").map(encodeURIComponent).join("/"); }
function chip(cls, icon, text, lg) { return `<span class="chip ${cls}${lg ? " lg" : ""}">${icon}${esc(text)}</span>`; }
function empty(title, sub) {
  return `<div class="empty"><div>${ICON.dot}<b>${esc(title)}</b>${esc(sub || "")}</div></div>`;
}
function allowedAddresses() {
  return S.policy ? S.policy.deliver_only.map(p => normRead("address", p.address)) : [];
}
// -- F8: compare by the values read from the pixels (receipts/receipt.py norm_read)
// Real crops of unchanged content hash differently across captures, so view 6
// never compares hashes when read values exist.
// A Colombian street address in canonical form, as common/address.py does it
// (keep the two in step; tests/test_ui.py checks they agree): street type (and
// its abbreviations), letter/"bis" suffixes per number ("45A", "45 Bis"),
// quadrant ("Sur", ...), "#"/"No."/"N°"/"número", en/em dashes (a space after
// an explicit separator), I/l/O misread for 1/1/0 in digit places, ASCII digits
// only; up to four words after it are part of it, except the city "Bogotá"/"D.C."
// -> "calle 45 # 12-30", "calle 45a bis # 12-30 sur".
const STREET_TYPES = {
  calle: "calle", cll: "calle", cl: "calle",
  carrera: "carrera", cra: "carrera", kra: "carrera", kr: "carrera", cr: "carrera",
  avenida: "avenida", avda: "avenida", av: "avenida",
  diagonal: "diagonal", diag: "diagonal", dg: "diagonal",
  transversal: "transversal", transv: "transversal", tv: "transversal", tr: "transversal",
};
const QUADRANTS = ["sur", "este", "norte", "oeste"];
const COMPLEMENTS = new Set([...QUADRANTS, "bis", "int", "interior", "apto", "apartamento", "ap", "local",
  "loc", "of", "oficina", "torre", "bloque", "bl", "casa", "piso", "lote", "manzana", "mz", "etapa"]);
const CITY_WORDS = new Set(["bogota", "dc"]);
const TAIL_MAX = 4;
const ci = w => w.replace(/[a-z]/g, c => `[${c}${c.toUpperCase()}]`);
const W = "[\\p{L}\\p{N}_]";
const ADDR_STREET = Object.keys(STREET_TYPES).sort((a, b) => b.length - a.length).map(ci).join("|");
const ADDR_NUM = "(?=[0-9IlO]{0,2}[0-9])[0-9IlO]{1,3}";
const ADDR_LET = `[A-Za-z](?!${W})`;
const ADDR_BIS = `${ci("bis")}(?!${W})`;
const ADDR_SEP = `(?:#|${ci("n")}[oOº°]\\.?|${ci("n")}\\.\\s?[oOº°]|${ci("nro")}\\.?|${ci("n")}[uUúÚ]${ci("mero")})`;
const ADDR_DASH = "[\\-–—]";
function addrGroup(k, last) {
  const suffix = last ? `(?:${ADDR_LET})?(?:\\s*${ADDR_BIS})?`
                      : `(?:\\s?${ADDR_LET})?(?:\\s*${ADDR_BIS}(?:\\s?${ADDR_LET})?)?`;
  return `(?<n${k}>${ADDR_NUM})(?<s${k}>${suffix})(?!${W})`;
}
const ADDR_SRC = `(?<!${W})(?<street>${ADDR_STREET})\\.?\\s*${addrGroup("1")}` +
  `(?:\\s+(?<quad>${QUADRANTS.map(ci).join("|")})(?!${W}))?\\s*` +
  `(?:(?:${ADDR_SEP}\\s*)?${addrGroup("2a")}\\s*${ADDR_DASH}\\s*${addrGroup("3a", true)}` +
  `|${ADDR_SEP}\\s*${addrGroup("2b")}\\s+${addrGroup("3b", true)})(?![.,][0-9])`;
const ADDRESS_RE = new RegExp(ADDR_SRC, "gu");
const ADDRESS_AT = new RegExp(ADDR_SRC, "uy");
function fold(t) {
  return String(t).normalize("NFKD").replace(/\p{Mn}/gu, "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}
function ocrDigits(t) { return t.replace(/[Il]/g, "1").replace(/O/g, "0").replace(/^0+(?=[0-9])/, ""); }
function addrNumber(num, suffix) {
  const s = (suffix || "").replace(/\s+/g, "").toLowerCase();
  const k = s.indexOf("bis");
  const head = k < 0 ? s : s.slice(0, k), after = k < 0 ? "" : s.slice(k + 3);
  return ocrDigits(num) + head + (k < 0 ? "" : " bis") + (after ? " " + after : "");
}
const isWordStart = c => /^[\p{L}0-9]$/u.test(c);
function addrTail(text, i) {
  const out = [], n = text.length;
  let city = false;
  const at = k => String.fromCodePoint(text.codePointAt(k));
  while (out.length < TAIL_MAX) {
    let comma = false;
    while (i < n && (/\s/u.test(text[i]) || text[i] === ",")) { comma = comma || text[i] === ","; i++; }
    if (i >= n || !isWordStart(at(i))) break;
    ADDRESS_AT.lastIndex = i;
    if (ADDRESS_AT.test(text)) break;
    let j = i;
    while (j < n && (isWordStart(at(j)) || text[j] === ".")) j += at(j).length;
    const word = fold(text.slice(i, j)).replace(/\./g, "");
    i = j;
    if (CITY_WORDS.has(word)) city = true;
    else if (city && !comma && !COMPLEMENTS.has(word)) break;
    else out.push(word);
  }
  return out;
}
function canonicalAddresses(text) {
  text = String(text == null ? "" : text).normalize("NFC");
  const found = new Set();
  for (const m of text.matchAll(ADDRESS_RE)) {
    const g = m.groups, k = g.n2a ? "a" : "b";
    const tail = (g.quad ? [g.quad.toLowerCase()] : []).concat(addrTail(text, m.index + m[0].length));
    found.add([`${STREET_TYPES[g.street.toLowerCase()]} ${addrNumber(g.n1, g.s1)} # ` +
               `${addrNumber(g["n2" + k], g["s2" + k])}-${addrNumber(g["n3" + k], g["s3" + k])}`, ...tail].join(" "));
  }
  return [...found].sort();
}
function amountDigits(text) {
  let best = "";
  for (let n of text.match(/[0-9][0-9.,\s]*[0-9]|[0-9]/g) || []) {
    n = n.replace(/\s/g, "").replace(/[.,][0-9]{2}$/, "");
    const d = n.replace(/[^0-9]/g, "");
    if (d.length > best.length) best = d;
  }
  return best ? (best.replace(/^0+/, "") || "0") : "";
}
function normRead(name, text) {
  if (text == null) return null;
  text = String(text);
  if (name === "amount") return amountDigits(text);
  const found = canonicalAddresses(text);
  if (found.length) return found.join(",");
  return text.normalize("NFC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}
const FIELDS = ["amount", "address"];
function readOf(e, side) { return ((e && e.read) || {})[side] || {}; }
// "diff" | "unread" | "" for one field of a verify.result
function fieldState(e, n) {
  const a = readOf(e, "approved"), x = readOf(e, "executed");
  const anyRead = Object.keys(a).length || Object.keys(x).length;
  if (anyRead) {
    if (x[n] == null) return "unread";
    return normRead(n, a[n]) !== normRead(n, x[n]) ? "diff" : "";
  }
  // neither side has read values (old events, fixtures): the hashes are all there is
  return (e.approved || {})[n] !== (e.executed || {})[n] ? "diff" : "";
}
function diffFields(e) { return FIELDS.filter(n => fieldState(e, n) === "diff"); }
function cannotReason(e) {
  if (e.reason) return e.reason;
  const miss = FIELDS.filter(n => fieldState(e, n) === "unread");
  return miss.length ? `could not read the ${miss.join(" and ")} on the screen` : "the pixels could not be read with confidence";
}
// The verdict of F8 over the run's verify.result events (review, then result).
// An event without `moment` is an older after-the-click one.
function verifyOutcome(r) {
  const vs = (r && r.verifies) || [];
  const last = f => { for (let i = vs.length - 1; i >= 0; i--) if (f(vs[i])) return vs[i]; return null; };
  const review = last(e => e.moment === "review"), result = last(e => e.moment !== "review");
  const bad = review && review.status !== "match" ? review : (result && result.status !== "match" ? result : null);
  if (bad) {
    const kind = bad.status === "cannot_verify" ? "cannot" : (bad === review ? "blocked" : "flagged");
    return { kind, moment: bad === review ? "review" : "result", event: bad, review, result };
  }
  if (result) return { kind: "verified", moment: "result", event: result, review, result };
  if (review) return { kind: "reviewed", moment: "review", event: review, review, result };
  return { kind: null, event: null, review, result };
}

function wave(state, n) {
  let bars = "";
  for (let i = 0; i < (n || 42); i++) {
    const h = 8 + Math.round(28 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.45)));
    bars += `<i style="height:${h}px;animation-delay:${(i % 9) * 0.08}s"></i>`;
  }
  return `<div class="wave ${state}" aria-hidden="true">${bars}</div>`;
}

function shot(r, frame, regions, check) {
  const f = r.frames[frame] || {};
  const img = f.image
    ? `<img src="${runUrl(f.image)}" alt="Captured screen, frame ${esc(frame)}">`
    : `<div class="noimg"><span>No screenshot in this event</span><span class="mono">frame ${esc(frame == null ? "—" : frame)}</span></div>`;
  const extra = check ? (check.pixels_only_text || []).map(t => t.toLowerCase()) : [];
  const boxes = (regions || []).map(g => {
    const [x0, y0, x1, y1] = g.box;
    const text = (g.text || "").toLowerCase();
    let cls = "";
    if (!REQUIRED.includes(g.label) || (text && extra.some(t => t.includes(text) || text.includes(t)))) cls = "diverge";
    else if (g.confidence < 0.5) cls = "low";
    const style = `left:${x0 / SHOT_W * 100}%;top:${y0 / SHOT_H * 100}%;` +
                  `width:${(x1 - x0) / SHOT_W * 100}%;height:${(y1 - y0) / SHOT_H * 100}%`;
    const conf = g.confidence == null ? "" : " · " + Number(g.confidence).toFixed(2);
    return `<div class="box ${cls}" style="${style}"><span>${esc(g.label)}${conf}</span></div>`;
  }).join("");
  return `<div class="shot">${img}${boxes}</div>`;
}

function logLine(e) {
  switch (e.type) {
    case "run.started": return [ICON.dot, "info", "Run started", `${e.mode === "no_supervisor" ? "no supervisor" : "supervised"} · ${e.scenario || ""}`];
    case "frame.captured": return [ICON.eye, "info", "Screen captured", `frame ${e.frame} · ${short(e.sha256)}`];
    case "agent.step": return [ICON.dot, "info", e.label, e.detail];
    case "check.result":
      if (e.status === "ok") return [ICON.check, "ok", "Checked in pixels: ok", `${e.latency_ms} ms`];
      if (e.status === "cannot_verify") return [ICON.ask, "warn", "Cannot verify · blocked", e.reason];
      return [ICON.stop, "bad", e.status === "divergence" ? "Divergence · blocked" : "Policy violation · blocked", e.reason];
    case "approval.requested": return [ICON.pause, "warn", "Approval requested", `${cop(e.amount_cop)} → ${e.address}`];
    case "approval.granted": return isGranted(e)
      ? [ICON.check, "ok", "Approved · voice + passkey", e.voice_transcript]
      : [ICON.stop, "bad", e.voice_match ? "Not approved · denied" : "Voice did not match · denied", e.voice_transcript];
    case "order.confirmed": return [ICON.coin, "info", "Portal recorded a confirmed order", `${cop(e.amount_cop)} → ${e.address}`];
    case "verify.result": {
      const review = e.moment === "review";
      if (e.status === "match") return [ICON.check, "ok", review ? "Review screen matches the approval" : "Verified after the click",
                                        review ? "re-read before confirming" : "executed = approved"];
      if (e.status === "cannot_verify") return [ICON.ask, "warn", review ? "Could not verify the review · blocked" : "Could not verify the result · flagged",
                                                 cannotReason(e)];
      return review ? [ICON.stop, "bad", "Blocked at review", "order not confirmed: " + diffFields(e).join(", ") + " changed"]
                    : [ICON.stop, "bad", "Mismatch after the click", "flagged for review"];
    }
    case "explain.result": return [ICON.eye, "info", "Explained after the run",
      e.status === "none" ? "nothing found" : `${e.status.replace(/_/g, " ")} · ${e.reason || ""}`];
    case "receipt.signed": return isPlaceholder(e.signature)
      ? [ICON.warn, "warn", "Receipt built · not signed yet", e.id]
      : [ICON.seal, "ok", "Receipt signed", e.id];
  }
  return [ICON.dot, "info", e.type, ""];
}
function timeline(r) {
  if (!r.log.length) return `<p class="muted small" style="padding:16px">No events yet.</p>`;
  return `<ol class="timeline">${r.log.map(e => {
    const [ic, cls, lbl, det] = logLine(e);
    return `<li><span class="ic ${cls}">${ic}</span><div><div class="lbl">${esc(lbl)}</div>` +
           (det ? `<div class="det">${esc(det)}</div>` : "") + `</div><time>${esc(time(e.ts))}</time></li>`;
  }).join("")}</ol>`;
}

// `note` says where readText comes from when there is no crop image to show;
// `state` is "" | "diff" | "unread" (true means "diff"); `readUnder` is the
// value read from the pixels, shown under the crop image when there is one.
function crop(label, image, readText, hash, state, note, readUnder) {
  const cls = state === true || state === "diff" ? " diff" : state === "unread" ? " unread" : "";
  const px = image
    ? `<div><img src="${runUrl(image)}" alt="${esc(label)} crop">${readUnder != null ? `<div class="note">read: <span class="mono">${esc(readUnder)}</span></div>` : ""}</div>`
    : `<div><div class="read">${esc(readText || "—")}</div><div class="note">${esc(note || "read from pixels · crop image not in this event")}</div></div>`;
  return `<div class="crop${cls}"><div class="lbl">${esc(label)}</div>` +
         `<div class="px">${px}</div><div class="hash">sha256 ${esc(short(hash))}</div></div>`;
}

// view 1, live: record -> Voice -> policy/compile.py -> draft -> sign and use
function ruleList(x) {
  return `<ul class="mrules">${x.deliver_only.map(d => `<li><span class="k">Deliver only to</span> ${esc(d.name)} <span class="mono">· ${esc(d.address)}</span></li>`).join("")}
    <li><span class="k">Max per order</span> ${esc(cop(x.max_per_order_cop))}</li>
    <li><span class="k">Ask before</span> ${esc(String(x.ask_before).replace(/_/g, " "))}</li></ul>`;
}
function mandateLive(p) {
  const m = S.mandate, st = m.state;
  const chipFor = {
    idle: chip("off", ICON.mic, "Not recording"),
    starting: chip("warn", ICON.mic, "Allow the microphone…"),
    recording: chip("warn", ICON.mic, "Recording…"),
    transcribing: chip("warn", ICON.pause, "Transcribing and compiling…"),
    draft: chip("info", ICON.file, "Draft · not signed"),
    refused: chip("bad", ICON.stop, "Refused · nothing changed"),
    signing: chip("warn", ICON.pause, "Signing…"),
    signed: chip("ok", ICON.seal, "Signed · in use"),
  }[st];
  const recording = st === "starting" || st === "recording";
  const busy = recording || st === "transcribing" || st === "signing";
  const recBtn = recording
    ? `<button class="btn rec on" id="mstop" type="button">${ICON.dot} ${st === "starting" ? "Cancel" : "Stop"}</button>`
    : `<button class="btn rec" id="mrec" type="button" ${busy ? "disabled" : ""}>${ICON.mic} ${st === "idle" ? "Record mandate" : "Record again"}</button>`;
  let body = "";
  if (st === "draft" || st === "signing") {
    const d = m.draft;
    body = `<div class="mcompare">
        <div class="panel mside draft"><div class="h">Draft from your voice · not signed</div>
          <div class="q">“${esc(d.transcript)}”</div>${ruleList(d)}
          <div class="muted small">Address from the shop profile (simulated). ${d.ask_before_said ? "" : "“Ask before” was not said: default."}</div></div>
        <div class="panel mside"><div class="h">Signed policy in use now</div>
          <div class="q">“${esc(p.transcript)}”</div>${ruleList(p)}
          <div class="muted small mono">sha256 ${esc(p.short_sha)}</div></div>
      </div>
      <div class="vctl"><button class="passkey" id="msign" type="button" ${st === "signing" ? "disabled" : ""}>${ICON.seal} Sign and use</button>
        <button class="btn" id="mdiscard" type="button" ${st === "signing" ? "disabled" : ""}>Discard</button>
        <span class="muted small">Signed with the owner key on this machine; the agent then enforces it.</span></div>`;
  } else if (st === "refused") {
    body = `<div class="alert mrefused">${ICON.stop}<div><div class="t">Mandate refused · nothing was signed and the policy did not change</div>
        <div class="s">${esc(m.reason)}</div>${m.transcript ? `<div class="s">Heard: “${esc(m.transcript)}”</div>` : ""}</div></div>`;
  } else if (st === "signed") {
    body = `<div class="notice ok mdone">${ICON.seal}<div><b>Signed and in use.</b> The agent now enforces this policy
        (sha256 <span class="mono">${esc(p.short_sha)}</span>, ${esc(p.path)}). The committed demo policy is unchanged.</div></div>`;
  } else if (st === "transcribing") {
    body = `<div class="transcript wait">Sending to Voice Transcribe, then compiling the rules…</div>`;
  } else if (recording) {
    body = `${wave(st === "recording" ? "live" : "idle")}<div class="transcript wait">Say the limits, for example: “Solo pide con entrega en la tienda, máximo ciento cincuenta mil pesos por pedido”.</div>`;
  }
  const err = m.error ? `<div class="verr">${ICON.warn}<span>${esc(m.error)}</span></div>` : "";
  return `<div class="panel mlive" id="mlive"><header><span class="t">${ICON.mic.replace("<svg", '<svg width="16" height="16"')} Say a new mandate</span>
      <span class="r">${chipFor}</span></header>
    <div class="body">${body}<div class="vctl">${recBtn}<span class="muted small">Up to ${MAX_REC_S} s · the audio is not kept · a refused mandate changes nothing</span></div>${err}</div></div>`;
}

// view 3: a zoom on one region of a captured frame, cut by CSS from the frame image
function zoom(r, frame, box, label) {
  const f = r.frames[frame] || {};
  const pad = 10;
  const x0 = Math.max(0, box[0] - pad), y0 = Math.max(0, box[1] - pad);
  const x1 = Math.min(SHOT_W, box[2] + pad), y1 = Math.min(SHOT_H, box[3] + pad);
  const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
  if (!f.image) return `<div class="zoom noimg"><span>No screenshot for frame ${esc(frame)}</span></div>`;
  const px = w < SHOT_W ? x0 / (SHOT_W - w) * 100 : 0, py = h < SHOT_H ? y0 / (SHOT_H - h) * 100 : 0;
  const style = `background-image:url('${runUrl(f.image)}');background-size:${SHOT_W / w * 100}% auto;` +
                `background-position:${px}% ${py}%;aspect-ratio:${w} / ${h}`;
  return `<div class="zoom" role="img" aria-label="${esc(label)}" style="${style}"></div>`;
}
// view 3: what TESTIGO+ would have seen, computed once after the run (agent.run --explain)
function explainPanel(r) {
  const x = r.explain;
  if (!x) return "";
  const lines = x.regions.filter(g => g.label === "divergent text");
  const addr = x.regions.find(g => g.label === "address");
  const targets = lines.length ? lines : (x.status === "policy_violation" && addr ? [addr] : []);
  const zooms = targets.map(g => `<figure class="zfig">${zoom(r, x.frame, g.box, g.text || g.label)}
      <figcaption><span class="mono">${esc(g.text || "")}</span><span class="muted small"> · ${g.label === "divergent text" ? "on screen · not in the page code" : "delivery address on screen"}</span></figcaption></figure>`).join("");
  const hidden = x.code_only_text.map(t => `<div class="line diff">${esc(t)}<span class="tag">in the page code · not on screen</span></div>`).join("");
  const painted = x.pixels_only_text.filter(t => !lines.some(g => g.text === t))
    .map(t => `<div class="line diff">${esc(t)}<span class="tag">on screen · not in the page code · not located</span></div>`).join("");
  const verdict = x.status === "none" ? chip("off", ICON.dot, "Nothing found on this frame")
    : x.status === "policy_violation" ? chip("bad", ICON.stop, "Would break the policy")
    : chip("bad", ICON.stop, x.pixels_only_text.length ? "Text painted on screen, not in the page code" : "Hidden text in the page code");
  return `<div class="panel explain" id="explain"><header><span class="t">${ICON.eye.replace("<svg", '<svg width="16" height="16"')} What the agent was looking at</span>
      <span>frame ${esc(x.frame)}</span><span class="r">${verdict}</span></header>
    <div class="xgrid"><div>${shot(r, x.frame, x.regions, null)}</div>
      <div class="xside">${zooms}${hidden}${painted}${x.reason ? `<div class="why">${esc(x.reason)}</div>` : ""}</div></div>
    <div class="xcap">${ICON.warn}<span>Computed after the run, for explanation only. During the run the pixel channel did not run,
      nothing was checked or blocked, and the outcome above is what happened.</span></div></div>`;
}

// -- views ---------------------------------------------------------------
const render = {
  cover() {
    return `<div class="cover">
      <div class="big">${ICON.seal}<span>TESTIGO<b>+</b></span></div>
      <h2>The witness for your AI agent</h2>
      <p>What the agent asked, what you approved, what executed — checked in pixels.</p>
      <div class="triad">
        <div class="s"><div class="c">${ICON.eye}</div>Agent asked</div><div class="j"></div>
        <div class="s"><div class="c">${ICON.user}</div>You approved</div><div class="j"></div>
        <div class="s"><div class="c">${ICON.coin}</div>It executed</div>
      </div>
      <div class="sim">Simulation only · simulated shop, supplier and addresses · no real brands</div>
    </div>`;
  },

  mandate() {
    const p = S.policy;
    if (!p) return empty("Loading the signed policy…");
    const sealOk = p.hash_ok && p.signed && p.signature_valid !== false;
    const sigText = p.signature_valid === true ? "signature valid"
      : p.signature_valid === false ? "signature INVALID" : "signature present · key not on this machine";
    return `<h1 class="title">What your agent may do</h1>
      <p class="lede">The owner says the limits out loud. TESTIGO+ compiles them into a signed policy the agent cannot change.</p>
      <div class="mandate">
        <div class="panel mic">
          <div class="c">${ICON.mic}</div>
          <div class="muted small">Recorded mandate · ${esc(p.source || "voice")} · ${esc(p.owner)}</div>
          ${wave("", 48)}
          <div class="q">“${esc(p.transcript)}”</div>
        </div>
        <div class="rules">
          ${p.deliver_only.map(x => `<div class="panel rule"><div class="ic">${ICON.user}</div><div>
            <div class="k">Deliver only to</div><div class="v">${esc(x.name)} <span class="mono">· ${esc(x.address)}</span></div>
            <div class="muted small">from the shop profile · simulated</div></div></div>`).join("")}
          <div class="panel rule"><div class="ic">${ICON.coin}</div><div>
            <div class="k">Max per order</div><div class="v">${esc(cop(p.max_per_order_cop))}</div></div></div>
          <div class="panel rule"><div class="ic">${ICON.ask}</div><div>
            <div class="k">Ask before</div><div class="v">${esc(String(p.ask_before).replace(/_/g, " "))}</div></div></div>
          <div class="seal${sealOk ? "" : " bad"}">${sealOk ? ICON.seal : ICON.stop}<div>
            <div class="t">${sealOk ? "Signed policy" : "Policy not trusted"}</div>
            <div class="s mono">sha256 ${esc(p.short_sha)} · hash ${p.hash_ok ? "ok" : "MISMATCH"} · ${esc(sigText)} · ${esc(p.signed_by)}</div>
            <div class="s muted small" id="policysrc">In use: ${esc(p.path || "")}${p.active === "signed_here" ? " · signed in this interface" : " · committed demo policy"}</div>
          </div></div>
        </div>
      </div>${mandateLive(p)}`;
  },

  agent() {
    const r = S.runs.supervised;
    const st = r.mode ? agentState(r) : null;
    return `<h1 class="title">The agent at work</h1>
      <p class="lede">Wonder restocks the shop on the supplier portal. TESTIGO+ watches every screen before an action runs.</p>
      <div class="split">
        <div class="panel"><header><span class="t">Supplier portal</span><span>${r.lastFrame != null ? "frame " + esc(r.lastFrame) : ""}</span>
          <span class="r mono">${esc(r.lastFrame != null ? short((r.frames[r.lastFrame] || {}).sha) : "")}</span></header>
          ${r.mode ? shot(r, r.lastFrame, []) : `<div class="body">${empty("Waiting for a supervised run", "Start the agent; its steps appear here.")}</div>`}
        </div>
        <div class="panel"><header><span class="t">TESTIGO+</span>
          <span class="r">${st ? chip(st.cls, st.icon, st.cls === "ok" ? "Watching" : st.text) : ""}</span></header>
          ${timeline(r)}
        </div>
      </div>`;
  },

  nosup() {
    const r = S.runs.no_supervisor;
    if (!r.mode) return `<h1 class="title">Without TESTIGO+</h1><p class="lede">The same task with the supervisor switched off.</p>` +
      empty("No unsupervised run yet", "Run the agent with --no-supervisor to show the “before”.");
    const order = r.order;
    const allowed = allowedAddresses();
    const wrong = order && allowed.length && !allowed.includes(normRead("address", order.address));
    let alert = "";
    if (order && wrong) {
      alert = `<div class="alert">${ICON.stop}<div><div class="t">Order confirmed for delivery to ${esc(order.address)} — ${esc(cop(order.amount_cop))}</div>
        <div class="s">Not the shop's address in the owner's policy: the goods go to the attacker. Nothing checked what the agent saw before it clicked.</div></div></div>`;
    } else if (order) {
      alert = `<div class="alert neutral">${ICON.coin}<div><div class="t">Order confirmed for delivery to ${esc(order.address)} — ${esc(cop(order.amount_cop))}</div>
        <div class="s">The order went to an allowed address in this run. It is recorded as it happened.</div></div></div>`;
    }
    return `<h1 class="title">Without TESTIGO+</h1>
      <p class="lede">The same task with the supervisor switched off. Scenario <span class="mono">${esc(r.scenario)}</span>.</p>
      <div class="split">
        <div class="panel"><header><span class="t">Supplier portal</span>${chip("off", ICON.warn, "No supervisor")}
          <span class="r mono">${r.lastFrame != null ? "frame " + esc(r.lastFrame) : ""}</span></header>${shot(r, r.lastFrame, [])}</div>
        <div class="panel"><header><span class="t">What happened</span></header>${timeline(r)}</div>
      </div>${alert}${explainPanel(r)}`;
  },

  diverge() {
    const r = S.runs.supervised, c = r.check;
    const head = `<h1 class="title">What the page code says vs. what the pixels show</h1>
      <p class="lede">An independent pixel channel reads the screen. If it disagrees with the page code, or cannot read it, the action is blocked before the click.</p>`;
    if (!c) return head + empty("No check yet", "The first action the agent proposes is checked here.");
    let verdict, why = c.reason || "";
    const codeOnly = c.code_only_text || [], pxOnly = c.pixels_only_text || [];
    if (c.status === "ok") verdict = chip("ok", ICON.check, "Code and pixels agree", true);
    else if (c.status === "cannot_verify") verdict = chip("warn", ICON.ask, "Cannot verify — blocked until a human checks", true);
    else if (c.status === "policy_violation") verdict = chip("bad", ICON.stop, "Policy violation — blocked", true);
    else verdict = chip("bad", ICON.stop, pxOnly.length ? "Mismatch: visible text not in page code" : "Mismatch: hidden text in page code", true);
    const col = (lines, tag) => lines.length
      ? lines.map(t => `<div class="line diff">${esc(t)}<span class="tag">${esc(tag)}</span></div>`).join("")
      : `<div class="line muted">No text missing from the other side</div>`;
    const blocked = c.status !== "ok";
    return head + `<div class="split">
      <div class="panel"><header><span class="t">Captured screen</span><span>frame ${esc(c.frame)}</span>
        <span class="r">${chip("info", ICON.eye, (c.regions || []).length + " regions found")}</span></header>${shot(r, c.frame, c.regions, c)}</div>
      <div class="panel">
        <div class="verdict">${verdict}${why ? `<div class="why">${esc(why)}</div>` : ""}
          ${c.status === "cannot_verify" ? `<button class="passkey" disabled style="margin-top:14px">${ICON.ask} Ask a human</button>` : ""}</div>
        <div class="cols">
          <div><h3>What the page code says</h3>${col(codeOnly, "in the page code · not on screen")}</div>
          <div><h3>What the pixels show</h3>${col(pxOnly, "on screen · not in the page code")}</div>
        </div>
        <div class="foot"><span>Pixel check ${esc(c.latency_ms)} ms</span>
          <span>${blocked ? "Action blocked before the click" : (r.approval ? "Order sent to the person for approval" : "Action allowed")}</span></div>
      </div></div>`;
  },

  approve() {
    const r = S.runs.supervised, a = r.approval, g = r.granted;
    const head = `<h1 class="title">Approve what will really happen</h1>
      <p class="lede">Exact crops of the screen — not the agent's summary. Read them aloud, then approve.</p>`;
    if (!a) return head + empty("No approval requested", "An order that passes every check stops here for the person before it is confirmed.");
    const d = deskFor(a), voice = d && d.voice;
    const img = Object.assign({}, (d && d.images) || {}, a.images || {});
    const rec = S.rec.state;
    // the loop's answer when it exists; before that, the service's record
    let state = "wait";
    if (g) state = isGranted(g) ? "approved" : (g.voice_match ? "refused" : "nomatch");
    else if (d && d.decision) state = d.decision === "approve" ? "sending" : "refused";
    else if (voice && rec === "idle") state = voice.match ? "match" : "nomatch";   // a new take hides the old one
    const vchip = {
      approved: chip("ok", ICON.check, "Approved"),
      match: chip("ok", ICON.check, "Matches the screen"),
      sending: chip("ok", ICON.check, "Approved · sent to the run"),
      nomatch: chip("bad", ICON.stop, "Does not match the screen"),
      refused: chip("bad", ICON.stop, g && g.voice_match ? "Matches · not approved" : "Denied"),
      wait: rec === "starting" ? chip("warn", ICON.mic, "Allow the microphone…")
        : rec === "recording" ? chip("warn", ICON.mic, "Recording…")
        : rec === "sending" ? chip("warn", ICON.pause, "Transcribing…")
        : chip("warn", ICON.pause, "Waiting for voice"),
    }[state];
    const transcript = g ? g.voice_transcript : (voice && rec === "idle" ? voice.transcript : "");
    const waitText = rec === "recording" ? "Listening… press Stop when done."
      : rec === "sending" ? "Sending to Voice Transcribe…" : rec === "starting" ? "Waiting for the browser to hand over the microphone…"
      : d ? "Press Record and read the total and the destination aloud." : "No voice yet.";
    const heard = transcript ? `<div class="transcript">“${esc(transcript)}”</div>`
      : `<div class="transcript wait">${esc(waitText)}</div>`;
    let diff = "";
    if (state === "nomatch" && !g && voice) {
      const lines = [];
      if (voice.negated && voice.negated.length) lines.push(`Heard “${esc(voice.negated.join(" "))}”: a no or a cancel is never an approval`);
      else if (!voice.amount_match) lines.push(voice.heard_amount == null
        ? `Amount: ${esc(voice.amount_reason || "none heard")} · screen ${esc(cop(a.amount_cop))}`
        : `Amount heard ${esc(cop(voice.heard_amount))} · screen ${esc(cop(a.amount_cop))}`);
      if (!voice.address_match) lines.push(`Destination “${esc(voice.address_name)}” not heard`);
      diff = `<div class="vdiff">${lines.map(l => `<div>${ICON.stop}<span>${l}</span></div>`).join("")}</div>`;
    }
    // the run is waiting for this person. Once the run's answer for this approval
    // arrives (e.g. denied on timeout even if its closing POST failed and the
    // service still shows the approval pending), nothing is offered any more.
    const open = !g && !!d && !d.decision;
    const busy = rec !== "idle" || S.deskBusy;
    let controls = "";
    if (open) {
      const recBtn = rec === "recording" || rec === "starting"
        ? `<button class="btn rec on" id="vstop" type="button">${ICON.dot} ${rec === "starting" ? "Cancel" : "Stop"}</button>`
        : `<button class="btn rec" id="vrec" type="button" ${busy ? "disabled" : ""}>${ICON.mic} ${voice ? "Record again" : "Record"}</button>`;
      const meta = voice
        ? `Attempt ${esc(d.attempts)} · Voice Transcribe ${esc(voice.latency_ms == null ? "—" : Math.round(voice.latency_ms) + " ms")}`
        : `Up to ${MAX_REC_S} s · the audio is not kept`;
      controls = `<div class="vctl">${recBtn}<span class="muted small">${meta}</span></div>`;
    } else if (!g && !d) {
      controls = `<div class="vctl"><span class="muted small">${S.deskChecked
        ? "This approval is not open in the interface (the run asks in its terminal, or these are test events)."
        : "Connecting to the approval…"}</span></div>`;
    }
    const err = S.rec.error ? `<div class="verr">${ICON.warn}<span>${esc(S.rec.error)}</span></div>` : "";
    const canApprove = open && voice && voice.match && !busy;
    const done = state === "approved" || state === "sending";
    const approveLabel = state === "approved"
      ? ICON.check + (g.method === "passkey" ? " Approved with passkey" : " Approved · voice + click")
      : state === "sending" ? ICON.check + " Approved · waiting for the run" : ICON.check + " Approve";
    const why = g && !isGranted(g) && d && d.reason && sameApproval(d.event, a) ? " · " + esc(d.reason) : "";
    const stamp = g ? `<div class="vstamp ${isGranted(g) ? "ok" : "bad"}">${isGranted(g) ? "Approved" : "Not approved"} at ${esc(time(g.ts))}${why}</div>` : "";
    return head + `<div class="capsule">
      <div class="crops">
        ${crop("Amount", img.amount, cop(a.amount_cop), a.crops.amount)}
        ${crop("Deliver to", img.address, a.address, a.crops.address)}
      </div>
      <div class="voice">
        <div class="head">${ICON.mic} Read aloud to confirm ${vchip}</div>
        ${wave(rec === "recording" ? "live" : (state === "match" || done ? "" : "idle"))}
        ${heard}${diff}${controls}${err}
      </div>
      <div class="decide">
        <button class="passkey${done ? " done" : ""}" id="vapprove" ${canApprove ? "" : "disabled"} type="button">${approveLabel}</button>
        <button class="btn deny" id="vdeny" ${open && !busy ? "" : "disabled"} type="button">${ICON.stop} Deny</button>
      </div>${stamp}
      <div class="fine">Your voice confirms the intent: the total and where the order goes, checked against the pixels.
        It does not prove who you are; a passkey would, and it is optional (R8) and not used here.</div>
    </div>`;
  },

  after() {
    const r = S.runs.supervised, vo = verifyOutcome(r), v = vo.event;
    const head = `<h1 class="title">Checked again before and after the click</h1>
      <p class="lede">What is about to execute, and what executed, is read again in pixels and compared with what was approved.</p>`;
    if (!v) return head + empty("Nothing to compare yet", "After an approved order, the review screen and the result are compared here.");
    const review = v.moment === "review";
    const im = v.images || {}, ia = im.approved || {}, ie = im.executed || {};
    const ra = readOf(v, "approved"), rx = readOf(v, "executed");
    const a = r.approval || {};
    const shown = (n, side) => {
      const rd = side === "approved" ? ra : rx;
      if (rd[n] != null) return n === "amount" && /^\d+$/.test(String(rd[n])) ? cop(rd[n]) : rd[n];
      if (side === "approved") return n === "amount" ? cop(a.amount_cop) : a.address;
      return null;
    };
    const cell = (n, side) => {
      const st = side === "executed" ? fieldState(v, n) : "";
      const txt = shown(n, side);
      const note = st === "diff" ? "read from the pixels · differs from what was approved"
        : st === "unread" ? "could not be read on this screen"
        : side === "approved" ? "read from the pixels when approved" : "read from the pixels · same as approved";
      return crop(n === "amount" ? "Amount" : "Deliver to", (side === "approved" ? ia : ie)[n],
                   txt == null ? "—" : txt, (side === "approved" ? v.approved : v.executed)[n], st, note, txt);
    };
    const mchip = e => !e ? chip("off", ICON.dot, "not reached")
      : e.status === "match" ? chip("ok", ICON.check, "Match")
      : e.status === "cannot_verify" ? chip("warn", ICON.ask, "Could not verify")
      : chip("bad", ICON.stop, "Mismatch");
    const moments = `<div class="moments">
        <div><span class="muted small">1 · Review screen, before confirming</span>${mchip(vo.review)}</div>
        <div><span class="muted small">2 · Result, after the click</span>${vo.kind === "blocked" || (vo.kind === "cannot" && review)
          ? chip("off", ICON.dot, "never happened") : mchip(vo.result)}</div></div>`;
    const order = r.order;
    const record = order ? `<div class="muted small" style="margin-top:8px">Portal record: ${esc(cop(order.amount_cop))} → <span class="mono">${esc(order.address)}</span></div>` : "";
    const diffs = diffFields(v);
    let stamp, verdict;
    if (vo.kind === "blocked") {
      stamp = `<span class="stamp bad">${ICON.stop}Blocked at review</span>`;
      verdict = `${chip("bad", ICON.stop, "Order not confirmed", true)}
        <div class="why">The review screen did not show what you approved (${esc(diffs.join(" and ") || "a field")} changed). The confirm click never happened.</div>`;
    } else if (vo.kind === "flagged") {
      stamp = `<span class="stamp bad">${ICON.stop}MISMATCH</span>`;
      verdict = `${chip("bad", ICON.stop, "Flagged for review", true)}
        <div class="why">What executed is not what you approved (${esc(diffs.join(" and ") || "a field")}). The receipt is marked.</div>${record}`;
    } else if (vo.kind === "cannot") {
      stamp = `<span class="stamp warn">${ICON.ask}Could not verify</span>`;
      verdict = `${chip("warn", ICON.ask, review ? "Order not confirmed" : "Flagged for review", true)}
        <div class="why">${esc(cannotReason(v))}. ${review ? "Without a clear match the confirm click is not made." : "The receipt is marked for a person to check."}</div>${review ? "" : record}`;
    } else if (vo.kind === "verified") {
      stamp = `<span class="stamp ok">${ICON.check}VERIFIED</span>`;
      verdict = `${chip("ok", ICON.check, "Order confirmed", true)}
        <div class="why">Executed = approved, read in pixels${vo.review ? " on the review screen and after the click" : " after the click"}.</div>${record}`;
    } else {
      stamp = `<span class="stamp info">${ICON.pause}Review matches</span>`;
      verdict = `${chip("info", ICON.pause, "Confirming · waiting for the result", true)}`;
    }
    return head + moments + `<div class="after">
        <div><h2>Approved</h2><div class="stack">${cell("amount", "approved")}${cell("address", "approved")}</div></div>
        <div><h2>${review ? "On the review screen" : "Executed"}</h2><div class="stack">${cell("amount", "executed")}${cell("address", "executed")}</div></div>
      </div>
      <div class="outcome">${stamp}<div>${verdict}</div></div>`;
  },

  receipt() {
    const head = `<h1 class="title">A signed receipt anyone can check</h1>
      <p class="lede">The receipt binds the policy, the approved crops and the executed crops. Verify it without trusting us.</p>`;
    const rc = S.receipt;
    if (rc === null) return head + empty("Loading the receipt…");
    if (rc && rc.error) return head + empty("No receipt yet", rc.error);
    const d = rc.receipt;
    const ev = S.runs.supervised.receipt;
    // Only a receipt.signed event with a path ties a file to this run.
    let stale = "";
    if (!(ev && ev.path)) {
      const why = !ev ? "This run has no receipt (it was blocked, or has not finished)."
        : isPlaceholder(ev.signature) ? "This run's receipt is an unsigned preview and was not written to runs/."
        : "This run's receipt was not written to runs/.";
      stale = `<div class="notice warn" style="margin:0 0 16px">${ICON.warn}<div><b>Not from this run.</b> ${esc(why)}
        Showing the newest receipt file under runs/, from ${esc(new Date(rc.modified * 1000).toLocaleString("en-US"))}.</div></div>`;
    }
    const blocked = d.status === "blocked";
    // by the values read from the pixels when the receipt has them (hashes of real captures differ)
    const diff = k => {
      if (blocked || !d.approved || !d.executed) return false;
      if (d.approved_read && d.executed_read) return normRead(k, d.approved_read[k]) !== normRead(k, d.executed_read[k]);
      return d.approved[k] !== d.executed[k];
    };
    const row = (k, v, cls) => `<dt>${esc(k)}</dt><dd class="${cls || ""}">${esc(v)}</dd>`;
    const vo = S.verify;
    let out = `<span class="p">$</span> testigo verify ${esc("runs/" + rc.path)}\n`;
    if (S.verifying) out += "\nrunning…";
    else if (vo) {
      const lines = vo.output.trimEnd().split("\n");
      const last = lines.pop();
      out += "\n" + lines.map(l => esc(l).replace(/✓/g, '<span class="y">✓</span>').replace(/✗/g, '<span class="n">✗</span>')).join("\n") +
        `<span class="last ${vo.exit_code === 0 ? "y" : "n"}">${esc(last)}</span>`;
    } else out += `\n<span style="color:#8B97A6">Press “Run verify” to run the real command.</span>`;
    const blockedNote = blocked ? `<div class="alert" style="margin:0 0 16px">${ICON.stop}<div><div class="t">Blocked at ${esc(d.blocked_at || "review")} — nothing executed</div>
        <div class="s">The approval is signed; the screen before confirming did not match it, so the order was never confirmed. Verify still checks the signature and the approved crops.</div></div></div>` : "";
    return head + stale + blockedNote + `<div class="split">
      <div class="panel receipt"><header><span class="t">${ICON.file.replace("<svg", '<svg width="16" height="16"')} receipt.json</span><span class="r">runs/${esc(rc.path)}</span></header>
        <dl>${row("id", d.id)}${row("time", d.time)}${row("agent", d.agent)}${row("action", d.action)}
          ${row("policy", short(d.policy_sha256))}
          ${row("approved", "amount " + short((d.approved || {}).amount) + " · address " + short((d.approved || {}).address))}
          ${row("status", blocked ? "blocked at " + (d.blocked_at || "review") + " — nothing executed" : (d.status || "confirmed"), blocked ? "diff" : "")}
          ${blocked || !d.executed ? row("executed", "— nothing executed", "muted")
            : row("executed", "amount " + short(d.executed.amount) + " · address " + short(d.executed.address), diff("amount") || diff("address") ? "diff" : "")}
          ${row("approval", ((d.approval || {}).method || "") + " · “" + ((d.approval || {}).voice_transcript || "") + "”")}
          ${row("signed by", d.signed_by || "")}${row("signature", d.signature)}</dl>
      </div>
      <div class="term"><header><i></i><i></i><i></i>&nbsp; terminal
        <button id="runverify" type="button" ${S.verifying ? "disabled" : ""}>Run verify</button></header><pre>${out}</pre></div>
    </div>`;
  },

  bench() {
    const b = S.bench;
    const head = `<div class="k">Orders delivered to the attacker</div>`;
    const lbls = `<div class="lbls"><span>without TESTIGO+</span><span>with TESTIGO+</span></div>`;
    if (!b) return `<div class="bench">${head}</div>`;
    const s = b.available && b.data && b.data.summary;
    const counted = x => x && Number.isFinite(x.succeeded) && Number.isFinite(x.runs);
    if (!s || !counted(s.attacks_succeed_without) || !counted(s.attacks_succeed_with)) {
      return `<div class="bench">${head}
        <div class="num none"><span>—</span><span class="arrow">→</span><span>—</span></div>${lbls}
        <div class="notice warn">${ICON.warn}<div><b>No WitnessBench results yet.</b> This view reads
        <span class="mono">runs/bench_results.json</span>, written by the real WitnessBench runs. Numbers are never typed in by hand.</div></div></div>`;
    }
    const wo = s.attacks_succeed_without, wi = s.attacks_succeed_with;
    const of = x => `${esc(x.succeeded)} of ${esc(x.runs)}`;
    const LABEL = { a1: "Hidden text in page code", a2: "Text painted in an image", a3: "Change after approval" };
    const bar = (lbl, cls, x) => {
      const w = counted(x) && x.runs > 0 ? x.succeeded / x.runs * 100 : 0;
      return `<div class="bar"><span>${lbl}</span><div class="track"><div class="fill ${cls}" style="width:${Math.max(0, Math.min(100, w))}%"></div></div>` +
             `<span class="pct">${counted(x) ? of(x) : "—"}</span></div>`;
    };
    const bars = Object.keys(LABEL).map(k => {
      const x = (s.by_attack || {})[k];
      if (!x) return "";
      return `<div class="g"><div class="t">${LABEL[k]} <span class="muted mono">${k}</span></div>${bar("without", "no", x.without)}${bar("with", "yes", x.with)}</div>`;
    }).join("");
    const fp = s.false_positives || {}, lat = s.added_latency_ms || {};
    const sec = ms => Number.isFinite(ms) ? (ms / 1000).toFixed(1) + " s" : "—";
    const fpText = Number.isFinite(fp.count) && Number.isFinite(fp.reached_check)
      ? `${esc(fp.count)} of ${esc(fp.reached_check)} clean runs that reached a check`
      : Number.isFinite(fp.count) && Number.isFinite(fp.clean_runs) ? `${esc(fp.count)} of ${esc(fp.clean_runs)} clean runs` : "—";
    const pc = s.per_check_latency_ms || {};
    const perCheck = Number.isFinite(pc.median) ? ` · per check <b>median ${esc(sec(pc.median))} · p90 ${esc(sec(pc.p90))}</b>` : "";
    const cb = s.clean_supervised;
    const n = x => Number.isFinite(x) ? x : 0;
    const cleanLine = cb && typeof cb === "object"
      ? `<div class="clean muted">Clean runs with TESTIGO+${Number.isFinite(fp.clean_runs) ? ` (${esc(fp.clean_runs)})` : ""}:
          ${esc(n(cb.delivered_to_shop))} delivered to the shop · ${esc(n(cb.blocked))} blocked${Array.isArray(cb.blocked_statuses) && cb.blocked_statuses.length ? ` <span class="mono">(${esc(cb.blocked_statuses.join(", "))})</span>` : ""}
          · ${esc(n(cb.flagged))} flagged · ${esc(n(cb.never_reached_confirm))} never reached the confirmation${n(cb.other) ? ` · ${esc(cb.other)} other` : ""}</div>` : "";
    const flaggedAfter = Number(s.delivered_but_flagged) > 0
      ? `<div class="flagged">${esc(s.delivered_but_flagged)} of the orders delivered to the attacker with TESTIGO+: delivered, flagged after (the order went out; the receipt says so).</div>` : "";
    const unapproved = Number(s.delivered_unapproved) > 0
      ? `<div class="flagged">${esc(s.delivered_unapproved)} delivered to the attacker without a check or approval.</div>` : "";
    const failed = Number(s.errors) > 0
      ? `<div class="notice warn">${ICON.warn}<div>${esc(s.errors)} run${s.errors === 1 ? "" : "s"} failed and ${s.errors === 1 ? "is" : "are"} left out (API or browser errors, not results).</div></div>` : "";
    const resisted = Number(s.agent_resisted_without_supervisor) > 0
      ? `<div class="resisted">${ICON.user}<span>Wonder refused ${esc(s.agent_resisted_without_supervisor)} attack${s.agent_resisted_without_supervisor === 1 ? "" : "s"} on its own, without TESTIGO+.</span></div>` : "";
    const edges = Array.isArray(s.edge_cases) && s.edge_cases.length
      ? `<div class="limits"><h3>Known limits</h3><ul>${s.edge_cases.map(x => {
          const out = x.delivered_to_attacker ? "delivered to the attacker" : x.blocked ? "blocked" : "not delivered to the attacker";
          return `<li><b>${esc(x.name || x.scenario || "edge case")}</b> <span class="mono muted">${esc([x.scenario, x.variant != null ? "v" + x.variant : "", x.mode].filter(Boolean).join(" · "))}</span> — ${esc(out)}${x.status ? " · " + esc(x.status) : ""}</li>`;
        }).join("")}</ul><div class="muted small">Counted apart; they never move the main number.</div></div>` : "";
    return `<div class="bench">${head}
      <div class="num"><span class="from">${esc(wo.succeeded)}<small> of ${esc(wo.runs)}</small></span><span class="arrow">→</span><span class="to">${esc(wi.succeeded)}<small> of ${esc(wi.runs)}</small></span></div>
      ${lbls}
      <div class="bars">${bars}</div>
      ${flaggedAfter}${unapproved}
      <div class="meta">False positives: <b>${fpText}</b> · TESTIGO+ time per run: <b>median ${esc(sec(lat.median))} · p90 ${esc(sec(lat.p90))}</b>${Number.isFinite(lat.n) && lat.n ? ` <span class="muted">(n=${esc(lat.n)})</span>` : ""}${perCheck}</div>
      ${cleanLine}${resisted}${failed}${edges}
    </div>`;
  },
};

// -- data the views read from files ----------------------------------------
async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const t = await r.json().catch(() => ({})); throw new Error(t.detail || r.statusText); }
  return r.json();
}
async function loadFor(i) {
  const key = VIEWS[i].key;
  try {
    if ((key === "mandate" || key === "nosup") && !S.policy) { S.policy = await getJSON("/api/policy"); draw(); }
    if (key === "bench") { S.bench = await getJSON("/api/bench"); draw(); }
    if (key === "approve") loadDesk();
    if (key === "receipt") {
      const ev = S.runs.supervised.receipt;
      const path = ev && ev.path ? ev.path : "";
      if (S.receiptFor !== path || !S.receipt) {
        forgetReceipt(); S.receiptFor = path; draw();
        const seq = S.loadSeq;
        let got;
        try { got = await getJSON("/api/receipt?path=" + encodeURIComponent(path)); }
        catch (err) { got = { error: err.message }; }
        if (seq !== S.loadSeq) return;          // a newer run or receipt replaced it
        S.receipt = got; draw();
      }
    }
  } catch (err) { console.error(err); }
}
async function runVerify() {
  if (!S.receipt || !S.receipt.path || S.verifying) return;
  const seq = S.loadSeq;
  S.verifying = true; draw();
  let got;
  try { got = await getJSON("/api/verify?path=" + encodeURIComponent(S.receipt.path), { method: "POST" }); }
  catch (err) { got = { output: "error: " + err.message, exit_code: 1 }; }
  S.verifying = false;
  if (seq === S.loadSeq) S.verify = got;     // only for the receipt still on screen
  draw();
}

// -- approval: voice + click (F7 with R8) ------------------------------------
// The service holds the approval the run is waiting on; it transcribes the
// audio and compares it with the pixels. The page only records and shows.
function sameApproval(x, a) {
  return !!x && !!a && x.ts === a.ts && x.amount_cop === a.amount_cop && x.address === a.address
    && !!x.crops && x.crops.amount === a.crops.amount && x.crops.address === a.crops.address;
}
function deskFor(a) { return S.desk && sameApproval(S.desk.event, a) ? S.desk : null; }
async function loadDesk() {
  try {
    const got = await getJSON("/api/approval");
    S.desk = got.approval; S.deskChecked = true;
  } catch (err) { console.error(err); }
  draw();
}
// the run posts approval.requested a moment before it opens the approval: look again
setInterval(() => {
  const r = S.runs.supervised;
  if (r.approval && !r.granted && !deskFor(r.approval) && S.rec.state === "idle") loadDesk();
}, 1500);

async function decide(decision) {
  const r = S.runs.supervised, d = deskFor(r.approval);
  if (!d || S.deskBusy || r.granted) return;      // the run already answered this approval
  S.deskBusy = true; S.rec.error = ""; draw();
  try {
    S.desk = await getJSON(`/api/approval/${encodeURIComponent(d.id)}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }) });
  } catch (err) { S.rec.error = err.message; }
  S.deskBusy = false; draw();
}

// the service refuses audio over 20 s: stop at 18 s, and trim to that when encoding
const MAX_REC_S = 18, WAV_RATE = 16000;
let mic = null;
// The microphone as raw PCM chunks; shared by view 5 (approval) and view 1 (mandate).
async function openMic(onTimeout) {
  const stream = await navigator.mediaDevices.getUserMedia(
    { audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  node.onaudioprocess = ev => chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
  src.connect(node); node.connect(ctx.destination);
  return { stream, ctx, src, node, chunks, timer: setTimeout(onTimeout, MAX_REC_S * 1000) };
}
// Release the microphone; returns the sample rate the chunks were taken at.
function closeMic(m) {
  clearTimeout(m.timer);
  try { m.src.disconnect(); m.node.disconnect(); } catch (e) { /* already closed */ }
  m.stream.getTracks().forEach(t => t.stop());
  const rate = m.ctx.sampleRate;
  m.ctx.close();
  return rate;
}
async function startRecording() {
  if (S.rec.state !== "idle") return;
  S.rec = { state: "starting", error: "" }; draw();     // until the browser hands over the mic
  try {
    mic = await openMic(() => stopRecording(false));
    if (S.rec.state !== "starting") { stopRecording(true); return; }   // cancelled, or the run decided
    S.rec = { state: "recording", error: "" }; draw();
  } catch (err) {
    if (S.rec.state === "starting") { S.rec = { state: "idle", error: "Microphone not available: " + err.message }; draw(); }
  }
}
async function stopRecording(discard) {
  const m = mic; mic = null;
  if (!m) {                                   // Stop before the mic arrived: cancel
    if (S.rec.state === "starting" || S.rec.state === "recording") { S.rec = { state: "idle", error: "" }; draw(); }
    return;
  }
  const rate = closeMic(m);
  if (discard) { S.rec = { state: "idle", error: "" }; draw(); return; }
  const d = deskFor(S.runs.supervised.approval);
  if (!d) { S.rec = { state: "idle", error: "The approval closed before the audio was sent." }; draw(); return; }
  S.rec = { state: "sending", error: "" }; draw();
  try {
    S.desk = await getJSON(`/api/approval/${encodeURIComponent(d.id)}/voice`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wav_base64: wavBase64(m.chunks, rate) }) });
    S.rec = { state: "idle", error: "" };
  } catch (err) {
    S.rec = { state: "idle", error: err.message };
  }
  draw();
}
// -- mandate: voice -> draft -> sign and use (view 1, F1 live) ----------------
let mmic = null;
function setMandate(x) { S.mandate = Object.assign({ state: "idle", draft: null, reason: "", transcript: "", error: "" }, x); draw(); }
async function startMandate() {
  const st = S.mandate.state;
  if (["starting", "recording", "transcribing", "signing"].includes(st)) return;
  setMandate({ state: "starting" });
  try {
    mmic = await openMic(() => stopMandate(false));
    if (S.mandate.state !== "starting") { stopMandate(true); return; }   // cancelled meanwhile
    setMandate({ state: "recording" });
  } catch (err) {
    if (S.mandate.state === "starting") setMandate({ error: "Microphone not available: " + err.message });
  }
}
async function stopMandate(discard) {
  const m = mmic; mmic = null;
  if (!m) { if (["starting", "recording"].includes(S.mandate.state)) setMandate({}); return; }
  const rate = closeMic(m);
  if (discard) { setMandate({}); return; }
  setMandate({ state: "transcribing" });
  await sendMandate(wavBase64(m.chunks, rate));
}
// the service transcribes and compiles; a refusal comes back as a normal answer
async function sendMandate(b64) {
  try {
    const got = await getJSON("/api/mandate/draft", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wav_base64: b64 }) });
    if (got.status === "refused") setMandate({ state: "refused", reason: got.reason, transcript: got.transcript || "" });
    else setMandate({ state: "draft", draft: got });
  } catch (err) { setMandate({ error: err.message }); }
}
async function signMandate() {
  const d = S.mandate.draft;
  if (!d || S.mandate.state !== "draft") return;
  setMandate({ state: "signing", draft: d });
  try {
    const p = await getJSON("/api/mandate/sign", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: d.id }) });
    S.policy = p;
    setMandate({ state: "signed" });
  } catch (err) { setMandate({ state: "draft", draft: d, error: err.message }); }
}

// Voice Transcribe takes WAV only: 16 kHz mono 16-bit PCM, encoded here.
function wavBase64(chunks, rate) {
  let n = 0; chunks.forEach(c => { n += c.length; });
  const pcm = new Float32Array(n); let o = 0;
  chunks.forEach(c => { pcm.set(c, o); o += c.length; });
  const ratio = rate / WAV_RATE, len = Math.min(Math.floor(n / ratio), MAX_REC_S * WAV_RATE);
  const buf = new ArrayBuffer(44 + len * 2), v = new DataView(buf);
  const str = (off, t) => { for (let i = 0; i < t.length; i++) v.setUint8(off + i, t.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + len * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, WAV_RATE, true); v.setUint32(28, WAV_RATE * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, len * 2, true);
  for (let i = 0; i < len; i++) {
    // average the source samples that fall in this output sample (a cheap low-pass)
    const a = Math.floor(i * ratio), b = Math.max(a + 1, Math.floor((i + 1) * ratio));
    let sum = 0; for (let j = a; j < b && j < n; j++) sum += pcm[j];
    const x = Math.max(-1, Math.min(1, sum / (b - a)));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// -- navigation and drawing --------------------------------------------------
function viewFromHash() {
  const n = parseInt((location.hash || "").replace(/\D/g, ""), 10);
  return Number.isInteger(n) && n >= 0 && n < VIEWS.length ? n : 0;
}
function go(i) {
  i = Math.max(0, Math.min(VIEWS.length - 1, i));
  if (location.hash !== "#/" + i) history.replaceState(null, "", "#/" + i);
  S.view = i; draw(); loadFor(i);
}
function follow(i) { if (S.auto) S.pendingView = i; }

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

function draw() {
  const r = runFor(S.view), st = agentState(r);
  document.getElementById("topbar").classList.toggle("off", r.mode === "no_supervisor");
  document.getElementById("runinfo").textContent = r.mode ? `${r.scenario || ""}${r.variant ? " v" + r.variant : ""}` : "";
  document.getElementById("agentstate").innerHTML = chip(st.cls, st.icon, st.text);
  document.getElementById("nav").innerHTML = VIEWS.map((v, i) =>
    `<a href="#/${i}" ${i === S.view ? 'aria-current="page"' : ""}><span class="n">${i || "·"}</span>${esc(v.name)}${hasNews(i) && i !== S.view ? '<span class="dot"></span>' : ""}</a>`).join("");
  const auto = document.getElementById("auto");
  auto.textContent = S.auto ? "Follow: on" : "Follow: off";
  auto.setAttribute("aria-pressed", String(S.auto));
  const conn = document.getElementById("conn");
  conn.className = "conn " + (S.conn === "live" ? "live" : S.conn === "down" ? "down" : "");
  conn.textContent = S.conn === "live" ? "Live" : S.conn === "down" ? "Reconnecting" : "Connecting";
  document.getElementById("testdata").hidden = !S.test;
  const v = document.getElementById("view");
  v.innerHTML = `<div class="wrap">${render[VIEWS[S.view].key]()}</div>` +
    `<div class="keys"><kbd>←</kbd><kbd>→</kbd> views · <kbd>0</kbd>–<kbd>8</kbd> jump · <kbd>A</kbd> follow</div>`;
  const btn = document.getElementById("runverify");
  if (btn) btn.onclick = runVerify;
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("vrec", startRecording); on("vstop", () => stopRecording(false));
  on("vapprove", () => decide("approve")); on("vdeny", () => decide("deny"));
  on("mrec", startMandate); on("mstop", () => stopMandate(false));
  on("msign", signMandate); on("mdiscard", () => setMandate({}));
}

// -- live events -------------------------------------------------------------
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
    } else {
      apply(e, follow);
    }
    if (S.pendingView !== undefined && S.pendingView !== S.view) go(S.pendingView);
    else {
      draw();
      const reload = ["receipt.signed", "hub.reset", "hub.history", "run.started"];
      if (VIEWS[S.view].key === "receipt" && reload.includes(e.type)) loadFor(S.view);
    }
  };
  ws.onclose = () => { S.conn = "down"; draw(); setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 8000); };
}

window.addEventListener("hashchange", () => go(viewFromHash()));
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "ArrowRight") go(S.view + 1);
  else if (e.key === "ArrowLeft") go(S.view - 1);
  else if (/^[0-8]$/.test(e.key)) go(Number(e.key));
  else if (e.key === "a" || e.key === "A") { S.auto = !S.auto; draw(); }
});
document.getElementById("auto").onclick = () => { S.auto = !S.auto; draw(); };

getJSON("/api/policy").then(p => { S.policy = p; draw(); }).catch(err => console.error(err));
go(S.view);
connect();
