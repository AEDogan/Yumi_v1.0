"""Yumi'ye seslenince çalan müziği duraklat, cevap bitince devam ettir (Windows medya oturumu; aç/kapa medya tuşu DEĞİL).
Aç/kapa tuşu durum bilmez: yanlışlıkla müziği başlatabilir. winrt oturumu doğrudan 'duraklat' / 'oynat' der.
Yalnız Yumi'nin duraklattığı müzik devam ettirilir; kullanıcı arada 'durdur/kapat' ya da yeni müzik istediyse ettirilmez."""
from __future__ import annotations

import asyncio
import threading
import time

DEVAM_ETTIRME = {"medya_kontrol", "muzik_cal", "iptal_sus"}  # bu niyetlerden sonra kendiliğinden devam yok


async def _oturum():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Yonetici
    return (await Yonetici.request_async()).get_current_session()


async def _calıyor_mu():
    s = await _oturum()
    return bool(s) and int(s.get_playback_info().playback_status) == 4


async def _duraklat():
    s = await _oturum()
    if s and int(s.get_playback_info().playback_status) == 4:
        return bool(await s.try_pause_async())
    return False


async def _oynat():
    s = await _oturum()
    if s and int(s.get_playback_info().playback_status) != 4:
        return bool(await s.try_play_async())
    return False


def _calistir(coro, zaman_asimi=2.0):
    sonuc = {}
    def is_():
        try:
            sonuc["v"] = asyncio.run(coro())
        except Exception as e:
            sonuc["hata"] = e
    t = threading.Thread(target=is_, daemon=True); t.start(); t.join(zaman_asimi)
    return sonuc.get("v", False)


class MuzikDuraklatici:
    def __init__(self):
        self.duraklatildi_t = 0.0  # 0 = Yumi duraklatmadı

    @property
    def bekliyor(self):
        return self.duraklatildi_t > 0

    def seslenince(self, caliyor_ipucu=None):
        """Seslenme/mikrofon başlarken çağrılır. Müzik çalıyorsa duraklatır (en fazla ~2 s, arayüzü bekletmemek için kısa)."""
        if caliyor_ipucu is False:
            return False
        if _calistir(_duraklat):
            self.duraklatildi_t = time.monotonic()
            return True
        return False

    def tur_bitti(self, son_niyet=None):
        """Yumi dinlemeyi/cevabı bitirince çağrılır. Gerekirse müziği devam ettirir."""
        if not self.bekliyor:
            return False
        self.duraklatildi_t = 0.0
        if son_niyet in DEVAM_ETTIRME:
            return False
        return bool(_calistir(_oynat))
