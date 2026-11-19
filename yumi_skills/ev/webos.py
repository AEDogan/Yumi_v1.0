"""LG webOS TV adaptörü (SSAP / WebSocket, yerel ağ).

Eşleştirme: ilk ``eslestir()`` çağrısında TV ekranında izin istemi çıkar (kumandayla kabul);
TV bir istemci anahtarı (client-key) döndürür → DPAPI'li depoya yazılır (kayıt json'una DEĞİL).
Yetenekler eşleştirmeden sonra TV'den sorgulanır: api/getServiceList, listLaunchPoints,
tv/getExternalInputList, audio/getStatus. Eşleştirme yoksa erişim 'eslestirme_gerekli'.
Kaynak: aiowebostv 1.1.0 (Apache-2.0) uç noktaları ve kayıt yükü; imzasız manifest
(yeni yazılımlar imzayı reddediyor, aiowebostv de imzasız gönderiyor).
"""
from __future__ import annotations

import itertools
import json
from typing import Any, Callable

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import (BOOL, ESLESTIRME_GEREKLI, HAZIR, SECIM, TAMSAYI, Sonuc, Yetenek)
from .tasima import TasimaHatasi
from .ws import WebSocket

IZINLER = sorted({
    "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CLOSE", "CONTROL_AUDIO", "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_POWER",
    "CONTROL_TV_SCREEN", "READ_APP_STATUS", "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST",
    "READ_NETWORK_STATE", "READ_RUNNING_APPS", "READ_TV_CHANNEL_LIST", "READ_POWER_STATE",
    "READ_COUNTRY_INFO", "READ_INSTALLED_APPS", "READ_SETTINGS", "CONTROL_INPUT_TEXT",
    "CONTROL_MOUSE_AND_KEYBOARD", "READ_UPDATE_INFO", "READ_TV_CURRENT_TIME", "WRITE_NOTIFICATION_TOAST"})


def kayit_mesaji(istemci_anahtari: str = "") -> dict:
    yuk: dict[str, Any] = {"forcePairing": False, "pairingType": "PROMPT",
                           "manifest": {"appVersion": "1.1", "manifestVersion": 1, "permissions": IZINLER}}
    if istemci_anahtari:
        yuk["client-key"] = istemci_anahtari
    return {"type": "register", "id": "register_0", "payload": yuk}


# Okuma uç noktaları (salt okunur kipte izinli olanlar)
OKUMA = {"api/getServiceList", "audio/getStatus", "audio/getVolume",
         "com.webos.applicationManager/listLaunchPoints", "com.webos.applicationManager/getForegroundAppInfo",
         "tv/getExternalInputList", "tv/getCurrentChannel", "system/getSystemInfo",
         "com.webos.service.update/getCurrentSWInformation", "com.webos.service.tvpower/power/getPowerState"}

YAZMA = {
    "ses_duzeyi": ("audio/setVolume", lambda v: {"volume": v}),
    "sessiz": ("audio/setMute", lambda v: {"mute": bool(v)}),
    "ses_adim": (None, None),  # yukari/asagi → audio/volumeUp|volumeDown
    "kanal_adim": (None, None),
    "kanal": ("tv/openChannel", lambda v: {"channelNumber": str(v)}),
    "giris": ("tv/switchInput", lambda v: {"inputId": v}),
    "uygulama": ("com.webos.applicationManager/launch", lambda v: {"id": v}),
    "guc": (None, None),
    "oynatma": (None, None),
}


