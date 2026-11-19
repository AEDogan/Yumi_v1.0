"""YouTube'u Yumi'nin ayrı Chrome profilinde açar; reklamda "Atla"ya o profile yüklenen eklenti basar
(`eklenti/reklam_atla`, kullanıcı 11 Kasım). Atlanamayan reklamlara dokunulmaz.

Neden eklenti, neden hata ayıklama portu yok (is_094–099): Chrome hata ayıklama portuyla (CDP) açılınca YouTube
~42. saniyede "Bir hata oluştu" deyip oynatmayı kesiyor; portsuz açılışta sorun yok. Chrome 157 `--load-extension`
bayrağını yok sayıyor (is_100), eklenti profile bir kez chrome://extensions → "Paketlenmemiş öğe yükle" ile eklenir.

- Profil: <Yumi>/data/youtube-profile (Gemini profili `browser-profile` aynı anda açık olduğu için paylaşılamaz).
- Tarayıcı: varsayılan Chromium tabanlı tarayıcı (`browser_chat.default_browser`), normal masaüstünde.
  Profil zaten açıksa Chrome adresi o pencereye yeni sekme olarak verir.
Chromium tabanlı tarayıcı yoksa `ac` False döner; çağıran normal `webbrowser.open`'a düşer."""
from __future__ import annotations

import json, os, subprocess
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
from app_paths import data_dir as _data_dir  # G-A2: tarayıcı profili kullanıcı veri alanında
PROFIL = _data_dir() / "youtube-profile"
PROFIL_EDGE = _data_dir() / "youtube-profile-edge"  # F1b: eklenti kendiliğinden yüklenen Edge profili
EKLENTI = KOK / "eklenti" / "reklam_atla"


def _eklenti_profilde(profil) -> bool:
    """Eklenti bu profile (elle, chrome://extensions) yüklenmiş mi?"""
    for ad in ("Secure Preferences", "Preferences"):
        try:
            d = json.loads((profil / "Default" / ad).read_text(encoding="utf-8", errors="replace"))
            if any("reklam_atla" in str(e.get("path", "")) for e in (d.get("extensions", {}).get("settings", {}) or {}).values()):
                return True
        except Exception:
            pass
    return False


def _edge():
    for k in ("ProgramFiles(x86)", "ProgramFiles"):
        p = Path(os.environ.get(k, "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if p.is_file():
            return p
    return None


def _secim():
    """(tarayıcı, profil, ek bayraklar). F1b (19 Kas ölçüm, work/f1b/eklenti_sina.py): Chrome 157 --load-extension'ı yok
    sayıyor, Edge 157 yüklüyor. Eklenti eski Chrome profiline elle yüklenmişse o kullanılır; yoksa Edge + eklenti
    kendiliğinden (her Windows'ta Edge var, kurulumda elle adım yok); Edge de yoksa varsayılan tarayıcı eklentisiz."""
    try:
        from browser_chat import default_browser  # Yumi kökü sys.path'te (app.py)
        exe = default_browser()
    except Exception:
        exe = None
    if exe and "msedge" not in exe.name.lower() and _eklenti_profilde(PROFIL):
        return exe, PROFIL, []
    edge = _edge()
    if edge and EKLENTI.is_dir():
        return edge, PROFIL_EDGE, [f"--load-extension={EKLENTI}"]
    if exe is None:
        raise RuntimeError("tarayıcı yok")
    return exe, PROFIL, []


def _temiz_cikis_isaretle(profil=PROFIL):
    """Canlı kabul (13 Kasım): Yumi açılış rutini/önbellek temizliği Chrome'u kapatınca profil "düzgün kapanmadı" sayılıyor,
    her açılışta "Sayfalar geri yüklensin mi?" balonu çıkıyordu → açmadan önce profil temiz kapanmış olarak işaretlenir
    (yalnız bu Yumi profili; kullanıcının kendi Chrome'una dokunulmaz)."""
    for yol in (profil / "Default" / "Preferences",):
        try:
            if not yol.exists():
                continue
            d = json.loads(yol.read_text(encoding="utf-8"))
            p = d.setdefault("profile", {})
            if p.get("exit_type") == "Normal" and p.get("exited_cleanly") is True:
                continue
            p["exit_type"] = "Normal"; p["exited_cleanly"] = True
            yol.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except Exception:
            pass


def ac(url) -> bool:
    try:
        exe, profil, ek = _secim()
        profil.mkdir(parents=True, exist_ok=True)
        _temiz_cikis_isaretle(profil)
        subprocess.Popen([str(exe), f"--user-data-dir={profil}", "--no-first-run", "--no-default-browser-check",
                          "--hide-crash-restore-bubble", "--autoplay-policy=no-user-gesture-required", *ek, url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def eklenti_kur():
    """Bir kerelik: Yumi YouTube profilinde eklentiler sayfasını açar (kullanıcı 'Paketlenmemiş öğe yükle' ile EKLENTI'yi seçer)."""
    from browser_chat import default_browser
    PROFIL.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(default_browser()), f"--user-data-dir={PROFIL}", "--no-first-run", "chrome://extensions/"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
