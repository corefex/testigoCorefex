"""F7: does the spoken confirmation match what the pixels show?

The person reads the order total and the delivery destination aloud («ciento
veinte mil pesos, entrega en Tienda Doña Marta»). Voice Transcribe gives the
text (F7 live path); this module compares it — normalized — against the amount
and the "Deliver to" text **read from the pixels** (F4), never the DOM. The
amount is spoken in Spanish words and converted to a number.

Strict on purpose (a doubt is a "no"):
- the amount is exactly ONE continuous, well-formed number phrase ("ciento
  veinte mil", "un millón doscientos mil", or digits like "120.000"). A second
  separate number phrase ("cinco mil, ciento quince mil") or a malformed one
  ("veinte cien mil") is not a match;
- only the phrase before the destination's name counts (after it, if nothing
  was said before), and street addresses are ignored, in digits ("Calle 45 #
  12-30") or in words ("calle cuarenta y cinco número doce treinta"), so
  reading the address aloud never changes the amount;
- a negation or cancel cue ("no", "no confirmes", "no lo pidas", "cancela",
  "mejor no", "nunca", "detente") rejects the confirmation.

The voice confirms the destination's NAME, not the address digits: the address
is checked by the pixels (F4/F5) and the signed policy (F1/F6).

Pure and offline: the transcription is real (a model), the comparison is code.
"""

import re
import unicodedata

from common.address import ADDRESS_RE, STREET_TYPES

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

# Words that take the confirmation back. Any of them (outside the destination's
# name) rejects it: "no", "no confirmes", "no lo pidas", "mejor no", "cancela",
# "nunca", "detente".
NEGATIONS = frozenset({
    "no", "nunca", "jamas", "cancela", "cancelar", "cancelo", "cancelen", "cancelalo",
    "cancelado", "cancelada", "detente", "detener", "deten", "detenlo", "anula",
    "anular", "anulalo", "espera", "stop",
})

# A street address read aloud in words: the street type, then its numbers
# ("calle cuarenta y cinco número doce treinta"). Dropped with its numbers.
_STREET_WORDS = frozenset(STREET_TYPES)
_ADDRESS_JOINERS = ("numero", "nro", "guion", "con")


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def normalize(text):
    text = strip_accents(str(text or "")).lower()
    return re.sub(r"[^a-z0-9\s]", " ", text)


# A street address in digits as a transcriber may write it without "#" or a
# dash: the street word and up to three 1-3 digit groups ("calle 45 12 30").
# A group never runs into a thousands separator ("calle 45 120.000" keeps
# "120.000"). Removed before thousands are joined, so "30 120.000" is never
# read as 30120000.
_DIGIT_ADDRESS_RE = re.compile(
    r"(?<!\w)(?ai:%s)\.?(?:[\s,]*(?:#|(?ai:no|nro|n)\.?|[º°]|(?ai:n[uú]mero)|-)?[\s,]*"
    r"[0-9]{1,3}(?:[A-Za-z](?!\w))?(?![0-9]|[.,][0-9])){1,3}"
    % "|".join(sorted(STREET_TYPES, key=len, reverse=True)))


def _join_digits(text):
    """Digits as a transcriber writes them: drop street addresses ("Calle 45 #
    12-30", "calle 45 12 30"), drop a 2-digit decimal part, join thousands
    separators ("120.000" -> "120000")."""
    text = ADDRESS_RE.sub(" ", str(text or ""))
    text = _DIGIT_ADDRESS_RE.sub(" ", text)
    text = re.sub(r"(?<=\d)[.,]\d{2}(?!\d)", "", text)
    return re.sub(r"(?<!\d)(\d{1,3})((?:[.,\s]\d{3})+)(?!\d)",
                  lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), text)


def tokens(text):
    return _drop_spoken_addresses(normalize(_join_digits(text)).split())


def _drop_spoken_addresses(toks):
    """Remove a street word and the (up to three) small numbers that follow it
    ("calle cuarenta y cinco numero doce treinta"): an address is never part of
    the amount. Each number is 1-999, in words or digits, never "mil"."""
    out, i, n = [], 0, len(toks)
    while i < n:
        if toks[i] in _STREET_WORDS:
            j, groups = i + 1, 0
            while groups < 3:
                k = j
                if k < n and (toks[k] in _ADDRESS_JOINERS or
                              (toks[k] in ("no", "n") and groups == 1)):
                    k += 1
                v, nxt = _small_group(toks, k)
                if v is None:
                    break
                j, groups = nxt, groups + 1
            if groups:
                i = j
                continue
        out.append(toks[i])
        i += 1
    return out


