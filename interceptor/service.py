"""The interceptor service: the interface (F11) and its event relay.

  make up        # starts this on INTERCEPTOR_PORT, next to the portal

Routes
  /                  the interface (ui/index.html; static files under /ui)
  /status, /health   the F0 status page and its JSON
  POST /events       the loop posts each event here (loopback only)
  POST /events/reset forget the stored events before a new recording
  GET  /events       the stored events, as JSON
  WS   /ws           history first, then every new event
  GET  /api/policy   the active signed policy (view 1; common.config.policy_path)
  POST /api/mandate/draft  a WAV of the mandate (base64 in JSON) -> Voice ->
                     policy/compile.py -> an unsigned draft, or why it was refused
  POST /api/mandate/discard {"id"}: forget that draft
  POST /api/mandate/sign   {"id"}: sign that draft with the owner key and make it
                     the active policy (RUNS_DIR/policy/active.policy.yaml)
  GET  /api/receipt  the newest receipt.json under runs/, or ?path= (view 7)
  POST /api/verify   runs the real `testigo verify` on that receipt (view 7)
  GET  /api/bench    runs/bench_results.json, else the newest committed
                     results/witnessbench-*.json, or "not available";
                     ?complete=1 skips a local run marked "complete": false
  POST /api/run      {scenario, variant?, supervised, explain?, headed?}: start one
                     real run (`agent.run` as a subprocess); 409 while one runs
  GET  /api/run      the run started here: idle | running | finished | failed |
                     cancelled | orphaned (left by a service that restarted)
  POST /api/run/cancel  stop that run (its process group) and deny its open approval
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
import contextlib
import html
import io
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import deque
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

@contextlib.asynccontextmanager
async def lifespan(_app):
    yield
    runs.shutdown()          # never leave an agent running behind the service


app = FastAPI(title="TESTIGO+ interceptor", docs_url=None, redoc_url=None, lifespan=lifespan)
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
        policy = load_policy(config.policy_path())
        policy_sha = policy.short_sha()
        policy_ok = policy.hash_matches_stored()
    except config.PolicyNotTrusted:
        policy_sha, policy_ok = "not trusted (active policy)", False
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


# -- mandate (F1 live, view 1) ------------------------------------------------
#
# The page records the owner saying the mandate, the service transcribes it
# (Voice) and compiles it with policy/compile.py: the same rules as the
# `policy.compile mandate` CLI (address from the shop profile, negations,
# millions refused). The draft stays here; "Sign and use" signs exactly that
# draft with the owner key and writes it, atomically, to
# RUNS_DIR/policy/active.policy.yaml, which config.policy_path() then serves to
# every consumer. The committed policy/marta.policy.yaml is never written. A
# refused mandate changes nothing.

MAX_MANDATE_SECONDS = MAX_VOICE_SECONDS
_drafts = {}                       # id -> {"policy": dict, "info": dict}; only the newest is kept


def mandate_client():
    """The Meta client the mandate compiles with (Voice Transcribe + Spark).
    Tests replace this function; they never call the Meta API."""
    from common.meta_client import MetaClient
    return MetaClient()


def _policy_label(path):
    path = Path(path)
    if path == config.POLICY_PATH:
        return _rel(path)
    try:
        return "runs/" + path.relative_to(config.ROOT / "runs").as_posix()
    except ValueError:
        return "RUNS_DIR/" + config.ACTIVE_POLICY.as_posix()


def _compile_wav(path):
    from policy.compile import compile_mandate
    return compile_mandate(mandate_client(), audio_path=path)


def _draft_view(draft_id, pol, info):
    from interceptor.policy import Policy
    from policy.compile import describe
    p = Policy(pol)
    return {"status": "draft", "id": draft_id, "transcript": p.transcript,
            "deliver_only": p.deliver_only, "max_per_order_cop": p.max_per_order_cop,
            "ask_before": p.ask_before, "ask_before_said": bool(info.get("ask_before_said")),
            "max_amount_words": info.get("max_amount_words", ""),
            "voice_ms": info.get("voice_ms"), "spark_ms": info.get("spark_ms"),
            "describe": describe(pol, info)}


@app.post("/api/mandate/draft")
async def mandate_draft(request: Request):
    """A WAV of the owner saying the mandate (base64 in JSON) -> a compiled,
    unsigned draft, or the reason it was refused. Nothing is signed here."""
    from common.meta_client import NotConfigured, SpendCapExceeded
    from policy.compile import MandateRefused
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
    with tempfile.TemporaryDirectory(prefix="testigo-mandate-") as tmp:
        path = Path(tmp) / "mandate.wav"
        path.write_bytes(data)
        try:
            pol, info = await run_in_threadpool(_compile_wav, path)
        except MandateRefused as e:
            _drafts.clear()
            return {"status": "refused", "reason": str(e),
                    "transcript": getattr(e, "transcript", None)}
        except (NotConfigured, SpendCapExceeded) as e:
            raise HTTPException(503, "Voice/Spark not available: %s" % type(e).__name__)
        except Exception as e:  # noqa: BLE001 - say so on the page; nothing is signed
            raise HTTPException(502, "Voice or Spark failed: %s" % type(e).__name__)
    draft_id = secrets.token_hex(8)
    _drafts.clear()
    _drafts[draft_id] = {"policy": pol, "info": info}
    return _draft_view(draft_id, pol, info)


def write_active_policy(signed):
    """Write the signed policy to RUNS_DIR/policy/active.policy.yaml atomically
    (a temporary file in the same folder, then os.replace), and check what is on
    disk before anyone reads it."""
    from policy.compile import HEADER, to_yaml
    dest = config.active_policy_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".active-", suffix=".yaml", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(HEADER + to_yaml(signed))
            f.flush()
            os.fsync(f.fileno())
        again = load_policy(tmp)
        if not again.hash_matches_stored() or again.signature != signed.get("signature"):
            raise HTTPException(500, "the signed policy did not round-trip; nothing changed")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    config.archive_policy(dest)      # kept by hash: earlier receipts still verify
    return dest


@app.post("/api/mandate/sign")
async def mandate_sign(request: Request):
    """Sign the server's draft (never rules sent by the page) with the owner key
    and make it the active policy."""
    from policy.compile import sign_policy_dict
    from receipts import keys
    local_only(request)
    body = await json_body(request, MAX_JSON_BYTES)
    draft_id = body.get("id")
    draft = _drafts.get(draft_id) if isinstance(draft_id, str) else None
    if draft is None:
        raise HTTPException(409, "no such draft: record the mandate again")
    key_path = config.settings().signing_key_path
    if not key_path.is_file():
        raise HTTPException(409, "the owner key is not on this machine (run: testigo keygen)")
    seed = keys.load_seed(key_path)
    signed, _ = sign_policy_dict(draft["policy"], seed)
    dest = await run_in_threadpool(write_active_policy, signed)
    # Only now is the draft used up: a failed sign above leaves it to retry.
    if _drafts.get(draft_id) is draft:
        _drafts.pop(draft_id, None)
    return dict(policy_view(load_policy(dest), dest), status="signed")


@app.post("/api/mandate/discard")
async def mandate_discard(request: Request):
    """{"id"}: forget that draft (the page's Discard). Nothing else changes."""
    local_only(request)
    body = await json_body(request, MAX_JSON_BYTES)
    draft_id = body.get("id")
    found = isinstance(draft_id, str) and _drafts.pop(draft_id, None) is not None
    return {"status": "discarded" if found else "none"}


# -- files the views read ---------------------------------------------------

@app.get("/api/policy")
def api_policy():
    try:
        path = config.policy_path()
    except config.PolicyNotTrusted as e:
        raise HTTPException(409, "the active policy is not trusted: %s" % e)
    return policy_view(load_policy(path), path)


def policy_view(policy, path):
    """The policy as view 1 shows it. Never any key material."""
    s = config.settings()
    sig_valid = None   # unknown without the owner's key on this machine
    if s.signing_key_path.is_file():
        from receipts import keys
        sig_valid = policy.signature_valid(keys.public_from_seed(keys.load_seed(s.signing_key_path)))
    return {
        "active": "committed" if Path(path) == config.POLICY_PATH else "signed_here",
        "path": _policy_label(path),
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


RESULTS_DIR = config.ROOT / "results"


def _committed_bench():
    committed = sorted(Path(RESULTS_DIR).glob("witnessbench-*.json"))
    return (committed[-1], "results/" + committed[-1].name) if committed else (None, None)


def _incomplete(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("complete") is False
    except (OSError, ValueError, AttributeError):
        return False


def bench_file(complete=False):
    """runs/bench_results.json (the latest WitnessBench run on this machine), else
    the newest committed copy in results/, else None. complete=True skips a
    local run marked "complete": false when a committed file exists."""
    p = runs_dir() / "bench_results.json"
    if p.is_file():
        if not (complete and _incomplete(p) and _committed_bench()[0] is not None):
            return p, "runs/bench_results.json"
    return _committed_bench()


@app.get("/api/bench")
def api_bench(complete: bool = False):
    p, label = bench_file(complete)
    if p is None:
        return {"available": False}
    try:
        return {"available": True, "source": label,
                "data": json.loads(p.read_text(encoding="utf-8"))}
    except ValueError:
        return {"available": False, "source": label, "error": "%s is not valid JSON" % p.name}


# -- start a run from the interface ------------------------------------------
#
# One real run at a time: `python -m agent.run` as a child process, exactly as
# from the terminal (it spends Meta credits). The argv is built here from
# validated values only, never from strings the page sent, and never through a
# shell. Its events reach the page the usual way (POST /events, then /ws); this
# only reports whether the process is alive and the last lines it printed.

RUN_SCENARIOS = ("clean", "a1", "a2", "a3")
RUN_KEYS = {"scenario", "variant", "supervised", "explain", "headed"}
RUN_TAIL_LINES = 40
RUN_STOP_TIMEOUT_S = 5
RUN_PID_FILE = "ui-run.pid.json"       # under RUNS_DIR: a restarted service still sees the run
# What the child needs besides the declared config variables (common/config.ENV_VARS).
CHILD_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG",
             "LC_ALL", "LC_CTYPE", "TZ", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME",
             "PLAYWRIGHT_BROWSERS_PATH", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
             "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "no_proxy", "SYSTEMROOT")


def start_process(argv, env):
    """Start the run in its own process group (so the whole group, browser
    included, can be stopped). Tests replace this function; they never start
    a real run."""
    return subprocess.Popen(argv, cwd=config.ROOT, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, errors="replace", start_new_session=True)


def child_env(port=None):
    """Only what the run needs: the system basics and the config variables
    (the Meta key among them; agent.run also reads .env itself)."""
    config.load_env()
    names = set(CHILD_ENV) | set(config.ENV_VARS)
    env = {k: v for k, v in os.environ.items() if k in names or k.startswith("LC_")}
    if port:
        env["INTERCEPTOR_PORT"] = str(port)     # the child reports to this service
    return env


# -- secrets never reach the page through the printed lines --------------------
_SECRET_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)(\s*[=:]\s*)[\"']?[^\s\"',]{6,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}"),
]


def _secret_values():
    out = []
    for k, v in os.environ.items():
        if v and len(v) >= 6 and re.search(r"KEY|TOKEN|SECRET|PASSWORD", k, re.I) and "PATH" not in k:
            out.append(v)
    return sorted(set(out), key=len, reverse=True)


def redact(line):
    for v in _secret_values():
        line = line.replace(v, "[redacted]")
    for i, rx in enumerate(_SECRET_PATTERNS):
        line = rx.sub((lambda m: m.group(1) + m.group(2) + "[redacted]") if i == 2 else "[redacted]", line)
    return line


# -- stopping a run, its process group, and the pending approval ---------------
def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_leader_alive(pid):
    """That pid is alive and still leads its own process group, as our run did
    (start_new_session): a reused pid of some other program is not ours."""
    if not pid_alive(pid):
        return False
    try:
        return os.getpgid(pid) == pid
    except (ProcessLookupError, PermissionError):
        return False


def kill_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _signal(proc, sig):
    """The whole group of a real child; a test double through its own methods."""
    if isinstance(proc, subprocess.Popen):
        kill_group(proc.pid, sig)
    elif sig == signal.SIGKILL:
        proc.kill()
    else:
        proc.terminate()


def deny_open_approval(reason):
    """A run that stops cannot be waiting for the person any more."""
    cur = desk.current()
    if cur and cur.get("decision") is None:
        try:
            desk.decide(cur["id"], "deny", reason)
        except DeskError:
            pass

def run_argv(scenario, variant, supervised, explain, headed):
    argv = [sys.executable, "-m", "agent.run", "--scenario", scenario,
            "--variant", str(variant), "--approve-in", "interface"]
    if not supervised:
        argv.append("--no-supervisor")
        if explain:
            argv.append("--explain")
    if headed:
        argv.append("--headed")
    return argv


def _flag(body, key, default):
    v = body.get(key, default)
    if not isinstance(v, bool):
        raise HTTPException(422, "%s must be true or false" % key)
    return v


def run_request(body):
    """The validated run, or 422."""
    extra = set(body) - RUN_KEYS
    if extra:
        raise HTTPException(422, "unknown field: %s" % ", ".join(sorted(extra)))
    scenario = body.get("scenario")
    if not isinstance(scenario, str) or scenario not in RUN_SCENARIOS:
        raise HTTPException(422, "scenario must be one of %s" % ", ".join(RUN_SCENARIOS))
    variant = body.get("variant", 1)
    if not isinstance(variant, int) or isinstance(variant, bool) or not 1 <= variant <= 5:
        raise HTTPException(422, "variant must be a whole number from 1 to 5")
    if "supervised" not in body:
        raise HTTPException(422, "supervised (true or false) is required")
    supervised = _flag(body, "supervised", True)
    explain = _flag(body, "explain", not supervised)
    if supervised and explain:
        raise HTTPException(422, "explain is only for runs without TESTIGO+")
    headed = _flag(body, "headed", False)
    return {"scenario": scenario, "variant": variant, "supervised": supervised,
            "explain": explain, "headed": headed}


class RunManager:
    """One run at a time, started from the page. Its pid (the process group
    leader) is kept in RUNS_DIR/ui-run.pid.json while it lives, so a restarted
    service reports it as orphaned, refuses a second run, and can stop it."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.info = None
        self.tail = deque(maxlen=RUN_TAIL_LINES)

    # -- the pid file --------------------------------------------------------
    def _pid_path(self):
        return runs_dir() / RUN_PID_FILE

    def _write_pid(self, proc, info):
        pid = getattr(proc, "pid", None)
        if not isinstance(pid, int):
            return
        path = self._pid_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(info, pid=pid)), encoding="utf-8")
        except OSError:
            pass

    def _clear_pid(self, pid=None):
        path = self._pid_path()
        try:
            if pid is not None and json.loads(path.read_text(encoding="utf-8")).get("pid") != pid:
                return
            path.unlink()
        except (OSError, ValueError):
            pass

    def orphan(self):
        """The run a previous service left alive, or None (a stale file is removed)."""
        path = self._pid_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        pid = data.get("pid") if isinstance(data, dict) else None
        if not isinstance(pid, int) or pid <= 0 or not run_leader_alive(pid):
            self._clear_pid()
            return None
        return data

    # -- state -----------------------------------------------------------------
    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def view(self):
        with self.lock:
            if self.info is not None and (self.busy() or self.orphan() is None):
                return dict(self.info, tail=list(self.tail))
            o = self.orphan() if not self.busy() else None
            if o is not None:
                return dict({k: o.get(k) for k in ("scenario", "variant", "supervised", "mode", "started")},
                            state="orphaned", pid=o["pid"], ended=None, exit_code=None, tail=[],
                            note="started before the interface service restarted; stop it to run again")
            if self.info is None:
                return {"state": "idle"}
            return dict(self.info, tail=list(self.tail))

    def start(self, req, port=None):
        with self.lock:
            if self.busy():
                raise HTTPException(409, "a run is already in progress")
            if self.orphan() is not None:
                raise HTTPException(409, "a run started before the service restarted is still going; stop it first")
            argv = run_argv(**req)
            self.tail.clear()
            try:
                proc = start_process(argv, child_env(port))
            except OSError as e:
                raise HTTPException(500, "could not start the run: %s" % type(e).__name__)
            self.proc = proc
            self.info = dict(req, state="running", started=clock.iso(), ended=None,
                             exit_code=None, mode="supervised" if req["supervised"] else "no_supervisor")
            self._write_pid(proc, self.info)
        threading.Thread(target=self._watch, args=(proc,), daemon=True).start()
        return self.view()

    def _watch(self, proc):
        try:
            for line in proc.stdout or ():
                with self.lock:
                    if self.proc is proc:
                        self.tail.append(redact(line.rstrip("\n"))[:300])
        except (OSError, ValueError):
            pass
        code = proc.wait()
        with self.lock:
            if self.proc is not proc:
                return                                  # a newer run took over
            if self.info["state"] == "running":
                self.info.update(state="finished" if code == 0 else "failed", ended=clock.iso())
            if self.info.get("exit_code") is None:
                self.info["exit_code"] = code
            self._clear_pid(getattr(proc, "pid", None))

    def cancel(self):
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return self._cancel_orphan()
            self.info.update(state="cancelled", ended=clock.iso())
        deny_open_approval("run cancelled")
        self._stop(proc)
        with self.lock:
            if self.proc is proc:
                self.info["exit_code"] = proc.returncode
                self._clear_pid(getattr(proc, "pid", None))
        return True

    def _stop(self, proc):
        _signal(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=RUN_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _signal(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=RUN_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                pass

    def _cancel_orphan(self):
        o = self.orphan()
        if o is None:
            return False
        pid = o["pid"]
        deny_open_approval("run cancelled")
        kill_group(pid, signal.SIGTERM)
        deadline = time.monotonic() + RUN_STOP_TIMEOUT_S
        while pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if pid_alive(pid):
            kill_group(pid, signal.SIGKILL)
        self._clear_pid(pid)
        return True

    def shutdown(self):
        """The service is stopping: never leave an agent running behind it."""
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                return
            self.info.update(state="cancelled", ended=clock.iso())
        deny_open_approval("the interface service stopped")
        self._stop(proc)
        with self.lock:
            if self.proc is proc:
                self.info["exit_code"] = proc.returncode
                self._clear_pid(getattr(proc, "pid", None))


runs = RunManager()


@app.post("/api/run")
async def api_run_start(request: Request):
    local_only(request)
    req = run_request(await json_body(request, MAX_JSON_BYTES))
    return runs.start(req, port=request.url.port)


@app.get("/api/run")
def api_run_status(request: Request):
    local_only(request)
    return runs.view()


@app.post("/api/run/cancel")
async def api_run_cancel(request: Request):
    local_only(request)
    await json_body(request, MAX_JSON_BYTES)
    cancelled = await run_in_threadpool(runs.cancel)
    return dict(runs.view(), cancelled=cancelled)


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
