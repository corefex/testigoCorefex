"""The four checks behind `testigo verify`.

  1. policy      the receipt's policy_sha256 equals the signed policy's hash
  2. signature   the Ed25519 signature is valid for the receipt body
  3. approved    each approved crop file hashes to the recorded approved hash
  4. executed    what executed equals what was approved (and its crop files
                 hash to the recorded executed hashes)

Check 4 is where a changed recipient shows up: an honest, correctly-signed
receipt of a *caught* attack passes 1-3 and fails 4 ("Evidence mismatch at
step 4", View 7b). A tampered receipt fails 2.

Step 4 recomputes the comparison from the signed values, never trusting the
recorded verdict: from the text read from each crop when the receipt has it
(`read`), else from crop-hash equality (older receipts, examples/). A `blocked`
receipt has no executed side, so step 4 does not apply (F9-D4); a confirmed one
with nothing captured after the click fails step 4 as not recorded.

Every recorded hash must be a 64-char lowercase hex sha256, and the crop names
must be exactly amount and recipient (approved always; executed when it is not
null); a missing hash never "matches" a missing file. Checks 3 and 4's file
half run only when an evidence folder is given: then every crop file must
exist and hash to its recorded value. Without it they check the recorded
values alone.

A receipt that is not the expected shape raises MalformedReceipt (the CLI
prints "Malformed receipt: <why>" and exits 1).
"""

import json
import re
from pathlib import Path

from common.config import POLICY_PATH
from interceptor.policy import load as load_policy
from .receipt import BLOCKED, CROP_NAMES, compare, norm_read, sha_crop, verify_signature

NOT_RECORDED = "Executed evidence not recorded at step 4"
NOT_COMPARED = "Executed evidence not compared at step 4"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class MalformedReceipt(ValueError):
    """The receipt file is not a receipt of the expected shape."""


class Check:
    def __init__(self, n, name, ok, detail="", summary=None):
        self.n = n
        self.name = name
        self.ok = ok
        self.detail = detail
        self.summary = summary    # overrides the default failure line


class Result:
    def __init__(self, receipt_id, checks, pinned=False):
        self.receipt_id = receipt_id
        self.checks = checks
        self.pinned = pinned      # False: signature checked with the key in the receipt

    @property
    def ok(self):
        return all(c.ok for c in self.checks)

    @property
    def first_failure(self):
        for c in self.checks:
            if not c.ok:
                return c
        return None

    def summary(self):
        if self.ok:
            return "Signature valid — evidence hashes match"
        f = self.first_failure
        return f.summary or {
            1: "Policy does not match the signed policy",
            2: "Signature invalid",
            3: "Approved evidence hash mismatch at step 3",
            4: "Evidence mismatch at step 4",
        }[f.n]

    def key_note(self):
        """How the signer's key was chosen, said honestly."""
        if self.pinned:
            return "Key: pinned with --pubkey"
        return "Key: embedded in the receipt (not pinned; pass --pubkey to pin it)"


# -- shape -------------------------------------------------------------------

def _dict_or_none(obj, key, where):
    v = obj.get(key)
    if v is not None and not isinstance(v, dict):
        raise MalformedReceipt("%s%s must be an object or null, not %s"
                               % (where, key, type(v).__name__))
    return v


def check_shape(receipt):
    """Raise MalformedReceipt unless the receipt has the types verify relies on."""
    if not isinstance(receipt, dict):
        raise MalformedReceipt("top level must be a JSON object, not %s" % type(receipt).__name__)
    for key in ("pubkey", "signature", "status", "policy_sha256", "blocked_at"):
        v = receipt.get(key)
        if v is not None and not isinstance(v, str):
            raise MalformedReceipt("%s must be a string, not %s" % (key, type(v).__name__))
    if not isinstance(receipt.get("approved"), dict):
        raise MalformedReceipt("approved must be an object of crop hashes")
    _dict_or_none(receipt, "executed", "")
    _dict_or_none(receipt, "comparison", "")
    read = _dict_or_none(receipt, "read", "")
    if read is not None:
        for side in ("approved", "executed"):
            vals = _dict_or_none(read, side, "read.")
            for n, t in (vals or {}).items():
                if t is not None and not isinstance(t, (str, int)):
                    raise MalformedReceipt("read.%s.%s must be text, not %s"
                                           % (side, n, type(t).__name__))
    for side in ("approved", "executed"):
        for n, h in (receipt.get(side) or {}).items():
            if h is not None and not isinstance(h, str):
                raise MalformedReceipt("%s.%s must be a hash string, not %s"
                                       % (side, n, type(h).__name__))


def load_receipt(receipt_path):
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise MalformedReceipt("cannot read %s: %s" % (receipt_path, e))
    except ValueError as e:
        raise MalformedReceipt("not valid JSON: %s" % e)
    check_shape(receipt)
    return receipt


# -- evidence ----------------------------------------------------------------

