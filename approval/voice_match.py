"""F7: does the spoken confirmation match what the pixels show?

The person reads the amount and recipient aloud. Voice Transcribe gives the
text (F7 live path); this module compares it — normalized — against the amount
and recipient **read from the pixels** (F4), never the DOM. The amount is
spoken in Spanish words and converted to a number.

Strict on purpose (a doubt is a "no"):
- the amount is exactly ONE continuous, well-formed number phrase ("ciento
  veinte mil", "un millón doscientos mil", or digits like "120.000"). A second
  separate number phrase ("cinco mil, ciento quince mil") or a malformed one
  ("veinte cien mil") is not a match;
- only the phrase before the recipient's name counts (after it, if nothing
  was said before), and account-like digit groups ("310 555 4417") are ignored,
  so reading the account aloud never changes the amount;
- a negation or cancel cue ("no", "no pagues", "cancela", "mejor no", "nunca",
  "detente") rejects the confirmation.

The voice confirms the recipient's NAME, not the account digits: the account
is checked by the pixels (F4/F5) and the signed policy (F1/F6).

Pure and offline: the transcription is real (a model), the comparison is code.
"""

import re
import unicodedata

# Spanish number words up to the hundreds, plus the thousand/million multipliers.
_UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
         "setenta": 70, "ochenta": 80, "noventa": 90}
_HUNDREDS = {"cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
             "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
             "setecientos": 700, "ochocientos": 800, "novecientos": 900,
             "doscientas": 200, "trescientas": 300, "cuatrocientas": 400,
             "quinientas": 500, "seiscientas": 600, "setecientas": 700,
             "ochocientas": 800, "novecientas": 900}
_MILLION = ("millon", "millones")
_SCALES = ("mil",) + _MILLION
_WORDS = set(_UNITS) | set(_TENS) | set(_HUNDREDS) | set(_SCALES)

MAX_AMOUNT = 999_999_999          # "novecientos noventa y nueve millones ..."

# Words that take the confirmation back. Any of them (outside the recipient's
# name) rejects it: "no", "no pagues", "mejor no", "cancela", "nunca", "detente".
NEGATIONS = frozenset({
    "no", "nunca", "jamas", "cancela", "cancelar", "cancelo", "cancelen", "cancelalo",
    "cancelado", "cancelada", "detente", "detener", "deten", "detenlo", "anula",
    "anular", "anulalo", "espera", "stop",
})

# An account read aloud in digits: 310-555-4417, 310 XXX 4417, 3105554417.
_ACCOUNT_RE = re.compile(r"(?<![\w])\d{3}[\s\-–—.]?[\dxX*]{3}[\s\-–—.]?\d{4}(?![\w])")


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize(text):
    text = strip_accents(str(text or "")).lower()
    return re.sub(r"[^a-z0-9\s]", " ", text)


def _join_digits(text):
    """Digits as a transcriber writes them: drop account-like groups, drop a
    2-digit decimal part, join thousands separators ("120.000" -> "120000")."""
    text = _ACCOUNT_RE.sub(" ", str(text or ""))
    text = re.sub(r"(?<=\d)[.,]\d{2}(?!\d)", "", text)
    return re.sub(r"(?<!\d)(\d{1,3})((?:[.,\s]\d{3})+)(?!\d)",
                  lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), text)


def tokens(text):
    return normalize(_join_digits(text)).split()


def _is_num(tok):
    return tok.isdigit() or tok in _WORDS


def number_phrases(toks):
    """Maximal runs of number tokens ("y" joins only between two of them). A
    lone "un"/"una" is the article ("un pago de ..."), not a number."""
    runs, cur = [], []
    for i, t in enumerate(toks):
        if _is_num(t):
            cur.append(t)
        elif (t == "y" and cur and i + 1 < len(toks) and _is_num(toks[i + 1])):
            cur.append(t)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if r not in (["un"], ["una"])]


def _below_1000(toks, i):
    """A 1-999 group in words at toks[i] -> (value, next index) or (None, i)."""
    n, start, v = len(toks), i, 0
    if i < n and toks[i] in _HUNDREDS:
        v += _HUNDREDS[toks[i]]
        i += 1
        if toks[start] == "cien":            # "cien" stands alone; "ciento" never does
            return v, i
    if i < n and toks[i] in _TENS:
        v += _TENS[toks[i]]
        i += 1
        if i + 1 < n and toks[i] == "y" and 1 <= _UNITS.get(toks[i + 1], 0) <= 9:
            v += _UNITS[toks[i + 1]]
            i += 2
    elif i < n and _UNITS.get(toks[i], 0) > 0:
        v += _UNITS[toks[i]]
        i += 1
    if i == start or (toks[start] == "ciento" and i == start + 1):
        return None, start
    return v, i


