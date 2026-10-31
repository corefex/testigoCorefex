"""F7: the approval desk inside the interceptor service.

The loop runs in its own process. When an order confirmation needs the person, its
`ServiceApprover` opens the approval here and waits; the interface (view 5)
records the person reading the total and the destination aloud, the service has it
transcribed (Voice Transcribe) and compared — with `voice_match` — against the
amount and address **read from the pixels** in the approval.requested event.
Only a voice that matches unlocks "Approve"; "Deny" is always possible. The
loop then emits approval.granted with method "voice" and the real transcript.

Voice confirms the intent (how much is ordered and where it is delivered). It does not prove who is
speaking; a passkey would, and it is optional and not used (R8).

The desk holds one approval at a time, in memory, and decides nothing on its
own: it records what was heard and what the person clicked.
"""

import secrets
import threading

from common import clock

from . import voice_match

MAX_VOICE_ATTEMPTS = 5     # each attempt is a billed Voice Transcribe call
DECISIONS = ("approve", "deny")


class DeskError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _copy(rec):
    if rec is None:
        return None
    out = dict(rec)
    out["event"] = dict(rec["event"])
    out["images"] = dict(rec["images"])
    out["voice"] = dict(rec["voice"]) if rec["voice"] else None
    return out


class ApprovalDesk:
    def __init__(self, new_id=lambda: secrets.token_hex(8), now=clock.iso):
        self._new_id = new_id
        self._now = now
        self._lock = threading.Lock()
        self._rec = None

    # -- the loop -----------------------------------------------------------

    def open(self, event, images=None):
        """Open the approval for one approval.requested event. A pending one
        left open by an earlier run is closed as denied (superseded)."""
        if not isinstance(event, dict) or event.get("type") != "approval.requested":
            raise DeskError(422, "event must be an approval.requested event")
        amount = event.get("amount_cop")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise DeskError(422, "amount_cop must be an integer (whole pesos)")
        with self._lock:
            old = self._rec
            if old is not None and old["decision"] is None:
                old.update(decision="deny", reason="superseded by a newer approval",
                           decided_at=self._now())
            self._rec = {
                "id": self._new_id(), "opened_at": self._now(),
                "event": dict(event), "images": dict(images or {}),
                "voice": None, "attempts": 0,
                "decision": None, "reason": "", "decided_at": None,
            }
            return _copy(self._rec)

    # -- the page and the loop ----------------------------------------------

    def current(self):
        with self._lock:
            return _copy(self._rec)

    def get(self, approval_id):
        with self._lock:
            return _copy(self._find(approval_id))

    def start_voice(self, approval_id):
        """Reserve one transcription attempt (before the billed call)."""
        with self._lock:
            rec = self._find(approval_id)
            self._pending(rec)
            if rec["attempts"] >= MAX_VOICE_ATTEMPTS:
                raise DeskError(429, "too many voice attempts for this approval (%d)"
                                % MAX_VOICE_ATTEMPTS)
            rec["attempts"] += 1
            return _copy(rec)

    def record_voice(self, approval_id, transcript, latency_ms=None):
        """Compare what was heard with what the pixels read. Returns the record."""
        with self._lock:
            rec = self._find(approval_id)
            self._pending(rec)
            e = rec["event"]
            ok, detail = voice_match.voice_matches(transcript, e["amount_cop"], e["address"])
            amt_ok, heard, amt_why = voice_match.amount_check(
                transcript, e["amount_cop"], e["address"])
            rec["voice"] = {
                "transcript": str(transcript or ""),
                "match": ok,
                "detail": detail,
                "heard_amount": heard,
                "amount_match": amt_ok,
                "amount_reason": amt_why,
                "address_match": voice_match.address_matches(transcript, e["address"]),
                "address_name": voice_match.name_of(e["address"]),
                "negated": voice_match.negated(transcript, e["address"]),
                "latency_ms": latency_ms,
                "at": self._now(),
            }
            return _copy(rec)

    def decide(self, approval_id, decision, reason=""):
        """The person's click (or the loop's timeout). Approve needs a voice
        that matched; a decision is final."""
        if decision not in DECISIONS:
            raise DeskError(422, "decision must be one of %s" % (DECISIONS,))
        with self._lock:
            rec = self._find(approval_id)
            self._pending(rec)
            if decision == "approve" and not (rec["voice"] and rec["voice"]["match"]):
                raise DeskError(409, "approve needs a voice that matches the screen first")
            if decision == "deny" and not reason:
                reason = "denied by the person"
            rec.update(decision=decision, reason=str(reason)[:200], decided_at=self._now())
            return _copy(rec)

    # -- helpers ------------------------------------------------------------

    def _find(self, approval_id):
        if self._rec is None or self._rec["id"] != approval_id:
            raise DeskError(404, "no such approval")
        return self._rec

    @staticmethod
    def _pending(rec):
        if rec["decision"] is not None:
            raise DeskError(409, "this approval is already decided (%s)" % rec["decision"])
