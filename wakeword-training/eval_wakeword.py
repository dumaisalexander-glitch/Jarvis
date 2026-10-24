"""Évalue un modèle de mot d'éveil en conditions réelles de flux (même code que les apps).

- Taux de détection : clips « Jarvis » jamais vus, dans plusieurs bruits de fond.
- Fausses alertes : longue suite de phrases jamais vues + bruit, en déclenchements par heure.

Usage : python eval_wakeword.py MODELE.onnx DOSSIER_MODELES DOSSIER_POS DOSSIER_NEG_LONG [SEUIL]
"""
import glob
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "desktop"))
from wakeword import WakeWordDetector  # noqa: E402

MODEL, BASE, POS_DIR, NEG_DIR = sys.argv[1:5]
THRESH = [float(sys.argv[5])] if len(sys.argv) > 5 else [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
rng = np.random.default_rng(3)


def det():
    return WakeWordDetector(os.path.join(BASE, "melspectrogram.onnx"), os.path.join(BASE, "embedding_model.onnx"), MODEL)


def noise(n, level):
    w = np.cumsum(rng.normal(0, 1, n))
    w -= np.convolve(w, np.ones(400) / 400, mode="same")
    w = w / (np.std(w) + 1e-9) * level
    return w


def stream_scores(d, audio):
    """Scores par bloc de 80 ms, en envoyant l'audio par paquets de 40 ms comme le micro."""
    scores = []
    for i in range(0, len(audio), 640):
        scores.append(d.process(audio[i:i + 640]))
    return np.array(scores)


def triggers(scores, th, cooldown_blocks=50):
    n, last = 0, -10 ** 9
    for i, s in enumerate(scores):
        if s >= th and i - last > cooldown_blocks:
            n += 1
            last = i
    return n


pos_files = sorted(glob.glob(os.path.join(POS_DIR, "*.wav")))
pos_best = []
d = det()
for f in pos_files:
    clip = sf.read(f, dtype="int16")[0].astype(np.float64)
    for level in (30, 300, 900):  # calme, auto, bruyant
        d.reset()
        audio = np.concatenate([noise(16000, level), clip + noise(len(clip), level), noise(16000, level)])
        pos_best.append(stream_scores(d, np.clip(audio, -32768, 32767).astype(np.int16)).max())
pos_best = np.array(pos_best)

neg_files = sorted(glob.glob(os.path.join(NEG_DIR, "*.wav")))
parts = []
for f in neg_files:
    parts.append(sf.read(f, dtype="int16")[0].astype(np.float64))
    parts.append(np.zeros(int(16000 * rng.uniform(0.2, 1.0))))
long_audio = np.concatenate(parts)
long_audio = np.clip(long_audio + noise(len(long_audio), 200), -32768, 32767).astype(np.int16)
hours = len(long_audio) / 16000 / 3600
d.reset()
neg_scores = stream_scores(d, long_audio)

print(f"{len(pos_files)} « Jarvis » x 3 bruits ; {len(long_audio) / 16000 / 60:.1f} min de conversation sans « Jarvis »")
for th in THRESH:
    rate = (pos_best >= th).mean()
    fa = triggers(neg_scores, th)
    print(f"seuil {th:.2f} : détecte {rate:6.1%} des « Jarvis » | {fa} fausse(s) alerte(s) = {fa / hours:5.1f} / heure de conversation")
