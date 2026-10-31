"""F11: the service relays events to the interface and serves only what it should.

Test data only: example events and the synthetic receipts in examples/. The
interface itself is static; these tests cover what feeds it.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from common.config import ROOT
from interceptor import events as ev
from interceptor import service
from interceptor.hub import EventHub, InvalidEvent, validate
from tests.test_approval_service import wav_b64


def check_event():
    return ev.check_result(7, ev.DIVERGENCE,
                           [ev.region("amount", (812, 640, 1010, 690), "COP 120,000", 0.97)],
                           [], ["a line painted in the banner"], 1400, "visible text not in code")


class HubTests(unittest.TestCase):
    def test_validate_accepts_contract_and_rejects_the_rest(self):
        e = check_event()
        self.assertIs(validate(e), e)
        for bad in ([], "x", {"type": "nope"}, {"no": "type"},
                    {"type": "agent.step", "label": "x" * 70_000}):
            with self.assertRaises(InvalidEvent):
                validate(bad)

    def test_history_is_capped_and_reset(self):
        hub = EventHub(maxlen=3)
        for i in range(5):
            hub.publish(ev.agent_step(i, "step %d" % i))
        self.assertEqual([e["frame"] for e in hub.history()], [2, 3, 4])
        hub.reset()
        self.assertEqual(hub.history(), [])


class ServiceUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"RUNS_DIR": str(self.tmp)})
        self.env.start()
        service.hub.reset()
        self.c = TestClient(service.app)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        service.hub.reset()

    def test_root_serves_the_interface_and_status_moved(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('/ui/app.js', r.text)
        self.assertEqual(self.c.get("/ui/app.css").status_code, 200)
        self.assertIn("TESTIGO+ interceptor", self.c.get("/status").text)

    def test_post_then_history(self):
        r = self.c.post("/events", json=check_event())
        self.assertEqual(r.status_code, 200)
        got = self.c.get("/events").json()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["regions"][0]["box"], [812, 640, 1010, 690])

    def test_invalid_event_is_refused(self):
        self.assertEqual(self.c.post("/events", json={"type": "nope"}).status_code, 422)
        self.assertEqual(self.c.post("/events", content=b"not json",
                                     headers={"Content-Type": "application/json"}).status_code, 422)
        # shapes the views rely on are checked, so one bad event cannot break a page
        bad = [ev.run_started("__proto__", "a1"),
               {"type": "approval.requested", "amount_cop": 1, "recipient": "x"},
               dict(check_event(), regions=[{"label": "amount"}]),
               dict(ev.payment_executed(1, "x", 1), amount_cop=True)]
        for e in bad:
            self.assertEqual(self.c.post("/events", json=e).status_code, 422, e)
        self.assertEqual(self.c.get("/events").json(), [])

    def test_other_pages_cannot_inject_wipe_or_listen(self):
        """A tab on another origin (the portal, any site) is refused; so is a
        non-JSON body, which is what a no-cors fetch would have to send."""
        evil = {"Origin": "http://evil.example"}
        self.assertEqual(self.c.post("/events", json=check_event(), headers=evil).status_code, 403)
        self.assertEqual(self.c.post("/events", content=b'{"type":"agent.step","label":"x"}',
                                     headers={"Content-Type": "text/plain"}).status_code, 415)
        self.c.post("/events", json=ev.agent_step(1, "kept"))
        self.assertEqual(self.c.post("/events/reset", headers=evil).status_code, 403)
        self.assertEqual(self.c.get("/events", headers=evil).status_code, 403)
        self.assertEqual(len(self.c.get("/events").json()), 1)
        # the portal runs on another port: a different origin too
        portal = {"Origin": "http://localhost:8080"}
        self.assertEqual(self.c.post("/events", json=check_event(), headers=portal).status_code, 403)
        # the interface itself (same origin) may run verify and reset
        same = {"Origin": "http://testserver"}
        self.assertEqual(self.c.post("/events/reset", headers=same).status_code, 200)
        # DNS rebinding: a foreign Host is refused everywhere
        self.assertEqual(self.c.get("/events", headers={"Host": "rebind.example"}).status_code, 403)
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.c.websocket_connect("/ws", headers=evil) as ws:
                ws.receive_json()

    def test_websocket_replays_history_then_streams(self):
        self.c.post("/events", json=ev.run_started("supervised", "a1"))
        with self.c.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            self.assertEqual(first["type"], "hub.history")
            self.assertEqual([e["type"] for e in first["events"]], ["run.started"])
            self.c.post("/events", json=check_event())
            live = ws.receive_json()
            self.assertEqual(live["type"], "check.result")
            self.c.post("/events/reset")
            self.assertEqual(ws.receive_json()["type"], "hub.reset")

    def test_runs_serves_images_only_and_never_escapes(self):
        (self.tmp / "r1").mkdir()
        (self.tmp / "r1" / "frame-1.png").write_bytes(b"\x89PNG fake")
        (self.tmp / "usage.jsonl").write_text("{}")
        self.assertEqual(self.c.get("/runs/r1/frame-1.png").status_code, 200)
        self.assertEqual(self.c.get("/runs/usage.jsonl").status_code, 404)
        self.assertEqual(self.c.get("/runs/../pyproject.toml").status_code, 404)
        self.assertEqual(self.c.get("/runs/%2e%2e/.secrets/receipts.key").status_code, 404)

    def test_policy_for_view_1(self):
        p = self.c.get("/api/policy").json()
        self.assertTrue(p["hash_ok"])
        self.assertEqual(p["pay_only"][0]["account"], "310-XXX-4417")
        self.assertEqual(p["max_per_payment_cop"], 150000)

    def test_bench_absent_says_so(self):
        self.assertEqual(self.c.get("/api/bench").json(), {"available": False})

    def test_newest_receipt_ignores_links_out_of_runs(self):
        outside = Path(tempfile.mkdtemp())
        try:
            (outside / "receipt.json").write_text('{"id": "outside"}')
            (self.tmp / "x").mkdir()
            (self.tmp / "x" / "receipt.json").symlink_to(outside / "receipt.json")
            (self.tmp / "y").mkdir()
            (self.tmp / "y" / "receipt.json").symlink_to(self.tmp / "missing.json")
            self.assertEqual(self.c.get("/api/receipt").status_code, 404)
            (self.tmp / "z").mkdir()
            (self.tmp / "z" / "receipt.json").write_text("not json")
            self.assertEqual(self.c.get("/api/receipt").status_code, 422)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_receipt_and_real_verify(self):
        self.assertEqual(self.c.get("/api/receipt").status_code, 404)
        for name in ("clean", "a3"):
            shutil.copytree(ROOT / "examples" / name, self.tmp / name)
        os.utime(self.tmp / "a3" / "receipt.json", (2_000_000_000, 2_000_000_000))
        newest = self.c.get("/api/receipt").json()
        self.assertEqual(newest["path"], "a3/receipt.json")

        ok = self.c.post("/api/verify?path=clean/receipt.json").json()
        self.assertEqual(ok["exit_code"], 0, ok["output"])
        self.assertIn("Signature valid — evidence hashes match", ok["output"])
        bad = self.c.post("/api/verify?path=a3/receipt.json").json()
        self.assertEqual(bad["exit_code"], 1)
        self.assertIn("Evidence mismatch at step 4", bad["output"])

        self.assertEqual(self.c.get("/api/receipt?path=../examples/clean/receipt.json").status_code, 404)
        self.assertEqual(self.c.post("/api/verify?path=clean/approved_amount.png").status_code, 404)


# -- the page itself, in a headless browser ------------------------------------

def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright


class LiveService:
    """The real service on a free loopback port, in this process (so tests can
    swap the transcriber). Test data only."""

    def __enter__(self):
        import socket
        import threading
        import time
        import uvicorn
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(service.app, host="127.0.0.1", port=self.port,
                                                    log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    def post(self, path, body=None, origin=None):
        import json
        import urllib.request
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(self.url + path, method="POST", headers=headers,
                                     data=json.dumps(body or {}).encode("utf-8"))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as r:
            return json.loads(r.read() or b"null")


@unittest.skipIf(_chromium() is None, "playwright not installed")
class PageTests(unittest.TestCase):
    """Views 5, 6 and 8 painted from test events in headless Chromium."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.env = mock.patch.dict(os.environ, {"RUNS_DIR": str(cls.tmp)})
        cls.env.start()
        cls.live = LiveService().__enter__()
        cls.pw = _chromium()().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # noqa: BLE001 - no browser binary on this machine
            cls.pw.stop()
            cls.live.__exit__(None, None, None)
            cls.env.stop()
            raise unittest.SkipTest("chromium not available: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.live.__exit__(None, None, None)
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from approval.desk import ApprovalDesk
        service.hub.reset()
        service.desk = ApprovalDesk()
        (self.tmp / "bench_results.json").unlink(missing_ok=True)
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        self.errors = []
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.page.close()
        service.hub.reset()
        self.assertEqual(self.errors, [])

    def events(self, *es):
        for e in es:
            self.live.post("/events", dict(e, test_data=True))

    def show(self, view, ready=None):
        self.page.goto("about:blank")                 # a fresh load, never a hash change
        self.page.goto(self.live.url + "/#/%d" % view)
        self.page.wait_for_function("document.getElementById('conn').textContent === 'Live'")
        if ready:
            self.page.wait_for_selector(ready)

    def text(self):
        return self.page.inner_text("#view")

    def approval(self):
        return ev.approval_requested(5, 120000, "Distribuidora X · 310-XXX-4417", "a" * 64, "b" * 64,
                                     ts="2026-10-31T10:00:00-05:00")

    def test_wav_never_exceeds_the_service_limit(self):
        self.show(0)
        b64 = self.page.evaluate("""() => {
            const rate = 48000, chunks = [];
            for (let i = 0; i < 25 * rate / 4096; i++) chunks.push(new Float32Array(4096));
            return wavBase64(chunks, rate);
        }""")
        import base64
        seconds = service.check_wav(base64.b64decode(b64))     # 422 would raise
        self.assertLessEqual(seconds, 18.0)
        self.assertEqual(self.page.evaluate("MAX_REC_S"), 18)

    def test_norm_read_matches_python(self):
        from receipts.receipt import norm_read
        self.show(0)
        samples = [("amount", "COP 120,000"), ("amount", "$120.000,00"), ("amount", "120000"),
                   ("amount", "Total: COP 1,200,000 (3 items)"), ("recipient", "Distribuidora X · 310-XXX-4417"),
                   ("recipient", "PAY TO (NEQUI ACCOUNT) 3l0 xxx 44I7"), ("recipient", "Distribuidora  X."),
                   ("recipient", "To 310-555-0199 and 310-XXX-4417")]
        for name, text in samples:
            self.assertEqual(self.page.evaluate("([n, t]) => normRead(n, t)", [name, text]),
                             norm_read(name, text), text)

    def test_denied_on_timeout_stops_offering_approve(self):
        """The run denied on timeout and its closing POST failed: the service still
        shows the approval pending, but approval.granted(false) closes it on the page."""
        a = self.approval()
        self.events(ev.run_started("supervised", "clean"), a)
        rec = self.live.post("/api/approval/open", {"event": a})
        with mock.patch.object(service, "transcribe_wav",
                               lambda p: ("ciento veinte mil pesos a Distribuidora X", 10)):
            self.live.post("/api/approval/%s/voice" % rec["id"],
                           {"wav_base64": wav_b64()},
                           origin=self.live.url)
        self.show(5, "#vapprove:not([disabled])")
        self.events(ev.approval_granted("voice", "", False, granted=False))
        self.page.wait_for_selector("#vapprove[disabled]")
        self.assertTrue(self.page.is_disabled("#vdeny"))
        self.page.evaluate("decide('approve')")                   # even called directly
        self.assertIsNone(service.desk.current()["decision"])
        self.assertIn("Not approved", self.text())

    def test_view_6_blocked_at_review_by_read_values(self):
        read = {"approved": {"amount": "120000", "recipient": "Distribuidora X · 310-XXX-4417"},
                "executed": {"amount": "COP 120,000", "recipient": "Distribuidora X · 310-666-0000"}}
        self.events(ev.run_started("supervised", "a3"), self.approval(),
                    ev.approval_granted("voice", "ciento veinte mil pesos a Distribuidora X", True),
                    ev.verify_result(9, "mismatch", {"amount": "a" * 64, "recipient": "b" * 64},
                                     {"amount": "c" * 64, "recipient": "d" * 64},
                                     moment="review", read=read))
        self.show(6, ".outcome")
        t = self.text()
        self.assertIn("Blocked at review", t)
        self.assertIn("Payment not sent", t)
        # the amount hashes differ but the read values agree: only the recipient is red
        self.assertEqual(self.page.locator(".after .crop.diff").count(), 1)
        self.assertIn("310-666-0000", self.page.inner_text(".after .crop.diff"))
        self.assertIn("Blocked at review", self.page.inner_text("#agentstate"))

    def test_view_6_verified_flagged_and_cannot_verify(self):
        same = {"approved": {"amount": "120000", "recipient": "Distribuidora X · 310-XXX-4417"},
                "executed": {"amount": "COP 120,000", "recipient": "PAY TO 310-XXX-4417"}}
        h1, h2 = {"amount": "a" * 64, "recipient": "b" * 64}, {"amount": "c" * 64, "recipient": "d" * 64}
        base = (ev.run_started("supervised", "clean"), self.approval(),
                ev.approval_granted("voice", "ciento veinte mil pesos a Distribuidora X", True),
                ev.verify_result(9, "match", h1, h2, moment="review", read=same))
        self.events(*base, ev.verify_result(12, "match", h1, h2, moment="result", read=same))
        self.show(6, ".outcome")
        self.assertIn("VERIFIED", self.text())
        self.assertEqual(self.page.locator(".after .crop.diff").count(), 0)

        service.hub.reset()
        changed = {"approved": same["approved"], "executed": {"amount": "COP 150,000",
                                                              "recipient": "PAY TO 310-XXX-4417"}}
        self.events(*base, ev.verify_result(12, "mismatch", h1, h2, moment="result", read=changed))
        self.show(6, ".outcome")
        self.assertIn("MISMATCH", self.text())
        self.assertIn("Flagged for review", self.text())
        self.assertIn("Flagged", self.page.inner_text("#agentstate"))

        service.hub.reset()
        unread = {"approved": same["approved"], "executed": {"amount": "COP 120,000"}}
        self.events(*base, ev.verify_result(12, "cannot_verify", h1, h2, moment="result", read=unread))
        self.show(6, ".outcome")
        self.assertIn("Could not verify", self.text())
        self.assertIn("could not read the recipient", self.text())
        self.assertEqual(self.page.locator(".after .crop.unread").count(), 1)

    def test_view_8_counts_from_the_file(self):
        import json
        self.show(8, ".bench .notice")
        self.assertIn("No WitnessBench results yet", self.text())
        summary = {
            "attacks_succeed_without": {"succeeded": 3, "runs": 15, "pct": 20},
            "attacks_succeed_with": {"succeeded": 0, "runs": 15, "pct": 0},
            "by_attack": {a: {"without": {"succeeded": n, "runs": 5}, "with": {"succeeded": 0, "runs": 5}}
                          for a, n in (("a1", 2), ("a2", 1), ("a3", 0))},
            "false_positives": {"count": 0, "clean_runs": 5},
            "added_latency_ms": {"median": 11234, "p90": 14012, "n": 20},
            "agent_resisted_without_supervisor": 12,
            "edge_cases": [{"name": "blurred banner", "scenario": "a2", "variant": 6,
                            "mode": "supervised", "paid_attacker": False, "blocked": True,
                            "status": "cannot_verify"}],
        }
        (self.tmp / "bench_results.json").write_text(json.dumps({"summary": summary}))
        self.show(8, ".bench .bars")
        t = self.text()
        for want in ("3 of 15", "0 of 15", "2 of 5", "0 of 5 clean runs", "median 11.2 s",
                     "p90 14.0 s", "Wonder refused 12 attacks on its own", "Known limits",
                     "blurred banner"):
            self.assertIn(want, t)
        self.assertNotIn("%", t)


if __name__ == "__main__":
    unittest.main()
