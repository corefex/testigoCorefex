"""F7: Spanish number parsing and voice-vs-pixels matching."""

import unittest

from .voice_match import spanish_to_int, amount_matches, recipient_matches, voice_matches


class SpanishNumberTests(unittest.TestCase):
    def test_demo_amounts(self):
        self.assertEqual(spanish_to_int("ciento veinte mil pesos"), 120000)
        self.assertEqual(spanish_to_int("ciento cincuenta mil"), 150000)

    def test_range(self):
        self.assertEqual(spanish_to_int("veinte"), 20)
        self.assertEqual(spanish_to_int("doscientos treinta y cuatro"), 234)
        self.assertEqual(spanish_to_int("mil"), 1000)
        self.assertEqual(spanish_to_int("quinientos mil"), 500000)

    def test_accents_and_noise(self):
        self.assertEqual(spanish_to_int("ciento veinte mil"), 120000)
        self.assertEqual(spanish_to_int("son ciento veinte mil pesos colombianos"), 120000)

    def test_digits_with_thousands_separators(self):
        # what a transcriber may write instead of words
        for said in ("120.000 pesos", "120,000", "$120 000 pesos", "120000", "120 mil"):
            self.assertEqual(spanish_to_int(said), 120000, said)

    def test_not_a_number(self):
        self.assertIsNone(spanish_to_int("Distribuidora X"))
        self.assertIsNone(spanish_to_int(""))


class MatchTests(unittest.TestCase):
    AMOUNT = 120000
    RECIPIENT = "Distribuidora X · 310-XXX-4417"
    GOOD = "ciento veinte mil pesos a Distribuidora X"

    def test_amount_matches(self):
        self.assertTrue(amount_matches(self.GOOD, self.AMOUNT))
        self.assertFalse(amount_matches("ciento cincuenta mil pesos a Distribuidora X", self.AMOUNT))

    def test_recipient_matches(self):
        self.assertTrue(recipient_matches(self.GOOD, self.RECIPIENT))
        self.assertFalse(recipient_matches("ciento veinte mil pesos a otra tienda", self.RECIPIENT))

    def test_recipient_letter_said_by_name(self):
        self.assertTrue(recipient_matches("ciento veinte mil a Distribuidora equis", self.RECIPIENT))
        self.assertTrue(recipient_matches("distribuidora, x.", self.RECIPIENT))
        # whole words, in order: a longer name is not the same recipient
        self.assertFalse(recipient_matches("Distribuidora Xavier", self.RECIPIENT))
        self.assertFalse(recipient_matches("X Distribuidora", self.RECIPIENT))

    def test_voice_matches_both(self):
        ok, _ = voice_matches(self.GOOD, self.AMOUNT, self.RECIPIENT)
        self.assertTrue(ok)

    def test_voice_mismatch_amount(self):
        ok, detail = voice_matches("ciento cincuenta mil pesos a Distribuidora X",
                                   self.AMOUNT, self.RECIPIENT)
        self.assertFalse(ok)
        self.assertIn("amount", detail)

    def test_voice_mismatch_recipient(self):
        ok, detail = voice_matches("ciento veinte mil pesos a otra cuenta",
                                   self.AMOUNT, self.RECIPIENT)
        self.assertFalse(ok)
        self.assertIn("recipient", detail)


if __name__ == "__main__":
    unittest.main()
