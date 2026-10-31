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

import os
import threading
import time
from unittest import mock

from interceptor import service

REAL_START = service.start_process      # before any test replaces it


class FakeProc:
    """Stands in for `python -m agent.run`. Never starts anything. `stubborn`
    ignores terminate (only kill stops it); `pid` makes it leave a pid file."""

    def __init__(self, lines=("approval: interface\n",), stubborn=False, pid=None):
        self.stdout = iter(lines)
        self.returncode = None
        self.done = threading.Event()
        self.terminated = False
        self.killed = False
        self.stubborn = stubborn
        if pid is not None:
            self.pid = pid

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
        if not self.stubborn:
            self.exit(-15)

    def kill(self):
        self.killed = True
        self.exit(-9)


class RunEndpointTests(unittest.TestCase):
    def setUp(self):
        import os
        import shutil
        import tempfile
        from approval.desk import ApprovalDesk
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"RUNS_DIR": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        service.runs = service.RunManager()
        desk = mock.patch.object(service, "desk", ApprovalDesk())
        desk.start()
        self.addCleanup(desk.stop)
        self.started = []
        self.procs = []
        self.next_proc = FakeProc

        def fake(argv, env):
            self.started.append((argv, env))
            p = self.next_proc()
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

    def test_the_portal_tab_and_rebinding_cannot_start_or_stop_a_run(self):
        ok = {"scenario": "a1", "supervised": True}
        portal = {"Host": "localhost:8090", "Origin": "http://localhost:8080"}
        self.assertEqual(self.c.post("/api/run", json=ok, headers=portal).status_code, 403)
        self.assertEqual(self.started, [])
        self.assertEqual(self.c.post("/api/run", json=ok, headers={"Host": "localhost:8090"}).status_code, 200)
        self.assertEqual(self.c.post("/api/run/cancel", json={}, headers=portal).status_code, 403)
        self.assertEqual(self.c.post("/api/run/cancel", json={}, headers={"Host": "rebind.example"}).status_code, 403)
        self.assertEqual(self.c.get("/api/run").json()["state"], "running")
        self.assertFalse(self.procs[0].terminated)

    def test_kill_after_timeout_keeps_the_exit_code(self):
        self.next_proc = lambda: FakeProc(stubborn=True)
        self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
        with mock.patch.object(service, "RUN_STOP_TIMEOUT_S", 0.1):
            got = self.c.post("/api/run/cancel", json={}).json()
        self.assertTrue(self.procs[0].terminated and self.procs[0].killed)
        self.assertEqual((got["state"], got["exit_code"]), ("cancelled", -9))
        time.sleep(0.1)                                # the watcher thread finishing too
        self.assertEqual(self.c.get("/api/run").json()["exit_code"], -9)

    def test_an_old_run_ending_never_touches_the_newer_one(self):
        self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
        old = self.procs[0]
        service.runs.proc = FakeProc()                 # as if a newer run had started meanwhile
        service.runs.info = dict(service.runs.info, state="running", exit_code=None)
        old.exit(3)
        time.sleep(0.1)
        got = self.c.get("/api/run").json()
        self.assertEqual((got["state"], got["exit_code"]), ("running", None))
        service.runs.proc.exit(0)

    def test_cancel_during_an_approval_denies_it(self):
        from interceptor import events as ev
        a = ev.approval_requested(5, 120000, "Tienda Doña Marta · Calle 45 # 12-30, Bogotá", "a" * 64, "b" * 64)
        self.c.post("/api/run", json={"scenario": "clean", "supervised": True})
        self.c.post("/api/approval/open", json={"event": a})
        self.assertIsNone(service.desk.current()["decision"])
        self.c.post("/api/run/cancel", json={})
        cur = service.desk.current()
        self.assertEqual((cur["decision"], cur["reason"]), ("deny", "run cancelled"))

    def test_a_restarted_service_sees_the_orphan_refuses_a_second_run_and_stops_it(self):
        from pathlib import Path
        import signal
        self.next_proc = lambda: FakeProc(pid=424242)
        alive = {"v": True}
        killed = []
        patches = [mock.patch.object(service, "run_leader_alive", lambda pid: alive["v"]),
                   mock.patch.object(service, "pid_alive", lambda pid: alive["v"]),
                   mock.patch.object(service, "kill_group",
                                     lambda pid, sig: (killed.append((pid, sig)), alive.update(v=False)))]
        for x in patches:
            x.start()
            self.addCleanup(x.stop)
        self.c.post("/api/run", json={"scenario": "a2", "variant": 3, "supervised": True})
        pid_file = Path(self.tmp) / service.RUN_PID_FILE
        self.assertTrue(pid_file.is_file())
        service.runs = service.RunManager()            # the service restarted; the child did not
        got = self.c.get("/api/run").json()
        self.assertEqual((got["state"], got["pid"], got["scenario"], got["variant"]), ("orphaned", 424242, "a2", 3))
        self.assertEqual(self.c.post("/api/run", json={"scenario": "a1", "supervised": True}).status_code, 409)
        self.assertEqual(len(self.started), 1)
        self.assertTrue(self.c.post("/api/run/cancel", json={}).json()["cancelled"])
        self.assertEqual(killed, [(424242, signal.SIGTERM)])
        self.assertFalse(pid_file.exists())
        self.assertEqual(self.c.get("/api/run").json(), {"state": "idle"})
        self.assertEqual(self.c.post("/api/run", json={"scenario": "a1", "supervised": True}).status_code, 200)

    def test_a_stale_pid_file_is_ignored(self):
        from pathlib import Path
        (Path(self.tmp) / service.RUN_PID_FILE).write_text('{"pid": 999999999, "scenario": "a1"}')
        self.assertEqual(self.c.get("/api/run").json(), {"state": "idle"})
        self.assertFalse((Path(self.tmp) / service.RUN_PID_FILE).exists())

    def test_shutdown_and_orphan_stop_kill_the_whole_process_group(self):
        """A real child here is a harmless `sleep`, never agent.run."""
        import subprocess
        import sys
        real = REAL_START
        sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
        with mock.patch.object(service, "start_process", lambda argv, env: real(sleeper, env)):
            self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
            proc = service.runs.proc
            self.assertIsInstance(proc, subprocess.Popen)
            self.assertEqual(os.getpgid(proc.pid), proc.pid)       # its own process group
            service.runs = service.RunManager()                     # restart: an orphan now
            self.assertEqual(self.c.get("/api/run").json()["state"], "orphaned")
            self.c.post("/api/run/cancel", json={})
            proc.wait(timeout=5)
            self.assertIsNotNone(proc.returncode)
            # and a clean shutdown stops the run it owns
            self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
            proc = service.runs.proc
            service.runs.shutdown()
            self.assertIsNotNone(proc.wait(timeout=5))
            self.assertEqual(self.c.get("/api/run").json()["state"], "cancelled")

    def test_service_shutdown_stops_the_run(self):
        with TestClient(app) as c:                     # runs the lifespan: startup, then shutdown
            c.post("/api/run", json={"scenario": "a1", "supervised": True})
        self.assertTrue(self.procs[0].terminated)
        self.assertEqual(service.runs.view()["state"], "cancelled")

    def test_printed_lines_are_redacted(self):
        secret = "mk-live-0123456789abcdef"
        hexkey = "ab" * 32
        self.next_proc = lambda: FakeProc(lines=(
            "Authorization: Bearer eyJhbGciOi.payload.sig\n", "key sk-abcdefghijklmnop12\n",
            "META_API_KEY=%s\n" % secret, "seed %s\n" % hexkey, "api_key: 'hunter22hunter'\n",
            "plain line stays\n"))
        with mock.patch.dict(os.environ, {"META_API_KEY": secret}):
            self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
            self.procs[0].exit(1)
            self.wait_state("failed")
        tail = "\n".join(self.c.get("/api/run").json()["tail"])
        for leak in (secret, "eyJhbGciOi", "sk-abcdefghijklmnop12", hexkey, "hunter22hunter"):
            self.assertNotIn(leak, tail)
        self.assertIn("plain line stays", tail)
        self.assertIn("[redacted]", tail)

    def test_the_child_gets_only_the_env_it_needs(self):
        with mock.patch.dict(os.environ, {"META_API_KEY": "k-123456", "AWS_SECRET_ACCESS_KEY": "nope",
                                          "SOME_OTHER_TOKEN": "nope"}):
            self.c.post("/api/run", json={"scenario": "a1", "supervised": True})
        env = self.started[0][1]
        self.assertEqual(env["META_API_KEY"], "k-123456")
        self.assertIn("PATH", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("SOME_OTHER_TOKEN", env)


if __name__ == "__main__":
    unittest.main()
