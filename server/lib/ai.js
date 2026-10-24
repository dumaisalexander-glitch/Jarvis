// Appels à Whisper (transcription) et à Claude (réflexion + organisation).

import { CATEGORIES, STATUTS } from "./projects.js";

const CLAUDE_MODEL = () => process.env.CLAUDE_MODEL || "claude-sonnet-5-5";

// ---------------------------------------------------------------- Whisper
export async function transcribe(audio, contentType) {
  const key = process.env.OPENAI_API_KEY;
  if (!key) throw new Error("OPENAI_API_KEY n'est pas configurée sur le serveur.");
  const ext = contentType.includes("wav") ? "wav" : contentType.includes("webm") ? "webm" : "m4a";
  const form = new FormData();
  form.append("file", new Blob([audio], { type: contentType }), `audio.${ext}`);
  form.append("model", process.env.WHISPER_MODEL || "whisper-1");
  form.append("language", "fr");
  // Aide Whisper à bien écrire les noms propres.
  form.append("prompt", "Jarvis, LoRyzon, Cricut, impression 3D, gravure laser, cégep, Teams.");
  const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: { authorization: `Bearer ${key}` },
    body: form,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Whisper : ${body.error?.message || res.status}`);
  return String(body.text || "").trim();
}

// ---------------------------------------------------------------- Claude
async function claude(payload) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY n'est pas configurée sur le serveur.");
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({ model: CLAUDE_MODEL(), ...payload }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Claude : ${body.error?.message || res.status}`);
  return body;
}

export const ORGANISER_TOOL = {
  name: "organiser",
  description:
    "Toujours appeler cet outil. Donne la réponse à dire à voix haute et les changements à faire dans les projets.",
  input_schema: {
    type: "object",
    properties: {
      reponse_vocale: {
        type: "string",
        description:
          "Ce que Jarvis dit à voix haute. Français québécois naturel, 1 à 3 phrases courtes, sans listes, sans émojis, sans markdown.",
      },
      actions: {
        type: "array",
        description: "Changements à appliquer aux projets. Liste vide si rien à changer.",
        items: {
          type: "object",
          properties: {
            type: {
              type: "string",
              enum: [
                "creer_projet",
                "modifier_projet",
                "ajouter_tache",
                "completer_tache",
                "supprimer_tache",
                "ajouter_note",
                "supprimer_projet",
              ],
            },
            projet: { type: "string", description: "Nom exact du projet visé (ou du nouveau projet)." },
            categorie: { type: "string", enum: CATEGORIES },
            statut: { type: "string", enum: STATUTS },
            nouveau_nom: { type: "string" },
            resume: { type: "string", description: "Résumé du projet en une ou deux phrases." },
            prochaine_etape: { type: "string" },
            echeance: { type: "string", description: "Date AAAA-MM-JJ si connue." },
            texte: { type: "string", description: "Texte de la tâche ou de la note." },
            tache: { type: "string", description: "Tâche existante visée (pour la compléter ou la retirer)." },
            fait: { type: "boolean" },
          },
          required: ["type", "projet"],
        },
      },
      fin_session: {
        type: "boolean",
        description: "Vrai seulement si l'utilisateur veut terminer la session (« c'est tout », « bye Jarvis »...).",
      },
    },
    required: ["reponse_vocale", "actions", "fin_session"],
  },
};

