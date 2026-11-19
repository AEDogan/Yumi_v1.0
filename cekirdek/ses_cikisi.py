"""SC1/SC2 (19 Kas 2026, kullanıcı): sesli cevap ayarı ve modelsiz API sesi kararları.

settings['sesli_cevap']: 'her_zaman' (varsayılan) · 'sesli_konusunca' (yazıyla sorulunca yalnız yazı) · 'sessiz' (hiç ses).
settings['modelsiz_ses']: 'yerel' (varsayılan Yumi sesi, XTTS) · 'api' (yalnız kurulu model YOKKEN; settings['api_ses']).
Sessizde ve API sesi etkinken XTTS işçisi kapatılır / hiç başlatılmaz (RAM/VRAM boşa harcanmaz).
Kartlar: work/docs/SES-CIKISI.md.
"""

MODLAR = (('Her zaman sesli', 'her_zaman'),
          ('Yalnız sesli konuşunca sesli', 'sesli_konusunca'),
          ('Sessiz · yalnız yazılı cevap', 'sessiz'))


def mod(app):
    m = app.settings.get('sesli_cevap', 'her_zaman')
    return m if m in {k for _, k in MODLAR} else 'her_zaman'


def model_sesi_yok(app):
    """Ses kuralı (kullanıcı, 19 Kas): modelsizken yalnız varsayılan Yumi sesi; model seçiliyken modelin kendi sesi;
    seçili modelin sesi yoksa (karakter.json "ses": {} — ör. Clippy) Yumi hep sessiz, varsayılan sese düşmez.
    Ayar değil, otomatik. Karakter kaydı bulunamazsa (eski/yerleşik görünüm) susturulmaz."""
    from modelsiz import model_yok
    if model_yok(app): return False
    try:
        import karakterler, skins
        anahtar = app.settings.get('skin') or ''
        kayit = karakterler.gorunum(anahtar)
        if kayit is None and anahtar == skins.SPRITE: kayit = karakterler.dizin().get('clippy')
        if kayit is None: return False
        return not (kayit.get('veri', {}).get('ses') or {})
    except Exception:
        return False


def sesli_mi(app, bildirim=False):
    """Bu turun cevabı seslendirilsin mi? Tur kaynağı _send'de 'yazi', mikrofon yolunda 'ses' olur.
    bildirim=True (alarm/sayaç bitti): 'yalnız sesli konuşunca' modunda da sesli (kullanıcı, 19 Kas); sessizde değil.
    Sesi olmayan model seçiliyken hiçbir zaman sesli değil (model_sesi_yok)."""
    if model_sesi_yok(app): return False
    m = mod(app)
    if m == 'sessiz': return False
    if bildirim: return True
    if m == 'sesli_konusunca': return getattr(app, '_tur_kaynak', 'yazi') == 'ses'
    return True


def api_ses(app):
    """Etkin API sesi ('api:elevenlabs:<kimlik>') ya da None. Kurulu model varsa API sesi KULLANILMAZ (kullanıcı kuralı)."""
    from modelsiz import model_yok
    if app.settings.get('modelsiz_ses') != 'api' or not model_yok(app): return None
    ses = str(app.settings.get('api_ses') or '')
    if not (ses.startswith('api:') and ses.count(':') >= 2 and ses.split(':', 2)[2]): return None
    import api_ses as _api
    return ses if _api.anahtar_oku() else None  # anahtar yoksa yerel Yumi sesi


def etkin_ses(app, secili):
    """Çalınacak ses: modelsiz + API seçiliyse XTTS sesinin yerine API sesi."""
    api = api_ses(app)
    return api if api and str(secili).startswith('xtts:') else secili


def xtts_gerekli(app):
    return mod(app) != 'sessiz' and api_ses(app) is None and not model_sesi_yok(app)


def xtts_kapat():
    """Çalışan XTTS işçi sürecini kapatır (yüklü değilse bir şey yapmaz). Kapattıysa True."""
    import sys
    xs = sys.modules.get('xtts_speech')
    if xs is None: return False
    w = getattr(xs, '_worker', None)
    if w is None or w.process is None or w.process.poll() is not None: return False
    w.stop(); return True