def _small_group(toks, i):
    """A 1-999 number at toks[i] (words or digits) not followed by a scale."""
    if i < len(toks) and toks[i].isdigit():
        v, nxt = (int(toks[i]), i + 1) if int(toks[i]) < 1000 else (None, i)
    else:
        v, nxt = _below_1000(toks, i)
    if v is None or (nxt < len(toks) and toks[nxt] in _SCALES):
        return None, i
    return v, nxt


def _is_num(tok):
    return tok.isdigit() or tok in _WORDS


def number_phrases(toks):
    """Maximal runs of number tokens ("y" joins only between two of them). A
    lone "un"/"una" is the article ("un pedido de ..."), not a number."""
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


_LABEL_RE = re.compile(r"^\s*(?:deliver(?:y)? to|ship to|entregar en|entrega en|enviar a)\s*:?\s*",
                       re.IGNORECASE)


def name_of(address_text):
    """The pixels read "Name · address" (maybe after a "Deliver to" label); the
    spoken confirmation uses the name: what comes before "·", " - " or the
    street address."""
    text = str(address_text or "")
    m = ADDRESS_RE.search(text)
    if m:
        text = text[:m.start()]
    text = text.split("·")[0].split(" - ")[0]
    return _LABEL_RE.sub("", text).strip(" ,;:")


# Spanish names of consonant letters, for a one-letter word in a name
# ("Bodega X" is read aloud, and may be transcribed, as "Bodega equis"). Vowels and "de" are not letter names here: "a", "e", "o", "u", "de"
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


def address_matches(transcript, pixel_address_text):
    """True when the destination NAME read from the pixels is spoken, word by
    word and in order (a one-letter word may be said by its consonant letter
    name). The address digits are not part of it."""
    return _find_name(tokens(transcript), normalize(name_of(pixel_address_text)).split()) >= 0


def heard_amount(transcript, pixel_address_text=None):
    """(value or None, reason). Only the amount phrase before the destination's
    name counts; after it only when nothing was said before (so an address
    read after the name cannot change the amount)."""
    toks = tokens(transcript)
    name = normalize(name_of(pixel_address_text)).split() if pixel_address_text else []
    at = _find_name(toks, name)
    if at < 0:
        return _amount(toks)
    before, after = toks[:at], toks[at + len(name):]
    if number_phrases(before):
        return _amount(before)
    return _amount(after)


def negated(transcript, pixel_address_text=None):
    """The negation/cancel words heard outside the destination's name (a "No."
    inside a street address is not one)."""
    name = set(normalize(name_of(pixel_address_text)).split()) if pixel_address_text else set()
    return [t for t in tokens(transcript) if t in NEGATIONS and t not in name]


def amount_in_range(pixel_amount_cop):
    try:
        return 1 <= int(pixel_amount_cop) <= MAX_AMOUNT
    except (TypeError, ValueError):
        return False


def amount_check(transcript, pixel_amount_cop, pixel_address_text=None):
    """(ok, heard value or None, reason when not ok)."""
    if not amount_in_range(pixel_amount_cop):
        return False, None, "amount out of range (voice supports 1 to %s)" % format(MAX_AMOUNT, ",")
    v, why = heard_amount(transcript, pixel_address_text)
    if v is None:
        return False, None, why
    if v != int(pixel_amount_cop):
        return False, v, "heard a different amount"
    return True, v, ""


def amount_matches(transcript, pixel_amount_cop, pixel_address_text=None):
    """True when the one amount spoken equals the amount read from the pixels."""
    return amount_check(transcript, pixel_amount_cop, pixel_address_text)[0]


def voice_matches(transcript, pixel_amount_cop, pixel_address_text):
    """Both the amount and the destination's name must match, with no negation.
    Returns (ok, detail)."""
    neg = negated(transcript, pixel_address_text)
    if neg:
        return False, "does not match: negation heard (%s)" % " ".join(neg)
    amt, _v, why = amount_check(transcript, pixel_amount_cop, pixel_address_text)
    rec = address_matches(transcript, pixel_address_text)
    if amt and rec:
        return True, "amount and destination match"
    missing = []
    if not amt:
        missing.append("amount (%s)" % why)
    if not rec:
        missing.append("destination")
    return False, "does not match: " + ", ".join(missing)
