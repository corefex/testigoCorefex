"""Approval: voice confirms the intent; a passkey would prove it is the person.

The loop asks an `Approver` when the interceptor says a payment needs approval.
Offline, `AutoApprover` grants (the happy path) and `DenyApprover` refuses.

Real runs use `ServiceApprover` (F7 with R8): the approval opens in the
interface (view 5), the person reads the amount and recipient aloud, Voice
Transcribe transcribes it, the service compares it with the amount and
recipient read from the pixels, and only then can the person click Approve.
Voice decides *what*. The passkey (*who*) is optional under R8 and not used;
`WebAuthnApprover` stays a stub. `ConsoleApprover` is the terminal fallback.
"""

import json
import time
import urllib.error
import urllib.request

from approval.voice_match import voice_matches


class Approver:
    def approve(self, approval_event):      # pragma: no cover - interface
        """Return (granted: bool, info: dict) for an approval.requested event."""
        raise NotImplementedError


class AutoApprover(Approver):
    """Grants, as if the person read the amount aloud and tapped the passkey."""

    def __init__(self, voice_transcript="ciento veinte mil pesos a Distribuidora X"):
        self.voice_transcript = voice_transcript

    def approve(self, approval_event):
        return True, {
            "method": "passkey",
            "voice_transcript": self.voice_transcript,
            "voice_match": True,
        }


class DenyApprover(Approver):
    """Refuses — e.g. the spoken amount did not match the screen."""

    def __init__(self, voice_transcript="ciento cincuenta mil pesos", reason="voice did not match"):
        self.voice_transcript = voice_transcript
        self.reason = reason

    def approve(self, approval_event):
        return False, {
            "method": "passkey",
            "voice_transcript": self.voice_transcript,
            "voice_match": False,
            "reason": self.reason,
        }


class ConsoleApprover(Approver):
    """A person approves in the terminal, looking at what the pixels read.

    The fallback when the interface is not running (or with --approve-in
    console): it shows the amount and recipient read from the screen and asks
    for "yes". No voice. Without a terminal (gate, benchmark) nobody can
    approve, so it refuses."""

    def __init__(self, ask=input, interactive=None):
        import sys
        self.ask = ask
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

    def approve(self, approval_event):
        info = {"method": "console", "voice_transcript": "", "voice_match": False}
        if not self.interactive:
            return False, dict(info, reason="no person at the terminal to approve")
        print("\nTESTIGO+ asks for approval (read from the pixels):")
        print("  amount:    COP {:,}".format(approval_event["amount_cop"]))
        print("  recipient: %s" % approval_event["recipient"])
        answer = self.ask("Approve this payment? Type yes to approve: ").strip().lower()
        return answer == "yes", info


class ServiceApprover(Approver):
    """The person approves in the interface (view 5) with voice + a click.

    Opens the approval on the interceptor service, then polls it until the
    person decides there, or until `timeout_s` (then it denies, and says so
    on the service so the page stops offering the buttons). Any doubt —
    service unreachable, a decision for another event, an approve without a
    voice that matched — is a denial: nobody approved, the payment does not
    happen.

    `images_for(event)` may return {"amount": path, "recipient": path} (crop
    PNGs under runs/) so the capsule can show the crops the event names.
    `http(method, path, body) -> (status, json)` is injectable for tests."""

    METHOD = "voice"

    def __init__(self, base_url=None, timeout_s=300.0, poll_s=0.5, images_for=None,
                 http=None, sleep=time.sleep, monotonic=time.monotonic):
        if base_url is None and http is None:
            from interceptor.sink import service_url
            base_url = service_url()
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.images_for = images_for
        self.http = http or self._urllib
        self.sleep = sleep
        self.monotonic = monotonic

    def _urllib(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    def _call(self, method, path, body=None):
        try:
            return self.http(method, path, body)
        except Exception as e:  # noqa: BLE001 - unreachable service means no approval
            return None, {"detail": "%s: %s" % (type(e).__name__, e)}

    def _denied(self, reason, voice=None):
        voice = voice or {}
        return False, {"method": self.METHOD, "voice_transcript": voice.get("transcript", ""),
                       "voice_match": bool(voice.get("match")), "reason": reason}

    def approve(self, approval_event):
        images = {}
        if self.images_for is not None:
            try:
                images = self.images_for(approval_event) or {}
            except Exception:  # noqa: BLE001 - crops on screen are nice to have
                images = {}
        status, rec = self._call("POST", "/api/approval/open",
                                 {"event": approval_event, "images": images})
        if status == 422 and images:          # an image the service refused: open without
            status, rec = self._call("POST", "/api/approval/open", {"event": approval_event})
        if status != 200 or not isinstance(rec, dict) or "id" not in rec:
            return self._denied("the interface could not open the approval (%s)"
                                % ((rec or {}).get("detail") if isinstance(rec, dict) else status))
        aid = rec["id"]
        print("\nTESTIGO+ asks for approval in the interface (view 5): read the amount "
              "and recipient aloud, then Approve or Deny. Waiting up to %ds." % self.timeout_s)
        deadline = self.monotonic() + self.timeout_s
        while True:
            status, got = self._call("GET", "/api/approval/%s" % aid)
            if status == 200 and isinstance(got, dict):
                rec = got
                if rec.get("decision"):
                    return self._result(approval_event, rec, aid)
            elif status == 404:
                return self._denied("the approval was closed on the service", rec.get("voice"))
            if self.monotonic() >= deadline:
                break
            self.sleep(self.poll_s)
        reason = "no decision in the interface within %ds" % self.timeout_s
        status, got = self._call("POST", "/api/approval/%s/decision" % aid,
                                 {"decision": "deny", "reason": reason})
        if status == 200 and isinstance(got, dict):
            rec = got
        elif status == 409:                   # the person decided at the last moment
            status, got = self._call("GET", "/api/approval/%s" % aid)
            if status == 200 and isinstance(got, dict) and got.get("decision"):
                return self._result(approval_event, got, aid)
        return self._denied(reason, rec.get("voice"))

    def _result(self, approval_event, rec, aid):
        """The service's decision, trusted only if it is for the approval this
        run opened and the voice, re-checked here against the event, agrees."""
        voice = rec.get("voice") or {}
        ev = rec.get("event") or {}
        if rec.get("id") != aid:
            return self._denied("the decision is for a different approval", voice)
        if (ev.get("crops") != approval_event.get("crops")
                or ev.get("amount_cop") != approval_event.get("amount_cop")
                or ev.get("recipient") != approval_event.get("recipient")):
            return self._denied("the decision is for a different approval", voice)
        if rec.get("decision") != "approve":
            return self._denied(rec.get("reason") or "denied by the person", voice)
        if not voice.get("match"):
            return self._denied("approve without a voice that matched", voice)
        ok, detail = voice_matches(voice.get("transcript", ""), approval_event.get("amount_cop"),
                                   approval_event.get("recipient"))
        if not ok:
            return self._denied("the voice re-checked by the run does not match (%s)" % detail,
                                dict(voice, match=False))
        return True, {"method": self.METHOD, "voice_transcript": voice.get("transcript", ""),
                      "voice_match": True}


class WebAuthnApprover(Approver):   # pragma: no cover - needs a browser + mic
    """Passkey on top of the voice (F7-D4). Optional under R8; not built."""

    def __init__(self, transcribe, webauthn):
        self.transcribe = transcribe
        self.webauthn = webauthn

    def approve(self, approval_event):
        raise NotImplementedError("record voice, compare to pixels, then WebAuthn")
