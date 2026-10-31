"""Start the portal and the interceptor together. Ctrl+C stops both."""

import subprocess
import sys
import time

from common import config


def main():
    s = config.settings()
    procs = [
        ("portal", [sys.executable, "-m", "portal.server",
                    "--host", s.portal_host, "--port", str(s.portal_port)]),
        ("interceptor", [sys.executable, "-m", "uvicorn", "interceptor.service:app",
                         "--host", s.interceptor_host, "--port", str(s.interceptor_port),
                         "--log-level", "warning"]),
    ]
    running = []
    try:
        for name, cmd in procs:
            running.append((name, subprocess.Popen(cmd, cwd=config.ROOT)))
        print("portal       %s/orders/new?scenario=clean" % s.portal_url)
        print("interface    http://localhost:%d/   (status: /status)" % s.interceptor_port)
        print("simulation only - simulated shop, supplier and addresses. Ctrl+C to stop.", flush=True)
        while True:
            for name, p in running:
                if p.poll() is not None:
                    print("%s exited with code %s - stopping" % (name, p.returncode))
                    return p.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopping")
        return 0
    finally:
        for _, p in running:
            if p.poll() is None:
                p.terminate()
        for _, p in running:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
