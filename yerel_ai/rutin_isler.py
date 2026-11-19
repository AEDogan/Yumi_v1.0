"""Arka plan yönlendiricisinin (yerel_ai.yonlendirici) açılış rutinleri — kullanıcı kararı 12 Kasım 17:37.

Yumi her açıldığında arka planda, sırayla ve sessizce çalışır; sonuç `data/logs/rutin.log`'a yazılır, hata Yumi'yi durdurmaz.
Yeni rutin eklemek: `ACILIS` listesine (ad, işlev) ekle; işlev kısa bir sonuç metni döndürür.

Rutinler:
- youtube_onbellek: YouTube profilinin Service Worker önbelleğini siler (is_139: eklentinin ESKİ arka plan betiği önbellekte
  kalıyordu). Profilin Chrome'u açıksa dokunmaz (açık tarayıcının dosyası silinmez), bir sonraki açılışa kalır.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
GIZLI = {"creationflags": 0x08000000} if hasattr(subprocess, "STARTUPINFO") else {}


def _gunluk(veri_klasoru: Path, satir: str) -> None:
    g = Path(veri_klasoru) / "logs" / "rutin.log"
    g.parent.mkdir(parents=True, exist_ok=True)
    with g.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + satir + "\n")


def _profil_acik(profil: Path) -> bool:
    ad = profil.name.replace("'", "")
    ps = (f"@(Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*{ad}*' -and $_.Name -ne 'powershell.exe' }}).Count")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20, **GIZLI)
        return int((r.stdout or "0").strip() or 0) > 0
    except Exception:
        return True  # emin değilsek silme


def youtube_onbellek(veri_klasoru: Path) -> str:
    """Chrome (eski, elle eklenti) ve Edge (F1b, eklenti kendiliğinden) YouTube profilleri."""
    sonuc = []
    for ad in ("youtube-profile", "youtube-profile-edge"):
        profil = Path(veri_klasoru) / ad
        hedef = profil / "Default" / "Service Worker"
        if not hedef.exists():
            continue
        if _profil_acik(profil):
            sonuc.append(f"{ad}: acik, atlandi"); continue
        shutil.rmtree(hedef, ignore_errors=True)
        sonuc.append(f"{ad}: silindi" if not hedef.exists() else f"{ad}: silinemedi")
    return "; ".join(sonuc) or "onbellek yok"


ACILIS = [("youtube_onbellek", youtube_onbellek)]


class RutinIsler:
    def __init__(self, veri_klasoru=None):
        if not veri_klasoru:
            from app_paths import data_dir  # G-A2: veri alanı
            veri_klasoru = data_dir()
        self.veri_klasoru = Path(veri_klasoru)
        self.sonuclar: dict[str, str] = {}

    def acilis(self, gecikme_s: float = 5.0) -> threading.Thread:
        """Açılış rutinlerini arka planda başlatır (açılış yükü bitsin diye kısa gecikmeyle)."""
        def calis():
            time.sleep(gecikme_s)
            for ad, islev in ACILIS:
                try:
                    sonuc = islev(self.veri_klasoru)
                except Exception as e:  # noqa: BLE001
                    sonuc = f"hata: {type(e).__name__}"
                self.sonuclar[ad] = sonuc
                try:
                    _gunluk(self.veri_klasoru, f"{ad}: {sonuc}")
                except OSError:
                    pass
        t = threading.Thread(target=calis, daemon=True, name="yonlendirici-rutin")
        t.start()
        return t
