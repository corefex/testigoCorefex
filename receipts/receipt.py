"""Build and sign a receipt, in the spec's shape.

A receipt records one action: the policy it ran under, the approved evidence
crops, the executed crops, how it was approved, and an Ed25519 signature over
everything else. The crop hashes are the same sha256 the interceptor used, so
the number on the receipt is the number that was checked.

Hashes prove the evidence files were not swapped; they cannot say whether two
captures show the same thing (SAM's boxes move a few pixels between captures,
and the review screen has another layout). So a receipt also records the text
read from each crop (`read`) and the comparison of those values
(`comparison`). Receipts without `read` compare by hash.

The signature covers the canonical content (every field except `signature`),
which includes `pubkey`. Trust comes from pinning that public key out of band;
`testigo verify --pubkey <hex>` does exactly that.
"""

import hashlib
import json
import os
import re

from common import address as _address
from common import clock
from . import keys

CONFIRMED = "confirmed"   # the order was confirmed
BLOCKED = "blocked"       # it never was; executed is null (F9-D4)
CROP_NAMES = ("amount", "address")
# A delivery address as a reader may return it (common.address): street type
# and abbreviations, "#"/"No."/"N°"/"número", en/em dashes, and I/l/O misread
# for 1/1/0 in digit places.
ADDRESS_RE = _address.ADDRESS_RE


def sha_crop(data):
    """sha256 over the crop bytes; the same hash as interceptor.channels.sha_crop
    (kept here so the interceptor can import this module without a cycle)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical(receipt):
    """Stable bytes signed over: the receipt without its signature."""
    body = {k: v for k, v in receipt.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_crops(crop_bytes):
    """{'amount': b'...', 'address': b'...'} -> {'amount': sha, 'address': sha}."""
    return {name: sha_crop(data) for name, data in crop_bytes.items()}


def new_id(now=None):
    """rcpt_<yyyymmdd>_<hhmmss>_<4 random hex>: unique per action, sortable."""
    return "rcpt_%s_%s" % ((now or clock.now()).strftime("%Y%m%d_%H%M%S"), os.urandom(2).hex())


def norm_read(name, text):
    """A read value as compared: the amount's digits. The address: the
    addresses in it in canonical form ("calle 45 # 12-30"), sorted,
    de-duplicated, joined by ","; labels, names and the city around them
    ("DELIVER TO", "Tienda Doña Marta", "Bogotá") differ between screens and do
    not count. With no address, its letters and digits in lower case (spacing,
    case and punctuation do not count)."""
    if text is None:
        return None
    if name == "amount":
        return _amount_digits(str(text))
    return _address.norm_address(text)


def _amount_digits(text):
    """The whole-currency digits of the largest number in `text`: "COP 120,000",
    "$120.000,00" and "120000" all give "120000" (a 2-digit decimal part is dropped)."""
    # ASCII digits only, as ui/app.js reads them (Python's \d also takes "٣").
    nums = re.findall(r"[0-9][0-9.,\s]*[0-9]|[0-9]", text)
    if not nums:
        return ""
    best = ""
    for n in nums:
        n = re.sub(r"\s", "", n)
        n = re.sub(r"[.,][0-9]{2}$", "", n)
        d = re.sub(r"[^0-9]", "", n)
        if len(d) > len(best):
            best = d
    return best.lstrip("0") or "0"


def compare(approved_read, executed_read, approved_hashes, executed_hashes):
    """{'status': match|mismatch|pending, 'by': read|hash|None}.

    By the read values when both sides have them. When only one side has read
    values the comparison is pending: real captures of unchanged content do not
    hash equal, so a hash fallback would invent a mismatch (or a match). By hash
    only when neither side has read values (old receipts, fixtures); pending
    when nothing was captured after the click.
    """
    if approved_read and executed_read:
        same = all(norm_read(n, approved_read.get(n)) == norm_read(n, executed_read.get(n))
                   for n in CROP_NAMES)
        return {"status": "match" if same else "mismatch", "by": "read"}
    if approved_read or executed_read:
        return {"status": "pending", "by": None}
    if executed_hashes:
        same = all(approved_hashes.get(n) == executed_hashes.get(n) for n in CROP_NAMES)
        return {"status": "match" if same else "mismatch", "by": "hash"}
    return {"status": "pending", "by": None}


def sign(receipt, seed):
    """Return the receipt with `pubkey` and an Ed25519 `signature` over the rest."""
    receipt = {k: v for k, v in receipt.items() if k != "signature"}
    receipt["pubkey"] = keys.public_from_seed(seed).hex()
    receipt["signature"] = "ed25519:" + keys.sign(seed, canonical(receipt)).hex()
    return receipt


def build(policy, action_text, amount_cop, address_text,
          approved_crops, executed_crops, approval, seed,
          receipt_id=None, time=None, agent="wonder@marta-shop",
          signed_by=None, approved_read=None, executed_read=None,
          executed_hashes=None, status=CONFIRMED, blocked_at=None):
    """Assemble and sign a receipt.

    approved_crops / executed_crops: {'amount': bytes, 'address': bytes};
    executed_crops is None when nothing was captured after the click (then
    `executed_hashes` may still carry the hashes). approved_read /
    executed_read: {'amount': text, 'address': text} read from the crops.
    A `blocked` receipt has no executed side and says where (`blocked_at`).
    """
    approved = hash_crops(approved_crops)
    executed = hash_crops(executed_crops) if executed_crops else executed_hashes
    if status == BLOCKED:
        executed = executed_read = None
    receipt = {
        "id": receipt_id or new_id(),
        "time": time or clock.iso(),
        "agent": agent,
        "action": action_text,
        "amount_cop": amount_cop,
        "address": address_text,
        "policy_sha256": policy.sha256(),
        "approved": approved,
        "executed": executed,
        "status": status,
        "approval": approval,
        "signed_by": signed_by or "passkey:%s" % policy.owner,
    }
    if status == BLOCKED:
        receipt["blocked_at"] = blocked_at
    else:
        if approved_read is not None:
            receipt["read"] = {"approved": approved_read, "executed": executed_read}
        receipt["comparison"] = compare(approved_read, executed_read, approved, executed)
    return sign(receipt, seed)


def parse_signature(receipt):
    raw = receipt.get("signature", "")
    if not isinstance(raw, str) or not raw.startswith("ed25519:"):
        return None
    try:
        return bytes.fromhex(raw.split(":", 1)[1])
    except ValueError:
        return None


def verify_signature(receipt, pinned_pubkey=None):
    sig = parse_signature(receipt)
    if sig is None:
        return False
    pub = pinned_pubkey
    if pub is None:
        raw = receipt.get("pubkey", "")
        if not isinstance(raw, str):
            return False
        try:
            pub = bytes.fromhex(raw)
        except ValueError:
            return False
    return keys.verify(pub, canonical(receipt), sig)


def dumps(receipt):
    return json.dumps(receipt, indent=2, ensure_ascii=False)


def short(h):
    return "%s…%s" % (h[:6], h[-4:])
