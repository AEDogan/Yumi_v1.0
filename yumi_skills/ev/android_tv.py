"""Android TV / Google TV adaptörü — mevcut ``yumi_skills.android_tv_bridge.AndroidTVBridge``'i sarmalar
(androidtvremote2, .venv'de var; sertifikalar data/tokens/android-tv/, mevcut eşleşmeler geçerli kalır).

Yetenekler TV'den SORGULANIR: bağlanınca ``is_on``, ``volume_info`` (düzey/en çok/sessiz), ``current_app``,
``device_info``. Ses yalnız tuşla (VOLUME_UP/DOWN) değişir; sessiz durumu okunur, gerekirse MUTE tuşu.
Eşleştirme iki adım: ``eslestir(c)`` TV'de kod gösterir → ``eslestir(c, kod)`` bitirir (kullanıcı başındayken).
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .adaptor import Adaptor, bos_cihaz, kaydet
from .model import BOOL, ESLESTIRME_GEREKLI, HAZIR, SECIM, TAMSAYI, METIN, Sonuc, Yetenek

UYGULAMA_BAGLANTILARI = {  # androidtvremote2 send_launch_app_command derin bağlantıları (topluluk listesi)
    "YouTube": "https://www.youtube.com", "Netflix": "https://www.netflix.com/title",
    "Prime Video": "https://app.primevideo.com", "Disney+": "https://www.disneyplus.com",
    "Spotify": "spotify://", "Twitch": "twitch://home",
}


def _tokens_klasoru() -> Path:
    try:
        from app_paths import data_dir
        return data_dir() / "tokens"
    except Exception:
        return Path.cwd() / "data" / "tokens"


@kaydet
class AndroidTvAdaptoru(Adaptor):
    aile = "androidtv"
    bulucu_aileleri = ("androidtv",)

    def __init__(self, *a, kopru=None, tokens_klasoru: Path | None = None, **k):
        super().__init__(*a, **k)
        self._kopru = kopru
        self._tokens = tokens_klasoru

    def kopru(self):
        if self._kopru is None:
            from ..android_tv_bridge import AndroidTVBridge
            self._kopru = AndroidTVBridge(SimpleNamespace(tokens_dir=self._tokens or _tokens_klasoru()))
        return self._kopru

    def _sertifika_var(self, adres: str) -> bool:
        anahtar = hashlib.sha256(adres.encode()).hexdigest()[:20]
        return ((self._tokens or _tokens_klasoru()) / "android-tv" / (anahtar + ".crt")).exists()

    def cihaz_olustur(self, bulunan):
        c = bos_cihaz(bulunan, self.aile, f"androidtv:{bulunan.mac or bulunan.adres}")
        c.tur = "tv"
        if self._sertifika_var(bulunan.adres):
            c.erisim, c.erisim_notu = HAZIR, "eşleşme sertifikası var"
        else:
            c.erisim, c.erisim_notu = ESLESTIRME_GEREKLI, "TV ekranındaki 6 haneli kodu Yumi'ye gir"
        return c

    async def _oku(self, adres: str) -> dict[str, Any]:
        k = self.kopru()
        remote = k.client(adres)
        try:
            await asyncio.wait_for(remote.async_connect(), 8)
            return {"is_on": remote.is_on, "volume": dict(remote.volume_info or {}),
                    "app": remote.current_app or "", "info": dict(remote.device_info or {})}
        finally:
            remote.disconnect()

    def yetenekler(self, cihaz):
        if not self._sertifika_var(cihaz.adres):
            cihaz.erisim = ESLESTIRME_GEREKLI
            return {}
        try:
            bilgi = self.kopru().call(self._oku(cihaz.adres))
        except Exception as e:
            if "auth" in type(e).__name__.lower():
                cihaz.erisim, cihaz.erisim_notu = ESLESTIRME_GEREKLI, "eşleşme geçersiz; yeniden eşleştir"
                return {}
            raise
        k = "androidtvremote2"
        yet: dict[str, Yetenek] = {"guc": Yetenek("guc", BOOL, bilgi["is_on"] is not None, True, kaynak=k + " is_on")}
        ses = bilgi["volume"]
        if ses:
            yet["ses_duzeyi"] = Yetenek("ses_duzeyi", TAMSAYI, True, False, 0, ses.get("max", 100), 1,
                                        kaynak=k + " volume_info (yalnız okuma)")
            yet["sessiz"] = Yetenek("sessiz", BOOL, True, True, kaynak=k + " volume_info.muted + MUTE tuşu")
        yet["ses_adim"] = Yetenek("ses_adim", SECIM, False, True, secenekler=["yukari", "asagi"], kaynak=k + " tuş")
        yet["uygulama"] = Yetenek("uygulama", SECIM, True, True, secenekler=list(UYGULAMA_BAGLANTILARI),
                                  kaynak=k + " send_launch_app_command (liste sorgulanamıyor; koddaki bilinen bağlantılar)", guven="tahmin",
                                  protokol={"liste_kaynagi": "tablo"})
        yet["tus"] = Yetenek("tus", SECIM, False, True, secenekler=["HOME", "BACK", "DPAD_CENTER", "MEDIA_PLAY_PAUSE"],
                             kaynak=k)
        info = bilgi["info"]
        cihaz.marka = cihaz.marka or info.get("manufacturer", "")
        cihaz.model = cihaz.model or info.get("model", "")
        cihaz.erisim, cihaz.erisim_notu = HAZIR, "eşleşmiş"
        for y in yet.values():
            cihaz.yetenek_ekle(y)
        return yet

    def durum(self, cihaz):
        if not self._sertifika_var(cihaz.adres):
            return {}
        b = self.kopru().call(self._oku(cihaz.adres))
        d: dict[str, Any] = {"guc": b["is_on"], "uygulama": b["app"]}
        if b["volume"]:
            d["ses_duzeyi"], d["sessiz"] = b["volume"].get("level"), b["volume"].get("muted")
        return d

    def eslestir(self, cihaz, kod: str | None = None) -> Sonuc:
        self.tasima.yazma_denetle("Android TV eşleştirme")
        k = self.kopru()
        r = k.finish(cihaz.adres, kod) if kod else k.begin(cihaz.adres)
        if kod and r.get("ok"):
            cihaz.erisim = HAZIR
        return Sonuc(bool(r.get("ok")), r.get("speech", ""), None, bool(kod and r.get("ok")))

    async def _gonder(self, adres: str, tus: str | None = None, uygulama: str | None = None):
        remote = self.kopru().client(adres)
        try:
            await asyncio.wait_for(remote.async_connect(), 8)
            if tus:
                remote.send_key_command(tus)
            if uygulama:
                remote.send_launch_app_command(uygulama)
            await asyncio.sleep(0.3)
            return {"muted": (remote.volume_info or {}).get("muted"), "is_on": remote.is_on}
        finally:
            remote.disconnect()

    def uygulama_yollari(self, cihaz, ad: str, video: str | None = None):
        if not self._sertifika_var(cihaz.adres):
            return []
        icerikli = bool(video and "youtube" in ad.lower())
        hedef = f"https://www.youtube.com/watch?v={video}" if icerikli else UYGULAMA_BAGLANTILARI.get(ad, ad)

        def ac():
            self.tasima.yazma_denetle(f"Android TV uygulama {ad}")
            self.kopru().call(self._gonder(cihaz.adres, uygulama=hedef))
            return Sonuc(True, "Android TV derin bağlantı gönderildi")
        return [("Android TV derin bağlantı", icerikli, ac)]

    def uygulama_calisiyor(self, cihaz, ad: str):
        try:
            uyg = str(self.durum(cihaz).get("uygulama") or "").lower()
        except Exception:
            return None
        anahtar = (ad or "").lower().split()[0] if ad else ""
        return bool(anahtar and anahtar.replace("+", "") in uyg)

    def _uygula(self, cihaz, y, deger):
        self.tasima.yazma_denetle(f"Android TV {y.ad}={deger}")
        k = self.kopru()
        if y.ad == "guc":
            r = k.call(self._gonder(cihaz.adres, tus="WAKEUP" if deger else "SLEEP"))
            return Sonuc(True, "Açıldı" if deger else "Kapatıldı", r.get("is_on"), r.get("is_on") == bool(deger))
        if y.ad == "ses_adim":
            k.call(self._gonder(cihaz.adres, tus="VOLUME_UP" if deger == "yukari" else "VOLUME_DOWN"))
            return Sonuc(True, "Ses tuşu gönderildi")
        if y.ad == "sessiz":
            simdi = self.durum(cihaz).get("sessiz")
            if simdi == deger:
                return Sonuc(True, "Zaten öyle", simdi, True)
            r = k.call(self._gonder(cihaz.adres, tus="VOLUME_MUTE"))
            return Sonuc(r.get("muted") == deger, "Sessiz" if r.get("muted") else "Ses açık", r.get("muted"),
                         r.get("muted") == deger)
        if y.ad == "uygulama":
            k.call(self._gonder(cihaz.adres, uygulama=UYGULAMA_BAGLANTILARI.get(deger, deger)))
            return Sonuc(True, f"{deger} açılıyor")
        if y.ad == "tus":
            k.call(self._gonder(cihaz.adres, tus=deger))
            return Sonuc(True, f"{deger} gönderildi")
        return super()._uygula(cihaz, y, deger)
