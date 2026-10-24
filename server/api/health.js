// GET /api/health — vérifie la configuration (sans révéler les clés).

import { json, unauthorized } from "../lib/http.js";

export function GET(request) {
  const denied = unauthorized(request);
  if (denied) return denied;
  const has = (k) => Boolean(process.env[k]);
  return json({
    ok: true,
    whisper: has("OPENAI_API_KEY"),
    claude: has("ANTHROPIC_API_KEY"),
    modele: process.env.CLAUDE_MODEL || "claude-sonnet-5-5",
    base_de_donnees: has("KV_REST_API_URL") || has("UPSTASH_REDIS_REST_URL"),
    teams: has("TEAMS_WEBHOOK_URL"),
  });
}
