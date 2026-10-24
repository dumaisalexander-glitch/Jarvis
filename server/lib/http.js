// Petits utilitaires HTTP communs à toutes les routes.

export function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...cors() },
  });
}

export function cors() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "authorization, content-type, x-session, x-device",
    "access-control-allow-methods": "GET, POST, OPTIONS",
  };
}

export function preflight() {
  return new Response(null, { status: 204, headers: cors() });
}

// Vérifie le mot de passe partagé (variable JARVIS_TOKEN sur Vercel).
export function unauthorized(request) {
  const expected = process.env.JARVIS_TOKEN;
  if (!expected) return json({ erreur: "JARVIS_TOKEN n'est pas configuré sur le serveur." }, 500);
  const header = request.headers.get("authorization") || "";
  const given = header.replace(/^Bearer\s+/i, "").trim();
  if (!safeEqual(given, expected)) return json({ erreur: "Mot de passe Jarvis invalide." }, 401);
  return null;
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
