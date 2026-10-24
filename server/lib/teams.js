// Envoi du résumé dans Teams par un « Workflow » (webhook Teams).
// Voir le guide : modèle « Publier dans une conversation à la réception d'une requête webhook ».

export async function postToTeams({ titre, texte, lien }) {
  const url = process.env.TEAMS_WEBHOOK_URL;
  if (!url) return { envoye: false, raison: "TEAMS_WEBHOOK_URL n'est pas configurée." };

  const card = {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.4",
    msteams: { width: "Full" },
    body: [
      { type: "TextBlock", text: titre, weight: "Bolder", size: "Medium", wrap: true },
      { type: "TextBlock", text: texte, wrap: true },
    ],
    actions: lien ? [{ type: "Action.OpenUrl", title: "Ouvrir mes projets", url: lien }] : [],
  };

  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      type: "message",
      attachments: [{ contentType: "application/vnd.microsoft.card.adaptive", contentUrl: null, content: card }],
    }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    return { envoye: false, raison: `Teams a répondu ${res.status} ${t.slice(0, 200)}` };
  }
  return { envoye: true };
}
