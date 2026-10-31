"""The interceptor service: the interface (F11) and its event relay.

  make up        # starts this on INTERCEPTOR_PORT, next to the portal

Routes
  /                  the interface (ui/index.html; static files under /ui)
  /status, /health   the F0 status page and its JSON
  POST /events       the loop posts each event here (loopback only)
  POST /events/reset forget the stored events before a new recording
  GET  /events       the stored events, as JSON
  WS   /ws           history first, then every new event
  GET  /api/policy   the signed policy (view 1)
  GET  /api/receipt  the newest receipt.json under runs/, or ?path= (view 7)
  POST /api/verify   runs the real `testigo verify` on that receipt (view 7)
  GET  /api/bench    runs/bench_results.json, or "not available" (view 8)
  GET  /runs/<path>  screenshots and crops (PNG/JPEG only) from runs/

Approval (F7, view 5; see approval/desk.py)
  POST /api/approval/open           the loop opens one approval (no browser Origin)
  GET  /api/approval                the open approval, for the page
  GET  /api/approval/<id>           one approval, polled by the loop
  POST /api/approval/<id>/voice     a WAV of the person reading aloud (base64 in
                                    JSON) -> Voice Transcribe -> match vs pixels
  POST /api/approval/<id>/decision  {"decision": "approve"|"deny"}; approve only
                                    after a voice that matched

The interface decides nothing and keeps nothing (F11-D4): it shows events and
files. runs/ is git-ignored, so captures exist only on the demo machine.

Who may talk to it: only this machine, and only this page. Every request must
carry a local Host (stops DNS rebinding). Any browser request that sends an
Origin must come from this service's own origin, which keeps other tabs (the
portal included) from injecting events, wiping a run or reading the stream.
Writes also require a JSON body, which makes a cross-site form or no-cors
fetch impossible. The approval endpoints are loopback only and size-limited;
the voice endpoint takes the audio itself (never a file path), checks it is a
short mono PCM WAV, and writes it only to a temporary file that is deleted
after the transcription.
"""

import asyncio
import base64
import binascii
import html
import io
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from approval.desk import ApprovalDesk, DeskError
from common import clock, config
from interceptor.hub import PAGE_QUEUE, EventHub, InvalidEvent, validate
from interceptor.policy import load as load_policy

UI_DIR = config.ROOT / "ui"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}
VERIFY_TIMEOUT_S = 20
MAX_JSON_BYTES = 64_000            # an approval or a decision is a small object
MAX_VOICE_BYTES = 1_500_000        # base64 of ~20 s of 16 kHz mono 16-bit PCM
MAX_VOICE_SECONDS = 20
MIN_VOICE_SECONDS = 0.3

app = FastAPI(title="TESTIGO+ interceptor", docs_url=None, redoc_url=None)
hub = EventHub()
desk = ApprovalDesk()


def _hostname(netloc):
    try:
        return (urlsplit("//" + netloc).hostname or "").lower()
    except ValueError:
        return ""


def origin_ok(headers):
    """No Origin (the loop's sink, curl) or exactly this service's origin."""
    origin = headers.get("origin")
    if origin is None:
        return True
    return origin.rstrip("/") in ("http://" + headers.get("host", ""),
                                  "https://" + headers.get("host", ""))


@app.middleware("http")
async def local_page_only(request: Request, call_next):
    if _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS:
        return JSONResponse({"detail": "local host only"}, status_code=403)
    if not origin_ok(request.headers):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)


# -- helpers ----------------------------------------------------------------

def runs_dir():
    return config.settings().runs_dir.resolve()


def under(base, rel):
    """Resolve `rel` inside `base`, or 404. No `..`, no absolute paths out."""
    base = Path(base).resolve()
    p = (base / str(rel)).resolve()
    if p != base and base not in p.parents:
        raise HTTPException(404, "not found")
    return p


def local_only(request):
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(403, "loopback only")


def _rel(p):
    try:
        return p.relative_to(config.ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def newest_receipt():
    base = runs_dir()
    found = []
    for p in base.rglob("receipt.json"):
        try:
            real = p.resolve(strict=True)
        except OSError:
            continue                      # broken link
        if base in real.parents and real.is_file():
            found.append((real.stat().st_mtime, real))
    return max(found)[1] if found else None


def receipt_path(path):
    if path:
        p = under(runs_dir(), path)
        if p.name != "receipt.json" or not p.is_file():
            raise HTTPException(404, "receipt not found")
        return p
    p = newest_receipt()
    if p is None:
        raise HTTPException(404, "no receipt under runs/ yet")
    return p


def status():
    s = config.settings()
    try:
        policy = load_policy(config.POLICY_PATH)
        policy_sha = policy.short_sha()
        policy_ok = policy.hash_matches_stored()
    except Exception as e:  # noqa: BLE001
        policy_sha, policy_ok = "unreadable (%s)" % type(e).__name__, False
    return {
        "service": "interceptor",
        "time": clock.iso(),
        "portal": s.portal_url,
        "policy_sha256": policy_sha,
        "policy_hash_ok": policy_ok,
        "models_configured": config.configured(),
        "signing_key_present": s.signing_key_path.is_file(),
        "ui": "/",
        "events_stored": len(hub.history()),
    }


# -- interface --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(UI_DIR / "index.html")


app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


@app.get("/runs/{path:path}")
def run_file(path):
    p = under(runs_dir(), path)
    kind = IMAGE_TYPES.get(p.suffix.lower())
    if kind is None or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type=kind)


