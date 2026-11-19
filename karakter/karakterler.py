"""Karakter dizini: <model kökü>/<kategori>/<karakter>/karakter.json (DUZEN 12 Kasım; G-A2 18 Kasım).

Kod hiçbir karakteri adıyla tanımaz: ad, görünüm anahtarı, ses, okunuşlar, ses profili, paket (ör. "witcher") ve pakete
özel davranış bayrakları yalnız kurulu karakterlerin karakter.json'undan okunur. Model kökleri `app_paths.model_kokleri()`
(eklenen paketler `VERI\\models` + ana modül `UYGULAMA\\models`). Kategori = model kökündeki, `_` ile başlamayan ve içinde
karakter.json bulunan klasör (ana modül klasörleri — whisper, niyet… — karakter.json içermez, kategori sayılmaz).

karakter.json (şema: karakter/karakter_semasi.json):
  {"format": "yumi-karakter", "surum": 1, "ad": "...", "kategori": "<kat>", "paket": "<kat>", "yerlesik": false,
   "gorunumler": [{"anahtar": "vrm:<eski dosya adı>", "dosya": "<Ad>.vrm", "ad": "...", "varsayilan": true,
                   "profil": {...sabit ses profili...}, "davranis": {...}}],
   "ses": {"tur": "xtts_witcher" | "xtts_anime" | "meowko", "id": "...", "klasor": "ses", "ad": "...", "cins": "female",
           "varyant": "ince_ayar", "surumler": [...], "eq_tiz_db": 7},
   "okunuslar": ["..."], "davranis": {...}, "kisilik": "kisilik.json", "tur": "clippy"}
Ortak dosyalar <kök>/_ortak/ (ana modülde anime XTTS tabanı ve varsayılan kişilik; paketlerde Meowko, arka plan havuzu).
Yalnız veri okunur; kod çalıştırılmaz.
"""
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import app_paths
_dizin = None


def model_kokleri():
    return app_paths.model_kokleri()


def __getattr__(ad):
    # Eski çağıranlar için: MODELS = birincil (eklenen paketler) kökü, ORTAK = onun _ortak'ı.
    if ad == 'MODELS':
        return app_paths.modeller_dir()
    if ad == 'ORTAK':
        return app_paths.modeller_dir() / '_ortak'
    if ad == 'KATEGORILER':
        return tuple(dizin()['kategoriler'])
    raise AttributeError(ad)


