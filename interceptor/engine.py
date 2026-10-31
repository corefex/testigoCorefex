"""The TESTIGO+ decision engine.

Nothing the agent proposes reaches the page without passing through `check`.
The rules run in order; the first that fires decides. This is the piece the
whole demo turns on, so it is kept pure: it takes a Capture and a PixelChannel,
returns events, and talks to no browser, model or network itself.

Rules (spec order):
  1. SAM cannot find amount, recipient or the pay button with confidence
        -> cannot_verify, block.
  2. Text in the page code that is not drawn, or drawn text not in the code
        -> divergence, block.
  3. Recipient or amount read from the pixels breaks the policy
        -> policy_violation, block.
  4. Everything agrees and the action is a payment
        -> needs approval (voice + passkey).
  5. After the click, executed crops differ from the approved crops
        -> mismatch, the receipt is flagged.

"Read from the pixels" everywhere: the recipient and amount used for the policy
check come from the pixel channel, never from the DOM, so a hidden or swapped
value cannot slip a payment through.
"""

import re
import time

from . import events as ev
from .channels import REQUIRED_REGIONS, CONFIDENCE_MIN, sha_crop
from .instruction_filter import filter_instructions


class Decision:
    """Result of a pre-action check."""

    def __init__(self, status, blocked, check_event, approval_event=None,
                 needs_approval=False, reason=""):
        self.status = status
        self.blocked = blocked
        self.needs_approval = needs_approval
        self.reason = reason
        self.check_event = check_event
        self.approval_event = approval_event

    @property
    def allowed_now(self):
        """True only for a non-payment action that passed every check."""
        return not self.blocked and not self.needs_approval


