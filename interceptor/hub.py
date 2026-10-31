"""The event hub inside the interceptor service (F11).

The supervised loop runs in its own process and posts each event to the
service; the hub keeps the current run's events and fans them out to every
open interface page over WebSocket. A page that connects late gets the history
first, so a recording can start at any time.

The hub only relays. It does not decide anything, and the interface keeps no
state of its own (F11-D4): what a page shows is a function of these events.
"""

import asyncio
import json
import threading
from collections import deque

from . import events as ev

MAX_EVENTS = 500          # one run is a few dozen events; this is a safety cap
MAX_EVENT_BYTES = 64_000  # an event is a small JSON object, never a screenshot
PAGE_QUEUE = 1000         # a stalled page drops events instead of growing memory

MODES = ("supervised", "no_supervisor")

# Fields each event must carry, with their JSON type, so one malformed event
# cannot break a view (history is replayed on every page load).
_STR, _NUM, _LIST, _DICT, _BOOL = str, (int, float), list, dict, bool
REQUIRED = {
    "run.started": {"mode": _STR},
    "agent.step": {"label": _STR},
    "frame.captured": {"sha256": _STR},
    "check.result": {"status": _STR, "regions": _LIST, "code_only_text": _LIST,
                     "pixels_only_text": _LIST, "latency_ms": _NUM},
    "approval.requested": {"amount_cop": _NUM, "address": _STR, "crops": _DICT},
    "approval.granted": {"voice_match": _BOOL},
    "verify.result": {"status": _STR, "approved": _DICT, "executed": _DICT},
    "receipt.signed": {"id": _STR, "signature": _STR},
    "order.confirmed": {"address": _STR, "amount_cop": _NUM},
    "explain.result": {"status": _STR, "regions": _LIST, "code_only_text": _LIST,
                       "pixels_only_text": _LIST, "latency_ms": _NUM},
}


class InvalidEvent(ValueError):
    pass


def validate(e):
    """Accept only the event shapes in interceptor/events.py."""
    if not isinstance(e, dict):
        raise InvalidEvent("event must be a JSON object")
    if e.get("type") not in ev.TYPES:
        raise InvalidEvent("unknown event type: %r" % (e.get("type"),))
    if len(json.dumps(e, ensure_ascii=False)) > MAX_EVENT_BYTES:
        raise InvalidEvent("event too large")
    for field, kind in REQUIRED[e["type"]].items():
        v = e.get(field)
        if not isinstance(v, kind) or (kind is _NUM and isinstance(v, bool)):
            raise InvalidEvent("%s.%s missing or wrong type" % (e["type"], field))
    if e["type"] == "run.started" and e["mode"] not in MODES:
        raise InvalidEvent("run.started.mode must be one of %s" % (MODES,))
    if e["type"] in ("check.result", "explain.result"):
        for g in e["regions"]:
            box = g.get("box") if isinstance(g, dict) else None
            if not (isinstance(box, list) and len(box) == 4
                    and all(isinstance(x, (int, float)) for x in box)):
                raise InvalidEvent("%s region needs box [x0,y0,x1,y1]" % e["type"])
    return e


def _offer(queue, e):
    try:
        queue.put_nowait(e)
    except asyncio.QueueFull:
        pass   # the page is not reading; it gets the full history on reconnect


class EventHub:
    def __init__(self, maxlen=MAX_EVENTS):
        self._history = deque(maxlen=maxlen)
        self._subs = set()          # (loop, asyncio.Queue)
        self._lock = threading.Lock()

    def history(self):
        with self._lock:
            return list(self._history)

    def publish(self, e):
        """Store and fan out one event. Safe to call from any thread."""
        validate(e)
        with self._lock:
            self._history.append(e)
            subs = list(self._subs)
        for loop, q in subs:
            loop.call_soon_threadsafe(_offer, q, e)
        return len(self._history)

    def reset(self):
        """Forget the stored events (a new recording) and tell the pages."""
        with self._lock:
            self._history.clear()
            subs = list(self._subs)
        for loop, q in subs:
            loop.call_soon_threadsafe(_offer, q, {"type": "hub.reset"})

    def subscribe(self, loop, queue):
        """Register a page's queue; returns the history to replay first."""
        with self._lock:
            self._subs.add((loop, queue))
            return list(self._history)

    def unsubscribe(self, loop, queue):
        with self._lock:
            self._subs.discard((loop, queue))
