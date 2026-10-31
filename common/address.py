"""Colombian street addresses as a reader may return them, in one canonical form.

The protected field of an order is its delivery address (R2, 1 Nov). What the
pixels read for it, what the policy allows and what the portal recorded are
compared in this form, so the labels around it ("DELIVER TO", "Entrega en"),
the city, the spacing, the case and the reader's small slips do not count:

  street type   calle | carrera | avenida | diagonal | transversal, also as
                Cl, Cll, Cra, Kr, Kra, Cr, Av, Avda, Dg, Diag, Tv, Tr, Transv
                (with or without a dot, any case)
  separator     "#", "No.", "No", "N°", "Nº", "Nro.", "número"/"numero", or
                nothing at all
  dash          "-", en dash, em dash (spaces around it allowed)
  digits        1-3 per group; I, l and O misread for 1, 1 and 0 are accepted
                in digit places (a group must still hold a real digit)

`canonical_addresses(text)` gives every address in the text as
"calle 45 # 12-30", sorted and without duplicates. Standard library only, so
the portal can use it too.
"""

import re

STREET_TYPES = {
    "calle": "calle", "cll": "calle", "cl": "calle",
    "carrera": "carrera", "cra": "carrera", "kra": "carrera", "kr": "carrera", "cr": "carrera",
    "avenida": "avenida", "avda": "avenida", "av": "avenida",
    "diagonal": "diagonal", "diag": "diagonal", "dg": "diagonal",
    "transversal": "transversal", "transv": "transversal", "tv": "transversal",
    "tr": "transversal",
}

# Longest first, so "cra" is not read as "cr" + "a".
_STREET = "|".join(sorted(STREET_TYPES, key=len, reverse=True))
# A digit group: 1-3 characters of digits or I/l/O, at least one a real digit.
_NUM = r"(?=[\dIlO]{0,2}\d)[\dIlO]{1,3}"
_SEP = r"(?:#|(?i:n[oº°]\.?|n\.\s?[oº°]|nro\.?|n[uú]mero))"
_DASH = r"[\-–—]"

ADDRESS_RE = re.compile(
    r"(?<![\w])(?i:(%s))\.?\s*(%s)(?![\w])\s*(?:%s\s*)?(%s)\s*%s\s*(%s)(?![\w])"
    % (_STREET, _NUM, _SEP, _NUM, _DASH, _NUM))

_OCR_DIGITS = str.maketrans({"I": "1", "l": "1", "O": "0"})


def _digits(group):
    return group.translate(_OCR_DIGITS).lstrip("0") or "0"


def canonical_addresses(text):
    """Every address in `text`, canonical ("carrera 80 # 7-15"), sorted, unique."""
    found = set()
    for street, a, b, c in ADDRESS_RE.findall(str(text or "")):
        found.add("%s %s # %s-%s" % (STREET_TYPES[street.lower()], _digits(a),
                                     _digits(b), _digits(c)))
    return sorted(found)


def norm_address(text):
    """The addresses in `text` joined by ","; with none, its letters and digits
    in lower case (spacing, case and punctuation do not count)."""
    if text is None:
        return None
    found = canonical_addresses(text)
    if found:
        return ",".join(found)
    return re.sub(r"[\W_]+", "", str(text).lower())
