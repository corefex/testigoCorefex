"""F3 §3b: the multi-step loop, Wonder's action format and the sensitive-click rule.

Offline: a scripted sequence of actions and a fake browser, never the API.
"""

import json
import unittest
from types import SimpleNamespace as NS

from agent.agent import Agent, WonderAgent, parse_action
from agent.driver import BrowserDriver, SUPPLIER_ACCT, _key
from agent.loop import MAX_STEPS, run
from interceptor.channels import Capture
from interceptor.sensitive import SamButtons
from tests.fixtures import captures as fx

PAY_BOX = [754, 700, 923, 747]


class StepDriver(BrowserDriver):
    """A page that pays when the pay button area is clicked."""
    is_test_double = True
    scenario, variant = "clean", 1

    def __init__(self):
        self.frame = 0
        self.ran = []
        self._payment = None

    def observe(self):
        self.frame += 1
        return fx.capture_clean()      # the fixture channel has regions for this frame

    def pixel_channel(self):
        return fx.channel_for("clean")

    def execute(self, action):
        self.ran.append(action["kind"])
        if action["kind"] == "click" and 754 <= action["x"] <= 923 and 700 <= action["y"] <= 747:
            self._payment = {"recipient": SUPPLIER_ACCT, "amount_cop": 120000}

    def observe_after(self):
        return self.observe()

    @property
    def last_payment(self):
        return self._payment


class Script(Agent):
    is_test_double = True

    def __init__(self, actions):
        self.actions = list(actions)
        self.results = []

    def propose(self, observation):
        return self.actions.pop(0) if self.actions else {"kind": "wait"}

    def result(self, action, outcome):
        self.results.append(outcome)


def sam(boxes_by_phrase):
    return lambda png, phrase: (boxes_by_phrase.get(phrase, []), 1)


def kinds(out):
    return [e["type"] for e in out.events]


class LoopTests(unittest.TestCase):
    def test_several_steps_until_payment(self):
        drv = StepDriver()
        agent = Script([{"kind": "click", "x": 100, "y": 330}, {"kind": "type", "text": "x"},
                        {"kind": "click", "x": 838, "y": 722}])
        out = run(drv, agent, supervised=False)
        self.assertEqual(drv.ran, ["click", "type", "click"])
        self.assertEqual(out.actions, 3)
        self.assertEqual(out.payment["recipient"], SUPPLIER_ACCT)
        self.assertEqual(agent.results, ["executed"] * 3)

    def test_done_ends_the_run_without_executing(self):
        drv = StepDriver()
        out = run(drv, Script([{"kind": "done", "rationale": "nothing to pay"}]), supervised=False)
        self.assertTrue(out.finished)
        self.assertEqual(drv.ran, [])

    def test_max_steps_stops_and_reports(self):
        drv = StepDriver()
        out = run(drv, Script([]), supervised=False, max_steps=4)
        self.assertTrue(out.max_steps)
        self.assertEqual(len(drv.ran), 4)
        self.assertIn("stopped: max_steps (4)", out.events[-1]["label"])
        self.assertEqual(MAX_STEPS, 15)

    def test_invalid_action_is_never_executed(self):
        drv = StepDriver()
        agent = Script([{"kind": "invalid", "detail": "click(x=9999)"}, {"kind": "done"}])
        out = run(drv, agent, supervised=False)
        self.assertEqual(drv.ran, [])
        self.assertTrue(agent.results[0].startswith("not executed"))

    def test_supervised_every_action_passes_the_hook(self):
        drv = StepDriver()
        agent = Script([{"kind": "click", "x": 100, "y": 330}, {"kind": "scroll", "x": 1, "y": 1, "dy": 5},
                        {"kind": "click", "x": 838, "y": 722}])
        out = run(drv, agent, supervised=True, sensitive=SamButtons(sam({"pay button": [{"box": PAY_BOX}]})))
        self.assertEqual(out.intercepted, out.actions)
        self.assertEqual(out.checked, 1)                 # only the pay click
        self.assertIn("check.result", kinds(out))
        self.assertTrue(out.payment)

    def test_supervised_block_stops_before_the_browser(self):
        drv = StepDriver()
        drv.pixel_channel = lambda: fx.channel_for("blurred")      # cannot_verify
        agent = Script([{"kind": "click", "x": 838, "y": 722}])
        out = run(drv, agent, supervised=True, sensitive=SamButtons(sam({"pay button": [{"box": PAY_BOX}]})))
        self.assertTrue(out.blocked)
        self.assertEqual(drv.ran, [])


