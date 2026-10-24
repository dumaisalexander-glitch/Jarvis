"""Exemples supplémentaires très rapides avec eSpeak NG (voix robotiques mais très variées :
hauteur, vitesse, accents). Complète les voix réalistes de generate_clips.py.

Usage : python espeak_clips.py SORTIE NB_POS NB_NEG
"""
import ctypes
import os
import random
import sys
import wave

import espeakng_loader
import numpy as np

OUT, NPOS, NNEG = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
HERE = os.path.dirname(os.path.abspath(__file__))
rng = random.Random(99)

lib = ctypes.CDLL(espeakng_loader.get_library_path())
CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
lib.espeak_Initialize.restype = ctypes.c_int
lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
lib.espeak_SetSynthCallback.argtypes = [CB]
lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                             ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
SR = lib.espeak_Initialize(1, 0, espeakng_loader.get_data_path().encode(), 0)  # 1 = AUDIO_OUTPUT_RETRIEVAL

chunks = []


@CB
def on_audio(wav, n, events):
    if n > 0:
        chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
    return 0


lib.espeak_SetSynthCallback(on_audio)

LANGS = ["en-us", "en", "fr-fr", "fr-be", "es", "it", "pt-br", "de"]
VARIANTS = [""] + [f"+m{i}" for i in range(1, 8)] + [f"+f{i}" for i in range(1, 5)]
POS = ["Jarvis", "Jarvis.", "Jarvis!", "Jarvis?", "Jarvis,"]
with open(os.environ.get("NEG_FILE", os.path.join(HERE, "negative_phrases.txt")), encoding="utf-8") as f:
    NEG = [l.strip() for l in f if l.strip() and not l.startswith("#")]


def synth(text, lang, path):
    chunks.clear()
    lib.espeak_SetVoiceByName((lang + rng.choice(VARIANTS)).encode())
    lib.espeak_SetParameter(1, rng.randint(110, 230), 0)   # vitesse
    lib.espeak_SetParameter(3, rng.randint(15, 85), 0)     # hauteur
    lib.espeak_SetParameter(4, rng.randint(10, 90), 0)     # intonation
    data = text.encode("utf-8")
    lib.espeak_Synth(data, len(data) + 1, 0, 0, 0, 0x10, None, None)  # 0x10 = espeakCHARS_UTF8
    lib.espeak_Synchronize()
    if not chunks:
        return False
    audio = np.concatenate(chunks).astype(np.float64)
    # rééchantillonnage vers 16 kHz
    idx = np.arange(0, len(audio) - 1, SR / 16000)
    audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(audio.tobytes())
    return True


for kind, n in (("pos", NPOS), ("neg", NNEG)):
    os.makedirs(os.path.join(OUT, kind), exist_ok=True)
    for i in range(n):
        if kind == "pos":
            lang = rng.choice(LANGS)
            text = rng.choice(POS)
        else:
            lang = rng.choice(["fr-fr"] * 3 + ["en-us", "en"])
            text = rng.choice(NEG)
        synth(text, lang, os.path.join(OUT, kind, f"es{os.environ.get('PREFIX', '')}_{kind}_{i:05d}.wav"))
print("terminé")
