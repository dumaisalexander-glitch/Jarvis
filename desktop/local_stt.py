"""Transcription sur l'ordinateur avec Whisper (faster-whisper), sans Internet ni clé OpenAI.

Le modèle est téléchargé une seule fois au premier lancement, puis gardé dans
%APPDATA%\\Jarvis\\whisper.
"""
from __future__ import annotations

import os
import threading

import numpy as np

MODELS = {
    "base": "rapide, moins précis (~150 Mo)",
    "small": "bon équilibre (~500 Mo) — recommandé",
    "medium": "très précis mais lent (~1,5 Go)",
}
PROMPT = "Jarvis, LoRyzon, Cricut, impression 3D, gravure laser, cégep, Teams."


class LocalTranscriber:
    def __init__(self, model_size: str, cache_dir: str):
        self.model_size = model_size if model_size in MODELS else "small"
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Charge (et télécharge au besoin) le modèle. Peut prendre quelques minutes la première fois."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            os.makedirs(self.cache_dir, exist_ok=True)
            threads = max(1, min(8, (os.cpu_count() or 4) - 1))
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8",
                                       cpu_threads=threads, download_root=self.cache_dir)

    def transcribe(self, pcm: np.ndarray) -> str:
        """Audio int16 mono 16 kHz -> texte en français."""
        self.load()
        audio = pcm.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language="fr",
            beam_size=2,
            initial_prompt=PROMPT,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
