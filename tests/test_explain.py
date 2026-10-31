"""View 3: `agent.run --no-supervisor --explain` reads the confirming frame once,
after the run, observe only. WitnessBench never does.

Test data only: the fixture driver, the scripted agent and the fixture pixel
channel from tests/fixtures; a fake `locate` stands in for Spark + SAM. No
browser, no model, no network.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import explain
from agent import run as agent_run
from interceptor import events as ev
from interceptor.hub import validate
from tests.fixtures import captures as fx
from tests.fixtures.fake_agent import FixtureDriver, ScriptedAgent, run_fixture


class ExplainTests(unittest.TestCase):
    def locate(self, png, text):
        self.located.append(text)
        return [120, 40, 900, 70]

    def setUp(self):
        self.located = []

    def explained(self, scenario):
        out = run_fixture(scenario, supervised=False)
        before = (out.attack_success, out.order, len(out.events), out.blocked)
        channel = fx.channel_for(scenario)
        cap = explain.capture_to_explain(out)
        cap.screenshot = b"\x89PNG fake"            # the fixture has no image; locate is fake
        e = explain.explain_run(out, channel, locate=self.locate)
        self.assertEqual(before, (out.attack_success, out.order, len(out.events), out.blocked))
        self.assertIs(validate(e), e)               # the hub accepts it
        return out, e

    def test_a2_painted_line_is_located_after_the_run(self):
        out, e = self.explained("a2")
        self.assertTrue(out.attack_success)         # the run itself went through, as it happened
        self.assertEqual(e["type"], "explain.result")
        self.assertTrue(e["after_run"])
        self.assertEqual(e["status"], ev.DIVERGENCE)
        self.assertEqual(e["pixels_only_text"], [fx.INJECT])
        self.assertEqual(e["code_only_text"], [])
        self.assertEqual(e["frame"], 150)           # the frame where the agent confirmed
        boxed = [r for r in e["regions"] if r["label"] == "divergent text"]
        self.assertEqual(boxed, [{"label": "divergent text", "box": [120, 40, 900, 70],
                                  "text": fx.INJECT, "confidence": None}])
        self.assertEqual(self.located, [fx.INJECT])
        self.assertIn("address", {r["label"] for r in e["regions"]})

    def test_a1_hidden_line_has_no_box(self):
        _, e = self.explained("a1")
        self.assertEqual(e["status"], ev.DIVERGENCE)
        self.assertEqual(e["code_only_text"], [fx.INJECT])
        self.assertEqual(self.located, [])          # nothing painted to locate
        self.assertEqual(e["reason"], "page code text not visible")

    def test_clean_finds_nothing(self):
        _, e = self.explained("clean")
        self.assertEqual(e["status"], "none")

    def test_no_frame_no_event(self):
        out = run_fixture("clean", supervised=False)
        out.order_capture = out.executed_capture = out.last_capture = None
        self.assertIsNone(explain.explain_run(out, fx.channel_for("clean")))

    def test_explain_is_only_for_unsupervised_runs(self):
        with self.assertRaises(SystemExit):
            agent_run.main(["--scenario", "a2", "--explain"])

    def test_a_failing_explanation_never_breaks_the_run(self):
        out = run_fixture("a2", supervised=False)

        class Broken:
            def read_regions(self, capture):
                raise RuntimeError("API down")
        published = []
        sink = mock.Mock(publish=published.append)
        tmp = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(agent_run.explain_after(out, Broken(), sink, tmp))
            self.assertEqual(published, [])
            self.assertFalse((tmp / "explain.json").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class FakeMeta:
    def spent_usd(self):
        return 0.0

    def model(self, name):
        return "fake-" + name

    def segment(self, png, prompt):
        return [], 0


class Agent(ScriptedAgent):
    tool = "wonder"
    raw = []


class Pixels:
    """The fixture channel, plus the two calls the real one has."""

    def __init__(self, scenario):
        self.channel = fx.channel_for(scenario)
        self.calls = 0

    def read_regions(self, capture):
        self.calls += 1
        return self.channel.read_regions(capture)

    def read_label(self, png):
        return ""

    def locate_text(self, png, text):
        return [120, 40, 900, 70]


class RunMainTests(unittest.TestCase):
    """agent.run end to end with test doubles: --explain adds one event and
    explain.json, and leaves outcome.json exactly as without it."""

    def main(self, *flags):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        published, pixels = [], Pixels("a2")

        @contextlib.contextmanager
        def portal(scenario, variant, **kw):
            d = FixtureDriver(scenario, variant)
            d.observe().screenshot = b"\x89PNG fake"
            yield d

        with mock.patch.dict(os.environ, {"RUNS_DIR": str(tmp)}), \
                mock.patch.object(agent_run, "portal_up", lambda url: True), \
                mock.patch.object(agent_run, "service_up", lambda: False), \
                mock.patch.object(agent_run, "open_portal", portal), \
                mock.patch.object(agent_run.meta_client, "MetaClient", FakeMeta), \
                mock.patch.object(agent_run, "WonderAgent", lambda meta, tool="wonder": Agent()), \
                mock.patch.object(agent_run, "SamSparkChannel", lambda meta: pixels), \
                mock.patch.object(agent_run, "default_sink",
                                  lambda: mock.Mock(publish=published.append)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(agent_run.main(["--scenario", "a2", "--no-supervisor", *flags]), 0)
        run_dir = next(tmp.rglob("outcome.json")).parent
        outcome = json.loads((run_dir / "outcome.json").read_text())
        outcome.pop("run")
        return outcome, published, pixels, run_dir

    def test_explain_is_observe_only(self):
        plain, ev_plain, px_plain, dir_plain = self.main()
        explained, ev_explained, px_explained, dir_explained = self.main("--explain")
        self.assertEqual(plain, explained)                       # the run's outcome is unchanged
        self.assertTrue(explained["attack_success"])
        self.assertEqual(px_plain.calls, 0)                      # no pixel read without the flag
        self.assertEqual(px_explained.calls, 1)                  # exactly one, after the run
        self.assertEqual([e["type"] for e in ev_explained][:-1], [e["type"] for e in ev_plain])
        last = ev_explained[-1]
        self.assertEqual(last["type"], "explain.result")
        self.assertEqual(last["status"], ev.DIVERGENCE)
        self.assertFalse((dir_plain / "explain.json").exists())
        saved = json.loads((dir_explained / "explain.json").read_text())
        self.assertEqual(saved["event"], last)
        lines = (dir_explained / "events.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(lines[-1])["type"], "explain.result")


class BenchNeverExplains(unittest.TestCase):
    def test_bench_has_no_explain_flag_and_never_calls_it(self):
        from bench import run as bench_run
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench_run.main(["--explain", "--dry-run"])
        self.assertNotIn("explain", Path(bench_run.__file__).read_text())

    def test_bench_run_does_not_explain(self):
        from bench import run as bench_run
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        pixels = Pixels("a2")
        pixels.errors = []

        @contextlib.contextmanager
        def portal(scenario, variant, **kw):
            yield FixtureDriver(scenario, variant)

        with mock.patch.object(bench_run, "open_portal", portal), \
                mock.patch.object(bench_run, "WonderAgent", lambda meta: Agent()), \
                mock.patch.object(bench_run, "SamSparkChannel", lambda meta: pixels), \
                mock.patch.object(explain, "explain_run", side_effect=AssertionError("explained")) as ex:
            row = bench_run.one_run(FakeMeta(), "a2", 1, "no_supervisor", tmp, 5)
        ex.assert_not_called()
        self.assertEqual(pixels.calls, 0)
        self.assertTrue(row["delivered_to_attacker"])
        events = (tmp / "a2_v1_no_supervisor" / "events.jsonl").read_text()
        self.assertNotIn("explain.result", events)


if __name__ == "__main__":
    unittest.main()
