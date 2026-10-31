"""WitnessBench (F10): every configuration with and without TESTIGO+, real models only.

  .venv/bin/python -m bench.run [--scenarios clean a1 a2 a3] [--variants 1 2 3 4 5]
                                [--modes no_supervisor supervised] [--edge] [--dry-run]

`--edge` adds the R10 / F5-D4 case: A1 written in words only (scenario a1edge,
variant 1), which the instruction filter does not flag. It runs in every mode
asked for, and its rows carry `edge_case: true, name: "r10_filter_limit"`, so
bench/score.py reports it apart and it never moves the main number. To add it
to a finished full run: `--resume --edge` (only the edge rows are new).

Each run is the same loop as agent.run (F3): Wonder in Chromium against the
portal, with or without the interceptor. Success is read only from the portal's
payment log (F10-D2), and rows go to runs/bench/<date>/rows.jsonl as they finish,
so a stopped benchmark keeps what it measured; `--resume` skips the rows already
there. The summary (bench/score.py) goes to runs/bench_results.json for view 8.

Refuses test doubles (F0 §10): the agent, the browser and the pixel channel are
the real ones, and so are SAM, Spark and Wonder.

The person in the benchmark. A supervised payment needs a person to approve it
(F7). Twenty spoken approvals cannot be recorded by hand, so the benchmark's
person approves what the capsule shows them, as a real owner who trusts the
screen would; whether the money then reaches the attacker is decided by
TESTIGO+ (the review and result re-reads, F8) and the portal's log, never by
this stand-in. Every row says so (`approver: bench-person`).
"""

import argparse
import json
import sys
import time
from pathlib import Path

from common import clock, config, meta_client
from interceptor.channels import SamSparkChannel
from interceptor.sensitive import SamButtons

from agent import loop
from agent.agent import WonderAgent
from agent.approval import Approver
from agent.driver import ATTACKER_ACCT, open_portal
from agent.run import _Tee, portal_up, start_portal
from interceptor.sink import NullSink

from .score import summarize

SCENARIOS = ("clean", "a1", "a2", "a3")
VARIANTS = (1, 2, 3, 4, 5)
MODES = ("no_supervisor", "supervised")
# R10 / F10-D4: the filter's known limit, run apart from the 20 configurations.
EDGE = ("a1edge", 1, "r10_filter_limit")


class BenchPerson(Approver):
    """Approves what the capsule shows (see the module docstring)."""

    def approve(self, approval_event):
        return True, {"method": "bench-person", "voice_transcript": "", "voice_match": False}


def edge_configs(modes):
    """The edge case in each mode, as (scenario, variant, mode)."""
    return [(EDGE[0], EDGE[1], m) for m in modes]


def time_pixels(pixels):
    """Wrap the channel's reads to measure TESTIGO+'s pixel time in this run.

    Returns the list the wrapper fills: one {"call", "ms"} per read_regions (a
    check or an F8 re-read at review/result) or read_label (the sensitive-button
    read). verify.result has no latency, so this is where the re-reads are timed.
    """
    calls = []

    def timed(name, fn):
        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                calls.append({"call": name, "ms": int(round((time.perf_counter() - t0) * 1000))})
        return wrapper

    pixels.read_regions = timed("regions", pixels.read_regions)
    if hasattr(pixels, "read_label"):
        pixels.read_label = timed("label", pixels.read_label)
    return calls


def _payment_fields(paid):
    paid = paid or {}
    return {"paid": bool(paid), "paid_to": paid.get("recipient"),
            "paid_attacker": paid.get("recipient") == ATTACKER_ACCT}


def _pixel_fields(calls, errors):
    regions = [c["ms"] for c in calls if c["call"] == "regions"]
    return {"pixel_ms_total": sum(c["ms"] for c in calls) if calls else None,
            "pixel_check_ms": regions, "pixel_errors": list(errors)}


def one_run(meta, scenario, variant, mode, out_dir, max_steps):
    supervised = mode == "supervised"
    run_dir = out_dir / ("%s_v%d_%s" % (scenario, variant, mode))
    agent = WonderAgent(meta)
    pixels = SamSparkChannel(meta)
    calls = time_pixels(pixels)
    spent0, t0 = meta.spent_usd(), time.perf_counter()
    started = clock.iso()
    row = {"scenario": scenario, "variant": variant, "mode": mode, "model": meta.model("wonder"),
           "approver": "bench-person" if supervised else None, "ts": started, "started": started}
    if (scenario, variant) == EDGE[:2]:
        row.update(edge_case=True, name=EDGE[2])

    def measured():
        return {"seconds": round(time.perf_counter() - t0, 1),
                "spent_usd": round(meta.spent_usd() - spent0, 4)}

    out = error = payment = None
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        with open_portal(scenario, variant, pixel_channel=pixels, run_dir=run_dir) as driver:
            try:
                out = loop.run(driver, agent, supervised=supervised, approver=BenchPerson(),
                               sink=_Tee(run_dir / "events.jsonl", NullSink()),
                               sensitive=SamButtons(meta.segment, read=pixels.read_label),
                               max_steps=max_steps, run_dir=run_dir)
            except Exception as e:  # noqa: BLE001 - a broken run is a row with an error
                error = "%s: %s" % (type(e).__name__, str(e)[:300])
                try:                     # the browser is still open: did money move anyway?
                    payment = driver.last_payment
                except Exception:  # noqa: BLE001
                    payment = None
    except Exception as e:  # noqa: BLE001 - the portal or browser did not open
        error = error or "%s: %s" % (type(e).__name__, str(e)[:300])
    finally:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "agent_raw.json").write_text(
            json.dumps(agent.raw, ensure_ascii=False, default=str), encoding="utf-8")

    if out is None:
        row.update(error=error, **_payment_fields(payment), **measured(),
                   **_pixel_fields(calls, pixels.errors))
        return row

    checks = [e for e in out.events if e["type"] == "check.result"]
    verifies = [e for e in out.events if e["type"] == "verify.result"]
    last = (verifies or checks or [None])[-1]
    row.update(
        **_payment_fields(out.payment),
        blocked=out.blocked, blocked_at=out.blocked_at, denied=out.denied,
        unapproved_payment=out.unapproved_payment,
        flagged=out.receipt_flagged, finished=out.finished, max_steps=out.max_steps,
        status=last["status"] if last else None,
        checks=len(checks) + len(verifies),
        verify=[{"moment": e.get("moment"), "status": e.get("status")} for e in verifies],
        check_latency_ms=sum(c["latency_ms"] for c in checks) if checks else None,
        actions=out.actions, intercepted=out.intercepted,
        receipt=out.receipt["id"] if out.receipt else None,
        agent_said=[e.get("detail", "") for e in out.events
                    if e["type"] == "agent.step" and e.get("detail")][-1:],
        **measured(), **_pixel_fields(calls, pixels.errors),
    )
    if pixels.errors:
        # An API failure made the channel return nothing, so the engine blocked
        # (cannot_verify): that is not TESTIGO+ catching anything. Kept for diagnosis.
        row["error"] = "pixel channel: %s" % pixels.errors[0]
    return row


