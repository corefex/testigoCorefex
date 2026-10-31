"""F7: Spanish number parsing and voice-vs-pixels matching."""

import unittest

from .voice_match import (spanish_to_int, amount_matches, amount_check, address_matches,
                          name_of, voice_matches)


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
        self.assertEqual(spanish_to_int("un pedido de ciento veinte mil pesos"), 120000)

    def test_not_a_number(self):
        self.assertIsNone(spanish_to_int("Tienda Doña Marta"))
        self.assertIsNone(spanish_to_int(""))

    def test_street_address_is_not_a_number(self):
        # an address in digits or in words is dropped, never read as the amount
        self.assertIsNone(spanish_to_int("Calle 45 # 12-30"))
        self.assertIsNone(spanish_to_int("calle cuarenta y cinco número doce treinta"))
        self.assertEqual(spanish_to_int("ciento veinte mil, Cra 80 No. 7-15"), 120000)


class MatchTests(unittest.TestCase):
    AMOUNT = 120000
    ADDRESS = "Tienda Doña Marta · Calle 45 # 12-30, Bogotá"
    GOOD = "ciento veinte mil pesos, entrega en Tienda Doña Marta"

    def test_amount_matches(self):
        self.assertTrue(amount_matches(self.GOOD, self.AMOUNT))
        self.assertFalse(amount_matches("ciento cincuenta mil pesos, entrega en Tienda Doña Marta",
                                        self.AMOUNT))

    def test_destination_name_matches(self):
        self.assertTrue(address_matches(self.GOOD, self.ADDRESS))
        self.assertTrue(address_matches("entrega en tienda dona marta", self.ADDRESS))
        self.assertFalse(address_matches("ciento veinte mil pesos, entrega en Bodega Norte",
                                         self.ADDRESS))
        # whole words, in order: a longer or reordered name is not the same destination
        self.assertFalse(address_matches("entrega en Tienda Doña", self.ADDRESS))
        self.assertFalse(address_matches("Marta Doña Tienda", self.ADDRESS))

    def test_name_read_with_a_label_and_no_separator(self):
        # the reader may join the label, the name and the address on one line
        pixels = "DELIVER TO Tienda Doña Marta Calle 45 # 12-30, Bogotá"
        self.assertEqual(name_of(pixels), "Tienda Doña Marta")
        self.assertTrue(voice_matches(self.GOOD, self.AMOUNT, pixels)[0])

    def test_letter_said_by_name(self):
        self.assertTrue(address_matches("entrega en Bodega equis", "Bodega X · Calle 1 # 2-3"))
        self.assertTrue(address_matches("bodega, x.", "Bodega X · Calle 1 # 2-3"))
        self.assertFalse(address_matches("Bodega Xavier", "Bodega X · Calle 1 # 2-3"))

    def test_letter_names_are_consonants_only(self):
        # vowels and "de" are ordinary words; they never stand in for a letter
        self.assertFalse(address_matches("entrega en Tienda e", "Tienda A"))
        self.assertFalse(address_matches("entrega en Tienda a", "Tienda E"))
        self.assertFalse(address_matches("entrega en Tienda u", "Tienda O"))
        self.assertFalse(address_matches("ciento veinte mil pesos a Tienda de", "Tienda D"))
        self.assertTrue(address_matches("Tienda d", "Tienda D"))
        for word, letter in (("jota", "J"), ("ka", "K"), ("zeta", "Z"), ("be", "B"), ("ce", "C")):
            self.assertTrue(address_matches("entrega en Tienda " + word, "Tienda " + letter), word)

    def test_negation_rejects(self):
        for said in ("no, ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "no confirmes ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "no lo pidas, ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "cancela, ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "ciento veinte mil pesos, entrega en Tienda Doña Marta, mejor no",
                     "nunca ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "detente, ciento veinte mil pesos, entrega en Tienda Doña Marta",
                     "anula el pedido de ciento veinte mil pesos, entrega en Tienda Doña Marta"):
            ok, detail = voice_matches(said, self.AMOUNT, self.ADDRESS)
            self.assertFalse(ok, said)
            self.assertIn("negation", detail)

    def test_no_inside_a_street_address_is_not_a_negation(self):
        said = "ciento veinte mil pesos, entrega en Tienda Doña Marta, Calle 45 No. 12-30"
        self.assertTrue(voice_matches(said, self.AMOUNT, self.ADDRESS)[0])
        said = ("ciento veinte mil pesos, entrega en Tienda Doña Marta, calle cuarenta y cinco "
                "no doce treinta")
        self.assertTrue(voice_matches(said, self.AMOUNT, self.ADDRESS)[0])

    def test_two_amounts_never_sum(self):
        ok, detail = voice_matches("cinco mil, ciento quince mil, entrega en Tienda Doña Marta",
                                   self.AMOUNT, self.ADDRESS)
        self.assertFalse(ok)
        self.assertFalse(voice_matches("veinte cien mil pesos, entrega en Tienda Doña Marta",
                                       120000, self.ADDRESS)[0])

    def test_address_numbers_never_change_the_amount(self):
        for said in ("ciento veinte mil pesos, entrega en Tienda Doña Marta, Calle 45 # 12-30",
                     "ciento veinte mil pesos, entrega en Tienda Doña Marta, Cl 45 N° 12–30",
                     "ciento veinte mil pesos, entrega en Tienda Doña Marta, calle cuarenta y "
                     "cinco número doce treinta",
                     "ciento veinte mil a la calle 45 # 12-30, Tienda Doña Marta",
                     "ciento veinte mil a la calle cuarenta y cinco número doce treinta, "
                     "Tienda Doña Marta",
                     "entrega en Tienda Doña Marta calle cuarenta y cinco número doce treinta, "
                     "ciento veinte mil pesos"):
            self.assertTrue(voice_matches(said, self.AMOUNT, self.ADDRESS)[0], said)
        # an address said in words never adds to or replaces the amount
        for said in ("ciento cinco mil pesos, calle quince número doce treinta, Tienda Doña Marta",
                     "calle ciento veinte número uno dos, Tienda Doña Marta"):
            self.assertFalse(voice_matches(said, self.AMOUNT, self.ADDRESS)[0], said)
        # the amount said after the name still counts when nothing came before
        self.assertTrue(voice_matches("entrega en Tienda Doña Marta, ciento veinte mil",
                                      self.AMOUNT, self.ADDRESS)[0])

    def test_millions_and_out_of_range(self):
        self.assertTrue(voice_matches("un millón doscientos mil, entrega en Tienda Doña Marta",
                                      1200000, self.ADDRESS)[0])
        ok, _heard, why = amount_check("mil millones, entrega en Tienda Doña Marta",
                                       1_000_000_000, self.ADDRESS)
        self.assertFalse(ok)
        self.assertIn("out of range", why)
        self.assertIn("out of range", voice_matches("x", 1_000_000_000, self.ADDRESS)[1])

    def test_still_matching(self):
        self.assertTrue(voice_matches(self.GOOD, self.AMOUNT, self.ADDRESS)[0])
        self.assertTrue(voice_matches("120.000 pesos, entrega en tienda doña marta", self.AMOUNT,
                                      self.ADDRESS)[0])

    def test_voice_matches_both(self):
        ok, _ = voice_matches(self.GOOD, self.AMOUNT, self.ADDRESS)
        self.assertTrue(ok)

    def test_voice_mismatch_amount(self):
        ok, detail = voice_matches("ciento cincuenta mil pesos, entrega en Tienda Doña Marta",
                                   self.AMOUNT, self.ADDRESS)
        self.assertFalse(ok)
        self.assertIn("amount", detail)

    def test_voice_mismatch_destination(self):
        ok, detail = voice_matches("ciento veinte mil pesos, entrega en Bodega Norte",
                                   self.AMOUNT, self.ADDRESS)
        self.assertFalse(ok)
        self.assertIn("destination", detail)


if __name__ == "__main__":
    unittest.main()
