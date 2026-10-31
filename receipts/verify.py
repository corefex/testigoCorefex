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

Checks 3 and 4's file half run only when an evidence folder is given; without
it, 3 is skipped and 4 compares the recorded values alone.
"""

import json
from pathlib import Path

from common.config import POLICY_PATH
from interceptor.channels import sha_crop
from interceptor.policy import load as load_policy
from .receipt import BLOCKED, CROP_NAMES, compare, norm_read, verify_signature

NOT_RECORDED = "Executed evidence not recorded at step 4"


class Check:
    def __init__(self, n, name, ok, detail="", summary=None):
        self.n = n
        self.name = name
        self.ok = ok
        self.detail = detail
        self.summary = summary    # overrides the default failure line


class Result:
    def __init__(self, receipt_id, checks):
        self.receipt_id = receipt_id
        self.checks = checks

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


def _hash_file(folder, fname):
    p = Path(folder, fname)
    return sha_crop(p.read_bytes()) if p.is_file() else None


def _check_executed(receipt, approved, evidence_dir):
    if receipt.get("status") == BLOCKED:
        return Check(4, "executed", True,
                     "not applicable · blocked at %s" % receipt.get("blocked_at", "?"))
    executed = receipt.get("executed")
    if not executed:
        return Check(4, "executed", False,
                     "no executed crops recorded (check after the click pending)",
                     summary=NOT_RECORDED)
    if evidence_dir:
        bad = [n for n in CROP_NAMES
               if _hash_file(evidence_dir, "executed_%s.png" % n) != executed.get(n)]
        if bad:
            return Check(4, "executed", False,
                         "executed %s file does not match its recorded hash" % ", ".join(bad))

    read = receipt.get("read") or {}
    cmp = compare(read.get("approved"), read.get("executed"), approved, executed)
    recorded = (receipt.get("comparison") or {}).get("status")
    if recorded and recorded != cmp["status"]:
        return Check(4, "executed", False,
                     "recorded comparison %r disagrees with the values (%s)"
                     % (recorded, cmp["status"]))
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
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
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

    # 3. approved crops match their recorded hashes
    approved = receipt.get("approved") or {}
    if evidence_dir:
        bad = [n for n in CROP_NAMES
               if _hash_file(evidence_dir, "approved_%s.png" % n) != approved.get(n)]
        ok3 = not bad
        d3 = "%d of %d hashes match" % (len(CROP_NAMES) - len(bad), len(CROP_NAMES))
    else:
        ok3, d3 = True, "skipped (no evidence folder)"
    checks.append(Check(3, "approved", ok3, d3))

    # 4. executed equals approved
    checks.append(_check_executed(receipt, approved, evidence_dir))

    return Result(receipt.get("id", "?"), checks)
