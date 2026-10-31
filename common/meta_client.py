"""The single entry point to Meta's API (OpenAI-compatible SDK).

No other module creates an API client or reads META_API_KEY; a test enforces it.

Every call:
  - goes to the model named by a META_MODEL_* variable (never hard-coded);
  - appends one line to runs/usage.jsonl: tool, model, usage, latency, cost;
  - is refused once the spend recorded in runs/usage.jsonl reaches MAX_SPEND_USD;
  - is retried at most twice, only on network errors or rate limits.

A failure is raised, never swallowed. Callers that decide (the interceptor)
turn a failure into `cannot_verify`: in doubt, block.

Endpoints, confirmed against the real API on 31 Oct (gate g1, R5):
  - Spark and Wonder: Chat Completions (`chat`) and the Responses API
    (`respond`). Images go as `image_url` (chat) or `input_image` (responses).
  - SAM 3.1: the Responses API with a noun phrase and one image; boxes come back
    as text tokens `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>` (`segment`).
  - Voice Transcribe: `POST /asr/transcribe`, multipart with a JSON `request`
    part and a WAV `audio` part (`transcribe`).
  - The `computer` tool answers on Spark 1.3 but not on Wonder 1.0 with our keys
    ("Unsupported tool type: 'computer'"); see F3.
"""

import base64
import json
import re
import time
from pathlib import Path

from . import clock, config

# Prices from the general spec (USD). Per million tokens for text models.
PRICES = {
    "wonder": {"in_per_mtok": 4.00, "out_per_mtok": 20.00},
    "spark": {"in_per_mtok": 1.25, "out_per_mtok": 4.25},
    "sam": {"per_1k_images": 2.50},
    "voice": {"per_hour": 0.18},
    "glimmer": {},  # local: no API cost
}

MAX_RETRIES = 2


class SpendCapExceeded(RuntimeError):
    pass


class NotConfigured(RuntimeError):
    pass


