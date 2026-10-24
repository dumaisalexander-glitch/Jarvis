// Modèle de données des projets et application des actions décidées par Claude
// (ou faites à la main dans le tableau).

export const CATEGORIES = ["ecole", "loryzon", "perso"];
export const STATUTS = ["actif", "en_pause", "termine"];

export function emptyState() {
  return { projets: [], journal: [], version: 1 };
}

const now = () => new Date().toISOString();
const newId = (prefix) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export function normalize(s) {
  return String(s || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function findProject(state, ref) {
  if (!ref) return null;
  const byId = state.projets.find((p) => p.id === ref);
  if (byId) return byId;
  const n = normalize(ref);
  if (!n) return null;
  return (
    state.projets.find((p) => normalize(p.nom) === n) ||
    state.projets.find((p) => normalize(p.nom).includes(n) || n.includes(normalize(p.nom))) ||
    null
  );
}

function findTask(projet, ref) {
  if (!ref) return null;
  const byId = projet.taches.find((t) => t.id === ref);
  if (byId) return byId;
  const n = normalize(ref);
  return (
    projet.taches.find((t) => normalize(t.texte) === n) ||
    projet.taches.find((t) => normalize(t.texte).includes(n) || n.includes(normalize(t.texte))) ||
    null
  );
}

function makeProject(a) {
  return {
    id: newId("p"),
    nom: String(a.nouveau_nom || a.projet || "Nouveau projet").slice(0, 120),
    categorie: CATEGORIES.includes(a.categorie) ? a.categorie : "perso",
    statut: "actif",
    resume: a.resume || "",
    prochaine_etape: a.prochaine_etape || "",
    echeance: a.echeance || "",
    taches: [],
    notes: [],
    cree: now(),
    maj: now(),
  };
}

/**
 * Applique une liste d'actions. Retourne la liste des changements faits (phrases courtes),
 * pour l'affichage et pour le résumé Teams.
 */
export function applyActions(state, actions = []) {
  const done = [];
  for (const a of actions) {
    if (!a || typeof a !== "object") continue;
    try {
      const msg = applyOne(state, a);
      if (msg) done.push(msg);
    } catch (e) {
      done.push(`⚠️ ${a.type} : ${e.message}`);
    }
  }
  return done;
}

function applyOne(state, a) {
  let p = findProject(state, a.projet);
  const needProject = () => {
    if (p) return p;
    // Une tâche ou une note pour un projet inconnu : on le crée plutôt que de perdre l'idée.
    p = makeProject({ projet: a.projet || "Idées en vrac", categorie: a.categorie });
    state.projets.push(p);
    return p;
  };

  switch (a.type) {
    case "creer_projet": {
      if (p) return null; // existe déjà, rien à faire
      p = makeProject(a);
      state.projets.push(p);
      return `Projet créé : ${p.nom} (${p.categorie})`;
    }
    case "modifier_projet": {
      needProject();
      if (a.nouveau_nom) p.nom = String(a.nouveau_nom).slice(0, 120);
      if (CATEGORIES.includes(a.categorie)) p.categorie = a.categorie;
      if (STATUTS.includes(a.statut)) p.statut = a.statut;
      if (a.resume != null && a.resume !== "") p.resume = a.resume;
      if (a.prochaine_etape != null && a.prochaine_etape !== "") p.prochaine_etape = a.prochaine_etape;
      if (a.echeance != null && a.echeance !== "") p.echeance = a.echeance;
      p.maj = now();
      return `Projet mis à jour : ${p.nom}`;
    }
    case "ajouter_tache": {
      needProject();
      const texte = String(a.texte || "").trim();
      if (!texte) return null;
      if (findTask(p, texte) && normalize(findTask(p, texte).texte) === normalize(texte)) return null;
      p.taches.push({ id: newId("t"), texte, fait: false, echeance: a.echeance || "", cree: now() });
      p.maj = now();
      return `Tâche ajoutée à ${p.nom} : ${texte}`;
    }
    case "completer_tache": {
      if (!p) throw new Error(`projet introuvable (${a.projet})`);
      const t = findTask(p, a.tache || a.texte);
      if (!t) throw new Error(`tâche introuvable (${a.tache || a.texte})`);
      t.fait = a.fait === false ? false : true;
      p.maj = now();
      return `${t.fait ? "Tâche terminée" : "Tâche rouverte"} dans ${p.nom} : ${t.texte}`;
    }
    case "supprimer_tache": {
      if (!p) throw new Error(`projet introuvable (${a.projet})`);
      const t = findTask(p, a.tache || a.texte);
      if (!t) throw new Error(`tâche introuvable (${a.tache || a.texte})`);
      p.taches = p.taches.filter((x) => x !== t);
      p.maj = now();
      return `Tâche retirée de ${p.nom} : ${t.texte}`;
    }
    case "ajouter_note": {
      needProject();
      const texte = String(a.texte || "").trim();
      if (!texte) return null;
      p.notes.push({ id: newId("n"), texte, date: now() });
      p.maj = now();
      return `Note ajoutée à ${p.nom}`;
    }
    case "supprimer_projet": {
      if (!p) throw new Error(`projet introuvable (${a.projet})`);
      state.projets = state.projets.filter((x) => x !== p);
      return `Projet supprimé : ${p.nom}`;
    }
    default:
      throw new Error("action inconnue");
  }
}

// Version compacte des projets envoyée à Claude (moins de jetons, donc moins cher).
export function compactForAI(state) {
  const actifs = state.projets.filter((p) => p.statut !== "termine");
  const termines = state.projets.filter((p) => p.statut === "termine").map((p) => p.nom);
  return {
    projets: actifs.map((p) => ({
      nom: p.nom,
      categorie: p.categorie,
      statut: p.statut,
      resume: p.resume || undefined,
      prochaine_etape: p.prochaine_etape || undefined,
      echeance: p.echeance || undefined,
      taches_a_faire: p.taches.filter((t) => !t.fait).map((t) => t.texte + (t.echeance ? ` (pour ${t.echeance})` : "")),
      taches_faites: p.taches.filter((t) => t.fait).length || undefined,
      dernieres_notes: p.notes.slice(-3).map((n) => n.texte),
    })),
    projets_termines: termines.length ? termines : undefined,
  };
}
