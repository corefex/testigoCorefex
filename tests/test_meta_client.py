"""F0 §8 and §15: the Meta client against a fake local server (no real API).

Covers: usage log, cost estimate, spend cap, retries only on retryable errors,
refusing to run without configuration, and the request/response shapes of the
Responses API, SAM and Voice as seen against the real API in gate g1.
"""

import dataclasses
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import config
from common.meta_client import MetaClient, NotConfigured, SpendCapExceeded, parse_sam_boxes

COMPLETION = {
    "id": "c1", "object": "chat.completion", "created": 0, "model": "fake",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000},
}

SAM_TEXT = ("<0f>0<|box;x1=754;y1=700;x2=923;y2=747;w=1280;h=800|><|mask;x=0;y=0;data=48,170,~!!|>"
            ",1<|box;x1=10;y1=20;x2=30;y2=40;c=0.42;w=1280;h=800|><|mask;x=0;y=0;data=1,1,~!|>\n")


def response(text, usage):
    return {"id": "r1", "object": "response", "created_at": 0, "model": "fake", "status": "completed",
            "output": [{"id": "m1", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}],
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "usage": usage}


TRANSCRIPT = {"sessionId": "s1", "transcript": "ciento veinte mil pesos", "audioDurationMs": 3040, "turns": []}


class FakeAPI(BaseHTTPRequestHandler):
    script = []   # statuses to return, in order; then 200
    calls = 0
    last = None   # (path, content type, body) of the last request

    def do_POST(self):
        FakeAPI.calls += 1
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        FakeAPI.last = (self.path, self.headers.get("Content-Type", ""), raw)
        status = FakeAPI.script.pop(0) if FakeAPI.script else 200
        if status != 200:
            ok = {"error": {"message": "x"}}
        elif self.path.endswith("/asr/transcribe"):
            ok = TRANSCRIPT
        elif self.path.endswith("/responses"):
            req = json.loads(raw)
            ok = (response(SAM_TEXT, None) if req["model"] == "fake-sam" else
                  response("COP 120,000", {"input_tokens": 1_000_000, "output_tokens": 0,
                                           "total_tokens": 1_000_000}))
        else:
            ok = COMPLETION
        body = json.dumps(ok).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class MetaClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/v1" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        FakeAPI.script, FakeAPI.calls = [], 0
        self.tmp = tempfile.mkdtemp()
        self.usage = Path(self.tmp, "usage.jsonl")

    def client(self, max_spend=10.0, **over):
        fields = dict(meta_base_url=self.base, meta_api_key="test-not-a-real-key",
                      model_spark="fake-spark", model_sam="fake-sam", model_voice="fake-voice",
                      max_spend_usd=max_spend)
        fields.update(over)
        s = dataclasses.replace(config.settings(), **fields)
        return MetaClient(settings=s, usage_path=self.usage, sleep=lambda _: None)

    def records(self):
        return [json.loads(x) for x in self.usage.read_text().splitlines()]

    def test_call_is_logged_with_cost(self):
        resp, ms = self.client().chat("spark", [{"role": "user", "content": "hi"}])
        self.assertEqual(resp.choices[0].message.content, "ok")
        rec = self.records()[-1]
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["tool"], "spark")
        self.assertEqual(rec["model"], "fake-spark")
        self.assertAlmostEqual(rec["cost_usd"], 1.25)   # 1M input tokens at USD 1.25
        self.assertGreaterEqual(rec["latency_ms"], 0)

    def test_spend_cap_stops_calls(self):
        c = self.client(max_spend=1.0)
        c.chat("spark", [{"role": "user", "content": "hi"}])   # spends 1.25
        with self.assertRaises(SpendCapExceeded):
            c.chat("spark", [{"role": "user", "content": "hi"}])
        self.assertEqual(FakeAPI.calls, 1)

    def test_retries_rate_limit_then_succeeds(self):
        FakeAPI.script = [429]
        self.client().chat("spark", [{"role": "user", "content": "hi"}])
        recs = self.records()
        self.assertEqual([r["ok"] for r in recs], [False, True])
        self.assertEqual(FakeAPI.calls, 2)

    def test_gives_up_after_two_retries(self):
        FakeAPI.script = [429, 429, 429]
        with self.assertRaises(Exception):
            self.client().chat("spark", [{"role": "user", "content": "hi"}])
        self.assertEqual(FakeAPI.calls, 3)

    def test_no_retry_on_bad_request(self):
        FakeAPI.script = [400]
        with self.assertRaises(Exception):
            self.client().chat("spark", [{"role": "user", "content": "hi"}])
        self.assertEqual(FakeAPI.calls, 1)

    def test_refuses_without_configuration(self):
        with self.assertRaises(NotConfigured):
            self.client(meta_base_url="").chat("spark", [{"role": "user", "content": "hi"}])
        with self.assertRaises(NotConfigured):
            self.client(model_spark="").chat("spark", [{"role": "user", "content": "hi"}])

    def test_respond_logs_responses_api_tokens(self):
        resp, _ = self.client().respond("spark", "hi")
        self.assertEqual(FakeAPI.last[0], "/v1/responses")
        self.assertAlmostEqual(self.records()[-1]["cost_usd"], 1.25)   # input_tokens priced

    def test_sam_returns_boxes_and_costs_one_image(self):
        boxes, _ = self.client().segment(b"\x89PNG fake", "pay button")
        self.assertEqual(boxes, [{"box": [754, 700, 923, 747], "confidence": None},
                                 {"box": [10, 20, 30, 40], "confidence": 0.42}])
        req = json.loads(FakeAPI.last[2])
        self.assertEqual(req["model"], "fake-sam")
        parts = req["input"][0]["content"]
        self.assertEqual(parts[0], {"type": "input_text", "text": "pay button"})
        self.assertTrue(parts[1]["image_url"].startswith("data:image/png;base64,"))
        rec = self.records()[-1]
        self.assertEqual((rec["tool"], rec["cost_usd"]), ("sam", 0.0025))

    def test_sam_no_match_is_empty(self):
        self.assertEqual(parse_sam_boxes(""), [])
        self.assertEqual(parse_sam_boxes("<0f>"), [])

    def test_voice_sends_request_and_audio_parts(self):
        clip = Path(self.tmp, "clip.wav")
        clip.write_bytes(b"RIFF fake wav")
        text, _, secs = self.client().transcribe(clip)
        self.assertEqual((text, secs), ("ciento veinte mil pesos", 3.04))
        path, ctype, body = FakeAPI.last
        self.assertEqual(path, "/v1/asr/transcribe")
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="request"', body)
        self.assertIn(b'"model": "fake-voice"', body)
        self.assertIn(b'name="audio"; filename="clip.wav"', body)
        self.assertIn(b"RIFF fake wav", body)
        self.assertAlmostEqual(self.records()[-1]["cost_usd"], 0.18 * 3 / 3600, places=6)


if __name__ == "__main__":
    unittest.main()