def _oku(yol):
    try:
        veri = json.loads(yol.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    if not isinstance(veri, dict) or veri.get('format') != 'yumi-karakter':
        return None
    return veri


def _yol_anahtari(yol):
    try:
        return os.path.normcase(str(Path(yol).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(str(yol))


_yol_onbellek = {}


def yenile():
    global _dizin
    _dizin = None
    _yol_onbellek.clear()


def dizin():
    """{'gorunum': {anahtar: kayit}, 'anime_ses': {id: klasor}, 'witcher_ses': {id: klasor}, 'meowko_ses': klasor|None,
    'karakter': [kayit], 'kategoriler': [ad], 'yol': {VRM yolu: görünüm kaydı}, 'clippy': kayit|None}"""
    global _dizin
    if _dizin is not None:
        return _dizin
    gorunum, anime_ses, witcher_ses, karakterler, kategoriler, yollar = {}, {}, {}, [], [], {}
    meowko, clippy, gorulen = None, None, set()
    kapali = app_paths.kapali_karakter_klasorleri()  # F3: bağlantısı kesik paket → dosyalar yerinde, listede yok
    for kok in model_kokleri():
        if not kok.is_dir():
            continue
        for kat_klasor in sorted(p for p in kok.iterdir() if p.is_dir() and not p.name.startswith('_')):
            kategori = kat_klasor.name
            for klasor in sorted(kat_klasor.iterdir()):
                veri = _oku(klasor / 'karakter.json') if klasor.is_dir() else None
                if veri is None or (kapali and _yol_anahtari(klasor) in kapali):
                    continue
                anahtar_k = (kategori.casefold(), klasor.name.casefold())
                if anahtar_k in gorulen:
                    continue  # aynı karakter iki kökte: eklenen paket önce gelir
                gorulen.add(anahtar_k)
                if kategori not in kategoriler:
                    kategoriler.append(kategori)
                kayit = {'ad': str(veri.get('ad') or klasor.name), 'kategori': kategori, 'klasor': klasor,
                         'yerlesik': bool(veri.get('yerlesik')), 'veri': veri,
                         'paket': str(veri.get('paket') or kategori)}
                karakterler.append(kayit)
                if veri.get('tur') == 'clippy' and clippy is None:
                    clippy = kayit
                for g in veri.get('gorunumler') or []:
                    anahtar, dosya = g.get('anahtar'), g.get('dosya')
                    if not isinstance(anahtar, str) or not isinstance(dosya, str) or Path(dosya).name != dosya:
                        continue
                    g_kayit = {**kayit, 'yol': klasor / dosya, 'gorunum_adi': str(g.get('ad') or kayit['ad']), 'gorunum': g}
                    gorunum.setdefault(anahtar, g_kayit)
                    yollar.setdefault(_yol_anahtari(klasor / dosya), g_kayit)
                ses = veri.get('ses') or {}
                ses_klasor = klasor / str(ses.get('klasor') or 'ses')
                if ses.get('tur') == 'xtts_anime' and ses.get('id') and ses_klasor.is_dir():
                    anime_ses.setdefault(str(ses['id']), ses_klasor)
                elif ses.get('tur') == 'xtts_witcher' and ses.get('id'):
                    witcher_ses.setdefault(str(ses['id']), ses_klasor)
                elif ses.get('tur') == 'meowko' and meowko is None:
                    try:
                        yer = ses_klasor.resolve()
                        if yer.is_relative_to(kok.resolve()) and yer.is_dir():
                            meowko = yer
                    except (OSError, ValueError):
                        pass
        havuz = kok / '_ortak' / 'ses_havuzu'
        if havuz.is_dir():
            for klasor in sorted(havuz.iterdir()):
                if klasor.is_dir():
                    anime_ses.setdefault(klasor.name, klasor)
    _dizin = {'gorunum': gorunum, 'anime_ses': anime_ses, 'witcher_ses': witcher_ses, 'meowko_ses': meowko,
              'karakter': karakterler, 'kategoriler': sorted(kategoriler), 'yol': yollar, 'clippy': clippy}
    return _dizin


def gorunum(anahtar):
    return dizin()['gorunum'].get(anahtar)


def karakter_klasoru(ad):
    """Görünüm ya da karakter adıyla (büyük/küçük harf duyarsız) karakter klasörü."""
    hedef = (ad or '').strip().casefold()
    if not hedef:
        return None
    for kayit in dizin()['karakter']:
        adlar = {kayit['ad'].casefold(), kayit['klasor'].name.casefold()}
        adlar |= {str(g.get('ad') or '').casefold() for g in kayit['veri'].get('gorunumler') or []}
        if hedef in adlar:
            return kayit
    return None


def sprite_klasoru():
    """karakter.json "tur": "clippy" olan kurulu karakterin klasörü (yoksa None)."""
    k = dizin().get('clippy')
    return k['klasor'] if k else None


def yol_kaydi(yol):
    """VRM dosya yolundan görünüm kaydı (karakter.json'u bilinen kurulu bir görünümse)."""
    if not yol:
        return None
    d = dizin(); ham = str(yol)
    hit = _yol_onbellek.get(ham)
    if hit is not None and hit[0] is d:
        return hit[1]
    kayit = d['yol'].get(_yol_anahtari(yol))
    _yol_onbellek[ham] = (d, kayit)  # her karede çağrılır (witcher_package): yol çözümü bir kez
    return kayit


def _veri_nesnesi(nesne):
    """model / model.data / springs / yol → (paket alanı ya da None, VRM yolu ya da None)."""
    if nesne is None:
        return None, None
    if isinstance(nesne, (str, os.PathLike)):
        return None, nesne
    d = getattr(nesne, 'data', nesne)
    return getattr(d, 'package', None), getattr(d, 'path', None)


def paket(nesne):
    """Modelin paketi (karakter.json 'paket', yoksa kategori). Test verisi `data.package` taşıyorsa o geçerli."""
    pk, yol = _veri_nesnesi(nesne)
    if pk is not None:
        return pk
    kayit = yol_kaydi(yol)
    return kayit['paket'] if kayit else None


def witcher_mi(nesne):
    """Witcher paketine özel davranışların kapısı (karakter.json "paket": "witcher")."""
    return paket(nesne) == 'witcher'


def davranis(nesne, ad, varsayilan=None):
    """Pakete/karaktere özel davranış bayrağı: görünümün 'davranis'ı, yoksa karakterin 'davranis'ı, yoksa varsayılan."""
    _, yol = _veri_nesnesi(nesne)
    kayit = yol_kaydi(yol)
    if not kayit:
        return varsayilan
    for kaynak in (kayit.get('gorunum') or {}, kayit['veri']):
        d = kaynak.get('davranis')
        if isinstance(d, dict) and ad in d:
            return d[ad]
    return varsayilan


def okunuslar():
    """{normalize ad: (okunuşlar)} — kurulu karakterlerin karakter.json 'okunuslar' alanından (adla çağırma)."""
    from wake_names import normalized
    sonuc = {}
    for kayit in dizin()['karakter']:
        ok = tuple(str(x) for x in (kayit['veri'].get('okunuslar') or []) if isinstance(x, str))
        adlar = {kayit['ad']} | {str(g.get('ad') or '') for g in kayit['veri'].get('gorunumler') or []}
        for ad in adlar:
            ad = ad.strip()
            if not ad:
                continue
            anahtar = normalized(ad.replace('I', 'ı').replace('İ', 'i').lower())
            ilk = anahtar.split()[0]
            for k in (anahtar, ilk):
                if ok:
                    sonuc[k] = tuple(dict.fromkeys(sonuc.get(k, ()) + ok))
                else:
                    sonuc.setdefault(k, ())
    return sonuc


def sabit_profil(anahtar):
    """Görünümün değişmez ses profili (karakter.json gorunumler[].profil; Witcher sesleri sabit)."""
    kayit = gorunum(anahtar)
    p = (kayit or {}).get('gorunum', {}).get('profil') if kayit else None
    return dict(p) if isinstance(p, dict) else None


def tema_gorsel_klasorleri(anahtar):
    """Kitap teması görselleri: karakterin kendi arka_plan/ klasörü, sonra paketinin ortak havuzu (<kat>/_ortak/arka_plan)."""
    kayit = gorunum(anahtar)
    sonuc = []
    if kayit:
        sonuc.append(kayit['klasor'] / 'arka_plan')
    paketler = [kayit['kategori']] if kayit else []
    paketler += [k for k in dizin()['kategoriler'] if k not in paketler]
    for kat in paketler:
        for kok in model_kokleri():
            aday = kok / kat / '_ortak' / 'arka_plan'
            if aday.is_dir() and aday not in sonuc:
                sonuc.append(aday)
    return sonuc


def _paket_guven():
    """F3 (19 Kas): etkin paket makbuzlarından gelen güven: paketle kurulan <kat>/_ortak/guven.json, dosyası makbuzdaki
    sha256 ile hâlâ aynıysa (paket kurulurken sha denetimiyle açıldı). Kurulum kipinde de geçerli."""
    import hashlib
    sonuc = {}
    for k in app_paths.paket_kayitlari():
        if not k.get('etkin'):
            continue
        rel = f"{k['kategori']}/_ortak/guven.json"
        kayit = next((d for d in k.get('dosyalar') or [] if d.get('yol') == rel), None)
        if not kayit:
            continue
        yol = Path(k['kok']) / k['kategori'] / '_ortak' / 'guven.json'
        try:
            ham = yol.read_bytes()
            if hashlib.sha256(ham).hexdigest() != kayit.get('sha256'):
                continue
            veri = json.loads(ham.decode('utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(veri, dict):
            for ad, g in veri.items():
                if isinstance(g, dict) and not ad.startswith('_'):
                    sonuc.setdefault(ad, g)
    return sonuc


def guven_listesi():
    """Güven kaydı {eski dosya adı: {name, model_sha256, group}}: etkin paket makbuzlarından (F3, her kipte) +
    geliştirme kipinde tüm model köklerindeki <kategori>/_ortak/guven.json (kişisel kullanım)."""
    sonuc = _paket_guven()
    if not app_paths.gelistirme():
        return sonuc
    for kok in model_kokleri():
        if not kok.is_dir():
            continue
        for kat in sorted(p for p in kok.iterdir() if p.is_dir() and not p.name.startswith('_')):
            yol = kat / '_ortak' / 'guven.json'
            try:
                veri = json.loads(yol.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if isinstance(veri, dict):
                for ad, kayit in veri.items():
                    if isinstance(kayit, dict) and not ad.startswith('_'):
                        sonuc.setdefault(ad, kayit)
    return sonuc
