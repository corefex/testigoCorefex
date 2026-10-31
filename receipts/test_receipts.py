"""Tests for receipts: Ed25519, signing, and the four verify checks.

  make test   (or: .venv/bin/python -m pytest receipts)
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from common.config import POLICY_PATH
from interceptor.policy import load as load_policy
from tests.fixtures.bundles import build_bundle

from . import keys
from . import cli
from .bundle import crops_of, sign_payment, write as write_bundle
from .receipt import BLOCKED, build, canonical, compare, norm_read, sha_crop, sign, verify_signature
from .verify import MalformedReceipt, verify_receipt

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


def _run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class HardeningTests(unittest.TestCase):
    """Code-review fixes: missing evidence never matches, malformed receipts
    fail cleanly, partial captures are recorded honestly."""

    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy(POLICY)
        cls.seed = keys.generate_seed()

    def _signed(self, body, files=None):
        d = Path(tempfile.mkdtemp())
        base = {"id": "rcpt_t", "policy_sha256": self.policy.sha256(), "status": "confirmed"}
        base.update(body)
        r = sign(base, self.seed)
        (d / "receipt.json").write_text(json.dumps(r))
        for name, data in (files or {}).items():
            (d / name).write_bytes(data)
        return d

    def _raw(self, obj):
        d = Path(tempfile.mkdtemp())
        (d / "receipt.json").write_text(json.dumps(obj))
        return str(d / "receipt.json")

    # 1. a missing hash or file never counts as a match
    def test_empty_approved_and_junk_executed_fail(self):
        d = self._signed({"approved": {}, "executed": {"foo": "bar"}})
        res = verify_receipt(str(d / "receipt.json"), policy_path=POLICY)
        self.assertFalse(res.ok)
        self.assertFalse(res.checks[2].ok)
        self.assertFalse(res.checks[3].ok)
        code, out, _ = _run_cli("verify", str(d / "receipt.json"), "--policy", POLICY)
        self.assertEqual(code, 1)

    def test_non_hex_hash_fails(self):
        h = sha_crop(b"A")
        d = self._signed({"approved": {"amount": h, "recipient": "XYZ"},
                          "executed": {"amount": h, "recipient": "XYZ"}})
        res = verify_receipt(str(d / "receipt.json"), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 3)
        self.assertIn("sha256", res.checks[2].detail)

    def test_missing_evidence_files_fail(self):
        ha, hr = sha_crop(b"A"), sha_crop(b"R")
        body = {"approved": {"amount": ha, "recipient": hr},
                "executed": {"amount": ha, "recipient": hr}}
        d = self._signed(body, {"approved_amount.png": b"A", "approved_recipient.png": b"R",
                                "executed_amount.png": b"A"})
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.checks[2].ok)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("executed recipient file missing", res.checks[3].detail)
        (d / "approved_recipient.png").unlink()
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 3)
        self.assertIn("missing", res.checks[2].detail)

    def test_extra_executed_crop_name_fails(self):
        ha, hr = sha_crop(b"A"), sha_crop(b"R")
        d = self._signed({"approved": {"amount": ha, "recipient": hr},
                          "executed": {"amount": ha, "recipient": hr, "memo": ha}})
        res = verify_receipt(str(d / "receipt.json"), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("memo", res.checks[3].detail)

    # 2. malformed receipts: a clear message, exit 1, no traceback
    def test_malformed_receipts_exit_1(self):
        h = sha_crop(b"A")
        good = {"approved": {"amount": h, "recipient": h}, "executed": None}
        cases = [
            [1, 2, 3],
            dict(good, read={"approved": "120000", "executed": None}),
            dict(good, executed="abc"),
            dict(good, pubkey=12345, signature="ed25519:00"),
            dict(good, approved="abc"),
            dict(good, signature=7),
        ]
        for obj in cases:
            path = self._raw(obj)
            with self.assertRaises(MalformedReceipt):
                verify_receipt(path, policy_path=POLICY)
            code, out, _ = _run_cli("verify", path, "--policy", POLICY)
            self.assertEqual(code, 1, obj)
            self.assertTrue(out.startswith("Malformed receipt: "), out)

    def test_not_json_is_malformed(self):
        d = Path(tempfile.mkdtemp())
        (d / "receipt.json").write_text("{nope")
        code, out, _ = _run_cli("verify", str(d / "receipt.json"), "--policy", POLICY)
        self.assertEqual(code, 1)
        self.assertIn("Malformed receipt: not valid JSON", out)

    def test_bad_pubkey_is_usage_error(self):
        clean = str(Path(__file__).resolve().parent.parent / "examples/clean/receipt.json")
        for bad in ("zz", "abcd"):
            code, out, err = _run_cli("verify", clean, "--pubkey", bad)
            self.assertEqual(code, 2)
            self.assertIn("--pubkey must be 64 hex", err)

    # 3. a partial executed capture records only what was written
    def _event(self):
        return {"amount_cop": 120000, "recipient": "Distribuidora X · 310-XXX-4417"}

    def test_crops_of_returns_partial_or_none(self):
        self.assertEqual(crops_of(SimpleNamespace(crops={"amount": b"A"})), {"amount": b"A"})
        self.assertIsNone(crops_of(SimpleNamespace(crops={})))
        self.assertIsNone(crops_of(None))

    def test_partial_executed_capture_recorded_honestly(self):
        d = Path(tempfile.mkdtemp())
        vr = {"executed": {"amount": "f" * 64, "recipient": "e" * 64}}
        r, path = sign_payment(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "recipient": b"R"}, self.seed,
                               executed_crops={"amount": b"A2"}, verify_result=vr, run_dir=d)
        self.assertEqual(r["executed"], {"amount": sha_crop(b"A2")})
        self.assertTrue((d / "executed_amount.png").is_file())
        self.assertFalse((d / "executed_recipient.png").exists())
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("recipient hash not recorded", res.checks[3].detail)

    def test_no_executed_crops_means_not_captured(self):
        d = Path(tempfile.mkdtemp())
        vr = {"executed": {"amount": "f" * 64, "recipient": "e" * 64}}
        r, path = sign_payment(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "recipient": b"R"}, self.seed,
                               executed_crops=None, verify_result=vr, run_dir=d)
        self.assertIsNone(r["executed"])
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertIn("not recorded", res.summary())

    def test_full_executed_capture_with_reads_passes(self):
        d = Path(tempfile.mkdtemp())
        r, path = sign_payment(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "recipient": b"R"}, self.seed,
                               executed_crops={"amount": b"A2", "recipient": b"R2"},
                               executed_read={"amount": "COP 120.000",
                                              "recipient": "To 310-xxx-4417"},
                               run_dir=d)
        self.assertEqual(r["comparison"], {"status": "match", "by": "read"})
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.ok, res.summary())

    # 4. approved read without executed read is pending, not by hash
    def test_compare_pending_when_executed_read_missing(self):
        h = {"amount": "a" * 64, "recipient": "b" * 64}
        self.assertEqual(compare({"amount": "1"}, None, h, dict(h)),
                         {"status": "pending", "by": None})
        self.assertEqual(compare(None, {"amount": "1"}, h, dict(h)),
                         {"status": "pending", "by": None})
        self.assertEqual(compare(None, None, h, dict(h)), {"status": "match", "by": "hash"})

    def test_receipt_without_executed_read_is_pending_at_step_4(self):
        d = Path(tempfile.mkdtemp())
        same = {"amount": b"A", "recipient": b"R"}
        r, path = sign_payment(self.policy, self._event(), {"method": "console"},
                               same, self.seed, executed_crops=dict(same), run_dir=d)
        self.assertEqual(r["comparison"]["status"], "pending")
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertEqual(res.summary(), "Executed evidence not compared at step 4")

    # 5. say whether the key was pinned
    def test_key_note_unpinned_and_pinned(self):
        root = Path(__file__).resolve().parent.parent / "examples"
        code, out, _ = _run_cli("verify", str(root / "clean/receipt.json"))
        self.assertEqual(code, 0)
        self.assertIn("Key: embedded in the receipt (not pinned; pass --pubkey to pin it)", out)
        self.assertEqual(out.strip().splitlines()[-1], "Signature valid — evidence hashes match")
        pub = (root / "pubkey.txt").read_text().strip()
        code, out, _ = _run_cli("verify", str(root / "clean/receipt.json"), "--pubkey", pub)
        self.assertEqual(code, 0)
        self.assertNotIn("not pinned", out)
        code, out, _ = _run_cli("verify", str(root / "a3/receipt.json"), "--pubkey", pub)
        self.assertEqual(code, 1)
        self.assertEqual(out.strip().splitlines()[-1], "Evidence mismatch at step 4")


class NormReadTests(unittest.TestCase):
    """The recipient compares by account number: labels differ per screen."""

    def test_labels_do_not_count(self):
        a = norm_read("recipient", "PAY TO (NEQUI ACCOUNT) 310-XXX-4417 Distribuidora X")
        b = norm_read("recipient", "To 310-xxx-4417")
        self.assertEqual(a, "310-xxx-4417")
        self.assertEqual(a, b)

    def test_other_account_differs(self):
        self.assertNotEqual(norm_read("recipient", "To 310-xxx-4417"),
                            norm_read("recipient", "300-XXX-0000"))

    def test_accounts_sorted_and_deduplicated(self):
        self.assertEqual(norm_read("recipient", "300-XXX-0000 / 310-xxx-4417 310-XXX-4417"),
                         "300-xxx-0000,310-xxx-4417")

    def test_without_account_letters_and_digits(self):
        self.assertEqual(norm_read("recipient", "Distribuidora X!"), "distribuidorax")
        self.assertEqual(norm_read("amount", "COP 120,000"), "120000")
        self.assertIsNone(norm_read("recipient", None))


class ReadNormalizationTests(unittest.TestCase):
    """Review of F8: what a reader may return for the same value compares equal."""

    def test_accounts(self):
        from receipts.receipt import norm_read
        same = ["310-XXX-4417", "310 XXX 4417", "310\u2013XXX\u20134417", "310-***-4417",
                "310-XXX-44I7", "PAY TO (NEQUI ACCOUNT) 310-xxx-4417 Distribuidora X"]
        for s in same:
            self.assertEqual(norm_read("recipient", s), "310-xxx-4417", s)
        self.assertNotEqual(norm_read("recipient", "300-XXX-0000"), "310-xxx-4417")

    def test_amounts(self):
        from receipts.receipt import norm_read
        for s in ("COP 120,000", "$120.000,00", "120000", "Total COP 120,000 Simulation"):
            self.assertEqual(norm_read("amount", s), "120000", s)
        self.assertNotEqual(norm_read("amount", "COP 125,000"), "120000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
