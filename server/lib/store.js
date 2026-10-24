// Stockage dans Upstash Redis (ajouté depuis le Marketplace de Vercel).
// Accepte les deux noms de variables que Vercel peut créer.
// Sans base de données configurée (tests locaux), on garde tout en mémoire.

const URL_ = () => process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const TOKEN = () => process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;

const memory = new Map();

async function redis(command) {
  const res = await fetch(URL_(), {
    method: "POST",
    headers: { authorization: `Bearer ${TOKEN()}`, "content-type": "application/json" },
    body: JSON.stringify(command),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.error) throw new Error(`Base de données : ${body.error || res.status}`);
  return body.result;
}

export async function getJSON(key, fallback) {
  if (!URL_()) return memory.has(key) ? structuredClone(memory.get(key)) : fallback;
  const raw = await redis(["GET", key]);
  if (raw == null) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export async function setJSON(key, value, ttlSeconds) {
  if (!URL_()) {
    memory.set(key, structuredClone(value));
    return;
  }
  const cmd = ["SET", key, JSON.stringify(value)];
  if (ttlSeconds) cmd.push("EX", String(ttlSeconds));
  await redis(cmd);
}

export async function del(key) {
  if (!URL_()) return void memory.delete(key);
  await redis(["DEL", key]);
}

export const KEYS = {
  state: "jarvis:etat",
  session: (id) => `jarvis:session:${id}`,
};