# -- events -----------------------------------------------------------------

@app.post("/events")
async def post_event(request: Request):
    local_only(request)
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "events must be sent as application/json")
    try:
        event = json.loads(await request.body())
        n = hub.publish(event)
    except (ValueError, InvalidEvent) as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "stored": n}


@app.post("/events/reset")
def reset_events(request: Request):
    local_only(request)
    hub.reset()
    return {"ok": True}


@app.get("/events")
def get_events():
    return hub.history()


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    # Browsers do not apply the same-origin policy to WebSockets, so check here.
    if (_hostname(websocket.headers.get("host", "")) not in LOCAL_HOSTS
            or not origin_ok(websocket.headers)):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=PAGE_QUEUE)
    history = hub.subscribe(loop, queue)
    recv = get = None
    try:
        await websocket.send_json({"type": "hub.history", "events": history})
        recv = asyncio.ensure_future(websocket.receive_text())
        get = asyncio.ensure_future(queue.get())
        while True:
            done, _ = await asyncio.wait({get, recv}, return_when=asyncio.FIRST_COMPLETED)
            if get in done:                   # send first: never drop a dequeued event
                await websocket.send_json(get.result())
                get = asyncio.ensure_future(queue.get())
            if recv in done:
                if recv.exception() is not None:
                    break                     # the page closed
                recv = asyncio.ensure_future(websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(loop, queue)
        for t in (recv, get):
            if t is not None and not t.done():
                t.cancel()


# -- approval (F7) ------------------------------------------------------------

def transcribe_wav(path):
    """Voice Transcribe on a WAV file (the real model). Returns (text, latency_ms).
    Tests replace this function; they never call the Meta API."""
    from common.meta_client import MetaClient
    text, ms, _seconds = MetaClient().transcribe(path)
    return text, ms


async def json_body(request, limit):
    """A JSON object body of at most `limit` bytes, read without trusting
    Content-Length."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "send application/json")
    try:
        if int(request.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, "body too large")
    except ValueError:
        raise HTTPException(400, "bad content-length")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(413, "body too large")
    try:
        data = json.loads(bytes(body))
    except ValueError:
        raise HTTPException(422, "body is not valid JSON")
    if not isinstance(data, dict):
        raise HTTPException(422, "body must be a JSON object")
    return data


def _desk(fn, *args):
    try:
        return fn(*args)
    except DeskError as e:
        raise HTTPException(e.status, e.detail)


def crop_images(images):
    """{"amount"|"address": path under runs/} — PNG files that exist."""
    if images is None:
        return {}
    if not isinstance(images, dict) or set(images) - {"amount", "address"}:
        raise HTTPException(422, "images: only amount and address")
    out = {}
    for label, rel in images.items():
        if not isinstance(rel, str) or not rel.lower().endswith(".png"):
            raise HTTPException(422, "images.%s must be a .png path under runs/" % label)
        p = under(runs_dir(), rel)
        if not p.is_file():
            raise HTTPException(422, "images.%s not found under runs/" % label)
        out[label] = p.relative_to(runs_dir()).as_posix()
    return out


def check_wav(data):
    """A short mono 16-bit PCM WAV, or 422. Returns its duration in seconds."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError):
        raise HTTPException(422, "audio must be a PCM WAV")
    if ch != 1 or width != 2 or not 8000 <= rate <= 48000:
        raise HTTPException(422, "audio must be mono 16-bit PCM, 8-48 kHz")
    seconds = n / float(rate)
    if not MIN_VOICE_SECONDS <= seconds <= MAX_VOICE_SECONDS:
        raise HTTPException(422, "audio must last %.1f-%d s" % (MIN_VOICE_SECONDS, MAX_VOICE_SECONDS))
    return seconds


@app.post("/api/approval/open")
async def approval_open(request: Request):
    """The loop's ServiceApprover. A browser page (which always sends an
    Origin on a POST) cannot open an approval."""
    local_only(request)
    if request.headers.get("origin") is not None:
        raise HTTPException(403, "only the loop opens an approval")
    body = await json_body(request, MAX_JSON_BYTES)
    event = body.get("event")
    try:
        validate(event)
    except InvalidEvent as e:
        raise HTTPException(422, str(e))
    if event["type"] != "approval.requested":
        raise HTTPException(422, "event must be an approval.requested event")
    amount = event.get("amount_cop")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise HTTPException(422, "approval.requested.amount_cop must be an integer (whole pesos)")
    return _desk(desk.open, event, crop_images(body.get("images")))


@app.get("/api/approval")
def approval_current(request: Request):
    local_only(request)
    return {"approval": desk.current()}


@app.get("/api/approval/{approval_id}")
def approval_get(approval_id: str, request: Request):
    local_only(request)
    return _desk(desk.get, approval_id)


@app.post("/api/approval/{approval_id}/voice")
async def approval_voice(approval_id: str, request: Request):
    local_only(request)
    body = await json_body(request, MAX_VOICE_BYTES)
    b64 = body.get("wav_base64")
    if not isinstance(b64, str) or not b64:
        raise HTTPException(422, "wav_base64 (the audio, base64) is required")
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "wav_base64 is not valid base64")
    check_wav(data)
    _desk(desk.start_voice, approval_id)
    with tempfile.TemporaryDirectory(prefix="testigo-voice-") as tmp:
        path = Path(tmp) / "voice.wav"
        path.write_bytes(data)
        try:
            text, ms = await run_in_threadpool(transcribe_wav, path)
        except Exception as e:  # noqa: BLE001 - say so on the page; nothing is approved
            raise HTTPException(502, "Voice Transcribe failed: %s" % type(e).__name__)
    return _desk(desk.record_voice, approval_id, text, ms)


