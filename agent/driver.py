"""Browser driver: what the agent observes and what actually executes.

The loop never touches a browser directly. It drives a `BrowserDriver`;
`observe()` returns an interceptor `Capture` (code channel + pixel channel +
crops), the same object the interceptor checks.

The real driver is Playwright (F3). The offline test double lives in
tests/fixtures/fake_agent.py and is never used outside tests.
"""

import json
import urllib.request
from contextlib import contextmanager
from urllib.parse import urlsplit

from common import clock, config
from interceptor.channels import Capture

SUPPLIER_ACCT = "310-XXX-4417"
ATTACKER_ACCT = "300-XXX-0000"

SETTLE_MS = 400   # after an action, let the page react before the next capture

# Every text node of the page body, rendered or not (A1's hidden line is here),
# plus the value of each text field. This is the "code" side of F5; it is never
# used to decide where the agent clicked or what the pixels show.
_CODE_TEXT_JS = """() => {
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const tag = n.parentElement ? n.parentElement.tagName : '';
    if (tag === 'SCRIPT' || tag === 'STYLE') continue;
    const t = n.textContent.replace(/\\s+/g, ' ').trim();
    if (t) out.push(t);
  }
  for (const el of document.querySelectorAll('input[type=text], textarea')) {
    if (el.value) out.push(el.value);
  }
  return out;
}"""


class BrowserDriver:
    is_test_double = False

    def observe(self):                      # pragma: no cover - interface
        raise NotImplementedError

    def pixel_channel(self):                # pragma: no cover - interface
        raise NotImplementedError

    def execute(self, action):              # pragma: no cover - interface
        raise NotImplementedError

    def observe_after(self):                # pragma: no cover - interface
        raise NotImplementedError

    @property
    def last_payment(self):                 # pragma: no cover - interface
        raise NotImplementedError


class PlaywrightDriver(BrowserDriver):
    """Real driver over a Chromium page.

      observe()        -> screenshot + page-code text, as a Capture; the PNG is
                          saved under runs/<run>/ so the interface can show it
      pixel_channel()  -> the pixel channel given at construction (F4)
      execute(action)  -> perform the click/type/keys/scroll on the page
      observe_after()  -> re-capture after the action
      last_payment     -> the payment this run made, from the portal's log

    `rendered_lines` stays empty here: what the pixels say is read by the pixel
    channel (F4/F5), never from the DOM.
    """

    def __init__(self, page, portal_url, scenario, variant, pixel_channel=None, run_dir=None):
        self.page = page
        self.portal_url = portal_url.rstrip("/")
        self.scenario = scenario
        self.variant = variant
        self._pixels = pixel_channel
        self.run_dir = run_dir
        self.frame = 0
        self._payments_before = None
        self._payment = None

    def start(self):
        self._payments_before = len(self._payments())
        self.page.goto("%s/orders/new?scenario=%s&variant=%s"
                       % (self.portal_url, self.scenario, self.variant))
        self.page.wait_for_load_state("networkidle")

    def observe(self):
        self.frame += 1
        png = self.page.screenshot(type="png")
        image = None
        if self.run_dir is not None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            p = self.run_dir / ("frame_%03d.png" % self.frame)
            p.write_bytes(png)
            image = _runs_relative(p)
        code = self.page.evaluate(_CODE_TEXT_JS)
        return Capture(self.frame, code, [], {}, screenshot=png, ts=clock.iso(), image=image)

    def pixel_channel(self):
        return self._pixels

    def execute(self, action):
        kind, mouse, kb = action.get("kind"), self.page.mouse, self.page.keyboard
        if kind == "click":
            mouse.click(action["x"], action["y"])
        elif kind == "double_click":
            mouse.dblclick(action["x"], action["y"])
        elif kind == "type":
            kb.type(action["text"])
        elif kind == "keypress":
            for key in action["keys"]:
                kb.press(_key(key))
        elif kind == "scroll":
            mouse.move(action["x"], action["y"])
            mouse.wheel(0, action["dy"])
        elif kind == "wait":
            pass
        else:
            raise ValueError("the browser cannot execute %r" % kind)
        self.page.wait_for_timeout(SETTLE_MS)
        self.page.wait_for_load_state("networkidle")
        self._payment = self._new_payment()

    def observe_after(self):
        return self.observe()

    @property
    def path(self):
        return urlsplit(self.page.url).path

    @property
    def last_payment(self):
        return self._payment

    def _new_payment(self):
        log = self._payments()
        return dict(log[-1]) if len(log) > (self._payments_before or 0) else None

    def _payments(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.portal_url + "/api/payments", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))


def _key(k):
    """Playwright key names: 'ctrl+a' -> 'Control+A', 'enter' -> 'Enter'."""
    names = {"ctrl": "Control", "control": "Control", "cmd": "Meta", "meta": "Meta",
             "alt": "Alt", "shift": "Shift", "enter": "Enter", "return": "Enter",
             "tab": "Tab", "backspace": "Backspace", "delete": "Delete", "escape": "Escape",
             "esc": "Escape", "space": "Space"}
    parts = [names.get(p.strip().lower(), p.strip()) for p in k.split("+")]
    parts = [p.upper() if len(p) == 1 else p for p in parts]
    return "+".join(parts)


def _runs_relative(p):
    try:
        return p.resolve().relative_to(config.settings().runs_dir.resolve()).as_posix()
    except ValueError:
        return None


@contextmanager
def open_portal(scenario, variant, pixel_channel=None, run_dir=None, headless=True):
    """A Chromium page on the running portal, with the measurable setup (F0 §9)."""
    from playwright.sync_api import sync_playwright
    from scripts.doctor import browser_context_options
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_context(**browser_context_options()).new_page()
            driver = PlaywrightDriver(page, config.settings().portal_url, scenario, variant,
                                      pixel_channel=pixel_channel, run_dir=run_dir)
            driver.start()
            yield driver
        finally:
            browser.close()
