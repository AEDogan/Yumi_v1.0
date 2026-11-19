// Yumi (11 Kasım, v1.2 12 Kasım): reklamda "Atla" butonu görünür olunca reklamı geçer. Yalnız YouTube (manifest), yalnız atlama
// butonu göründüğünde (YouTube'un atlamaya izin verdiği an); atlanamayan reklama ve başka reklam öğelerine dokunmaz.
// is_102: YouTube sayfa içi (isTrusted=false) tıklamayı yok sayıyor -> önce tıkla, 0,8 s'de geçmezse reklam videosunu sonuna sar.
// v1.2: youtube.com'da çalışmadı (kullanıcı 12 Kasım) -> buton yazı/aria-label ile de aranır (sınıf adları değişebiliyor),
// reklam başladığında ne bulunduğu Yumi'ye bildirilir (data/logs/reklam-atla.log), sarma 3 kez denenir.
// v1.3 (13 Kasım canlı kabul): art arda 2. reklamda sarma "sar_olmadi" (reklam videosunun süresi henüz bilinmiyordu, tek
// <video> seçiliyordu) -> oynatıcıdaki tüm videolar denenir; süre yoksa reklam 16x hızda ve sessiz oynatılır, süre gelince sonuna
// sarılır; reklam bitince hız/ses ana video için geri alınır. Yine yalnız "Atla" butonu göründüğünde.
(() => {
  const SECICI = [".ytp-skip-ad-button", ".ytp-ad-skip-button", ".ytp-ad-skip-button-modern", ".ytp-skip-ad button",
                  ".ytp-ad-skip-button-slot button", ".ytp-ad-skip-button-container button", "[id^='skip-button'] button",
                  "button[class*='skip']"];
  const YAZI = /^(atla|reklam[ıi] atla|reklamlar[ıi] atla|skip|skip ad|skip ads)\b/i;
  let son = 0, reklamVar = false, deneme = 0;
  const gorunur = (b) => {
    const r = b.getBoundingClientRect(), st = getComputedStyle(b);
    return r.width > 4 && r.height > 4 && st.visibility !== "hidden" && st.display !== "none" && parseFloat(st.opacity || "1") > 0.1;
  };
  const reklamOynatici = () => document.querySelector(".html5-video-player.ad-showing, .html5-video-player.ad-interrupting");
  const atlaButonu = () => {
    for (const q of SECICI) for (const b of document.querySelectorAll(q)) if (gorunur(b)) return b;
    const p = reklamOynatici();
    if (p) for (const b of p.querySelectorAll("button, [role='button']")) {
      const t = (b.getAttribute("aria-label") || b.innerText || "").trim();
      if (YAZI.test(t) && gorunur(b)) return b;
    }
    return null;
  };
  const bildir = (olay, ek) => { try { chrome.runtime.sendMessage({ atlandi: true, olay, ...ek, site: location.hostname }); } catch (e) {} };
  const bas = (b) => {
    const r = b.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
    const ortak = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 };
    for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup"])
      b.dispatchEvent(new (t.startsWith("pointer") ? PointerEvent : MouseEvent)(t, { ...ortak, pointerId: 1, isPrimary: true }));
    b.click();
  };
  let hizli = false;
  const sar = (p) => {
    let oldu = false;
    for (const v of (p ? p.querySelectorAll("video") : [])) {
      if (isFinite(v.duration) && v.duration > 0) {
        v.currentTime = Math.max(0, v.duration - 0.05); oldu = true;
        try { v.play(); } catch (e) {}
      } else if (!v.paused || v.readyState > 0) {
        v.muted = true; v.playbackRate = 16; hizli = true;
        v.addEventListener("loadedmetadata", () => { if (reklamOynatici()) v.currentTime = Math.max(0, v.duration - 0.05); }, { once: true });
        oldu = true;
      }
    }
    return oldu;
  };
  const hiziGeriAl = () => {
    if (!hizli) return;
    hizli = false;
    for (const v of document.querySelectorAll("video")) { v.playbackRate = 1; v.muted = false; }
  };
  setInterval(() => {
    const p = reklamOynatici();
    if (p && !reklamVar) {  // tanı: reklam başladı, oynatıcıdaki butonlar
      reklamVar = true; deneme = 0;
      const butonlar = [...p.querySelectorAll("button")].filter(gorunur).map(b => (b.className || "").toString().slice(0, 60) + "|" + (b.getAttribute("aria-label") || b.innerText || "").trim().slice(0, 30)).slice(0, 8);
      bildir("reklam", { butonlar: butonlar.join(" ; ") });
    }
    if (!p && reklamVar) { reklamVar = false; hiziGeriAl(); bildir("reklam_bitti", { deneme }); }
    if (!p) hiziGeriAl();
    if (Date.now() - son < 1500) return;
    const b = atlaButonu();
    if (!b) return;
    son = Date.now(); deneme++;
    bas(b);
    setTimeout(() => {
      const p2 = reklamOynatici();
      if (!p2 || !atlaButonu()) { bildir("tik", { deneme }); return; }  // tıklama işe yaradı
      bildir(sar(p2) ? "sar" : "sar_olmadi", { deneme, sinif: (b.className || "").toString().slice(0, 60) });
    }, 800);
  }, 400);
})();
