"""TV yardımcıları (18 Kasım, ev_tarama): içerik (YouTube video kimliği) bulma, TV platformu tespiti,
ağdan açma ipuçları. Ağ: yalnız YouTube arama sayfası (internet) ve ev ağındaki TV'nin okuma uçları.
"""
from __future__ import annotations

import re

# Genel müzik isteği ("müzik aç", "şarkı çal") için makul arama
GENEL_MUZIK = "türkçe pop müzik mix"
GENEL_SOZCUKLER = {"müzik", "muzik", "şarkı", "sarki", "şarkılar", "müzikler", "bir şarkı", "bir müzik", "biraz müzik"}

# Platform → ağdan açma için TV'de açılması gereken ayar (Türkçe menü adlarıyla)
GUC_IPUCU = {
    "tizen": "Samsung TV'de Ayarlar > Genel > Ağ > Uzman Ayarları > 'Mobil ile Aç' (Power On with Mobile) açık olmalı.",
    "webos": "LG TV'de Ayarlar > Genel > Cihazlar > TV Yönetimi (veya Bağlantı) > 'Mobil ile TV'yi Aç' / 'Wi‑Fi ile aç' açık olmalı.",
    "androidtv": "Android/Google TV'de Ayarlar > Sistem > Güç ve enerji > 'Ağ bekleme' / 'Wake on LAN' açık olmalı.",
    "dial": "TV'nin ayarlarında 'ağ üzerinden aç' / 'Wake on LAN' seçeneği açık olmalı.",
    "upnp_av": "TV'nin ayarlarında 'ağ üzerinden aç' / 'Wake on LAN' seçeneği açık olmalı.",
}
PLATFORM_ADI = {"tizen": "Samsung Tizen", "webos": "LG webOS", "androidtv": "Android TV / Google TV",
                "dial": "DIAL", "upnp_av": "DLNA/UPnP", "roku": "Roku", "vidaa": "Hisense VIDAA"}
# Salt okunur port imzaları (TCP bağlantı açılır, veri gönderilmez)
PLATFORM_PORTLARI = (("webos", 3000), ("webos", 3001), ("tizen", 8001), ("tizen", 8002),
                     ("androidtv", 6466), ("androidtv", 6467), ("roku", 8060), ("googlecast", 8009))


def genel_mi(icerik: str) -> bool:
    return (icerik or "").strip().lower() in GENEL_SOZCUKLER


def arama_metni(icerik: str) -> str:
    if genel_mi(icerik):
        return GENEL_MUZIK
    try:
        from yerel_ai.medya_oynat import arama_metni as _am  # masaüstü YouTube oynatma tarafıyla aynı
        return _am(icerik)
    except Exception:
        return icerik


def video_bul(icerik: str, zaman_asimi: float = 4.0) -> str | None:
    """YouTube aramasındaki ilk video kimliği (Yumi'nin masaüstü yolu: yerel_ai/medya_oynat.ilk_video)."""
    if not (icerik or "").strip():
        return None
    sorgu = arama_metni(icerik)
    try:
        from yerel_ai.medya_oynat import ilk_video
        return ilk_video(sorgu, zaman_asimi)
    except ImportError:
        pass
    except Exception:
        return None
    try:  # yerel_ai yoksa (bağımsız test) aynı yöntem
        import urllib.parse
        import urllib.request
        url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": sorgu, "hl": "tr", "gl": "TR"})
        istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "tr-TR"})
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as y:
            html = y.read().decode("utf-8", "ignore")
        m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def youtube_mu(ad: str) -> bool:
    a = (ad or "").lower()
    return "youtube" in a and "music" not in a and "kids" not in a


def platform_tespit(bulunan_ya_da_cihaz, acik_portlar: set[int] | None = None) -> list[str]:
    """Kanıtlardan TV platformu adayları (sıra: en güçlü önce). Salt okunur, ağ kullanmaz."""
    adaylar: list[str] = []
    aileler = list(getattr(bulunan_ya_da_cihaz, "aileler", []) or [])
    aile = getattr(bulunan_ya_da_cihaz, "aile", "")
    ek = list(getattr(bulunan_ya_da_cihaz, "ek_aileler", []) or [])
    for a in [aile, *ek, *aileler]:
        if a in ("tizen", "webos", "androidtv", "roku", "vidaa") and a not in adaylar:
            adaylar.append(a)
    metin = " ".join(str(x) for x in (getattr(bulunan_ya_da_cihaz, "marka", ""), getattr(bulunan_ya_da_cihaz, "model", ""),
                                      getattr(bulunan_ya_da_cihaz, "ad", ""))).lower()
    for anahtar, p in (("samsung", "tizen"), ("[tv] samsung", "tizen"), ("lg ", "webos"), ("webos", "webos"),
                       ("bravia", "androidtv"), ("android", "androidtv"), ("google tv", "androidtv"),
                       ("roku", "roku"), ("hisense", "vidaa"), ("vidaa", "vidaa")):
        if anahtar in metin + " " and p not in adaylar:
            adaylar.append(p)
    for p, port in PLATFORM_PORTLARI:
        if acik_portlar and port in acik_portlar and p not in adaylar and p != "googlecast":
            adaylar.append(p)
    return adaylar


__all__ = ["video_bul", "arama_metni", "genel_mi", "youtube_mu", "platform_tespit", "GUC_IPUCU", "PLATFORM_ADI",
           "PLATFORM_PORTLARI", "GENEL_MUZIK"]
