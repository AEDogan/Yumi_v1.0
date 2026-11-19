"""iRobot Roomba adaptörü — yerel MQTT (TLS 8883) yolu, roombapy ile (lib/ev/pydeps; kurulu değilse yok).

Keşif: iRobot UDP 5678 keşif yanıtı (robot adı, sku, MAC, yazılım, 'cap' yetenek sözlüğü). Yetenekler robotun
KENDİ bildirdiği 'cap' alanından ve bağlanınca raporladığı durumdan (batPct, cleanMissionStatus) çıkarılır.
Parola robottan bir kez alınır (robot yuvadayken HOME düğmesi basılı; roombapy-password) → DPAPI depo.
Parola yoksa 'anahtar_gerekli'; robot yerel bağlantıyı reddederse 'yalniz_bulut' (yeni yazılımlar).
Bu adaptör gerçek robotla DOĞRULANMADI.
"""
from __future__ import annotations

import json
from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet, pydeps_ekle
from .model import ANAHTAR_GEREKLI, DESTEKLENMIYOR, HAZIR, METIN, SECIM, TAMSAYI, YALNIZ_BULUT, Sonuc, Yetenek

KOMUT = {"baslat": "start", "durdur": "pause", "sarja_don": "dock"}


def blid_bul(ana_makine: str) -> str:
    return ana_makine.split("-", 1)[1] if "-" in (ana_makine or "") else ana_makine or ""


@kaydet
class RoombaAdaptoru(Adaptor):
    aile = "roomba"
    bulucu_aileleri = ("roomba",)

    def __init__(self, *a, robot_fabrikasi=None, **k):
        super().__init__(*a, **k)
        self.robot_fabrikasi = robot_fabrikasi  # test: (adres, blid, parola) -> nesne(connect/send_command/master_state)

    def uygun_mu(self, bulunan):
        return "roomba" in getattr(bulunan, "aileler", []) and bool(bulunan.adres)

    def cihaz_olustur(self, bulunan):
        blid = blid_bul(bulunan.alan("ana_makine"))
        c = bos_cihaz(bulunan, self.aile, f"roomba:{blid or bulunan.mac or bulunan.adres}")
        c.tur, c.marka = "vacuum", "iRobot"
        c.model = bulunan.alan("model") or c.model
        c.protokol = {"blid": blid, "cap": json.loads(bulunan.alan("irobot_cap") or "{}"), "sw": bulunan.alan("surum")}
        c.erisim, c.erisim_notu = ANAHTAR_GEREKLI, "robot parolası gerekli (yuvadayken HOME basılı tutulup alınır)"
        return c

    def _robot(self, cihaz):
        parola = self.sirlar(cihaz).get("parola", "")
        if not parola:
            return None
        if self.robot_fabrikasi:
            return self.robot_fabrikasi(cihaz.adres, cihaz.protokol.get("blid", ""), parola)
        pydeps_ekle()
        try:
            from roombapy import RoombaFactory
        except ImportError:
            raise RuntimeError("roombapy kurulu değil (lib/ev/pydeps)") from None
        return RoombaFactory.create_roomba(cihaz.adres, cihaz.protokol.get("blid", ""), parola, continuous=False)

    def _durum_oku(self, r) -> dict:
        r.connect()
        try:
            import time
            for _ in range(30):
                rap = ((getattr(r, "master_state", {}) or {}).get("state") or {}).get("reported") or {}
                if rap.get("batPct") is not None:
                    return rap
                time.sleep(0.2)
            return rap
        finally:
            r.disconnect()

    def yetenekler(self, cihaz):
        try:
            r = self._robot(cihaz)
        except RuntimeError as e:
            cihaz.erisim, cihaz.erisim_notu = DESTEKLENMIYOR, str(e)
            return {}
        if r is None:
            cihaz.erisim = ANAHTAR_GEREKLI
            return {}
        try:
            rap = self._durum_oku(r)
        except ConnectionRefusedError:
            cihaz.erisim, cihaz.erisim_notu = YALNIZ_BULUT, "robot yerel bağlantıyı reddetti; yalnız iRobot bulutu"
            return {}
        k = "iRobot yerel MQTT"
        yet = {"supurge": Yetenek("supurge", SECIM, False, True, secenekler=list(KOMUT), kaynak=k + " cmd",
                                  guven="tahmin"),
               "durum_metni": Yetenek("durum_metni", METIN, True, False, kaynak=k + " cleanMissionStatus.phase")}
        if rap.get("batPct") is not None:
            yet["olcum_pil"] = Yetenek("olcum_pil", TAMSAYI, True, False, 0, 100, 1, "%", kaynak=k + " batPct")
        cihaz.erisim, cihaz.erisim_notu = HAZIR, "parola ile bağlı"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        r = self._robot(cihaz)
        if r is None:
            return {}
        rap = self._durum_oku(r)
        return {"olcum_pil": rap.get("batPct"),
                "durum_metni": (rap.get("cleanMissionStatus") or {}).get("phase", "")}

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"Roomba {y.ad}={deger}")
        if y.ad != "supurge":
            return super()._uygula(cihaz, y, deger)
        r = self._robot(cihaz)
        if r is None:
            return Sonuc(False, "robot parolası gerekli")
        r.connect()
        try:
            r.send_command(KOMUT[deger])
        finally:
            r.disconnect()
        return Sonuc(True, {"baslat": "Temizlik başladı", "durdur": "Durdu", "sarja_don": "Şarja dönüyor"}[deger])
