"""F7: Spanish number parsing and voice-vs-pixels matching."""

import unittest

from .voice_match import (spanish_to_int, amount_matches, amount_check, recipient_matches,
                          voice_matches)


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

    def test_millions(self):
        self.assertEqual(spanish_to_int("un millón doscientos mil"), 1200000)
        self.assertEqual(spanish_to_int("dos millones"), 2000000)
        self.assertEqual(spanish_to_int("1.200.000 pesos"), 1200000)
        self.assertEqual(spanish_to_int("tres millones cuarenta y cinco mil seiscientos"), 3045600)

    def test_one_well_formed_phrase_only(self):
        # two separate numbers are not one amount, even if the sum would match
        self.assertIsNone(spanish_to_int("cinco mil, ciento quince mil"))
        self.assertIsNone(spanish_to_int("cinco mil pesos y ciento quince mil"))
        self.assertIsNone(spanish_to_int("ciento veinte mil o ciento cincuenta mil"))
        # malformed
        for said in ("veinte cien mil", "ciento mil", "cien veinte", "mil mil", "millones",
                     "veinte y cinco", "cinco mil 120000"):
            self.assertIsNone(spanish_to_int(said), said)
        # the article "un" is not a second number
        self.assertEqual(spanish_to_int("un pago de ciento veinte mil pesos"), 120000)

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

    def test_letter_names_are_consonants_only(self):
        # vowels and "de" are ordinary words; they never stand in for a letter
        self.assertFalse(recipient_matches("pago a Tienda e", "Tienda A"))
        self.assertFalse(recipient_matches("pago a Tienda a", "Tienda E"))
        self.assertFalse(recipient_matches("pago a Tienda u", "Tienda O"))
        self.assertFalse(recipient_matches("ciento veinte mil pesos a Tienda de", "Tienda D"))
        self.assertTrue(recipient_matches("Tienda d", "Tienda D"))
        for word, letter in (("jota", "J"), ("ka", "K"), ("zeta", "Z"), ("be", "B"), ("ce", "C")):
            self.assertTrue(recipient_matches("a Tienda " + word, "Tienda " + letter), word)

    def test_negation_rejects(self):
        for said in ("no, ciento veinte mil pesos a Distribuidora X",
                     "no pagues ciento veinte mil pesos a Distribuidora X",
                     "cancela, ciento veinte mil pesos a Distribuidora X",
                     "ciento veinte mil pesos a Distribuidora X, mejor no",
                     "nunca ciento veinte mil pesos a Distribuidora X",
                     "detente, ciento veinte mil pesos a Distribuidora X"):
            ok, detail = voice_matches(said, self.AMOUNT, self.RECIPIENT)
            self.assertFalse(ok, said)
            self.assertIn("negation", detail)

    def test_two_amounts_never_sum(self):
        ok, detail = voice_matches("cinco mil, ciento quince mil a Distribuidora X", self.AMOUNT,
                                   self.RECIPIENT)
        self.assertFalse(ok)
        self.assertFalse(voice_matches("veinte cien mil pesos a Distribuidora X", 120000,
                                       self.RECIPIENT)[0])

    def test_account_digits_after_the_name_do_not_change_the_amount(self):
        for said in ("ciento veinte mil pesos a Distribuidora X cuenta tres uno cero",
                     "ciento veinte mil pesos a Distribuidora X, 310 555 4417",
                     "ciento veinte mil pesos a Distribuidora X 310-XXX-4417",
                     "ciento veinte mil a la cuenta 310 555 4417 de Distribuidora X"):
            self.assertTrue(voice_matches(said, self.AMOUNT, self.RECIPIENT)[0], said)
        # the amount said after the name still counts when nothing came before
        self.assertTrue(voice_matches("a Distribuidora X ciento veinte mil", self.AMOUNT,
                                      self.RECIPIENT)[0])

    def test_millions_and_out_of_range(self):
        self.assertTrue(voice_matches("un millón doscientos mil a Distribuidora X", 1200000,
                                      self.RECIPIENT)[0])
        ok, _heard, why = amount_check("mil millones a Distribuidora X", 1_000_000_000,
                                       self.RECIPIENT)
        self.assertFalse(ok)
        self.assertIn("out of range", why)
        self.assertIn("out of range", voice_matches("x", 1_000_000_000, self.RECIPIENT)[1])

    def test_still_matching(self):
        self.assertTrue(voice_matches(self.GOOD, self.AMOUNT, self.RECIPIENT)[0])
        self.assertTrue(voice_matches("120.000 pesos a Distribuidora equis", self.AMOUNT,
                                      self.RECIPIENT)[0])

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
