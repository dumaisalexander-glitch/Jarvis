"""Entraîne le petit modèle « Jarvis » à partir des exemples générés par generate_clips.py.

Le modèle prend les 16 derniers « embeddings » openWakeWord (16 x 96) et donne un score 0..1,
exactement comme hey_jarvis_v0.1.onnx : il se branche donc tel quel dans les apps
(fichier wakeword.onnx).

Usage : python train_jarvis.py DOSSIER_CLIPS DOSSIER_MODELES SORTIE.onnx
(DOSSIER_MODELES contient melspectrogram.onnx et embedding_model.onnx)
"""
import glob
import os
import sys

import numpy as np
import onnxruntime as ort
import soundfile as sf

CLIPS, MODELS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SR = 16000
rng = np.random.default_rng(7)

opts = ort.SessionOptions()
opts.intra_op_num_threads = 2
mel = ort.InferenceSession(os.path.join(MODELS, "melspectrogram.onnx"), opts)
emb = ort.InferenceSession(os.path.join(MODELS, "embedding_model.onnx"), opts)


# ---------------------------------------------------------------- caractéristiques
def embeddings(audio: np.ndarray) -> np.ndarray:
    """Embeddings (N x 96) d'un clip int16. L'embedding i couvre l'audio jusqu'à ~ (76 + 8i) trames de 10 ms."""
    spec = np.squeeze(mel.run(None, {"input": audio.astype(np.float32)[None]})[0]).reshape(-1, 32) / 10 + 2
    wins = [spec[i:i + 76] for i in range(0, spec.shape[0] - 75, 8)]
    if not wins:
        return np.zeros((0, 96), np.float32)
    batch = np.stack(wins)[:, :, :, None].astype(np.float32)
    return emb.run(None, {"input_1": batch})[0].reshape(-1, 96)


def emb_index_for_sample(sample: int) -> int:
    """Indice du premier embedding dont la fenêtre se termine après « sample »."""
    frame = sample / 160  # trames de 10 ms
    return max(0, int(np.ceil((frame - 76) / 8)))


# ---------------------------------------------------------------- augmentation
def background(n: int) -> np.ndarray:
    kind = rng.choice(["white", "pink", "brown", "hum", "quiet"])
    w = rng.normal(0, 1, n)
    if kind == "pink":
        w = np.cumsum(w) * 0.02 + w * 0.5
    elif kind == "brown":  # bruit de route / moteur
        w = np.cumsum(w)
        w -= np.convolve(w, np.ones(400) / 400, mode="same")
    elif kind == "hum":
        t = np.arange(n) / SR
        w = np.sin(2 * np.pi * rng.uniform(50, 180) * t) + 0.3 * w
    w = w / (np.std(w) + 1e-9)
    level = rng.uniform(5, 60) if kind == "quiet" else rng.uniform(40, 900)
    return w * level


def reverb(x: np.ndarray) -> np.ndarray:
    if rng.random() < 0.5:
        return x
    length = int(SR * rng.uniform(0.05, 0.35))
    rir = rng.normal(0, 1, length) * np.exp(-np.arange(length) / (length / rng.uniform(3, 7)))
    rir[0] = 1.0
    y = np.convolve(x, rir)[: len(x)]
    return y / (np.max(np.abs(y)) + 1e-9) * np.max(np.abs(x))


def speed(x: np.ndarray) -> np.ndarray:
    f = rng.uniform(0.9, 1.1)
    idx = np.arange(0, len(x) - 1, f)
    return np.interp(idx, np.arange(len(x)), x)


def augment(speech: np.ndarray, total: int, end_at: int):
    """Place la parole pour qu'elle finisse à « end_at » dans un fond de « total » échantillons."""
    s = speed(reverb(speech.astype(np.float64)))
    s = s * rng.uniform(0.25, 1.6)
    out = background(total)
    start = end_at - len(s)
    a, b = max(0, start), min(total, start + len(s))
    out[a:b] += s[a - start:b - start]
    return np.clip(out, -32768, 32767).astype(np.int16), len(s)