@app.post("/api/approval/{approval_id}/decision")
async def approval_decision(approval_id: str, request: Request):
    local_only(request)
    body = await json_body(request, MAX_JSON_BYTES)
    reason = body.get("reason", "")
    return _desk(desk.decide, approval_id, body.get("decision"),
                 reason if isinstance(reason, str) else "")


# -- files the views read ---------------------------------------------------

@app.get("/api/policy")
def api_policy():
    s = config.settings()
    policy = load_policy(config.POLICY_PATH)
    sig_valid = None   # unknown without the owner's key on this machine
    if s.signing_key_path.is_file():
        from receipts import keys
        sig_valid = policy.signature_valid(keys.public_from_seed(keys.load_seed(s.signing_key_path)))
    return {
        "owner": policy.owner,
        "source": policy.source,
        "transcript": policy.transcript,
        "deliver_only": policy.deliver_only,
        "max_per_order_cop": policy.max_per_order_cop,
        "ask_before": policy.ask_before,
        "signed_by": policy.signed_by,
        "sha256": policy.sha256(),
        "short_sha": policy.short_sha(),
        "hash_ok": policy.hash_matches_stored(),
        "signed": bool(policy.signature),
        "signature_valid": sig_valid,
    }


@app.get("/api/receipt")
def api_receipt(path: str = ""):
    p = receipt_path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise HTTPException(422, "receipt.json is not valid JSON")
    return {"path": p.relative_to(runs_dir()).as_posix(), "receipt": data,
            "modified": p.stat().st_mtime}


@app.post("/api/verify")
def api_verify(request: Request, path: str = ""):
    """Run the real CLI, exactly as anyone would, and return its output."""
    local_only(request)
    p = receipt_path(path)
    cmd = [sys.executable, "-m", "receipts.cli", "verify", str(p)]
    try:
        r = subprocess.run(cmd, cwd=config.ROOT, capture_output=True, text=True,
                           timeout=VERIFY_TIMEOUT_S)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        out, code = "verify timed out after %ds\n" % VERIFY_TIMEOUT_S, 124
    return {"command": "testigo verify %s" % _rel(p), "output": out, "exit_code": code}


@app.get("/api/bench")
def api_bench():
    p = runs_dir() / "bench_results.json"
    if not p.is_file():
        return {"available": False}
    try:
        return {"available": True, "data": json.loads(p.read_text(encoding="utf-8"))}
    except ValueError:
        return {"available": False, "error": "bench_results.json is not valid JSON"}


# -- F0 status page ---------------------------------------------------------

@app.get("/health")
def health():
    return status()


@app.get("/status", response_class=HTMLResponse)
def status_page():
    st = status()
    rows = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (html.escape(k), "set" if v else "<b>empty</b>")
        for k, v in st["models_configured"].items())
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>TESTIGO+ interceptor</title>
<style>body{{font-family:system-ui,sans-serif;background:#FAFAF8;color:#0B0B0B;margin:40px;max-width:720px}}
h1{{color:#104281;font-size:22px}} td{{padding:4px 16px 4px 0}} .muted{{color:#52514E;font-size:14px}}</style>
</head><body>
<h1>TESTIGO+ interceptor &middot; running</h1>
<p class="muted">Simulation only: simulated shop, supplier and addresses. {time}</p>
<p>Portal: <a href="{portal}/orders/new?scenario=clean">{portal}</a></p>
<p>Policy: {sha} &middot; hash {hok}</p>
<p>Signing key: {key}</p>
<h2 style="font-size:16px">Meta API configuration</h2>
<table>{rows}</table>
<p class="muted">Interface: <a href="/">/</a> &middot; events stored: {n} &middot;
Health JSON: <a href="/health">/health</a></p>
</body></html>""".format(
        time=html.escape(st["time"]), portal=html.escape(st["portal"]),
        sha=html.escape(st["policy_sha256"]), hok="ok" if st["policy_hash_ok"] else "MISMATCH",
        key="present" if st["signing_key_present"] else "missing (run: testigo keygen)",
        rows=rows, n=st["events_stored"])
