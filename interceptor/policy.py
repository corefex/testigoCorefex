"""Policy: the compiled, signed output of Marta's spoken mandate (F1).

The interceptor enforces this; the agent cannot change it. The policy ties the
recipient by **name and account** (F1-D2): a payment passes only if both appear
in what the pixels read for the recipient, so changing the account while the
name stays visible no longer slips through.

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
        self.pay_only = _parse_pay_only(rules.get("pay_only", []))
        self.max_per_payment_cop = int(rules.get("max_per_payment_cop", 0))
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

    def pay_only_text(self):
        return ", ".join("%s · %s" % (p["name"], p["account"]) for p in self.pay_only) or "(none)"

    def recipient_allowed(self, recipient_text):
        """Pass only if an allowed name appears AND the accounts read for the
        recipient are exactly its account (F1-D2): a crop that also shows
        another account does not pass (review of F4)."""
        from receipts.receipt import norm_read
        t = (recipient_text or "").lower()
        accounts = norm_read("recipient", recipient_text or "")
        return any(p["name"].lower() in t and accounts == norm_read("recipient", p["account"])
                   for p in self.pay_only)

    def allowed_accounts(self):
        from receipts.receipt import norm_read
        return {norm_read("recipient", p["account"]) for p in self.pay_only}

    def amount_allowed(self, amount_cop):
        return 0 < int(amount_cop) <= self.max_per_payment_cop

    def check_payment(self, recipient_text, amount_cop):
        """Return (ok, reason). reason is a short human string when not ok."""
        if not self.recipient_allowed(recipient_text):
            return False, "recipient is not in pay-only list (%s)" % self.pay_only_text()
        if not self.amount_allowed(amount_cop):
            return False, "amount %s exceeds max %s" % (amount_cop, self.max_per_payment_cop)
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


def _parse_pay_only(raw):
    """Accept the F1 form [{name, account}] and tolerate a bare [name] list."""
    out = []
    for entry in raw or []:
        if isinstance(entry, dict):
            out.append({"name": str(entry.get("name", "")).strip(),
                        "account": str(entry.get("account", "")).strip()})
        else:
            out.append({"name": str(entry).strip(), "account": ""})
    return out


if __name__ == "__main__":
    import sys
    from common.config import POLICY_PATH
    p = load(sys.argv[1] if len(sys.argv) > 1 else POLICY_PATH)
    print("owner        :", p.owner)
    print("pay_only     :", p.pay_only)
    print("max_cop      :", p.max_per_payment_cop)
    print("ask_before   :", p.ask_before)
    print("sha256       :", p.sha256())
    print("short        :", p.short_sha())
    print("stored match :", p.hash_matches_stored())
