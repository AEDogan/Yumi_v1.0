// Atlama/tanı bildirimini Yumi'ye iletir (Yumi dinlemiyorsa sessizce geçer). v1.2: tüm alanlar gönderilir.
chrome.runtime.onMessage.addListener((m) => {
  if (!m || !m.atlandi) return;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(m)) if (k !== "atlandi") q.set(k, String(v));
  if (!q.has("yol") && m.olay) q.set("yol", m.olay);
  fetch("http://127.0.0.1:8766/reklam-atlandi?" + q.toString()).catch(() => {});
});
