"""The output contract every gate script follows (F0 §13).

One JSON line on stdout: {"id", "pass", "metric", "threshold", "n", "details"};
the same object and any raw data under runs/gate/<date>/; exit code 0 or 1.
`passed=None` means omitted (the item cannot run here, e.g. no GPU or no
`say`): "pass" is null and the exit code is 0; run_gate decides what that means.
"""

import json

from common import clock, config


def run_dir(gate_id):
    d = config.settings().runs_dir / "gate" / clock.today() / gate_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def report(gate_id, passed, metric, threshold, n, details):
    result = {"id": gate_id, "pass": None if passed is None else bool(passed), "metric": metric,
              "threshold": threshold, "n": n, "details": details}
    (run_dir(gate_id) / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed or passed is None else 1
