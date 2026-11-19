"""Ev cihazı sırları (webOS istemci anahtarı, Tizen belirteci, Tuya yerel anahtarı, miIO token, Roomba
parolası): data/ev_sirlar.json, her değer Yumi'nin mevcut DPAPI biçimiyle ("dpapi:v1:<base64>",
cekirdek/platform_win.protect — yumi_skills/storage.py ile aynı) şifreli tutulur.

Kayıt json'una (ev_cihazlari.json) hiçbir sır yazılmaz. DPAPI yoksa (Windows dışı/test) sırlar
yalnız bellekte tutulur ve diske YAZILMAZ (açık metin sır asla kaydedilmez).
"""
from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Callable

ONEK = "dpapi:v1:"


def _dpapi() -> tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]] | None:
    try:
        from platform_win import protect, unprotect
        return protect, unprotect
    except Exception:
        return None


class SirDeposu:
    def __init__(self, yol: str | Path | None, sifreleyici: tuple[Callable, Callable] | None | str = "varsayilan"):
        self.yol = Path(yol) if yol else None
        self.sifre = _dpapi() if sifreleyici == "varsayilan" else sifreleyici
        self._kilit = threading.RLock()
        self._veri: dict[str, dict[str, str]] = {}
        self._yukle()

    @property
    def kalici(self) -> bool:
        return bool(self.yol and self.sifre)

    def _yukle(self) -> None:
        if not self.kalici or not self.yol.exists():
            return
        try:
            ham = json.loads(self.yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        _, coz = self.sifre
        for kimlik, alanlar in (ham.get("cihazlar") or {}).items():
            acik = {}
            for k, v in (alanlar or {}).items():
                if isinstance(v, str) and v.startswith(ONEK):
                    try:
                        acik[k] = coz(base64.b64decode(v[len(ONEK):], validate=True)).decode("utf-8")
                    except Exception:
                        continue  # başka Windows hesabı: o sır yok sayılır, dosya korunur
            if acik:
                self._veri[kimlik] = acik

    def _kaydet(self) -> None:
        if not self.kalici:
            return
        sifrele, _ = self.sifre
        disari = {k: {a: ONEK + base64.b64encode(sifrele(v.encode("utf-8"))).decode("ascii")
                      for a, v in alanlar.items() if v}
                  for k, alanlar in self._veri.items()}
        from .kayit import _atomik_yaz
        _atomik_yaz(self.yol, {"surum": 1, "cihazlar": disari})

    def al(self, cihaz) -> dict[str, str]:
        """Cihazın tüm sırları (kimlik ve yan kimlikler birleşik)."""
        with self._kilit:
            sonuc: dict[str, str] = {}
            for k in [*getattr(cihaz, "yan_kimlikler", []), cihaz.kimlik]:
                sonuc.update(self._veri.get(k, {}))
            return sonuc

    def yaz(self, cihaz, **alanlar: str) -> None:
        with self._kilit:
            hedef = self._veri.setdefault(cihaz.kimlik, {})
            for k, v in alanlar.items():
                if v:
                    hedef[k] = str(v)
                else:
                    hedef.pop(k, None)
            self._kaydet()

    def sil(self, cihaz) -> None:
        with self._kilit:
            for k in [cihaz.kimlik, *getattr(cihaz, "yan_kimlikler", [])]:
                self._veri.pop(k, None)
            self._kaydet()

    def var_mi(self, cihaz, alan: str) -> bool:
        return bool(self.al(cihaz).get(alan))