def speech_end(x: np.ndarray) -> int:
    e = np.convolve(np.abs(x.astype(np.float64)), np.ones(320) / 320, mode="same")
    above = np.where(e > 0.08 * e.max())[0]
    return int(above[-1]) if len(above) else len(x)


def trim(x: np.ndarray) -> np.ndarray:
    e = np.convolve(np.abs(x.astype(np.float64)), np.ones(320) / 320, mode="same")
    above = np.where(e > 0.05 * e.max())[0]
    if not len(above):
        return x
    return x[max(0, above[0] - 800): above[-1] + 800]


# ---------------------------------------------------------------- jeu de données
def windows_from(feats: np.ndarray, ends):
    out = []
    for e in ends:
        if 16 <= e <= len(feats):
            out.append(feats[e - 16:e])
    return out


def build(files_pos, files_neg, reps_pos, reps_neg):
    X, y = [], []
    total = int(SR * 3.0)
    for f in files_pos:
        clip = trim(sf.read(f, dtype="int16")[0])
        end = speech_end(clip)
        clip = clip[: end + 400]
        for _ in range(reps_pos):
            end_at = int(rng.uniform(1.7, 2.7) * SR)
            audio, n = augment(clip, total, end_at)
            feats = embeddings(audio)
            k = emb_index_for_sample(end_at)
            # positifs : fenêtres qui se terminent juste après la fin du mot (0 à ~0.3 s)
            for w in windows_from(feats, range(k + 1, k + 5)):
                X.append(w); y.append(1)
            # négatifs difficiles : le mot n'est pas encore fini (début du mot seulement)
            for w in windows_from(feats, range(k - 7, k - 4)):
                X.append(w); y.append(0)
    for f in files_neg:
        clip = trim(sf.read(f, dtype="int16")[0])
        for _ in range(reps_neg):
            tot = max(total, len(clip) + SR)
            audio, _ = augment(clip, tot, int(rng.uniform(len(clip), tot)))
            feats = embeddings(audio)
            for w in windows_from(feats, range(16, len(feats) + 1, 3)):
                X.append(w); y.append(0)
    for _ in range(len(files_neg) // 2 + 20):  # bruit seul
        feats = embeddings(np.clip(background(total), -32768, 32767).astype(np.int16))
        for w in windows_from(feats, range(16, len(feats) + 1, 3)):
            X.append(w); y.append(0)
    return np.array(X, np.float32), np.array(y, np.float32)


# ---------------------------------------------------------------- petit réseau (numpy)
class MLP:
    def __init__(self, d_in=1536, h=96):
        s = lambda a, b: rng.normal(0, np.sqrt(2 / a), (a, b)).astype(np.float32)
        self.p = {"W1": s(d_in, h), "b1": np.zeros(h, np.float32), "W2": s(h, h), "b2": np.zeros(h, np.float32),
                  "W3": s(h, 1), "b3": np.zeros(1, np.float32)}
        self.m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self.t = 0

    def forward(self, x, train=False):
        p = self.p
        z1 = x @ p["W1"] + p["b1"]; a1 = np.maximum(z1, 0)
        if train:
            self.mask = (rng.random(a1.shape) > 0.3) / 0.7
            a1 = a1 * self.mask
        z2 = a1 @ p["W2"] + p["b2"]; a2 = np.maximum(z2, 0)
        z3 = a2 @ p["W3"] + p["b3"]
        self.cache = (x, z1, a1, z2, a2)
        return 1 / (1 + np.exp(-np.clip(z3[:, 0], -30, 30)))

    def step(self, out, y, w, lr=1e-3, l2=1e-4):
        x, z1, a1, z2, a2 = self.cache
        p = self.p
        d3 = ((out - y) * w)[:, None] / len(y)
        g = {"W3": a2.T @ d3, "b3": d3.sum(0)}
        d2 = (d3 @ p["W3"].T) * (z2 > 0)
        g["W2"] = a1.T @ d2; g["b2"] = d2.sum(0)
        d1 = (d2 @ p["W2"].T) * self.mask * (z1 > 0)
        g["W1"] = x.T @ d1; g["b1"] = d1.sum(0)
        self.t += 1
        for k in p:
            if k.startswith("W"):
                g[k] += l2 * p[k]
            self.m[k] = 0.9 * self.m[k] + 0.1 * g[k]
            self.v[k] = 0.999 * self.v[k] + 0.001 * g[k] ** 2
            mh = self.m[k] / (1 - 0.9 ** self.t); vh = self.v[k] / (1 - 0.999 ** self.t)
            p[k] -= lr * mh / (np.sqrt(vh) + 1e-8)


def export_onnx(model: MLP, path: str):
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    p = model.p
    inits = [numpy_helper.from_array(v.astype(np.float32), k) for k, v in p.items()]
    inits.append(numpy_helper.from_array(np.array([1, 1536], np.int64), "shape"))
    nodes = [
        helper.make_node("Reshape", ["x", "shape"], ["flat"]),
        helper.make_node("Gemm", ["flat", "W1", "b1"], ["h1"]), helper.make_node("Relu", ["h1"], ["r1"]),
        helper.make_node("Gemm", ["r1", "W2", "b2"], ["h2"]), helper.make_node("Relu", ["h2"], ["r2"]),
        helper.make_node("Gemm", ["r2", "W3", "b3"], ["h3"]), helper.make_node("Sigmoid", ["h3"], ["score"]),
    ]
    graph = helper.make_graph(nodes, "jarvis", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 16, 96])],
                              [helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])], inits)
    m = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], producer_name="jarvis-loryzon")
    m.ir_version = 8
    onnx.checker.check_model(m)
    onnx.save(m, path)


