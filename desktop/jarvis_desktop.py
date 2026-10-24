"""Jarvis pour Windows.

Dis « Jarvis » (ou clique sur le rond, ou Ctrl+Espace dans la fenêtre), parle,
Jarvis transcrit, organise tes projets sur le serveur et te répond à voix haute.
"""
from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import uuid
import webbrowser
from tkinter import messagebox

import numpy as np
import sounddevice as sd

from wakeword import WakeWordDetector

SAMPLE_RATE = 16000
FRAME = 640  # 40 ms
MAX_RECORD_SEC = 60
END_SILENCE_SEC = 1.5
NO_SPEECH_SEC = 7.0

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Jarvis")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DEFAULTS = {
    "server_url": "",
    "token": "",
    "wake_word": True,
    "threshold": 0.5,
    "conversation": True,
    "session_timeout_min": 5,
}

COLORS = {
    "bg": "#0b1218", "panel": "#121c24", "ink": "#e5edf2", "muted": "#8fa1ae",
    "idle": "#1e8caa", "listening": "#ff5252", "thinking": "#ffc43d", "speaking": "#2cc4e6", "off": "#46505a",
}
LABELS = {
    "idle": "Dis « Jarvis » ou clique sur le rond",
    "idle_no_wake": "Clique sur le rond pour parler (Ctrl+Espace)",
    "listening": "Je t'écoute…",
    "thinking": "Je réfléchis…",
    "speaking": "Je réponds…",
    "off": "Micro arrêté",
}


def resource(*parts: str) -> str:
    """Chemin d'un fichier inclus (fonctionne aussi dans le .exe PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, *parts)
    if os.path.exists(path):
        return path
    # en développement : réutilise les modèles de l'app Android
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "android", "app", "src", "main", "assets", parts[-1])


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return {**DEFAULTS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def wav_bytes(pcm: np.ndarray) -> bytes:
    data = pcm.astype("<i2").tobytes()
    header = b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
    header += (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + SAMPLE_RATE.to_bytes(4, "little")
    header += (SAMPLE_RATE * 2).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
    header += b"data" + len(data).to_bytes(4, "little")
    return header + data


# ------------------------------------------------------------------ serveur
class Api:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _call(self, path: str, body: bytes | None, ctype: str | None, session: str = "", method: str = "POST") -> dict:
        req = urllib.request.Request(self.cfg["server_url"].rstrip("/") + path, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self.cfg["token"])
        req.add_header("X-Device", "windows")
        if session:
            req.add_header("X-Session", session)
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=75) as res:
                return json.loads(res.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("erreur")
            except Exception:
                msg = None
            if e.code == 401:
                raise RuntimeError("Mot de passe Jarvis refusé par le serveur.") from e
            raise RuntimeError(msg or f"Erreur du serveur ({e.code})") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Serveur injoignable : {e.reason}") from e

    def converse_audio(self, pcm: np.ndarray, session: str) -> dict:
        return self._call("/api/converse", wav_bytes(pcm), "audio/wav", session)

    def converse_text(self, text: str, session: str) -> dict:
        return self._call("/api/converse", json.dumps({"texte": text}).encode(), "application/json", session)

    def end_session(self, session: str) -> dict:
        return self._call("/api/session-end", json.dumps({"session": session}).encode(), "application/json", session)

    def health(self) -> dict:
        return self._call("/api/health", None, None, method="GET")


# ------------------------------------------------------------------ voix
class Voice:
    """Voix Windows (SAPI) en français si disponible."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.speaking = threading.Event()
        self.stop_flag = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str, on_done=None):
        self.stop_flag.clear()
        self.q.put((text, on_done))

    def stop(self):
        self.stop_flag.set()

    def _run(self):
        voice = None
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            best = None
            for v in voice.GetVoices():
                desc = v.GetDescription()
                if "French" in desc or "Français" in desc or "fran" in desc.lower():
                    if best is None or "Canada" in desc:
                        best = v
            if best is not None:
                voice.Voice = best
            voice.Rate = 1
        except Exception as e:  # pas Windows ou pas de SAPI : on affiche seulement le texte
            print("Voix indisponible :", e)
        while True:
            text, on_done = self.q.get()
            self.speaking.set()
            try:
                if voice is not None:
                    voice.Speak(text, 1)  # asynchrone
                    while not voice.WaitUntilDone(100):
                        if self.stop_flag.is_set():
                            voice.Speak("", 2)  # coupe la parole
                            break
                else:
                    time.sleep(min(6, len(text) / 15))
            finally:
                self.speaking.clear()
                if on_done:
                    on_done()


