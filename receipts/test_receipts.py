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
from .bundle import crops_of, sign_order, write as write_bundle
from .receipt import BLOCKED, build, canonical, compare, norm_read, sha_crop, sign, verify_signature
from .verify import MalformedReceipt, verify_receipt

POLICY = str(POLICY_PATH)
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def examples_current():
    """The published examples/ carry this version's crop names (R2: amount and
    address). Until they are replaced after a real run they may predate it."""
    from .receipt import CROP_NAMES
    return all((EXAMPLES / n / ("approved_%s.png" % c)).is_file()
               for n in ("clean", "a3") for c in CROP_NAMES)


_SYNTHETIC = []


def synthetic_examples():
    """A folder shaped like examples/ (clean/, a3/, pubkey.txt), built from the
    test fixtures with a throwaway key, for the CLI tests."""
    if not _SYNTHETIC:
        root = Path(tempfile.mkdtemp())
        seed = keys.generate_seed()
        for scenario in ("clean", "a3"):
            build_bundle(scenario, str(root / scenario), seed=seed, policy_path=POLICY)
        (root / "pubkey.txt").write_text(keys.public_from_seed(seed).hex() + "\n")
        _SYNTHETIC.append(root)
    return _SYNTHETIC[0]


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
        approved = {"amount": b"A", "address": b"R"}
        executed = executed or {"amount": b"A", "address": b"R"}
        return build(self.policy, "confirm order 120000 COP -> deliver to Tienda Doña Marta",
                     120000, "Tienda Doña Marta · Calle 45 # 12-30, Bogotá",
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
        r["address"] = "Bodega Norte · Carrera 80 # 7-15, Bogotá"
        Path(path).write_text(json.dumps(r))
        res = verify_receipt(path, evidence_dir=ev, policy_path=POLICY)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_failure.n, 2)

    def test_swapped_evidence_file_fails_step_three(self):
        path, ev = self._bundle("clean")
        # overwrite an approved crop file with different bytes
        Path(ev, "approved_address.png").write_bytes(b"tampered")
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
        approved = {"amount": b"A1", "address": b"R1"}
        executed = kw.pop("executed", {"amount": b"A2", "address": b"R2"})   # moved boxes
        r = build(self.policy, "confirm order", 120000, "Tienda Doña Marta · Calle 45 # 12-30, Bogotá",
                  approved, executed, {"method": "console", "voice_transcript": ""}, self.seed,
                  approved_read={"amount": "120000", "address": "Tienda Doña Marta · Calle 45 # 12-30, Bogotá"},
                  **kw)
        d = Path(tempfile.mkdtemp())
        write_bundle(r, approved, executed, d)
        return r, d

    def test_same_read_values_pass_though_hashes_differ(self):
        r, d = self._write(executed_read={"amount": "COP 120,000",
                                          "address": "tienda doña marta cl 45 no 12-30"})
        self.assertEqual(r["comparison"], {"status": "match", "by": "read"})
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.ok, res.summary())

    def test_changed_address_read_fails_step_four(self):
        r, d = self._write(executed_read={"amount": "COP 120,000",
                                          "address": "Bodega Norte · Carrera 80 # 7-15"})
        self.assertEqual(r["comparison"]["status"], "mismatch")
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertTrue(res.checks[1].ok)
        self.assertEqual(res.summary(), "Evidence mismatch at step 4")

    def test_swapped_executed_file_fails_step_four(self):
        _, d = self._write(executed_read={"amount": "120000",
                                          "address": "Tienda Doña Marta · Calle 45 # 12-30, Bogotá"})
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

    @unittest.skipUnless(examples_current(), "examples/ predates R2 (delivery address); "
                                             "it is replaced after a real run")
    def test_examples(self):
        self._check(EXAMPLES)

    def test_synthetic_examples_like_the_published_ones(self):
        self._check(synthetic_examples())

    def _check(self, root):
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
        d = self._signed({"approved": {"amount": h, "address": "XYZ"},
                          "executed": {"amount": h, "address": "XYZ"}})
        res = verify_receipt(str(d / "receipt.json"), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 3)
        self.assertIn("sha256", res.checks[2].detail)

    def test_missing_evidence_files_fail(self):
        ha, hr = sha_crop(b"A"), sha_crop(b"R")
        body = {"approved": {"amount": ha, "address": hr},
                "executed": {"amount": ha, "address": hr}}
        d = self._signed(body, {"approved_amount.png": b"A", "approved_address.png": b"R",
                                "executed_amount.png": b"A"})
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.checks[2].ok)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("executed address file missing", res.checks[3].detail)
        (d / "approved_address.png").unlink()
        res = verify_receipt(str(d / "receipt.json"), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 3)
        self.assertIn("missing", res.checks[2].detail)

    def test_extra_executed_crop_name_fails(self):
        ha, hr = sha_crop(b"A"), sha_crop(b"R")
        d = self._signed({"approved": {"amount": ha, "address": hr},
                          "executed": {"amount": ha, "address": hr, "memo": ha}})
        res = verify_receipt(str(d / "receipt.json"), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("memo", res.checks[3].detail)

    # 2. malformed receipts: a clear message, exit 1, no traceback
    def test_malformed_receipts_exit_1(self):
        h = sha_crop(b"A")
        good = {"approved": {"amount": h, "address": h}, "executed": None}
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
        clean = str(synthetic_examples() / "clean/receipt.json")
        for bad in ("zz", "abcd"):
            code, out, err = _run_cli("verify", clean, "--pubkey", bad)
            self.assertEqual(code, 2)
            self.assertIn("--pubkey must be 64 hex", err)

    # 3. a partial executed capture records only what was written
    def _event(self):
        return {"amount_cop": 120000, "address": "Tienda Doña Marta · Calle 45 # 12-30, Bogotá"}

    def test_crops_of_returns_partial_or_none(self):
        self.assertEqual(crops_of(SimpleNamespace(crops={"amount": b"A"})), {"amount": b"A"})
        self.assertIsNone(crops_of(SimpleNamespace(crops={})))
        self.assertIsNone(crops_of(None))

    def test_partial_executed_capture_recorded_honestly(self):
        d = Path(tempfile.mkdtemp())
        vr = {"executed": {"amount": "f" * 64, "address": "e" * 64}}
        r, path = sign_order(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "address": b"R"}, self.seed,
                               executed_crops={"amount": b"A2"}, verify_result=vr, run_dir=d)
        self.assertEqual(r["executed"], {"amount": sha_crop(b"A2")})
        self.assertTrue((d / "executed_amount.png").is_file())
        self.assertFalse((d / "executed_address.png").exists())
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertIn("address hash not recorded", res.checks[3].detail)

    def test_no_executed_crops_means_not_captured(self):
        d = Path(tempfile.mkdtemp())
        vr = {"executed": {"amount": "f" * 64, "address": "e" * 64}}
        r, path = sign_order(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "address": b"R"}, self.seed,
                               executed_crops=None, verify_result=vr, run_dir=d)
        self.assertIsNone(r["executed"])
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertIn("not recorded", res.summary())

    def test_full_executed_capture_with_reads_passes(self):
        d = Path(tempfile.mkdtemp())
        r, path = sign_order(self.policy, self._event(), {"method": "console"},
                               {"amount": b"A", "address": b"R"}, self.seed,
                               executed_crops={"amount": b"A2", "address": b"R2"},
                               executed_read={"amount": "COP 120.000",
                                              "address": "Deliver to Calle 45 # 12-30"},
                               run_dir=d)
        self.assertEqual(r["comparison"], {"status": "match", "by": "read"})
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertTrue(res.ok, res.summary())

    # 4. approved read without executed read is pending, not by hash
    def test_compare_pending_when_executed_read_missing(self):
        h = {"amount": "a" * 64, "address": "b" * 64}
        self.assertEqual(compare({"amount": "1"}, None, h, dict(h)),
                         {"status": "pending", "by": None})
        self.assertEqual(compare(None, {"amount": "1"}, h, dict(h)),
                         {"status": "pending", "by": None})
        self.assertEqual(compare(None, None, h, dict(h)), {"status": "match", "by": "hash"})

    def test_receipt_without_executed_read_is_pending_at_step_4(self):
        d = Path(tempfile.mkdtemp())
        same = {"amount": b"A", "address": b"R"}
        r, path = sign_order(self.policy, self._event(), {"method": "console"},
                               same, self.seed, executed_crops=dict(same), run_dir=d)
        self.assertEqual(r["comparison"]["status"], "pending")
        res = verify_receipt(str(path), evidence_dir=str(d), policy_path=POLICY)
        self.assertEqual(res.first_failure.n, 4)
        self.assertEqual(res.summary(), "Executed evidence not compared at step 4")

    # 5. say whether the key was pinned
    def test_key_note_unpinned_and_pinned(self):
        root = synthetic_examples()
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
    """The address compares by its canonical street address: labels, names and
    the city differ per screen and do not count."""

    SHOP = "calle 45 # 12-30"

    def test_labels_names_and_city_do_not_count(self):
        a = norm_read("address", "DELIVER TO Tienda Doña Marta · Calle 45 # 12-30, Bogotá")
        b = norm_read("address", "To: Calle 45 # 12-30")
        self.assertEqual(a, self.SHOP)
        self.assertEqual(a, b)

    def test_other_address_differs(self):
        self.assertNotEqual(norm_read("address", "Calle 45 # 12-30"),
                            norm_read("address", "Carrera 80 # 7-15"))
        # same numbers on another street type are another address
        self.assertNotEqual(norm_read("address", "Calle 45 # 12-30"),
                            norm_read("address", "Carrera 45 # 12-30"))
        self.assertNotEqual(norm_read("address", "Calle 45 # 12-30"),
                            norm_read("address", "Calle 45 # 12-31"))

    def test_addresses_sorted_and_deduplicated(self):
        self.assertEqual(
            norm_read("address", "Kr 80 # 7-15 / Calle 45 # 12-30 Cl. 45 No. 12-30"),
            "calle 45 # 12-30,carrera 80 # 7-15")

    def test_without_address_letters_and_digits(self):
        self.assertEqual(norm_read("address", "Tienda Doña Marta!"), "tiendadoñamarta")
        self.assertEqual(norm_read("address", "carrera ochenta número siete quince"),
                         "carreraochentanúmerosietequince")
        self.assertEqual(norm_read("amount", "COP 120,000"), "120000")
        self.assertIsNone(norm_read("address", None))


