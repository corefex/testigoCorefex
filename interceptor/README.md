# TESTIGO+ interceptor

The checker that sits between the agent *Wonder* and the browser. Nothing the
agent proposes reaches the page without passing through `check`; after the
click it runs `verify`. This folder is the **decision core** — pure, standard
library only, no browser, model or network — so it is testable today and wires
to Playwright / SAM 3.1 / Spark / FastAPI later without changing the rules.

Everything is a simulation: fake supplier, shop and attacker address.

## Run

```bash
make test                                         # unit tests (all packages)
.venv/bin/python -m tests.demos.interceptor_demo  # fixture demo of the five rules
.venv/bin/python -m interceptor.policy            # inspect the signed policy
```

Paths resolve from the repo root (`common/config.py`). The test captures and
the demo live in `tests/` since F0: they prove the rules are wired, not that
detection works on real captures.

## The five rules (in order, first match decides)

| # | Condition (read from the **pixels**, never the DOM) | Verdict | Action |
|---|---|---|---|
| 1 | SAM can't find amount, address or confirm button ≥ 0.50 confidence | `cannot_verify` | block |
| 2 | Text in the code not drawn, or drawn text not in the code | `divergence` | block |
| 3 | Pixel delivery address/total breaks the policy (or a stray address is on screen) | `policy_violation` | block |
| 4 | All agree and it confirms the order | `ok` | ask for approval |
| 5 | After the click, executed crops ≠ approved crops | `mismatch` | flag the receipt |

Rule 1 runs first on purpose: a comparison you can't read is not a pass. The
address and amount used for rule 3 come from the pixel channel, so a hidden
or swapped DOM value can't push an order to another address.

## Pieces

```
interceptor/
  policy.py      load + hash the signed policy; address/amount checks
  events.py      constructors for every event (check.result, verify.result, …)
  channels.py    Capture + PixelChannel; FixtureChannel (tests) and the
                 SamSparkChannel stub (plug SAM 3.1 + Spark here)
  engine.py      the five rules + after-click verify  <- the contribution
  service.py     FastAPI service: status page now, events and UI later (F11)
  test_engine.py unit tests
```

The committed policy lives in `policy/marta.policy.yaml`; one signed live from
view 1 goes to `runs/policy/active.policy.yaml` and wins while it exists
(`common.config.policy_path()`, used by the service, the loop, the bench and
`testigo verify`). Its sha256 is stamped in and is the same hash the receipt and
`testigo verify` will use.

## Wiring the real inputs later

- **Capture** — fill `code_lines` from the page's DOM text and `rendered_lines`
  from what is actually painted (incl. text inside images); screenshot bytes
  and per-region crops from Playwright.
- **PixelChannel** — `SamSparkChannel(sam, spark)`: `sam(screenshot)` returns
  boxes + scores (SAM 3.1), `spark(crop)` reads each crop (Spark 1.3). Any
  failure must return low confidence so rule 1 blocks rather than guessing.
- **Transport** — the engine returns plain dict events; a FastAPI app pushes
  them over WebSocket to the interface. The core doesn't change.

## Acceptance (Oct 30)

`.venv/bin/python -m tests.demos.interceptor_demo` asserts, on fixtures,: A1 and A2 are blocked, clean is not,
plus `cannot_verify`, `policy_violation` and the after-click `mismatch`.

## What is real vs simulated

Real: the decision logic, the divergence detection, the event contract, the
policy hash, the after-click comparison. Simulated here: the screenshots and
SAM/Spark readings (fixtures). Plug the two adapters above in to run it live.
