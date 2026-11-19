"""Yeelight LAN adaptörü (TCP 55443, JSON satır protokolü) — kullanıcı Yeelight uygulamasında 'LAN kontrolü'nü açmalı.

Keşif: bulucunun Yeelight M-SEARCH yanıtı. Yetenekler cihazın KENDİ bildirdiği 'support' yöntem listesinden
çıkarılır (set_power → guc, set_bright → parlaklık, set_ct_abx → renk sıcaklığı, set_rgb → renk).
Okuma: get_prop. Yazma Tasima yazma kilidine tabidir. LAN kontrolü kapalıysa TCP bağlantısı reddedilir.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import BOOL, ESLESTIRME_GEREKLI, HAZIR, METIN, TAMSAYI, Sonuc, Yetenek


def destek_yetenekleri(destek: str) -> dict[str, Yetenek]:
    yontemler = set((destek or "").split())
    k = "Yeelight support"
    yet: dict[str, Yetenek] = {}
    if "set_power" in yontemler:
        yet["guc"] = Yetenek("guc", BOOL, "get_prop" in yontemler, True, kaynak=k + " set_power")
    if "set_bright" in yontemler:
        yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, "get_prop" in yontemler, True, 1, 100, 1, "%",
                                   kaynak=k + " set_bright")
    if "set_ct_abx" in yontemler:
        yet["renk_sicakligi"] = Yetenek("renk_sicakligi", TAMSAYI, "get_prop" in yontemler, True, 1700, 6500, 100, "K",
                                        kaynak=k + " set_ct_abx")
    if "set_rgb" in yontemler:
        yet["renk"] = Yetenek("renk", METIN, False, True, kaynak=k + " set_rgb (onaltılık RRGGBB)")
    return yet


@kaydet
class YeelightAdaptoru(Adaptor):
    aile = "yeelight"
    bulucu_aileleri = ("yeelight",)

    def uygun_mu(self, bulunan):
        return bool(bulunan.alan("yeelight_destek"))

    def cihaz_olustur(self, bulunan):
        kimlik = bulunan.alan("cihaz_kimligi")
        c = bos_cihaz(bulunan, self.aile, f"yeelight:{kimlik or bulunan.adres}")
        c.tur, c.marka = "light", "Yeelight"
        c.model = bulunan.alan("model") or c.model
        c.protokol = {"yeelight_destek": bulunan.alan("yeelight_destek")}
        c.erisim, c.erisim_notu = HAZIR, "Yeelight LAN kontrolü"
        return c

    def _komut(self, cihaz, yontem: str, parametreler: list) -> list:
        istek = json.dumps({"id": 1, "method": yontem, "params": parametreler}).encode() + b"\r\n"
        ham = self.tasima.tcp_istek(cihaz.adres, 55443, istek, yazma=not yontem.startswith("get_"))
        for satir in ham.decode("utf-8", "replace").splitlines():
            js = json.loads(satir) if satir.strip().startswith("{") else {}
            if js.get("id") == 1:
                if "error" in js:
                    raise RuntimeError(f"Yeelight: {js['error'].get('message', js['error'])}")
                return js.get("result", [])
        return []

    def yetenekler(self, cihaz):
        yet = destek_yetenekleri(cihaz.protokol.get("yeelight_destek", ""))
        try:
            self._komut(cihaz, "get_prop", ["power"])
        except ConnectionRefusedError:
            cihaz.erisim, cihaz.erisim_notu = ESLESTIRME_GEREKLI, "Yeelight uygulamasında 'LAN kontrolü'nü aç"
            return {}
        cihaz.erisim, cihaz.erisim_notu = HAZIR, "Yeelight LAN kontrolü açık"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        r = self._komut(cihaz, "get_prop", ["power", "bright", "ct"])
        d: dict[str, Any] = {}
        if len(r) >= 1:
            d["guc"] = r[0] == "on"
        if len(r) >= 2 and str(r[1]).isdigit():
            d["parlaklik"] = int(r[1])
        if len(r) >= 3 and str(r[2]).isdigit():
            d["renk_sicakligi"] = int(r[2])
        return d

    def _uygula(self, cihaz, y, deger):
        if y.ad == "guc":
            self._komut(cihaz, "set_power", ["on" if deger else "off", "smooth", 300])
        elif y.ad == "parlaklik":
            self._komut(cihaz, "set_bright", [int(deger), "smooth", 300])
        elif y.ad == "renk_sicakligi":
            self._komut(cihaz, "set_ct_abx", [int(deger), "smooth", 300])
        elif y.ad == "renk":
            hex_ = re.sub(r"[^0-9a-fA-F]", "", str(deger))[:6]
            self._komut(cihaz, "set_rgb", [int(hex_ or "ffffff", 16), "smooth", 300])
            return Sonuc(True, f"Renk {hex_}")
        else:
            return super()._uygula(cihaz, y, deger)
        geri = self.durum(cihaz).get(y.ad)
        return Sonuc(geri == deger, f"{y.etiket}: {geri}", geri, geri == deger)
