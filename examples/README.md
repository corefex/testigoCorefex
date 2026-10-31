# Synthetic receipts (decision D7)

Two receipts of a supplier order (COP 120,000, delivered to Tienda Doña Marta ·
Calle 45 # 12-30) so anyone can try `testigo verify` without running anything:

- `clean/` — every check passes.
- `a3/` — the receipt is correctly signed, but the delivery address that
  executed (Carrera 80 # 7-15) differs from the approved one (Calle 45 # 12-30),
  so it fails at step 4.

They are **synthetic**: the "crop" files (`approved_amount.png`,
`approved_address.png`, `executed_*.png`) are placeholder bytes, not real
screenshots. They were signed with a throwaway key generated in memory whose
private half was never saved; only `pubkey.txt` remains. They name the
committed policy (`policy/marta.policy.yaml`) by its hash, so step 1 passes
from a fresh clone. They say nothing about how TESTIGO+ performs on real runs.

```bash
testigo verify examples/clean/receipt.json --pubkey "$(cat examples/pubkey.txt)"
testigo verify examples/a3/receipt.json    --pubkey "$(cat examples/pubkey.txt)"
```

To regenerate them (new key, ids, times and signatures; same shape and verdicts):

```bash
.venv/bin/python -m scripts.make_examples
```
