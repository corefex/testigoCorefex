"""Tests for receipts: Ed25519, signing, and the four verify checks.

  make test   (or: .venv/bin/python -m pytest receipts)
"""

import json
import tempfile
import unittest
from pathlib import Path

from common.config import POLICY_PATH
from interceptor.policy import load as load_policy
from tests.fixtures.bundles import build_bundle

from . import keys
from .bundle import write as write_bundle
from .receipt import BLOCKED, build, canonical, verify_signature
from .verify import verify_receipt

POLICY = str(POLICY_PATH)


class Ed25519Tests(unittest.TestCase):
    def test_sign_verify_roundtrip(self):
        seed = keys.generate_seed()
        pub = keys.public_from_seed(seed)
        sig = keys.sign(seed, b"evidence")
        self.assertTrue(keys.verify(pub, b"evidence", sig))
        self.assertFalse(keys.verify(pub, b"evidence!", sig))
        self.assertEqual(len(pub), 32)
        self.assertEqual(len(sig), 64)

    def test_wrong_key_fails(self):
        seed = keys.generate_seed()
        other = keys.public_from_seed(keys.generate_seed())
        sig = keys.sign(seed, b"x")
        self.assertFalse(keys.verify(other, b"x", sig))


class SignBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(POLICY)
        cls.seed = keys.generate_seed()

    def _receipt(self, executed=None):
        approved = {"amount": b"A", "recipient": b"R"}
        executed = executed or {"amount": b"A", "recipient": b"R"}
        return build(self.policy, "pay 120000 COP -> Distribuidora X",
                     120000, "Distribuidora X · 310-XXX-4417",
                     approved, executed,
                     {"method": "passkey", "voice_transcript": "..."}, self.seed)

    def test_signature_valid_and_covers_body(self):
        r = self._receipt()
        self.assertTrue(verify_signature(r))
        r2 = dict(r)
        r2["amount_cop"] = 999999        # change a signed field
        self.assertFalse(verify_signature(r2))

    def test_canonical_excludes_signature(self):
        r = self._receipt()
        self.assertNotIn(b"signature", canonical(r))

    def test_pinned_pubkey_matches(self):
        r = self._receipt()
        pub = keys.public_from_seed(self.seed)
        self.assertTrue(verify_signature(r, pinned_pubkey=pub))
        self.assertFalse(verify_signature(r, pinned_pubkey=keys.public_from_seed(keys.generate_seed())))

    def test_records_policy_hash(self):
        r = self._receipt()
        self.assertEqual(r["policy_sha256"], self.policy.sha256())


class VerifyChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.seed = keys.generate_seed()

    def _bundle(self, scenario):
        out = Path(self.tmp, scenario)
        path, _ = build_bundle(scenario, str(out), seed=self.seed, policy_path=POLICY)
        return str(path), str(out)

    def test_clean_passes_all_four(self):
        path, ev = self._bundle("clean")
        res = verify_receipt(path, evidence_dir=ev, policy_path=POLICY)
        self.assertTrue(res.ok)
        self.assertIn("valid", res.summary())

    def test_a3_fails_at_step_four(self):
        path, ev = self._bundle("a3")
        res = verify_receipt(path, evidence_dir=ev, policy_path=POLICY)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("step 4", res.summary())
        # signature itself is still valid - the receipt honestly records a mismatch
        self.assertTrue(res.checks[1].ok)

    def test_tampered_receipt_fails_signature(self):
        path, ev = self._bundle("clean")
        r = json.loads(Path(path).read_text())
        r["recipient"] = "300-XXX-0000"
        Path(path).write_text(json.dumps(r))
        res = verify_receipt(path, evidence_dir=ev, policy_path=POLICY)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_failure.n, 2)

    def test_swapped_evidence_file_fails_step_three(self):
        path, ev = self._bundle("clean")
        # overwrite an approved crop file with different bytes
        Path(ev, "approved_recipient.png").write_bytes(b"tampered")
        res = verify_receipt(path, evidence_dir=ev, policy_path=POLICY)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_failure.n, 3)

    def test_without_evidence_still_checks_recorded(self):
        path, _ = self._bundle("a3")
        res = verify_receipt(path, evidence_dir=None, policy_path=POLICY)
        # step 3 skipped, but step 4 still catches the recorded mismatch
        self.assertFalse(res.ok)
        self.assertEqual(res.first_failure.n, 4)


