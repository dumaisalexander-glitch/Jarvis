# Jarvis

Ton assistant vocal pour faire avancer tes projets (École, LoRyzon, Perso) dans l'auto, à la maison ou à l'école.
Tu dis **« Jarvis »**, tu parles, Whisper transcrit, Claude organise tes projets avec toi et te répond à voix haute.
Le résumé de chaque session arrive dans **Teams**, et tout est rangé dans ton **tableau de projets**.

```
 Téléphone Android ─┐                       ┌─ Whisper (transcription)
                    ├──►  Serveur Jarvis  ──┼─ Claude (réflexion, organisation)
 Ordinateur Windows ┘     (Vercel)          ├─ Base de données (tes projets)
 Tableau web (n'importe où) ───┘            └─ Teams (résumés de session)
```

| Dossier | Contenu |
|---|---|
| `server/` | Le cerveau, sur Vercel : API + tableau de projets web |
| `android/` | L'app Android (mot d'éveil, gros bouton, voix) |
| `desktop/` | Le programme Windows (même chose + champ pour écrire) |
| `wakeword-training/` | Les scripts qui ont servi à entraîner le mot « Jarvis » |

---

## Mise en route (environ 30 minutes, une seule fois)

### 1. Obtenir les deux clés d'API

- **Whisper (OpenAI)** : sur <https://platform.openai.com/api-keys>, crée une clé (commence par `sk-`). Ajoute quelques dollars de crédit dans *Billing*.
- **Claude (Anthropic)** : sur <https://console.anthropic.com/settings/keys>, crée une clé (commence par `sk-ant-`). Ajoute aussi un peu de crédit.

> Coût : c'est à l'usage. Une session normale de quelques minutes coûte quelques sous. Tu peux mettre une limite de dépense mensuelle dans chaque console.

### 2. Créer le lien Teams (pour recevoir les résumés)

1. Dans Teams, ouvre l'app **Workflows** (menu *Applications*).
2. Cherche le modèle **« Send webhook alerts to a chat »** (en français : *Envoyer des alertes webhook à une conversation*).
3. Choisis la conversation où recevoir les résumés. Prends ta conversation avec toi-même si elle est proposée ; sinon, les résumés arrivent dans la conversation avec le bot *Workflows*.
4. Clique **Enregistrer**, puis **copie l'adresse du webhook** affichée.

> Si ton compte Teams est géré par l'école, l'app Workflows peut être bloquée. Dans ce cas Jarvis fonctionne quand même : les résumés restent dans l'onglet **Journal** du tableau.

### 3. Mettre le serveur en ligne sur Vercel

1. Sur <https://vercel.com/new>, importe ce dépôt GitHub (`Jarvis`).
2. Dans **Root Directory**, choisis **`server`**. Laisse le reste par défaut et clique **Deploy**.
3. Dans le projet Vercel, onglet **Storage** → **Create Database** → **Upstash for Redis** (gratuit) → connecte-la au projet. Ça ajoute tout seul les variables de la base de données.
4. Onglet **Settings → Environment Variables**, ajoute :

