"""Protokol adaptörü ortak arayüzü ve eklenti kaydı.

Her aile küçük bir adaptördür:
    kesfet(tarama)            -> list[EvCihazi]   (bulucu sonucundan kendi cihazlarını çıkarır)
    yetenekler(cihaz)         -> dict[str, Yetenek]  (CİHAZDAN SORGULANIR; cihaz.erisim'i günceller)
    durum(cihaz)              -> dict[str, Any]   (yalnız okuma)
    uygula(cihaz, ad, deger)  -> Sonuc            (yazma; Tasima yazma kilidine tabidir)
Yeni aile = yeni modül + ``@kaydet``; çekirdek değişmez.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .model import DESTEKLENMIYOR, EvCihazi, Sonuc, Yetenek
from .tasima import Tasima, YazmaKilitli

ADAPTORLER: dict[str, type["Adaptor"]] = {}


def kaydet(sinif: type["Adaptor"]) -> type["Adaptor"]:
    ADAPTORLER[sinif.aile] = sinif
    return sinif


class Adaptor:
    aile = ""
    bulucu_aileleri: tuple[str, ...] = ()   # cihaz_bulucu aileleri (BulunanCihaz.aileler içinde aranır)

    def __init__(self, tasima: Tasima | None = None, sirlar: Callable[[EvCihazi], dict] | None = None):
        self.tasima = tasima or Tasima()
        # sirlar(cihaz) -> {"anahtar": ..., "istemci_anahtari": ...}; DPAPI'li depodan okunur, kayda yazılmaz
        self.sirlar = sirlar or (lambda cihaz: {})

    # -- keşif
    def uygun_mu(self, bulunan) -> bool:
        return any(a in self.bulucu_aileleri for a in getattr(bulunan, "aileler", []))

    def cihaz_olustur(self, bulunan) -> EvCihazi | None:
        raise NotImplementedError

    def kesfet(self, tarama=None) -> list[EvCihazi]:
        if tarama is None:
            from ..cihaz_bulucu import kesfet as _kesfet
            tarama = _kesfet()
        cihazlar = []
        for b in tarama.cihazlar:
            if self.uygun_mu(b):
                c = self.cihaz_olustur(b)
                if c is not None:
                    c.son_gorulme = time.strftime("%Y-%m-%d %H:%M:%S")
                    cihazlar.append(c)
        return cihazlar

    # -- yetenek / durum / uygula
    def yetenekler(self, cihaz: EvCihazi) -> dict[str, Yetenek]:
        return {}

    def durum(self, cihaz: EvCihazi) -> dict[str, Any]:
        return {}

    def uygula(self, cihaz: EvCihazi, yetenek: str, deger: Any = None) -> Sonuc:
        y = cihaz.yetenekler.get(yetenek)
        if y is None:
            return Sonuc(False, f"{cihaz.gorunen_ad}: '{yetenek}' yeteneği yok")
        try:
            gecerli = y.deger_dogrula(deger)
            return self._uygula(cihaz, y, gecerli)
        except YazmaKilitli as e:
            return Sonuc(False, str(e))
        except (ValueError, NotImplementedError) as e:
            return Sonuc(False, str(e))
        except Exception as e:  # ağ/cihaz hatası başarı gibi gösterilmez
            return Sonuc(False, f"{cihaz.gorunen_ad}: {type(e).__name__}: {e}")

    def _uygula(self, cihaz: EvCihazi, y: Yetenek, deger: Any) -> Sonuc:
        raise NotImplementedError(f"{self.aile}: '{y.ad}' yazma desteklenmiyor")


def kimlik_sec(*adaylar: str) -> str:
    return next((a for a in adaylar if a), "")


def bos_cihaz(bulunan, aile: str, kimlik: str) -> EvCihazi:
    return EvCihazi(kimlik=kimlik, ad=bulunan.ad or bulunan.adres, tur=bulunan.tur, aile=aile,
                    adres=bulunan.adres, mac=getattr(bulunan, "mac", ""), marka=bulunan.marka,
                    model=bulunan.model, erisim=DESTEKLENMIYOR)


def pydeps_ekle() -> None:
    """İsteğe bağlı paket klasörünü (lib/ev/pydeps; bleak, tinytuya) sys.path SONUNA ekler (.venv önceliklidir)."""
    import sys
    try:
        from ..cihaz_yoklayicilar import PYDEPS
    except Exception:
        return
    if PYDEPS.is_dir() and str(PYDEPS) not in sys.path:
        sys.path.append(str(PYDEPS))
