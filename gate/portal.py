"""The portal the gate scripts drive (g3, g4, g5).

`portal()` uses the portal already listening on PORTAL_PORT, or starts one in
this process (like agent.run). A portal from another checkout or an older
version may be listening there: `probe()` checks that it answers `/api/run`
with this .env's SCORER_TOKEN, and the scripts stop with a hint when it does
not (stop it, or set PORTAL_PORT to a free port).
"""

import json
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager

from agent.run import portal_up, start_portal
from common import config


def probe(url):
    """None when the portal answers /api/run as this repo's portal does, else why not."""
    token = config.settings().scorer_token
    if not token:
        return "SCORER_TOKEN is empty: run `make setup`"
    req = urllib.request.Request(url + "/api/run", headers={"Authorization": "Bearer " + token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as r:
            json.loads(r.read().decode("utf-8"))
            return None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 404 and "no such session" in body:
            return None                # this portal: no cookie, no session
        if e.code == 401:
            return "the portal on %s rejects this SCORER_TOKEN" % url
        return "the portal on %s does not answer /api/run (HTTP %d)" % (url, e.code)
    except (OSError, ValueError) as e:
        return "the portal on %s does not answer /api/run (%s)" % (url, e)


class PortalError(RuntimeError):
    pass


def failed(gate_id, err, threshold):
    """The contract's result line when the portal is not usable (no model was called)."""
    from gate.report import report
    return report(gate_id, False, "not run: %s" % err, threshold, 0, {"error": str(err), "hint": HINT})


HINT = ("a stale portal (another session or checkout?) is listening on PORTAL_PORT; stop it, "
        "or run with another port, e.g. PORTAL_PORT=8181 .venv/bin/python -m gate.<name>")


@contextmanager
def portal():
    url = config.settings().portal_url
    httpd = None if portal_up(url) else start_portal()
    try:
        why = probe(url)
        if why:
            print("gate: %s\ngate: hint: %s" % (why, HINT), file=sys.stderr)
            raise PortalError(why)
        yield url
    finally:
        if httpd:
            httpd.shutdown()