# ------------------------------------------------------------------ cerveau local
class Jarvis:
    def __init__(self, ui: "App"):
        self.ui = ui
        self.cfg = load_config()
        self.api = Api(self.cfg)
        self.voice = Voice()
        self.phase = "off"
        self.detector: WakeWordDetector | None = None
        self.lock = threading.Lock()
        self.audio_q: queue.Queue = queue.Queue(maxsize=500)
        self.stream = None
        self.session = self._new_session()
        self.turns = 0
        self.last_activity = 0.0
        self.noise_floor = 300.0
        self.cooldown_until = 0.0
        self._reset_recording()
        self.load_detector()
        threading.Thread(target=self._audio_worker, daemon=True).start()
        threading.Thread(target=self._session_watch, daemon=True).start()

    @staticmethod
    def _new_session() -> str:
        return "win_" + uuid.uuid4().hex[:10]

    def configured(self) -> bool:
        return self.cfg["server_url"].startswith("https://") and bool(self.cfg["token"])

    def load_detector(self):
        with self.lock:
            self.detector = None
            if not self.cfg["wake_word"]:
                return
            try:
                self.detector = WakeWordDetector(
                    resource("models", "melspectrogram.onnx"),
                    resource("models", "embedding_model.onnx"),
                    resource("models", "wakeword.onnx"),
                    threshold=float(self.cfg["threshold"]),
                )
            except Exception as e:
                self.ui.message(f"Mot d'éveil indisponible : {e}")

    # -- micro --------------------------------------------------------
    def start_mic(self):
        if self.stream is not None:
            return
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                         blocksize=FRAME, callback=self._on_audio)
            self.stream.start()
            self.go_idle()
        except Exception as e:
            self.stream = None
            self.set_phase("off")
            self.ui.message(f"Impossible d'ouvrir le micro : {e}")

    def stop_mic(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.set_phase("off")

    def _on_audio(self, indata, frames, t, status):
        try:
            self.audio_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _audio_worker(self):
        while True:
            buf = self.audio_q.get()
            level = float(np.sqrt(np.mean(buf.astype(np.float64) ** 2))) if len(buf) else 0.0
            phase = self.phase
            if phase in ("idle", "idle_no_wake"):
                self.noise_floor = self.noise_floor * 0.98 + level * 0.02
                with self.lock:
                    d = self.detector
                    score = d.process(buf) if d else 0.0
                if d and score >= float(self.cfg["threshold"]) and time.time() > self.cooldown_until:
                    self.cooldown_until = time.time() + 2
                    self.ui.later(self.start_listening)
            elif phase == "listening":
                self.ui.level(min(1.0, level / 4000))
                self.listened += len(buf)
                if self.listened < SAMPLE_RATE * 0.3:
                    continue  # ignore le bip de départ
                if self.rec_len + len(buf) <= len(self.rec):
                    self.rec[self.rec_len:self.rec_len + len(buf)] = buf
                    self.rec_len += len(buf)
                if level > max(self.noise_floor * 2.5, 450):
                    self.speech_heard = True
                    self.silent = 0
                else:
                    self.silent += len(buf)
                if (self.speech_heard and self.silent > SAMPLE_RATE * END_SILENCE_SEC) or \
                        (not self.speech_heard and self.listened > SAMPLE_RATE * NO_SPEECH_SEC) or \
                        self.rec_len + FRAME > len(self.rec):
                    self.ui.later(self.finish_listening)

    def _reset_recording(self):
        self.rec = np.zeros(SAMPLE_RATE * MAX_RECORD_SEC, dtype=np.int16)
        self.rec_len = 0
        self.speech_heard = False
        self.silent = 0
        self.listened = 0

    # -- états (toujours appelés sur le fil de l'interface) ------------
    def set_phase(self, p: str):
        self.phase = p
        self.ui.show_phase(p)

    def go_idle(self):
        if self.stream is None:
            self.set_phase("off")
            return
        with self.lock:
            if self.detector:
                self.detector.reset()
        self.set_phase("idle" if self.detector else "idle_no_wake")

    def talk_pressed(self):
        if not self.configured():
            self.ui.open_settings()
            return
        if self.stream is None:
            self.start_mic()
        if self.phase == "listening":
            self.finish_listening()
        elif self.phase == "speaking":
            self.voice.stop()
            self.ui.after(300, self.start_listening)
        elif self.phase != "thinking":
            self.start_listening()

    def start_listening(self):
        if not self.configured():
            self.ui.open_settings()
            return
        if self.phase in ("listening", "thinking"):
            return
        self._reset_recording()
        beep(880, 0.12)
        self.set_phase("listening")

    def finish_listening(self):
        if self.phase != "listening":
            return
        if not self.speech_heard or self.rec_len < SAMPLE_RATE // 2:
            beep(330, 0.12)
            self.go_idle()
            return
        beep(1320, 0.08)
        self.set_phase("thinking")
        audio = self.rec[:self.rec_len].copy()
        threading.Thread(target=self._send, args=(audio, None), daemon=True).start()

    def send_text(self, text: str):
        if not self.configured():
            self.ui.open_settings()
            return
        self.set_phase("thinking")
        threading.Thread(target=self._send, args=(None, text), daemon=True).start()

    def _send(self, audio, text):
        session = self.session
        try:
            r = self.api.converse_audio(audio, session) if audio is not None else self.api.converse_text(text, session)
            self.ui.later(lambda: self._on_reply(r, spoken=audio is not None))
        except Exception as e:
            msg = str(e)
            self.ui.later(lambda: (self.ui.message(msg), self._speak("Désolé, je n'arrive pas à joindre le serveur.", False)))

    def _on_reply(self, r: dict, spoken: bool):
        self.turns += 1
        self.last_activity = time.time()
        self.ui.show_reply(r.get("transcription", ""), r.get("reponse", ""), r.get("changements") or [])
        if r.get("finSession"):
            self.session = self._new_session()
            self.turns = 0
            teams = r.get("teams") or {}
            self.ui.message("Résumé envoyé dans Teams." if teams.get("envoye") else "Session terminée.")
            self._speak(r.get("reponse", ""), False)
        else:
            self._speak(r.get("reponse", ""), spoken and self.cfg["conversation"])

    def _speak(self, text: str, listen_after: bool):
        self.set_phase("speaking")

        def done():
            def after():
                if self.phase != "speaking":
                    return
                if listen_after and self.stream is not None:
                    self.set_phase("thinking")
                    self.ui.after(350, self.start_listening)
                else:
                    self.go_idle()
            self.ui.later(after)

        self.voice.say(text, done)

    # -- session -------------------------------------------------------
    def end_session(self, spoken: bool = True):
        if self.turns == 0:
            if spoken:
                self.ui.message("Il n'y a rien à résumer pour l'instant.")
            return
        session, self.session, self.turns = self.session, self._new_session(), 0

        def work():
            try:
                r = self.api.end_session(session)
                teams = r.get("teams") or {}
                msg = "Résumé envoyé dans Teams." if teams.get("envoye") else f"Résumé enregistré ({teams.get('raison', '')})."
            except Exception as e:
                msg = f"Résumé impossible : {e}"
            self.ui.later(lambda: self.ui.message(msg))

        threading.Thread(target=work, daemon=True).start()

    def _session_watch(self):
        while True:
            time.sleep(15)
            idle_for = time.time() - self.last_activity
            if self.turns > 0 and self.phase in ("idle", "idle_no_wake", "off") and \
                    idle_for > 60 * int(self.cfg["session_timeout_min"]):
                self.ui.later(lambda: self.end_session(spoken=False))

    def shutdown(self):
        if self.turns > 0:
            try:
                self.api.end_session(self.session)
            except Exception:
                pass
        self.stop_mic()


def beep(freq: float, dur: float):
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(int(freq), int(dur * 1000)), daemon=True).start()
    except Exception:
        pass


