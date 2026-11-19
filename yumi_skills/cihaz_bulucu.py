"""Ev ağı cihaz bulucu (E06, aday) — salt okunur keşif, protokol ailesi sınıflandırma.

Qt'ye bağımlı değildir; Qt panelinden iş parçacığıyla çağrılabilir:

    iptal = threading.Event()
    sonuc = kesfet(sure=8.0, iptal=iptal, ilerleme=lambda ad, sayi: ...)

Hiçbir cihaza komut, eşleştirme ya da oturum isteği göndermez (bkz. cihaz_yoklayicilar).
Sonuç modeli mevcut ``oem_connectors.DeviceDescriptor`` alanlarına
``descriptor_alanlari`` ile dönüştürülebilir.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Protocol

from .cihaz_aileleri import AILELER, GUVEN_SIRASI, KISISEL_TURLER, KURALLAR, TURLER, aile_bilgisi
from .cihaz_yoklayicilar import (BILGI_UCLARI, BleYoklayici, EnvanterYoklayici, ImzaYoklayici, Kayit,
                                 MdnsYoklayici, SelamYoklayici, SsdpYoklayici, TuyaYoklayici, WifiYoklayici,
                                 YoklayiciHatasi, bilgi_ucu_oku, yerel_ipv4_adresleri)

VARSAYILAN_SURE = 8.0


class Yoklayici(Protocol):
    ad: str
    notlar: list[str]

    def calistir(self, bitis: float, iptal: threading.Event) -> list[Kayit]: ...


@dataclass
class Kanit:
    yoklayici: str
    kayit: str
    alanlar: dict[str, str]


@dataclass
class BulunanCihaz:
    adres: str
    ad: str
    aile: str
    aile_etiketi: str
    tur: str
    tur_etiketi: str
    marka: str
    model: str
    destek: str
    baglanma: str
    yumi_protokol: str
    aileler: list[str]
    kanitlar: list[Kanit] = field(default_factory=list)
    guven: str = "tahmin"
    kategori: str = "ev"
    mac: str = ""
    eslestirme: str = ""

    def alan(self, *adlar: str) -> str:
        """Kanıtlardaki ilk dolu alan (ör. 'udn', 'dial_url', 'upnp_servisler')."""
        for ad in adlar:
            for k in self.kanitlar:
                if k.alanlar.get(ad):
                    return k.alanlar[ad]
        return ""

    def descriptor_alanlari(self) -> dict[str, Any]:
        """oem_connectors.DeviceDescriptor(**...) için alanlar.

        Keşif bir yetenek iddiası değildir: capabilities boş döner; yetenekler
        ancak ilgili adaptör bağlandıktan sonra doldurulur.
        """
        kimlik = next((k.alanlar.get("cihaz_kimligi") for k in self.kanitlar if k.alanlar.get("cihaz_kimligi")), "")
        return {
            "provider_id": self.yumi_protokol or self.aile,
            "account_id": "yerel-ag",
            "device_id": kimlik or self.adres or self.ad,
            "name": self.ad or self.adres,
            "device_type": self.tur,
            "capabilities": (),
            "model": " ".join(x for x in (self.marka, self.model) if x),
            "room": "",
        }


@dataclass
class YoklayiciDurumu:
    ad: str
    durum: str          # tamam | sonuc_yok | hata | iptal | zaman_asimi
    kayit_sayisi: int
    sure_sn: float
    notlar: list[str] = field(default_factory=list)


@dataclass
class TaramaSonucu:
    cihazlar: list[BulunanCihaz]
    yoklayicilar: list[YoklayiciDurumu]
    sure_sn: float
    iptal_edildi: bool
    ham_kayitlar: list[Kayit] = field(default_factory=list)

    def sozluk(self, ham: bool = False) -> dict[str, Any]:
        veri = {
            "sure_sn": round(self.sure_sn, 2),
            "iptal_edildi": self.iptal_edildi,
            "yoklayicilar": [asdict(y) for y in self.yoklayicilar],
            "cihazlar": [asdict(c) for c in self.cihazlar],
        }
        if ham:
            veri["ham_kayitlar"] = [asdict(k) for k in self.ham_kayitlar]
        return veri


# ---------------------------------------------------------------- sınıflandırma
def _eslesir(eslesme: str, desen: str, deger: str) -> bool:
    d, v = desen.casefold(), deger.casefold()
    if eslesme == "tam":
        return v == d
    if eslesme == "onek":
        return v.startswith(d)
    return d in v


def kural_eslesmeleri(kayit: Kayit, kurallar: Iterable[tuple] = KURALLAR) -> list[tuple]:
    alanlar = dict(kayit.alanlar)
    alanlar.setdefault("servis", kayit.kayit)
    eslesen = []
    for kural in kurallar:
        yoklayici, alan, eslesme, desen, *_ = kural
        if yoklayici not in ("*", kayit.yoklayici):
            continue
        deger = alanlar.get(alan)
        if deger is not None and _eslesir(eslesme, desen, str(deger)):
            eslesen.append(kural)
    return eslesen


def _ilk_dolu(*degerler: str) -> str:
    return next((d for d in degerler if d), "")


def birlestir(kayitlar: Iterable[Kayit], kurallar: Iterable[tuple] = KURALLAR) -> list[BulunanCihaz]:
    """Kayıtları adrese göre birleştirir ve tabloya göre sınıflandırır."""
    kurallar = tuple(kurallar)
    gruplar: dict[str, list[Kayit]] = {}
    for kayit in kayitlar:
        anahtar = (kayit.adres or kayit.alanlar.get("ble_adres") and f"ble:{kayit.alanlar['ble_adres']}"
                   or f"{kayit.yoklayici}:{kayit.ad or kayit.kayit}")
        gruplar.setdefault(anahtar, []).append(kayit)

    cihazlar = []
    for anahtar, grup in gruplar.items():
        eslesmeler = [k for kayit in grup for k in kural_eslesmeleri(kayit, kurallar)]
        aile_kurallari = sorted((k for k in eslesmeler if k[4]), key=lambda k: -k[6])
        tur_kurallari = sorted((k for k in eslesmeler if k[5]), key=lambda k: -k[6])
        aile = aile_kurallari[0][4] if aile_kurallari else "bilinmeyen"
        tur = tur_kurallari[0][5] if tur_kurallari else "unknown"
        bilgi_a = aile_bilgisi(aile)
        etiket, destek, baglanma, protokol = (bilgi_a["etiket"], bilgi_a["destek"], bilgi_a["baglanma"],
                                              bilgi_a["protokol"])
        aileler = sorted({k[4] for k in aile_kurallari})
        guven = "tahmin"
        if aile_kurallari:
            ayni = [k for k in aile_kurallari if k[4] == aile]
            seviye = max(GUVEN_SIRASI.get(k[7] if len(k) > 7 else "", 1) for k in ayni)
            if len({k[0] for k in ayni}) >= 2:  # iki ayrı yoklayıcı aynı aileyi destekliyor
                seviye = min(3, seviye + 1)
            guven = {v: k for k, v in GUVEN_SIRASI.items()}[seviye]
        kategori = bilgi_a.get("kategori", "ev")
        if tur in KISISEL_TURLER:
            kategori = "kisisel_ag"

        bilgi = [k for k in grup if k.yoklayici == "bilgi_ucu"]
        diger = [k for k in grup if k.yoklayici != "bilgi_ucu"]

        def alan(*adlar: str) -> str:
            for kume in (bilgi, diger):  # cihazın kendi bilgi ucu en güvenilir kaynaktır
                for ad in adlar:
                    for kayit in kume:
                        if kayit.alanlar.get(ad):
                            return kayit.alanlar[ad]
            return ""

        ad = _ilk_dolu(alan("friendlyname"), alan("txt_fn"),
                       next((k.ad for k in grup if k.yoklayici == "mdns" and k.ad), ""),
                       next((k.ad for k in grup if k.ad), ""))
        cihazlar.append(BulunanCihaz(
            adres=grup[0].adres, ad=ad, aile=aile, aile_etiketi=etiket,
            tur=tur, tur_etiketi=TURLER.get(tur, tur), marka=alan("manufacturer", "txt_manufacturer"),
            model=alan("txt_model", "modelname", "txt_md", "txt_mn", "txt_ty"),
            destek=destek, baglanma=baglanma, yumi_protokol=protokol, aileler=aileler or ["bilinmeyen"],
            kanitlar=[Kanit(k.yoklayici, k.kayit, dict(k.alanlar)) for k in grup],
            guven=guven, kategori=kategori, mac=alan("mac").upper().replace("-", ":"),
            eslestirme=bilgi_a.get("eslestirme", ""),
        ))
    cihazlar.sort(key=lambda c: (c.kategori != "ev", c.destek != "yumi_var", c.destek != "planli",
                                 c.aile == "bilinmeyen", c.adres))
    return cihazlar


# ---------------------------------------------------------------- yürütme
def varsayilan_yoklayicilar(ble: bool = False, wifi: bool = True) -> list[Yoklayici]:
    y: list = [MdnsYoklayici(), SsdpYoklayici(), TuyaYoklayici(), SelamYoklayici(), EnvanterYoklayici()]
    if wifi:
        y.append(WifiYoklayici())
    if ble:
        y.append(BleYoklayici())
    return y


def kesfet(sure: float = VARSAYILAN_SURE, iptal: threading.Event | None = None,
           yoklayicilar: list[Yoklayici] | None = None, bilgi_uclari: bool = True,
           ilerleme: Callable[[str, int], None] | None = None, imza: bool = False) -> TaramaSonucu:
    """Yoklayıcıları paralel çalıştırır; toplam süre ``sure`` (+~0,5 sn) ile sınırlıdır."""
    sure = max(1.0, min(float(sure), 60.0))
    iptal = iptal or threading.Event()
    yoklayicilar = varsayilan_yoklayicilar() if yoklayicilar is None else yoklayicilar
    baslangic = time.monotonic()
    son_sinir = baslangic + sure
    bilgi_payi = min(2.0, sure * 0.2) if bilgi_uclari else 0.0
    yoklama_sonu = son_sinir - bilgi_payi

    sonuclar: dict[str, YoklayiciDurumu] = {}
    ham: dict[str, list[Kayit]] = {}
    kilit = threading.Lock()

    def calistir(y: Yoklayici) -> None:
        t0 = time.monotonic()
        notlar = getattr(y, "notlar", None)
        try:
            kayitlar = list(y.calistir(yoklama_sonu, iptal))
            durum = "iptal" if iptal.is_set() else ("tamam" if kayitlar else "sonuc_yok")
        except YoklayiciHatasi as hata:
            kayitlar, durum = [], "hata"
            (notlar if notlar is not None else []).append(str(hata))
        except Exception as hata:  # yoklayıcı hatası taramayı düşürmez
            kayitlar, durum = [], "hata"
            (notlar if notlar is not None else []).append(f"{type(hata).__name__}: {hata}")
        with kilit:
            ham[y.ad] = kayitlar
            sonuclar[y.ad] = YoklayiciDurumu(y.ad, durum, len(kayitlar), round(time.monotonic() - t0, 2),
                                             list(notlar or []))
        if ilerleme:
            try:
                ilerleme(y.ad, len(kayitlar))
            except Exception:
                pass

    is_parcaciklari = [threading.Thread(target=calistir, args=(y,), name=f"YumiBulucu-{y.ad}", daemon=True)
                       for y in yoklayicilar]
    for t in is_parcaciklari:
        t.start()
    for t in is_parcaciklari:
        t.join(max(0.0, yoklama_sonu + 0.5 - time.monotonic()))
    with kilit:
        for y in yoklayicilar:
            if y.ad not in sonuclar:  # süreyi aşan yoklayıcı beklenmez
                sonuclar[y.ad] = YoklayiciDurumu(y.ad, "zaman_asimi", 0, round(time.monotonic() - baslangic, 2),
                                                 list(getattr(y, "notlar", []) or []))
                ham[y.ad] = []
        tum_kayitlar = [k for y in yoklayicilar for k in ham.get(y.ad, [])]

    if imza and not iptal.is_set():  # 2. aşama: yalnız envanterde olup tanınmayan/zayıf adresler
        ara = birlestir(tum_kayitlar)
        hedef = [c.adres for c in ara if c.adres and c.kategori != "kisisel_ag" and c.guven != "kesin"]
        y = ImzaYoklayici(hedef)
        imza_sonu = son_sinir - (min(2.0, sure * 0.1) if bilgi_uclari else 0)
        t0 = time.monotonic()
        k_imza = y.calistir(imza_sonu, iptal)
        tum_kayitlar.extend(k_imza)
        sonuclar["imza"] = YoklayiciDurumu("imza", "tamam" if k_imza else "sonuc_yok", len(k_imza),
                                           round(time.monotonic() - t0, 2), [f"{len(hedef)} adres yoklandı"])

    if bilgi_uclari and not iptal.is_set():
        bilgi_kayitlari, notlar = _bilgi_uclarini_oku(birlestir(tum_kayitlar), son_sinir, iptal)
        tum_kayitlar.extend(bilgi_kayitlari)
        sonuclar["bilgi_ucu"] = YoklayiciDurumu("bilgi_ucu", "tamam" if bilgi_kayitlari else "sonuc_yok",
                                                len(bilgi_kayitlari), 0.0, notlar)

    cihazlar = birlestir(tum_kayitlar)
    yerel = set(yerel_ipv4_adresleri())
    for cihaz in cihazlar:  # Yumi'nin çalıştığı bilgisayarın kendi yayınları
        if cihaz.adres in yerel:
            cihaz.tur, cihaz.tur_etiketi, cihaz.kategori = "computer", TURLER["computer"], "kisisel_ag"
            cihaz.ad = (cihaz.ad + " (bu bilgisayar)").strip()
    return TaramaSonucu(cihazlar, [sonuclar[k] for k in sonuclar],
                        time.monotonic() - baslangic, iptal.is_set(), tum_kayitlar)


def _bilgi_uclarini_oku(cihazlar: list[BulunanCihaz], son_sinir: float,
                        iptal: threading.Event) -> tuple[list[Kayit], list[str]]:
    kayitlar, notlar = [], []
    for cihaz in cihazlar:
        for aile in cihaz.aileler:
            if aile not in BILGI_UCLARI or not cihaz.adres:
                continue
            kalan = son_sinir - time.monotonic()
            if iptal.is_set() or kalan < 0.3:
                notlar.append("süre doldu; kalan bilgi uçları okunmadı")
                return kayitlar, notlar
            try:
                kayitlar.append(bilgi_ucu_oku(aile, cihaz.adres, min(1.5, kalan - 0.1)))
            except Exception as hata:
                notlar.append(f"{aile} bilgi ucu okunamadı ({cihaz.adres}): {type(hata).__name__}")
    return kayitlar, notlar


__all__ = ["AILELER", "BulunanCihaz", "Kanit", "Kayit", "TaramaSonucu", "YoklayiciDurumu",
           "birlestir", "kesfet", "kural_eslesmeleri", "varsayilan_yoklayicilar"]
