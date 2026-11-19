"""Karakter kişiliği (docs/KARAKTER-PAKETI.md): kisilik.json doğrulama + cilve motoru. Yalnız veri okunur; kod çalıştırılmaz.

Kişilik kaynağı (öncelik): karakter klasörünün kisilik.json'u (models/<kategori>/<karakter>/, karakter.json 'kisilik') -> models/_ortak/kisilik/<ad>.json -> varsayilan.json.
Cilve.sec(durum, **degiskenler) -> (cumle|None, hareket|None). None: cilve yok, Yumi kendi sade cümlesini söyler.
"""
from __future__ import annotations

import json
import random
import re
import time
from collections import defaultdict, deque
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
KISILIK_KLASORU = KOK / "models" / "_ortak" / "kisilik"  # 12 Kasım: karakterin kendi kisilik.json'u kendi klasöründe (karakterler.py)

TONLAR = {"sade", "sicak", "cilveli", "neseli", "kuru", "igneleyici"}
DURUMLAR = {  # durum -> izinli değişkenler
    "muzik_aciliyor": {"ad"}, "alarm_kuruldu": {"saat"}, "gece_alarm": {"saat"}, "sayac_kuruldu": {"sure"},
    "hatirlatici_kuruldu": {"icerik", "zaman"}, "tamam": set(), "tekrar_kis": set(), "anlamadim": set(), "internet_yok": set(), "selam": set(),
}
BAGLAMSAL = {"gece_alarm", "tekrar_kis"}  # bağlama özel: daha sık
HAREKET_ADI = re.compile(r"^[a-z_]{2,24}$")
SEVIYE_OLASILIK = {"sade": 0.0, "dengeli": 0.3, "cilveli": 0.6}
MAKS_CUMLE, MAKS_UZUNLUK, MAKS_DOSYA = 12, 160, 65536


class KisilikHatasi(ValueError):
    pass


def dogrula(veri: dict) -> dict:
    """Kişilik verisini doğrular ve temizlenmiş kopyasını döndürür. Bilinmeyen durum/alan yok sayılır; biçim bozuksa hata."""
    if not isinstance(veri, dict) or veri.get("format") != "yumi-kisilik" or veri.get("surum") != 1:
        raise KisilikHatasi("format 'yumi-kisilik', surum 1 olmalı")
    ton = veri.get("ton", "sicak")
    if ton not in TONLAR:
        raise KisilikHatasi(f"bilinmeyen ton: {ton}")
    try:
        cilve = float(veri.get("cilve", 0.5))
    except (TypeError, ValueError):
        raise KisilikHatasi("cilve 0..1 arası sayı olmalı") from None
    temiz = {"karakter": str(veri.get("karakter", ""))[:40], "ton": ton, "cilve": max(0.0, min(1.0, cilve)), "cumleler": {}, "hareketler": {}}
    for durum, liste in (veri.get("cumleler") or {}).items():
        if durum not in DURUMLAR or not isinstance(liste, list):
            continue
        iyi = []
        for c in liste[:MAKS_CUMLE]:
            if not isinstance(c, str) or not c.strip() or len(c) > MAKS_UZUNLUK:
                continue
            degiskenler = set(re.findall(r"\{(\w+)\}", c))
            if degiskenler - DURUMLAR[durum] or re.search(r"\{[^}]*[^\w}][^}]*\}", c):  # yalnız izinli {ad} biçimi
                continue
            iyi.append(c.strip())
        if iyi:
            temiz["cumleler"][durum] = iyi
    for durum, liste in (veri.get("hareketler") or {}).items():
        if durum in DURUMLAR and isinstance(liste, list):
            h = [x for x in liste[:6] if isinstance(x, str) and HAREKET_ADI.match(x)]
            if h:
                temiz["hareketler"][durum] = h
    return temiz


def oku(yol: Path) -> dict:
    yol = Path(yol)
    if yol.stat().st_size > MAKS_DOSYA:
        raise KisilikHatasi("kişilik dosyası çok büyük")
    return dogrula(json.loads(yol.read_text(encoding="utf-8")))


def _anahtar(ad):
    return re.sub(r"[^a-z0-9ğüşıöç]+", "_", (ad or "").replace("İ", "i").replace("I", "ı").lower()).strip("_")


def karakter_kisiligi(karakter_adi: str | None) -> dict:
    """Karakterin kişiliği; yoksa varsayılan; o da yoksa boş sade kişilik."""
    adaylar = []
    try:
        import karakterler
        kayit = karakterler.karakter_klasoru(karakter_adi)
        if kayit and kayit["veri"].get("kisilik"):
            adaylar.append(kayit["klasor"] / str(kayit["veri"]["kisilik"]))
    except Exception:
        pass
    adaylar += [KISILIK_KLASORU / f"{_anahtar(karakter_adi)}.json", KISILIK_KLASORU / "varsayilan.json"]
    for aday in adaylar:
        try:
            if aday.is_file():
                return oku(aday)
        except (OSError, ValueError):
            continue
    return {"karakter": karakter_adi or "", "ton": "sade", "cilve": 0.0, "cumleler": {}, "hareketler": {}}


class Cilve:
    def __init__(self, kisilik: dict, seviye: str = "dengeli", rastgele=None):
        self.kisilik, self.seviye = kisilik, seviye if seviye in SEVIYE_OLASILIK else "dengeli"
        self.r = rastgele or random.Random()
        self.son = defaultdict(lambda: deque(maxlen=3))
        self._kis = deque(maxlen=3)

    def olasilik(self, durum):
        taban = SEVIYE_OLASILIK[self.seviye]
        if taban == 0:
            return 0.0
        olcek = 0.5 + self.kisilik.get("cilve", 0.5)  # cilve 0.5 -> x1, 1.0 -> x1.5, 0 -> x0.5
        p = taban * olcek
        return min(0.9, p * 2.2) if durum in BAGLAMSAL else min(0.85, p)

    def tekrar_kis_mi(self):
        """Son 2 dakikada üçüncü 'sesi kıs' mı?"""
        simdi = time.monotonic()
        self._kis.append(simdi)
        return len(self._kis) == 3 and simdi - self._kis[0] < 120

    def sec(self, durum, **deg):
        cumleler = self.kisilik.get("cumleler", {}).get(durum, [])
        if not cumleler or self.r.random() >= self.olasilik(durum):
            return None, None
        uygun = [c for c in cumleler if set(re.findall(r"\{(\w+)\}", c)) <= {k for k, v in deg.items() if v}]
        taze = [c for c in uygun if c not in self.son[durum]] or uygun
        if not taze:
            return None, None
        c = self.r.choice(taze)
        self.son[durum].append(c)
        hareketler = self.kisilik.get("hareketler", {}).get(durum, [])
        return c.format(**{k: v for k, v in deg.items() if v}), (self.r.choice(hareketler) if hareketler else None)
