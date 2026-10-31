"""Events the interceptor emits to the interface.

One JSON object per event. These constructors fix the contract from the spec;
if a field changes, it changes here first. The interface (WebSocket/SSE) and
WitnessBench both read these shapes.

Event types:
  run.started         a run began (mode supervised|no_supervisor, scenario)
  agent.step          the agent proposed or completed a step
  frame.captured      a screenshot was taken
  check.result        the pre-action verdict (ok|divergence|policy_violation|cannot_verify)
  approval.requested  an order confirmation that passed checks now needs the person
  approval.granted    the person approved (voice + passkey)
  verify.result       the after-the-click comparison (match|mismatch)
  receipt.signed      the signed receipt was written
  order.confirmed     what the portal recorded as confirmed (both modes; view 3)

Optional fields added by F11 (absent until the producer has them):
  frame.captured.image        screenshot path, relative to runs/
  approval.requested.images   {"amount": path, "address": path} crop PNGs
  verify.result.images        {"approved": {...}, "executed": {...}} crop PNGs
  receipt.signed.path         receipt.json path, relative to runs/

check.result.status is one of: ok, divergence, policy_violation, cannot_verify.
When status is ok and the action confirms the order, the engine follows it with
an approval.requested; any other ok action is simply allowed.
"""

import time


# Verdict constants (check.result.status)
OK = "ok"
DIVERGENCE = "divergence"
POLICY_VIOLATION = "policy_violation"
CANNOT_VERIFY = "cannot_verify"

# verify.result.status
MATCH = "match"
MISMATCH = "mismatch"

TYPES = frozenset({
    "run.started", "agent.step", "frame.captured", "check.result",
    "approval.requested", "approval.granted", "verify.result",
    "receipt.signed", "order.confirmed",
})


def _ts(ts=None):
    # RFC3339 with the demo's fixed -05:00 (Bogotá) offset.
    if ts:
        return ts
    return time.strftime("%Y-%m-%dT%H:%M:%S-05:00", time.localtime())


def run_started(mode, scenario, variant=None, ts=None):
    return {"type": "run.started", "ts": _ts(ts), "mode": mode,
            "scenario": scenario, "variant": variant}


def agent_step(frame, label, detail="", ts=None):
    return {"type": "agent.step", "frame": frame, "ts": _ts(ts),
            "label": label, "detail": detail}


def frame_captured(frame, sha, image=None, ts=None):
    e = {"type": "frame.captured", "frame": frame, "ts": _ts(ts), "sha256": sha}
    if image:
        e["image"] = image
    return e


def check_result(frame, status, regions, code_only_text, pixels_only_text,
                 latency_ms, reason="", ts=None):
    return {
        "type": "check.result", "frame": frame, "ts": _ts(ts),
        "status": status,
        "regions": regions,
        "code_only_text": code_only_text,
        "pixels_only_text": pixels_only_text,
        "latency_ms": latency_ms,
        "reason": reason,
    }


def approval_requested(frame, amount_cop, address_text,
                       crop_amount_sha, crop_address_sha, images=None, ts=None):
    e = {
        "type": "approval.requested", "frame": frame, "ts": _ts(ts),
        "amount_cop": amount_cop,
        "address": address_text,
        "crops": {"amount": crop_amount_sha, "address": crop_address_sha},
    }
    if images:
        e["images"] = images
    return e


def approval_granted(method, voice_transcript, voice_match, granted=True, ts=None):
    """The person's answer. `granted` is false when they refused (voice did not
    match, or the passkey was not given); the event name stays for the contract."""
    return {
        "type": "approval.granted", "ts": _ts(ts),
        "method": method,
        "voice_transcript": voice_transcript,
        "voice_match": voice_match,
        "granted": bool(granted),
    }


def verify_result(frame, status, approved, executed, images=None, ts=None,
                  moment=None, read=None):
    """F8. `moment`: "review" (before confirming; a mismatch blocks) or "result"
    (after the click; a mismatch flags the receipt). `read`: the values read
    from the pixels, {"approved": {...}, "executed": {...}}."""
    e = {
        "type": "verify.result", "frame": frame, "ts": _ts(ts),
        "status": status,
        "approved": approved,   # {"amount": sha, "address": sha}
        "executed": executed,   # {"amount": sha, "address": sha}
    }
    if images:
        e["images"] = images
    if moment:
        e["moment"] = moment
    if read:
        e["read"] = read
    return e


def receipt_signed(receipt_id, signature, path=None, ts=None):
    e = {"type": "receipt.signed", "ts": _ts(ts),
         "id": receipt_id, "signature": signature}
    if path:
        e["path"] = path
    return e


def order_confirmed(frame, address_text, amount_cop, ts=None):
    """The order the portal recorded as confirmed, and where it is delivered.
    Emitted in both modes, so view 3 can show the order that went through
    without a supervisor."""
    return {"type": "order.confirmed", "frame": frame, "ts": _ts(ts),
            "address": address_text, "amount_cop": amount_cop}


def region(label, box, text, confidence):
    """One SAM region as it appears in check.result.regions."""
    return {"label": label, "box": list(box), "text": text,
            "confidence": round(float(confidence), 2)}
