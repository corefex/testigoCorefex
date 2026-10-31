"""F8: the two moments after approval, on a two-step flow (offline doubles).

Order page (approve) -> review screen (re-read before confirming: a mismatch
blocks) -> result (re-read after the click: a mismatch flags the receipt).
Compared by the values read from the pixels, never by the DOM.
"""

import unittest

from agent.agent import Agent
from agent.driver import BrowserDriver, SHOP_ADDRESS, ATTACKER_ADDRESS
from agent.loop import run
from interceptor.channels import Capture, FixtureChannel
from tests.fixtures import captures as fx

ORDER, REVIEW, RESULT = 150, 151, 152
TEST_SEED = bytes(range(32))     # a throwaway test key, never the owner's


class TwoStep(BrowserDriver):
    """Order page, review screen, result. `review_to` / `delivered_to`: the
    "Deliver to" the review screen shows and the address the portal records."""
    is_test_double = True
    scenario, variant = "clean", 1

    def __init__(self, review_to=fx.SHOP, delivered_to=SHOP_ADDRESS):
        self.review_to, self.delivered_to = review_to, delivered_to
        self.page = ORDER
        self.ran = []
        self._order = None
        self.ch = FixtureChannel()
        self.ch.set_regions(ORDER, fx._regions())
        self.ch.set_regions(REVIEW, fx._regions(address=review_to))
        self.ch.set_regions(RESULT, fx._regions(address=delivered_to))

    def _cap(self, frame, tag):
        return Capture(frame, list(fx._BASE_LINES), list(fx._BASE_LINES), fx._crops(tag))

    def observe(self):
        return self._cap(self.page, "%s-%d" % (self.review_to, self.page))

    def observe_after(self):
        return self._cap(RESULT, self.delivered_to)

    def pixel_channel(self):
        return self.ch

    def execute(self, action):
        self.ran.append(self.page)
        if self.page == ORDER:
            self.page = REVIEW
        elif self.page == REVIEW:
            self._order = {"address": self.delivered_to, "amount_cop": 120000}

    @property
    def last_order(self):
        return self._order


class Confirm(Agent):
    """Clicks "Review order", then "Confirm order": both sensitive."""
    is_test_double = True

    def propose(self, observation):
        return {"kind": "confirm"}


def verifies(out):
    return [(e["moment"], e["status"]) for e in out.events if e["type"] == "verify.result"]


class MomentsTests(unittest.TestCase):
    def test_review_matches_and_result_matches(self):
        drv = TwoStep()
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "match"), ("result", "match")])
        self.assertFalse(out.blocked or out.receipt_flagged)
        self.assertEqual(out.order["address"], SHOP_ADDRESS)
        self.assertEqual(out.receipt["comparison"]["status"], "match")
        self.assertEqual(out.receipt["comparison"]["by"], "read")

    def test_address_changed_on_review_blocks_before_confirm(self):
        drv = TwoStep(review_to="Tienda Doña Marta · " + ATTACKER_ADDRESS, delivered_to=ATTACKER_ADDRESS)
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "mismatch")])
        self.assertTrue(out.blocked)
        self.assertEqual(out.blocked_at, "review")
        self.assertIsNone(out.order)
        self.assertEqual(drv.ran, [ORDER])           # the confirm click never ran
        vr = [e for e in out.events if e["type"] == "verify.result"][0]
        self.assertIn(ATTACKER_ADDRESS, vr["read"]["executed"]["address"])

    def test_changed_after_the_click_flags_the_receipt(self):
        drv = TwoStep(delivered_to=ATTACKER_ADDRESS)          # review looked right, result did not
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "match"), ("result", "mismatch")])
        self.assertTrue(out.receipt_flagged)
        self.assertFalse(out.attack_success)
        self.assertEqual(out.receipt["comparison"]["status"], "mismatch")

    def test_formatting_differences_are_not_a_mismatch(self):
        # the review screen shows the address in another layout, case and abbreviation
        drv = TwoStep(review_to="DELIVER TO Cl. 45 No. 12–30, BOGOTÁ Tienda Doña Marta")
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out)[0], ("review", "match"))


if __name__ == "__main__":
    unittest.main()


class ReviewFindingsTests(unittest.TestCase):
    """Code review of F8 (31 Oct)."""

    def test_blocked_at_review_leaves_a_signed_blocked_receipt(self):
        drv = TwoStep(review_to="Tienda Doña Marta · " + ATTACKER_ADDRESS, delivered_to=ATTACKER_ADDRESS)
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual((out.receipt["status"], out.receipt["blocked_at"]), ("blocked", "review"))
        self.assertIsNone(out.receipt["executed"])

    def test_partial_result_read_still_proves_a_mismatch(self):
        drv = TwoStep(delivered_to=ATTACKER_ADDRESS)
        drv.ch.set_regions(RESULT, [r for r in fx._regions(address=ATTACKER_ADDRESS)
                                    if r["label"] != "amount"])
        out = run(drv, Confirm(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out)[-1], ("result", "mismatch"))
        self.assertEqual(out.receipt["comparison"]["status"], "mismatch")

    def test_an_order_no_check_saw_is_reported(self):
        class Enter(Agent):
            is_test_double = True

            def propose(self, observation):
                return {"kind": "keypress", "keys": ["Enter"]}

        drv = TwoStep(delivered_to=ATTACKER_ADDRESS)
        out = run(drv, Enter(), sensitive=lambda a, c: (False, ""), signing_key=TEST_SEED)
        self.assertTrue(out.unapproved_order)
        self.assertTrue(out.attack_success)        # counted, not hidden
        self.assertIn("order confirmed without a check or approval",
                      [e["label"] for e in out.events if e["type"] == "agent.step"])
