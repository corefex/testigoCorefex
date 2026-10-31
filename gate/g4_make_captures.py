"""Gate g4, step 1: the captures and their reference boxes (F0 §13). No models.

  .venv/bin/python -m gate.g4_make_captures [--limit N]

Takes, with Playwright on the running portal (1280x800, scale 1):
  - 20 order pages: 4 scenarios x 5 variants, after "Add order items", so the
    amount, the recipient and the pay button are on screen (60 elements);
  - 10 review screens, after "Review payment": clean and a3, variants 1-5
    (a3 is the scenario whose review screen differs; 20 elements).

The reference boxes come from the portal's data-testid elements, as painted
(a button or bordered field whole, text by its extent). That is allowed here because it is MEASUREMENT, after the
fact: the pixel channel never sees them. The recipient's box covers the
account field and the name next to it, as the channel is asked to read both.

Writes runs/gate/<date>/g4/captures/<name>.png and truth.json. --limit takes
only the first N captures (order pages first).
"""

import argparse
import json

from agent.driver import open_portal
from gate.portal import portal
from gate.report import run_dir

SCENARIOS = ("clean", "a1", "a2", "a3")
VARIANTS = (1, 2, 3, 4, 5)
REVIEW_SCENARIOS = ("clean", "a3")

# label -> the data-testid elements whose union is the reference box
ORDER_TRUTH = {"amount": ("amount",), "recipient": ("recipient", "recipient-name"),
               "pay button": ("pay-button",)}
REVIEW_TRUTH = {"amount": ("amount",), "recipient": ("recipient", "recipient-name"),
                "pay button": ("confirm-button",)}


def plan(limit=None):
    """The captures to take, in order: (name, scenario, variant, screen)."""
    out = [("order_%s_v%d" % (s, v), s, v, "order") for s in SCENARIOS for v in VARIANTS]
    out += [("review_%s_v%d" % (s, v), s, v, "review") for s in REVIEW_SCENARIOS for v in VARIANTS]
    return out[:limit] if limit else out


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


# Where the element is painted, in CSS px (= screenshot px at scale 1): a button
# or a bordered text field is its whole box (both are visible shapes); a
# borderless field (the review screen's) is its text; any other element is the
# extent of its text (a full-width <div> around "COP 120,000" is not the amount).
_BOX_JS = """el => {
  const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
  const box = (x1, y1, x2, y2) => [x1, y1, x2, y2].map(Math.round);
  if (el.tagName === 'BUTTON') return box(r.left, r.top, r.right, r.bottom);
  if (el.tagName === 'INPUT') {
    if (parseFloat(cs.borderTopWidth) > 0) return box(r.left, r.top, r.right, r.bottom);
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.font = cs.font;
    const x1 = r.left + parseFloat(cs.paddingLeft);
    return box(x1, r.top, Math.min(r.right, x1 + ctx.measureText(el.value).width), r.bottom);
  }
  const range = document.createRange();
  range.selectNodeContents(el);
  const t = range.getBoundingClientRect();
  if (!t.width || !t.height) return null;
  return box(t.left, t.top, t.right, t.bottom);
}"""


def _box(page, testid):
    loc = page.locator('[data-testid="%s"]' % testid).first
    if not loc.count() or not loc.is_visible():
        return None
    return loc.evaluate(_BOX_JS)


def truth_boxes(page, spec):
    out = {}
    for label, ids in spec.items():
        boxes = [b for b in (_box(page, i) for i in ids) if b]
        if boxes:
            out[label] = union(boxes)
    return out


def capture(name, scenario, variant, screen, cap_dir):
    with open_portal(scenario, variant) as driver:
        page = driver.page
        page.click('[data-testid="add-items"]')
        page.wait_for_load_state("networkidle")
        spec = ORDER_TRUTH
        if screen == "review":
            page.click('[data-testid="pay-button"]')
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(400)      # let A3's late rewrites land (v5: 150 ms)
            spec = REVIEW_TRUTH
        png = page.screenshot(type="png")
        boxes = truth_boxes(page, spec)
    (cap_dir / (name + ".png")).write_bytes(png)
    return {"name": name, "scenario": scenario, "variant": variant, "screen": screen,
            "image": name + ".png", "truth": boxes}


def make(limit=None):
    """Take the captures; returns the truth list (also written to truth.json)."""
    cap_dir = run_dir("g4") / "captures"
    cap_dir.mkdir(parents=True, exist_ok=True)
    with portal():
        truth = [capture(n, s, v, scr, cap_dir) for n, s, v, scr in plan(limit)]
    (cap_dir / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return truth


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, help="take only the first N captures (default all 30)")
    args = ap.parse_args(argv)
    truth = make(args.limit)
    print(json.dumps({"captures": len(truth),
                      "elements": sum(len(t["truth"]) for t in truth),
                      "dir": str(run_dir("g4") / "captures")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
