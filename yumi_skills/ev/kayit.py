"""Kalıcı ev cihazı kaydı: data/ev_cihazlari.json (sır içermez; anahtarlar sirlar.py'de DPAPI ile).

Yeniden eşleştirme: tarama yeni EvCihazi listesi getirdiğinde her biri kayıttaki cihazla şu sırayla
eşlenir: kalıcı kimlik (UDN, BLE adresi, Tuya gwId, miIO kimliği) → yan kimlikler → MAC → (son çare)
aynı adres + aynı aile. Eşleşen kayıtta kullanıcının verdiği ad, oda ve takma adlar KORUNUR;
adres/yetenek/erişim gibi cihazdan gelen alanlar güncellenir. IP değişse de cihaz aynı kalır.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable

from .model import EvCihazi

KULLANICI_ALANLARI = ("kullanici_adi", "oda", "takma_adlar")
SURUM = 1


def _atomik_yaz(yol: Path, veri: dict) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    try:  # Yumi'nin ortak atomik yazıcısı (.bak yedekli) varsa onu kullan
        from durable_json import atomic_json_write
        atomic_json_write(yol, veri, keep_backup=True)
        return
    except ImportError:
        pass
    fd, gecici = tempfile.mkstemp(prefix=yol.name, dir=str(yol.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def _mac(m: str) -> str:
    m = (m or "").upper().replace("-", ":")
    return m if len(m) == 17 else ""


class CihazKaydi:
    def __init__(self, yol: str | Path | None):
        self.yol = Path(yol) if yol else None
        self._kilit = threading.RLock()
        self.cihazlar: dict[str, EvCihazi] = {}
        self.yukle()

    # -- dosya
    def yukle(self) -> None:
        with self._kilit:
            self.cihazlar = {}
            if not self.yol or not self.yol.exists():
                return
            try:
                veri = json.loads(self.yol.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                yedek = self.yol.with_name(self.yol.name + ".bak")
                if not yedek.exists():
                    raise
                veri = json.loads(yedek.read_text(encoding="utf-8"))
            for c in veri.get("cihazlar", []):
                try:
                    cihaz = EvCihazi.sozlukten(c)
                except TypeError:
                    continue
                self.cihazlar[cihaz.kimlik] = cihaz

    def kaydet(self) -> None:
        if not self.yol:
            return
        with self._kilit:
            _atomik_yaz(self.yol, {"surum": SURUM, "guncelleme": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "cihazlar": [c.sozluk() for c in self.cihazlar.values()]})

    # -- sorgu
    def tumu(self) -> list[EvCihazi]:
        with self._kilit:
            return list(self.cihazlar.values())

    def al(self, kimlik: str) -> EvCihazi | None:
        return self.cihazlar.get(kimlik)

    def esle(self, yeni: EvCihazi) -> EvCihazi | None:
        """Yeni taramadaki cihazın kayıttaki karşılığı (yoksa None)."""
        with self._kilit:
            if yeni.kimlik in self.cihazlar:
                return self.cihazlar[yeni.kimlik]
            yeni_kimlikler = {yeni.kimlik, *yeni.yan_kimlikler}
            for c in self.cihazlar.values():
                if yeni_kimlikler & {c.kimlik, *c.yan_kimlikler}:
                    return c
            m = _mac(yeni.mac)
            if m:
                for c in self.cihazlar.values():
                    if _mac(c.mac) == m:
                        return c
            if yeni.adres:
                for c in self.cihazlar.values():
                    if c.adres == yeni.adres and c.aile == yeni.aile and not _mac(c.mac) and not _mac(yeni.mac):
                        return c
            return None

    # -- güncelleme
    def guncelle(self, yeniler: Iterable[EvCihazi]) -> list[EvCihazi]:
        """Tarama sonucunu kayda işler; kullanıcı alanları korunur. Güncel cihaz listesi döner."""
        sonuc = []
        with self._kilit:
            for y in yeniler:
                eski = self.esle(y)
                if eski is not None:
                    for alan in KULLANICI_ALANLARI:
                        setattr(y, alan, getattr(eski, alan))
                    # eski kimlik farklıysa (ör. önce IP ile, şimdi UDN ile) yan kimlik olarak tutulur
                    y.yan_kimlikler = sorted({*y.yan_kimlikler, *eski.yan_kimlikler,
                                              *([eski.kimlik] if eski.kimlik != y.kimlik else [])})
                    if not y.mac and eski.mac:
                        y.mac = eski.mac
                    # cihazdan bu kez okunamayan kalıcı protokol bilgisi (ör. TLS parmak izi) korunur
                    for k, v in eski.protokol.items():
                        y.protokol.setdefault(k, v)
                    if not y.yetenekler and eski.yetenekler:
                        y.yetenekler = eski.yetenekler
                    self.cihazlar.pop(eski.kimlik, None)
                self.cihazlar[y.kimlik] = y
                sonuc.append(y)
            self.kaydet()
        return sonuc

    def ekle(self, cihaz: EvCihazi) -> None:
        with self._kilit:
            self.cihazlar[cihaz.kimlik] = cihaz
            self.kaydet()

    def ad_ver(self, kimlik: str, ad: str | None = None, oda: str | None = None,
               takma_adlar: list[str] | None = None) -> EvCihazi:
        with self._kilit:
            c = self.cihazlar[kimlik]
            if ad is not None:
                c.kullanici_adi = ad.strip()
            if oda is not None:
                c.oda = oda.strip()
            if takma_adlar is not None:
                c.takma_adlar = [t.strip() for t in takma_adlar if t.strip()]
            self.kaydet()
            return c

    def sil(self, kimlik: str) -> bool:
        with self._kilit:
            var = self.cihazlar.pop(kimlik, None) is not None
            if var:
                self.kaydet()
            return var
