"""Gate g6: Spanish spoken amounts, transcribed and parsed exactly and fast (F0 §13, D8).

  .venv/bin/python -m gate.g6_voice_numeric [--n 20] [--voices Paulina Juan]

Synthesizes --n phrases "<amount in words> pesos, entrega en Tienda Doña Marta" with macOS
`say` (the requested voices that exist here, alternating) as 16 kHz WAV,
transcribes each with Voice Transcribe and parses the amount with
approval.voice_match (the F7 code). "Exact" means the parsed amount equals the
amount said. Latency is measured in the client, from sending the finished
audio to receiving the text. Passes with >= 95% exact and a median < 1.5 s.

Without `say`/`afconvert`, or with none of the voices, the item is omitted
(pass null). Audio stays in runs/gate/<date>/g6/ (never committed).
"""

import argparse
import json
import random
import shutil
import statistics
import subprocess

from approval import voice_match
from common import meta_client
from gate.report import report, run_dir

DESTINATION = "Tienda Doña Marta"
EXACT_MIN = 0.95
MEDIAN_MAX_MS = 1500

_UNITS = ["", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
          "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
          "diecinueve", "veinte", "veintiún", "veintidós", "veintitrés", "veinticuatro",
          "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_TENS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta",
         8: "ochenta", 9: "noventa"}
_HUNDREDS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
             "seiscientos", "setecientos", "ochocientos", "novecientos"]


def _below_1000(n):
    if n == 100:
        return "cien"
    h, rest = divmod(n, 100)
    parts = [_HUNDREDS[h]] if h else []
    if rest < 30:
        parts.append(_UNITS[rest])
    else:
        t, u = divmod(rest, 10)
        parts.append(_TENS[t] + (" y " + _UNITS[u] if u else ""))
    return " ".join(p for p in parts if p)


def to_words(n):
    """1 <= n <= 999,999,999 in Spanish words, as a person says an amount."""
    if not 1 <= n <= 999_999_999:
        raise ValueError(n)
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append("un millón" if millions == 1 else _below_1000(millions) + " millones")
    if thousands:
        parts.append("mil" if thousands == 1 else _below_1000(thousands) + " mil")
    if units:
        parts.append(_below_1000(units))
    return " ".join(parts)


def amounts(n, seed=31):
    """n amounts in COP like the portal's orders: round to the hundred, 1,000 to 5,000,000."""
    rng = random.Random(seed)
    fixed = [120_000, 150_000, 1_250_000, 85_500, 999_900]
    out = fixed[:n]
    while len(out) < n:
        out.append(rng.randrange(10, 50_000) * 100)
    return out


def available_voices(wanted):
    if not (shutil.which("say") and shutil.which("afconvert")):
        return []
    listed = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    names = {line.split("  ")[0].strip() for line in listed.splitlines()}
    return [v for v in wanted if v in names]


def synth(text, voice, wav):
    aiff = wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)],
                   check=True)
    aiff.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=20, help="phrases to synthesize (default 20)")
    ap.add_argument("--voices", nargs="+", default=["Paulina", "Juan"])
    args = ap.parse_args(argv)

    voices = available_voices(args.voices)
    if not voices:
        return report("g6", None, "omitted: no macOS `say`/`afconvert` or none of %s" % args.voices,
                      "%d%% exact, median < %.1f s" % (EXACT_MIN * 100, MEDIAN_MAX_MS / 1000), 0,
                      {"omitted": True})

    out_dir = run_dir("g6")
    meta = meta_client.MetaClient()
    rows = []
    for i, amount in enumerate(amounts(args.n)):
        voice = voices[i % len(voices)]
        said = "%s pesos, entrega en %s" % (to_words(amount), DESTINATION)
        wav = out_dir / ("clip_%02d.wav" % i)
        synth(said, voice, wav)
        try:
            text, ms, secs = meta.transcribe(wav)
        except Exception as e:  # noqa: BLE001 - a failed call is a miss, reported
            rows.append({"amount": amount, "said": said, "voice": voice, "error": str(e)[:200],
                         "exact": False, "latency_ms": None})
            continue
        heard, why = voice_match.heard_amount(text, DESTINATION)
        rows.append({"amount": amount, "said": said, "voice": voice, "transcript": text,
                     "heard": heard, "why": why, "exact": heard == amount,
                     "latency_ms": ms, "audio_s": secs})
        print("g6: %s %r -> %s %s %d ms" % (voice, said, heard, "ok" if heard == amount else "MISS", ms),
              flush=True)

    (out_dir / "clips.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    exact = sum(1 for r in rows if r["exact"])
    lat = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    median = statistics.median(lat) if lat else None
    share = exact / len(rows) if rows else 0.0
    passed = share >= EXACT_MIN and median is not None and median < MEDIAN_MAX_MS
    details = {"voices": voices, "missing_voices": [v for v in args.voices if v not in voices],
               "median_ms": median, "max_ms": max(lat) if lat else None,
               "misses": [{k: r.get(k) for k in ("said", "transcript", "heard", "why", "error")}
                          for r in rows if not r["exact"]],
               "spent_usd_total": round(meta.spent_usd(), 4)}
    return report("g6", passed,
                  "%d/%d exact (%.0f%%), median %s ms" % (exact, len(rows), 100 * share, median),
                  "%d%% exact, median < %.1f s" % (EXACT_MIN * 100, MEDIAN_MAX_MS / 1000),
                  len(rows), details)


if __name__ == "__main__":
    raise SystemExit(main())
