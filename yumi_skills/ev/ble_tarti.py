"""Bluetooth LE tartı/sensör adaptörü — PASİF: yalnız reklam (advertisement) dinlenir, bağlanılmaz.

Desteklenen reklam biçimleri (servis verisi):
  0x181D (Weight Scale) — Xiaomi Mi Smart Scale 1/2 biçimi: bayt0 bayrak, bayt1-2 ağırlık LE
  0x181B (Body Composition) — Xiaomi Mi Body Composition Scale 2 biçimi: 13 bayt, ağırlık bayt 11-12 LE
Bayrak anlamları openScale/xiaomi-ble topluluk çözümlemelerine göredir (resmî belge değil; gerçek
tartıyla doğrulanmadı). Şifreli MiBeacon (0xFE95, ör. S400) ve GATT bağlantısı isteyen tartılar
bu dilimde yok → 'desteklenmiyor' + not.
"""
from __future__ import annotations

import time
from typing import Any

from .adaptor import Adaptor, kaydet
from .model import DESTEKLENMIYOR, HAZIR, ONDALIK, EvCihazi, Sonuc, Yetenek


def tarti_coz(servis: str, veri: bytes) -> dict[str, Any] | None:
    """Servis verisi → {'kg', 'kararli', 'kaldirildi', 'empedans'?}; tanınmazsa None."""
    servis = servis.lower()
    if servis == "181d" and len(veri) >= 3:
        b = veri[0]
        ham = int.from_bytes(veri[1:3], "little")
        if b & 0x01:          # lbs
            kg = ham / 100 * 0.45359237
        elif b & 0x10:        # jin (catty)
            kg = ham / 100 * 0.5
        else:
            kg = ham / 200
        return {"kg": round(kg, 2), "kararli": bool(b & 0x20), "kaldirildi": bool(b & 0x80), "bicim": "181d"}
    if servis == "181b" and len(veri) == 13:
        b0, b1 = veri[0], veri[1]
        ham = int.from_bytes(veri[11:13], "little")
        lbs = b0 & 0x01
        kg = ham / 100 * 0.45359237 if lbs else ham / 200
        sonuc = {"kg": round(kg, 2), "kararli": bool(b1 & 0x20), "kaldirildi": bool(b1 & 0x80), "bicim": "181b"}
        if b1 & 0x02:
            sonuc["empedans"] = int.from_bytes(veri[9:11], "little")
        return sonuc
    return None


def servis_verisi_coz(metin: str) -> dict[str, bytes]:
    """Bulucu kaydındaki 'ble_servis_verisi' ("181d=02a0...;fe95=...") → {servis: bayt}."""
    sonuc = {}
    for parca in (metin or "").split(";"):
        if "=" in parca:
            k, v = parca.split("=", 1)
            try:
                sonuc[k.strip().lower()] = bytes.fromhex(v.strip())
            except ValueError:
                pass
    return sonuc


@kaydet
class BleTartiAdaptoru(Adaptor):
    aile = "ble_tarti"

    def __init__(self, *a, tarayici=None, **k):
        super().__init__(*a, **k)
        self.tarayici = tarayici  # test: callable(sure, adres) -> list[(servis, bayt)]

    def uygun_mu(self, bulunan):
        sv = servis_verisi_coz(bulunan.alan("ble_servis_verisi"))
        return "181d" in sv or "181b" in sv or "fe95" in sv and "scale" in (bulunan.ad or "").lower()

    def cihaz_olustur(self, bulunan):
        adres = bulunan.alan("ble_adres")
        c = EvCihazi(kimlik=f"ble:{adres}", ad=bulunan.ad or "Tartı", tur="sensor", aile=self.aile,
                     adres="", mac=adres)
        sv = servis_verisi_coz(bulunan.alan("ble_servis_verisi"))
        olcum = next((tarti_coz(s, v) for s, v in sv.items() if tarti_coz(s, v)), None)
        if olcum:
            c.erisim, c.erisim_notu = HAZIR, "pasif BLE reklamı; tartıya çıkınca okunur"
            c.protokol = {"son_olcum": olcum, "son_olcum_zamani": time.strftime("%Y-%m-%d %H:%M:%S")}
        else:
            c.erisim, c.erisim_notu = DESTEKLENMIYOR, "şifreli MiBeacon/GATT tartı; bu dilimde çözücü yok"
        return c

    def yetenekler(self, cihaz):
        if cihaz.erisim != HAZIR:
            return {}
        y = Yetenek("olcum_agirlik", ONDALIK, True, False, 0, 200, 0.05, "kg",
                    kaynak="BLE reklam servis verisi " + cihaz.protokol.get("son_olcum", {}).get("bicim", ""),
                    guven="tahmin")
        cihaz.yetenek_ekle(y)
        return {"olcum_agirlik": y}

    def durum(self, cihaz, sure: float = 8.0):
        """Kısa pasif tarama; son KARARLI ölçüm döner (tartıya o sırada çıkılmış olmalı)."""
        okumalar = []
        if self.tarayici is not None:
            okumalar = self.tarayici(sure, cihaz.mac)
        else:
            from ..cihaz_yoklayicilar import BleYoklayici
            import threading
            for k in BleYoklayici(sure).calistir(time.monotonic() + sure, threading.Event()):
                if k.alanlar.get("ble_adres", "").upper() == cihaz.mac.upper():
                    okumalar += list(servis_verisi_coz(k.alanlar.get("ble_servis_verisi", "")).items())
        for s, v in okumalar:
            o = tarti_coz(s, v)
            if o and o["kararli"] and not o["kaldirildi"]:
                cihaz.protokol["son_olcum"] = o
                return {"olcum_agirlik": o["kg"]}
        son = cihaz.protokol.get("son_olcum")
        return {"olcum_agirlik": son["kg"], "eski": True} if son else {}

    def _uygula(self, cihaz, y, deger):
        return Sonuc(False, "tartı yalnız okunur")
