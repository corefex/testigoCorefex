"""F1 live in view 1 (F11): a mandate said in the interface becomes the active
policy, and every consumer resolves the policy the same way.

Test data only: a fake Meta client (tests/test_policy_compile.FakeMeta) stands
in for Voice Transcribe and Spark, keys are throwaway seeds in a temporary
folder, and RUNS_DIR points at a temporary folder. No Meta API call is made.
"""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from common import config
from interceptor import service
from interceptor.policy import load
from receipts import keys
from tests.test_approval_service import wav_b64
from tests.test_policy_compile import GOOD, PHRASE, FakeMeta, with_

SAME = {"Origin": "http://testserver"}          # the interface page itself
EVIL = {"Origin": "http://evil.example"}


def committed_sha():
    return hashlib.sha256(config.POLICY_PATH.read_bytes()).hexdigest()


class Isolated(unittest.TestCase):
    """RUNS_DIR and SIGNING_KEY_PATH in a temporary folder, with a throwaway key."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.key = self.tmp / "owner.key"
        self.seed = keys.load_or_create_seed(self.key)
        self.env = mock.patch.dict(os.environ, {"RUNS_DIR": str(self.tmp / "runs"),
                                                "SIGNING_KEY_PATH": str(self.key)})
        self.env.start()
        self.committed = committed_sha()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        # whatever happened, the committed demo policy is byte for byte the same
        self.assertEqual(committed_sha(), self.committed)

    def write_active(self, max_cop=90000):
        from policy.compile import build_policy_dict, sign_policy_dict, write_policy
        d = build_policy_dict(PHRASE, [{"name": "Tienda Doña Marta",
                                        "address": "Calle 45 # 12-30, Bogotá"}],
                              max_cop, "new_address", signed_by="owner-key:marta")
        signed, p = sign_policy_dict(d, self.seed)
        write_policy(signed, config.active_policy_path())
        return p


class ResolutionTests(Isolated):
    def test_committed_until_one_is_signed_here(self):
        self.assertEqual(config.policy_path(), config.POLICY_PATH)
        self.assertEqual(config.active_policy_path(), self.tmp / "runs" / "policy" / "active.policy.yaml")
        self.write_active()
        self.assertEqual(config.policy_path(), config.active_policy_path())

    def test_loop_and_verify_use_the_active_policy(self):
        from receipts.verify import verify_receipt
        from tests.fixtures.fake_agent import run_fixture
        p = self.write_active(max_cop=150000)
        out = run_fixture("clean", supervised=True, run_dir=self.tmp / "r1")
        self.assertEqual(out.receipt["policy_sha256"], p.sha256())
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.tmp / "r1"))
        self.assertTrue(res.checks[0].ok, res.checks[0].detail)
        # the committed policy no longer matches this receipt: verify says so
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.tmp / "r1"),
                             policy_path=config.POLICY_PATH)
        self.assertFalse(res.checks[0].ok)

    def test_the_active_policy_is_enforced(self):
        from tests.fixtures.fake_agent import run_fixture
        self.write_active(max_cop=90000)              # below the order's COP 120,000
        out = run_fixture("clean", supervised=True)
        self.assertTrue(out.blocked)
        check = [e for e in out.events if e["type"] == "check.result"][-1]
        self.assertEqual(check["status"], "policy_violation")

    def test_service_status_and_policy_follow(self):
        c = TestClient(service.app)
        self.assertEqual(c.get("/api/policy").json()["active"], "committed")
        p = self.write_active()
        got = c.get("/api/policy").json()
        self.assertEqual(got["active"], "signed_here")
        self.assertEqual(got["sha256"], p.sha256())
        self.assertEqual(c.get("/health").json()["policy_sha256"], p.short_sha())


class MandateServiceTests(Isolated):
    def setUp(self):
        super().setUp()
        service._drafts.clear()
        self.c = TestClient(service.app)

    def tearDown(self):
        service._drafts.clear()
        super().tearDown()

    def draft(self, meta, b64=None, headers=SAME):
        with mock.patch.object(service, "mandate_client", lambda: meta):
            return self.c.post("/api/mandate/draft", json={"wav_base64": b64 or wav_b64()},
                               headers=headers)

    def test_draft_then_sign_makes_it_active(self):
        meta = FakeMeta(GOOD)
        r = self.draft(meta)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["status"], "draft")
        self.assertEqual(d["transcript"], PHRASE)
        self.assertEqual(d["deliver_only"], [{"name": "Tienda Doña Marta",
                                              "address": "Calle 45 # 12-30, Bogotá"}])
        self.assertEqual(d["max_per_order_cop"], 150000)
        self.assertEqual([c[0] for c in meta.calls], ["transcribe", "chat"])
        # the audio went to a temporary file that is gone
        self.assertFalse(Path(meta.calls[0][1]).exists())
        # a draft changes nothing yet
        self.assertFalse(config.active_policy_path().exists())
        self.assertEqual(self.c.get("/api/policy").json()["active"], "committed")

        r = self.c.post("/api/mandate/sign", json={"id": d["id"]}, headers=SAME)
        self.assertEqual(r.status_code, 200, r.text)
        signed = r.json()
        self.assertEqual(signed["status"], "signed")
        self.assertEqual(signed["active"], "signed_here")
        self.assertTrue(signed["hash_ok"])
        self.assertTrue(signed["signature_valid"])
        self.assertEqual(signed["signed_by"], "owner-key:marta")
        self.assertEqual(signed["transcript"], PHRASE)
        on_disk = load(config.active_policy_path())
        self.assertTrue(on_disk.signature_valid(keys.public_from_seed(self.seed)))
        self.assertEqual(self.c.get("/api/policy").json()["sha256"], on_disk.sha256())
        # no temporary files left next to it, and no key material in any answer
        self.assertEqual(sorted(x.name for x in config.active_policy_path().parent.iterdir()),
                         ["active.policy.yaml"])
        for text in (r.text, self.c.get("/api/policy").text):
            self.assertNotIn(self.seed.hex(), text)
            self.assertNotIn("signature\"", text.replace("signature_valid\"", ""))
        # a draft signs once
        self.assertEqual(self.c.post("/api/mandate/sign", json={"id": d["id"]},
                                     headers=SAME).status_code, 409)

    def test_refused_mandates_change_nothing(self):
        cases = [
            FakeMeta(GOOD, transcript="No pidas con entrega en la tienda, máximo ciento "
                                      "cincuenta mil pesos por pedido"),
            FakeMeta(with_(max_amount_words="un millón de pesos", max_per_order_cop=1000000),
                     transcript="Solo pide con entrega en la tienda, máximo un millón de pesos"),
            FakeMeta(with_(deliver_only=[{"name": "Bodega Norte", "address": ""}]),
                     transcript="Solo pide con entrega en Bodega Norte, máximo ciento cincuenta mil pesos"),
            FakeMeta("not json"),
        ]
        for meta in cases:
            r = self.draft(meta)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["status"], "refused", r.text)
            self.assertTrue(r.json()["reason"])
            self.assertEqual(r.json()["transcript"], meta.transcript)
            self.assertEqual(service._drafts, {})
            self.assertFalse(config.active_policy_path().exists())
        self.assertIn("negative", self.draft(cases[0]).json()["reason"])
        self.assertIn("amount", self.draft(cases[1]).json()["reason"])

    def test_a_refusal_drops_the_earlier_draft(self):
        d = self.draft(FakeMeta(GOOD)).json()
        self.draft(FakeMeta(GOOD, transcript="No pidas con entrega en la tienda, máximo "
                                             "ciento cincuenta mil pesos"))
        self.assertEqual(self.c.post("/api/mandate/sign", json={"id": d["id"]},
                                     headers=SAME).status_code, 409)
        self.assertFalse(config.active_policy_path().exists())

    def test_protections(self):
        meta = FakeMeta(GOOD)
        # another origin (the portal, any site), a foreign Host, a non-JSON body
        self.assertEqual(self.draft(meta, headers=EVIL).status_code, 403)
        self.assertEqual(self.draft(meta, headers={"Origin": "http://localhost:8080"}).status_code, 403)
        self.assertEqual(self.c.post("/api/mandate/draft", json={"wav_base64": wav_b64()},
                                     headers={"Host": "rebind.example"}).status_code, 403)
        self.assertEqual(self.c.post("/api/mandate/draft", content=b'{"wav_base64": "x"}',
                                     headers={"Content-Type": "text/plain"}).status_code, 415)
        # size cap, bad base64, not a WAV, too long, stereo
        big = "A" * (service.MAX_VOICE_BYTES + 10)
        self.assertEqual(self.draft(meta, b64=big).status_code, 413)
        self.assertEqual(self.draft(meta, b64="%%%").status_code, 422)
        self.assertEqual(self.draft(meta, b64="aGVsbG8=").status_code, 422)
        self.assertEqual(self.draft(meta, b64=wav_b64(seconds=25, rate=8000)).status_code, 422)
        self.assertEqual(self.draft(meta, b64=wav_b64(channels=2)).status_code, 422)
        self.assertEqual(self.c.post("/api/mandate/draft", json={}, headers=SAME).status_code, 422)
        self.assertEqual(meta.calls, [])                        # Voice never called
        # signing: from another origin, without a draft, with a forged id
        d = self.draft(meta).json()
        self.assertEqual(self.c.post("/api/mandate/sign", json={"id": d["id"]},
                                     headers=EVIL).status_code, 403)
        self.assertEqual(self.c.post("/api/mandate/sign", json={"id": "nope"},
                                     headers=SAME).status_code, 409)
        self.assertEqual(self.c.post("/api/mandate/sign", json={"id": ["x"]},
                                     headers=SAME).status_code, 409)
        # the page cannot send its own rules: only the id counts
        r = self.c.post("/api/mandate/sign", json={"id": d["id"], "max_per_order_cop": 9_999_999},
                        headers=SAME)
        self.assertEqual(r.json()["max_per_order_cop"], 150000)

    def test_no_owner_key_signs_nothing(self):
        d = self.draft(FakeMeta(GOOD)).json()
        self.key.unlink()
        r = self.c.post("/api/mandate/sign", json={"id": d["id"]}, headers=SAME)
        self.assertEqual(r.status_code, 409)
        self.assertIn("keygen", r.json()["detail"])
        self.assertFalse(config.active_policy_path().exists())
        self.assertFalse(self.key.exists())                    # never created by the page

    def test_voice_unavailable_is_said(self):
        from common.meta_client import NotConfigured

        class Down(FakeMeta):
            def transcribe(self, audio_path, language="es"):
                raise NotConfigured("META_API_KEY")
        r = self.draft(Down(GOOD))
        self.assertEqual(r.status_code, 503)
        self.assertFalse(config.active_policy_path().exists())


if __name__ == "__main__":
    unittest.main()
