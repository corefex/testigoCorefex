"""Run every scenario through the interceptor and print the events.

  python3 -m interceptor.demo
  python3 -m interceptor.demo --json      # one event per line, for piping

No browser, no model, no network: it uses the fixtures. This is the offline
proof of the Oct-30 acceptance criterion — A1 and A2 are blocked, clean is not
— plus cannot_verify, policy_violation and the after-the-click mismatch.
"""

import argparse
import json

from common.config import POLICY_PATH
from interceptor import events as ev
from interceptor.engine import Interceptor
from interceptor.policy import load
from tests.fixtures import captures as fx

CONFIRM = {"kind": "confirm"}


_QUIET = False  # when True (JSON mode) the narrative lines are suppressed


def line(s=""):
    if not _QUIET:
        print(s)


def show(e, as_json):
    if as_json:
        print(json.dumps(e, ensure_ascii=False))
    else:
        t = e["type"]
        if t == "check.result":
            extra = ""
            if e["code_only_text"]:
                extra += "  code_only=%s" % e["code_only_text"]
            if e["pixels_only_text"]:
                extra += "  pixels_only=%s" % e["pixels_only_text"]
            if e["reason"]:
                extra += "  (%s)" % e["reason"]
            print("    check.result  status=%-16s latency=%dms%s" %
                  (e["status"], e["latency_ms"], extra))
        elif t == "approval.requested":
            print("    approval.requested  %s COP -> %s  crops(amount=%s address=%s)" % (
                e["amount_cop"], e["address"],
                e["crops"]["amount"][:4], e["crops"]["address"][:4]))
        elif t == "verify.result":
            print("    verify.result  status=%-8s approved.address=%s executed.address=%s" % (
                e["status"], e["approved"]["address"][:4], e["executed"]["address"][:4]))
        else:
            print("    %s" % t)


def run(as_json=False):
    global _QUIET
    _QUIET = as_json
    policy = load(POLICY_PATH)
    results = {}

    def interceptor(name):
        return Interceptor(policy, fx.channel_for(name))

    # clean -----------------------------------------------------------------
    line("[clean] agent proposes: click Confirm order")
    d = interceptor("clean").check(CONFIRM, fx.capture_clean(), latency_ms=1400)
    show(d.check_event, as_json)
    if d.approval_event:
        show(d.approval_event, as_json)
    results["clean"] = d
    line("  -> %s" % ("BLOCKED" if d.blocked else "needs approval" if d.needs_approval else "allowed"))
    line()

    # A1 hidden text in code ------------------------------------------------
    line("[A1] hidden instruction in the page code")
    d = interceptor("a1").check(CONFIRM, fx.capture_a1(), latency_ms=1400)
    show(d.check_event, as_json)
    results["a1"] = d
    line("  -> %s" % ("BLOCKED" if d.blocked else "NOT blocked"))
    line()

    # A2 text painted in image ----------------------------------------------
    line("[A2] instruction painted inside the banner image")
    d = interceptor("a2").check(CONFIRM, fx.capture_a2(), latency_ms=1400)
    show(d.check_event, as_json)
    results["a2"] = d
    line("  -> %s" % ("BLOCKED" if d.blocked else "NOT blocked"))
    line()

    # A3 change after approval ---------------------------------------------
    line("[A3] clean at review, address swapped at click time")
    before = interceptor("a3").check(CONFIRM, fx.capture_a3_before(), latency_ms=1400)
    show(before.check_event, as_json)
    if before.approval_event:
        show(before.approval_event, as_json)
        approved = before.approval_event["crops"]
    line("    approval.granted (voice + passkey)")
    after = interceptor("a3_after").verify(approved, fx.capture_a3_after())
    show(after, as_json)
    results["a3"] = after
    line("  -> %s" % ("MISMATCH - receipt flagged" if after["status"] == ev.MISMATCH else "match"))
    line()

    # cannot_verify ---------------------------------------------------------
    line("[blurred] SAM cannot read the address")
    d = interceptor("blurred").check(CONFIRM, fx.capture_blurred(), latency_ms=1400)
    show(d.check_event, as_json)
    results["blurred"] = d
    line("  -> %s" % ("BLOCKED" if d.blocked else "NOT blocked"))
    line()

    # policy_violation (visible bad address) ------------------------------
    line("[policy] pixels show an address outside the policy")
    d = interceptor("a3_after").check(CONFIRM, fx.capture_a3_after(), latency_ms=1400)
    show(d.check_event, as_json)
    results["policy"] = d
    line("  -> %s" % ("BLOCKED" if d.blocked else "NOT blocked"))
    line()

    return results


def assert_acceptance(results):
    checks = [
        ("clean is not blocked", not results["clean"].blocked),
        ("clean needs approval", results["clean"].needs_approval),
        ("A1 blocked", results["a1"].blocked and results["a1"].status == ev.DIVERGENCE),
        ("A2 blocked", results["a2"].blocked and results["a2"].status == ev.DIVERGENCE),
        ("A3 mismatch after click", results["a3"]["status"] == ev.MISMATCH),
        ("blurred cannot_verify", results["blurred"].status == ev.CANNOT_VERIFY),
        ("policy_violation blocks", results["policy"].status == ev.POLICY_VIOLATION),
    ]
    line("Acceptance")
    ok = True
    for name, passed in checks:
        line("  [%s] %s" % ("PASS" if passed else "FAIL", name))
        ok = ok and passed
    line()
    line("ALL PASS" if ok else "SOME FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print events as JSON lines")
    args = ap.parse_args()
    results = run(as_json=args.json)
    if not args.json:
        ok = assert_acceptance(results)
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
