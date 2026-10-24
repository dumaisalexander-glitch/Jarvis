// GET  /api/projects            -> tous les projets + journal des sessions
// POST /api/projects {actions}  -> changements faits à la main dans le tableau

import { json, preflight, unauthorized } from "../lib/http.js";
import { applyActions } from "../lib/projects.js";
import { loadState, saveState } from "../lib/session.js";

export function OPTIONS() {
  return preflight();
}

export async function GET(request) {
  const denied = unauthorized(request);
  if (denied) return denied;
  try {
    return json(await loadState());
  } catch (e) {
    return json({ erreur: e.message }, 502);
  }
}

export async function POST(request) {
  const denied = unauthorized(request);
  if (denied) return denied;
  try {
    const body = await request.json();
    const state = await loadState();
    const changements = applyActions(state, Array.isArray(body.actions) ? body.actions : []);
    await saveState(state);
    return json({ changements, etat: state });
  } catch (e) {
    return json({ erreur: e.message }, 400);
  }
}