class WebOsOturumu:
    """Tek bağlantı: kayıt (anahtarla sessiz) + istek/yanıt."""

    def __init__(self, adres: str, istemci_anahtari: str, ws_fabrikasi: Callable[..., Any] = WebSocket,
                 parmak_izi: str = "", zaman_asimi: float = 5.0):
        self.ws = None
        son_hata: Exception | None = None
        for url in (f"wss://{adres}:3001/", f"ws://{adres}:3000/"):
            try:
                self.ws = ws_fabrikasi(url, zaman_asimi=zaman_asimi, parmak_izi=parmak_izi if url.startswith("wss") else "")
                break
            except Exception as e:  # 3001 kapalıysa eski yazılım: 3000
                son_hata = e
        if self.ws is None:
            raise TasimaHatasi(f"webOS bağlantısı kurulamadı: {son_hata}")
        self.parmak_izi = getattr(self.ws, "parmak_izi", "")
        self._sayac = itertools.count(1)
        self.istemci_anahtari = istemci_anahtari

    def kaydol(self, istem_bekle: bool = False, en_fazla_mesaj: int = 6) -> str:
        """Anahtarla kayıt (istemsiz). Anahtar yoksa TV istem gösterir: yalnız eslestir() çağırır."""
        if not self.istemci_anahtari and not istem_bekle:
            raise TasimaHatasi("istemci anahtarı yok; önce eşleştirme gerekir")
        self.ws.gonder(json.dumps(kayit_mesaji(self.istemci_anahtari)))
        for _ in range(en_fazla_mesaj if not istem_bekle else 60):
            m = json.loads(self.ws.al())
            if m.get("type") == "registered":
                self.istemci_anahtari = (m.get("payload") or {}).get("client-key", self.istemci_anahtari)
                return self.istemci_anahtari
            if m.get("type") == "error":
                raise TasimaHatasi(f"webOS kaydı reddedildi: {m.get('error')}")
        raise TasimaHatasi("webOS kaydı yanıtsız (TV istemini kabul edin)")

    def iste(self, uri: str, yuk: dict | None = None) -> dict:
        kimlik = f"y{next(self._sayac)}"
        mesaj = {"type": "request", "id": kimlik, "uri": "ssap://" + uri}
        if yuk is not None:
            mesaj["payload"] = yuk
        self.ws.gonder(json.dumps(mesaj))
        for _ in range(20):
            m = json.loads(self.ws.al())
            if m.get("id") == kimlik:
                if m.get("type") == "error":
                    raise TasimaHatasi(f"{uri}: {m.get('error')}")
                return m.get("payload") or {}
        raise TasimaHatasi(f"{uri}: yanıt yok")

    def kapat(self):
        try:
            self.ws.kapat()
        except Exception:
            pass


