"""Gate g4: SAM 3.1 finds the critical elements on 30 captures (F0 §13).

  .venv/bin/python -m gate.g4_sam_iou [--limit N] [--make] [--phrases "pay button" button]

Runs the real pixel channel (interceptor.channels.SamSparkChannel, F4-D5:
Spark's rough boxes refined by SAM with a box prompt, and SAM's "pay button"
by name) on each capture from gate.g4_make_captures, and compares the box it
returns for the amount, the recipient and the pay button with the reference
box from the portal's data-testid elements. A missing region counts as IoU 0,
and so does a missing reference box (with its reason, never skipped). An API
failure (the channel's `errors`) is recorded apart and its capture is not
measured; the item then fails, because n is not the expected count.
Passes when IoU >= 0.5 on at least 70% of the critical elements.

The captures are taken first when runs/gate/<date>/g4/captures/ has none (or
with --make). --phrases also asks SAM directly for the button with each noun
phrase (plan B: "button"), reported per phrase, outside the pass rule.
Per-element results go to runs/gate/<date>/g4/iou.json.
"""

import argparse
import json

from common import meta_client
from gate import g4_make_captures
from gate.portal import PortalError, failed
from gate.report import report, run_dir
from interceptor.channels import Capture, SamSparkChannel

IOU_MIN = 0.5
SHARE_MIN = 0.70
LABELS = ("amount", "recipient", "pay button")


def iou(a, b):
    """Intersection over union of two [x1, y1, x2, y2] boxes (0 when either is missing)."""
    if not a or not b:
        return 0.0
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area = lambda r: max(0, r[2] - r[0]) * max(0, r[3] - r[1])  # noqa: E731
    total = area(a) + area(b) - inter
    return inter / total if total > 0 else 0.0


def score(elements, iou_min=IOU_MIN):
    """(hits, n, share) over a list of {"iou": float} elements."""
    n = len(elements)
    hits = sum(1 for e in elements if e["iou"] >= iou_min)
    return hits, n, (hits / n if n else 0.0)


def measure(t, regions):
    """One element per critical label of a capture. A label with no reference
    box is a failure with its reason (IoU 0), never skipped."""
    got = {r["label"]: r for r in regions}
    out = []
    for label in LABELS:
        ref = t["truth"].get(label)
        r = got.get(label)
        e = {"capture": t["name"], "screen": t["screen"], "label": label, "truth": ref,
             "box": r["box"] if r else None, "confidence": r.get("confidence") if r else None,
             "iou": round(iou(ref, r["box"] if r else None), 3)}
        if not ref:
            e["reason"] = "no reference box (data-testid not found in the capture)"
        elif not r:
            e["reason"] = "the channel returned no region"
        out.append(e)
    return out


def verdict(elements, expected):
    """(passed, hits, n, share): fails when n is not the expected count."""
    hits, n, share = score(elements)
    return n == expected and n > 0 and share >= SHARE_MIN, hits, n, share


def load_or_make(limit, make):
    path = run_dir("g4") / "captures" / "truth.json"
    want = len(g4_make_captures.plan(limit))
    truth = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    if make or len(truth) < want:          # missing, or taken with a smaller --limit
        return g4_make_captures.make(limit)
    return truth[:want]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="measure only the first N captures (default all 30)")
    ap.add_argument("--make", action="store_true", help="retake the captures first")
    ap.add_argument("--phrases", nargs="*", default=[],
                    help="extra noun phrases to ask SAM for the button, e.g. button")
    args = ap.parse_args(argv)

    try:
        truth = load_or_make(args.limit, args.make)
    except PortalError as e:
        return failed("g4", e, "IoU>=%.1f on >=%d%% of critical elements" % (IOU_MIN, round(100 * SHARE_MIN)))
    cap_dir = run_dir("g4") / "captures"
    meta = meta_client.MetaClient()
    channel = SamSparkChannel(meta)
    elements, phrase_rows, errors, api_errors = [], {p: [] for p in args.phrases}, [], []
    for i, t in enumerate(truth, 1):
        png = (cap_dir / t["image"]).read_bytes()
        seen = len(channel.errors)
        regions = channel.read_regions(Capture(i, [], [], {}, screenshot=png))
        failed_api = channel.errors[seen:]
        if failed_api:
            # An API failure is not SAM missing the element: recorded apart, its
            # elements are not measured, and the count then falls short of n.
            api_errors.append({"capture": t["name"], "errors": failed_api})
            print("g4: %s API error: %s" % (t["name"], failed_api[0]), flush=True)
            continue
        if not regions:
            errors.append("%s: the channel returned no regions" % t["name"])
        elements += measure(t, regions)
        for phrase in args.phrases:
            found, _ = meta.segment(png, phrase)
            best = max(found, key=lambda b: b.get("confidence") or 0)["box"] if found else None
            phrase_rows[phrase].append(round(iou(t["truth"].get("pay button"), best), 3))
        print("g4: %s %s" % (t["name"], " ".join("%s=%.2f" % (e["label"], e["iou"])
                                                for e in elements if e["capture"] == t["name"])),
              flush=True)

    (run_dir("g4") / "iou.json").write_text(json.dumps(elements, indent=2), encoding="utf-8")
    expected = len(g4_make_captures.plan(args.limit)) * len(LABELS)
    passed, hits, n, share = verdict(elements, expected)
    by_label = {}
    for label in LABELS:
        h, m, _ = score([e for e in elements if e["label"] == label])
        by_label[label] = "%d/%d" % (h, m)
    by_screen = {}
    for screen in ("order", "review"):
        h, m, _ = score([e for e in elements if e["screen"] == screen])
        if m:
            by_screen[screen] = "%d/%d" % (h, m)
    details = {"captures": len(truth), "by_label": by_label, "by_screen": by_screen,
               "phrases": {p: "%d/%d IoU>=%.1f" % (sum(1 for v in vals if v >= IOU_MIN), len(vals), IOU_MIN)
                           for p, vals in phrase_rows.items()},
               "expected_elements": expected, "api_errors": api_errors,
               "no_reference_box": sum(1 for e in elements if e["truth"] is None),
               "errors": errors, "spent_usd_total": round(meta.spent_usd(), 4)}
    metric = "%d/%d elements with IoU>=%.1f (%.0f%%)" % (hits, n, IOU_MIN, 100 * share)
    if n != expected:
        metric += "; incomplete: %d of %d elements measured (%d captures with API errors)" % (
            n, expected, len(api_errors))
    return report("g4", passed, metric,
                  "IoU>=%.1f on >=%d%% of critical elements" % (IOU_MIN, round(100 * SHARE_MIN)),
                  n, details)


if __name__ == "__main__":
    raise SystemExit(main())
