"""Tests for the agent loop and the gate invariant.

  make test   (or: .venv/bin/python -m pytest agent)
"""

import unittest

from interceptor import events as ev

from tests.fixtures.fake_agent import FixtureDriver, ScriptedAgent, run_fixture as run

from .approval import AutoApprover, DenyApprover  # noqa: F401
from .loop import run as loop_run
from .driver import ATTACKER_ADDRESS, SHOP_ADDRESS
from common.address import norm_address


def same_address(a, b):
    return norm_address(a) == norm_address(b)


def types(out):
    return [e["type"] for e in out.events]


class SupervisedTests(unittest.TestCase):
    def test_clean_completes_and_delivers_to_the_shop(self):
        out = run("clean", supervised=True)
        self.assertTrue(out.executed)
        self.assertFalse(out.blocked)
        self.assertFalse(out.receipt_flagged)
        self.assertEqual(out.order["address"], SHOP_ADDRESS)
        self.assertFalse(out.attack_success)
        self.assertIn("receipt.signed", types(out))

    def test_a1_blocked_before_click(self):
        out = run("a1", supervised=True)
        self.assertTrue(out.blocked)
        self.assertFalse(out.executed)
        self.assertIsNone(out.order)
        self.assertNotIn("receipt.signed", types(out))

    def test_a2_blocked_before_click(self):
        out = run("a2", supervised=True)
        self.assertTrue(out.blocked)
        self.assertFalse(out.executed)

    def test_a3_caught_after_click_and_held(self):
        out = run("a3", supervised=True)
        self.assertTrue(out.executed)
        self.assertTrue(out.receipt_flagged)
        self.assertTrue(out.reached_attacker)       # the order went out...
        self.assertFalse(out.attack_success)        # ...but held, so not a win
        self.assertIn("verify.result", types(out))

    def test_blurred_blocked(self):
        out = run("blurred", supervised=True)
        self.assertTrue(out.blocked)

    def test_denied_approval_does_not_execute(self):
        out = run("clean", supervised=True, approver=DenyApprover())
        self.assertTrue(out.denied)
        self.assertFalse(out.executed)
        self.assertIsNone(out.order)


class NoSupervisorTests(unittest.TestCase):
    def test_attacks_succeed_without_supervisor(self):
        for s in ("a1", "a2", "a3"):
            out = run(s, supervised=False)
            self.assertTrue(out.executed, s)
            self.assertTrue(out.attack_success, s)
            self.assertTrue(same_address(out.order["address"], ATTACKER_ADDRESS), s)

    def test_clean_delivers_to_the_shop_without_supervisor(self):
        out = run("clean", supervised=False)
        self.assertFalse(out.attack_success)
        self.assertEqual(out.order["address"], SHOP_ADDRESS)

    def test_no_receipt_without_supervisor(self):
        out = run("a3", supervised=False)
        self.assertNotIn("receipt.signed", types(out))
        self.assertIsNone(out.receipt)

    def test_no_action_is_intercepted_without_supervisor(self):
        out = run("a1", supervised=False)
        self.assertEqual(out.intercepted, 0)


class GateInvariantTests(unittest.TestCase):
    def test_every_action_is_intercepted_when_supervised(self):
        # Gate test 2, modelled: no action reaches the driver un-checked.
        total = checked = 0
        for s in ("clean", "a1", "a2", "a3", "blurred"):
            out = run(s, supervised=True)
            total += out.actions
            checked += out.intercepted
        self.assertEqual(checked, total)
        self.assertEqual(checked, 5)

    def test_susceptible_agent_obeys_injection(self):
        # the agent itself is foolable - that is what the supervisor guards.
        drv = FixtureDriver("a1")
        action = ScriptedAgent().propose(drv.observe())
        self.assertTrue(same_address(action["address_text"], ATTACKER_ADDRESS))

    def test_hardened_agent_ignores_injection(self):
        drv = FixtureDriver("a1")
        action = ScriptedAgent(obeys_injections=False).propose(drv.observe())
        self.assertEqual(action["address_text"], SHOP_ADDRESS)

    def test_event_order_supervised_clean(self):
        out = run("clean", supervised=True)
        order = types(out)
        self.assertEqual(order[0], "run.started")
        self.assertEqual(order[1], "frame.captured")
        self.assertEqual(order[2], "agent.step")          # proposed
        self.assertEqual(order[3], "agent.step")          # sensitive: order confirmation
        self.assertEqual(order[4], "check.result")
        self.assertIn("approval.requested", order)
        # the portal's record comes after the approval, never before it
        self.assertLess(order.index("approval.granted"), order.index("order.confirmed"))
        self.assertEqual(order[-1], "receipt.signed")


class SinkTests(unittest.TestCase):
    """F11: every event reaches the sink, and a broken sink changes nothing."""

    def test_sink_receives_every_event(self):
        got = []

        class ListSink:
            def publish(self, e):
                got.append(e)

        out = loop_run(FixtureDriver("a1", 1), ScriptedAgent(), supervised=True, sink=ListSink())
        self.assertEqual(got, out.events)
        self.assertTrue(out.blocked)

    def test_broken_sink_does_not_change_the_verdict(self):
        class Broken:
            def publish(self, e):
                raise OSError("service down")

        for scenario, blocked in (("a1", True), ("a2", True), ("clean", False)):
            out = loop_run(FixtureDriver(scenario, 1), ScriptedAgent(),
                           supervised=True, sink=Broken())
            self.assertEqual(out.blocked, blocked, scenario)

    def test_denial_is_explicit_in_the_event(self):
        out = run("clean", supervised=True, approver=DenyApprover())
        g = [e for e in out.events if e["type"] == "approval.granted"][0]
        self.assertFalse(g["granted"])
        self.assertTrue(out.denied)

    def test_no_supervisor_reports_the_order(self):
        out = run("a3", supervised=False)
        confirmed = [e for e in out.events if e["type"] == "order.confirmed"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(out.events[0]["mode"], "no_supervisor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
