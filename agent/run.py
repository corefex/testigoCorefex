"""One real run: Wonder drives the portal in Chromium, with or without TESTIGO+.

  .venv/bin/python -m agent.run --scenario clean [--variant 1] [--no-supervisor] [--headed]

Uses the real Meta API (spend goes to runs/usage.jsonl). If the portal is not
up on PORTAL_PORT, one is started in this process. Every event goes to the
interceptor service for the interface (best effort) and to
runs/<date>/<run>/events.jsonl; screenshots, Wonder's raw answers and a summary
(outcome.json) land next to them. An approved payment also leaves its signed
receipt.json and evidence crops there (F9; `testigo verify` checks them).

Supervised runs classify clicks with SAM (R4) and check the sensitive ones with
the real pixel channel (F4). A payment that passes is approved by the person at
the terminal (ConsoleApprover) until the voice capsule (F7) is wired; with no
terminal, nobody approves and the payment does not happen.
"""

import argparse
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from common import clock, config, meta_client
from interceptor.channels import SamSparkChannel
from interceptor.sensitive import SamButtons
from interceptor.sink import default_sink

from . import loop
from .agent import WonderAgent
from .approval import ConsoleApprover
from .driver import open_portal


class _Tee:
    """Events to the interface and to a file."""

    def __init__(self, path, sink):
        self.path, self.sink = path, sink

    def publish(self, e):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.sink.publish(e)


def portal_up(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/", timeout=2):
            return True
    except OSError:
        return False


def start_portal():
    from portal.server import Handler
    s = config.settings()
    httpd = ThreadingHTTPServer((s.portal_host, s.portal_port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", default="clean", choices=("clean", "a1", "a2", "a3"))
    ap.add_argument("--variant", type=int, default=1, choices=range(1, 6))
    ap.add_argument("--no-supervisor", action="store_true")
    ap.add_argument("--headed", action="store_true", help="show the browser (for recording)")
    ap.add_argument("--max-steps", type=int, default=loop.MAX_STEPS)
    ap.add_argument("--model", default="wonder", choices=("wonder", "spark"),
                    help="spark only to develop cheaply; WitnessBench and the video use wonder")
    args = ap.parse_args(argv)

    s = config.settings()
    httpd = None if portal_up(s.portal_url) else start_portal()
    supervised = not args.no_supervisor
    run_id = "%s_%s_v%d_%s" % (clock.now().strftime("%H%M%S"), args.scenario, args.variant,
                               "sup" if supervised else "nosup")
    run_dir = s.runs_dir / clock.today() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = meta_client.MetaClient()
    agent = WonderAgent(meta, tool=args.model)
    spent0 = meta.spent_usd()
    try:
        with open_portal(args.scenario, args.variant, pixel_channel=SamSparkChannel(meta),
                         run_dir=run_dir, headless=not args.headed) as driver:
            out = loop.run(driver, agent, supervised=supervised, approver=ConsoleApprover(),
                           sink=_Tee(run_dir / "events.jsonl", default_sink()),
                           sensitive=SamButtons(meta.segment), max_steps=args.max_steps,
                           run_dir=run_dir)
    finally:
        (run_dir / "agent_raw.json").write_text(
            json.dumps(agent.raw, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if httpd:
            httpd.shutdown()

    summary = {
        "run": run_id, "model": meta.model(args.model), "mode": out.mode,
        "scenario": args.scenario, "variant": args.variant,
        "actions": out.actions, "intercepted": out.intercepted, "checked": out.checked,
        "finished": out.finished, "max_steps": out.max_steps, "blocked": out.blocked,
        "denied": out.denied,
        "checks": [{k: e[k] for k in ("status", "reason", "latency_ms", "code_only_text",
                                      "pixels_only_text")} | {"regions": [
                       {k: r[k] for k in ("label", "text", "confidence")} for r in e["regions"]]}
                   for e in out.events if e["type"] == "check.result"],
        "payment": out.payment, "attack_success": out.attack_success,
        "receipt": out.receipt and {"id": out.receipt["id"],
                                    "comparison": out.receipt.get("comparison"),
                                    "path": out.receipt_path and out.receipt_path.name},
        "spent_usd": round(meta.spent_usd() - spent0, 4),
        "steps": [e["label"] for e in out.events if e["type"] == "agent.step"],
    }
    (run_dir / "outcome.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