@kaydet
class WebOsAdaptoru(Adaptor):
    aile = "webos"
    bulucu_aileleri = ("webos",)

    def __init__(self, *a, ws_fabrikasi: Callable[..., Any] = WebSocket, **k):
        super().__init__(*a, **k)
        self.ws_fabrikasi = ws_fabrikasi

    def cihaz_olustur(self, bulunan):
        c = bos_cihaz(bulunan, self.aile, bulunan.alan("udn") or f"webos:{bulunan.mac or bulunan.adres}")
        c.tur = "tv"
        c.erisim, c.erisim_notu = ESLESTIRME_GEREKLI, "TV ekranındaki Yumi bağlantı istemini kumandayla bir kez kabul et"
        return c

    def _oturum(self, cihaz) -> WebOsOturumu:
        anahtar = self.sirlar(cihaz).get("istemci_anahtari", "")
        o = WebOsOturumu(cihaz.adres, anahtar, self.ws_fabrikasi, cihaz.protokol.get("tls_parmak_izi", ""))
        o.kaydol()
        return o

    def eslestir(self, cihaz) -> Sonuc:
        """KULLANICI BAŞINDAYKEN: TV'de istem çıkar. Dönen anahtar Sonuc.deger'dedir → DPAPI depoya."""
        self.tasima.yazma_denetle("webOS eşleştirme istemi")
        o = WebOsOturumu(cihaz.adres, "", self.ws_fabrikasi, zaman_asimi=60.0)
        try:
            anahtar = o.kaydol(istem_bekle=True)
            cihaz.protokol["tls_parmak_izi"] = o.parmak_izi
            cihaz.erisim = HAZIR
            return Sonuc(True, "webOS eşleşti", {"istemci_anahtari": anahtar}, True)
        finally:
            o.kapat()

    def yetenekler(self, cihaz):
        if not self.sirlar(cihaz).get("istemci_anahtari"):
            cihaz.erisim = ESLESTIRME_GEREKLI
            return {}
        o = self._oturum(cihaz)
        try:
            servisler = {s.get("name") for s in o.iste("api/getServiceList").get("services", [])}
            yet: dict[str, Yetenek] = {}
            k = "webOS SSAP"
            yet["guc"] = Yetenek("guc", BOOL, True, True, kaynak=k + " system/turnOff (+ açma: Wake-on-LAN, MAC gerekli)")
            if "audio" in servisler or not servisler:
                ses = o.iste("audio/getStatus")
                yet["ses_duzeyi"] = Yetenek("ses_duzeyi", TAMSAYI, True, True, 0, 100, 1, kaynak=k + " audio/getStatus",
                                            protokol={"ses_cikisi": ses.get("scenario", "")})
                yet["sessiz"] = Yetenek("sessiz", BOOL, True, True, kaynak=k + " audio")
                yet["ses_adim"] = Yetenek("ses_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak=k)
            if "tv" in servisler or not servisler:
                girisler = o.iste("tv/getExternalInputList").get("devices", [])
                if girisler:
                    yet["giris"] = Yetenek("giris", SECIM, False, True, secenekler=[g.get("id", "") for g in girisler],
                                           kaynak=k + " tv/getExternalInputList",
                                           protokol={"adlar": {g.get("id", ""): g.get("label", "") for g in girisler}})
                yet["kanal"] = Yetenek("kanal", TAMSAYI, True, True, 0, 9999, 1, kaynak=k + " tv/getCurrentChannel")
                yet["kanal_adim"] = Yetenek("kanal_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak=k)
            uyg = o.iste("com.webos.applicationManager/listLaunchPoints").get("launchPoints", [])
            if uyg:
                yet["uygulama"] = Yetenek("uygulama", SECIM, True, True, secenekler=[u.get("id", "") for u in uyg],
                                          kaynak=k + " listLaunchPoints (TV'nin kurulu uygulama listesi)",
                                          protokol={"adlar": {u.get("id", ""): u.get("title", "") for u in uyg},
                                                    "liste_kaynagi": "cihaz"})
            yet["oynatma"] = Yetenek("oynatma", SECIM, False, True, secenekler=["oynat", "duraklat", "durdur"],
                                     kaynak=k + " media.controls")
            cihaz.erisim, cihaz.erisim_notu = HAZIR, "eşleşmiş"
            for y in yet.values():
                cihaz.yetenek_ekle(y)
            return yet
        finally:
            o.kapat()

    def durum(self, cihaz):
        if not self.sirlar(cihaz).get("istemci_anahtari"):
            return {}
        o = self._oturum(cihaz)
        try:
            d: dict[str, Any] = {}
            ses = o.iste("audio/getStatus")
            d["ses_duzeyi"], d["sessiz"] = ses.get("volume"), ses.get("mute")
            try:
                d["guc"] = o.iste("com.webos.service.tvpower/power/getPowerState").get("state") == "Active"
            except TasimaHatasi:
                d["guc"] = True  # yanıt verdiyse açık
            try:
                d["uygulama"] = o.iste("com.webos.applicationManager/getForegroundAppInfo").get("appId", "")
                d["kanal"] = o.iste("tv/getCurrentChannel").get("channelNumber")
            except TasimaHatasi:
                pass
            return d
        finally:
            o.kapat()

    def uygulama_yollari(self, cihaz, ad: str, video: str | None = None):
        if not self.sirlar(cihaz).get("istemci_anahtari"):
            return []
        yuk = {"id": ad}
        if video and "youtube" in ad.lower():
            yuk["params"] = {"contentTarget": f"https://www.youtube.com/tv?v={video}"}

        def ac():
            self.tasima.yazma_denetle(f"webOS uygulama {ad}")
            o = self._oturum(cihaz)
            try:
                o.iste("com.webos.applicationManager/launch", yuk)
            finally:
                o.kapat()
            return Sonuc(True, "webOS launch gönderildi")
        return [("webOS launch" + (" (contentTarget)" if "params" in yuk else ""), "params" in yuk, ac)]

    def uygulama_calisiyor(self, cihaz, ad: str):
        if not self.sirlar(cihaz).get("istemci_anahtari"):
            return None
        o = self._oturum(cihaz)
        try:
            return o.iste("com.webos.applicationManager/getForegroundAppInfo").get("appId", "") == ad
        except Exception:
            return None
        finally:
            o.kapat()

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"webOS {y.ad}={deger}")
        if y.ad == "guc" and deger:
            return Sonuc(False, "webOS açma Wake-on-LAN ister (MAC ile yonetici.wol_gonder)")
        o = self._oturum(cihaz)
        try:
            if y.ad == "guc":
                o.iste("system/turnOff")
                return Sonuc(True, "Kapatma gönderildi")
            if y.ad == "ses_adim":
                o.iste("audio/volumeUp" if deger == "yukari" else "audio/volumeDown")
            elif y.ad == "kanal_adim":
                o.iste("tv/channelUp" if deger == "yukari" else "tv/channelDown")
            elif y.ad == "oynatma":
                o.iste({"oynat": "media.controls/play", "duraklat": "media.controls/pause",
                        "durdur": "media.controls/stop"}[deger])
            else:
                uri, yuk = YAZMA[y.ad]
                o.iste(uri, yuk(deger))
            if y.ad in ("ses_duzeyi", "sessiz"):
                ses = o.iste("audio/getStatus")
                geri = ses.get("volume") if y.ad == "ses_duzeyi" else ses.get("mute")
                return Sonuc(geri == deger, f"{y.etiket}: {geri}", geri, geri == deger)
            return Sonuc(True, f"{y.etiket}: {deger} gönderildi")
        finally:
            o.kapat()
