# Entraînement du mot d'éveil « Jarvis »

Le modèle `wakeword.onnx` des apps a été produit avec ces scripts. Ils ne servent que si tu veux le réentraîner.

1. `generate_clips.py` : voix réalistes (Kokoro, une cinquantaine de voix et leurs mélanges, accents variés) qui disent « Jarvis », plus des phrases ordinaires et des mots qui ressemblent (« Travis », « j'arrive », « service »…). Lent sur un ordinateur ordinaire (environ 10 exemples par minute).
2. `espeak_clips.py` : des milliers d'exemples robotiques en quelques secondes, pour la variété.
3. `train_jarvis.py` : ajoute du bruit (route, moteur, ventilation), de l'écho, change la vitesse et le volume, puis entraîne un petit réseau sur les « embeddings » d'openWakeWord. Sortie : un fichier `.onnx` qui remplace directement `wakeword.onnx`.
4. `eval_wakeword.py` : teste le modèle exactement comme les apps l'utilisent (en continu), sur des voix et des phrases jamais vues : taux de détection et fausses alertes par heure.

```bash
pip install kokoro-onnx soundfile onnxruntime onnx numpy espeakng-loader
# modèles de base : melspectrogram.onnx, embedding_model.onnx (releases openWakeWord v0.5.1)
# voix Kokoro : kokoro-v1.0.int8.onnx, voices-v1.0.bin (releases kokoro-onnx)
python generate_clips.py clips 0 1 1600 900
python espeak_clips.py clips 1500 3000
python train_jarvis.py clips modeles jarvis.onnx
python eval_wakeword.py jarvis.onnx modeles dossier_jarvis_tests dossier_phrases_tests
cp jarvis.onnx ../android/app/src/main/assets/wakeword.onnx
```

**Meilleure amélioration possible** : enregistrer ta propre voix. Une trentaine de « Jarvis » dits avec ton téléphone (dans l'auto, à la maison, fort, doucement), en fichiers WAV 16 kHz dans `clips/pos/`, puis réentraîner. Le modèle apprendra ta façon de le dire.
