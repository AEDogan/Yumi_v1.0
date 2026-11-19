"""Yumi bağlantısı (Qt'siz): süreç içi tek EvYoneticisi + yerel komut yönlendiricisi için ev komutu işleyicisi.

- ``yonetici_al(beceri=None)``: data/ev_cihazlari.json + data/ev_sirlar.json ile tek yönetici; SmartHomeSkill
  verilirse bağlanır (kayıtlı eski cihazlar ortak modele girer).
- ``EvKomutlari.isle(metin)``: yerel_ai/yonlendirici.py çağırır (niyet modelinden ÖNCE; Gemini'ye gitmez).
  Dönüş: None (ev komutu değil → eski yol) | ("soyle", metin) | ("soyle_is", çağrılabilir → metin).
  Belirsizlikte "hangisi?" sorar; bir sonraki cevapta cihaz adını/ sırasını ("ilki", "ikincisi") kabul eder.
Yazma: Yumi çalışırken kullanıcı komutu cihaza gider (Tasima yazma=True). YUMI_EV_SALT_OKUNUR=1 ise kapalı.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import komut as K
from .model import EvCihazi, Sonuc
from .tasima import Tasima

_KILIT = threading.Lock()
_YONETICI = None
BEKLEME_S = 40
TEKRAR_S = 300  # 18 Kas: "tekrar dene / yine olmadı" son ev komutunu bu süre içinde yeniden dener
TEKRAR = re.compile(r"^(?:(?:hadi|bir|lütfen|ya|o|yine|hala|hâlâ|tv|televizyon|açılmadı|olmadı|çalışmadı|çalmadı|"
                    r"gelmedi|açmadı|tekrar|yeniden|daha|kez|sefer|dene|deneyin|denesene|denermisin|denermisin|"
                    r"dener|misin|mısın|bakar|bak|et|yap|aynısını|şimdi)\s*)+$")
TEKRAR_ANAHTAR = re.compile(r"\b(tekrar|yeniden|bir daha|bir kez daha|yine olmadı|olmadı|açılmadı|çalışmadı|dene)\b")


def veri_klasoru() -> Path:
    try:
        from app_paths import data_dir
        return data_dir()
    except Exception:
        return Path(__file__).resolve().parents[2] / "data"


def yonetici_al(beceri=None):
    global _YONETICI
    with _KILIT:
        if _YONETICI is None:
            from .yonetici import EvYoneticisi
            yazma = os.environ.get("YUMI_EV_SALT_OKUNUR", "") not in ("1", "evet", "true")
            _YONETICI = EvYoneticisi(veri_klasoru(), tasima=Tasima(yazma=yazma))
        if beceri is not None:
            _YONETICI.beceri_bagla(beceri)
        return _YONETICI


def tum_cihazlar(y) -> list[EvCihazi]:
    """Kayıttaki cihazlar + kayıtta olmayan eski SmartHomeSkill cihazları (diske yazmadan)."""
    kayitli = y.kayit.tumu()
    try:
        ek = y._beceri_cihazlari([])
    except Exception:
        ek = []
    for b in ek:
        if not any(y._ayni(c, b) or (b.adres and c.adres == b.adres) for c in kayitli):
            kayitli.append(b)
    return kayitli


SIRA = {"ilk": 0, "birinci": 0, "bir": 0, "ikinci": 1, "iki": 1, "üçüncü": 2, "üç": 2, "son": -1, "sonuncu": -1}


class EvKomutlari:
    def __init__(self, yonetici=None, beceri=None):
        self._y = yonetici
        self._beceri = beceri
        self.bekleyen: dict[str, Any] | None = None
        self.son_komut: dict[str, Any] | None = None

    @property
    def y(self):
        if self._y is None:
            self._y = yonetici_al(self._beceri)
        return self._y

    # ------------------------------------------------------------ giriş
    def isle(self, metin: str):
        try:
            cihazlar = tum_cihazlar(self.y)
        except Exception:
            return None
        if self.bekleyen and time.monotonic() - self.bekleyen["t"] > BEKLEME_S:
            self.bekleyen = None
        if self.bekleyen:
            cevap = self._bekleyen_cevap(metin)
            if cevap is not None:
                return cevap
        tekrar = self._tekrar(metin)
        if tekrar is not None:
            return tekrar
        k = K.cozumle(metin, cihazlar)
        if k.durum == "ev_degil":
            self.son_komut = None  # konu değişti: sonraki "tekrar dene" ev komutu sayılmaz
            return None
        return self._sonuc(k, metin)

    def _tekrar(self, metin: str):
        """'açılmadı tekrar dene', 'yine olmadı', 'bir daha' → son ev komutunu yeniden dener (Gemini'ye gitmez)."""
        m = K._temiz(metin)
        son = getattr(self, "son_komut", None)
        if not m or not TEKRAR_ANAHTAR.search(m) or not TEKRAR.match(m) or len(m.split()) > 7:
            return None
        if not son or time.monotonic() - son["t"] > TEKRAR_S:
            return None  # yakın zamanda ev komutu yok: başka konu olabilir, eski yola kalsın
        sonuc = self._sonuc(son["k"], son["metin"])
        if sonuc and sonuc[0] == "soyle_is":
            is_ = sonuc[1]
            return ("soyle_is", lambda: "Tekrar denedim. " + is_())
        return sonuc

    def _bekleyen_cevap(self, metin: str):
        m = K._temiz(metin)
        adaylar: list[EvCihazi] = self.bekleyen["adaylar"]
        secilen = [c for c in adaylar if K._ad_eslesir(m, c.gorunen_ad) or (c.oda and K._ad_eslesir(m, c.oda))]
        if not secilen:
            for kelime, i in SIRA.items():
                if re.search(rf"\b{kelime}\w*\b", m) and len(m.split()) <= 3:
                    secilen = [adaylar[i]]
                    break
        if re.match(r"^(hiçbiri|vazgeç|iptal|boş ?ver)", m):
            self.bekleyen = None
            return ("soyle", "Tamam, vazgeçtim.")
        if len(secilen) != 1:
            return None  # cevap değil: normal akış
        onceki = self.bekleyen["metin"]
        self.bekleyen = None
        k = K.cozumle(onceki, [secilen[0]])
        if k.durum == "sor":
            k = K.cozumle(onceki + " " + secilen[0].gorunen_ad, [secilen[0]])
        return self._sonuc(k, onceki)

    def _sonuc(self, k: K.Komut, metin: str):
        if k.durum == "sor":
            self.bekleyen = {"metin": metin, "adaylar": k.adaylar, "t": time.monotonic()}
            return ("soyle", k.soru)
        if k.durum != "tamam":
            return ("soyle", k.soru or "Anlayamadım.")
        self.son_komut = {"k": k, "metin": metin, "t": time.monotonic()}
        y = self.y

        def is_():
            sonuclar = []
            for c in k.cihazlar:
                try:
                    if k.okuma:
                        d = y.durum(c)
                        v = d.get(k.yetenek)
                        if v is None and k.yetenek == "olcum_agirlik":
                            v = (c.protokol.get("son_olcum") or {}).get("kg")
                        sonuclar.append(Sonuc(v is not None, "" if v is not None else
                                              f"{c.gorunen_ad}: değer okunamadı", v))
                    else:
                        if k.yetenek == "uygulama" and k.icerik:
                            sonuclar.append(y.uygula(c, k.yetenek, k.deger, adim=k.adim, goreli=k.goreli,
                                                     icerik=k.icerik))
                        else:
                            sonuclar.append(y.uygula(c, k.yetenek, k.deger, adim=k.adim, goreli=k.goreli))
                except Exception as e:  # cihaz hatası başarı gibi gösterilmez
                    sonuclar.append(Sonuc(False, f"{c.gorunen_ad}: {type(e).__name__}"))
            return K.yanit_metni(k, sonuclar)
        return ("soyle_is", is_)


__all__ = ["yonetici_al", "EvKomutlari", "tum_cihazlar", "veri_klasoru"]
