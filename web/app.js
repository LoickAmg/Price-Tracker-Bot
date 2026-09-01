/* V2 — helpers HTML partagés (dashboard + ajouter). */

function formatPrice(value, currency) {
  const symbols = { EUR: "€", USD: "$", GBP: "£" };
  const symbol = symbols[currency] ?? currency;
  return `${Number(value).toFixed(2)} ${symbol}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : `réponse ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

function formatTime(iso) {
  if (!iso) return "jamais";
  return new Date(iso).toLocaleString("fr-FR");
}

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function onError(target, err) {
  target.hidden = false;
  target.textContent = err.message || String(err);
}