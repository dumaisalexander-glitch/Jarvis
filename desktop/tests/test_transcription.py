"""Vérifie que Whisper local transcrit bien le français (lancé par GitHub Actions)."""
import os
import sys
import tempfile
import time
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from local_stt import LocalTranscriber  # noqa: E402

with wave.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "exemple_fr.wav")) as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

stt = LocalTranscriber(os.environ.get("MODELE", "small"), os.path.join(tempfile.gettempdir(), "whisper-test"))
t = time.time()
stt.load()
print(f"modèle chargé en {time.time() - t:.0f} s")
t = time.time()
text = stt.transcribe(pcm)
print(f"transcrit en {time.time() - t:.1f} s : {text}")
low = text.lower()
assert "tâche" in low or "tache" in low, text
assert "filament" in low, text
print("OK")
