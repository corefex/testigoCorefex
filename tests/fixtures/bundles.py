"""TEST ONLY: build a signed receipt bundle from fixture captures.

Moved out of receipts/ by F0: it signs evidence made of placeholder bytes, so
it can only prove that signing and `testigo verify` work. Real bundles come
from real runs (F9). Without --key it signs with a throwaway key, never with
the key in .secrets/.

A bundle is a folder:
  receipt.json
  approved_amount.png    approved_address.png
  executed_amount.png    executed_address.png

The crop files hold the exact bytes the interceptor hashed, so `testigo verify`
recomputes the same sha256. (Here the crops are placeholder bytes; in the live
system they are the real cropped PNGs — the hashing path is identical.)

  .venv/bin/python -m tests.fixtures.bundles --scenario a3 --out runs/evidence/test-a3
"""

import argparse
from pathlib import Path

from common.config import POLICY_PATH
from interceptor.engine import Interceptor
from interceptor.policy import load as load_policy
from receipts import keys
from receipts.receipt import build as build_receipt, dumps
from tests.fixtures import captures as fx

CROP_NAMES = ("amount", "address")


def _crops_from(capture):
    return {name: capture.crops[name] for name in CROP_NAMES}


def build_bundle(scenario, out_dir, seed=None, policy_path=POLICY_PATH, key_path=None):
    """Run the supervised check/verify for `scenario` and write a signed bundle.

    Works for clean (match) and a3 (mismatch). Scenarios blocked before the
    click (a1/a2/blurred) produce no receipt — there was no approved order.
    """
    policy = load_policy(policy_path)
    if seed is None:
        seed = keys.load_or_create_seed(key_path) if key_path else keys.generate_seed()

    pre = {"clean": fx.capture_clean, "a3": fx.capture_a3_before}[scenario]()
    itc = Interceptor(policy, fx.channel_for(scenario))
    decision = itc.check({"kind": "confirm"}, pre, latency_ms=1400)
    if decision.blocked or not decision.needs_approval:
        raise ValueError("scenario %r produced no approved order" % scenario)

    after = fx.capture_a3_after() if scenario == "a3" else fx.capture_clean(frame=164)
    approved_crops = _crops_from(pre)
    executed_crops = _crops_from(after)

    receipt = build_receipt(
        policy,
        action_text="confirm order %s COP -> deliver to %s" % (
            decision.approval_event["amount_cop"], decision.approval_event["address"]),
        amount_cop=decision.approval_event["amount_cop"],
        address_text=decision.approval_event["address"],
        approved_crops=approved_crops,
        executed_crops=executed_crops,
        approval={"method": "passkey",
                  "voice_transcript": "ciento veinte mil pesos, entrega en Tienda Doña Marta"},
        seed=seed,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name in CROP_NAMES:
        (out / ("approved_%s.png" % name)).write_bytes(approved_crops[name])
        (out / ("executed_%s.png" % name)).write_bytes(executed_crops[name])
    (out / "receipt.json").write_text(dumps(receipt) + "\n", encoding="utf-8")
    return out / "receipt.json", receipt


def main():
    ap = argparse.ArgumentParser(description="Build a signed receipt bundle")
    ap.add_argument("--scenario", default="clean", choices=["clean", "a3"])
    ap.add_argument("--out", default="runs/evidence/test-bundle")
    ap.add_argument("--key", default=None, help="default: a throwaway key")
    args = ap.parse_args()
    path, receipt = build_bundle(args.scenario, args.out, key_path=args.key)
    print("wrote", path)
    print("  id       ", receipt["id"])
    print("  policy   ", receipt["policy_sha256"][:12], "…")
    print("  signature", receipt["signature"][:24], "…")
    print("  key       marta-shop (%s)" % keys.backend())


if __name__ == "__main__":
    main()