def is_holdout(f):
    """Clips réalistes (Kokoro) dont le numéro finit par 0 : gardés pour l'évaluation finale."""
    b = os.path.basename(f)
    return not b.startswith("es_") and b[-5] == "0"


if __name__ == "__main__":
    pos = sorted(f for f in glob.glob(os.path.join(CLIPS, "pos", "*.wav")) if not is_holdout(f))
    neg = sorted(f for f in glob.glob(os.path.join(CLIPS, "neg", "*.wav")) if not is_holdout(f))
    rng.shuffle(pos); rng.shuffle(neg)
    vp, vn = max(1, len(pos) // 10), max(1, len(neg) // 10)
    print(f"{len(pos)} positifs, {len(neg)} négatifs", flush=True)
    real = lambda fs: [f for f in fs if not os.path.basename(f).startswith("es_")]
    robot = lambda fs: [f for f in fs if os.path.basename(f).startswith("es_")]
    tr_p, tr_n = pos[vp:], neg[vn:]
    X1, y1 = build(real(tr_p), real(tr_n), reps_pos=8, reps_neg=4)
    X2, y2 = build(robot(tr_p), robot(tr_n), reps_pos=3, reps_neg=1)
    Xtr, ytr = np.concatenate([X1, X2]), np.concatenate([y1, y2])
    Xva, yva = build(pos[:vp], neg[:vn], reps_pos=2, reps_neg=1)
    print(f"entraînement : {int(ytr.sum())} pos / {int((1 - ytr).sum())} nég ; validation : {int(yva.sum())} pos / {int((1 - yva).sum())} nég", flush=True)

    Xtr = Xtr.reshape(len(Xtr), -1); Xva = Xva.reshape(len(Xva), -1)
    model = MLP()
    pos_w = (1 - ytr).sum() / max(1, ytr.sum())
    for epoch in range(int(os.environ.get("EPOCHS", 40))):
        order = rng.permutation(len(Xtr))
        for i in range(0, len(order), 256):
            b = order[i:i + 256]
            out = model.forward(Xtr[b], train=True)
            w = np.where(ytr[b] == 1, pos_w * 0.5, 1.0)  # rater un « Jarvis » est moins grave qu'une fausse alerte
            model.step(out, ytr[b], w, lr=1e-3 if epoch < 25 else 3e-4)
        if epoch % 5 == 4 or epoch == 0:
            pv = model.forward(Xva)
            rappel = (pv[yva == 1] > 0.5).mean()
            fa = (pv[yva == 0] > 0.5).mean()
            print(f"époque {epoch + 1:2d} : détecte {rappel:.1%} des « Jarvis », fausses alertes {fa:.3%} des fenêtres", flush=True)
    export_onnx(model, OUT)
    print("modèle écrit :", OUT)
