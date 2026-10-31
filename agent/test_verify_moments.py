"""F8: the two moments after approval, on a two-step flow (offline doubles).

Order page (approve) -> review screen (re-read before confirming: a mismatch
blocks) -> result (re-read after the click: a mismatch flags the receipt).
Compared by the values read from the pixels, never by the DOM.
"""

import unittest

from agent.agent import Agent
from agent.driver import BrowserDriver, SUPPLIER_ACCT, ATTACKER_ACCT
from agent.loop import run
from interceptor.channels import Capture, FixtureChannel
from tests.fixtures import captures as fx

ORDER, REVIEW, RESULT = 150, 151, 152
TEST_SEED = bytes(range(32))     # a throwaway test key, never the owner's


class TwoStep(BrowserDriver):
    """Order page, review screen, result. `review_to` / `paid_to`: the
    recipient the review screen shows and the one the portal pays."""
    is_test_double = True
    scenario, variant = "clean", 1

    def __init__(self, review_to="Distribuidora X · 310-XXX-4417", paid_to=SUPPLIER_ACCT):
        self.review_to, self.paid_to = review_to, paid_to
        self.page = ORDER
        self.ran = []
        self._payment = None
        self.ch = FixtureChannel()
        self.ch.set_regions(ORDER, fx._regions())
        self.ch.set_regions(REVIEW, fx._regions(recipient=review_to))
        self.ch.set_regions(RESULT, fx._regions(recipient=paid_to))

    def _cap(self, frame, tag):
        return Capture(frame, list(fx._BASE_LINES), list(fx._BASE_LINES), fx._crops(tag))

    def observe(self):
        return self._cap(self.page, "%s-%d" % (self.review_to, self.page))

    def observe_after(self):
        return self._cap(RESULT, self.paid_to)

    def pixel_channel(self):
        return self.ch

    def execute(self, action):
        self.ran.append(self.page)
        if self.page == ORDER:
            self.page = REVIEW
        elif self.page == REVIEW:
            self._payment = {"recipient": self.paid_to, "amount_cop": 120000}

    @property
    def last_payment(self):
        return self._payment


class Pay(Agent):
    """Clicks pay, then confirm: both sensitive."""
    is_test_double = True

    def propose(self, observation):
        return {"kind": "pay"}


def verifies(out):
    return [(e["moment"], e["status"]) for e in out.events if e["type"] == "verify.result"]


class MomentsTests(unittest.TestCase):
    def test_review_matches_and_result_matches(self):
        drv = TwoStep()
        out = run(drv, Pay(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "match"), ("result", "match")])
        self.assertFalse(out.blocked or out.receipt_flagged)
        self.assertEqual(out.payment["recipient"], SUPPLIER_ACCT)
        self.assertEqual(out.receipt["comparison"]["status"], "match")
        self.assertEqual(out.receipt["comparison"]["by"], "read")

    def test_recipient_changed_on_review_blocks_before_confirm(self):
        drv = TwoStep(review_to="Distribuidora X · " + ATTACKER_ACCT, paid_to=ATTACKER_ACCT)
        out = run(drv, Pay(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "mismatch")])
        self.assertTrue(out.blocked)
        self.assertEqual(out.blocked_at, "review")
        self.assertIsNone(out.payment)
        self.assertEqual(drv.ran, [ORDER])           # the confirm click never ran
        vr = [e for e in out.events if e["type"] == "verify.result"][0]
        self.assertIn(ATTACKER_ACCT, vr["read"]["executed"]["recipient"])

    def test_changed_after_the_click_flags_the_receipt(self):
        drv = TwoStep(paid_to=ATTACKER_ACCT)          # review looked right, result did not
        out = run(drv, Pay(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out), [("review", "match"), ("result", "mismatch")])
        self.assertTrue(out.receipt_flagged)
        self.assertFalse(out.attack_success)
        self.assertEqual(out.receipt["comparison"]["status"], "mismatch")

    def test_formatting_differences_are_not_a_mismatch(self):
        # the review screen shows the account in another layout and case
        drv = TwoStep(review_to="PAY TO (NEQUI ACCOUNT) 310-xxx-4417 Distribuidora X")
        out = run(drv, Pay(), signing_key=TEST_SEED)
        self.assertEqual(verifies(out)[0], ("review", "match"))


if __name__ == "__main__":
    unittest.main()