# ------------------------------------------------------------------ interface
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jarvis")
        self.geometry("460x680")
        self.minsize(380, 560)
        self.configure(bg=COLORS["bg"])
        self.phase = "off"
        self._level = 0.0
        self._shown = 0.0
        self._t0 = time.time()
        self._build()
        self.jarvis = Jarvis(self)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.bind("<Control-space>", lambda e: self.jarvis.talk_pressed())
        if self.jarvis.configured():
            self.jarvis.start_mic()
        else:
            self.after(300, self.open_settings)
        self._animate()

    # -- appels sûrs depuis d'autres fils --
    def later(self, fn):
        self.after(0, fn)

    def level(self, v: float):
        self._level = v

    def message(self, text: str):
        self.later(lambda: self.msg.config(text=text))

    def show_phase(self, p: str):
        self.phase = p
        self.status.config(text=LABELS.get(p, p))
        self.mic_btn.config(text="Couper le micro" if p != "off" else "Activer le micro")

    def show_reply(self, transcript: str, reply: str, changes: list):
        self.transcript.config(text=f"Toi : {transcript}" if transcript else "")
        self.reply.config(text=reply)
        self.changes.config(text="\n".join("✔ " + c for c in changes))

    # -- construction --
    def _build(self):
        c = COLORS
        top = tk.Frame(self, bg=c["bg"])
        top.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(top, text="JARVIS", fg="#9beafb", bg=c["bg"], font=("Segoe UI", 16, "bold")).pack(side="left")
        for label, cmd in (("Réglages", self.open_settings), ("Mes projets", self.open_projects)):
            tk.Button(top, text=label, command=cmd, fg="#9beafb", bg=c["bg"], activebackground=c["panel"],
                      activeforeground="#9beafb", relief="flat", bd=0, cursor="hand2",
                      font=("Segoe UI", 10)).pack(side="right", padx=4)

        self.canvas = tk.Canvas(self, width=300, height=260, bg=c["bg"], highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="x", pady=(6, 0))
        self.canvas.bind("<Button-1>", lambda e: self.jarvis.talk_pressed())

        self.status = tk.Label(self, text="", fg=c["ink"], bg=c["bg"], font=("Segoe UI", 15, "bold"))
        self.status.pack(pady=(0, 8))

        box = tk.Frame(self, bg=c["bg"])
        box.pack(fill="both", expand=True, padx=18)
        wrap = 410
        self.transcript = tk.Label(box, text="", fg=c["muted"], bg=c["bg"], font=("Segoe UI", 10), wraplength=wrap, justify="left", anchor="w")
        self.reply = tk.Label(box, text="", fg=c["ink"], bg=c["bg"], font=("Segoe UI", 12), wraplength=wrap, justify="left", anchor="w")
        self.changes = tk.Label(box, text="", fg=c["speaking"], bg=c["bg"], font=("Segoe UI", 10), wraplength=wrap, justify="left", anchor="w")
        self.msg = tk.Label(box, text="", fg=c["thinking"], bg=c["bg"], font=("Segoe UI", 10), wraplength=wrap, justify="left", anchor="w")
        for w in (self.transcript, self.reply, self.changes, self.msg):
            w.pack(fill="x", pady=3)
        self.bind("<Configure>", lambda e: [w.config(wraplength=max(250, self.winfo_width() - 50))
                                            for w in (self.transcript, self.reply, self.changes, self.msg)])

        entry_row = tk.Frame(self, bg=c["bg"])
        entry_row.pack(fill="x", padx=16, pady=(6, 6))
        self.entry = tk.Entry(entry_row, bg=c["panel"], fg=c["ink"], insertbackground=c["ink"], relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 6))
        self.entry.bind("<Return>", self._send_entry)
        tk.Button(entry_row, text="Écrire", command=self._send_entry, bg=c["idle"], fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="right", ipadx=10, ipady=4)

        bottom = tk.Frame(self, bg=c["bg"])
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(bottom, text="Terminer la session", command=lambda: self.jarvis.end_session(True), bg=c["panel"], fg=c["ink"],
                  relief="flat", font=("Segoe UI", 10), cursor="hand2").pack(side="left", expand=True, fill="x", padx=(0, 4), ipady=8)
        self.mic_btn = tk.Button(bottom, text="Couper le micro", command=self._toggle_mic, bg=c["panel"], fg=c["ink"],
                                 relief="flat", font=("Segoe UI", 10), cursor="hand2")
        self.mic_btn.pack(side="left", expand=True, fill="x", padx=(4, 0), ipady=8)

    def _send_entry(self, *_):
        t = self.entry.get().strip()
        if t:
            self.entry.delete(0, "end")
            self.jarvis.send_text(t)

    def _toggle_mic(self):
        if self.jarvis.stream is None:
            self.jarvis.start_mic()
        else:
            self.jarvis.stop_mic()

    def _animate(self):
        cv = self.canvas
        cv.delete("all")
        w = cv.winfo_width() or 300
        h = cv.winfo_height() or 260
        cx, cy, r = w / 2, h / 2, min(w, h) * 0.32
        t = time.time() - self._t0
        self._shown += (self._level - self._shown) * 0.3
        p = self.phase
        pulse = {"listening": 0.06 + self._shown * 0.25, "thinking": 0.04 * math.sin(t * 6),
                 "speaking": 0.05 * math.sin(t * 9), "off": 0.0}.get(p, 0.02 * math.sin(t * 1.5))
        col = COLORS.get({"idle_no_wake": "idle"}.get(p, p), COLORS["idle"])
        for i, a in enumerate((0.18, 0.10, 0.05)):
            rr = r * (1.15 + i * 0.15 + pulse)
            cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=_mix(col, COLORS["bg"], a), width=6)
        rr = r * (1 + pulse)
        cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=col, outline="")
        rr = r * 0.72
        cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=COLORS["bg"], outline="")
        rr = r * (0.38 + pulse * 0.8)
        cv.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=_mix("#ffffff", col, 0.45), outline="")
        self.after(33, self._animate)

    # -- fenêtres --
    def open_projects(self):
        url = self.jarvis.cfg["server_url"]
        if url:
            webbrowser.open(url.rstrip("/") + "/")
        else:
            self.open_settings()

    def open_settings(self):
        Settings(self)

    def _quit(self):
        self.jarvis.shutdown()
        self.destroy()


