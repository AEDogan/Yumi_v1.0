"""Samsung Tizen TV adaptörü (2016+): REST bilgi ucu (8001, kimliksiz, salt okunur) +
uzaktan kumanda WebSocket'i (8002 wss, belirteçli).

Kimliksiz okunanlar: model, güç durumu (PowerState), desteklenen özellikler (isSupport),
kurulu uygulama durumu (GET /api/v2/applications/<id>, 200=kurulu, 404=yok).
Eşleştirme: ilk WebSocket bağlantısında TV'de izin istemi; dönen belirteç DPAPI depoya.
Kumanda tuşları (KEY_*) yalnız gönderilir; TV tuş için durum döndürmez → ses düzeyi
okuması aynı TV'nin UPnP RenderingControl'ünden (upnp_av) gelir.
Kaynak: samsungtvws 3.0.7 (MIT) mesaj biçimleri.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Callable

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import BOOL, ESLESTIRME_GEREKLI, HAZIR, SECIM, Sonuc, Yetenek
from .tasima import TasimaHatasi
from .ws import WebSocket

UYGULAMA_KIMLIKLERI = {  # topluluk listesi (samsungtvws/HA); cihaz yanıtı belirleyici
    "YouTube": "111299001912", "Netflix": "3201907018807", "Prime Video": "3201910019365",
    "Spotify": "3201606009684", "Disney+": "3201901017640", "Tarayıcı": "org.tizen.browser",
}
TUSLAR = ["KEY_POWER", "KEY_VOLUP", "KEY_VOLDOWN", "KEY_MUTE", "KEY_CHUP", "KEY_CHDOWN", "KEY_SOURCE",
          "KEY_HOME", "KEY_RETURN", "KEY_ENTER", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
          "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_MENU", "KEY_HDMI"] + [f"KEY_{i}" for i in range(10)]
UYGULAMA_ADI = "Yumi"


def bilgi_coz(js: dict) -> dict[str, Any]:
    d = js.get("device") or {}
    destek = {}
    try:
        destek = json.loads(js.get("isSupport") or d.get("isSupport") or "{}")
    except ValueError:
        pass
    return {"model": d.get("modelName", ""), "ad": d.get("name", ""), "guc": d.get("PowerState", ""),
            "belirtec_destek": str(d.get("TokenAuthSupport", "")).lower() == "true",
            "mac": d.get("wifiMac", ""), "os": d.get("OS", ""), "destek": destek,
            "ses_destek": str(d.get("VoiceSupport", "")).lower() == "true"}


@kaydet
class TizenAdaptoru(Adaptor):
    aile = "tizen"
    bulucu_aileleri = ("tizen",)

    def __init__(self, *a, ws_fabrikasi: Callable[..., Any] = WebSocket, **k):
        super().__init__(*a, **k)
        self.ws_fabrikasi = ws_fabrikasi

    def cihaz_olustur(self, bulunan):
        c = bos_cihaz(bulunan, self.aile, bulunan.alan("udn") or f"tizen:{bulunan.mac or bulunan.adres}")
        c.tur = "tv"
        c.erisim, c.erisim_notu = ESLESTIRME_GEREKLI, "TV ekranındaki izin istemini kumandayla bir kez kabul et"
        return c

    def _bilgi(self, cihaz) -> dict[str, Any]:
        return bilgi_coz(self.tasima.get_json(f"http://{cihaz.adres}:8001/api/v2/"))

    def _ws_url(self, belirtec: str) -> str:
        ad = base64.b64encode(UYGULAMA_ADI.encode()).decode()
        return (f"wss://{{}}:8002/api/v2/channels/samsung.remote.control?name={ad}"
                + (f"&token={belirtec}" if belirtec else ""))

    def yetenekler(self, cihaz):
        b = self._bilgi(cihaz)
        cihaz.protokol.update({"guc_durumu": b["guc"], "isSupport": b["destek"], "os": b["os"]})
        if b["mac"] and not cihaz.mac:
            cihaz.mac = b["mac"].upper()
        yet: dict[str, Yetenek] = {}
        k = "Samsung REST /api/v2"
        yet["guc"] = Yetenek("guc", BOOL, bool(b["guc"]), True, kaynak=k + " PowerState (+ açma: Wake-on-LAN)")
        # 18 Kas: uygulama listesi önce CİHAZDAN (belirteçle WebSocket ed.installedApp.get); olmazsa bilinen
        # kimlik tablosu REST ile yoklanır (200=kurulu). Kaynak kartta gösterilir (liste_kaynagi).
        kimlikler, liste_kaynagi = {}, ""
        if self.sirlar(cihaz).get("istemci_anahtari"):
            try:
                kimlikler = self.kurulu_uygulamalar(cihaz)
                liste_kaynagi = "cihaz" if kimlikler else ""
            except Exception as e:
                cihaz.protokol["uygulama_listesi_hatasi"] = f"{type(e).__name__}: {e}"[:160]
        if not kimlikler:
            for ad, kimlik in UYGULAMA_KIMLIKLERI.items():
                try:
                    kod, _, _ = self.tasima.get(f"http://{cihaz.adres}:8001/api/v2/applications/{kimlik}", sinir=8192)
                except (OSError, TasimaHatasi):
                    continue
                if kod == 200:
                    kimlikler[ad] = kimlik
            liste_kaynagi = "tablo" if kimlikler else ""
        if kimlikler:
            yet["uygulama"] = Yetenek("uygulama", SECIM, True, True, secenekler=list(kimlikler),
                                      kaynak=k + (" ed.installedApp.get (TV'nin kurulu uygulama listesi)"
                                                  if liste_kaynagi == "cihaz" else " applications/<id> (bilinen kimlikler yoklandı, 200=kurulu)"),
                                      protokol={"kimlikler": kimlikler, "liste_kaynagi": liste_kaynagi})
        if b["destek"].get("remote_available", "true") != "false":
            yet["ses_adim"] = Yetenek("ses_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak="KEY_VOLUP/DOWN")
            yet["kanal_adim"] = Yetenek("kanal_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak="KEY_CHUP/DOWN")
            yet["tus"] = Yetenek("tus", SECIM, False, True, secenekler=list(TUSLAR), kaynak="ms.remote.control")
        belirtec = self.sirlar(cihaz).get("istemci_anahtari", "")
        cihaz.erisim = HAZIR if belirtec else ESLESTIRME_GEREKLI
        cihaz.erisim_notu = "eşleşmiş" if belirtec else ("güç/uygulama durumu okunur; kumanda için TV'de izin istemini kabul et")
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def kurulu_uygulamalar(self, cihaz) -> dict[str, str]:
        """TV'nin kurulu uygulama listesi (ad → appId); salt okunur WebSocket olayı, belirteç gerekir."""
        belirtec = self.sirlar(cihaz).get("istemci_anahtari", "")
        if not belirtec:
            return {}
        ws, _ = self._baglan(cihaz, belirtec)
        try:
            ws.gonder(json.dumps({"method": "ms.channel.emit",
                                  "params": {"event": "ed.installedApp.get", "to": "host"}}))
            for _ in range(12):
                m = json.loads(ws.al())
                if m.get("event") == "ed.installedApp.get":
                    liste = (m.get("data") or {}).get("data") or []
                    return {a["name"]: a["appId"] for a in liste if a.get("name") and a.get("appId")}
        finally:
            ws.kapat()
        return {}

    def _kimlik(self, cihaz, ad: str) -> str:
        y = cihaz.yetenekler.get("uygulama")
        kimlikler = (y.protokol.get("kimlikler", {}) if y else {}) or {}
        return kimlikler.get(ad) or UYGULAMA_KIMLIKLERI.get(ad) or next(
            (v for k2, v in {**UYGULAMA_KIMLIKLERI, **kimlikler}.items() if k2.lower() == (ad or "").lower()), ad)

    def uygulama_yollari(self, cihaz, ad: str, video: str | None = None) -> list[tuple[str, bool, Any]]:
        """(etiket, içerik taşır mı, gönder()) listesi; yonetici sırayla dener ve TV'den doğrular."""
        kimlik = self._kimlik(cihaz, ad)
        yollar = []
        belirtec = self.sirlar(cihaz).get("istemci_anahtari", "")
        if belirtec:
            def ws_ac():
                self.tasima.yazma_denetle(f"Tizen uygulama {ad}")
                ws, _ = self._baglan(cihaz, belirtec)
                try:
                    ws.gonder(json.dumps({"method": "ms.channel.emit", "params": {
                        "event": "ed.apps.launch", "to": "host",
                        "data": {"appId": kimlik, "action_type": "DEEP_LINK", "metaTag": f"v={video}" if video else ""}}}))
                finally:
                    ws.kapat()
                return Sonuc(True, "Tizen WebSocket ed.apps.launch gönderildi")
            yollar.append(("Tizen derin bağlantı (WebSocket)", bool(video), ws_ac))

        def rest_ac():
            self.tasima.yazma_denetle(f"Tizen uygulama {ad}")
            kod, _, _ = self.tasima.istek("POST", f"http://{cihaz.adres}:8001/api/v2/applications/{kimlik}", b"")
            return Sonuc(kod == 200, f"Tizen REST HTTP {kod}")
        yollar.append(("Tizen REST", False, rest_ac))
        return yollar

    def uygulama_calisiyor(self, cihaz, ad: str) -> bool | None:
        try:
            js = self.tasima.get_json(f"http://{cihaz.adres}:8001/api/v2/applications/{self._kimlik(cihaz, ad)}")
        except Exception:
            return None
        return bool(js.get("running") and js.get("visible", True))

    def guc_durumu(self, cihaz) -> str:
        """'acik' | 'bekleme' (ağ beklemede, REST yanıt veriyor) | 'kapali' (yanıt yok)."""
        try:
            b = self._bilgi(cihaz)
        except Exception:
            return "kapali"
        g = (b.get("guc") or "").lower()
        return "acik" if g in ("on", "") else "bekleme"

    def durum(self, cihaz):
        b = self._bilgi(cihaz)
        d: dict[str, Any] = {"guc": b["guc"] == "on"}
        for ad in cihaz.yetenekler.get("uygulama", Yetenek("", SECIM)).secenekler:
            kimlik = UYGULAMA_KIMLIKLERI.get(ad, ad)
            try:
                js = self.tasima.get_json(f"http://{cihaz.adres}:8001/api/v2/applications/{kimlik}")
            except Exception:
                continue
            if js.get("running") and js.get("visible"):
                d["uygulama"] = ad
        return d

    def _baglan(self, cihaz, belirtec: str, zaman_asimi: float = 5.0):
        ws = self.ws_fabrikasi(self._ws_url(belirtec).format(cihaz.adres), zaman_asimi=zaman_asimi,
                               parmak_izi=cihaz.protokol.get("tls_parmak_izi", ""))
        for _ in range(10):
            m = json.loads(ws.al())
            if m.get("event") == "ms.channel.connect":
                return ws, (m.get("data") or {}).get("token", belirtec)
            if m.get("event") in ("ms.channel.unauthorized", "ms.channel.timeOut"):
                ws.kapat()
                raise TasimaHatasi("TV izin vermedi (" + m["event"] + ")")
        ws.kapat()
        raise TasimaHatasi("TV bağlantı onayı gelmedi")

    def eslestir(self, cihaz) -> Sonuc:
        self.tasima.yazma_denetle("Tizen eşleştirme istemi")
        ws, belirtec = self._baglan(cihaz, "", zaman_asimi=60.0)
        cihaz.protokol["tls_parmak_izi"] = getattr(ws, "parmak_izi", "")
        ws.kapat()
        cihaz.erisim = HAZIR
        return Sonuc(bool(belirtec), "Tizen eşleşti", {"istemci_anahtari": belirtec}, bool(belirtec))

    def _tus(self, cihaz, tus: str) -> None:
        belirtec = self.sirlar(cihaz).get("istemci_anahtari", "")
        if not belirtec:
            raise TasimaHatasi("Tizen belirteci yok; önce eşleştirme")
        ws, _ = self._baglan(cihaz, belirtec)
        try:
            ws.gonder(json.dumps({"method": "ms.remote.control", "params": {
                "Cmd": "Click", "DataOfCmd": tus, "Option": "false", "TypeOfRemote": "SendRemoteKey"}}))
        finally:
            ws.kapat()

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"Tizen {y.ad}={deger}")
        if y.ad == "guc":
            if deger:
                # ağ beklemedeki TV (REST yanıt veriyor) kumanda tuşuyla açılır; tamamen kapalıysa WoL (yonetici)
                if self.guc_durumu(cihaz) == "bekleme" and self.sirlar(cihaz).get("istemci_anahtari"):
                    self._tus(cihaz, "KEY_POWER")
                    return Sonuc(True, "Bekleme modundaki TV'ye açma tuşu gönderildi")
                return Sonuc(False, "Tizen açma Wake-on-LAN ister (MAC ile yonetici.wol_gonder)")
            self._tus(cihaz, "KEY_POWER")
            return Sonuc(True, "Kapatma tuşu gönderildi")
        if y.ad == "uygulama":
            kimlik = y.protokol.get("kimlikler", {}).get(deger, deger)
            kod, _, _ = self.tasima.istek("POST", f"http://{cihaz.adres}:8001/api/v2/applications/{kimlik}", b"")
            return Sonuc(kod == 200, f"{deger}: HTTP {kod}")
        tus = {"ses_adim": {"yukari": "KEY_VOLUP", "asagi": "KEY_VOLDOWN"},
               "kanal_adim": {"yukari": "KEY_CHUP", "asagi": "KEY_CHDOWN"}}.get(y.ad, {}).get(deger, deger)
        self._tus(cihaz, tus)
        return Sonuc(True, f"{tus} gönderildi")
