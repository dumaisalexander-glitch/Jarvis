"""Génère des exemples synthétiques pour entraîner le mot d'éveil « Jarvis ».

Positifs : « Jarvis » prononcé par des dizaines de voix (et mélanges de voix),
avec accents anglais, français, espagnol, italien, portugais, à différentes vitesses.
Négatifs : phrases ordinaires en français/anglais + mots qui ressemblent (« Travis », « j'arrive »...).

Usage : python generate_clips.py SORTIE SHARD NB_SHARDS NB_POS NB_NEG
"""
import os
import random
import subprocess
import sys

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.abspath(__file__))
OUT, SHARD, NSHARDS, NPOS, NNEG = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
MODEL_DIR = os.environ.get("KOKORO_DIR", ".")

rng = random.Random(1000 + SHARD)
k = Kokoro(os.path.join(MODEL_DIR, "kokoro-v1.0.int8.onnx"), os.path.join(MODEL_DIR, "voices-v1.0.bin"))
VOICES = sorted(k.get_voices())
# langues de phonétisation -> donne des accents variés
LANG_VOICES = {
    "en-us": [v for v in VOICES if v[0] == "a"],
    "en-gb": [v for v in VOICES if v[0] == "b"],
    "fr-fr": [v for v in VOICES if v[0] in "fab"],
    "es": [v for v in VOICES if v[0] in "ea"],
    "it": [v for v in VOICES if v[0] in "ia"],
    "pt-br": [v for v in VOICES if v[0] in "pa"],
}
POS_LANGS = ["en-us"] * 4 + ["en-gb"] * 2 + ["fr-fr"] * 4 + ["es", "it", "pt-br"]

POS_TEXT = ["Jarvis", "Jarvis.", "Jarvis!", "Jarvis?", "Jarvis,", "Jarvis...", "Jarvis !"]

with open(os.path.join(HERE, "negative_phrases.txt"), encoding="utf-8") as f:
    NEG = [l.strip() for l in f if l.strip() and not l.startswith("#")]


def voice_style(lang):
    pool = LANG_VOICES[lang] or VOICES
    a = rng.choice(pool)
    if rng.random() < 0.5:  # mélange de deux voix = nouvelle voix
        b = rng.choice(VOICES)
        w = rng.uniform(0.2, 0.8)
        return k.get_voice_style(a) * w + k.get_voice_style(b) * (1 - w), f"{a}+{b}"
    return k.get_voice_style(a), a


def synth(text, lang, path):
    style, _ = voice_style(lang)
    samples, sr = k.create(text, voice=style, speed=rng.uniform(0.75, 1.3), lang=lang)
    tmp = path + ".tmp.wav"
    sf.write(tmp, samples, sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-ar", "16000", "-ac", "1",
                    "-sample_fmt", "s16", path], check=True)
    os.remove(tmp)


os.makedirs(os.path.join(OUT, "pos"), exist_ok=True)
os.makedirs(os.path.join(OUT, "neg"), exist_ok=True)
jobs = [("pos", i) for i in range(NPOS)] + [("neg", i) for i in range(NNEG)]
rng.shuffle(jobs)
for kind, i in jobs:
    if i % NSHARDS != SHARD:
        continue
    path = os.path.join(OUT, kind, f"{kind}_{i:05d}.wav")
    if os.path.exists(path):
        continue
    try:
        if kind == "pos":
            lang = rng.choice(POS_LANGS)
            # « Jarvis » seul : la fin de la parole = la fin du mot (sert à étiqueter)
            text = rng.choice(POS_TEXT)
        else:
            lang = rng.choice(["fr-fr"] * 3 + ["en-us", "en-gb"])
            text = rng.choice(NEG)
        synth(text, lang, path)
        with open(path + ".txt", "w", encoding="utf-8") as f:
            f.write(f"{lang}\t{text}\n")
    except Exception as e:  # une phrase qui ne passe pas ne doit pas tout arrêter
        print("échec", kind, i, e, flush=True)
print("terminé shard", SHARD, flush=True)
