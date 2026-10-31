"""F7 with R8: approval in the interface by voice + click.

Test data only. The transcriber is a fake: these tests never call the Meta API.
They cover the service endpoints (and what they refuse), the desk's rules, and
the loop-side `ServiceApprover` (wait, timeout, deny) talking to the real
service through FastAPI's TestClient.
"""

import base64
import io
import os
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agent.approval import ServiceApprover
from approval.desk import MAX_VOICE_ATTEMPTS, ApprovalDesk, DeskError
from interceptor import events as ev
from interceptor import service

GOOD = "ciento veinte mil pesos a Distribuidora X"
WRONG = "ciento cincuenta mil pesos a Distribuidora X"
SAME = {"Origin": "http://testserver"}          # the interface page itself


def approval_event():
    return ev.approval_requested(5, 120000, "Distribuidora X · 310-XXX-4417",
                                 "a" * 64, "b" * 64, ts="2026-10-31T10:00:00-05:00")


def wav_bytes(seconds=1.0, rate=16000, channels=1, width=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


def wav_b64(**kw):
    return base64.b64encode(wav_bytes(**kw)).decode("ascii")


class FakeTranscriber:
    """Stands in for Voice Transcribe: returns fixed texts, records the files."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.paths = []

    def __call__(self, path):
        path = Path(path)
        self.paths.append(path)
        assert path.read_bytes()[:4] == b"RIFF"
        return self.texts.pop(0), 812


class DeskTests(unittest.TestCase):
    def test_approve_needs_a_matching_voice_and_decisions_are_final(self):
        d = ApprovalDesk()
        rec = d.open(approval_event())
        with self.assertRaises(DeskError) as e:
            d.decide(rec["id"], "approve")
        self.assertEqual(e.exception.status, 409)
        d.start_voice(rec["id"])
        got = d.record_voice(rec["id"], WRONG)
        self.assertFalse(got["voice"]["match"])
        self.assertFalse(got["voice"]["amount_match"])
        self.assertEqual(got["voice"]["heard_amount"], 150000)
        with self.assertRaises(DeskError):
            d.decide(rec["id"], "approve")
        d.start_voice(rec["id"])
        self.assertTrue(d.record_voice(rec["id"], GOOD)["voice"]["match"])
        self.assertEqual(d.decide(rec["id"], "approve")["decision"], "approve")
        with self.assertRaises(DeskError):
            d.decide(rec["id"], "deny")
        with self.assertRaises(DeskError):
            d.start_voice(rec["id"])

    def test_a_new_approval_supersedes_the_old_one(self):
        d = ApprovalDesk()
        old = d.open(approval_event())
        new = d.open(approval_event())
        self.assertNotEqual(old["id"], new["id"])
        with self.assertRaises(DeskError) as e:
            d.get(old["id"])
        self.assertEqual(e.exception.status, 404)

    def test_open_needs_an_integer_amount(self):
        d = ApprovalDesk()
        for amount in (120000.0, "120000", True, None):
            with self.assertRaises(DeskError) as e:
                d.open(dict(approval_event(), amount_cop=amount))
            self.assertEqual(e.exception.status, 422, amount)
        self.assertIsNone(d.current())

    def test_voice_record_says_why(self):
        d = ApprovalDesk()
        rec = d.open(approval_event())
        d.start_voice(rec["id"])
        v = d.record_voice(rec["id"], "no pagues " + GOOD)["voice"]
        self.assertFalse(v["match"])
        self.assertEqual(v["negated"], ["no"])
        d.start_voice(rec["id"])
        v = d.record_voice(rec["id"], "cinco mil, ciento quince mil a Distribuidora X")["voice"]
        self.assertFalse(v["amount_match"])
        self.assertIsNone(v["heard_amount"])
        self.assertTrue(v["amount_reason"])
        big = d.open(dict(approval_event(), amount_cop=2_000_000_000))
        d.start_voice(big["id"])
        v = d.record_voice(big["id"], "dos mil millones a Distribuidora X")["voice"]
        self.assertIn("out of range", v["amount_reason"])

    def test_voice_attempts_are_capped(self):
        d = ApprovalDesk()
        rec = d.open(approval_event())
        for _ in range(MAX_VOICE_ATTEMPTS):
            d.start_voice(rec["id"])
        with self.assertRaises(DeskError) as e:
            d.start_voice(rec["id"])
        self.assertEqual(e.exception.status, 429)


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"RUNS_DIR": str(self.tmp)})
        self.env.start()
        service.desk = ApprovalDesk()
        self.c = TestClient(service.app)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        service.desk = ApprovalDesk()

    def open(self, **body):
        r = self.c.post("/api/approval/open", json=dict({"event": approval_event()}, **body))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def voice(self, aid, b64=None, headers=SAME):
        return self.c.post("/api/approval/%s/voice" % aid, json={"wav_base64": b64 or wav_b64()},
                           headers=headers)

    def test_voice_that_matches_unlocks_approve(self):
        rec = self.open()
        self.assertEqual(self.c.get("/api/approval").json()["approval"]["id"], rec["id"])
        fake = FakeTranscriber(WRONG, GOOD)
        with mock.patch.object(service, "transcribe_wav", fake):
            r = self.voice(rec["id"])
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse(r.json()["voice"]["match"])
            self.assertEqual(r.json()["voice"]["transcript"], WRONG)
            # the button is disabled on the page; the service refuses as well
            self.assertEqual(self.c.post("/api/approval/%s/decision" % rec["id"],
                                         json={"decision": "approve"}, headers=SAME).status_code, 409)
            r = self.voice(rec["id"])
        v = r.json()["voice"]
        self.assertTrue(v["match"])
        self.assertEqual(v["latency_ms"], 812)
        self.assertEqual(r.json()["attempts"], 2)
        # the audio went to a temporary file that no longer exists
        self.assertTrue(all(not p.exists() for p in fake.paths))
        r = self.c.post("/api/approval/%s/decision" % rec["id"], json={"decision": "approve"},
                        headers=SAME)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/approval/%s" % rec["id"]).json()["decision"], "approve")

    def test_deny_is_always_possible(self):
        rec = self.open()
        r = self.c.post("/api/approval/%s/decision" % rec["id"], json={"decision": "deny"},
                        headers=SAME)
        self.assertEqual(r.json()["decision"], "deny")
        self.assertEqual(r.json()["reason"], "denied by the person")
        self.assertEqual(self.voice(rec["id"]).status_code, 409)

    def test_refusals(self):
        rec = self.open()
        aid = rec["id"]
        evil = {"Origin": "http://evil.example"}
        portal = {"Origin": "http://localhost:8080"}
        with mock.patch.object(service, "transcribe_wav", FakeTranscriber(GOOD)) as fake:
            # other origins and hosts cannot record, decide or read
            self.assertEqual(self.voice(aid, headers=evil).status_code, 403)
            self.assertEqual(self.voice(aid, headers=portal).status_code, 403)
            self.assertEqual(self.c.post("/api/approval/%s/decision" % aid,
                                         json={"decision": "deny"}, headers=evil).status_code, 403)
            self.assertEqual(self.c.get("/api/approval", headers={"Host": "rebind.example"}).status_code, 403)
            # a browser page cannot open an approval, even the interface itself
            self.assertEqual(self.c.post("/api/approval/open", json={"event": approval_event()},
                                         headers=SAME).status_code, 403)
            # JSON only; a form or a no-cors fetch cannot send it
            self.assertEqual(self.c.post("/api/approval/%s/voice" % aid, content=wav_bytes(),
                                         headers={"Content-Type": "audio/wav"}).status_code, 415)
            self.assertEqual(self.c.post("/api/approval/%s/decision" % aid,
                                         content=b'{"decision":"deny"}',
                                         headers={"Content-Type": "text/plain"}).status_code, 415)
            # never a file path: the audio itself, valid base64, a short mono PCM WAV
            self.assertEqual(self.c.post("/api/approval/%s/voice" % aid,
                                         json={"path": "/etc/passwd"}).status_code, 422)
            self.assertEqual(self.voice(aid, b64="not base64!").status_code, 422)
            self.assertEqual(self.voice(aid, b64=base64.b64encode(b"RIFF....junk").decode()).status_code, 422)
            self.assertEqual(self.voice(aid, b64=wav_b64(channels=2)).status_code, 422)
            self.assertEqual(self.voice(aid, b64=wav_b64(width=1)).status_code, 422)
            self.assertEqual(self.voice(aid, b64=wav_b64(seconds=0.1)).status_code, 422)
            self.assertEqual(self.voice(aid, b64=wav_b64(seconds=25)).status_code, 422)  # too long
            # size limit, without trusting Content-Length
            big = b'{"wav_base64": "' + b"A" * (service.MAX_VOICE_BYTES + 10) + b'"}'
            self.assertEqual(self.c.post("/api/approval/%s/voice" % aid, content=big,
                                         headers={"Content-Type": "application/json"}).status_code, 413)
            # unknown approval, unknown decision
            self.assertEqual(self.voice("nope").status_code, 404)
            self.assertEqual(self.c.post("/api/approval/%s/decision" % aid,
                                         json={"decision": "maybe"}).status_code, 422)
            self.assertEqual(fake.paths, [])           # nothing above reached the transcriber
        # opening: only a valid approval.requested, crop images only PNGs under runs/
        self.assertEqual(self.c.post("/api/approval/open",
                                     json={"event": ev.agent_step(1, "x")}).status_code, 422)
        self.assertEqual(self.c.post("/api/approval/open",
                                     json={"event": {"type": "approval.requested"}}).status_code, 422)
        for images in ({"amount": "../pyproject.toml"}, {"amount": "missing.png"},
                       {"other": "x.png"}, {"amount": "/etc/passwd"}):
            self.assertIn(self.c.post("/api/approval/open", json={"event": approval_event(),
                                                                   "images": images}).status_code,
                          (404, 422), images)

    def test_open_refuses_a_non_integer_amount(self):
        for amount in (120000.5, 120000.0):
            r = self.c.post("/api/approval/open",
                            json={"event": dict(approval_event(), amount_cop=amount)})
            self.assertEqual(r.status_code, 422, amount)
            self.assertIn("integer", r.json()["detail"])
        self.assertIsNone(self.c.get("/api/approval").json()["approval"])

    def test_crop_images_under_runs(self):
        (self.tmp / "r1").mkdir()
        (self.tmp / "r1" / "crop_amount.png").write_bytes(b"\x89PNG fake")
        rec = self.open(images={"amount": "r1/crop_amount.png"})
        self.assertEqual(rec["images"], {"amount": "r1/crop_amount.png"})

    def test_transcriber_failure_is_reported_not_approved(self):
        rec = self.open()

        def broken(path):
            raise RuntimeError("network down")
        with mock.patch.object(service, "transcribe_wav", broken):
            r = self.voice(rec["id"])
        self.assertEqual(r.status_code, 502)
        self.assertIsNone(self.c.get("/api/approval").json()["approval"]["voice"])


def client_http(c):
    """ServiceApprover's http hook over TestClient (no Origin: like the loop)."""
    def http(method, path, body=None):
        r = c.request(method, path, json=body)
        return r.status_code, r.json()
    return http


class ServiceApproverTests(unittest.TestCase):
    def setUp(self):
        service.desk = ApprovalDesk()
        self.c = TestClient(service.app)
        self.t = [0.0]

    def tearDown(self):
        service.desk = ApprovalDesk()

    def approver(self, on_poll=None, timeout_s=10, http=None):
        def sleep(s):
            self.t[0] += s
            if on_poll:
                on_poll()
        return ServiceApprover(http=http or client_http(self.c), timeout_s=timeout_s, poll_s=1,
                               sleep=sleep, monotonic=lambda: self.t[0])

    def person(self, *texts, decision="approve", after=2):
        """The person at the page: after `after` polls, reads aloud and clicks."""
        n = [0]
        fake = FakeTranscriber(*texts)

        def act():
            n[0] += 1
            if n[0] != after:
                return
            rec = self.c.get("/api/approval").json()["approval"]
            with mock.patch.object(service, "transcribe_wav", fake):
                for _ in texts:
                    self.c.post("/api/approval/%s/voice" % rec["id"],
                                json={"wav_base64": wav_b64()}, headers=SAME)
            self.c.post("/api/approval/%s/decision" % rec["id"], json={"decision": decision},
                        headers=SAME)
        return act

    def test_waits_then_grants_with_the_real_transcript(self):
        granted, info = self.approver(self.person(WRONG, GOOD)).approve(approval_event())
        self.assertTrue(granted)
        self.assertEqual(info, {"method": "voice", "voice_transcript": GOOD, "voice_match": True})
        # the loop turns this into approval.granted; the hub accepts it
        e = ev.approval_granted(info["method"], info["voice_transcript"], info["voice_match"],
                                granted=granted)
        self.assertEqual(e["method"], "voice")

    def test_person_denies(self):
        granted, info = self.approver(self.person(GOOD, decision="deny")).approve(approval_event())
        self.assertFalse(granted)
        self.assertEqual(info["reason"], "denied by the person")
        self.assertTrue(info["voice_match"])
        self.assertEqual(info["voice_transcript"], GOOD)

    def test_timeout_denies_and_closes_the_approval(self):
        granted, info = self.approver(timeout_s=5).approve(approval_event())
        self.assertFalse(granted)
        self.assertIn("within 5s", info["reason"])
        self.assertEqual(info["method"], "voice")
        rec = self.c.get("/api/approval").json()["approval"]
        self.assertEqual(rec["decision"], "deny")      # the page stops offering the buttons
        self.assertGreaterEqual(self.t[0], 5)

    def test_service_down_denies(self):
        def down(method, path, body=None):
            raise ConnectionRefusedError("no service")
        granted, info = self.approver(http=down).approve(approval_event())
        self.assertFalse(granted)
        self.assertIn("could not open", info["reason"])

    def test_decision_for_another_event_or_without_match_is_a_denial(self):
        a = ServiceApprover(http=lambda *a: None, sleep=lambda s: None)
        other = dict(approval_event(), amount_cop=999)
        rec = {"id": "a1", "decision": "approve", "event": other,
               "voice": {"match": True, "transcript": GOOD}}
        self.assertFalse(a._result(approval_event(), rec, "a1")[0])
        rec = {"id": "a1", "decision": "approve", "event": approval_event(),
               "voice": {"match": False, "transcript": WRONG}}
        self.assertFalse(a._result(approval_event(), rec, "a1")[0])
        good = {"id": "a1", "decision": "approve", "event": approval_event(),
                "voice": {"match": True, "transcript": GOOD}}
        self.assertTrue(a._result(approval_event(), good, "a1")[0])

    def test_decision_for_another_record_id_is_a_denial(self):
        a = ServiceApprover(http=lambda *a: None, sleep=lambda s: None)
        rec = {"id": "someone-else", "decision": "approve", "event": approval_event(),
               "voice": {"match": True, "transcript": GOOD}}
        granted, info = a._result(approval_event(), rec, "a1")
        self.assertFalse(granted)
        self.assertIn("different approval", info["reason"])

    def test_run_rechecks_the_voice_itself(self):
        """A service that says match for a transcript that does not match the
        event (a bug, or a tampered record) is not trusted."""
        a = ServiceApprover(http=lambda *a: None, sleep=lambda s: None)
        for said in (WRONG, "no pagues " + GOOD, "cinco mil, ciento quince mil a Distribuidora X"):
            rec = {"id": "a1", "decision": "approve", "event": approval_event(),
                   "voice": {"match": True, "transcript": said}}
            granted, info = a._result(approval_event(), rec, "a1")
            self.assertFalse(granted, said)
            self.assertIn("re-checked", info["reason"])
            self.assertFalse(info["voice_match"])

    def test_images_for_are_sent_and_a_refused_image_still_opens(self):
        a = self.approver(self.person(GOOD), http=client_http(self.c))
        a.images_for = lambda e: {"amount": "missing.png"}
        granted, _ = a.approve(approval_event())
        self.assertTrue(granted)


class RunWiringTests(unittest.TestCase):
    """agent/run.py: crops kept by hash for the capsule; which approver."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"RUNS_DIR": str(self.tmp)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_crop_files_named_by_the_hash_the_event_carries(self):
        from agent.run import CropFiles
        from interceptor.channels import sha_crop

        class Channel:
            def read_regions(self, capture):
                capture.crops["amount"] = b"\x89PNG amount"
                capture.crops["recipient"] = b"\x89PNG recipient"
                return ["regions"]

        capture = mock.Mock(frame=5, crops={})
        cf = CropFiles(Channel(), self.tmp / "run1")
        (self.tmp / "run1").mkdir()
        self.assertEqual(cf.read_regions(capture), ["regions"])
        e = ev.approval_requested(5, 120000, "Distribuidora X", sha_crop(b"\x89PNG amount"),
                                  sha_crop(b"\x89PNG recipient"))
        images = cf.images_for(e)
        self.assertEqual(set(images), {"amount", "recipient"})
        self.assertEqual((self.tmp / images["amount"]).read_bytes(), b"\x89PNG amount")
        self.assertEqual(cf.images_for(dict(e, crops={"amount": "0" * 64})), {})

    def test_choose_approver(self):
        from agent import run
        from agent.approval import ConsoleApprover
        crops = mock.Mock()
        self.assertIsInstance(run.choose_approver("console", 300, crops), ConsoleApprover)
        self.assertIsInstance(run.choose_approver("interface", 300, crops), ServiceApprover)
        with mock.patch.object(run, "service_up", return_value=True):
            self.assertIsInstance(run.choose_approver(None, 300, crops), ServiceApprover)
        with mock.patch.object(run, "service_up", return_value=False):
            self.assertIsInstance(run.choose_approver(None, 300, crops), ConsoleApprover)


if __name__ == "__main__":
    unittest.main()