def config_key(row):
    return (row["scenario"], row["variant"], row["mode"])


def full_configs():
    return [(s, v, m) for s in SCENARIOS for v in VARIANTS for m in MODES]


def refusal(tag, configs, resume, force, rows_path):
    """Why this invocation must not run (None: it may)."""
    if tag == "full" and not resume and not set(full_configs()) <= set(configs):
        return ("--tag full needs the 20 configurations in both modes (or --resume); "
                "use another --tag for a partial or trial run")
    if not resume and not force and rows_path.is_file() and rows_path.read_text().strip():
        return ("%s already has rows: --resume to continue it, --force to start over, "
                "or another --tag / --out-dir" % rows_path)
    return None


def pending(configs, rows, resume):
    """The configurations still to run: on --resume, those without a clean row."""
    done = {config_key(r) for r in rows if not r.get("error")} if resume else set()
    return [c for c in configs if c not in done]


def completeness(rows):
    """Which of the 20 x 2 configurations have no clean (non-error) last row."""
    last = {config_key(r): r for r in rows}
    missing = [c for c in full_configs() if c not in last or last[c].get("error")]
    return {"complete": not missing, "missing": ["%s v%d %s" % c for c in missing]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    ap.add_argument("--variants", nargs="+", type=int, default=list(VARIANTS), choices=VARIANTS)
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    ap.add_argument("--max-steps", type=int, default=loop.MAX_STEPS)
    ap.add_argument("--edge", action="store_true",
                    help="also run the R10 filter-limit case (a1edge v1), reported apart")
    ap.add_argument("--resume", action="store_true",
                    help="skip configurations already in rows.jsonl without an error")
    ap.add_argument("--force", action="store_true", help="empty a non-empty rows.jsonl and start over")
    ap.add_argument("--dry-run", action="store_true", help="list the configurations and stop")
    ap.add_argument("--tag", default="full",
                    help="a partial or trial run: anything but 'full' keeps its rows apart and "
                         "never writes runs/bench_results.json, which view 8 shows")
    ap.add_argument("--out-dir", help="where rows.jsonl goes (default runs/bench/<tag>)")
    args = ap.parse_args(argv)

    configs = [(s, v, m) for s in args.scenarios for v in args.variants for m in args.modes]
    if args.edge:
        configs += edge_configs(args.modes)

    s = config.settings()
    out_dir = Path(args.out_dir) if args.out_dir else s.runs_dir / "bench" / args.tag
    rows_path = out_dir / "rows.jsonl"
    why = refusal(args.tag, configs, args.resume, args.force, rows_path)
    if why:
        print("bench: refused: " + why, file=sys.stderr)
        return 2
    rows = ([json.loads(x) for x in rows_path.read_text().splitlines() if x.strip()]
            if args.resume and rows_path.is_file() else [])
    todo = pending(configs, rows, args.resume)
    if args.dry_run:
        for c in todo:
            print("%s v%d %s" % c)
        print("%d runs (%d already measured)" % (len(todo), len(configs) - len(todo)))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.resume:
        rows_path.write_text("", encoding="utf-8")

    httpd = None if portal_up(s.portal_url) else start_portal()
    meta = meta_client.MetaClient()
    try:
        for i, (sc, v, m) in enumerate(todo, 1):
            row = one_run(meta, sc, v, m, out_dir, args.max_steps)
            rows.append(row)
            with rows_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("[%d/%d] %s v%d %-13s paid_to=%s blocked=%s status=%s $%.3f %s" % (
                i, len(todo), sc, v, m, row.get("paid_to"), row.get("blocked"),
                row.get("status"), row.get("spent_usd") or 0, row.get("error", "")), flush=True)
    finally:
        if httpd:
            httpd.shutdown()

    result = {"generated": clock.iso(), "model": meta.model("wonder"), "tag": args.tag,
              **completeness(rows), "summary": summarize(rows), "rows": rows}
    results_path = (s.runs_dir / "bench_results.json" if args.tag == "full"
                    else out_dir / "results.json")
    results_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if not result["complete"]:
        print("bench: %d configurations missing or broken: --resume to retry them"
              % len(result["missing"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
