"""Policy: the compiled, signed output of Marta's spoken mandate (F1).

The interceptor enforces this; the agent cannot change it. The policy ties the
delivery destination by **name and address** (F1-D2): an order passes only if
both appear in what the pixels read for "Deliver to", so changing the address
while the shop's name stays visible does not slip through.

A policy's identity is the sha256 over its canonical content (every field
except `sha256` and `signature`). An Ed25519 signature of the owner's key
(the same key pair as the receipts, F1-D3) covers that same content. The
receipt reuses this hash, so the number shown is the one that is signed.

PyYAML is a declared dependency; `.json` policies are also accepted.
"""

import hashlib
import json
from pathlib import Path


class Policy:
    def __init__(self, data):
        self.version = data.get("version", 1)
        self.owner = data.get("owner", "")
        self.source = data.get("source", "")
        self.transcript = data.get("transcript", "")
        self.signed_by = data.get("signed_by", "")
        self.signature = data.get("signature")
        self._stored_sha = data.get("sha256", "")

        rules = _merge_rules(data.get("rules", []))
        self.deliver_only = _parse_deliver_only(rules.get("deliver_only", []))
        self.max_per_order_cop = int(rules.get("max_per_order_cop", 0))
        self.ask_before = rules.get("ask_before", "")
        self._raw = data

    # -- identity -----------------------------------------------------------

    def canonical(self):
        """Stable bytes for hashing and signing: content without sha256/signature."""
        content = {k: v for k, v in self._raw.items() if k not in ("sha256", "signature")}
        return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def sha256(self):
        return hashlib.sha256(self.canonical()).hexdigest()

    def short_sha(self):
        h = self.sha256()
        return "%s…%s" % (h[:6], h[-4:])

    def hash_matches_stored(self):
        return self._stored_sha == self.sha256()

    def stamp_hash(self):
        self._raw["sha256"] = self.sha256()
        self._stored_sha = self._raw["sha256"]
        return self._stored_sha

    def to_dict(self):
        return self._raw

    # -- signing (Ed25519, same key pair as receipts) -----------------------

    def sign(self, seed):
        """Sign the canonical content and store the signature. Returns it."""
        from receipts import keys
        sig = keys.sign(seed, self.canonical())
        self.signature = "ed25519:" + sig.hex()
        self._raw["signature"] = self.signature
        return self.signature

    def signature_valid(self, pubkey):
        """True when the stored signature verifies for `pubkey` (32 bytes)."""
        from receipts import keys
        raw = self.signature or ""
        if not raw.startswith("ed25519:"):
            return False
        try:
            sig = bytes.fromhex(raw.split(":", 1)[1])
        except ValueError:
            return False
        return keys.verify(pubkey, self.canonical(), sig)

    # -- enforcement --------------------------------------------------------

    def deliver_only_text(self):
        return ", ".join("%s · %s" % (p["name"], p["address"]) for p in self.deliver_only) or "(none)"

    def address_allowed(self, address_text):
        """Pass only if an allowed name appears AND the addresses read for
        "Deliver to" are exactly its address (F1-D2): a crop that also shows
        another address does not pass (review of F4)."""
        from receipts.receipt import norm_read
        t = (address_text or "").lower()
        addresses = norm_read("address", address_text or "")
        return any(p["name"].lower() in t and addresses == norm_read("address", p["address"])
                   for p in self.deliver_only)

    def allowed_addresses(self):
        from receipts.receipt import norm_read
        return {norm_read("address", p["address"]) for p in self.deliver_only}

    def amount_allowed(self, amount_cop):
        return 0 < int(amount_cop) <= self.max_per_order_cop

    def check_order(self, address_text, amount_cop):
        """Return (ok, reason). reason is a short human string when not ok."""
        if not self.address_allowed(address_text):
            return False, "delivery address is not in the deliver-only list (%s)" % self.deliver_only_text()
        if not self.amount_allowed(amount_cop):
            return False, "amount %s exceeds max %s" % (amount_cop, self.max_per_order_cop)
        return True, ""


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return Policy(json.loads(text))
    import yaml
    return Policy(yaml.safe_load(text))


def _merge_rules(rule_list):
    """rules is a list of single-key dicts; flatten to one dict."""
    out = {}
    for item in rule_list or []:
        if isinstance(item, dict):
            out.update(item)
    return out


def _parse_deliver_only(raw):
    """Accept the F1 form [{name, address}] and tolerate a bare [name] list."""
    out = []
    for entry in raw or []:
        if isinstance(entry, dict):
            out.append({"name": str(entry.get("name", "")).strip(),
                        "address": str(entry.get("address", "")).strip()})
        else:
            out.append({"name": str(entry).strip(), "address": ""})
    return out


if __name__ == "__main__":
    import sys
    from common.config import policy_path
    p = load(sys.argv[1] if len(sys.argv) > 1 else policy_path())
    print("owner        :", p.owner)
    print("deliver_only :", p.deliver_only)
    print("max_cop      :", p.max_per_order_cop)
    print("ask_before   :", p.ask_before)
    print("sha256       :", p.sha256())
    print("short        :", p.short_sha())
    print("stored match :", p.hash_matches_stored())