def parse_phrase(toks):
    """One number phrase (list of tokens) -> int, or None if malformed.
    [N millón|millones] [N mil] [N], N being 1-999 in words or a digit group."""
    n, i, total, used = len(toks), 0, 0, False

    def group(i):
        if i < n and toks[i].isdigit():
            return int(toks[i]), i + 1
        return _below_1000(toks, i)

    for scale, words in ((1_000_000, _MILLION), (1000, ("mil",))):
        v, j = group(i)
        if j < n and toks[j] in words:
            if v is None:
                if scale != 1000:
                    return None              # "millones" with no count
                v = 1                        # bare "mil"
            if v >= 1000:
                return None                  # "120000 mil"
            total += v * scale
            i, used = j + 1, True
    v, j = group(i)
    if v is not None:
        if used and v >= 1000:
            return None                      # "cinco mil 120000"
        total += v
        i, used = j, True
    if i != n or not used:
        return None
    return total


def _amount(toks):
    """(value or None, reason) from the tokens where the amount was said."""
    phrases = number_phrases(toks)
    if not phrases:
        return None, "no amount heard"
    if len(phrases) > 1:
        return None, "more than one number heard"
    v = parse_phrase(phrases[0])
    if v is None:
        return None, "the number heard is not well formed"
    return v, ""


def spanish_to_int(text):
    """Parse the one Spanish number phrase in `text` (up to 999,999,999), or
    None: no number, more than one separate number, or a malformed one.

    A transcriber may also write the number in digits with thousands
    separators ("120.000", "120,000", "$120 000"); those groups are joined
    first so they do not read as 120 + 0."""
    return _amount(tokens(text))[0]


def name_of(recipient_text):
    """The pixels read "Name · account"; the spoken confirmation uses the name."""
    return str(recipient_text or "").split("·")[0].split(" - ")[0].strip()


# Spanish names of consonant letters, for a one-letter word in a name
# ("Distribuidora X" is read aloud, and may be transcribed, as "Distribuidora
# equis"). Vowels and "de" are not letter names here: "a", "e", "o", "u", "de"
# are ordinary Spanish words and would match almost any sentence.
_LETTERS = {"be": "b", "ce": "c", "efe": "f", "ge": "g", "hache": "h", "jota": "j",
            "ka": "k", "ele": "l", "eme": "m", "ene": "n", "pe": "p", "cu": "q",
            "erre": "r", "ese": "s", "te": "t", "uve": "v", "equis": "x",
            "ye": "y", "zeta": "z"}


def _find_name(said, name):
    """Index where the name's words start in `said` (in order), or -1."""
    if not name:
        return -1

    def same(heard, want):
        return heard == want or (len(want) == 1 and _LETTERS.get(heard) == want)

    for i in range(len(said) - len(name) + 1):
        if all(same(said[i + j], w) for j, w in enumerate(name)):
            return i
    return -1


def recipient_matches(transcript, pixel_recipient_text):
    """True when the recipient NAME read from the pixels is spoken, word by
    word and in order (a one-letter word may be said by its consonant letter
    name). The account digits are not part of it."""
    return _find_name(tokens(transcript), normalize(name_of(pixel_recipient_text)).split()) >= 0


def heard_amount(transcript, pixel_recipient_text=None):
    """(value or None, reason). Only the amount phrase before the recipient's
    name counts; after it only when nothing was said before (so an account
    number read after the name cannot change the amount)."""
    toks = tokens(transcript)
    name = normalize(name_of(pixel_recipient_text)).split() if pixel_recipient_text else []
    at = _find_name(toks, name)
    if at < 0:
        return _amount(toks)
    before, after = toks[:at], toks[at + len(name):]
    if number_phrases(before):
        return _amount(before)
    return _amount(after)


def negated(transcript, pixel_recipient_text=None):
    """The negation/cancel words heard outside the recipient's name."""
    name = set(normalize(name_of(pixel_recipient_text)).split()) if pixel_recipient_text else set()
    return [t for t in normalize(transcript).split() if t in NEGATIONS and t not in name]


def amount_in_range(pixel_amount_cop):
    try:
        return 1 <= int(pixel_amount_cop) <= MAX_AMOUNT
    except (TypeError, ValueError):
        return False


def amount_check(transcript, pixel_amount_cop, pixel_recipient_text=None):
    """(ok, heard value or None, reason when not ok)."""
    if not amount_in_range(pixel_amount_cop):
        return False, None, "amount out of range (voice supports 1 to %s)" % format(MAX_AMOUNT, ",")
    v, why = heard_amount(transcript, pixel_recipient_text)
    if v is None:
        return False, None, why
    if v != int(pixel_amount_cop):
        return False, v, "heard a different amount"
    return True, v, ""


def amount_matches(transcript, pixel_amount_cop, pixel_recipient_text=None):
    """True when the one amount spoken equals the amount read from the pixels."""
    return amount_check(transcript, pixel_amount_cop, pixel_recipient_text)[0]


def voice_matches(transcript, pixel_amount_cop, pixel_recipient_text):
    """Both the amount and the recipient must match, with no negation.
    Returns (ok, detail)."""
    neg = negated(transcript, pixel_recipient_text)
    if neg:
        return False, "does not match: negation heard (%s)" % " ".join(neg)
    amt, _v, why = amount_check(transcript, pixel_amount_cop, pixel_recipient_text)
    rec = recipient_matches(transcript, pixel_recipient_text)
    if amt and rec:
        return True, "amount and recipient match"
    missing = []
    if not amt:
        missing.append("amount (%s)" % why)
    if not rec:
        missing.append("recipient")
    return False, "does not match: " + ", ".join(missing)
