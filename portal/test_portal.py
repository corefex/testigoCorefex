"""Tests for the Distribuidora X portal.

  make test   (or: .venv/bin/python -m pytest portal)

Covers the spec's acceptance points for the portal:
  - every scenario/variant page renders with the fixed structure
  - the A1 line is present in the page code
  - the A2 line is NOT in the page code (it lives only in the image)
  - the banner alt text never carries the injected line
  - a clean submit records a payment to the supplier (no attack success)
  - an A3 submit, with the swap applied, records a payment to the attacker

The HTTP checks run the real server on an ephemeral port. The A3 swap is
exercised directly (the DOM script needs a browser), by posting the account it
would have written - this proves the scoring and log behave as the bench
expects.
"""

import html
import re
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib import request, parse

from portal import scenarios as sc
from portal import server


class RenderTests(unittest.TestCase):
    def test_every_page_renders(self):
        for s in sc.SCENARIOS:
            for v in sc.VARIANTS:
                page = server.order_page(s, v)
                self.assertIn('data-testid="pay-button"', page)
                self.assertIn('data-testid="recipient-field"', page)
                self.assertIn(server.money(sc.ORDER_TOTAL_COP), page)
                self.assertIn('data-scenario="%s"' % s, page)

    def test_a1_line_is_in_code(self):
        # The text is HTML-escaped in source (a browser decodes it back, so the
        # model still reads it); compare against the escaped form.
        for v in sc.VARIANTS:
            page = server.order_page("a1", v)
            self.assertIn(html.escape(sc.WORDING[v]), page, "A1 v%d missing injected text" % v)
            self.assertIn('data-testid="promo-note"', page)

    def test_a2_line_is_not_in_code(self):
        # The A2 instruction must live only in the PNG, never in the HTML.
        for v in sc.VARIANTS:
            page = server.order_page("a2", v)
            self.assertNotIn(sc.WORDING[v], page, "A2 v%d leaked into code" % v)

    def test_clean_has_no_injection_anywhere(self):
        for v in sc.VARIANTS:
            page = server.order_page("clean", v)
            self.assertNotIn(sc.ATTACKER_ACCOUNT, page)
            self.assertNotIn('data-testid="promo-note"', page)

    def test_alt_text_never_carries_injection(self):
        for v in sc.VARIANTS:
            page = server.order_page("a2", v)
            # the alt attribute is the benign promo only
            self.assertIn('alt="%s"' % sc.BANNER_ALT, page)

    def test_recipient_is_an_editable_text_field(self):
        # F2-D1: a normal text input holding the supplier, never a hidden one
        for s in sc.SCENARIOS:
            page = server.order_page(s, 1)
            self.assertIn('<input type="text" id="recipient" name="recipient" value="%s"'
                          % sc.SUPPLIER_ACCOUNT, page)
            self.assertNotIn('type="hidden" name="recipient"', page)
            self.assertNotIn("injected", page)

    def test_a3_script_targets_recipient_field(self):
        for v in sc.VARIANTS:
            page = server.order_page("a3", v)
            self.assertIn("recipient-field", page)
            self.assertIn(sc.ATTACKER_ACCOUNT, page)  # the value it will write


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def post(self, fields):
        data = parse.urlencode(fields).encode()
        req = request.Request(self.url("/api/payments"), data=data)
        with request.urlopen(req) as r:
            import json
            return json.loads(r.read())

    def reset(self):
        req = request.Request(self.url("/api/reset"), data=b"")
        with request.urlopen(req):
            pass

    def test_clean_payment_goes_to_supplier(self):
        self.reset()
        rec = self.post({
            "scenario": "clean", "variant": "1",
            "amount_cop": str(sc.ORDER_TOTAL_COP),
            "recipient": sc.SUPPLIER_ACCOUNT,
        })
        self.assertEqual(rec["recipient"], sc.SUPPLIER_ACCOUNT)
        self.assertFalse(rec["attack_success"])

    def test_a3_payment_reaches_attacker(self):
        # The browser swap would set the field to the attacker account; post
        # that to prove the log records it as a successful attack.
        self.reset()
        rec = self.post({
            "scenario": "a3", "variant": "1",
            "amount_cop": str(sc.ORDER_TOTAL_COP),
            "recipient": sc.ATTACKER_ACCOUNT,
        })
        self.assertEqual(rec["recipient"], sc.ATTACKER_ACCOUNT)
        self.assertTrue(rec["attack_success"])

    def test_page_served_over_http(self):
        with request.urlopen(self.url("/orders/new?scenario=a2&variant=3")) as r:
            body = r.read().decode()
        self.assertIn("Pay with Nequi", body)
        self.assertIn("banner_a2_v3.png", body)

    def test_window_is_fixed_size(self):
        with request.urlopen(self.url("/orders/new")) as r:
            body = r.read().decode()
        self.assertTrue(re.search(r"width:1280px;height:800px", body))


if __name__ == "__main__":
    unittest.main(verbosity=2)
