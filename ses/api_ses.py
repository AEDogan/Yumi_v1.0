"""SC2 (19 Kas 2026, kullanıcı): API ile ses — yalnız kurulu model YOKKEN varsayılan Yumi sesinin alternatifi.

Ses anahtarı biçimi: 'api:<sağlayıcı>:<ses kimliği>' (ör. 'api:elevenlabs:21m00Tcm4TlvDq8ikWAM').
Sağlayıcıdan bağımsız arayüz: SAGLAYICILAR[ad] = sesler(anahtar) / stream(metin, ses, anahtar, on_chunk).
Anahtar Windows DPAPI ile data/api_ses_anahtari.bin içinde; dosyaya/günlüğe açık yazılmaz.
Hata olursa (internet, kota, yanlış anahtar) Türkçe açıklamalı ApiSesHatasi; yerel sese otomatik düşülmez
(XTTS yüklü değil; dikkat noktası 1, work/docs/SES-CIKISI.md).
"""
import numpy as np

ONEK = 'api:'
SR = 24000
VARSAYILAN_SAGLAYICI = 'elevenlabs'
ZAMAN_ASIMI = (5, 20)  # bağlanma, okuma (s)


class ApiSesHatasi(RuntimeError):
    pass


def _anahtar_dosyasi():
    from app_paths import data_dir
    return data_dir() / 'api_ses_anahtari.bin'


def anahtar_oku():
    try:
        from platform_win import unprotect
        return unprotect(_anahtar_dosyasi().read_bytes()).decode('utf-8').strip()
    except Exception:
        return ''


def anahtar_kaydet(deger):
    from platform_win import protect
    yol = _anahtar_dosyasi(); yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix('.tmp'); gecici.write_bytes(protect(deger.strip().encode('utf-8'))); gecici.replace(yol)


def anahtar_sil():
    try: _anahtar_dosyasi().unlink()
    except FileNotFoundError: pass


def ayristir(ses):
    """'api:elevenlabs:<kimlik>' → ('elevenlabs', '<kimlik>')."""
    parca = str(ses).split(':', 2)
    if len(parca) < 3 or parca[0] != 'api' or not parca[2]: raise ApiSesHatasi('API sesi seçilmemiş (Ayarlar → Ses).')
    return parca[1], parca[2]


# ---------------- ElevenLabs ----------------
_EL = 'https://api.elevenlabs.io/v1'
EL_MODEL = 'eleven_flash_v2_5'  # Türkçe destekli, düşük gecikme


def _el_hata(yanit):
    try: ayrinti = yanit.json().get('detail')
    except Exception: ayrinti = None
    durum = (ayrinti or {}).get('status') if isinstance(ayrinti, dict) else None
    if durum == 'quota_exceeded': return ApiSesHatasi('ElevenLabs kotası bitti.')
    if yanit.status_code == 401: return ApiSesHatasi('ElevenLabs API anahtarı geçersiz.')
    if yanit.status_code == 429: return ApiSesHatasi('ElevenLabs çok fazla istek / eşzamanlılık sınırı.')
    if yanit.status_code == 404: return ApiSesHatasi('Seçili ElevenLabs sesi bulunamadı.')
    return ApiSesHatasi(f'ElevenLabs hata {yanit.status_code}.')


def _istek(yontem, url, anahtar, **kw):
    import requests
    if not anahtar: raise ApiSesHatasi('API anahtarı kayıtlı değil (Ayarlar → Ses).')
    try:
        return requests.request(yontem, url, headers={'xi-api-key': anahtar}, timeout=ZAMAN_ASIMI, **kw)
    except requests.exceptions.RequestException:
        raise ApiSesHatasi('Ses sitesine bağlanılamadı (internet?).') from None


def el_sesler(anahtar):
    """Hesaptaki sesler: [(ad, kimlik)]."""
    yanit = _istek('GET', _EL + '/voices', anahtar)
    if yanit.status_code != 200: raise _el_hata(yanit)
    sesler = [(s.get('name') or s.get('voice_id'), s.get('voice_id')) for s in yanit.json().get('voices', []) if s.get('voice_id')]
    return sorted(sesler, key=lambda x: x[0].casefold())


def el_stream(metin, ses_kimligi, anahtar, on_chunk, hiz=1.0):
    govde = {'text': metin, 'model_id': EL_MODEL, 'language_code': 'tr',
             'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': max(0.7, min(1.2, float(hiz)))}}
    yanit = _istek('POST', f'{_EL}/text-to-speech/{ses_kimligi}/stream', anahtar,
                   params={'output_format': 'pcm_24000'}, json=govde, stream=True)
    with yanit:
        if yanit.status_code != 200: raise _el_hata(yanit)
        artik = b''
        try:
            for parca in yanit.iter_content(chunk_size=4800):
                if not parca: continue
                veri = artik + parca; n = len(veri) // 2 * 2; artik = veri[n:]
                if n: on_chunk(np.frombuffer(veri[:n], dtype='<i2').astype(np.float32) / 32768.0, SR)
        except ApiSesHatasi:
            raise
        except Exception as hata:
            import requests
            if isinstance(hata, requests.exceptions.RequestException): raise ApiSesHatasi('Ses sitesiyle bağlantı koptu.') from None
            raise  # on_chunk hatası (ör. bölüm iptal) olduğu gibi


SAGLAYICILAR = {
    'elevenlabs': {'ad': 'ElevenLabs', 'sesler': el_sesler, 'stream': el_stream},
}


def sesler(saglayici=VARSAYILAN_SAGLAYICI, anahtar=None):
    return SAGLAYICILAR[saglayici]['sesler'](anahtar if anahtar is not None else anahtar_oku())


def stream(metin, ses, on_chunk, anahtar=None):
    """Akışlı üretim: on_chunk(float32, 24000). Konuşma hızı karakter profilinden (xtts_speech.HIZ)."""
    saglayici, kimlik = ayristir(ses)
    if saglayici not in SAGLAYICILAR: raise ApiSesHatasi(f'Bilinmeyen ses sağlayıcısı: {saglayici}')
    try:
        from xtts_speech import HIZ as hiz  # modül yalnız okunur; XTTS işçisini başlatmaz
    except Exception:
        hiz = 1.0
    SAGLAYICILAR[saglayici]['stream'](metin, kimlik, anahtar if anahtar is not None else anahtar_oku(), on_chunk, hiz)
