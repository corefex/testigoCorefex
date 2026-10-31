"""Which agent actions are sensitive (F3 §3b, decision R4).

Wonder hands us clicks with coordinates, not "pay". A click is sensitive when it
lands inside the box SAM returns for one of the protected buttons on that very
screenshot. Decided from pixels only: never from the DOM or a data-testid, which
an attacker could rename while leaving the button looking the same.

Only sensitive actions run the full pixel check (F4-F6); the rest are logged and
executed, so cost and latency grow only on the steps that matter.
"""

BUTTONS = ("pay button", "confirm button")


# What a protected button says. SAM also calls other buttons a "pay button"
# (it marked "Add order items" with 0.56 on 31 Oct), so the label is read too.
PAY_WORDS = ("pay", "confirm", "review payment", "pagar", "paga", "confirmar", "transfer", "send")


class SamButtons:
    """`segment(png, phrase) -> (boxes, ms)`, normally MetaClient.segment;
    `read(crop_png) -> str` reads a button's label from the pixels (Spark). Without
    `read`, any SAM button box counts (test doubles)."""

    def __init__(self, segment, phrases=BUTTONS, read=None):
        self.segment = segment
        self.phrases = phrases
        self.read = read

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
                    return self._label_says_pay(capture, b["box"], phrase)
        return False, ""

    def _label_says_pay(self, capture, box, phrase):
        if self.read is None:
            return True, "click on %s" % phrase
        from .channels import crop
        try:
            label = self.read(crop(capture.screenshot, box))
        except Exception as e:  # noqa: BLE001 - in doubt, check
            return True, "click on %s (label unreadable: %s)" % (phrase, type(e).__name__)
        t = " ".join(str(label or "").lower().split())
        if any(w in t for w in PAY_WORDS):
            return True, "click on %s %r" % (phrase, label)
        return False, "button %r is not a payment" % label


def payment_only(action, capture):
    """The classifier for test doubles, whose agent proposes `pay` directly."""
    return (True, "payment action") if action.get("kind") == "pay" else (False, "")
