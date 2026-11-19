"""Modelsiz dağıtım tanımı — tek yer (C05 16 Kas; G-A2 18 Kas).

Kararlar: setup'ta hiç karakter modeli yok; Whisper, niyet, yamnet, music, XTTS tabanı, varsayılan kişilik ve
varsayılan Yumi sesi programla gelir (UYGULAMA\\models). Karakter paketleri (kategori klasörleri) kullanıcının veri
alanına eklenir (VERI\\models\\<kategori>). Bu dosya yalnız veri ve okuma yardımcıları içerir.
Okuyanlar: voice_profiles.varsayilan_ses, xtts_speech (varsayılan ses isteği), arayuz/modelsiz.py, cekirdek/app.py DEFAULTS.
"""
from pathlib import Path

KARAKTER = 'karakter'   # dağıtıma girmez (paket)
SISTEM = 'sistem'       # programla gelir

# UYGULAMA\models üst klasörleri (yalnız ana modül). Burada olmayan her klasör karakter paketi sayılır.
MODELS_SINIF = {
    '_ortak': SISTEM,                  # xtts_anime (XTTS tabanı: temel.pth/config/vocab), kisilik/varsayilan.json
    'varsayilan_ses': SISTEM,          # varsayılan Yumi sesi (ince_ayar.pth + ref.wav + ses.json)
    'whisper-large-v3-turbo': SISTEM,  # ses tanıma (ekran kartı)
    'whisper-small': SISTEM,           # ses tanıma (işlemci yedeği)
    'niyet': SISTEM,                   # yerel yönlendirme (niyet modeli)
    'yamnet': SISTEM,                  # ses sınıflandırma
    'music': SISTEM,                   # müzik türü analizi
}
ORTAK_SINIF = {'xtts_anime': SISTEM, 'kisilik': SISTEM}

# Varsayılan Yumi sesi (K1, 18 Kas 00:50): anime paketindeki Yumi sesinin kopyası, ana modülde.
# Parametreler anime XTTS ses türüyle aynı (xtts_speech.ANIME_PARAMS); taban UYGULAMA\models\_ortak\xtts_anime.
SISTEM_SESI = 'xtts:varsayilan'
SISTEM_SESI_ADI = 'Yumi sesi (varsayılan)'
SISTEM_SESI_KLASORU = Path('varsayilan_ses')   # UYGULAMA\models altına göre


def karakter_kategorileri():
    """Kurulu karakter kategorileri (karakter.json'lardan; sabit liste yok)."""
    import karakterler
    return tuple(karakterler.dizin()['kategoriler'])


def __getattr__(ad):
    if ad in ('KARAKTER_KATEGORILERI',):
        return karakter_kategorileri()
    raise AttributeError(ad)


def siniflandir(models_klasoru):
    """{üst klasör adı: sınıf} — gerçek models/ klasörü için (ana modülde olmayan → KARAKTER)."""
    kok = Path(models_klasoru)
    if not kok.is_dir():
        return {}
    return {p.name: MODELS_SINIF.get(p.name, KARAKTER) for p in sorted(kok.iterdir()) if p.is_dir()}
