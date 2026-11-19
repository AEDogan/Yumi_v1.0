"""Tuya yerel adaptörü (tinytuya, lib/ev/pydeps; bulut hesabı gerekmez).

Keşif: cihazın kendi UDP yayını (gwId, sürüm, ürün anahtarı). Yerel anahtar (local key) kullanıcıdan
alınır (Ev paneli > Anahtar gir) → DPAPI depo; yoksa erişim 'anahtar_gerekli'.
Yetenekler cihazdan SORGULANIR: tinytuya status() → DP (veri noktası) sözlüğü; DP değer kalıplarından
standart yetenekler çıkarılır (guven='tahmin': Tuya DP haritası ürüne göre değişir, cihaz şema
bildirmiyor). Yazma Tasima yazma kilidine tabidir.
"""
from __future__ import annotations

from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet, pydeps_ekle
from .model import ANAHTAR_GEREKLI, BOOL, DESTEKLENMIYOR, HAZIR, ONDALIK, SECIM, TAMSAYI, Sonuc, Yetenek


def dp_yetenekleri(dps: dict[str, Any]) -> dict[str, Yetenek]:
    """Tuya DP sözlüğü → yetenekler (ağsız; testlenir). Yaygın DP kalıpları:
    priz: 1=anahtar(bool), 9=geri sayım, 18=akım mA, 19=güç W×10, 20=gerilim V×10
    ampul (v3.3+): 20=anahtar, 21=kip, 22=parlaklık 10–1000, 23=renk sıcaklığı 0–1000, 24=renk (hsv hex)
    eski ampul: 1=anahtar, 2=kip, 3=parlaklık 25–255, 4=sıcaklık 0–255
    """
    d = {str(k): v for k, v in (dps or {}).items()}
    yet: dict[str, Yetenek] = {}
    k = "tinytuya status() DP"
    isik_yeni = isinstance(d.get("20"), bool) and isinstance(d.get("22"), int)
    isik_eski = isinstance(d.get("1"), bool) and isinstance(d.get("3"), int) and 25 <= d.get("3", 0) <= 255 \
        and isinstance(d.get("2"), str)
    if isik_yeni:
        yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " 20", guven="tahmin", protokol={"dp": "20"})
        yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, True, True, 1, 100, 1, "%", kaynak=k + " 22",
                                   guven="tahmin", protokol={"dp": "22", "olcek": [10, 1000]})
        if isinstance(d.get("23"), int):
            yet["renk_sicakligi"] = Yetenek("renk_sicakligi", TAMSAYI, True, True, 0, 100, 1, "%", kaynak=k + " 23",
                                            guven="tahmin", protokol={"dp": "23", "olcek": [0, 1000]})
        if isinstance(d.get("21"), str):
            yet["mod"] = Yetenek("mod", SECIM, True, True, secenekler=["white", "colour", "scene", "music"],
                                 kaynak=k + " 21", guven="tahmin", protokol={"dp": "21"})
        return yet
    if isik_eski:
        yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " 1", guven="tahmin", protokol={"dp": "1"})
        yet["parlaklik"] = Yetenek("parlaklik", TAMSAYI, True, True, 1, 100, 1, "%", kaynak=k + " 3",
                                   guven="tahmin", protokol={"dp": "3", "olcek": [25, 255]})
        return yet
    if isinstance(d.get("1"), bool):
        yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " 1", guven="tahmin", protokol={"dp": "1"})
    for dp, ad, bolen, birim in (("18", "olcum_akim", 1000, "A"), ("19", "olcum_guc", 10, "W"),
                                 ("20", "olcum_gerilim", 10, "V")):
        if isinstance(d.get(dp), int) and not isinstance(d.get(dp), bool):
            yet[ad] = Yetenek(ad, ONDALIK, True, False, birim=birim, kaynak=f"{k} {dp}", guven="tahmin",
                              protokol={"dp": dp, "bolen": bolen})
    return yet


def _olcekle(deger: float, olcek: list[int], ters: bool = False) -> int:
    a, b = olcek
    if ters:  # cihaz → yüzde
        return int(round((deger - a) * 100 / (b - a)))
    return int(round(a + (b - a) * deger / 100))


