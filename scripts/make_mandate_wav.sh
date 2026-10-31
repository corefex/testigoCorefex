#!/bin/sh
# Make a test WAV of Marta's mandate on macOS (F1), for
#   .venv/bin/python -m policy.compile mandate <wav>
#
#   sh scripts/make_mandate_wav.sh                       # → $TMPDIR/mandato.wav
#   sh scripts/make_mandate_wav.sh out.wav "Solo pide con entrega en la tienda, …"
#
# Uses the system voice Paulina (Spanish, Mexico) and converts to 16 kHz mono
# 16-bit WAV, which Voice Transcribe accepts. Audio is never committed
# (check-secrets flags .wav files), so the default lands outside the repo.
set -eu
OUT="${1:-${TMPDIR:-/tmp}/mandato.wav}"
PHRASE="${2:-Solo pide con entrega en la tienda, máximo ciento cincuenta mil pesos por pedido}"
AIFF="${OUT%.wav}.aiff"
say -v Paulina -o "$AIFF" "$PHRASE"
afconvert -f WAVE -d LEI16@16000 -c 1 "$AIFF" "$OUT"
rm -f "$AIFF"
echo "$OUT"
