"""F1: building and signing a policy offline, and the voice path with a fake
Meta client (no network): schema refusal, address binding, signing."""

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
            "Solo pide con entrega en la tienda, máximo ciento cincuenta mil pesos por pedido",
            [{"name": "Tienda Doña Marta", "address": "Calle 45 # 12-30, Bogotá"}],
            150000, "new_address")

    def test_build_shape(self):
        p = Policy(self.d)
        self.assertEqual(p.deliver_only, [SHOP_RULE])
        self.assertEqual(p.max_per_order_cop, 150000)
        self.assertEqual(p.ask_before, "new_address")

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

    def test_address_binding_blocks_name_only_swap(self):
        p = Policy(self.d)
        self.assertTrue(p.address_allowed("Tienda Doña Marta · Calle 45 # 12-30, Bogotá"))
        self.assertTrue(p.address_allowed("DELIVER TO Tienda Doña Marta Cl. 45 No. 12–30"))
        self.assertFalse(p.address_allowed("Tienda Doña Marta · Carrera 80 # 7-15, Bogotá"))
        self.assertFalse(p.address_allowed("Bodega Norte · Calle 45 # 12-30, Bogotá"))


PHRASE = "Solo pide con entrega en la tienda, máximo ciento cincuenta mil pesos por pedido"
SHOP_RULE = {"name": "Tienda Doña Marta", "address": "Calle 45 # 12-30, Bogotá"}
DIRECTORY = {"Tienda Doña Marta": "Calle 45 # 12-30, Bogotá"}
GOOD = {"deliver_only": [{"name": "la tienda", "address": ""}],
        "max_amount_words": "ciento cincuenta mil pesos",
        "max_per_order_cop": 150000, "ask_before_new_address": False}


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
        self.assertEqual(p.deliver_only, [SHOP_RULE])
        self.assertEqual(p.max_per_order_cop, 150000)
        self.assertEqual(p.ask_before, "new_address")
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
        pol, _ = self.compile(GOOD, directory=None)   # the real shop profile (config)
        demo = load(Path(pc.__file__).with_name("marta.policy.yaml"))
        p = Policy(pol)
        self.assertEqual(p.deliver_only, demo.deliver_only)
        self.assertEqual(p.max_per_order_cop, demo.max_per_order_cop)
        self.assertEqual(p.ask_before, demo.ask_before)
        self.assertTrue(p.check_order("Tienda Doña Marta · Calle 45 # 12-30, Bogotá", 120000)[0])
        self.assertFalse(p.check_order("Tienda Doña Marta · Carrera 80 # 7-15, Bogotá", 120000)[0])
        self.assertFalse(p.check_order("Tienda Doña Marta · Calle 45 # 12-30, Bogotá", 160000)[0])

    def test_schema_refusals(self):
        bad = [
            "not json",
            None,                                              # reasoning ate max_tokens
            json.dumps([GOOD]),
            with_(extra="deliver anywhere"),
            {k: v for k, v in GOOD.items() if k != "max_amount_words"},
            with_(deliver_only="la tienda"),
            with_(deliver_only=[{"name": "la tienda"}]),
            with_(deliver_only=[{"name": "la tienda", "address": "", "note": "x"}]),
            with_(deliver_only=[{"name": "la tienda", "account": ""}]),
            with_(max_per_order_cop="150000"),
            with_(max_per_order_cop=150000.0),
            with_(max_per_order_cop=True),
            with_(ask_before_new_address="yes"),
            with_(deliver_only=[]),
        ]
        for extraction in bad:
            with self.subTest(extraction=extraction):
                with self.assertRaises(MandateRefused):
                    self.compile(extraction)

    def test_shop_named_in_full_compiles_the_same(self):
        t = ("Solo pide con entrega en Tienda Doña Marta, máximo ciento cincuenta mil pesos "
             "por pedido")
        for name in ("Tienda Doña Marta", "tienda dona marta"):
            pol, _ = self.compile(with_(deliver_only=[{"name": name, "address": ""}]), t)
            self.assertEqual(Policy(pol).deliver_only, [SHOP_RULE])
        t2 = "Pide solo para mi tienda, hasta 150.000 pesos por pedido"
        pol, _ = self.compile(with_(deliver_only=[{"name": "mi tienda", "address": ""}],
                                    max_amount_words="150.000 pesos"), t2)
        self.assertEqual(Policy(pol).deliver_only, [SHOP_RULE])

    def test_unknown_destination_refused(self):
        t = "Solo pide con entrega en Bodega Norte, máximo ciento cincuenta mil pesos por pedido"
        with self.assertRaises(MandateRefused) as cm:
            self.compile(with_(deliver_only=[{"name": "Bodega Norte",
                                              "address": "Carrera 80 # 7-15"}]), t)
        self.assertIn("shop profile", str(cm.exception))

    def test_destination_not_said_refused(self):
        # Spark may not add a destination the owner did not name
        with self.assertRaises(MandateRefused):
            self.compile(with_(deliver_only=[{"name": "la tienda", "address": ""},
                                             {"name": "Bodega Norte", "address": ""}]),
                         directory={**DIRECTORY, "Bodega Norte": "Carrera 80 # 7-15, Bogotá"})

    def test_address_bound_by_name(self):
        # a spoken address that matches is accepted (formatting aside); the stored one is the profile's
        t = ("Solo pide con entrega en la tienda, Calle 45 No. 12-30, "
             "máximo ciento cincuenta mil pesos por pedido")
        pol, _ = self.compile(with_(deliver_only=[{"name": "la tienda",
                                                   "address": "Cl 45 No. 12-30"}]), t)
        self.assertEqual(Policy(pol).deliver_only, [SHOP_RULE])
        # a different spoken address for the shop is refused
        with self.assertRaises(MandateRefused):
            self.compile(with_(deliver_only=[{"name": "la tienda",
                                              "address": "Carrera 80 # 7-15"}]))

    def test_address_never_comes_from_speech(self):
        # the extraction carries no address: the policy still binds the profile's address
        pol, _ = self.compile(GOOD)
        self.assertEqual(Policy(pol).deliver_only[0]["address"], "Calle 45 # 12-30, Bogotá")

    def test_amount_is_reparsed_from_the_words(self):
        with self.assertRaises(MandateRefused):                 # Spark's integer disagrees
            self.compile(with_(max_per_order_cop=1500000))
        with self.assertRaises(MandateRefused):                 # words not in the transcript
            self.compile(with_(max_amount_words="doscientos mil pesos", max_per_order_cop=200000))
        with self.assertRaises(MandateRefused):                 # no amount said
            self.compile(with_(max_amount_words="", max_per_order_cop=0))
        t = "Solo pide con entrega en la tienda, máximo 150.000 pesos por pedido"
        pol, _ = self.compile(with_(max_amount_words="150.000 pesos"), t)
        self.assertEqual(Policy(pol).max_per_order_cop, 150000)

    def test_parse_amount_cop(self):
        cases = {"ciento cincuenta mil pesos": 150000, "150 mil": 150000, "150.000": 150000,
                 "$150,000 COP": 150000, "doscientos treinta y cinco mil": 235000,
                 "noventa y nueve mil novecientos": 99900, "pesos": None,
                 "150 000 pesos": 150000, "un millón de pesos": None, "dos millones": None}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_amount_cop(text), want)

    def test_amount_must_be_said_as_a_maximum(self):
        # review F1-2: a number said for another reason is not the ceiling
        t = ("Solo pide con entrega en la tienda, máximo cincuenta mil pesos por pedido; "
             "el pedido de hoy es de 900 mil")
        with self.assertRaises(MandateRefused):
            self.compile(with_(max_amount_words="900 mil", max_per_order_cop=900000), t)
        pol, _ = self.compile(with_(max_amount_words="cincuenta mil pesos", max_per_order_cop=50000), t)
        self.assertEqual(Policy(pol).max_per_order_cop, 50000)
        t2 = "Pide con entrega en la tienda hasta 150.000 pesos"
        self.assertEqual(Policy(self.compile(with_(max_amount_words="150.000 pesos"), t2)[0])
                         .max_per_order_cop, 150000)

    def test_destination_in_a_negative_is_refused(self):
        for t in ("No pidas con entrega en la tienda, máximo ciento cincuenta mil pesos",
                  "Nunca entregues en la tienda, máximo ciento cincuenta mil pesos por pedido"):
            with self.subTest(t=t):
                with self.assertRaises(MandateRefused):
                    self.compile(GOOD, t)

    def test_million_ceiling_refused(self):
        t = "Solo pide con entrega en la tienda, máximo un millón de pesos por pedido"
        with self.assertRaises(MandateRefused):
            self.compile(with_(max_amount_words="un millón de pesos",
                               max_per_order_cop=1000000), t)

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
        self.assertEqual(p.deliver_only[0]["address"], "Calle 45 # 12-30, Bogotá")

    def test_no_confirmation_writes_nothing(self):
        rc, out, _ = self.run_cli(GOOD, confirm_answer="n")
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())

    def test_stamp_updates_a_dumped_policy(self):
        # review F1-1: yaml.safe_dump writes sha256/signature unquoted
        rc, out, key = self.run_cli(GOOD)
        out.write_text(out.read_text().replace("150000", "120000"))
        self.assertFalse(load(out).hash_matches_stored())
        pc._stamp_file(out, key)
        p = load(out)
        self.assertTrue(p.hash_matches_stored())
        self.assertTrue(p.signature_valid(keys.public_from_seed(keys.load_seed(key))))

    def test_refused_extraction_writes_nothing(self):
        rc, out, _ = self.run_cli(with_(max_per_order_cop=999999999), extra=["--yes"])
        self.assertEqual(rc, 1)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
