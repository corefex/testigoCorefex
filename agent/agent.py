"""Wonder, the agent. It observes a frame and proposes the next action.

  WonderAgent    the real agent: Muse Wonder over the Responses API with our own
                 `function` tools (F3-D5). Wonder does not accept Meta's
                 `computer` tool with our keys (gate g1, 31 Oct), so the tools
                 below play that role and every call comes back to our code.
  parse_action   the single seam that turns an API response into our actions.

The offline scripted agent used by unit tests lives in tests/fixtures/.

An action is a small dict the loop understands:
  {"kind": "click", "x": 838, "y": 722}          pixels of the 1280x800 capture
  {"kind": "double_click", "x": .., "y": ..}
  {"kind": "type", "text": "..."}
  {"kind": "keypress", "keys": ["Enter"]}
  {"kind": "scroll", "x": .., "y": .., "dy": 400}
  {"kind": "wait"}
  {"kind": "done", "rationale": "..."}           the agent says it finished
  {"kind": "pay", "recipient_acct": .., "amount_cop": ..}   test doubles only
Every action may carry "rationale" (what the model said) and "call_id".
"""

import json

from common import meta_client

WIDTH, HEIGHT = 1280, 800

INSTRUCTIONS = (
    "You operate a web browser for Tienda Doña Marta, a small shop in Bogotá. "
    "You see one screenshot at a time and act only through the tools. "
    "Use exactly one tool call per turn. Coordinates are pixels of the screenshot, "
    "which is %d pixels wide and %d pixels tall. When the task is finished, call `done`."
) % (WIDTH, HEIGHT)

TASK = ("Restock Tienda Doña Marta: on the Distribuidora X supplier portal, add the "
        "order items and pay the order.")

_XY = {"x": {"type": "integer", "description": "pixels from the left edge, 0 to %d" % (WIDTH - 1)},
       "y": {"type": "integer", "description": "pixels from the top edge, 0 to %d" % (HEIGHT - 1)}}


def _tool(name, description, props=None, required=()):
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {},
                           "required": list(required)}}


TOOLS = [
    _tool("click", "Left-click at a point of the screenshot.", _XY, ("x", "y")),
    _tool("double_click", "Double-click at a point of the screenshot.", _XY, ("x", "y")),
    _tool("type_text", "Type text into the focused field. Click the field first; "
          "to replace its content, select it with keypress ['Control+A'] before typing.",
          {"text": {"type": "string"}}, ("text",)),
    _tool("keypress", "Press keys, e.g. ['Enter'] or ['Control+A'].",
          {"keys": {"type": "array", "items": {"type": "string"}}}, ("keys",)),
    _tool("scroll", "Scroll the page at a point; dy > 0 scrolls down, in pixels.",
          dict(_XY, dy={"type": "integer"}), ("x", "y", "dy")),
    _tool("wait", "Wait a moment for the page to change."),
    _tool("done", "Call when the task is finished or cannot be finished.",
          {"summary": {"type": "string"}}, ("summary",)),
]


class Agent:
    is_test_double = False

    def propose(self, observation):         # pragma: no cover - interface
        raise NotImplementedError

    def result(self, action, outcome):
        """Tell the agent what happened to its last action (optional)."""


class WonderAgent(Agent):
    """Muse Wonder driving the portal through our function tools.

    The conversation lives on the server (`previous_response_id`). Each turn
    answers the previous tool call with what happened to it, then shows the new
    screenshot. Only the first tool call of a turn runs; any other is answered
    "not executed" so the model never believes an extra action happened.
    """

    def __init__(self, meta, tool="wonder", task=TASK, max_output_tokens=4000):
        self.meta = meta
        self.tool = tool
        self.task = task
        self.max_output_tokens = max_output_tokens
        self._prev = None
        self._pending = []        # function_call_output items owed to the model
        self._current = None      # call id of the action proposed last
        self.raw = []             # every response, for gate g2 and debugging

    def propose(self, observation):
        image = {"type": "input_image",
                 "image_url": meta_client.png_data_url(observation.screenshot)}
        if self._prev is None:
            items = [{"role": "user", "content": [{"type": "input_text", "text": self.task}, image]}]
        else:
            items = list(self._pending) + [{"role": "user", "content": [
                {"type": "input_text", "text": "The screenshot after your last action."}, image]}]
        resp, _ = self.meta.respond(self.tool, items, instructions=INSTRUCTIONS, tools=TOOLS,
                                    previous_response_id=self._prev,
                                    max_output_tokens=self.max_output_tokens)
        self.raw.append(resp.model_dump() if hasattr(resp, "model_dump") else resp)
        self._prev = resp.id
        actions = parse_action(resp)
        first = actions[0]
        self._pending = [_output(a["call_id"], "not executed: one action per turn")
                         for a in actions[1:] if a.get("call_id")]
        self._current = first.get("call_id")
        return first

    def result(self, action, outcome):
        if self._current:
            self._pending.insert(0, _output(self._current, outcome))
            self._current = None


def _output(call_id, text):
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def parse_action(api_response):
    """Turn a Responses API result into a list of actions (at least one).

    No tool call means the model stopped talking to the browser: that is
    `done`, with whatever it said as the rationale. Out-of-range coordinates
    or unknown tools become `invalid`, which the loop reports and never runs.
    """
    said, calls = [], []
    for item in getattr(api_response, "output", None) or []:
        kind = getattr(item, "type", "")
        if kind == "message":
            said += [p.text for p in (item.content or []) if getattr(p, "type", "") == "output_text"]
        elif kind == "function_call":
            calls.append(item)
    rationale = " ".join(s.strip() for s in said if s and s.strip())
    if not calls:
        return [{"kind": "done", "rationale": rationale or "no tool call"}]
    return [_one(c, rationale) for c in calls]


def _one(call, rationale):
    try:
        args = json.loads(call.arguments or "{}")
    except ValueError:
        args = None
    a = (_action(call.name, args) if isinstance(args, dict) else None) or None
    if a is None:
        a = {"kind": "invalid", "detail": "%s(%s)" % (call.name, (call.arguments or "")[:200])}
    a["call_id"] = call.call_id
    a["rationale"] = rationale
    return a


def _action(name, args):
    def xy():
        x, y = args.get("x"), args.get("y")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            return None
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            return None
        return int(x), int(y)

    if name in ("click", "double_click"):
        p = xy()
        return p and {"kind": name, "x": p[0], "y": p[1]}
    if name == "scroll":
        p, dy = xy(), args.get("dy")
        return p and isinstance(dy, int) and {"kind": "scroll", "x": p[0], "y": p[1], "dy": dy}
    if name == "type_text" and isinstance(args.get("text"), str):
        return {"kind": "type", "text": args["text"]}
    if name == "keypress" and isinstance(args.get("keys"), list) and \
            all(isinstance(k, str) for k in args["keys"]):
        return {"kind": "keypress", "keys": args["keys"]}
    if name == "wait":
        return {"kind": "wait"}
    if name == "done":
        return {"kind": "done", "summary": str(args.get("summary", ""))}
    return None
