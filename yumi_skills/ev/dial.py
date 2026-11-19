"""DIAL adaptörü: TV'de kurulu uygulamaları sorgular (GET) ve uygulama başlatır (POST).

Uygulama listesi cihazdan sorgulanır: cihazın Application-URL'ü altında bilinen uygulama
adlarına GET; 200 dönenler kurulu sayılır (DIAL 2.x, 404 = yok). Eşleştirme gerekmez.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import HAZIR, SECIM, Sonuc, Yetenek
from .tasima import TasimaHatasi

# DIAL kayıt defterindeki yaygın adlar (yalnız SORGU listesi; cihaz yanıtı belirleyicidir)
BILINEN_UYGULAMALAR = ("YouTube", "Netflix", "AmazonInstantVideo", "Spotify", "PrimeVideo", "Disney+",
                       "Twitch", "Plex", "Kodi", "Tidal")
TURKCE_AD = {"YouTube": "youtube", "Netflix": "netflix", "AmazonInstantVideo": "prime video",
             "PrimeVideo": "prime video", "Spotify": "spotify", "Disney+": "disney"}


def dial_durumu_coz(veri: bytes) -> str:
    try:
        kok = ET.fromstring(veri)
    except ET.ParseError:
        return ""
    return next((e.text or "" for e in kok.iter() if e.tag.split("}")[-1] == "state"), "")


@kaydet
class DialAdaptoru(Adaptor):
    aile = "dial"
    bulucu_aileleri = ("dial",)

    def uygun_mu(self, bulunan):
        return bool(bulunan.alan("dial_url"))

    def cihaz_olustur(self, bulunan):
        c = bos_cihaz(bulunan, self.aile, bulunan.alan("udn") or f"dial:{bulunan.adres}")
        c.protokol = {"dial_url": bulunan.alan("dial_url").rstrip("/") + "/"}
        c.erisim, c.erisim_notu = HAZIR, "DIAL: yalnız uygulama başlatma (güç/ses değil)"
        return c

    def yetenekler(self, cihaz):
        kok = cihaz.protokol["dial_url"]
        kurulu, durumlar = [], {}
        for ad in BILINEN_UYGULAMALAR:
            try:
                kod, _, govde = self.tasima.get(kok + ad, sinir=16_384)
            except (OSError, TasimaHatasi):
                continue
            if kod == 200:
                kurulu.append(ad)
                durumlar[ad] = dial_durumu_coz(govde)
        cihaz.protokol["dial_uygulama_durumu"] = durumlar
        if not kurulu:
            return {}
        y = Yetenek("uygulama", SECIM, True, True, secenekler=kurulu,
                    kaynak="DIAL GET <Application-URL>/<ad> (bilinen DIAL adları yoklandı, 200=kurulu)",
                    protokol={"dial": True, "liste_kaynagi": "tablo"})
        cihaz.yetenek_ekle(y)
        return {"uygulama": y}

    def durum(self, cihaz):
        acik = []
        for ad in cihaz.yetenekler.get("uygulama", Yetenek("", SECIM)).secenekler:
            kod, _, govde = self.tasima.get(cihaz.protokol["dial_url"] + ad, sinir=16_384)
            if kod == 200 and dial_durumu_coz(govde) == "running":
                acik.append(ad)
        return {"uygulama": acik[0] if acik else ""}

    def _dial_adi(self, cihaz, ad: str) -> str:
        durumlar = cihaz.protokol.get("dial_uygulama_durumu", {}) or {}
        for aday in (*durumlar, *BILINEN_UYGULAMALAR):
            if aday.lower() == (ad or "").lower() or (ad and ad.lower().startswith(aday.lower())):
                return aday
        return ad

    def uygulama_yollari(self, cihaz, ad: str, video: str | None = None):
        dad = self._dial_adi(cihaz, ad)
        durum = (cihaz.protokol.get("dial_uygulama_durumu", {}) or {}).get(dad, "")
        if dad not in BILINEN_UYGULAMALAR and not durum:
            return []
        if durum.startswith("installable"):
            return []  # TV'de kurulu değil (DIAL 'installable')
        govde = f"v={video}".encode() if video and dad == "YouTube" else b""

        def ac():
            kod, _, _ = self.tasima.istek("POST", cihaz.protokol["dial_url"] + dad, govde,
                                          {"Content-Type": "text/plain; charset=utf-8"})
            return Sonuc(kod in (200, 201), f"DIAL {dad} başlatma: HTTP {kod}")
        return [(f"DIAL {dad}" + (" (video)" if govde else ""), bool(govde), ac)]

    def uygulama_calisiyor(self, cihaz, ad: str):
        try:
            kod, _, govde = self.tasima.get(cihaz.protokol["dial_url"] + self._dial_adi(cihaz, ad), sinir=16_384)
        except Exception:
            return None
        return kod == 200 and dial_durumu_coz(govde) == "running"

    def _uygula(self, cihaz, y, deger):
        kod, _, _ = self.tasima.istek("POST", cihaz.protokol["dial_url"] + deger, b"",
                                      {"Content-Type": "text/plain; charset=utf-8"})
        return Sonuc(kod in (200, 201), f"{deger} başlatma isteği: HTTP {kod}")
