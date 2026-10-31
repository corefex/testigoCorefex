"""Colombian street addresses as a reader may return them, in one canonical form.

The protected field of an order is its delivery address (R2, 1 Nov). What the
pixels read for it, what the policy allows and what the portal recorded are
compared in this form, so the labels around it ("DELIVER TO", "Entrega en"),
the city, the spacing, the case and the reader's small slips do not count:

  street type   calle | carrera | avenida | diagonal | transversal, also as
                Cl, Cll, Cra, Kr, Kra, Cr, Av, Avda, Dg, Diag, Tv, Tr, Transv
                (with or without a dot, any case)
  numbers       1-3 ASCII digits per group; I, l and O misread for 1, 1 and 0
                are accepted in digit places (a group must still hold a real
                digit). Each group keeps its letter and "bis" suffixes:
                "45A", "45 A", "45 Bis", "45 Bis B" (the last group: "30A",
                "30 Bis")
  quadrant      "Sur", "Este", "Norte", "Oeste" after the first number
                ("Calle 45 Sur # 12-30") or after the address; both give the
                same canonical form
  separator     "#", "No.", "No", "N°", "Nº", "Nro.", "número"/"numero", or
                nothing at all
  dash          "-", en dash, em dash (spaces around it allowed); after an
                explicit separator a plain space also works ("# 7 15")

What follows the address and names a place is part of it (review of cebf0f4:
"Calle 45 # 12-30 Sur", "..., Medellín", "..., Bogotá Soacha", "... Int. 2"
are other addresses): up to four words after it, up to a punctuation mark
other than "," and ".", or the next address, taking a quadrant, a complement
word with the word after it ("Int. 2", "Apto 301", "Torre B") and capitalized
words (a locality: "Medellín", "Soacha"). The first lower-case word of any
other kind ends it, so the sentence an address sits in ("... to Carrera 80 #
7-15 and confirm", "... #7-15 instead") is not read as part of it. The city
"Bogotá"/"Bogota" and "D.C." are dropped, and so is the shop's name when it is
exactly all that is left (the portal shows the delivery point's name right
after the address field: "Calle 45 # 12-30, Bogotá Tienda Doña Marta").

`canonical_addresses(text)` gives every address in the text as
"calle 45 # 12-30" / "calle 45a bis # 12-30 sur", sorted and without
duplicates. Standard library only, so the portal can use it too. ui/app.js
ports these rules (tests/test_ui.py checks both agree).
"""

import re
import unicodedata

from common.config import SHOP

STREET_TYPES = {
    "calle": "calle", "cll": "calle", "cl": "calle",
    "carrera": "carrera", "cra": "carrera", "kra": "carrera", "kr": "carrera", "cr": "carrera",
    "avenida": "avenida", "avda": "avenida", "av": "avenida",
    "diagonal": "diagonal", "diag": "diagonal", "dg": "diagonal",
    "transversal": "transversal", "transv": "transversal", "tv": "transversal",
    "tr": "transversal",
}

QUADRANTS = ("sur", "este", "norte", "oeste")
# The city of every address in the demo: dropped from the canonical form.
CITY_WORDS = frozenset({"bogota", "dc"})
# The portal shows the delivery point's name right after the address field;
# exactly that name (and nothing more) after an address is not part of it.
SHOP_NAME = SHOP["name"]
TAIL_MAX = 4
# Complement words: they and the word after them belong to the address.
COMPLEMENTS = frozenset({"int", "interior", "apto", "apartamento", "apt", "ap", "torre",
                         "bloque", "bl", "casa", "local", "piso", "of", "oficina",
                         "etapa", "manzana", "mz", "lote", "conjunto"})

# Longest first, so "cra" is not read as "cr" + "a".
_STREET = "|".join(sorted(STREET_TYPES, key=len, reverse=True))
# A digit group: 1-3 characters of ASCII digits or I/l/O, at least one a real digit.
_NUM = r"(?=[0-9IlO]{0,2}[0-9])[0-9IlO]{1,3}"
_LET = r"[A-Za-z](?!\w)"
_BIS = r"(?ai:bis)(?!\w)"
# ASCII-only case folding ("(?ai:"): Python's Unicode folding would also take
# "ſ" for "s" and "K" (Kelvin) for "k", which ui/app.js does not.
_SEP = r"(?:#|(?ai:n)[oOº°]\.?|(?ai:n)\.\s?[oOº°]|(?ai:nro)\.?|(?ai:n)[uUúÚ](?ai:mero))"
_DASH = r"[\-–—]"


