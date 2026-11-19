"""TP-Link Kasa (eski yerel protokol, TCP 9999, XOR şifreleme) adaptörü — anahtar/hesap gerekmez.

Keşif: bulucunun Kasa sysinfo yayın yanıtı. Yetenekler cihazın kendi get_sysinfo yanıtından SORGULANIR:
relay_state → guc (priz), light_state → guc + parlaklık (ampul), is_dimmable → parlaklık (dimmer),
feature 'ENE' → anlık güç (emeter). Yeni Tapo cihazları (KLAP, TP-Link hesabı) bu yoldan yanıt vermez;
onlar mevcut SmartHomeSkill (tapo) sarmalayıcısıyla gelir.
"""
from __future__ import annotations

import json
import socket
import struct
from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import BOOL, HAZIR, ONDALIK, TAMSAYI, Sonuc, Yetenek
from .tasima import TasimaHatasi, ev_agi_adresi


def sifrele(veri: bytes) -> bytes:
    anahtar, cikti = 171, bytearray()
    for b in veri:
        anahtar ^= b
        cikti.append(anahtar)
    return bytes(cikti)


def coz(veri: bytes) -> bytes:
    anahtar, cikti = 171, bytearray()
    for b in veri:
        cikti.append(anahtar ^ b)
        anahtar = b
    return bytes(cikti)


OKUMA_KOMUTLARI = ("get_sysinfo", "get_realtime")


def sysinfo_yetenekleri(bilgi: dict) -> dict[str, Yetenek]:
    k = "Kasa get_sysinfo"
    yet: dict[str, Yetenek] = {}
    if "relay_state" in bilgi:
        yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " relay_state", protokol={"tip": "priz"})
        if str(bilgi.get("is_dimmable", 0)) == "1" or "brightness" in bilgi:
            yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, True, True, 1, 100, 1, "%", kaynak=k + " brightness",
                                       protokol={"tip": "dimmer"})
    elif "light_state" in bilgi:
        yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " light_state", protokol={"tip": "ampul"})
        if str(bilgi.get("is_dimmable", 1)) == "1":
            yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, True, True, 1, 100, 1, "%", kaynak=k + " light_state",
                                       protokol={"tip": "ampul"})
    if "ENE" in str(bilgi.get("feature", "")):
        yet["olcum_guc"] = Yetenek("olcum_guc", ONDALIK, True, False, birim="W", kaynak="Kasa emeter get_realtime")
    return yet


@kaydet
class KasaAdaptoru(Adaptor):
    aile = "kasa"
    bulucu_aileleri = ("tplink",)

    def __init__(self, *a, gonderici=None, **k):
        super().__init__(*a, **k)
        self.gonderici = gonderici  # test: (adres, dict) -> dict

    def uygun_mu(self, bulunan):
        return bool(bulunan.alan("kasa_sysinfo"))

    def cihaz_olustur(self, bulunan):
        bilgi = json.loads(bulunan.alan("kasa_sysinfo") or "{}")
        c = bos_cihaz(bulunan, self.aile, f"kasa:{bilgi.get('deviceId') or bulunan.mac or bulunan.adres}")
        c.ad = bilgi.get("alias") or c.ad
        c.model = bilgi.get("model", c.model)
        c.marka = "TP-Link"
        c.mac = (bilgi.get("mac") or bilgi.get("mic_mac") or c.mac).upper().replace("-", ":")
        c.tur = "light" if "light_state" in bilgi else "plug"
        c.erisim, c.erisim_notu = HAZIR, "Kasa yerel protokolü (anahtarsız)"
        return c

    def _istek(self, adres: str, komut: dict) -> dict:
        okuma = all(k2 in OKUMA_KOMUTLARI for v in komut.values() for k2 in v)
        if not okuma:
            self.tasima.yazma_denetle(f"Kasa {adres} {list(komut)}")
        if self.gonderici:
            return self.gonderici(adres, komut)
        if not ev_agi_adresi(adres):
            raise TasimaHatasi("yalnız ev ağı adresleri")
        yuk = sifrele(json.dumps(komut).encode())
        with socket.create_connection((adres, 9999), timeout=self.tasima.zaman_asimi) as s:
            s.sendall(struct.pack(">I", len(yuk)) + yuk)
            bas = s.recv(4)
            n = struct.unpack(">I", bas)[0] if len(bas) == 4 else 0
            veri = b""
            while len(veri) < min(n, 65536):
                parca = s.recv(4096)
                if not parca:
                    break
                veri += parca
        return json.loads(coz(veri).decode("utf-8", "replace") or "{}")

    def _sysinfo(self, cihaz) -> dict:
        return self._istek(cihaz.adres, {"system": {"get_sysinfo": {}}}).get("system", {}).get("get_sysinfo", {})

    def yetenekler(self, cihaz):
        yet = sysinfo_yetenekleri(self._sysinfo(cihaz))
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        b = self._sysinfo(cihaz)
        d: dict[str, Any] = {}
        if "relay_state" in b:
            d["guc"] = bool(b["relay_state"])
            if "brightness" in b:
                d["parlaklik"] = b["brightness"]
        elif "light_state" in b:
            ls = b["light_state"]
            d["guc"] = bool(ls.get("on_off"))
            d["parlaklik"] = ls.get("brightness", (ls.get("dft_on_state") or {}).get("brightness"))
        if "olcum_guc" in cihaz.yetenekler:
            rt = self._istek(cihaz.adres, {"emeter": {"get_realtime": {}}}).get("emeter", {}).get("get_realtime", {})
            d["olcum_guc"] = rt.get("power", (rt.get("power_mw") or 0) / 1000)
        return d

    def _uygula(self, cihaz, y, deger):
        tip = y.protokol.get("tip", "priz")
        if tip == "ampul":
            durum = {"on_off": 1} if y.ad == "parlaklik" else {"on_off": int(bool(deger))}
            if y.ad == "parlaklik":
                durum["brightness"] = int(deger)
            self._istek(cihaz.adres, {"smartlife.iot.smartbulb.lightingservice": {"transition_light_state": durum}})
        elif y.ad == "guc":
            self._istek(cihaz.adres, {"system": {"set_relay_state": {"state": int(bool(deger))}}})
        elif y.ad == "parlaklik":
            self._istek(cihaz.adres, {"smartlife.iot.dimmer": {"set_brightness": {"brightness": int(deger)}}})
        else:
            return super()._uygula(cihaz, y, deger)
        geri = self.durum(cihaz).get(y.ad)
        return Sonuc(geri == deger, f"{y.etiket}: {geri}", geri, geri == deger)