class Interceptor:
    def __init__(self, policy, pixel_channel, confidence_min=CONFIDENCE_MIN):
        self.policy = policy
        self.pixels = pixel_channel
        self.confidence_min = confidence_min

    # -- pre-action ---------------------------------------------------------

    def check(self, action, capture, latency_ms=None):
        """Decide on a proposed action. `action` is {"kind": "pay"|"click"|"type", ...}."""
        t0 = time.perf_counter()
        regions = self.pixels.read_regions(capture)
        by_label = {r["label"]: r for r in regions}
        measured = int(round((time.perf_counter() - t0) * 1000))
        lat = latency_ms if latency_ms is not None else measured

        # Rule 1: cannot_verify
        missing, low = self._confidence_gaps(by_label)
        if missing or low:
            reason = _cannot_reason(missing, low, self.confidence_min)
            return Decision(
                ev.CANNOT_VERIFY, True,
                ev.check_result(capture.frame, ev.CANNOT_VERIFY, regions, [], [], lat, reason),
                reason=reason,
            )

        # Rule 2: divergence (both directions)
        code_only, pixels_only = self._divergence(capture)
        if code_only or pixels_only:
            if pixels_only:
                reason = "visible text not in page code"
            else:
                reason = "page code text not visible"
            return Decision(
                ev.DIVERGENCE, True,
                ev.check_result(capture.frame, ev.DIVERGENCE, regions,
                                code_only, pixels_only, lat, reason),
                reason=reason,
            )

        # Rule 3a: an account the policy does not allow is painted on the screen
        # (a decoy next to the real field, review of F4). The pixels decide.
        stray = self._stray_accounts(capture.rendered_lines)
        if stray:
            why = "an account not in the pay-only list is on screen: %s" % ", ".join(stray)
            return Decision(
                ev.POLICY_VIOLATION, True,
                ev.check_result(capture.frame, ev.POLICY_VIOLATION, regions, [], [], lat, why),
                reason=why,
            )

        # Rule 3: policy violation (recipient/amount read from pixels)
        recipient_text = by_label["recipient"]["text"]
        amount_cop = _amount_from(by_label["amount"]["text"])
        ok, why = self.policy.check_payment(recipient_text, amount_cop)
        if not ok:
            return Decision(
                ev.POLICY_VIOLATION, True,
                ev.check_result(capture.frame, ev.POLICY_VIOLATION, regions, [], [], lat, why),
                reason=why,
            )

        # Rule 4: ok. A payment needs approval; anything else is allowed.
        check_ev = ev.check_result(capture.frame, ev.OK, regions, [], [], lat, "")
        if _is_payment(action):
            crop_amt = sha_crop(capture.crops.get("amount", b""))
            crop_rec = sha_crop(capture.crops.get("recipient", b""))
            approval = ev.approval_requested(
                capture.frame, amount_cop, recipient_text, crop_amt, crop_rec)
            return Decision(ev.OK, False, check_ev, approval_event=approval,
                            needs_approval=True)
        return Decision(ev.OK, False, check_ev)

    # -- after the click ----------------------------------------------------

    def verify(self, approved_crops, executed_capture):
        """Rule 5: compare what executed against what was approved.

        approved_crops: {"amount": sha, "recipient": sha} from approval time.
        Returns a verify.result event; status is match or mismatch.
        """
        executed = {
            "amount": sha_crop(executed_capture.crops.get("amount", b"")),
            "recipient": sha_crop(executed_capture.crops.get("recipient", b"")),
        }
        status = ev.MATCH
        if (executed["amount"] != approved_crops.get("amount") or
                executed["recipient"] != approved_crops.get("recipient")):
            status = ev.MISMATCH
        return ev.verify_result(executed_capture.frame, status, dict(approved_crops), executed)

    def reread(self, approved_read, approved_hashes, capture, moment):
        """F8: read amount and recipient again and compare with what was approved.

        Compared by the values read from the pixels (receipts.receipt.norm_read:
        the amount's digits, the recipient's account numbers), because crops of
        unchanged content never hash the same across two real captures. The
        hashes travel along as evidence. Returns (verify.result event, read)."""
        from receipts.receipt import norm_read
        by = {r["label"]: r for r in self.pixels.read_regions(capture)}
        read = {n: by[n]["text"] for n in ("amount", "recipient")
                if n in by and by[n].get("confidence", 0) >= self.confidence_min}
        executed = {n: sha_crop(capture.crops[n]) for n in ("amount", "recipient")
                    if capture.crops.get(n)}
        if any(norm_read(n, approved_read.get(n)) != norm_read(n, read[n]) for n in read):
            status = ev.MISMATCH           # any field read and different: proven
        elif len(read) < 2:
            status = ev.CANNOT_VERIFY      # what was read agrees, but not everything was
        else:
            status = ev.MATCH
        return ev.verify_result(capture.frame, status, dict(approved_hashes), executed,
                                moment=moment,
                                read={"approved": dict(approved_read), "executed": read}), read

    # -- helpers ------------------------------------------------------------

    def _stray_accounts(self, lines):
        from receipts.receipt import ACCOUNT_RE, norm_read
        allowed = self.policy.allowed_accounts()
        seen = []
        for line in lines:
            if not ACCOUNT_RE.search(str(line)):
                continue
            for acct in norm_read("recipient", line).split(","):
                if acct and acct not in allowed and acct not in seen:
                    seen.append(acct)
        return seen

    def _confidence_gaps(self, by_label):
        missing = [r for r in REQUIRED_REGIONS if r not in by_label]
        low = [r for r in REQUIRED_REGIONS
               if r in by_label and by_label[r].get("confidence", 0) < self.confidence_min]
        return missing, low

    def _divergence(self, capture):
        """Differences in both directions, kept only where they look like an
        instruction for the agent (F5). Legitimate hidden text does not block."""
        code = _compact_all(capture.code_lines)
        pixels = _compact_all(capture.rendered_lines)
        code_only = [x for x in capture.code_lines if not _covered(x, pixels)]
        pixels_only = [x for x in capture.rendered_lines if not _covered(x, code)]
        return (filter_instructions(_dedupe(code_only)),
                filter_instructions(_dedupe(pixels_only)))


def _compact(s):
    """Letters and digits only, lower case: the DOM splits text into nodes and a
    reader groups it into lines, so a line is "in" the other channel when its
    letters and digits appear there in order, whatever the spacing or case."""
    return re.sub(r"[\W_]+", "", str(s).lower())


def _compact_all(lines):
    return "".join(_compact(x) for x in lines)


def _covered(line, other):
    """Every word of `line` is somewhere in the other channel. A reader may join
    on one line what the DOM keeps apart (the account field's value and the
    name beside it, 31 Oct), so whole lines are not compared; an instruction
    still shows, because its words (the attacker's account, "agent") are not
    in the other channel at all."""
    words = [_compact(w) for w in str(line).split()]
    words = [w for w in words if w]
    return not words or all(w in other for w in words)


def _norm(s):
    return " ".join(str(s).split()).strip().lower()


def _dedupe(xs):
    seen, out = set(), []
    for x in xs:
        k = _norm(x)
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _amount_from(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def _is_payment(action):
    return action.get("kind") == "pay"


def _cannot_reason(missing, low, cmin):
    bits = []
    if missing:
        bits.append("not found: " + ", ".join(missing))
    if low:
        bits.append("low confidence: " + ", ".join(low) + " (needs %.2f)" % cmin)
    return "; ".join(bits)
