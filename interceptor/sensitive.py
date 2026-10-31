"""Which agent actions are sensitive (F3 §3b, decision R4).

Wonder hands us clicks with coordinates, not "pay". A click is sensitive when it
lands inside the box SAM returns for one of the protected buttons on that very
screenshot. Decided from pixels only: never from the DOM or a data-testid, which
an attacker could rename while leaving the button looking the same.

Only sensitive actions run the full pixel check (F4-F6); the rest are logged and
executed, so cost and latency grow only on the steps that matter.
"""

BUTTONS = ("pay button", "confirm button")


class SamButtons:
    """`segment(png, phrase) -> (boxes, ms)`, normally MetaClient.segment."""

    def __init__(self, segment, phrases=BUTTONS):
        self.segment = segment
        self.phrases = phrases

    def __call__(self, action, capture):
        """(sensitive, reason). A SAM failure counts as sensitive: in doubt, check."""
        if action.get("kind") == "pay":
            return True, "payment action"
        if action.get("kind") not in ("click", "double_click"):
            return False, ""
        x, y = action["x"], action["y"]
        for phrase in self.phrases:
            try:
                boxes, _ = self.segment(capture.screenshot, phrase)
            except Exception as e:  # noqa: BLE001
                return True, "could not locate %s (%s)" % (phrase, type(e).__name__)
            for b in boxes:
                x1, y1, x2, y2 = b["box"]
                if x1 <= x <= x2 and y1 <= y <= y2:
                    return True, "click on %s" % phrase
        return False, ""


def payment_only(action, capture):
    """The classifier for test doubles, whose agent proposes `pay` directly."""
    return (True, "payment action") if action.get("kind") == "pay" else (False, "")