class MetaClient:
    def __init__(self, settings=None, usage_path=None, sdk_client=None, sleep=time.sleep):
        self.s = settings or config.settings()
        self.usage_path = Path(usage_path) if usage_path else self.s.runs_dir / "usage.jsonl"
        self._sdk = sdk_client
        self._local = None
        self._sleep = sleep

    # -- clients ------------------------------------------------------------

    def _client(self):
        if self._sdk is None:
            missing = self.s.missing("META_API_BASE_URL", "META_API_KEY")
            if missing:
                raise NotConfigured("set %s in .env" % ", ".join(missing))
            from openai import OpenAI
            self._sdk = OpenAI(base_url=self.s.meta_base_url,
                               api_key=self.s.meta_api_key, max_retries=0)
        return self._sdk

    def _glimmer(self):
        if self._local is None:
            if not self.s.glimmer_base_url:
                raise NotConfigured("set GLIMMER_BASE_URL in .env")
            from openai import OpenAI
            self._local = OpenAI(base_url=self.s.glimmer_base_url,
                                 api_key="local", max_retries=0)
        return self._local

    def model(self, tool):
        name = {"wonder": self.s.model_wonder, "spark": self.s.model_spark,
                "sam": self.s.model_sam, "voice": self.s.model_voice,
                "glimmer": self.s.glimmer_model}[tool]
        if not name:
            raise NotConfigured("set META_MODEL_%s in .env" % tool.upper()
                                if tool != "glimmer" else "set GLIMMER_MODEL in .env")
        return name

    # -- spend --------------------------------------------------------------

    def spent_usd(self):
        if not self.usage_path.is_file():
            return 0.0
        total = 0.0
        for line in self.usage_path.read_text(encoding="utf-8").splitlines():
            try:
                total += float(json.loads(line).get("cost_usd") or 0)
            except ValueError:
                continue
        return total

    def _check_budget(self):
        spent = self.spent_usd()
        if spent >= self.s.max_spend_usd:
            raise SpendCapExceeded("spent USD %.2f of MAX_SPEND_USD %.2f" % (spent, self.s.max_spend_usd))

    def _log(self, record):
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- calls --------------------------------------------------------------

    def _call(self, tool, model, fn, usage_of, cost_of):
        self._check_budget()
        attempt = 0
        while True:
            t0 = time.perf_counter()
            try:
                result = fn()
                ms = int(round((time.perf_counter() - t0) * 1000))
                usage = usage_of(result)
                self._log({"ts": clock.iso(), "tool": tool, "model": model, "ok": True,
                           "attempt": attempt, "latency_ms": ms, "usage": usage,
                           "cost_usd": round(cost_of(usage), 6)})
                return result, ms
            except Exception as e:  # noqa: BLE001 - logged, then retried or raised
                ms = int(round((time.perf_counter() - t0) * 1000))
                retryable = _is_retryable(e)
                self._log({"ts": clock.iso(), "tool": tool, "model": model, "ok": False,
                           "attempt": attempt, "latency_ms": ms,
                           "error": "%s: %s" % (type(e).__name__, str(e)[:300]),
                           "cost_usd": 0})
                if not retryable or attempt >= MAX_RETRIES:
                    raise
                attempt += 1
                self._sleep(0.5 * (2 ** attempt))

    def chat(self, tool, messages, **kwargs):
        """Chat completion with Wonder, Spark or Glimmer. Returns (response, latency_ms)."""
        model = self.model(tool)
        client = self._glimmer() if tool == "glimmer" else self._client()
        return self._call(
            tool, model,
            lambda: client.chat.completions.create(model=model, messages=messages, **kwargs),
            _token_usage, lambda u: _token_cost(tool, u))

    def respond(self, tool, input, **kwargs):
        """Responses API with Wonder or Spark. Returns (response, latency_ms)."""
        model = self.model(tool)
        client = self._client()
        return self._call(
            tool, model,
            lambda: client.responses.create(model=model, input=input, **kwargs),
            _token_usage, lambda u: _token_cost(tool, u))

    def transcribe(self, audio_path, language="es"):
        """Voice Transcribe on a WAV file. Returns (text, latency_ms, seconds).

        The API detects the language itself; `language` is kept for callers."""
        model = self.model("voice")
        client = self._client()
        request = json.dumps({"model": model, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"})

        def fn():
            with open(audio_path, "rb") as f:
                return client.post("/asr/transcribe", cast_to=object, files=[
                    ("request", (None, request.encode("utf-8"), "application/json")),
                    ("audio", (Path(audio_path).name, f.read(), "audio/wav"))],
                    options={"headers": {"Content-Type": "multipart/form-data"}})

        resp, ms = self._call("voice", model, fn,
                              lambda r: {"audio_seconds": (r.get("audioDurationMs") or 0) / 1000.0},
                              lambda u: PRICES["voice"]["per_hour"] * int(u["audio_seconds"]) / 3600.0)
        return resp.get("transcript", ""), ms, (resp.get("audioDurationMs") or 0) / 1000.0

    def segment(self, image_png, phrase):
        """SAM 3.1: boxes for one noun phrase. Returns (boxes, latency_ms).

        Each box is {"box": [x1, y1, x2, y2], "confidence": float or None}, in
        pixels of the image sent. Masks are not decoded (we only need boxes)."""
        model = self.model("sam")
        client = self._client()
        content = [{"type": "input_text", "text": phrase},
                   {"type": "input_image", "image_url": png_data_url(image_png)}]
        resp, ms = self._call(
            "sam", model,
            lambda: client.responses.create(model=model, input=[{"role": "user", "content": content}],
                                            metadata={"include_confidence": "true"}),
            lambda r: {"images": 1},
            lambda u: PRICES["sam"]["per_1k_images"] * u["images"] / 1000.0)
        return parse_sam_boxes(output_text(resp)), ms

    def list_models(self):
        resp, _ = self._call("spark", "models.list", lambda: self._client().models.list(),
                             lambda r: {}, lambda u: 0.0)
        return [m.id for m in getattr(resp, "data", [])]


def png_data_url(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def image_content(png_bytes, text=None):
    """Chat Completions message content with one PNG."""
    parts = [{"type": "image_url", "image_url": {"url": png_data_url(png_bytes)}}]
    if text:
        parts.insert(0, {"type": "text", "text": text})
    return parts


def output_text(resp):
    """All `output_text` of a Responses API result, joined."""
    out = []
    for item in getattr(resp, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", "") == "output_text":
                out.append(part.text)
    return "".join(out)


_BOX = re.compile(r"<\|box;([^|>]*)\|>")


def parse_sam_boxes(text):
    """Boxes from SAM's text output; a phrase with no match gives []."""
    boxes = []
    for m in _BOX.finditer(text or ""):
        f = dict(kv.split("=", 1) for kv in m.group(1).split(";") if "=" in kv)
        try:
            box = [int(float(f[k])) for k in ("x1", "y1", "x2", "y2")]
        except (KeyError, ValueError):
            continue
        boxes.append({"box": box, "confidence": float(f["c"]) if "c" in f else None})
    return boxes


def _token_usage(resp):
    """Token counts from Chat Completions or the Responses API."""
    u = getattr(resp, "usage", None)
    if u is None:
        return {"prompt_tokens": None, "completion_tokens": None}
    tin = getattr(u, "prompt_tokens", None)
    tout = getattr(u, "completion_tokens", None)
    if tin is None and tout is None:
        tin, tout = getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)
    return {"prompt_tokens": tin, "completion_tokens": tout}


def _token_cost(tool, usage):
    p = PRICES.get(tool, {})
    if "in_per_mtok" not in p:
        return 0.0
    tin = usage.get("prompt_tokens") or 0
    tout = usage.get("completion_tokens") or 0
    return tin / 1e6 * p["in_per_mtok"] + tout / 1e6 * p["out_per_mtok"]


def _is_retryable(e):
    try:
        import openai
        return isinstance(e, (openai.APIConnectionError, openai.APITimeoutError,
                              openai.RateLimitError))
    except ImportError:
        return False
