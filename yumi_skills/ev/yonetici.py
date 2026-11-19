"""Ev yöneticisi: bulucu → adaptörler → tek EvCihazi; yetenek sorgulama, durum okuma, komut yönlendirme, WoL.

    y = EvYoneticisi(veri_klasoru)            # data/ev_cihazlari.json + data/ev_sirlar.json
    cihazlar = y.tara(sure=8, ble=True)       # keşif + yetenekleri CİHAZDAN sorgular + kayda işler
    y.durum(c); y.uygula(c, "ses_duzeyi", 10); y.eslestir(c)  # yazma Tasima(yazma=True) ister

Birleştirme: aynı bulucu kaydından çıkan tüm adaptör cihazları tek cihazdır (TV = webos + upnp_av + dial);
farklı kayıtlar UDN / MAC ile birleşir. Birincil aile en yetenekli adaptördür (ONCELIK).
Her yetenek, onu sağlayan adaptörün adını ``Yetenek.protokol['_aile']``'de taşır; uygula() oraya gider.
"""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from . import adaptor as _adaptor
from .adaptor import ADAPTORLER, Adaptor
from .kayit import CihazKaydi
from .model import (ANAHTAR_GEREKLI, DESTEKLENMIYOR, ESLESTIRME_GEREKLI, HAZIR, YALNIZ_BULUT, EvCihazi,
                    Sonuc)
from .sirlar import SirDeposu
from .tasima import Tasima, YazmaKilitli

# Birincil aile önceliği (küçük = önce). Listede olmayanlar sona.
ONCELIK = ("webos", "tizen", "androidtv", "tuya_yerel", "miio", "roomba", "kasa", "yeelight", "ble_tarti",
           "yumi_beceri", "upnp_av", "dial")
ERISIM_SIRASI = (HAZIR, ESLESTIRME_GEREKLI, ANAHTAR_GEREKLI, YALNIZ_BULUT, DESTEKLENMIYOR)
TV_AILELERI = ("webos", "tizen", "androidtv", "upnp_av", "dial")
AILE_ADI = {"webos": "webOS kumanda", "tizen": "Samsung kumanda", "androidtv": "Android TV", "upnp_av": "DLNA",
            "dial": "uygulama başlatma", "tuya_yerel": "Tuya", "miio": "Xiaomi miIO", "roomba": "iRobot",
            "kasa": "TP-Link Kasa", "yeelight": "Yeelight", "ble_tarti": "Bluetooth tartı", "yumi_beceri": "Yumi kaydı"}


def _oncelik(aile: str) -> int:
    return ONCELIK.index(aile) if aile in ONCELIK else len(ONCELIK)


def adaptorleri_yukle() -> None:
    """Tüm adaptör modüllerini içe aktarır (her biri @kaydet ile ADAPTORLER'e eklenir)."""
    import importlib
    for ad in ("upnp_av", "dial", "webos", "tizen", "ble_tarti", "tuya_yerel", "android_tv", "miio_cihaz",
               "kasa", "yeelight", "roomba", "beceri_sarmal"):
        try:
            importlib.import_module(f"{__package__}.{ad}")
        except ImportError:
            continue


def erisim_ozeti(durumlar: dict[str, list]) -> tuple[str, str]:
    """{aile: [durum, not]} → cihazın genel erişimi (en iyi durum) ve not."""
    if not durumlar:
        return DESTEKLENMIYOR, ""
    en_iyi = min(durumlar.values(), key=lambda d: ERISIM_SIRASI.index(d[0]) if d[0] in ERISIM_SIRASI else 99)
    eksik = [f"{AILE_ADI.get(a, a)}: {d[1]}" for a, d in durumlar.items() if d[0] in (ESLESTIRME_GEREKLI, ANAHTAR_GEREKLI)]
    notu = en_iyi[1]
    if en_iyi[0] == HAZIR and eksik:
        notu = "kısmen hazır; " + "; ".join(eksik)
    return en_iyi[0], notu


