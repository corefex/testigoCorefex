"""Which agent actions are sensitive (F3 §3b, decision R4).

Wonder hands us clicks with coordinates, not "confirm the order". A click is sensitive when it
lands inside the box SAM returns for one of the protected buttons on that very
screenshot. Decided from pixels only: never from the DOM or a data-testid, which
an attacker could rename while leaving the button looking the same.

Only sensitive actions run the full pixel check (F4-F6); the rest are logged and
executed, so cost and latency grow only on the steps that matter.
"""

BUTTONS = ("confirm button", "order button")


# SAM also marks other buttons as the one asked for (it marked "Add order items"
# with 0.56 on 31 Oct). A box is skipped only when its label, read from the
# pixels, is one of these known non-confirming actions; anything else stays
# sensitive, so drawing the confirm button as "Continuar" does not dodge the
# check (review F8).
NOT_CONFIRM = ("add order items", "add items", "add to cart", "agregar", "añadir",
               "back", "volver", "cancel", "cancelar")
# Keys that submit a focused form, alone or in a combination (Control+Enter):
# as sensitive as clicking its button.
SUBMIT_KEYS = ("enter", "return", "numpadenter", "space", " ")
CONFIRM_HINTS = ("confirm", "place order", "submit", "deliver", "ship", "send",
                 "pedir", "entrega", "envi")


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
        kind = action.get("kind")
        if kind == "confirm":
            return True, "order confirmation"
        if kind == "keypress" and any(
                part.strip().lower() in SUBMIT_KEYS or part == " "
                for k in action.get("keys", []) for part in str(k).split("+")):
            return True, "a key that submits the form (%s)" % "+".join(action["keys"])
        if kind == "type" and ("\n" in action.get("text", "") or "\r" in action.get("text", "")):
            return True, "typed text that submits the form"
        if kind not in ("click", "double_click"):
            return False, ""
        x, y = action["x"], action["y"]
        any_button = False
        for phrase in self.phrases:
            try:
                boxes, _ = self.segment(capture.screenshot, phrase)
            except Exception as e:  # noqa: BLE001
                return True, "could not locate %s (%s)" % (phrase, type(e).__name__)
            any_button = any_button or bool(boxes)
            for b in boxes:
                x1, y1, x2, y2 = b["box"]
                if x1 <= x <= x2 and y1 <= y <= y2:
                    return self._label_says_confirm(capture, b["box"], phrase)
        if not any_button:
            # No confirm button found at all: a restyled page could hide it. In doubt, check.
            return True, "no confirm button found on this screen"
        return False, ""

    def _label_says_confirm(self, capture, box, phrase):
        if self.read is None:
            return True, "click on %s" % phrase
        from .channels import crop
        try:
            label = self.read(crop(capture.screenshot, box))
        except Exception as e:  # noqa: BLE001 - in doubt, check
            return True, "click on %s (label unreadable: %s)" % (phrase, type(e).__name__)
        t = " ".join(str(label or "").lower().split())
        if t in NOT_CONFIRM and not any(h in t for h in CONFIRM_HINTS):
            return False, "button %r does not confirm the order" % label
        return True, "click on %s %r" % (phrase, label)


def confirm_only(action, capture):
    """The classifier for test doubles, whose agent proposes `confirm` directly."""
    return (True, "order confirmation") if action.get("kind") == "confirm" else (False, "")
