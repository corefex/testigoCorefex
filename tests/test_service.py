"""F0 §14.1: the interceptor service answers with its status page (now at /status;
/ is the F11 interface)."""

import unittest

from fastapi.testclient import TestClient

from interceptor.service import app


class ServiceTests(unittest.TestCase):
    def test_status_page_and_health(self):
        c = TestClient(app)
        r = c.get("/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("TESTIGO+ interceptor", r.text)
        h = c.get("/health").json()
        self.assertEqual(h["service"], "interceptor")
        self.assertTrue(h["policy_hash_ok"])
        # reports whether variables are set, never their values
        self.assertTrue(all(isinstance(v, bool) for v in h["models_configured"].values()))


# -- POST /api/run: start a run from the interface (the process is always a fake) --

import threading
import time
from unittest import mock

from interceptor import service


class FakeProc:
    """Stands in for `python -m agent.run`. Never starts anything."""

    def __init__(self, lines=("approval: interface\n",)):
        self.stdout = iter(lines)
        self.returncode = None
        self.done = threading.Event()
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.done.wait(timeout if timeout is not None else 10):
            import subprocess
            raise subprocess.TimeoutExpired("agent.run", timeout)
        return self.returncode

    def exit(self, code):
        self.returncode = code
        self.done.set()

    def terminate(self):
        self.terminated = True
        self.exit(-15)

    def kill(self):
        self.exit(-9)


class RunEndpointTests(unittest.TestCase):
    def setUp(self):
        service.runs = service.RunManager()
        self.started = []
        self.procs = []

        def fake(argv, env):
            self.started.append((argv, env))
            p = FakeProc()
            self.procs.append(p)
            return p
        patch = mock.patch.object(service, "start_process", fake)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(lambda: [p.exit(0) for p in self.procs if p.returncode is None])
        self.c = TestClient(app)

    def wait_state(self, state):
        for _ in range(100):
            if self.c.get("/api/run").json()["state"] == state:
                return
            time.sleep(0.02)
        self.fail("run never reached %s" % state)

    def test_idle_then_supervised_run_with_exact_argv(self):
        self.assertEqual(self.c.get("/api/run").json(), {"state": "idle"})
        r = self.c.post("/api/run", json={"scenario": "a3", "supervised": True},
                        headers={"Host": "127.0.0.1:9123"})
        self.assertEqual(r.status_code, 200, r.text)
        got = r.json()
        self.assertEqual((got["state"], got["mode"], got["scenario"], got["variant"]),
                         ("running", "supervised", "a3", 1))
        argv, env = self.started[0]
        self.assertEqual(argv[1:], ["-m", "agent.run", "--scenario", "a3", "--variant", "1",
                                    "--approve-in", "interface"])
        self.assertIsInstance(argv, list)            # an argv list: never a shell string
        self.assertEqual(env["INTERCEPTOR_PORT"], "9123")  # reports back to this service
        self.procs[0].exit(0)
        self.wait_state("finished")
        self.assertEqual(self.c.get("/api/run").json()["tail"], ["approval: interface"])

    def test_unsupervised_run_explains_and_headed_is_optional(self):
        self.c.post("/api/run", json={"scenario": "a1", "variant": 5, "supervised": False, "headed": True})
        argv = self.started[0][0]
        self.assertEqual(argv[3:], ["--scenario", "a1", "--variant", "5", "--approve-in", "interface",
                                    "--no-supervisor", "--explain", "--headed"])
        self.procs[0].exit(0)
        self.wait_state("finished")
        self.c.post("/api/run", json={"scenario": "a1", "supervised": False, "explain": False})
        self.assertNotIn("--explain", self.started[1][0])

    def test_one_run_at_a_time_and_failure_is_reported(self):
        self.assertEqual(self.c.post("/api/run", json={"scenario": "clean", "supervised": True}).status_code, 200)
        busy = self.c.post("/api/run", json={"scenario": "a2", "supervised": False})
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(len(self.started), 1)
        self.procs[0].exit(1)
        self.wait_state("failed")
        self.assertEqual(self.c.get("/api/run").json()["exit_code"], 1)
        self.assertEqual(self.c.post("/api/run", json={"scenario": "a2", "supervised": False}).status_code, 200)

    def test_cancel(self):
        self.assertFalse(self.c.post("/api/run/cancel", json={}).json()["cancelled"])
        self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
        got = self.c.post("/api/run/cancel", json={}).json()
        self.assertTrue(got["cancelled"])
        self.assertEqual(got["state"], "cancelled")
        self.assertTrue(self.procs[0].terminated)
        self.assertEqual(self.c.get("/api/run").json()["state"], "cancelled")

    def test_inputs_are_validated_strictly(self):
        bad = [{"supervised": True},
               {"scenario": "a1edge", "supervised": True},
               {"scenario": "a1; rm -rf /", "supervised": True},
               {"scenario": ["a1"], "supervised": True},
               {"scenario": "a1"},
               {"scenario": "a1", "supervised": "yes"},
               {"scenario": "a1", "supervised": True, "variant": 0},
               {"scenario": "a1", "supervised": True, "variant": 6},
               {"scenario": "a1", "supervised": True, "variant": "2"},
               {"scenario": "a1", "supervised": True, "variant": True},
               {"scenario": "a1", "supervised": True, "variant": 2.5},
               {"scenario": "a1", "supervised": True, "explain": True},
               {"scenario": "a1", "supervised": True, "max_steps": 99},
               {"scenario": "a1", "supervised": True, "headed": 1}]
        for body in bad:
            self.assertEqual(self.c.post("/api/run", json=body).status_code, 422, body)
        self.assertEqual(self.c.post("/api/run", json=["a1"]).status_code, 422)
        self.assertEqual(self.started, [])

    def test_same_protections_as_the_other_writes(self):
        ok = {"scenario": "a1", "supervised": True}
        self.assertEqual(self.c.post("/api/run", json=ok, headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.c.post("/api/run", json=ok, headers={"Origin": "http://localhost:8080"}).status_code, 403)
        self.assertEqual(self.c.post("/api/run", json=ok, headers={"Host": "rebind.example"}).status_code, 403)
        self.assertEqual(self.c.post("/api/run", content=b'{"scenario":"a1","supervised":true}',
                                     headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.c.post("/api/run/cancel", content=b"{}",
                                     headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.c.get("/api/run", headers={"Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.started, [])
        same = self.c.post("/api/run", json=ok, headers={"Origin": "http://testserver"})
        self.assertEqual(same.status_code, 200)


if __name__ == "__main__":
    unittest.main()
