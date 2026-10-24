"""Détecteur de mot d'éveil basé sur les modèles openWakeWord (ONNX).

Même pipeline que l'app Android (WakeWordDetector.kt) :
audio 16 kHz int16 -> blocs de 1280 échantillons (80 ms)
-> melspectrogram.onnx (x/10 + 2) -> fenêtres de 76 trames
-> embedding_model.onnx (96 valeurs) -> 16 dernières -> modèle du mot (score 0..1).
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort

CHUNK = 1280            # 80 ms à 16 kHz
MEL_CONTEXT = 160 * 3   # échantillons de contexte en plus pour le mel
MEL_WINDOW = 76
N_FEATURES = 16


class WakeWordDetector:
    def __init__(self, mel_path: str, embed_path: str, word_path: str, threshold: float = 0.85):
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self.mel = ort.InferenceSession(mel_path, opts, providers=["CPUExecutionProvider"])
        self.emb = ort.InferenceSession(embed_path, opts, providers=["CPUExecutionProvider"])
        self.word = ort.InferenceSession(word_path, opts, providers=["CPUExecutionProvider"])
        self.mel_in = self.mel.get_inputs()[0].name
        self.emb_in = self.emb.get_inputs()[0].name
        self.word_in = self.word.get_inputs()[0].name
        self.threshold = threshold
        self.reset()

    # -- état -----------------------------------------------------------
    def reset(self) -> None:
        self.raw = np.zeros(0, dtype=np.int16)          # audio pas encore traité
        self.history = np.zeros(MEL_CONTEXT, dtype=np.int16)  # contexte pour le mel
        self.mels = np.ones((MEL_WINDOW, 32), dtype=np.float32)
        noise = np.random.randint(-1000, 1000, 16000 * 4).astype(np.int16)
        self.features = self._embeddings_of(noise)
        self.chunks_seen = 0
        self.prev_score = 0.0

    def _melspec(self, audio: np.ndarray) -> np.ndarray:
        x = audio.astype(np.float32)[None, :]
        out = self.mel.run(None, {self.mel_in: x})[0]
        return np.squeeze(out).reshape(-1, 32) / 10.0 + 2.0

    def _embed(self, window: np.ndarray) -> np.ndarray:
        x = window.astype(np.float32)[None, :, :, None]
        return self.emb.run(None, {self.emb_in: x})[0].reshape(-1, 96)

    def _embeddings_of(self, audio: np.ndarray) -> np.ndarray:
        spec = self._melspec(audio)
        rows = [self._embed(spec[i:i + MEL_WINDOW]) for i in range(0, spec.shape[0] - MEL_WINDOW + 1, 8)]
        return np.vstack(rows)

    # -- flux -----------------------------------------------------------
    def process(self, pcm: np.ndarray) -> float:
        """Ajoute de l'audio int16 mono 16 kHz. Retourne le meilleur score « confirmé » du paquet :
        le plus petit des scores de deux blocs de 80 ms consécutifs (évite les déclenchements sur un seul pic)."""
        self.raw = np.concatenate((self.raw, pcm.astype(np.int16)))
        best = 0.0
        while self.raw.shape[0] >= CHUNK:
            chunk, self.raw = self.raw[:CHUNK], self.raw[CHUNK:]
            score = self._process_chunk(chunk)
            best = max(best, min(score, self.prev_score))
            self.prev_score = score
        return best

    def _process_chunk(self, chunk: np.ndarray) -> float:
        audio = np.concatenate((self.history, chunk))
        self.history = audio[-MEL_CONTEXT:]
        self.mels = np.vstack((self.mels, self._melspec(audio)))[-970:]
        self.features = np.vstack((self.features, self._embed(self.mels[-MEL_WINDOW:])))[-120:]
        self.chunks_seen += 1
        if self.chunks_seen < 5:   # comme openWakeWord : ignorer le tout début
            return 0.0
        x = self.features[-N_FEATURES:][None, :, :].astype(np.float32)
        return float(np.squeeze(self.word.run(None, {self.word_in: x})[0]))

    def detected(self, pcm: np.ndarray) -> bool:
        return self.process(pcm) >= self.threshold
