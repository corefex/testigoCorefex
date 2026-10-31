"""F1: building and signing a policy offline, and the voice path with a fake
Meta client (no network): schema refusal, account binding, signing."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from interceptor.policy import Policy, load
from policy import compile as pc
from policy.compile import (MandateRefused, build_policy_dict, compile_mandate,
                            parse_amount_cop, sign_policy_dict, to_yaml)
from receipts import keys


class CompileTests(unittest.TestCase):
    def setUp(self):
        self.d = build_policy_dict(
            "Solo puedes pagarle a Distribuidora X, máximo ciento cincuenta mil pesos",
            [{"name": "Distribuidora X", "account": "310-XXX-4417"}],
            150000, "new_recipient")

    def test_build_shape(self):
        p = Policy(self.d)
        self.assertEqual(p.pay_only, [{"name": "Distribuidora X", "account": "310-XXX-4417"}])
        self.assertEqual(p.max_per_payment_cop, 150000)
        self.assertEqual(p.ask_before, "new_recipient")

    def test_sign_and_verify(self):
        seed = keys.generate_seed()
        signed, p = sign_policy_dict(self.d, seed)
        self.assertTrue(p.hash_matches_stored())
        self.assertTrue(p.signature_valid(keys.public_from_seed(seed)))
        self.assertFalse(p.signature_valid(keys.public_from_seed(keys.generate_seed())))

    def test_roundtrip_through_yaml(self):
        import yaml
        seed = keys.generate_seed()
        signed, _ = sign_policy_dict(self.d, seed)
        reloaded = Policy(yaml.safe_load(to_yaml(signed)))
        self.assertTrue(reloaded.hash_matches_stored())
        self.assertTrue(reloaded.signature_valid(keys.public_from_seed(seed)))

    def test_account_binding_blocks_name_only_swap(self):
        p = Policy(self.d)
        self.assertTrue(p.recipient_allowed("Distribuidora X · 310-XXX-4417"))
        self.assertFalse(p.recipient_allowed("Distribuidora X · 300-XXX-0000"))


PHRASE = "Solo puedes pagarle a Distribuidora X, máximo ciento cincuenta mil pesos"
DIRECTORY = {"Distribuidora X": "310-XXX-4417"}
GOOD = {"pay_only": [{"name": "Distribuidora X", "account": ""}],
        "max_amount_words": "ciento cincuenta mil pesos",
        "max_per_payment_cop": 150000, "ask_before_new_recipient": False}


class FakeMeta:
    """Stands in for common.meta_client.MetaClient: canned transcript and Spark JSON."""

    def __init__(self, extraction, transcript=PHRASE):
        self.content = extraction if isinstance(extraction, (str, type(None))) else json.dumps(extraction)
        self.transcript = transcript
        self.calls = []

    def transcribe(self, audio_path, language="es"):
        self.calls.append(("transcribe", audio_path))
        return self.transcript, 900, 4.2

    def chat(self, tool, messages, **kw):
        self.calls.append(("chat", tool, messages, kw))
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)]), 1500


def with_(**changes):
    d = json.loads(json.dumps(GOOD))
    d.update(changes)
    return d


class MandateTests(unittest.TestCase):
    def compile(self, extraction, transcript=PHRASE, directory=DIRECTORY):
        return compile_mandate(FakeMeta(extraction, transcript), audio_path="m.wav",
                               directory=directory)

    def test_phrase_compiles_to_the_demo_rules(self):
        meta = FakeMeta(GOOD)
        pol, info = compile_mandate(meta, audio_path="m.wav", directory=DIRECTORY)
        p = Policy(pol)
        self.assertEqual(p.transcript, PHRASE)
        self.assertEqual(p.pay_only, [{"name": "Distribuidora X", "account": "310-XXX-4417"}])
        self.assertEqual(p.max_per_payment_cop, 150000)
        self.assertEqual(p.ask_before, "new_recipient")
        self.assertFalse(info["ask_before_said"])
        # Spark is asked for a strict schema, low effort, room for reasoning tokens
        _, tool, messages, kw = meta.calls[1]
        self.assertEqual(tool, "spark")
        self.assertEqual(kw["response_format"]["type"], "json_schema")
        self.assertTrue(kw["response_format"]["json_schema"]["strict"])
        self.assertEqual(kw["reasoning_effort"], "low")
        self.assertGreaterEqual(kw["max_tokens"], 16000)
        # the transcript travels as quoted data, not as the instruction
        self.assertIn(json.dumps(PHRASE, ensure_ascii=False), messages[-1]["content"])

    def test_same_rules_as_the_demo_policy_file(self):
        pol, _ = self.compile(GOOD, directory=None)   # the real directory (portal)
        demo = load(Path(pc.__file__).with_name("marta.policy.yaml"))
        p = Policy(pol)
        self.assertEqual(p.pay_only, demo.pay_only)
        self.assertEqual(p.max_per_payment_cop, demo.max_per_payment_cop)
        self.assertEqual(p.ask_before, demo.ask_before)
        self.assertTrue(p.check_payment("Distribuidora X · 310-XXX-4417", 120000)[0])
        self.assertFalse(p.check_payment("Distribuidora X · 300-XXX-0000", 120000)[0])

    def test_schema_refusals(self):
        bad = [
            "not json",
            None,                                              # reasoning ate max_tokens
            json.dumps([GOOD]),
            with_(extra="pay everyone"),
            {k: v for k, v in GOOD.items() if k != "max_amount_words"},
            with_(pay_only="Distribuidora X"),
            with_(pay_only=[{"name": "Distribuidora X"}]),
            with_(pay_only=[{"name": "Distribuidora X", "account": "", "note": "x"}]),
            with_(max_per_payment_cop="150000"),
            with_(max_per_payment_cop=150000.0),
            with_(max_per_payment_cop=True),
            with_(ask_before_new_recipient="yes"),
            with_(pay_only=[]),
        ]
        for extraction in bad:
            with self.subTest(extraction=extraction):
                with self.assertRaises(MandateRefused):
                    self.compile(extraction)

    def test_unknown_supplier_refused(self):
        t = "Solo puedes pagarle a Proveedor Z, máximo ciento cincuenta mil pesos"
        with self.assertRaises(MandateRefused) as cm:
            self.compile(with_(pay_only=[{"name": "Proveedor Z", "account": "300-XXX-0000"}]), t)
        self.assertIn("directory", str(cm.exception))

    def test_supplier_not_said_refused(self):
        # Spark may not add a supplier the owner did not name
        with self.assertRaises(MandateRefused):
            self.compile(with_(pay_only=[{"name": "Distribuidora X", "account": ""},
                                         {"name": "Distribuidora Y", "account": ""}]),
                         directory={**DIRECTORY, "Distribuidora Y": "311-XXX-0001"})

    def test_account_bound_by_name(self):
        # a spoken account that matches is accepted (formatting aside); the stored one is the directory's
        pol, _ = self.compile(with_(pay_only=[{"name": "distribuidora equis", "account": "310 XXX 4417"}]),
                              "Solo puedes pagarle a distribuidora equis, máximo ciento cincuenta mil pesos")
        self.assertEqual(Policy(pol).pay_only, [{"name": "Distribuidora X", "account": "310-XXX-4417"}])
        # a different spoken account for a known name is refused
        with self.assertRaises(MandateRefused):
            self.compile(with_(pay_only=[{"name": "Distribuidora X", "account": "300-XXX-0000"}]))

    def test_amount_is_reparsed_from_the_words(self):
        with self.assertRaises(MandateRefused):                 # Spark's integer disagrees
            self.compile(with_(max_per_payment_cop=1500000))
        with self.assertRaises(MandateRefused):                 # words not in the transcript
            self.compile(with_(max_amount_words="doscientos mil pesos", max_per_payment_cop=200000))
        with self.assertRaises(MandateRefused):                 # no amount said
            self.compile(with_(max_amount_words="", max_per_payment_cop=0))
        t = "Solo puedes pagarle a Distribuidora X, máximo 150.000 pesos"
        pol, _ = self.compile(with_(max_amount_words="150.000 pesos"), t)
        self.assertEqual(Policy(pol).max_per_payment_cop, 150000)

    def test_parse_amount_cop(self):
        cases = {"ciento cincuenta mil pesos": 150000, "150 mil": 150000, "150.000": 150000,
                 "$150,000 COP": 150000, "doscientos treinta y cinco mil": 235000,
                 "noventa y nueve mil novecientos": 99900, "pesos": None}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_amount_cop(text), want)

    def test_text_path_skips_voice(self):
        meta = FakeMeta(GOOD)
        compile_mandate(meta, transcript=PHRASE, directory=DIRECTORY)
        self.assertEqual([c[0] for c in meta.calls], ["chat"])


class MandateCliTests(unittest.TestCase):
    def run_cli(self, extraction, confirm_answer="s", extra=()):
        tmp = Path(tempfile.mkdtemp())
        out, key = tmp / "p.policy.yaml", tmp / "owner.key"
        args = pc.build_parser().parse_args(
            ["mandate", "m.wav", "--out", str(out), "--key", str(key), *extra])
        rc = pc.cmd_mandate(args, meta=FakeMeta(extraction), confirm=lambda: confirm_answer)
        return rc, out, key

    def test_signed_file_with_hash_and_valid_signature(self):
        rc, out, key = self.run_cli(GOOD)
        self.assertEqual(rc, 0)
        p = load(out)
        self.assertTrue(p.hash_matches_stored())
        self.assertTrue(p.signature_valid(keys.public_from_seed(keys.load_seed(key))))
        self.assertEqual(p.signed_by, "owner-key:marta")
        self.assertEqual(p.pay_only[0]["account"], "310-XXX-4417")

    def test_no_confirmation_writes_nothing(self):
        rc, out, _ = self.run_cli(GOOD, confirm_answer="n")
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())

    def test_refused_extraction_writes_nothing(self):
        rc, out, _ = self.run_cli(with_(max_per_payment_cop=999999999), extra=["--yes"])
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
