"""Gate g1: a real call to each Meta model from this machine (F0 §13, R5).

  .venv/bin/python -m gate.g1_api_bogota [--audio clip.wav]

Checks, each against the real API through common.meta_client:
  models  the four configured model ids are listed by the API
  spark   Spark 1.3 reads the total from a screenshot of the portal
  wonder  Wonder 1.0 answers the same question
  sam     SAM 3.1 returns a box for "confirm button" on that screenshot
  voice   Voice Transcribe hears the amount in a Spanish WAV clip
It also records, without failing, whether each model accepts the `computer`
tool (computer use), which decides how F3 drives the browser.

Without --audio the clip is synthesized with macOS `say`; elsewhere voice is
marked "omitted". Spend is a few cents. The raw answers go to
runs/gate/<date>/g1/. That the call came from Bogotá, and that the credits were
claimed, is confirmed by a person (manual items of the gate).
"""

import argparse
import json
import re
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer

from common import meta_client
from gate.report import report, run_dir

TOTAL = "120,000"
SPOKEN = "ciento veinte mil pesos, entrega en Tienda Doña Marta"


def portal_screenshot(path):
    """A 1280x800 capture of the clean order page, from an in-process portal."""
    from playwright.sync_api import sync_playwright
    from portal.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto("http://127.0.0.1:%d/orders/new?scenario=clean&variant=1" % httpd.server_port)
            page.screenshot(path=str(path))
            browser.close()
    finally:
        httpd.shutdown()
    return path.read_bytes()


def synth_clip(out_dir):
    if not (shutil.which("say") and shutil.which("afconvert")):
        return None
    aiff, wav = out_dir / "voice.aiff", out_dir / "voice.wav"
    subprocess.run(["say", "-v", "Paulina", "-o", str(aiff), SPOKEN], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(wav)], check=True)
    return wav


def norm(s):
    return re.sub(r"[^0-9a-záéíóúñ ]", "", (s or "").lower())


def check(results, name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 - a failed call is a failed check
        ok, detail = False, "%s: %s" % (type(e).__name__, str(e)[:300])
    results[name] = {"pass": ok, "detail": detail}


def computer_tool(meta, tool, png):
    """'supported' or the API's refusal; never fails the gate."""
    try:
        resp, _ = meta.respond(tool, [{"role": "user", "content": [
            {"type": "input_text", "text": "Confirm this order. Propose the next action."},
            {"type": "input_image", "image_url": meta_client.png_data_url(png)}]}],
            tools=[{"type": "computer"}])
        calls = [o for o in resp.output if getattr(o, "type", "") == "computer_call"]
        return "supported (%d computer_call)" % len(calls)
    except Exception as e:  # noqa: BLE001
        return "refused: %s" % str(e)[:200]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--audio", help="a Spanish WAV clip saying: " + SPOKEN)
    args = ap.parse_args(argv)

    out = run_dir("g1")
    meta = meta_client.MetaClient()
    png = portal_screenshot(out / "portal_clean.png")
    ask = "What is the total amount on this page? Answer only the amount."
    raw = {}
    results = {}

    def models():
        listed = set(meta.list_models())
        wanted = {meta.model(t) for t in ("wonder", "spark", "sam", "voice")}
        raw["models"] = sorted(listed)
        return wanted <= listed, "missing: %s" % sorted(wanted - listed) if wanted - listed else "all 4 listed"

    def spark():
        resp, ms = meta.chat("spark", [{"role": "user", "content": meta_client.image_content(png, ask)}],
                             max_tokens=1500)
        text = resp.choices[0].message.content or ""
        raw["spark"] = text
        return TOTAL in text, "%r in %d ms" % (text, ms)

    def wonder():
        resp, ms = meta.respond("wonder", [{"role": "user", "content": [
            {"type": "input_text", "text": ask},
            {"type": "input_image", "image_url": meta_client.png_data_url(png)}]}],
            max_output_tokens=3000)
        text = meta_client.output_text(resp)
        raw["wonder"] = text
        return TOTAL in text, "%r in %d ms" % (text, ms)

    def sam():
        boxes, ms = meta.segment(png, "confirm button")
        raw["sam"] = boxes
        return bool(boxes), "%d box(es) %s in %d ms" % (len(boxes), [b["box"] for b in boxes], ms)

    check(results, "models", models)
    check(results, "spark", spark)
    check(results, "wonder", wonder)
    check(results, "sam", sam)

    clip = args.audio or synth_clip(out)
    if clip:
        def voice():
            text, ms, secs = meta.transcribe(clip)
            raw["voice"] = text
            return "ciento veinte mil" in norm(text), "%r, %.1f s of audio in %d ms" % (text, secs, ms)
        check(results, "voice", voice)
    else:
        results["voice"] = {"pass": None, "detail": "omitted: no clip (pass --audio)"}

    raw["computer_tool"] = {t: computer_tool(meta, t, png) for t in ("wonder", "spark")}
    (out / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str),
                                  encoding="utf-8")

    required = [r["pass"] for r in results.values() if r["pass"] is not None]
    passed = sum(1 for r in required if r)
    details = dict(results, computer_tool=raw["computer_tool"],
                   spent_usd_total=round(meta.spent_usd(), 4),
                   manual="confirm the call was made from Bogotá and the credits were claimed")
    return report("g1", bool(required) and passed == len(required),
                  "%d/%d checks passed" % (passed, len(required)),
                  "%d/%d" % (len(required), len(required)), len(required), details)


if __name__ == "__main__":
    raise SystemExit(main())