| Nom | Valeur |
|---|---|
| `JARVIS_TOKEN` | Un mot de passe long que tu inventes (il sert pour l'app, le programme et le tableau) |
| `OPENAI_API_KEY` | Ta clé OpenAI (`sk-...`) |
| `ANTHROPIC_API_KEY` | Ta clé Claude (`sk-ant-...`) |
| `TEAMS_WEBHOOK_URL` | L'adresse copiée à l'étape 2 |
| `CLAUDE_MODEL` *(optionnel)* | `claude-sonnet-5-5` par défaut. `claude-haiku-5-5` = plus rapide et moins cher |

5. Onglet **Deployments** → sur le dernier déploiement, **⋯ → Redeploy** (pour prendre les variables en compte).
6. Ouvre l'adresse de ton projet (ex. `https://jarvis-xxxx.vercel.app`) : le tableau te demande ton mot de passe. 🎉

> Projet Vercel **séparé** de loryzon.com : rien ne touche à ton site.

### 4. Installer l'app Android

1. Sur ton téléphone, va dans ton dépôt GitHub → **Releases** → **Jarvis Android (dernière version)** → télécharge **`Jarvis.apk`**.
2. Ouvre le fichier. Android va demander d'autoriser l'installation depuis ton navigateur : accepte.
3. Ouvre Jarvis → **Réglages** : colle l'adresse Vercel et ton `JARVIS_TOKEN` → **Tester la connexion** → **Enregistrer**.
4. Accepte la permission du **micro** (et des notifications).

Les mises à jour s'installent par-dessus l'ancienne version (même clé de signature).

### 5. Installer le programme Windows

1. Dans **Releases** → **Jarvis Windows (dernière version)**, télécharge **`Jarvis.exe`**.
2. Lance-le. Windows SmartScreen peut afficher « Windows a protégé votre ordinateur » (le programme n'est pas signé par un éditeur payant) : **Informations complémentaires → Exécuter quand même**.
3. **Réglages** : même adresse et même mot de passe.
4. Pour une voix québécoise : *Paramètres Windows → Heure et langue → Voix* → ajoute **Français (Canada)**. Jarvis la choisit automatiquement.

---

## Utilisation

- **« Jarvis »** (ou toucher le rond, ou **Ctrl+Espace** sur l'ordi) → un bip → tu parles → Jarvis s'arrête tout seul quand tu te tais.
- **Mode conversation** : après sa réponse, Jarvis réécoute tout de suite. Pas besoin de redire son nom.
- Pour finir : dis **« c'est tout, Jarvis »**, ou appuie sur **Terminer la session**. Sinon, après 5 minutes sans parler, le résumé part dans Teams tout seul.
- Le tableau web (bouton **Projets**) marche aussi au cégep sur n'importe quel ordi : cocher des tâches, en ajouter, écrire à Jarvis.

**Exemples :**
- « Jarvis, nouveau projet pour l'école : dissertation de français pour le 6 novembre. »
- « J'ai une idée de produit LoRyzon : des porte-clés gravés au laser pour les équipes de hockey. »
- « Où j'en suis dans mes projets? Qu'est-ce qui est le plus urgent? »
- « J'ai fini le plan de la dissertation. »

**Dans l'auto** : Jarvis ne te demande jamais de regarder l'écran. Pose le téléphone sur un support et laisse l'écran allumé, ou éteins-le : Jarvis continue d'écouter en arrière-plan (notification « Jarvis »). La voix passe par les haut-parleurs de l'auto si le téléphone y est connecté en Bluetooth.

---

## Le mot d'éveil « Jarvis »

Le mot d'éveil fonctionne **sur l'appareil** : rien n'est envoyé sur Internet tant que tu n'as pas dit « Jarvis ».
Le modèle (`wakeword.onnx`) a été entraîné spécialement pour « Jarvis » seul, avec des milliers d'exemples de voix synthétiques (accents anglais, français, etc.).

- S'il **ne réagit pas assez** : baisse le seuil dans les Réglages (ex. 0,35).
- S'il **se déclenche tout seul** : monte le seuil (ex. 0,65).

Pour le réentraîner plus tard avec plus d'exemples, voir `wakeword-training/`.

Basé sur [openWakeWord](https://github.com/dscripka/openWakeWord) (code Apache 2.0 ; les modèles de base sont pour usage non commercial, parfait pour un assistant personnel).

---

## Pour aller plus loin

- **Haut-parleur maison** : un Raspberry Pi avec un micro peut faire tourner `desktop/` presque tel quel et partager les mêmes projets.
- **Code** : chaque modification poussée sur GitHub recompile automatiquement l'APK et le `.exe` (onglet *Actions*), et les publie dans *Releases*.
- **Tests du serveur** : `cd server && npm test`.
