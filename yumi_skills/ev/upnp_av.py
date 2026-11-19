"""UPnP/DLNA MediaRenderer adaptörü: RenderingControl (ses, sessiz) ve AVTransport (oynatma).

Yetenekler cihazın SCPD (servis tanımı) belgesinden çıkarılır: eylem listesi ve
Volume durum değişkeninin allowedValueRange'i. Eşleştirme gerekmez (DLNA açık TV'ler).
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import BOOL, HAZIR, SECIM, TAMSAYI, METIN, Sonuc, Yetenek

RC = "urn:schemas-upnp-org:service:RenderingControl:"
AVT = "urn:schemas-upnp-org:service:AVTransport:"


def scpd_coz(kok) -> tuple[set[str], dict[str, dict]]:
    """SCPD XML kökü → (eylem adları, {durum değişkeni: {min,max,step,izinli}})."""
    eylemler, degiskenler = set(), {}
    for e in kok.iter():
        etiket = e.tag.split("}")[-1]
        if etiket == "action":
            ad = next((c.text for c in e if c.tag.split("}")[-1] == "name"), None)
            if ad:
                eylemler.add(ad.strip())
        elif etiket == "stateVariable":
            ad = next((c.text for c in e if c.tag.split("}")[-1] == "name"), None)
            if not ad:
                continue
            bilgi: dict[str, Any] = {}
            for c in e.iter():
                t = c.tag.split("}")[-1]
                if t in ("minimum", "maximum", "step") and c.text:
                    try:
                        bilgi[t] = float(c.text)
                    except ValueError:
                        pass
                elif t == "allowedValue" and c.text:
                    bilgi.setdefault("izinli", []).append(c.text.strip())
            degiskenler[ad.strip()] = bilgi
    return eylemler, degiskenler


def renderer_servisleri(bulunan) -> dict[str, dict[str, str]]:
    """Bulucu kanıtlarından {'rc': {...}, 'avt': {...}} (mutlak controlURL/SCPDURL ile)."""
    sonuc: dict[str, dict[str, str]] = {}
    for k in getattr(bulunan, "kanitlar", []):
        a = k.alanlar
        if not a.get("upnp_servisler") or not a.get("location"):
            continue
        taban = a.get("urlbase") or a["location"]
        try:
            servisler = json.loads(a["upnp_servisler"])
        except ValueError:
            continue
        for s in servisler:
            st = s.get("serviceType", "")
            anahtar = "rc" if st.startswith(RC) else "avt" if st.startswith(AVT) else ""
            if anahtar and anahtar not in sonuc:
                sonuc[anahtar] = {"tur": st,
                                  "kontrol": urllib.parse.urljoin(taban, s.get("controlURL", "")),
                                  "scpd": urllib.parse.urljoin(taban, s.get("SCPDURL", "")),
                                  "udn": a.get("udn", "")}
    return sonuc


@kaydet
class UpnpAvAdaptoru(Adaptor):
    aile = "upnp_av"
    bulucu_aileleri = ("upnp-medya",)

    def uygun_mu(self, bulunan) -> bool:
        return bool(renderer_servisleri(bulunan))

    def cihaz_olustur(self, bulunan):
        s = renderer_servisleri(bulunan)
        udn = next((v["udn"] for v in s.values() if v.get("udn")), "")
        c = bos_cihaz(bulunan, self.aile, udn or f"upnp:{bulunan.adres}")
        c.protokol = {"servisler": s}
        c.erisim, c.erisim_notu = HAZIR, "DLNA/UPnP; eşleştirme gerekmez (TV'de DLNA kapalıysa yanıt vermez)"
        return c

    def yetenekler(self, cihaz):
        s = cihaz.protokol.get("servisler", {})
        yet: dict[str, Yetenek] = {}
        if "rc" in s:
            eylemler, deg = scpd_coz(self.tasima.get_xml(s["rc"]["scpd"]))
            if "GetVolume" in eylemler:
                v = deg.get("Volume", {})
                yet["ses_duzeyi"] = Yetenek("ses_duzeyi", TAMSAYI, True, "SetVolume" in eylemler,
                                            v.get("minimum", 0), v.get("maximum", 100), v.get("step", 1),
                                            kaynak="UPnP RenderingControl SCPD")
            if "GetMute" in eylemler:
                yet["sessiz"] = Yetenek("sessiz", BOOL, True, "SetMute" in eylemler,
                                        kaynak="UPnP RenderingControl SCPD")
        if "avt" in s:
            eylemler, deg = scpd_coz(self.tasima.get_xml(s["avt"]["scpd"]))
            secenek = [e.lower() for e in ("Play", "Pause", "Stop") if e in eylemler]
            if "GetTransportInfo" in eylemler or secenek:
                yet["oynatma"] = Yetenek("oynatma", SECIM, "GetTransportInfo" in eylemler, bool(secenek),
                                         secenekler=[{"play": "oynat", "pause": "duraklat", "stop": "durdur"}[x]
                                                     for x in secenek],
                                         kaynak="UPnP AVTransport SCPD (yalnız DLNA ile gönderilen medya)")
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        s = cihaz.protokol.get("servisler", {})
        d: dict[str, Any] = {}
        if "rc" in s:
            rc = s["rc"]
            if "ses_duzeyi" in cihaz.yetenekler:
                d["ses_duzeyi"] = int(self.tasima.soap(rc["kontrol"], rc["tur"], "GetVolume",
                                                       {"InstanceID": 0, "Channel": "Master"}).get("CurrentVolume", 0))
            if "sessiz" in cihaz.yetenekler:
                d["sessiz"] = self.tasima.soap(rc["kontrol"], rc["tur"], "GetMute",
                                               {"InstanceID": 0, "Channel": "Master"}).get("CurrentMute") in ("1", "true")
        if "avt" in s and cihaz.yetenekler.get("oynatma", Yetenek("", METIN, False)).okunur:
            avt = s["avt"]
            d["oynatma"] = self.tasima.soap(avt["kontrol"], avt["tur"], "GetTransportInfo",
                                            {"InstanceID": 0}).get("CurrentTransportState", "")
        return d

    def _uygula(self, cihaz, y, deger):
        s = cihaz.protokol.get("servisler", {})
        if y.ad == "ses_duzeyi":
            rc = s["rc"]
            self.tasima.soap(rc["kontrol"], rc["tur"], "SetVolume",
                             {"InstanceID": 0, "Channel": "Master", "DesiredVolume": deger})
            geri = self.durum(cihaz).get("ses_duzeyi")
            return Sonuc(geri == deger, f"Ses {geri}", geri, geri == deger)
        if y.ad == "sessiz":
            rc = s["rc"]
            self.tasima.soap(rc["kontrol"], rc["tur"], "SetMute",
                             {"InstanceID": 0, "Channel": "Master", "DesiredMute": int(deger)})
            geri = self.durum(cihaz).get("sessiz")
            return Sonuc(geri == deger, "Sessiz" if geri else "Ses açık", geri, geri == deger)
        if y.ad == "oynatma":
            avt = s["avt"]
            eylem = {"oynat": "Play", "duraklat": "Pause", "durdur": "Stop"}[deger]
            self.tasima.soap(avt["kontrol"], avt["tur"], eylem, {"InstanceID": 0, **({"Speed": 1} if eylem == "Play" else {})})
            return Sonuc(True, f"{deger} gönderildi")
        return super()._uygula(cihaz, y, deger)