@kaydet
class TuyaYerelAdaptoru(Adaptor):
    aile = "tuya_yerel"
    bulucu_aileleri = ("tuya",)

    def __init__(self, *a, cihaz_fabrikasi=None, **k):
        super().__init__(*a, **k)
        self.cihaz_fabrikasi = cihaz_fabrikasi  # test: (kimlik, adres, anahtar, surum) -> nesne(status/set_value)

    def uygun_mu(self, bulunan):
        return "tuya" in getattr(bulunan, "aileler", []) and bool(bulunan.alan("cihaz_kimligi"))

    def cihaz_olustur(self, bulunan):
        gw = bulunan.alan("cihaz_kimligi")
        c = bos_cihaz(bulunan, self.aile, f"tuya:{gw}")
        c.protokol = {"gwId": gw, "surum": bulunan.alan("surum") or "3.3", "urun_anahtari": bulunan.alan("urun_anahtari")}
        c.erisim, c.erisim_notu = ANAHTAR_GEREKLI, "Tuya yerel anahtarı (local key) gerekli"
        if not c.ad or c.ad == c.adres:
            c.ad = "Tuya cihazı"
        return c

    def _baglanti(self, cihaz):
        anahtar = self.sirlar(cihaz).get("yerel_anahtar", "")
        if not anahtar:
            return None
        if self.cihaz_fabrikasi:
            return self.cihaz_fabrikasi(cihaz.protokol["gwId"], cihaz.adres, anahtar, cihaz.protokol.get("surum", "3.3"))
        pydeps_ekle()
        try:
            import tinytuya
        except ImportError:
            raise RuntimeError("tinytuya kurulu değil (lib/ev/pydeps)") from None
        d = tinytuya.Device(cihaz.protokol["gwId"], cihaz.adres, anahtar, version=float(cihaz.protokol.get("surum", "3.3")))
        d.set_socketTimeout(3)
        d.set_socketRetryLimit(1)
        return d

    def yetenekler(self, cihaz):
        try:
            d = self._baglanti(cihaz)
        except RuntimeError as e:
            cihaz.erisim, cihaz.erisim_notu = DESTEKLENMIYOR, str(e)
            return {}
        if d is None:
            cihaz.erisim, cihaz.erisim_notu = ANAHTAR_GEREKLI, "Tuya yerel anahtarı (local key) gerekli"
            return {}
        durum = d.status() or {}
        if "Error" in durum or "dps" not in durum:
            cihaz.erisim, cihaz.erisim_notu = ANAHTAR_GEREKLI, f"anahtar/sürüm doğrulanamadı: {durum.get('Error', 'yanıt yok')}"
            return {}
        cihaz.protokol["son_dps"] = {k: v for k, v in durum["dps"].items() if not isinstance(v, str) or len(v) < 40}
        yet = dp_yetenekleri(durum["dps"])
        if "parlaklik" in yet and cihaz.tur in ("unknown", "plug", ""):
            cihaz.tur = "light"
        elif "guc" in yet and cihaz.tur in ("unknown", ""):
            cihaz.tur = "plug"
        cihaz.erisim, cihaz.erisim_notu = HAZIR, "yerel anahtarla bağlı"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        d = self._baglanti(cihaz)
        if d is None:
            return {}
        dps = (d.status() or {}).get("dps", {})
        sonuc: dict[str, Any] = {}
        for ad, y in cihaz.yetenekler.items():
            dp = y.protokol.get("dp")
            if dp not in dps:
                continue
            v = dps[dp]
            if "olcek" in y.protokol:
                v = _olcekle(v, y.protokol["olcek"], ters=True)
            elif "bolen" in y.protokol:
                v = v / y.protokol["bolen"]
            sonuc[ad] = v
        return sonuc

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"Tuya {y.ad}={deger}")
        d = self._baglanti(cihaz)
        if d is None:
            return Sonuc(False, "Tuya yerel anahtarı gerekli")
        ham = _olcekle(deger, y.protokol["olcek"]) if "olcek" in y.protokol else deger
        d.set_value(int(y.protokol["dp"]), ham)
        geri = self.durum(cihaz).get(y.ad)
        tamam = geri == deger or (isinstance(deger, int) and isinstance(geri, int) and abs(geri - deger) <= 1)
        return Sonuc(tamam, f"{y.etiket}: {geri}", geri, tamam)
