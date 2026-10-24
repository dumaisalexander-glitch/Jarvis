// Logique d'une session de conversation : un tour de parole, et la fin de session.

import { converse, summarize } from "./ai.js";
import { applyActions, compactForAI, emptyState } from "./projects.js";
import { KEYS, del, getJSON, setJSON } from "./store.js";
import { postToTeams } from "./teams.js";

const SESSION_TTL = 60 * 60 * 12; // 12 h
const MAX_HISTORY = 24; // 12 échanges gardés en mémoire pour Claude

export async function loadState() {
  return getJSON(KEYS.state, emptyState());
}

export async function saveState(state) {
  await setJSON(KEYS.state, state);
}

export async function handleTurn({ text, sessionId, device }) {
  const session = await getJSON(KEYS.session(sessionId), { history: [], changes: [], debut: new Date().toISOString() });
  const state = await loadState();

  const result = await converse({
    text,
    history: session.history,
    projectsCompact: compactForAI(state),
    device,
  });

  const changes = applyActions(state, result.actions);
  if (changes.length) await saveState(state);

  session.history.push({ role: "user", content: text }, { role: "assistant", content: result.reponse });
  if (session.history.length > MAX_HISTORY) session.history = session.history.slice(-MAX_HISTORY);
  session.changes.push(...changes);
  session.device = device;
  await setJSON(KEYS.session(sessionId), session, SESSION_TTL);

  return { reponse: result.reponse, changements: changes, finSession: result.finSession };
}

export async function endSession({ sessionId, lien }) {
  const session = await getJSON(KEYS.session(sessionId), null);
  if (!session || !session.history.length) return { resume: "", teams: { envoye: false, raison: "Session vide." } };

  const state = await loadState();
  const resume = await summarize({
    history: session.history,
    changes: session.changes,
    projectsCompact: compactForAI(state),
  });

  const quand = new Intl.DateTimeFormat("fr-CA", {
    timeZone: "America/Toronto",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date());
  const source = session.device === "android" ? "téléphone" : "ordinateur";
  const teams = await postToTeams({ titre: `🧠 Session Jarvis (${source}) · ${quand}`, texte: resume, lien });

  state.journal = [{ date: new Date().toISOString(), source, resume }, ...(state.journal || [])].slice(0, 30);
  await saveState(state);
  await del(KEYS.session(sessionId));
  return { resume, teams };
}