def _mix(a: str, b: str, ratio: float) -> str:
    """Mélange deux couleurs (ratio de a)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * ratio + y * (1 - ratio)):02x}" for x, y in zip(ca, cb))


class Settings(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Réglages de Jarvis")
        self.configure(bg=COLORS["bg"], padx=18, pady=14)
        self.resizable(False, False)
        cfg = app.jarvis.cfg
        c = COLORS

        def label(t):
            tk.Label(self, text=t, fg=c["muted"], bg=c["bg"], font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(10, 2))

        def entry(value, show=None):
            e = tk.Entry(self, width=48, bg=c["panel"], fg=c["ink"], insertbackground=c["ink"], relief="flat", show=show)
            e.insert(0, value)
            e.pack(fill="x", ipady=5)
            return e

        label("Adresse du serveur Jarvis (Vercel)")
        self.url = entry(cfg["server_url"])
        label("Mot de passe Jarvis (JARVIS_TOKEN)")
        self.token = entry(cfg["token"], show="•")

        self.wake = tk.BooleanVar(value=cfg["wake_word"])
        self.convo = tk.BooleanVar(value=cfg["conversation"])
        for text, var in (("Écouter « Jarvis » en continu", self.wake),
                          ("Mode conversation (réécoute après la réponse)", self.convo)):
            tk.Checkbutton(self, text=text, variable=var, fg=c["ink"], bg=c["bg"], selectcolor=c["panel"],
                           activebackground=c["bg"], activeforeground=c["ink"], anchor="w").pack(fill="x", pady=(10, 0))

        label("Seuil du mot d'éveil (plus bas = réagit plus facilement)")
        self.threshold = tk.Scale(self, from_=0.1, to=0.9, resolution=0.05, orient="horizontal", bg=c["bg"], fg=c["ink"],
                                  highlightthickness=0, troughcolor=c["panel"])
        self.threshold.set(cfg["threshold"])
        self.threshold.pack(fill="x")

        label("Minutes de silence avant d'envoyer le résumé dans Teams")
        self.timeout = entry(str(cfg["session_timeout_min"]))

        self.result = tk.Label(self, text="", fg=c["thinking"], bg=c["bg"], wraplength=380, justify="left")
        row = tk.Frame(self, bg=c["bg"])
        row.pack(fill="x", pady=(16, 4))
        tk.Button(row, text="Tester la connexion", command=self.test, bg=c["panel"], fg=c["ink"], relief="flat").pack(side="left", ipadx=8, ipady=4)
        tk.Button(row, text="Enregistrer", command=self.save, bg=c["idle"], fg="white", relief="flat").pack(side="right", ipadx=12, ipady=4)
        self.result.pack(fill="x", pady=(6, 0))
        self.grab_set()

    def _apply(self):
        cfg = self.app.jarvis.cfg
        cfg["server_url"] = self.url.get().strip().rstrip("/")
        cfg["token"] = self.token.get().strip()
        cfg["wake_word"] = bool(self.wake.get())
        cfg["conversation"] = bool(self.convo.get())
        cfg["threshold"] = float(self.threshold.get())
        try:
            cfg["session_timeout_min"] = max(1, min(120, int(self.timeout.get())))
        except ValueError:
            cfg["session_timeout_min"] = 5

    def test(self):
        self._apply()
        self.result.config(text="Test en cours…")

        def work():
            try:
                h = self.app.jarvis.api.health()
                manque = [n for k, n in (("whisper", "clé Whisper"), ("claude", "clé Claude"),
                                         ("base_de_donnees", "base de données"), ("teams", "Teams")) if not h.get(k)]
                msg = f"✔ Tout est prêt (modèle {h.get('modele')})." if not manque else \
                    "Connecté, mais il manque sur Vercel : " + ", ".join(manque) + "."
            except Exception as e:
                msg = f"✘ {e}"
            self.app.later(lambda: self.result.config(text=msg))

        threading.Thread(target=work, daemon=True).start()

    def save(self):
        self._apply()
        if not self.app.jarvis.configured():
            messagebox.showwarning("Jarvis", "L'adresse doit commencer par https:// et le mot de passe est requis.", parent=self)
            return
        save_config(self.app.jarvis.cfg)
        self.app.jarvis.load_detector()
        if self.app.jarvis.stream is None:
            self.app.jarvis.start_mic()
        else:
            self.app.jarvis.go_idle()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