def _group(k, last=False):
    if last:      # the last group: a letter only when attached ("30A")
        suffix = r"(?:%s)?(?:\s*%s)?" % (_LET, _BIS)
    else:
        suffix = r"(?:\s?%s)?(?:\s*%s(?:\s?%s)?)?" % (_LET, _BIS, _LET)
    return r"(?P<n%s>%s)(?P<s%s>%s)(?!\w)" % (k, _NUM, k, suffix)


ADDRESS_RE = re.compile(
    r"(?<!\w)(?P<street>(?ai:%s))\.?\s*%s(?:\s+(?P<quad>(?ai:%s))(?!\w))?\s*"
    r"(?:(?:%s\s*)?%s\s*%s\s*%s|%s\s*%s\s+%s)(?![.,][0-9])"
    % (_STREET, _group(1), "|".join(QUADRANTS),
       _SEP, _group("2a"), _DASH, _group("3a", True),
       _SEP, _group("2b"), _group("3b", True)))

_OCR_DIGITS = str.maketrans({"I": "1", "l": "1", "O": "0"})


def fold(text):
    """Text compared regardless of Unicode form, accents, case and spacing:
    "Tienda Dona Marta" == "Tienda Doña Marta" (NFC or NFD)."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.lower().split())


_SHOP_WORDS = [w.replace(".", "") for w in fold(SHOP_NAME).split()]


def _digits(group):
    return group.translate(_OCR_DIGITS).lstrip("0") or "0"


def _number(num, suffix):
    """"45" + " a bis b" -> "45a bis b"."""
    s = re.sub(r"\s+", "", suffix or "").lower()
    head, bis, after = s.partition("bis")
    return _digits(num) + head + (" bis" if bis else "") + (" " + after if after else "")


def _is_word_start(c):
    return c.isalpha() or c in "0123456789"


def _segment(text, i):
    """The words after an address at text[i:], up to a punctuation mark other
    than "," and ".", the next address, or the end, as (folded without dots,
    capitalized in the text)."""
    words, n = [], len(text)
    while True:
        while i < n and (text[i].isspace() or text[i] == ","):
            i += 1
        if i >= n or not _is_word_start(text[i]) or ADDRESS_RE.match(text, i):
            return words
        j = i
        while j < n and (_is_word_start(text[j]) or text[j] == "."):
            j += 1
        words.append((fold(text[i:j]).replace(".", ""), text[i].isupper()))
        i = j


def _tail(text, i):
    """The words that follow an address and belong to it (module docstring)."""
    out, segment = [], _segment(text, i)
    words = [w for w, _ in segment]
    k = 0
    while k < len(words) and len(out) < TAIL_MAX:
        word, capital = segment[k]
        if words[k:] == _SHOP_WORDS:
            break
        if word in CITY_WORDS:
            pass
        elif word in COMPLEMENTS:
            out += words[k:k + 2]
            k += 1
        elif word in QUADRANTS or capital:
            out.append(word)
        else:
            break
        k += 1
    return out[:TAIL_MAX]


def canonical_addresses(text):
    """Every address in `text`, canonical ("carrera 80 # 7-15"), sorted, unique."""
    text = unicodedata.normalize("NFC", str(text or ""))
    found = set()
    for m in ADDRESS_RE.finditer(text):
        k = "a" if m.group("n2a") else "b"
        tail = ([m.group("quad").lower()] if m.group("quad") else []) + _tail(text, m.end())
        found.add(" ".join(["%s %s # %s-%s" % (
            STREET_TYPES[m.group("street").lower()], _number(m.group("n1"), m.group("s1")),
            _number(m.group("n2" + k), m.group("s2" + k)),
            _number(m.group("n3" + k), m.group("s3" + k)))] + tail))
    return sorted(found)


def norm_address(text):
    """The addresses in `text` joined by ","; with none, its letters and digits
    in lower case (spacing, case and punctuation do not count)."""
    if text is None:
        return None
    found = canonical_addresses(text)
    if found:
        return ",".join(found)
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", str(text)).lower())


def squash(text):
    """Letters and ASCII digits only, accents folded, lower case:
    "Carrera 80 # 7-15" -> "carrera80715"."""
    return re.sub(r"[^a-z0-9]+", "", fold(text))
