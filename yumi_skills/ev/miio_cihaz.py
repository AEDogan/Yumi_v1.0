"""Xiaomi miIO adaptörü (python-miio 0.5.12, .venv'de var): robot süpürge (Roborock/Xiaomi/Viomi/Dreame) ve
miIO prizler. Mevcut SmartHomeSkill.control_vacuum ile aynı sürücü seçimi.

Keşif: miIO "hello" yanıtı (cihaz kimliği). Token kullanıcıdan alınır (DPAPI depo) → yoksa 'anahtar_gerekli'
(yeni cihazlar hello'da token vermez). Yetenekler cihazdan SORGULANIR: miIO.info → model; süpürgede
status() (durum, pil, fan) ve fan_speed_presets(). Yazma Tasima yazma kilidine tabidir.
Not: yeni Roborock (S7+, Q serisi) yerel protokolü farklıdır (python-roborock, hesap gerekir) → 'yalniz_bulut'.
"""
from __future__ import annotations

from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import ANAHTAR_GEREKLI, BOOL, HAZIR, METIN, SECIM, TAMSAYI, Sonuc, Yetenek

SUPURGE_ONEKLERI = ("roborock.", "rockrobo.", "viomi.", "dreame.")
PRIZ_ONEKLERI = ("chuangmi.plug", "cuco.plug", "zimi.powerstrip", "qmi.powerstrip")


def surucu_sec(model: str):
    """Model → python-miio sürücü sınıfı (yoksa None). SmartHomeSkill.control_vacuum ile aynı kural."""
    import miio
    if model.startswith("viomi."):
        return miio.ViomiVacuum
    if model.startswith("dreame."):
        return miio.DreameVacuum
    if model.startswith(("roborock.", "rockrobo.")):
        return miio.RoborockVacuum
    if model.startswith(PRIZ_ONEKLERI):
        return getattr(miio, "ChuangmiPlug", None)
    return None


@kaydet
class MiioAdaptoru(Adaptor):
    aile = "miio"
    bulucu_aileleri = ("xiaomi", "roborock")

    def __init__(self, *a, surucu_fabrikasi=None, **k):
        super().__init__(*a, **k)
        self.surucu_fabrikasi = surucu_fabrikasi  # test: (adres, token, model) -> nesne

    def uygun_mu(self, bulunan):
        return any(a in self.bulucu_aileleri for a in getattr(bulunan, "aileler", [])) and bool(bulunan.adres)

    def cihaz_olustur(self, bulunan):
        kimlik = bulunan.alan("cihaz_kimligi")
        c = bos_cihaz(bulunan, self.aile, f"miio:{kimlik}" if kimlik else f"miio:{bulunan.mac or bulunan.adres}")
        c.protokol = {"miio_kimlik": kimlik}
        c.erisim, c.erisim_notu = ANAHTAR_GEREKLI, "miIO token gerekli (Xiaomi Home'dan bir kez alınır)"
        return c

    def _surucu(self, cihaz, model: str = ""):
        token = self.sirlar(cihaz).get("token", "")
        if not token:
            return None
        if self.surucu_fabrikasi:
            return self.surucu_fabrikasi(cihaz.adres, token, model)
        import miio
        if not model:
            return miio.Device(cihaz.adres, token, timeout=3)
        sinif = surucu_sec(model) or miio.Device
        return sinif(cihaz.adres, token, model=model) if sinif is not miio.Device else sinif(cihaz.adres, token, timeout=3)

    def yetenekler(self, cihaz):
        d = self._surucu(cihaz)
        if d is None:
            cihaz.erisim = ANAHTAR_GEREKLI
            return {}
        model = cihaz.protokol.get("miio_model") or d.info().model
        cihaz.protokol["miio_model"] = model
        cihaz.model = cihaz.model or model
        s = self._surucu(cihaz, model)
        yet: dict[str, Yetenek] = {}
        k = f"python-miio {model}"
        if model.startswith(SUPURGE_ONEKLERI):
            cihaz.tur = "vacuum"
            st = s.status()
            yet["supurge"] = Yetenek("supurge", SECIM, False, True, secenekler=["baslat", "durdur", "sarja_don"],
                                     kaynak=k + " start/pause/home")
            if getattr(st, "battery", None) is not None:
                yet["olcum_pil"] = Yetenek("olcum_pil", TAMSAYI, True, False, 0, 100, 1, "%", kaynak=k + " status")
            yet["durum_metni"] = Yetenek("durum_metni", METIN, True, False, kaynak=k + " status.state")
            try:
                hazir = s.fan_speed_presets()
                if hazir:
                    yet["fan_hizi"] = Yetenek("fan_hizi", SECIM, True, True, secenekler=list(hazir),
                                              kaynak=k + " fan_speed_presets", protokol={"degerler": dict(hazir)})
            except Exception:
                pass
        elif model.startswith(PRIZ_ONEKLERI):
            cihaz.tur = "plug"
            yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " status.is_on")
        else:
            yet["durum_metni"] = Yetenek("durum_metni", METIN, True, False, kaynak=k + " info")
            cihaz.erisim, cihaz.erisim_notu = HAZIR, f"{model}: bu sürümde yalnız bilgi okunur"
        if model.startswith(("roborock.vacuum.a", "roborock.vacuum.s7", "roborock.vacuum.q")):
            cihaz.erisim_notu = "yeni Roborock: miIO yanıt vermezse yalnız bulut (python-roborock) yolu var"
        if yet and cihaz.erisim != HAZIR:
            cihaz.erisim, cihaz.erisim_notu = HAZIR, cihaz.erisim_notu if "Roborock" in cihaz.erisim_notu else "token ile bağlı"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        s = self._surucu(cihaz, cihaz.protokol.get("miio_model", ""))
        if s is None:
            return {}
        st = s.status()
        d: dict[str, Any] = {}
        if "olcum_pil" in cihaz.yetenekler:
            d["olcum_pil"] = getattr(st, "battery", None)
        if "durum_metni" in cihaz.yetenekler:
            d["durum_metni"] = str(getattr(st, "state", "") or "")
        if "fan_hizi" in cihaz.yetenekler:
            ters = {v: k for k, v in cihaz.yetenekler["fan_hizi"].protokol.get("degerler", {}).items()}
            d["fan_hizi"] = ters.get(getattr(st, "fanspeed", None), getattr(st, "fanspeed", None))
        if "guc" in cihaz.yetenekler:
            d["guc"] = bool(getattr(st, "is_on", False))
        return d

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"miIO {y.ad}={deger}")
        s = self._surucu(cihaz, cihaz.protokol.get("miio_model", ""))
        if s is None:
            return Sonuc(False, "miIO token gerekli")
        if y.ad == "supurge":
            {"baslat": s.start, "durdur": s.pause, "sarja_don": s.home}[deger]()
            return Sonuc(True, {"baslat": "Temizlik başladı", "durdur": "Durdu", "sarja_don": "Şarja dönüyor"}[deger])
        if y.ad == "fan_hizi":
            s.set_fan_speed(y.protokol.get("degerler", {}).get(deger, deger))
            return Sonuc(True, f"Fan {deger}")
        if y.ad == "guc":
            (s.on if deger else s.off)()
            geri = self.durum(cihaz).get("guc")
            return Sonuc(geri == deger, "Açık" if geri else "Kapalı", geri, geri == deger)
        return super()._uygula(cihaz, y, deger)

