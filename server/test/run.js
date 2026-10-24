// Tests locaux du serveur, sans Internet : Whisper, Claude et Teams sont simulés.
// Lancer : npm test

import assert from "node:assert/strict";

process.env.JARVIS_TOKEN = "secret-test";
process.env.OPENAI_API_KEY = "sk-test";
process.env.ANTHROPIC_API_KEY = "sk-ant-test";
process.env.TEAMS_WEBHOOK_URL = "https://teams.example/webhook";

const calls = [];
let nextClaude = [];
globalThis.fetch = async (url, opts = {}) => {
  url = String(url);
  calls.push({ url, opts });
  if (url.includes("openai.com")) {
    assert.ok(opts.body instanceof FormData, "Whisper reçoit un formulaire");
    assert.equal(opts.body.get("language"), "fr");
    return Response.json({ text: "Jarvis, nouveau projet pour l'école, une dissertation en français pour vendredi." });
  }
  if (url.includes("anthropic.com")) {
    const req = JSON.parse(opts.body);
    assert.equal(opts.headers["anthropic-version"], "2023-06-01");
    assert.equal(req.model, "claude-sonnet-5-5");
    // l'historique doit alterner user/assistant et commencer par user
    req.messages.forEach((m, i) => assert.equal(m.role, i % 2 === 0 ? "user" : "assistant"));
    const next = nextClaude.shift();
    assert.ok(next, "réponse Claude simulée manquante");
    return Response.json(next(req));
  }
  if (url.includes("teams.example")) {
    const body = JSON.parse(opts.body);
    assert.equal(body.attachments[0].contentType, "application/vnd.microsoft.card.adaptive");
    return new Response("", { status: 202 });
  }
  throw new Error("URL inattendue " + url);
};

const toolReply = (input) => () => ({ content: [{ type: "tool_use", name: "organiser", input }], usage: {} });

const converse = await import("../api/converse.js");
const projects = await import("../api/projects.js");
const sessionEnd = await import("../api/session-end.js");
const health = await import("../api/health.js");

const H = (extra = {}) => ({ authorization: "Bearer secret-test", "x-session": "s1", "x-device": "android", ...extra });

// 1. mauvais mot de passe
let r = await projects.GET(new Request("https://j.test/api/projects", { headers: { authorization: "Bearer non" } }));
assert.equal(r.status, 401);

// 2. santé
r = await health.GET(new Request("https://j.test/api/health", { headers: H() }));
assert.deepEqual((await r.json()).claude, true);

// 3. un tour audio : crée un projet + une tâche
nextClaude.push((req) => {
  assert.ok(req.system.includes("auto"), "le mode auto est mentionné pour Android");
  assert.equal(req.tool_choice.name, "organiser");
  return toolReply({
    reponse_vocale: "Parfait, j'ai créé ton projet de dissertation. C'est quoi le sujet?",
    actions: [
      { type: "creer_projet", projet: "Dissertation de français", categorie: "ecole", echeance: "2026-10-30" },
      { type: "ajouter_tache", projet: "Dissertation de français", texte: "Choisir le sujet" },
    ],
    fin_session: false,
  })();
});
const fakeAudio = new Uint8Array(8000).fill(1);
r = await converse.POST(new Request("https://j.test/api/converse", { method: "POST", headers: H({ "content-type": "audio/mp4" }), body: fakeAudio }));
let body = await r.json();
assert.equal(r.status, 200, JSON.stringify(body));
assert.match(body.reponse, /dissertation/);
assert.equal(body.changements.length, 2);

// 4. un tour texte qui touche la tâche existante (nom approximatif, accents) et termine la session
nextClaude.push((req) => {
  assert.equal(req.messages.length, 3, "historique conservé");
  assert.ok(req.system.includes("Choisir le sujet"), "les projets sont envoyés à Claude");
  return toolReply({
    reponse_vocale: "C'est noté, bonne journée!",
    actions: [
      { type: "completer_tache", projet: "dissertation de francais", tache: "choisir le sujet" },
      { type: "ajouter_note", projet: "Dissertation de français", texte: "Sujet : l'IA dans l'art" },
      { type: "ajouter_tache", projet: "Boutique en ligne", categorie: "loryzon", texte: "Mettre à jour les photos" },
    ],
    fin_session: true,
  })();
});
nextClaude.push(() => ({ content: [{ type: "text", text: "**Dissertation de français**\n- Sujet choisi" }] }));
r = await converse.POST(new Request("https://j.test/api/converse", {
  method: "POST", headers: H({ "content-type": "application/json" }), body: JSON.stringify({ texte: "Le sujet c'est l'IA dans l'art, c'est tout." }),
}));
body = await r.json();
assert.equal(r.status, 200, JSON.stringify(body));
assert.equal(body.finSession, true);
assert.equal(body.teams.envoye, true);

// 5. état final
r = await projects.GET(new Request("https://j.test/api/projects", { headers: H() }));
const state = await r.json();
assert.equal(state.projets.length, 2, "projet LoRyzon créé automatiquement");
const diss = state.projets.find((p) => p.categorie === "ecole");
assert.equal(diss.taches[0].fait, true);
assert.equal(diss.notes.length, 1);
assert.equal(state.journal.length, 1);

// 6. changement manuel depuis le tableau
r = await projects.POST(new Request("https://j.test/api/projects", {
  method: "POST", headers: H({ "content-type": "application/json" }),
  body: JSON.stringify({ actions: [{ type: "modifier_projet", projet: diss.id, statut: "termine" }] }),
}));
body = await r.json();
assert.equal(body.etat.projets.find((p) => p.id === diss.id).statut, "termine");

// 7. fin de session vide
r = await sessionEnd.POST(new Request("https://j.test/api/session-end", {
  method: "POST", headers: H({ "content-type": "application/json" }), body: JSON.stringify({ session: "inconnue" }),
}));
assert.equal((await r.json()).teams.envoye, false);

console.log("✅ Tous les tests du serveur passent.");
