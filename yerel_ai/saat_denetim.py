"""Saat doğruluğu denetimi (salt okunur; sistem ayarı değiştirmez).
- İnternet varken sunucu saati (HTTP Date başlığı) ile bilgisayar saatini karşılaştırır: |fark| > ESIK_S ise uyarır.
- Varsayılan şehrin saat dilimi (Open-Meteo utc_offset_seconds) ile bilgisayarın saat dilimini karşılaştırır.
- Windows'ta otomatik saat (W32Time NTP) ve otomatik saat dilimi (tzautoupdate) açık mı, kayıt defterinden okur.
denetle(sehir_koord=None) -> uyarı cümlesi ya da None (her şey yolunda / internet yok)."""
from __future__ import annotations

import email.utils
import sys
import time
import urllib.request

ESIK_S = 3.0
SUNUCULAR = ["https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&current=temperature_2m", "https://www.cloudflare.com/cdn-cgi/trace"]


def sunucu_farki():
    """Bilgisayar saati - sunucu saati (saniye), ağ gecikmesinin yarısı düzeltilmiş. İnternet yoksa None."""
    for url in SUNUCULAR:
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Yumi-saat"}), timeout=4) as r:
                t1 = time.time()
                tarih = r.headers.get("Date")
            if not tarih:
                continue
            sunucu = email.utils.parsedate_to_datetime(tarih).timestamp() + 0.5  # Date saniyeye yuvarlanmış: ortalama +0,5 s
            return (t0 + t1) / 2 - sunucu
        except Exception:
            continue
    return None


def windows_otomatik():
    """(otomatik_saat, otomatik_dilim) — bilinmiyorsa None."""
    if sys.platform != "win32":
        return None, None
    try:
        import winreg
        def oku(yol, ad):
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, yol) as k:
                return winreg.QueryValueEx(k, ad)[0]
        saat = str(oku(r"SYSTEM\CurrentControlSet\Services\W32Time\Parameters", "Type")).upper() in ("NTP", "ALLSYNC", "NT5DS")
        try:
            dilim = int(oku(r"SYSTEM\CurrentControlSet\Services\tzautoupdate", "Start")) == 3
        except OSError:
            dilim = None
        return saat, dilim
    except Exception:
        return None, None


def yerel_ofset_s():
    return -(time.altzone if time.localtime().tm_isdst > 0 else time.timezone)


def sehir_ofseti(enlem, boylam):
    try:
        import json
        url = f"https://api.open-meteo.com/v1/forecast?latitude={enlem}&longitude={boylam}&current=temperature_2m&timezone=auto"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Yumi-saat"}), timeout=4) as r:
            return int(json.loads(r.read()).get("utc_offset_seconds"))
    except Exception:
        return None


def denetle(sehir_koord=None):
    uyarilar = []
    fark = sunucu_farki()
    otomatik_saat, otomatik_dilim = windows_otomatik()
    if fark is not None and abs(fark) > ESIK_S:
        yon = "ileri" if fark > 0 else "geri"
        s = f"Bilgisayarın saati yaklaşık {abs(fark):.0f} saniye {yon}."
        if otomatik_saat is False:
            s += " Windows Ayarlar > Saat ve dil > Tarih ve saat bölümünden 'Saati otomatik ayarla'yı açmanı öneririm."
        else:
            s += " Windows Ayarlar > Saat ve dil > Tarih ve saat > 'Şimdi eşitle' ile düzeltebilirsin."
        uyarilar.append(s)
    if sehir_koord:
        o = sehir_ofseti(sehir_koord["enlem"], sehir_koord["boylam"])
        if o is not None and o != yerel_ofset_s():
            s = f"Bilgisayarın saat dilimi (UTC{yerel_ofset_s() / 3600:+.0f}) {sehir_koord.get('ad', 'şehrinle')} ile uyuşmuyor (UTC{o / 3600:+.0f})."
            if otomatik_dilim is False:
                s += " 'Saat dilimini otomatik ayarla'yı açmanı öneririm."
            uyarilar.append(s)
    return " ".join(uyarilar) or None