class SensitiveTests(unittest.TestCase):
    cap = Capture(1, [], [], {}, screenshot=b"png")

    def test_click_inside_pay_box_is_sensitive(self):
        ok, why = SamButtons(sam({"pay button": [{"box": PAY_BOX}]}))({"kind": "click", "x": 838, "y": 722}, self.cap)
        self.assertEqual((ok, why), (True, "click on pay button"))

    def test_click_elsewhere_and_typing_are_not(self):
        cls = SamButtons(sam({"pay button": [{"box": PAY_BOX}]}))
        self.assertFalse(cls({"kind": "click", "x": 100, "y": 330}, self.cap)[0])
        self.assertFalse(cls({"kind": "type", "text": "hola"}, self.cap)[0])

    def test_sam_failure_counts_as_sensitive(self):
        def broken(png, phrase):
            raise RuntimeError("down")
        self.assertTrue(SamButtons(broken)({"kind": "click", "x": 1, "y": 1}, self.cap)[0])


def fn_call(name, args, call_id="c1"):
    return NS(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id)


def said(text):
    return NS(type="message", content=[NS(type="output_text", text=text)])


class ParseActionTests(unittest.TestCase):
    def test_click_in_pixels(self):
        [a] = parse_action(NS(output=[said("Paying."), fn_call("click", {"x": 838, "y": 722})]))
        self.assertEqual((a["kind"], a["x"], a["y"], a["rationale"], a["call_id"]),
                         ("click", 838, 722, "Paying.", "c1"))

    def test_out_of_screen_is_invalid(self):
        # Wonder answers in 0-1000 if the tool does not say pixels (g1 probe)
        [a] = parse_action(NS(output=[fn_call("click", {"x": 655, "y": 894})]))
        self.assertEqual(a["kind"], "invalid")

    def test_other_tools(self):
        out = parse_action(NS(output=[fn_call("type_text", {"text": "310"}, "a"),
                                      fn_call("keypress", {"keys": ["Control+A"]}, "b"),
                                      fn_call("scroll", {"x": 5, "y": 5, "dy": 300}, "c"),
                                      fn_call("done", {"summary": "paid"}, "d")]))
        self.assertEqual([a["kind"] for a in out], ["type", "keypress", "scroll", "done"])

    def test_no_tool_call_is_done(self):
        [a] = parse_action(NS(output=[said("I will not pay to that account.")]))
        self.assertEqual((a["kind"], a["rationale"]), ("done", "I will not pay to that account."))

    def test_bad_arguments_are_invalid(self):
        bad = NS(type="function_call", name="click", arguments="{not json", call_id="z")
        self.assertEqual(parse_action(NS(output=[bad]))[0]["kind"], "invalid")
        self.assertEqual(parse_action(NS(output=[fn_call("rm", {})]))[0]["kind"], "invalid")


class FakeMeta:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def respond(self, tool, items, **kw):
        self.calls.append((tool, items, kw))
        return self.responses.pop(0), 1


class WonderAgentTests(unittest.TestCase):
    def test_answers_each_call_and_chains_the_conversation(self):
        meta = FakeMeta([NS(id="r1", output=[fn_call("click", {"x": 1, "y": 2}, "c1"),
                                             fn_call("click", {"x": 3, "y": 4}, "c2")]),
                         NS(id="r2", output=[fn_call("done", {"summary": "ok"}, "c3")])])
        agent = WonderAgent(meta)
        cap = Capture(1, [], [], {}, screenshot=b"\x89PNG")
        first = agent.propose(cap)
        self.assertEqual((first["x"], first["y"]), (1, 2))
        agent.result(first, "executed")
        agent.propose(cap)
        _, items, kw = meta.calls[1]
        self.assertEqual(kw["previous_response_id"], "r1")
        outputs = [(i["call_id"], i["output"]) for i in items if i.get("type") == "function_call_output"]
        self.assertEqual(outputs, [("c1", "executed"), ("c2", "not executed: one action per turn")])
        self.assertEqual(meta.calls[0][0], "wonder")
        self.assertIn("1280 pixels wide", meta.calls[0][2]["instructions"])


class KeyTests(unittest.TestCase):
    def test_key_names(self):
        self.assertEqual(_key("ctrl+a"), "Control+A")
        self.assertEqual(_key("Enter"), "Enter")
        self.assertEqual(_key("return"), "Enter")


if __name__ == "__main__":
    unittest.main()
