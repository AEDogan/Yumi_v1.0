"""B08: YouTube / YouTube Music'te doğrudan oynatma (hesap gerekmez). Arama sayfasındaki ilk videoyu bulur, izleme sayfasını açar
(tarayıcıda kendiliğinden başlar). Bulamazsa None döner; çağıran eski yola (arama sayfası) düşer. Ağ çağrısı: arka planda çalıştırılır."""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import webbrowser

ORTAM = {  # Türkçe ortam sesi -> daha iyi sonuç veren arama
    "yağmur": "rain sounds for sleeping 1 hour", "şömine": "fireplace crackling sound 1 hour", "beyaz gürültü": "white noise 1 hour",
    "orman": "forest nature sounds 1 hour", "kafe": "coffee shop ambience 1 hour", "dalga": "ocean waves sounds 1 hour",
    "kuş": "birds singing nature sounds", "doğa": "relaxing nature sounds 1 hour", "lofi": "lofi hip hop radio", "lo-fi": "lofi hip hop radio",
}


def ilk_video(sorgu: str, zaman_asimi=4):
    """YouTube aramasındaki ilk video kimliği (11 karakter) ya da None. Reklam/canlı yayın ayrımı yapmaz; ilk 'videoRenderer' alınır."""
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": sorgu, "hl": "tr", "gl": "TR"})
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "tr-TR,tr;q=0.9"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as y:
        html = y.read().decode("utf-8", errors="ignore")
    m = re.search(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})"', html) or re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
    return m.group(1) if m else None


def arama_metni(sorgu: str, yalniz_sanatci=False) -> str:
    k = sorgu.lower()
    for tr, en in ORTAM.items():
        if tr in k:
            return en
    return f"{sorgu} şarkı" if yalniz_sanatci else sorgu  # 'tarkan' -> haber/konuşma değil şarkı gelsin


def bas_harf(s: str) -> str:
    return ("İ" if s[:1] == "i" else s[:1].upper()) + s[1:] if s else s


def _ac(url):
    """Yumi'nin YouTube penceresi (reklamda 'Atla'ya kendisi basar, 11 Kasım); olmazsa varsayılan tarayıcı."""
    try:
        from .youtube_tarayici import ac as yt_ac
        if yt_ac(url):
            return
    except Exception:
        pass
    webbrowser.open(url)


def oynat(sorgu: str, platform: str = "youtube", ac=_ac, yalniz_sanatci=False):
    """-> söylenecek cümle ya da None (bulunamadı / ağ yok)."""
    try:
        vid = ilk_video(arama_metni(sorgu, yalniz_sanatci))
    except Exception:
        return None
    if not vid:
        return None
    if platform == "youtube_music":
        ac(f"https://music.youtube.com/watch?v={vid}")
        return f"{bas_harf(sorgu)} YouTube Music'te çalıyor."
    ac(f"https://www.youtube.com/watch?v={vid}")
    return f"{bas_harf(sorgu)} YouTube'da çalıyor."