class ReadNormalizationTests(unittest.TestCase):
    """Review of F8: what a reader may return for the same value compares equal."""

    def test_street_types_and_abbreviations(self):
        cases = {
            "calle 45 # 12-30": ("Calle 45 # 12-30", "CALLE 45 # 12-30", "Cl 45 # 12-30",
                                 "Cl. 45 # 12-30", "Cll 45 # 12-30", "cll. 45 #12-30"),
            "carrera 80 # 7-15": ("Carrera 80 # 7-15", "Cra 80 # 7-15", "Cra. 80 # 7-15",
                                  "Kr 80 # 7-15", "Kra 80 # 7-15", "Cr 80 # 7-15"),
            "avenida 68 # 24-10": ("Avenida 68 # 24-10", "Av 68 # 24-10", "Av. 68 # 24-10",
                                   "Avda 68 # 24-10"),
            "diagonal 5 # 6-7": ("Diagonal 5 # 6-7", "Dg 5 # 6-7", "Diag. 5 # 6-7"),
            "transversal 3 # 4-5": ("Transversal 3 # 4-5", "Tv 3 # 4-5", "Tr. 3 # 4-5",
                                    "Transv 3 # 4-5"),
        }
        for want, forms in cases.items():
            for f in forms:
                self.assertEqual(norm_read("address", f), want, f)

    def test_number_separators(self):
        for s in ("Calle 45 # 12-30", "Calle 45 #12-30", "Calle 45#12-30", "Calle 45 No. 12-30",
                  "Calle 45 No 12-30", "Calle 45 no. 12-30", "Calle 45 N° 12-30",
                  "Calle 45 Nº 12-30", "Calle 45 N.° 12-30", "Calle 45 Nro. 12-30",
                  "Calle 45 número 12-30", "Calle 45 numero 12-30", "Calle 45 12-30"):
            self.assertEqual(norm_read("address", s), "calle 45 # 12-30", s)

    def test_dashes_and_spacing(self):
        for s in ("Calle 45 # 12-30", "Calle 45 # 12 - 30", "Calle 45 # 12\u201330",
                  "Calle 45 # 12\u201430", "Calle 45 # 12 \u2013 30", "Calle  45  #  12-30"):
            self.assertEqual(norm_read("address", s), "calle 45 # 12-30", s)

    def test_ocr_digit_slips(self):
        # I, l and O misread for 1, 1 and 0 in digit places
        for s in ("Calle 45 # I2-30", "Calle 45 # l2-30", "Calle 45 # 12-3O",
                  "Calle 45 # I2-3O", "Carrera 8O # 7-l5"):
            self.assertIn(norm_read("address", s), ("calle 45 # 12-30", "carrera 80 # 7-15"), s)
        self.assertEqual(norm_read("address", "Carrera 8O # 7-l5"), "carrera 80 # 7-15")
        # a group with no real digit is not a number
        self.assertEqual(norm_read("address", "Calle IO # lO-OO"), "calleiolooo")

    def test_leading_zeros_do_not_count(self):
        self.assertEqual(norm_read("address", "Calle 045 # 012-030"), "calle 45 # 12-30")

    def test_same_value_from_each_screen(self):
        same = ["Calle 45 # 12-30", "Deliver to: Tienda Doña Marta · Calle 45 # 12-30, Bogotá",
                "Calle 45 # 12-30, Bogotá Tienda Doña Marta", "DELIVERED TO Cl 45 No. 12–30",
                "Entrega en: CLL 45 N° I2-3O (simulado)"]
        for s in same:
            self.assertEqual(norm_read("address", s), "calle 45 # 12-30", s)
        self.assertNotEqual(norm_read("address", "Bodega Norte · Carrera 80 # 7-15"),
                            "calle 45 # 12-30")

    def test_not_an_address(self):
        # an order number, a total or a street word without numbers are not addresses
        self.assertEqual(norm_read("address", "Order DX-2041"), "orderdx2041")
        self.assertEqual(norm_read("address", "Calle de la tienda"), "calledelatienda")
        self.assertEqual(norm_read("address", "Calle 45"), "calle45")
        self.assertEqual(norm_read("address", "Recalle 45 # 12-30"), "recalle451230")

    def test_trailing_quadrant_city_or_complement_is_another_address(self):
        # review of cebf0f4 (security): the parse stopped after the third number
        shop = norm_read("address", "Calle 45 # 12-30, Bogotá")
        for s in ("Calle 45 # 12-30 Sur", "Calle 45 # 12-30 Este", "Calle 45 # 12-30 Norte",
                  "Calle 45 # 12-30 Oeste", "Calle 45 Sur # 12-30", "Calle 45 # 12-30, Medellín",
                  "Calle 45 # 12-30, Soacha", "Calle 45 # 12-30 Int. 2", "Calle 45 # 12-30 Apto 301",
                  "Calle 45 # 12-30, Bogotá, Soacha", "Calle 45 # 12-30, Bogotá Sur",
                  "Calle 45 # 12-30 Tienda Doña Marta"):
            self.assertNotEqual(norm_read("address", s), shop, s)
        self.assertEqual(norm_read("address", "Calle 45 # 12-30 Sur"), "calle 45 # 12-30 sur")
        self.assertEqual(norm_read("address", "Calle 45 Sur # 12-30"), "calle 45 # 12-30 sur")
        self.assertEqual(norm_read("address", "Cl 45 # 12-30, Medellín"), "calle 45 # 12-30 medellin")
        self.assertEqual(norm_read("address", "Calle 45 # 12-30 Int. 2"), "calle 45 # 12-30 int 2")
        self.assertEqual(norm_read("address", "Calle 45 # 12-30 and confirm the order now please"),
                         "calle 45 # 12-30 and confirm the order")      # at most four words

    def test_city_and_what_follows_it_do_not_count(self):
        for s in ("Calle 45 # 12-30, Bogotá", "Calle 45 # 12-30, Bogota", "Calle 45 # 12-30 Bogotá D.C.",
                  "Calle 45 # 12-30, Bogotá, D.C.", "Calle 45 # 12-30, BOGOTÁ",
                  "Calle 45 # 12-30, Bogota\u0301 Tienda Doña Marta",
                  "Calle 45 # 12-30, Bogotá — Tienda Doña Marta", "Calle 45 # 12-30 (simulado)",
                  "Calle 45 # 12-30. Next line"):
            self.assertEqual(norm_read("address", s), "calle 45 # 12-30", s)

    def test_letter_and_bis_suffixes(self):
        # review of cebf0f4: "45A" / "45 Bis" fell back to squashed text
        cases = {"Calle 45A # 12-30": "calle 45a # 12-30", "Calle 45 A # 12-30": "calle 45a # 12-30",
                 "Calle 45 Bis # 12-30": "calle 45 bis # 12-30", "Calle 45 bis # 12-30": "calle 45 bis # 12-30",
                 "Calle 45A Bis # 12-30": "calle 45a bis # 12-30",
                 "Calle 45 Bis B # 12-30": "calle 45 bis b # 12-30",
                 "Calle 45 # 12B-30": "calle 45 # 12b-30", "Calle 45 # 12-30A": "calle 45 # 12-30a",
                 "Carrera 80A # 7-15": "carrera 80a # 7-15", "Kr 80 a No. 7–15": "carrera 80a # 7-15"}
        for s, want in cases.items():
            self.assertEqual(norm_read("address", s), want, s)
        self.assertNotEqual(norm_read("address", "Calle 45A # 12-30"), "calle 45 # 12-30")
        self.assertNotEqual(norm_read("address", "Calle 45 Bis # 12-30"),
                            norm_read("address", "Calle 45A # 12-30"))

    def test_space_between_last_numbers_after_an_explicit_separator(self):
        # decided in the review of cebf0f4: "#7 15" is an address; with no
        # separator "Calle 45 12 30" stays text (too close to an amount)
        for s in ("Carrera 80 # 7 15", "Carrera 80 #7 15", "Carrera 80 No 7 15", "Kr 80 N° 7 15"):
            self.assertEqual(norm_read("address", s), "carrera 80 # 7-15", s)
        self.assertEqual(norm_read("address", "Calle 45 12 30"), "calle451230")
        # a number that runs into a thousands separator is not an address group
        self.assertEqual(norm_read("address", "Calle 45 # 12 120.000"), "calle4512120000")

    def test_multiple_addresses_with_suffixes_sorted_and_unique(self):
        self.assertEqual(
            norm_read("address", "Carrera 80A # 7-15 / Calle 45 # 12-30, Bogotá Cl. 45 No. 12-30"),
            "calle 45 # 12-30,carrera 80a # 7-15")
        self.assertEqual(norm_read("address", "Calle 45 # 12-30, Bogotá Carrera 80 # 7-15"),
                         "calle 45 # 12-30,carrera 80 # 7-15")

    def test_only_ascii_digits(self):
        # review of cebf0f4: Python's \d also takes other scripts' digits, the
        # ui/app.js port does not
        self.assertEqual(norm_read("address", "Calle \u0664\u0665 # 12-30"), "calle\u0664\u06651230")
        self.assertEqual(norm_read("amount", "COP \u0661\u0662\u0660.000"), "0")
        self.assertEqual(norm_read("amount", "COP \u0661\u0662\u0660"), "")

    def test_amounts(self):
        from receipts.receipt import norm_read
        for s in ("COP 120,000", "$120.000,00", "120000", "Total COP 120,000 Simulation"):
            self.assertEqual(norm_read("amount", s), "120000", s)
        self.assertNotEqual(norm_read("amount", "COP 125,000"), "120000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