class EvYoneticisi:
    def __init__(self, veri_klasoru: str | Path | None = None, tasima: Tasima | None = None,
                 kayit: CihazKaydi | None = None, sirlar: SirDeposu | None = None,
                 adaptorler: dict[str, Adaptor] | None = None, kesif: Callable[..., Any] | None = None):
        klasor = Path(veri_klasoru) if veri_klasoru else None
        self.tasima = tasima or Tasima(yazma=False)
        self.kayit = kayit if kayit is not None else CihazKaydi(klasor / "ev_cihazlari.json" if klasor else None)
        self.sirlar = sirlar if sirlar is not None else SirDeposu(klasor / "ev_sirlar.json" if klasor else None)
        self._kesif = kesif
        self._kilit = threading.RLock()
        if adaptorler is None:
            adaptorleri_yukle()
            adaptorler = {}
            for aile, sinif in ADAPTORLER.items():
                try:
                    adaptorler[aile] = sinif(self.tasima, sirlar=self.sirlar.al)
                except Exception:
                    continue
        self.adaptorler = adaptorler
        self.son_tarama = None
        self.notlar: list[str] = []
        self.video_bulucu: Callable[[str], str | None] | None = None  # testte sahte; None = tv_yardim.video_bul

    # ------------------------------------------------------------ keşif
    def _kesfet(self, sure: float, ble: bool, iptal, ilerleme):
        if self._kesif is not None:
            return self._kesif(sure=sure, ble=ble, iptal=iptal, ilerleme=ilerleme)
        from ..cihaz_bulucu import kesfet, varsayilan_yoklayicilar
        # 18 Kas: imza aşaması açık — yalnız ARP'de görülen (yayın yapmayan) TV'nin platformu port imzasından bulunur
        return kesfet(sure=sure, iptal=iptal, ilerleme=ilerleme, yoklayicilar=varsayilan_yoklayicilar(ble=ble), imza=True)

    def bulunanlardan(self, tarama) -> list[EvCihazi]:
        """Bulucu sonucu → birleştirilmiş EvCihazi listesi (ağ kullanmaz)."""
        cihazlar: list[EvCihazi] = []
        for b in tarama.cihazlar:
            if getattr(b, "kategori", "ev") == "kisisel_ag":
                continue
            parcalar = []
            for aile, a in self.adaptorler.items():
                try:
                    if a.uygun_mu(b):
                        c = a.cihaz_olustur(b)
                        if c is not None:
                            parcalar.append(c)
                except Exception as e:
                    self.notlar.append(f"{aile} keşif hatası ({getattr(b, 'adres', '')}): {type(e).__name__}: {e}")
            if parcalar:
                cihazlar.append(self._birlestir(parcalar))
        # farklı bulucu kayıtlarından gelen aynı cihaz (UDN/MAC)
        sonuc: list[EvCihazi] = []
        for c in cihazlar:
            es = next((s for s in sonuc if self._ayni(s, c)), None)
            if es is None:
                sonuc.append(c)
            else:
                sonuc[sonuc.index(es)] = self._birlestir([es, c])
        zaman = time.strftime("%Y-%m-%d %H:%M:%S")
        for c in sonuc:
            c.son_gorulme = zaman
        return sonuc

    @staticmethod
    def _ayni(a: EvCihazi, b: EvCihazi) -> bool:
        ka, kb = {a.kimlik, *a.yan_kimlikler}, {b.kimlik, *b.yan_kimlikler}
        if ka & kb:
            return True
        return bool(a.mac and b.mac and a.mac.upper() == b.mac.upper())

    @staticmethod
    def _birlestir(parcalar: list[EvCihazi]) -> EvCihazi:
        parcalar = sorted(parcalar, key=lambda c: _oncelik(c.aile))
        ana = copy.deepcopy(parcalar[0])
        durumlar = dict(ana.protokol.pop("erisim_aileler", {}) or {})
        durumlar.setdefault(ana.aile, [ana.erisim, ana.erisim_notu])
        for p in parcalar[1:]:
            pd = dict(p.protokol)
            durumlar.update(pd.pop("erisim_aileler", {}) or {})
            durumlar.setdefault(p.aile, [p.erisim, p.erisim_notu])
            for aile in (p.aile, *p.ek_aileler):
                if aile != ana.aile and aile not in ana.ek_aileler:
                    ana.ek_aileler.append(aile)
            for k, v in pd.items():
                ana.protokol.setdefault(k, v)
            for k in (p.kimlik, *p.yan_kimlikler):
                if k != ana.kimlik and k not in ana.yan_kimlikler:
                    ana.yan_kimlikler.append(k)
            for alan in ("mac", "marka", "model", "adres"):
                if not getattr(ana, alan) and getattr(p, alan):
                    setattr(ana, alan, getattr(p, alan))
            if ana.tur in ("unknown", "media", "") and p.tur not in ("unknown", ""):
                ana.tur = p.tur
            for y in p.yetenekler.values():
                ana.yetenek_ekle(y)
        if any(a in TV_AILELERI[:3] for a in (ana.aile, *ana.ek_aileler)):
            ana.tur = "tv"
        ana.protokol["erisim_aileler"] = durumlar
        ana.erisim, ana.erisim_notu = erisim_ozeti(durumlar)
        return ana

    def beceri_bagla(self, beceri) -> None:
        """Mevcut SmartHomeSkill'i bağlar: kayıtlı cihazları ortak modele alınır, komutlar ona gider."""
        a = self.adaptorler.get("yumi_beceri")
        if a is not None:
            a.beceri = beceri

    def _beceri_cihazlari(self, cihazlar: list[EvCihazi]) -> list[EvCihazi]:
        a = self.adaptorler.get("yumi_beceri")
        if a is None or not hasattr(a, "kayitli_cihazlar"):
            return cihazlar
        for b in a.kayitli_cihazlar():
            es = next((c for c in cihazlar if self._ayni(c, b) or (b.adres and c.adres == b.adres)), None)
            if es is None:
                cihazlar.append(b)
                continue
            birlesik = self._birlestir([es, b])
            birlesik.kullanici_adi = birlesik.kullanici_adi or b.kullanici_adi
            birlesik.oda = birlesik.oda or b.oda
            cihazlar[cihazlar.index(es)] = birlesik
        return cihazlar

    def tara(self, sure: float = 8.0, ble: bool = False, iptal=None, ilerleme=None, sorgula: bool = True,
             kaydet: bool = True) -> list[EvCihazi]:
        tarama = self._kesfet(sure, ble, iptal, ilerleme)
        self.son_tarama = tarama
        cihazlar = self._beceri_cihazlari(self.bulunanlardan(tarama))
        if sorgula:
            for c in cihazlar:
                if iptal is not None and iptal.is_set():
                    break
                self.yetenekleri_sorgula(c, kaydet=False)
        for c in cihazlar:  # 18 Kas: kartta açık/bekleme/kapalı (salt okunur)
            if c.tur == "tv" or c.aile in TV_AILELERI:
                try:
                    c.protokol["cevrimici"] = self.cevrimici(c)
                    c.protokol["cevrimici_zamani"] = time.strftime("%H:%M")
                except Exception:
                    pass
        sonuc = self.kayit.guncelle(cihazlar) if kaydet else cihazlar
        # 18 Kas: kayıtlı ama bu taramada yanıt vermeyen TV'ler de dönsün (kapalı/bekleme durumuyla); kart kaybolmasın
        gorulen = {c.kimlik for c in sonuc} | {c.mac.upper() for c in sonuc if c.mac}
        for c in list(self.kayit.tumu()) if kaydet else []:
            if c.kimlik in gorulen or (c.mac and c.mac.upper() in gorulen):
                continue
            if c.tur == "tv" or c.aile in TV_AILELERI:
                try:
                    c.protokol["cevrimici"] = self.cevrimici(c)
                    c.protokol["cevrimici_zamani"] = time.strftime("%H:%M")
                except Exception:
                    pass
            c.protokol["bu_taramada_yok"] = True
            sonuc.append(c)
        for c in sonuc[:len(cihazlar)]:
            c.protokol.pop("bu_taramada_yok", None)
        return sonuc

    # ------------------------------------------------------------ çevrimiçi / güç (salt okunur)
    def _tcp_acik(self, adres: str, port: int, zaman_asimi: float = 0.8) -> bool:
        f = getattr(self.tasima, "tcp_acik", None)
        if f is not None:
            return bool(f(adres, port, zaman_asimi))
        from ..cihaz_yoklayicilar import tcp_acik
        return tcp_acik(adres, port, zaman_asimi)

    def cevrimici(self, c: EvCihazi) -> str:
        """'acik' | 'bekleme' | 'kapali' | 'bilinmiyor' — platformun okuma ucu / portu yoklanır, komut gitmez."""
        aileler = self._aileler(c)
        if "tizen" in aileler and hasattr(self.adaptorler["tizen"], "guc_durumu"):
            return self.adaptorler["tizen"].guc_durumu(c)
        if not c.adres:
            return "bilinmiyor"
        portlar = [p for a, p in (("webos", 3000), ("webos", 3001), ("androidtv", 6466)) if a in aileler]
        dial = c.protokol.get("dial_url", "")
        if dial:
            try:
                import urllib.parse
                portlar.append(urllib.parse.urlsplit(dial).port or 80)
            except ValueError:
                pass
        for s in (c.protokol.get("servisler") or {}).values():
            try:
                import urllib.parse
                portlar.append(urllib.parse.urlsplit(s.get("kontrol", "")).port or 80)
            except ValueError:
                pass
        if not portlar:
            return "bilinmiyor"
        return "acik" if any(self._tcp_acik(c.adres, p) for p in dict.fromkeys(portlar)) else "kapali"

    def ac_destegi(self, c: EvCihazi) -> tuple[bool, str]:
        """Ağdan açma yapılabilir mi + ipucu. MAC yoksa WoL olmaz (Android TV kendi yoluyla açılır)."""
        from .tv_yardim import GUC_IPUCU
        aile = next((a for a in ("tizen", "webos", "androidtv") if a in self._aileler(c)), c.aile)
        ipucu = GUC_IPUCU.get(aile, GUC_IPUCU["dial"])
        if aile == "androidtv" and "guc" in c.yetenekler:
            return True, ipucu
        if not c.mac:
            return False, "MAC adresi bilinmiyor; ağdan açılamaz. TV açıkken yeniden tara. " + ipucu
        return True, ipucu

    # ------------------------------------------------------------ yetenek / durum
    def _aileler(self, c: EvCihazi) -> list[str]:
        return [a for a in (c.aile, *c.ek_aileler) if a in self.adaptorler]

    def yetenekleri_sorgula(self, c: EvCihazi, kaydet: bool = True) -> dict[str, Any]:
        """Her adaptörden yetenekleri sorgular (cihazla konuşur; yalnız okuma). Hatalar notlara düşer."""
        hatalar: dict[str, str] = {}
        durumlar = dict(c.protokol.get("erisim_aileler", {}))
        c.yetenekler = {}
        for aile in self._aileler(c):
            a = self.adaptorler[aile]
            onceki = c.erisim, c.erisim_notu
            c.erisim, c.erisim_notu = (durumlar.get(aile) or [onceki[0], onceki[1]])
            try:
                yet = a.yetenekler(c) or {}
                for y in yet.values():
                    y.protokol.setdefault("_aile", aile)
                    c.yetenek_ekle(y)
            except Exception as e:
                hatalar[aile] = f"{type(e).__name__}: {e}"[:200]
            durumlar[aile] = [c.erisim, c.erisim_notu]
        c.protokol["erisim_aileler"] = durumlar
        c.protokol["sorgu_hatalari"] = hatalar
        c.protokol["sorgu_zamani"] = time.strftime("%Y-%m-%d %H:%M:%S")
        c.erisim, c.erisim_notu = erisim_ozeti(durumlar)
        if kaydet and self.kayit.al(c.kimlik) is not None:
            self.kayit.kaydet()
        return {"yetenekler": sorted(c.yetenekler), "hatalar": hatalar}

    def durum(self, c: EvCihazi) -> dict[str, Any]:
        d: dict[str, Any] = {}
        hatalar = {}
        for aile in self._aileler(c):
            try:
                for k, v in (self.adaptorler[aile].durum(c) or {}).items():
                    if v is not None and k not in d:
                        d[k] = v
            except Exception as e:
                hatalar[aile] = f"{type(e).__name__}: {e}"[:200]
        if hatalar:
            d["_hatalar"] = hatalar
        return d

    # ------------------------------------------------------------ yazma
    def _adaptor_for(self, c: EvCihazi, yetenek: str) -> Adaptor | None:
        y = c.yetenekler.get(yetenek)
        aile = (y.protokol.get("_aile") if y else None) or c.aile
        return self.adaptorler.get(aile)

    wol_bekle = 15.0   # açma sonrası TV'nin ağda görünmesi beklenir (0 = doğrulama yok)

    def _acilmayi_bekle(self, c: EvCihazi, sure: float) -> bool:
        son = time.monotonic() + sure
        while True:
            try:
                if self.cevrimici(c) == "acik":
                    return True
            except Exception:
                pass
            if time.monotonic() >= son:
                return False
            time.sleep(1.0)

    def wol(self, c: EvCihazi) -> Sonuc:
        destek, ipucu = self.ac_destegi(c)
        if not c.mac:
            return Sonuc(False, f"{c.gorunen_ad}: MAC adresi bilinmiyor; ağdan açılamaz")
        hedefler = ["255.255.255.255"]
        if c.adres and c.adres.count(".") == 3:  # çok ağ kartlı PC'de genel yayın yanlış karttan çıkabilir
            hedefler.append(c.adres.rsplit(".", 1)[0] + ".255")
        try:
            for h in hedefler:
                for port in (9, 7):
                    self.tasima.wol_gonder(c.mac, yayin=h, port=port)
        except YazmaKilitli as e:
            return Sonuc(False, str(e))
        except Exception as e:
            return Sonuc(False, f"Açma sinyali gönderilemedi: {e}")
        if not self.wol_bekle:
            return Sonuc(True, "Açma sinyali gönderildi (Wake-on-LAN)", True, False)
        if self._acilmayi_bekle(c, self.wol_bekle):
            return Sonuc(True, "Açıldı (Wake-on-LAN, ağda görüldü)", True, True)
        return Sonuc(False, f"açma sinyali gönderdim ama televizyon {int(self.wol_bekle)} saniyede açılmadı. {ipucu}")

    def _tv_ac(self, c: EvCihazi) -> Sonuc:
        """Önce platformun kendi yolu (Tizen bekleme → KEY_POWER, Android TV WAKEUP), sonra WoL; doğrulanır."""
        for aile in ("androidtv", "tizen"):
            a = self.adaptorler.get(aile)
            if a is None or aile not in self._aileler(c) or "guc" not in c.yetenekler:
                continue
            s = a.uygula(c, "guc", True)
            if s.ok:
                if not self.wol_bekle or s.dogrulandi or self._acilmayi_bekle(c, min(self.wol_bekle, 10.0)):
                    return Sonuc(True, s.mesaj, True, True)
        return self.wol(c)

    # ------------------------------------------------------------ uygulama açma (içerikli, doğrulanır)
    def uygulama_ac(self, c: EvCihazi, ad: str, icerik: str | None = None, bekle: float = 6.0) -> Sonuc:
        """Uygulamayı (ve varsa içeriği) TV'nin platform yöntemleriyle sırayla dener; her denemeden sonra TV'den
        uygulamanın açıldığını okur. Doğrulanmadıysa başarı denmez; denenen yollar ve nedenleri döner."""
        from .tv_yardim import video_bul, youtube_mu, genel_mi
        try:
            self.tasima.yazma_denetle(f"{c.gorunen_ad}: {ad} aç")
        except YazmaKilitli as e:
            return Sonuc(False, str(e))
        video, notlar = None, []
        if icerik and youtube_mu(ad):
            video = (self.video_bulucu or video_bul)(icerik)
            if not video:
                notlar.append(f"'{icerik}' için YouTube'da video bulamadım (internet?)")
        guc = "bilinmiyor"
        try:
            guc = self.cevrimici(c)
        except Exception:
            pass
        if guc in ("kapali", "bekleme"):
            s = self._tv_ac(c)
            if not s.ok:
                return Sonuc(False, f"{c.gorunen_ad} kapalı görünüyor; {s.mesaj}")
        yollar = []
        for aile in self._aileler(c):
            a = self.adaptorler[aile]
            if hasattr(a, "uygulama_yollari"):
                try:
                    yollar += [(aile, *y) for y in a.uygulama_yollari(c, ad, video)]
                except Exception as e:
                    notlar.append(f"{aile}: {type(e).__name__}")
        if video:  # içerik taşıyan yollar önce
            yollar.sort(key=lambda y: not y[2])
        if not yollar:
            a = self._adaptor_for(c, "uygulama")
            if a is None:
                return Sonuc(False, f"{c.gorunen_ad}: uygulama açma yolu yok")
            return a.uygula(c, "uygulama", ad)
        denenen = []
        for aile, etiket, icerikli, gonder in yollar:
            try:
                s = gonder()
            except YazmaKilitli as e:
                return Sonuc(False, str(e))
            except Exception as e:
                denenen.append(f"{etiket}: {type(e).__name__}: {e}"[:160])
                continue
            if not s.ok:
                denenen.append(f"{etiket}: {s.mesaj}")
                continue
            dogru = self._uygulama_dogrula(c, ad, bekle)
            if dogru is None:
                return Sonuc(True, f"{etiket}: istek kabul edildi (bu TV'de açıldığı okunamıyor)",
                             {"yol": etiket, "video": video if icerikli else None, "icerik": icerik,
                              "genel": genel_mi(icerik or ""), "icerik_eksik": bool(icerik) and not (video and icerikli),
                              "notlar": notlar}, False)
            if dogru:
                eksik = bool(icerik) and not (video and icerikli)
                metin = f"{etiket} ile açıldı" + ("; içerik gönderilemedi" if eksik and video else "")
                return Sonuc(True, metin, {"yol": etiket, "video": video if icerikli else None,
                                           "icerik": icerik, "genel": genel_mi(icerik or ""),
                                           "icerik_eksik": eksik, "notlar": notlar}, True)
            denenen.append(f"{etiket}: istek kabul edildi ama uygulama TV ekranında görünmedi")
        return Sonuc(False, f"{ad} televizyonda açılamadı. " + "; ".join(notlar + denenen))

    def _uygulama_dogrula(self, c: EvCihazi, ad: str, bekle: float) -> bool | None:
        """True: TV'de açık görüldü; False: görülmedi; None: hiçbir platform okuyamıyor."""
        son = time.monotonic() + max(0.0, bekle)
        while True:
            bilinen = False
            for aile in self._aileler(c):
                f = getattr(self.adaptorler[aile], "uygulama_calisiyor", None)
                if f is None:
                    continue
                try:
                    r = f(c, ad)
                except Exception:
                    r = None
                if r:
                    return True
                bilinen = bilinen or r is not None
            if not bilinen:
                return None
            if time.monotonic() >= son:
                return False
            time.sleep(0.7)

    def uygula(self, c: EvCihazi, yetenek: str, deger: Any = None, adim: int | None = None,
               goreli: float | None = None, icerik: str | None = None) -> Sonuc:
        with self._kilit:
            # TV açma: platform yolu (bekleme/Android) → Wake-on-LAN; TV'nin ağda görünmesiyle doğrulanır
            if yetenek == "guc" and deger and (c.tur == "tv" or c.aile in TV_AILELERI):
                return self._tv_ac(c)
            if yetenek == "uygulama" and (c.tur == "tv" or c.aile in TV_AILELERI) and deger:
                return self.uygulama_ac(c, str(deger), icerik)
            # göreli ayar (ses/parlaklık): mevcut değer okunur, adım eklenir
            if yetenek == "ses_adim" and "ses_duzeyi" in c.yetenekler and c.yetenekler["ses_duzeyi"].yazilir \
                    and c.yetenekler["ses_duzeyi"].okunur and ((adim or 1) > 1 or "ses_adim" not in c.yetenekler):
                goreli, yetenek = (adim or 1) * (1 if deger == "yukari" else -1), "ses_duzeyi"
            if goreli is not None:
                y = c.yetenekler.get(yetenek)
                if y is None:
                    return Sonuc(False, f"{c.gorunen_ad}: '{yetenek}' yeteneği yok")
                try:
                    simdi = self._adaptor_for(c, yetenek).durum(c).get(yetenek)
                except Exception as e:
                    return Sonuc(False, f"{c.gorunen_ad}: mevcut değer okunamadı ({type(e).__name__})")
                if simdi is None:
                    return Sonuc(False, f"{c.gorunen_ad}: mevcut değer okunamadı")
                deger = float(simdi) + goreli
            if yetenek == "ses_adim" and "ses_adim" not in c.yetenekler:
                return Sonuc(False, f"{c.gorunen_ad}: sesi adım adım ayarlama yok")
            a = self._adaptor_for(c, yetenek)
            if a is None:
                return Sonuc(False, f"{c.gorunen_ad}: bu cihaz için bağlantı yok")
            if yetenek in ("ses_adim", "kanal_adim") and adim and adim > 1:
                son = Sonuc(False, "")
                for _ in range(min(int(adim), 15)):
                    son = a.uygula(c, yetenek, deger)
                    if not son.ok:
                        return son
                return son
            return a.uygula(c, yetenek, deger)

    # ------------------------------------------------------------ eşleştirme / anahtar
    def eslestir(self, c: EvCihazi, aile: str | None = None, kod: str | None = None) -> Sonuc:
        """KULLANICI BAŞINDAYKEN çağrılır (TV'de istem çıkarır). Yazma kilidi açık Tasima gerekir."""
        adaylar = [aile] if aile else self._aileler(c)
        for a_ad in adaylar:
            a = self.adaptorler.get(a_ad)
            if a is None or not hasattr(a, "eslestir"):
                continue
            durum = (c.protokol.get("erisim_aileler", {}).get(a_ad) or [""])[0]
            if not aile and durum not in (ESLESTIRME_GEREKLI, ""):
                continue
            try:
                s = a.eslestir(c, kod) if kod is not None else a.eslestir(c)
            except YazmaKilitli as e:
                return Sonuc(False, str(e))
            except Exception as e:
                return Sonuc(False, f"Eşleştirme olmadı: {type(e).__name__}: {e}")
            if s.ok and isinstance(s.deger, dict):
                self.sirlar.yaz(c, **s.deger)
                s.deger = {k: "***" for k in s.deger}  # sır arayüze/kayda dönmez
                self.yetenekleri_sorgula(c)
                self.kayit.kaydet()
            return s
        return Sonuc(False, f"{c.gorunen_ad}: eşleştirme gerektiren bağlantı yok")

    def anahtar_ver(self, c: EvCihazi, **alanlar: str) -> dict[str, Any]:
        """Kullanıcının girdiği yerel anahtar/token/parola → DPAPI depo, ardından yetenekler yeniden sorgulanır."""
        self.sirlar.yaz(c, **alanlar)
        return self.yetenekleri_sorgula(c)

    # ------------------------------------------------------------ kayıt kısayolları
    def cihazlar(self) -> list[EvCihazi]:
        return self.kayit.tumu()

    def bul(self, kimlik: str) -> EvCihazi | None:
        return self.kayit.al(kimlik)


def eski_bicim(c: EvCihazi) -> dict[str, Any]:
    """SmartHomeSkill.discover_wifi_devices ve panelin eski açılır listesi için geriye uyumlu sözlük."""
    protokol = {"webos": "dlna_tv", "tizen": "dlna_tv", "upnp_av": "dlna_tv", "dial": "dlna_tv",
                "androidtv": "android_tv", "tuya_yerel": "tuya", "miio": "xiaomi", "kasa": "tapo",
                "yeelight": "yeelight"}.get(c.aile, c.aile)
    return {"ip": c.adres, "info": " ".join(x for x in (c.gorunen_ad, f"({c.marka} {c.model})".replace("( ", "(")
                                                        if (c.marka or c.model) else "") if x).strip(),
            "protocol": protokol, "device_type": c.tur, "erisim": c.erisim, "erisim_notu": c.erisim_notu,
            "kimlik": c.kimlik, "aile": c.aile, "yetenekler": sorted(c.yetenekler), "model": c.model,
            "marka": c.marka, "mac": c.mac}


__all__ = ["EvYoneticisi", "eski_bicim", "erisim_ozeti", "adaptorleri_yukle", "ONCELIK"]