function today() {
  return new Intl.DateTimeFormat("fr-CA", {
    timeZone: process.env.TZ_JARVIS || "America/Toronto",
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}

export function systemPrompt(projectsCompact, device) {
  const where =
    device === "android"
      ? "Il te parle probablement depuis son auto, en conduisant : il ne peut PAS regarder l'écran. Ne lui demande jamais de lire, de cliquer ou de regarder quoi que ce soit."
      : "Il te parle depuis son ordinateur.";
  return `Tu es Jarvis, l'assistant personnel d'Alexander. Il est étudiant et propriétaire de LoRyzon, une petite entreprise québécoise de produits artisanaux (impression 3D, découpe Cricut, gravure laser).

Ton rôle : l'aider à faire avancer ses projets à voix haute, pour que tout soit déjà organisé quand il arrive à l'école ou à la maison. ${where}

Nous sommes le ${today()}.

Catégories de projets : "ecole" (travaux scolaires), "loryzon" (produits, site web, idées d'affaires), "perso" (projets personnels).

Comment tu travailles :
- Tu réponds en français québécois naturel, comme un collègue allumé. Phrases courtes, faciles à comprendre à l'oral. Jamais de listes ni de symboles : tout est lu par une voix de synthèse.
- Tu ORIENTES : tu poses UNE seule question à la fois pour clarifier ou faire avancer (objectif, échéance, prochaine étape concrète). Tu proposes de découper un gros projet en petites tâches.
- Tu ranges tout de suite ce qu'il dit dans ses projets avec l'outil organiser : nouveau projet, tâches concrètes (commencent par un verbe), notes d'idées, prochaine étape, échéance. N'invente pas de tâches qu'il n'a pas acceptées ; tu peux en proposer à voix haute et les ajouter quand il dit oui.
- Si ce qu'il dit pourrait aller dans plusieurs projets, choisis le plus probable et dis-le brièvement.
- Pour un travail scolaire, aide-le à planifier et à structurer ses idées, mais c'est lui qui fait le travail.
- Quand il demande où il en est, résume l'essentiel en deux ou trois phrases, en commençant par ce qui est le plus urgent.
- Si la transcription semble incomplète ou bizarre, demande-lui de répéter plutôt que de deviner.

Ses projets actuels (JSON) :
${JSON.stringify(projectsCompact)}`;
}

/** Une étape de conversation. history = [{role, content}] en texte simple. */
export async function converse({ text, history, projectsCompact, device }) {
  const messages = [...history, { role: "user", content: text }];
  const body = await claude({
    max_tokens: 1500,
    system: systemPrompt(projectsCompact, device),
    tools: [ORGANISER_TOOL],
    tool_choice: { type: "tool", name: "organiser" },
    messages,
  });
  const call = (body.content || []).find((c) => c.type === "tool_use" && c.name === "organiser");
  if (!call) throw new Error("Claude n'a pas utilisé l'outil organiser.");
  const input = call.input || {};
  return {
    reponse: String(input.reponse_vocale || "").trim() || "C'est noté.",
    actions: Array.isArray(input.actions) ? input.actions : [],
    finSession: input.fin_session === true,
    usage: body.usage,
  };
}

/** Résumé de fin de session, pour Teams. */
export async function summarize({ history, changes, projectsCompact }) {
  const transcript = history.map((m) => `${m.role === "user" ? "Alexander" : "Jarvis"} : ${m.content}`).join("\n");
  const body = await claude({
    max_tokens: 900,
    system:
      "Tu rédiges le compte rendu d'une session de travail entre Alexander et son assistant Jarvis, pour qu'il le retrouve dans Teams en arrivant à l'école ou à la maison. Français québécois, concis. Format : une phrase d'ouverture, puis par projet touché une ligne en gras avec le nom du projet suivie de puces courtes (décisions, tâches ajoutées, prochaine étape). Termine par une ligne « À faire en premier : » avec la chose la plus importante. Markdown simple seulement (gras et puces).",
    messages: [
      {
        role: "user",
        content: `Conversation :\n${transcript || "(aucune)"}\n\nChangements faits dans les projets :\n${
          changes.join("\n") || "(aucun)"
        }\n\nÉtat des projets après la session :\n${JSON.stringify(projectsCompact)}`,
      },
    ],
  });
  return (body.content || [])
    .filter((c) => c.type === "text")
    .map((c) => c.text)
    .join("\n")
    .trim();
}
