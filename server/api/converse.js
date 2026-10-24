// POST /api/converse
// Corps : l'audio brut (audio/wav, audio/mp4, audio/webm...) OU du JSON {"texte": "..."}.
// En-têtes : Authorization: Bearer <JARVIS_TOKEN>, X-Session: <id>, X-Device: android|windows|web

import { transcribe } from "../lib/ai.js";
import { json, preflight, unauthorized } from "../lib/http.js";
import { endSession, handleTurn } from "../lib/session.js";

export function OPTIONS() {
  return preflight();
}

export async function POST(request) {
  const denied = unauthorized(request);
  if (denied) return denied;

  const sessionId = (request.headers.get("x-session") || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64) || "defaut";
  const device = (request.headers.get("x-device") || "web").toLowerCase();
  const contentType = (request.headers.get("content-type") || "").toLowerCase();

  try {
    let texte;
    if (contentType.includes("application/json")) {
      const body = await request.json();
      texte = String(body.texte || "").trim();
    } else {
      const audio = new Uint8Array(await request.arrayBuffer());
      if (audio.byteLength < 2000) return json({ transcription: "", reponse: "Je n'ai rien entendu.", changements: [] });
      texte = await transcribe(audio, contentType || "audio/wav");
    }

    if (!texte || texte.length < 2) {
      return json({ transcription: texte, reponse: "Je n'ai pas bien compris, peux-tu répéter?", changements: [] });
    }

    const tour = await handleTurn({ text: texte, sessionId, device });
    let fin = null;
    if (tour.finSession) {
      const lien = new URL("/", request.url).toString();
      fin = await endSession({ sessionId, lien });
    }
    return json({
      transcription: texte,
      reponse: tour.reponse,
      changements: tour.changements,
      finSession: tour.finSession,
      teams: fin?.teams,
    });
  } catch (e) {
    console.error(e);
    return json({ erreur: e.message, reponse: "Désolé, j'ai eu un problème. Réessaie dans un instant." }, 502);
  }
}