def _crop_problems(side, hashes, evidence_dir):
    """What is wrong with one side's recorded crop hashes and (with a folder)
    its crop files; [] when every crop is recorded and its file matches."""
    probs = []
    names = set(hashes)
    missing = [n for n in CROP_NAMES if n not in names]
    extra = sorted(names - set(CROP_NAMES))
    if missing:
        probs.append("%s %s hash not recorded" % (side, ", ".join(missing)))
    if extra:
        probs.append("unexpected %s crop %s" % (side, ", ".join(extra)))
    bad_hash = [n for n in CROP_NAMES if n in names and not HASH_RE.match(hashes[n] or "")]
    if bad_hash:
        probs.append("%s %s hash is not a sha256 hex" % (side, ", ".join(bad_hash)))
    if evidence_dir and not probs:
        for n in CROP_NAMES:
            p = Path(evidence_dir, "%s_%s.png" % (side, n))
            if not p.is_file():
                probs.append("%s %s file missing" % (side, n))
            elif sha_crop(p.read_bytes()) != hashes[n]:
                probs.append("%s %s file does not match its recorded hash" % (side, n))
    return probs


def _check_executed(receipt, approved, evidence_dir):
    if receipt.get("status") == BLOCKED:
        return Check(4, "executed", True,
                     "not applicable · blocked at %s" % receipt.get("blocked_at", "?"))
    executed = receipt.get("executed")
    if not executed:
        return Check(4, "executed", False,
                     "no executed crops recorded (check after the click pending)",
                     summary=NOT_RECORDED)
    probs = _crop_problems("executed", executed, evidence_dir)
    if probs:
        return Check(4, "executed", False, "; ".join(probs))

    read = receipt.get("read") or {}
    cmp = compare(read.get("approved"), read.get("executed"), approved, executed)
    recorded = (receipt.get("comparison") or {}).get("status")
    if recorded and recorded != cmp["status"]:
        return Check(4, "executed", False,
                     "recorded comparison %r disagrees with the values (%s)"
                     % (recorded, cmp["status"]))
    if cmp["status"] == "pending":
        return Check(4, "executed", False,
                     "executed read values not recorded; comparison pending",
                     summary=NOT_COMPARED)
    if cmp["by"] == "read":
        a, e = read["approved"], read["executed"]
        diff = [n for n in CROP_NAMES if norm_read(n, a.get(n)) != norm_read(n, e.get(n))]
        if not diff:
            return Check(4, "executed", True, "executed read values match approved · amount, recipient")
        return Check(4, "executed", False, "executed %s read differs from approved: %s"
                     % (", ".join(diff), "; ".join("%r vs %r" % (a.get(n), e.get(n)) for n in diff)))
    if cmp["status"] == "match":
        return Check(4, "executed", True, "executed crops match approved · %d of %d"
                     % (len(CROP_NAMES), len(CROP_NAMES)))
    diff = [n for n in CROP_NAMES if executed.get(n) != approved.get(n)]
    return Check(4, "executed", False,
                 "executed %s differs from approved" % (", ".join(diff) or "crops"))


def verify_receipt(receipt_path, evidence_dir=None,
                   policy_path=POLICY_PATH, pinned_pubkey=None):
    """Run the four checks. Raises MalformedReceipt for a receipt of the wrong shape."""
    receipt = load_receipt(receipt_path)
    checks = []

    # 1. policy
    try:
        pol = load_policy(policy_path)
        ok1 = pol.sha256() == receipt.get("policy_sha256")
        d1 = "matches signed policy %s…%s" % (pol.sha256()[:6], pol.sha256()[-4:]) if ok1 \
            else "receipt policy hash does not match %s" % policy_path
    except Exception as e:  # policy missing/unreadable
        ok1, d1 = False, "cannot load policy: %s" % e
    checks.append(Check(1, "policy", ok1, d1))

    # 2. signature
    ok2 = verify_signature(receipt, pinned_pubkey)
    key_src = "pinned key" if pinned_pubkey else "key in receipt"
    checks.append(Check(2, "signature", ok2,
                        "ed25519 · %s" % key_src if ok2 else "bad signature (%s)" % key_src))

    # 3. approved crops: all recorded, and their files match
    approved = receipt["approved"]
    probs = _crop_problems("approved", approved, evidence_dir)
    if probs:
        ok3, d3 = False, "; ".join(probs)
    elif evidence_dir:
        ok3, d3 = True, "%d of %d hashes match" % (len(CROP_NAMES), len(CROP_NAMES))
    else:
        ok3, d3 = True, "hashes recorded · files skipped (no evidence folder)"
    checks.append(Check(3, "approved", ok3, d3))

    # 4. executed equals approved
    checks.append(_check_executed(receipt, approved, evidence_dir))

    return Result(str(receipt.get("id", "?")), checks, pinned=pinned_pubkey is not None)
