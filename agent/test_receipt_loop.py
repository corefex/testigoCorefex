"""F9 in the loop: an approved payment leaves a signed receipt that verifies.

Offline: fixture runs with a throwaway key, files in a temp folder.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.config import POLICY_PATH
from receipts import keys
from receipts.verify import verify_receipt
from tests.fixtures.fake_agent import FixtureDriver, ScriptedAgent, run_fixture

from .loop import run

POLICY = str(POLICY_PATH)


def _steps(out):
    return [e["label"] for e in out.events if e["type"] == "agent.step"]


class LoopReceiptTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.seed = keys.generate_seed()

    def test_clean_run_writes_a_receipt_that_verifies(self):
        out = run_fixture("clean", run_dir=self.dir, signing_key=self.seed)
        self.assertEqual(out.receipt_path, self.dir / "receipt.json")
        for f in ("approved_amount.png", "approved_recipient.png",
                  "executed_amount.png", "executed_recipient.png"):
            self.assertTrue((self.dir / f).is_file(), f)
        r = json.loads(out.receipt_path.read_text())
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(r["approval"]["method"], "passkey")          # from the approver
        self.assertEqual(r["pubkey"], keys.public_from_seed(self.seed).hex())
        self.assertNotIn("PLACEHOLDER", r["signature"])
        signed = [e for e in out.events if e["type"] == "receipt.signed"][-1]
        self.assertEqual((signed["id"], signed["signature"]), (r["id"], r["signature"]))
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.dir),
                             policy_path=POLICY, pinned_pubkey=keys.public_from_seed(self.seed))
        self.assertTrue(res.ok, res.summary())

    def test_event_path_is_relative_to_runs(self):
        with mock.patch.dict(os.environ, {"RUNS_DIR": str(self.dir)}):
            out = run_fixture("clean", run_dir=self.dir / "2026-10-31" / "run1",
                              signing_key=self.seed)
        signed = [e for e in out.events if e["type"] == "receipt.signed"][-1]
        self.assertEqual(signed["path"], "2026-10-31/run1/receipt.json")

    def test_a3_receipt_is_signed_and_flags_step_four(self):
        out = run_fixture("a3", run_dir=self.dir, signing_key=self.seed)
        self.assertTrue(out.receipt_flagged)
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.dir), policy_path=POLICY)
        self.assertTrue(res.checks[1].ok)
        self.assertEqual(res.first_failure.n, 4)
        self.assertEqual(res.summary(), "Evidence mismatch at step 4")

    def test_tampered_crop_is_detected(self):
        out = run_fixture("clean", run_dir=self.dir, signing_key=self.seed)
        (self.dir / "approved_recipient.png").write_bytes(b"swapped")
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.dir), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 3)

    def test_tampered_receipt_fails_signature(self):
        out = run_fixture("clean", run_dir=self.dir, signing_key=self.seed)
        r = json.loads(out.receipt_path.read_text())
        r["recipient"] = "300-XXX-0000"
        out.receipt_path.write_text(json.dumps(r))
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.dir), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 2)

    def test_missing_key_does_not_stop_the_run(self):
        out = run(FixtureDriver("clean"), ScriptedAgent(), run_dir=self.dir,
                  signing_key=self.dir / "nope.key")
        self.assertTrue(out.executed)
        self.assertIsNone(out.receipt)
        self.assertNotIn("receipt.signed", [e["type"] for e in out.events])
        self.assertTrue(any(s.startswith("receipt not signed: no signing key") for s in _steps(out)))
        self.assertFalse((self.dir / "receipt.json").exists())

    def test_test_double_never_uses_the_owners_key(self):
        out = run(FixtureDriver("clean"), ScriptedAgent())
        self.assertIsNone(out.receipt)
        self.assertTrue(any("owner's key never signs" in s for s in _steps(out)))

    def test_no_run_dir_signs_in_memory_only(self):
        out = run_fixture("clean")
        self.assertIsNotNone(out.receipt)
        self.assertIsNone(out.receipt_path)
        signed = [e for e in out.events if e["type"] == "receipt.signed"][-1]
        self.assertNotIn("path", signed)

    def test_pending_after_click_still_signs(self):
        class NoAfterCrops(FixtureDriver):
            def observe_after(self):
                cap = super().observe_after()
                cap.crops = {}
                return cap

        out = run(NoAfterCrops("clean"), ScriptedAgent(), run_dir=self.dir, signing_key=self.seed)
        self.assertIn("verify after the click: pending (F8)", _steps(out))
        self.assertIsNone(out.receipt["executed"])
        self.assertEqual(out.receipt["comparison"]["status"], "pending")
        self.assertFalse((self.dir / "executed_amount.png").exists())
        res = verify_receipt(str(out.receipt_path), evidence_dir=str(self.dir), policy_path=POLICY)
        self.assertTrue(res.checks[2].ok)
        self.assertEqual(res.first_failure.n, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