class ReadValueTests(unittest.TestCase):
    """Real captures: equal regions do not hash equal (SAM's boxes move), so
    step 4 decides on the values read from the crops; hashes guard the files."""

    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(POLICY)
        cls.seed = keys.generate_seed()

    def _write(self, **kw):
        approved = {"amount": b"A1", "recipient": b"R1"}
        executed = kw.pop("executed", {"amount": b"A2", "recipient": b"R2"})   # moved boxes
        r = build(self.policy, "pay", 120000, "Distribuidora X · 310-XXX-4417",
                  approved, executed, {"method": "console", "voice_transcript": ""}, self.seed,
                  approved_read={"amount": "120000", "recipient": "Distribuidora X · 310-XXX-4417"},
                  **kw)
        d = Path(tempfile.mkdtemp())
        write_bundle(r, approved, executed, d)
        return r, d

    def test_same_read_values_pass_though_hashes_differ(self):
        r, d = self._write(executed_read={"amount": "COP 120,000",
                                          "recipient": "distribuidora x 310-XXX-4417"})
        self.assertEqual(r["comparison"], {"status": "match", "by": "read"})
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.ok, res.summary())

    def test_changed_recipient_read_fails_step_four(self):
        r, d = self._write(executed_read={"amount": "COP 120,000", "recipient": "300-XXX-0000"})
        self.assertEqual(r["comparison"]["status"], "mismatch")
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertTrue(res.checks[1].ok)
        self.assertEqual(res.summary(), "Evidence mismatch at step 4")

    def test_swapped_executed_file_fails_step_four(self):
        _, d = self._write(executed_read={"amount": "120000",
                                          "recipient": "Distribuidora X · 310-XXX-4417"})
        Path(d, "executed_amount.png").write_bytes(b"tampered")
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("file", res.first_failure.detail)

    def test_nothing_captured_after_click_is_reported_not_invented(self):
        r, d = self._write(executed=None)
        self.assertIsNone(r["executed"])
        self.assertEqual(r["comparison"]["status"], "pending")
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("not recorded", res.summary())

    def test_blocked_receipt_has_no_executed_and_no_step_four(self):
        r, d = self._write(status=BLOCKED, blocked_at="review", executed=None)
        self.assertIsNone(r["executed"])
        self.assertEqual(r["blocked_at"], "review")
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.ok, res.summary())
        self.assertIn("not applicable", res.checks[3].detail)

    def test_id_and_time_are_generated(self):
        a, _ = self._write(executed_read=None)
        b, _ = self._write(executed_read=None)
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(a["time"].endswith("-05:00"))


class ExamplesTests(unittest.TestCase):
    """The published examples keep verifying with the old (hash-only) format."""

    def test_examples(self):
        root = Path(__file__).resolve().parent.parent / "examples"
        pub = bytes.fromhex((root / "pubkey.txt").read_text().strip())
        clean = verify_receipt(str(root / "clean/receipt.json"), evidence_dir=str(root / "clean"),
                               policy_path=POLICY, pinned_pubkey=pub)
        self.assertTrue(clean.ok)
        self.assertEqual(clean.summary(), "Signature valid — evidence hashes match")
        a3 = verify_receipt(str(root / "a3/receipt.json"), evidence_dir=str(root / "a3"),
                            policy_path=POLICY, pinned_pubkey=pub)
        self.assertEqual(a3.summary(), "Evidence mismatch at step 4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
