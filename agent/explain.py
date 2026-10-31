"""Explain an unsupervised run after it ended (view 3), observe only.

  .venv/bin/python -m agent.run --scenario a2 --no-supervisor --explain

Without TESTIGO+ the pixel channel never runs, so view 3 has no region to show
where the attack text was. With `--explain`, once the run is over, the pixel
channel and the code-vs-pixels comparison (interceptor.engine.Interceptor.explain)
run ONCE on the frame where the agent confirmed the order (or the last frame
an action ran on, or the last frame seen), and one `explain.result` event says
what they found: the instruction-like lines on each side, the regions, and a
box around each painted line (SamSparkChannel.locate_text).

It never blocks, never changes the run, its outcome.json or WitnessBench (which
never passes --explain), and the event says `after_run: true`.
"""

import copy

from common import config
from interceptor import events as ev
from interceptor.engine import Interceptor
from interceptor.policy import load as load_policy

MAX_LOCATED = 3          # boxes for at most this many painted lines (one Spark + SAM call each)


def capture_to_explain(out):
    """The confirming frame, else the last frame an action ran on, else the last frame."""
    return out.order_capture or out.executed_capture or out.last_capture


def explain_run(out, pixel_channel, policy=None, locate=None):
    """Returns the explain.result event, or None when the run saw no frame.
    Reads a copy of the capture, so the run's own objects are left as they were."""
    capture = capture_to_explain(out)
    if capture is None:
        return None
    capture = copy.copy(capture)
    policy = policy or load_policy(config.policy_path())
    found = Interceptor(policy, pixel_channel).explain(capture)
    regions = [dict(r) for r in found["regions"]]
    code_only, pixels_only = found["code_only_text"], found["pixels_only_text"]

    locate = locate or getattr(pixel_channel, "locate_text", None)
    if locate is not None and capture.screenshot:
        for line in pixels_only[:MAX_LOCATED]:
            box = locate(capture.screenshot, line)
            if box:
                regions.append({"label": "divergent text", "box": [int(v) for v in box],
                                "text": line, "confidence": None})

    if pixels_only:
        status, reason = ev.DIVERGENCE, "visible text not in page code"
    elif code_only:
        status, reason = ev.DIVERGENCE, "page code text not visible"
    elif found["policy_reason"]:
        status, reason = ev.POLICY_VIOLATION, found["policy_reason"]
    else:
        status, reason = "none", "no instruction-like divergence and no policy problem found"
    return ev.explain_result(capture.frame, status, regions, list(code_only), list(pixels_only),
                             found["latency_ms"], reason, image=getattr(capture, "image", None))
