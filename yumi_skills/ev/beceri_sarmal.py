"""Mevcut SmartHomeSkill sarmalayıcısı: kullanıcının daha önce Yumi'ye kaydettiği cihazlar (Shelly, Yeelight,
Hue, Tapo, Tuya bulut/yerel, Xiaomi/Roborock, Home Assistant, Android TV) yeniden YAZILMADAN ortak modele
alınır; komutlar SmartHomeSkill'in kendi yöntemlerine gider (control_light_or_plug, control_vacuum,
control_smart_tv). Kayıt kaynağı: skills_data.json 'smart_devices' (sırlar orada DPAPI'li kalır).

Yetenekler: kayıtta 'capabilities' alanı doluysa oradan (cihaz/OEM adaptörünün bildirdiği), değilse
cihaz türünden çıkarılır (guven='tahmin'); bu sağlayıcıların çoğu durum geri okumaz → okunur=False.
"""
from __future__ import annotations

from typing import Any

from .adaptor import Adaptor, kaydet
from .model import BOOL, HAZIR, SECIM, TAMSAYI, EvCihazi, Sonuc, Yetenek

YETENEK_ESLEME = {"power": "guc", "on_off": "guc", "brightness": "parlaklik", "volume": "ses_adim",
                  "mute": "sessiz", "app": "uygulama", "vacuum": "supurge"}


def tur_yetenekleri(tur: str, protokol: str) -> dict[str, Yetenek]:
    k = f"SmartHomeSkill ({protokol})"
    yet: dict[str, Yetenek] = {}
    if tur in ("light", "plug"):
        yet["guc"] = Yetenek("guc", BOOL, False, True, kaynak=k + " control_light_or_plug", guven="tahmin")
        if tur == "light" and protokol in ("hue", "yeelight", "tapo", "home_assistant", "ha", "tuya"):
            yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, False, True, 1, 100, 1, "%",
                                       kaynak=k + " brightness", guven="tahmin")
    elif tur == "vacuum":
        yet["supurge"] = Yetenek("supurge", SECIM, False, True, secenekler=["baslat", "durdur", "sarja_don"],
                                 kaynak=k + " control_vacuum", guven="tahmin")
    elif tur == "tv":
        yet["guc"] = Yetenek("guc", BOOL, False, True, kaynak=k + " control_smart_tv", guven="tahmin")
        if protokol in ("android_tv", "home_assistant", "ha"):
            yet["ses_adim"] = Yetenek("ses_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak=k,
                                      guven="tahmin")
            yet["sessiz"] = Yetenek("sessiz", BOOL, False, True, kaynak=k, guven="tahmin")
        yet["uygulama"] = Yetenek("uygulama", SECIM, False, True, secenekler=["YouTube", "Netflix"],
                                  kaynak=k + " launch_app (DIAL/HA)", guven="tahmin")
    return yet


def kayittan_cihaz(anahtar: str, kayit: dict[str, Any]) -> EvCihazi:
    tur = kayit.get("device_type", "") or "unknown"
    protokol = kayit.get("protocol", "")
    c = EvCihazi(kimlik=f"beceri:{anahtar}", ad=kayit.get("name", anahtar), tur=tur, aile="yumi_beceri",
                 adres=kayit.get("ip", ""), model=kayit.get("model", ""), erisim=HAZIR,
                 erisim_notu=f"Yumi'de kayıtlı ({protokol})", oda=kayit.get("room", ""),
                 kullanici_adi=kayit.get("name", ""), takma_adlar=list(kayit.get("aliases") or []),
                 protokol={"beceri_adi": kayit.get("name", anahtar), "beceri_protokol": protokol})
    return c


@kaydet
class BeceriSarmalAdaptoru(Adaptor):
    aile = "yumi_beceri"

    def __init__(self, *a, beceri=None, **k):
        super().__init__(*a, **k)
        self.beceri = beceri  # SmartHomeSkill (yonetici.beceri_bagla ile verilir)

    def uygun_mu(self, bulunan):
        return False  # ağ keşfinden değil, Yumi kaydından gelir

    def kayitli_cihazlar(self) -> list[EvCihazi]:
        if self.beceri is None:
            return []
        kayitlar = self.beceri.storage.get("smart_devices", {}) or {}
        return [kayittan_cihaz(k, v) for k, v in kayitlar.items() if isinstance(v, dict)]

    def yetenekler(self, cihaz):
        kayit = {}
        if self.beceri is not None:
            kayit = (self.beceri.storage.get("smart_devices", {}) or {}).get(
                cihaz.kimlik.split(":", 1)[-1], {}) or {}
        yet = tur_yetenekleri(cihaz.tur, cihaz.protokol.get("beceri_protokol", ""))
        bildirilen = {YETENEK_ESLEME.get(str(x).lower(), "") for x in kayit.get("capabilities", [])} - {""}
        if bildirilen:  # cihaz/OEM adaptörünün bildirdiği yetenekler kesin sayılır
            for ad in list(yet):
                if ad in bildirilen:
                    yet[ad].guven = "kesin"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"SmartHomeSkill {y.ad}={deger}")
        if self.beceri is None:
            return Sonuc(False, "Yumi akıllı ev becerisi bağlı değil")
        ad = cihaz.protokol.get("beceri_adi", cihaz.gorunen_ad)
        b = self.beceri
        if y.ad == "guc" and cihaz.tur == "tv":
            r = b.control_smart_tv(action="power_on" if deger else "power_off", device_name=ad)
        elif y.ad == "guc":
            r = b.control_light_or_plug(ad, "on" if deger else "off")
        elif y.ad == "parlaklik":
            r = b.control_light_or_plug(ad, "on", int(deger))
        elif y.ad == "supurge":
            r = b.control_vacuum({"baslat": "start", "durdur": "pause", "sarja_don": "dock"}[deger], ad)
        elif y.ad == "ses_adim":
            r = b.control_smart_tv(action="volume_up" if deger == "yukari" else "volume_down", device_name=ad)
        elif y.ad == "sessiz":
            r = b.control_smart_tv(action="mute", device_name=ad)
        elif y.ad == "uygulama":
            r = b.control_smart_tv(action="launch_app", device_name=ad, app_or_channel=str(deger))
        else:
            return super()._uygula(cihaz, y, deger)
        return Sonuc(bool(r.get("ok")), r.get("speech", ""))
