"""`testigo` — check a receipt without trusting us.

  testigo verify runs/evidence/run/receipt.json
  testigo verify receipt.json --evidence <folder>
  testigo verify receipt.json --pubkey <hex>        # pin the signer's key
  testigo keygen                                    # create/show the key at SIGNING_KEY_PATH

The verify output mirrors View 7: a four-step checklist, then one line.
Exit code 0 only when every check passes; 1 when a check fails or the
receipt is malformed; 2 for a usage error (as argparse), e.g. a bad --pubkey.
"""

import argparse
import sys
from pathlib import Path

from common import config

from . import keys
from .verify import MalformedReceipt, verify_receipt

CHECK = "✓"   # ✓
CROSS = "✗"   # ✗


def cmd_verify(args):
    evidence = args.evidence
    if evidence is None:
        guess = Path(args.receipt).resolve().parent
        if (guess / "approved_amount.png").exists():
            evidence = str(guess)
    pinned = None
    if args.pubkey is not None:
        pinned = parse_pubkey(args.pubkey)
        if pinned is None:
            print("testigo verify: error: --pubkey must be 64 hex characters "
                  "(a 32-byte Ed25519 public key)", file=sys.stderr)
            return 2

    try:
        res = verify_receipt(args.receipt, evidence_dir=evidence,
                             policy_path=args.policy, pinned_pubkey=pinned)
    except MalformedReceipt as e:
        print("Malformed receipt: %s" % e)
        return 1
    print("Checking %s …" % res.receipt_id)
    for c in res.checks:
        mark = CHECK if c.ok else CROSS
        print("[%d/4] %s %s %s" % (c.n, mark, c.name, ("· " + c.detail) if c.detail else ""))
    if not res.pinned:
        print(res.key_note())
    print()
    print(res.summary())
    return 0 if res.ok else 1


def parse_pubkey(text):
    """32 raw bytes from a hex public key, or None if it is not one."""
    try:
        raw = bytes.fromhex(text.strip())
    except ValueError:
        return None
    return raw if len(raw) == 32 else None


def cmd_keygen(args):
    path = args.path or config.settings().signing_key_path
    seed = keys.load_or_create_seed(path)
    print("key file :", path)
    print("pubkey   :", keys.public_from_seed(seed).hex())
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="testigo", description="TESTIGO+ receipt tools")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify a signed receipt")
    v.add_argument("receipt")
    v.add_argument("--evidence", help="folder with the crop PNGs (auto-detected next to the receipt)")
    v.add_argument("--policy", default=None,
                   help="default: the active policy (RUNS_DIR/%s if signed from the "
                        "interface, else policy/marta.policy.yaml)" % config.ACTIVE_POLICY)
    v.add_argument("--pubkey", help="pin the signer's public key (hex)")
    v.set_defaults(func=cmd_verify)

    k = sub.add_parser("keygen", help="create or show the signing key")
    k.add_argument("path", nargs="?", default=None, help="default: SIGNING_KEY_PATH")
    k.set_defaults(func=cmd_keygen)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
