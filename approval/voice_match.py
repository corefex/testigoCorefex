"""F7: does the spoken confirmation match what the pixels show?

The person reads the amount and recipient aloud. Voice Transcribe gives the
text (F7 live path); this module compares it — normalized — against the amount
and recipient **read from the pixels** (F4), never the DOM. The amount is
spoken in Spanish words and converted to a number.

Pure and offline: the transcription is real (a model), the comparison is code.
"""

import re
import unicodedata

# Spanish number words up to the hundreds, plus the thousand multiplier.
_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiun": 21, "veintiuno": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
         "setenta": 70, "ochenta": 80, "noventa": 90}
_HUNDREDS = {"cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
             "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
             "setecientos": 700, "ochocientos": 800, "novecientos": 900}


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize(text):
    text = strip_accents(str(text or "")).lower()
    return re.sub(r"[^a-z0-9\s]", " ", text)


def spanish_to_int(text):
    """Parse a Spanish number phrase (0–999,999) into an int, or None.

    A transcriber may also write the number in digits with thousands
    separators ("120.000", "120,000", "$120 000"); those groups are joined
    first so they do not read as 120 + 0."""
    text = re.sub(r"(?<=\d)[.,\s](?=\d{3}(?!\d))", "", str(text or ""))
    tokens = [t for t in normalize(text).split() if t and t != "y"]
    if not tokens:
        return None
    total, current, seen = 0, 0, False
    for tok in tokens:
        if tok.isdigit():
            current += int(tok); seen = True
        elif tok in _UNITS:
            current += _UNITS[tok]; seen = True
        elif tok in _TENS:
            current += _TENS[tok]; seen = True
        elif tok in _HUNDREDS:
            current += _HUNDREDS[tok]; seen = True
        elif tok == "mil":
            current = current or 1
            total += current * 1000; current = 0; seen = True
        # pesos / moneda words and anything else are ignored
    if not seen:
        return None
    return total + current


def amount_matches(transcript, pixel_amount_cop):
    """True when the number spoken equals the amount read from the pixels."""
    spoken = spanish_to_int(transcript)
    return spoken is not None and spoken == int(pixel_amount_cop)


# Spanish names of letters, for a one-letter word in a name ("Distribuidora
# X" is read aloud, and may be transcribed, as "Distribuidora equis").
_LETTERS = {"a": "a", "be": "b", "ce": "c", "de": "d", "e": "e", "efe": "f",
            "ge": "g", "hache": "h", "i": "i", "jota": "j", "ka": "k", "ele": "l",
            "eme": "m", "ene": "n", "o": "o", "pe": "p", "cu": "q", "erre": "r",
            "ese": "s", "te": "t", "u": "u", "uve": "v", "equis": "x", "ye": "y",
            "zeta": "z"}


def recipient_matches(transcript, pixel_recipient_text):
    """True when the recipient name read from the pixels is spoken, word by
    word and in order (a one-letter word may be said by its letter name)."""
    said = normalize(transcript).split()
    name = normalize(name_of(pixel_recipient_text)).split()
    if not name:
        return False

    def same(heard, want):
        return heard == want or (len(want) == 1 and _LETTERS.get(heard) == want)

    return any(all(same(said[i + j], w) for j, w in enumerate(name))
               for i in range(len(said) - len(name) + 1))


def name_of(recipient_text):
    """The pixels read "Name · account"; the spoken confirmation uses the name."""
    return str(recipient_text or "").split("·")[0].split(" - ")[0].strip()


def voice_matches(transcript, pixel_amount_cop, pixel_recipient_text):
    """Both the amount and the recipient must match. Returns (ok, detail)."""
    amt = amount_matches(transcript, pixel_amount_cop)
    rec = recipient_matches(transcript, pixel_recipient_text)
    if amt and rec:
        return True, "amount and recipient match"
    missing = []
    if not amt:
        missing.append("amount")
    if not rec:
        missing.append("recipient")
    return False, "does not match: " + ", ".join(missing)
