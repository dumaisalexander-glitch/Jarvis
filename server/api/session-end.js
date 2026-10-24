// POST /api/session-end  {"session": "<id>"}
// Termine la session : résumé par Claude, envoi dans Teams, ajout au journal.

import { json, preflight, unauthorized } from "../lib/http.js";
import { endSession } from "../lib/session.js";

export function OPTIONS() {
  return preflight();
}

export async function POST(request) {
  const denied = unauthorized(request);
  if (denied) return denied;
  try {
    const body = await request.json().catch(() => ({}));
    const sessionId = String(body.session || request.headers.get("x-session") || "")
      .replace(/[^a-zA-Z0-9_-]/g, "")
      .slice(0, 64);
    if (!sessionId) return json({ erreur: "session manquante" }, 400);
    const lien = new URL("/", request.url).toString();
    return json(await endSession({ sessionId, lien }));
  } catch (e) {
    console.error(e);
    return json({ erreur: e.message }, 502);
  }
}
