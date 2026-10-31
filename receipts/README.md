# Signed receipts + `testigo verify`

Every supervised action leaves a receipt: the policy it ran under, the approved
evidence crops, what actually executed, how it was approved, and an **Ed25519
signature** over all of it. Anyone can check a receipt with `testigo verify` —
no TESTIGO+ account, no trust in us.

Ed25519 comes from the `cryptography` library. Everything is simulated.

## Run

```bash
.venv/bin/testigo keygen                       # create the key at SIGNING_KEY_PATH (.secrets/)
.venv/bin/testigo verify examples/clean/receipt.json --pubkey "$(cat examples/pubkey.txt)"
.venv/bin/testigo verify examples/a3/receipt.json    --pubkey "$(cat examples/pubkey.txt)"
make test                                      # tests
```

`examples/` holds synthetic receipts signed with a throwaway key (decision D7).
Real receipts come from real runs: when a supervised run approves and
executes a payment, the loop signs the receipt with the owner's key
(SIGNING_KEY_PATH) and writes it with its crop PNGs into the run folder,
`runs/<date>/<run>/` (git-ignored). Without a key the run goes on and says the
receipt was not signed. The fixture bundle builder is in `tests/fixtures/bundles.py`.

## The four checks (View 7)

```
$ testigo verify examples/clean/receipt.json
Checking rcpt_2041_7f3a …
[1/4] ✓ policy    · matches signed policy 6afbaf…88f1
[2/4] ✓ signature · ed25519 · key in receipt
[3/4] ✓ approved  · 2 of 2 hashes match
[4/4] ✓ executed  · executed crops match approved · 2 of 2

Signature valid — evidence hashes match
```

| # | check | fails when |
|---|---|---|
| 1 | policy | the receipt's `policy_sha256` ≠ the signed policy's hash |
| 2 | signature | the Ed25519 signature doesn't verify (tampered receipt) |
| 3 | approved | an approved crop file doesn't hash to its recorded value |
| 4 | executed | what executed ≠ what was approved, an executed crop file doesn't hash to its recorded value, or nothing was recorded after the click |

Hashes guard the evidence files; they cannot say whether two real captures show
the same thing (SAM's boxes move a few pixels between captures). So a receipt
from a run also records the text read from each crop (`read.approved`,
`read.executed`) and the signed `comparison` (`match`/`mismatch`/`pending`, by
`read` or `hash`). Step 4 recomputes it from the signed values: by the read
values when both are there, else by hash equality (as in `examples/`). A
`blocked` receipt (`executed: null`, `blocked_at`) has no step 4 to fail.

Two distinct failures, both shown in View 7:

- **Tampered receipt** → step 2 fails → `Signature invalid`.
- **Honest receipt of a caught attack** (A3) → steps 1-3 pass, step 4 fails →
  `Evidence mismatch at step 4`. The signature is valid; the receipt faithfully
  records that what executed differed from what was approved.

Exit code is 0 only when all four pass.

## An evidence bundle

```
evidence/a3/
  receipt.json
  approved_amount.png    approved_recipient.png
  executed_amount.png    executed_recipient.png
```

The crop files hold the exact bytes the interceptor hashed, so `testigo verify`
recomputes the same sha256. (Here the crops are placeholder bytes; in the live
system they are the real cropped PNGs — the hashing path is identical.) Without
the folder, verify still runs checks 1, 2 and the recorded half of 4.

## Trust model

The receipt carries the signer's `pubkey`. That is convenient, not the root of
trust: pin the expected key out of band and verify against it —

```bash
./testigo verify receipt.json --pubkey b1ac36f3…
```

The signature covers the `pubkey` field, so a receipt can't be re-pointed to a
different key without re-signing, which only the real key holder can do. The
hashes are the same ones the interceptor and the loop produce, and
`policy_sha256` is the same hash `interceptor/policy.py` reports — the number on
the receipt is the number that was checked.

## Pieces

```
receipts/
  keys.py          keygen / sign / verify (cryptography); key files in .secrets/
  receipt.py       build + sign; canonical serialization; signature verify
  bundle.py        the receipt of a run: key, sign, write receipt.json + crops
  verify.py        the four checks (library)
  cli.py           `testigo verify|keygen` (installed as the `testigo` command)
  test_receipts.py tests
```

`.secrets/` and `runs/` are git-ignored.

## Acceptance (Nov 2)

`testigo verify` returns valid for a good receipt and catches an altered one —
both shown above. The receipt's `approved`/`executed` crop hashes and
`policy_sha256` are produced by the interceptor and the loop, not re-invented
here.
