"""WitnessBench (F10): every configuration with and without TESTIGO+, real models only.

  .venv/bin/python -m bench.run [--scenarios clean a1 a2 a3] [--variants 1 2 3 4 5]
                                [--modes no_supervisor supervised] [--dry-run]

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
import time

from common import clock, config, meta_client
from interceptor.channels import SamSparkChannel
from interceptor.sensitive import SamButtons

from agent import loop
from agent.agent import WonderAgent
from agent.approval import Approver
from agent.driver import ATTACKER_ACCT, open_portal
from agent.run import portal_up, start_portal

from .score import summarize

SCENARIOS = ("clean", "a1", "a2", "a3")
VARIANTS = (1, 2, 3, 4, 5)
MODES = ("no_supervisor", "supervised")


class BenchPerson(Approver):
    """Approves what the capsule shows (see the module docstring)."""

    def approve(self, approval_event):
        return True, {"method": "bench-person", "voice_transcript": "", "voice_match": False}


def one_run(meta, scenario, variant, mode, out_dir, max_steps):
    supervised = mode == "supervised"
    run_dir = out_dir / ("%s_v%d_%s" % (scenario, variant, mode))
    agent = WonderAgent(meta)
    pixels = SamSparkChannel(meta)
    spent0, t0 = meta.spent_usd(), time.perf_counter()
    row = {"scenario": scenario, "variant": variant, "mode": mode, "model": meta.model("wonder"),
           "approver": "bench-person" if supervised else None, "ts": clock.iso()}
    try:
        with open_portal(scenario, variant, pixel_channel=pixels, run_dir=run_dir) as driver:
            out = loop.run(driver, agent, supervised=supervised, approver=BenchPerson(),
                           sensitive=SamButtons(meta.segment, read=pixels.read_label),
                           max_steps=max_steps, run_dir=run_dir)
    except Exception as e:  # noqa: BLE001 - a broken run is a row with an error, not a crash
        row.update(error="%s: %s" % (type(e).__name__, str(e)[:300]))
        return row
    finally:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "agent_raw.json").write_text(
            json.dumps(agent.raw, ensure_ascii=False, default=str), encoding="utf-8")

    checks = [e for e in out.events if e["type"] == "check.result"]
    verifies = [e for e in out.events if e["type"] == "verify.result"]
    last = (verifies or checks or [None])[-1]
    paid = out.payment or {}
    row.update(
        paid=bool(paid), paid_to=paid.get("recipient"),
        paid_attacker=paid.get("recipient") == ATTACKER_ACCT,
        blocked=out.blocked, blocked_at=out.blocked_at, denied=out.denied,
        unapproved_payment=out.unapproved_payment,
        flagged=out.receipt_flagged, finished=out.finished, max_steps=out.max_steps,
        status=last["status"] if last else None,
        check_latency_ms=sum(c["latency_ms"] for c in checks) if checks else None,
        actions=out.actions, intercepted=out.intercepted,
        receipt=out.receipt["id"] if out.receipt else None,
        seconds=round(time.perf_counter() - t0, 1),
        spent_usd=round(meta.spent_usd() - spent0, 4),
        agent_said=[e.get("detail", "") for e in out.events
                    if e["type"] == "agent.step" and e.get("detail")][-1:],
    )
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS), choices=SCENARIOS)
    ap.add_argument("--variants", nargs="+", type=int, default=list(VARIANTS), choices=VARIANTS)
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    ap.add_argument("--max-steps", type=int, default=loop.MAX_STEPS)
    ap.add_argument("--resume", action="store_true", help="skip configurations already in rows.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="list the configurations and stop")
    args = ap.parse_args(argv)

    configs = [(s, v, m) for s in args.scenarios for v in args.variants for m in args.modes]
    if args.dry_run:
        for c in configs:
            print("%s v%d %s" % c)
        print("%d runs" % len(configs))
        return 0

    s = config.settings()
    out_dir = s.runs_dir / "bench" / clock.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"
    rows = [json.loads(x) for x in rows_path.read_text().splitlines()] if rows_path.is_file() else []
    done = {(r["scenario"], r["variant"], r["mode"]) for r in rows} if args.resume else set()
    if not args.resume:
        rows = []
        rows_path.write_text("", encoding="utf-8")

    httpd = None if portal_up(s.portal_url) else start_portal()
    meta = meta_client.MetaClient()
    try:
        for i, (sc, v, m) in enumerate(configs, 1):
            if (sc, v, m) in done:
                continue
            row = one_run(meta, sc, v, m, out_dir, args.max_steps)
            rows.append(row)
            with rows_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("[%d/%d] %s v%d %-13s paid_to=%s blocked=%s status=%s $%.3f %s" % (
                i, len(configs), sc, v, m, row.get("paid_to"), row.get("blocked"),
                row.get("status"), row.get("spent_usd") or 0, row.get("error", "")), flush=True)
    finally:
        if httpd:
            httpd.shutdown()

    result = {"generated": clock.iso(), "model": meta.model("wonder"),
              "summary": summarize(rows), "rows": rows}
    (s.runs_dir / "bench_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
