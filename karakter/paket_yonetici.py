"""F3 (19 Kas 2026): Yumi'de .yumipaket ekleme / bağlantı kesme / yeniden bağlama.

Kullanıcı kararları (AYIRMA-PLANI G-F3, 18 Kas akşam):
- Paketler kişisel veri alanına açılır: varsayılan `app_paths.modeller_dir()` (geliştirmede `Yumi\\models`, kurulumda
  `%LOCALAPPDATA%\\Yumi\\models`); Ayarlar → Model → "Paket klasörü" ile başka bir yere (ör. `D:\\Yumi-Modeller`).
  Kayıtlar (makbuz) her zaman `data_dir()/paketler/<paket>.json`.
- Kaldır = SİLME/TAŞIMA YOK: kayıt `etkin: false` olur, karakterler listeden çıkar, dosyalar yerinde kalır.
  "Yeniden bağla" dosyaların sha256'sını denetleyip kaydı yeniden etkinleştirir (.yumipaket'i yeniden seçmeden).
- Kurulum: önizleme (sha okumadan) → çakışma → arka planda düşük G/Ç önceliğiyle sha denetimli açma (geçici klasöre,
  aynı birimde) → klasör klasör taşıma (hata olursa taşınanlar geri alınır) → makbuz → `karakterler.yenile()`.
- Güncellemede / üzerine yazmada eski klasörler silinmez: `<kök>/_eski/<zaman>/...` altına taşınır.
Kod çalıştırılmaz; yalnız veri okunur/yazılır. Kartlar: AYIRMA-PLANI G-F3, Yumi-Modeller docs/PAKET-EKLEME-AKISI.md.
"""
import hashlib, json, os, shutil, threading, time, uuid
from pathlib import Path

import sys as _sys
_CEKIRDEK = str(Path(__file__).resolve().parents[1] / 'cekirdek')
if _CEKIRDEK not in _sys.path:  # işçi süreç olarak çalışırken app_paths bulunsun
    _sys.path.append(_CEKIRDEK)
import app_paths
import paket_dogrula as pd
from paket_dogrula import PaketHatasi

GECICI = '_gecici'
ESKI = '_eski'
# 19 Kas (kullanıcı): paket kurulumu/denetimi diskin tamamını işgal etmesin (yoksa her şey donar). İşçi süreç
# Windows arka plan kipinde (düşük G/Ç + bellek önceliği) ve bu hızla sınırlı çalışır. Ölçüm: work/f3/disk/.
HIZ_SINIRI_MB = 20


def _arka_plan_kipi():
    """İşçi sürecini Windows PROCESS_MODE_BACKGROUND_BEGIN kipine alır (G/Ç önceliği 'çok düşük'). Başarılıysa True."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        return bool(k32.SetPriorityClass(ctypes.c_void_p(k32.GetCurrentProcess()), 0x00100000))
    except Exception:
        return False


# ---------------- kayıtlar ----------------
def kayit_klasoru():
    return app_paths.data_dir() / 'paketler'


def kayitlar():
    """Tüm paket makbuzları (etkin ve bağlantısı kesik), ada göre sıralı."""
    return app_paths.paket_kayitlari()


def kayit(ad):
    return next((k for k in kayitlar() if k.get('ad') == ad), None)


def _yaz(k):
    klasor = kayit_klasoru(); klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"{k['ad']}.json"; gecici = yol.with_suffix('.json.tmp')
    gecici.write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding='utf-8'); os.replace(gecici, yol)
    degisti()


def degisti():
    """Kayıt ya da kurulu dosyalar değişti: yol/karakter/güven önbelleklerini sıfırla."""
    app_paths.paket_onbellek_sifirla()
    if _COCUK:
        return
    import karakterler; karakterler.yenile()
    try:
        import model_packages; model_packages._approved.cache_clear()
    except Exception:
        pass
    try:
        from voice_profiles import refresh_voices; refresh_voices()
    except Exception:
        pass


def kok_sec(settings=None):
    """Yeni paketlerin açılacağı kök: ayardaki "Paket klasörü", yoksa varsayılan modeller klasörü."""
    deger = str((settings or {}).get('paket_klasoru') or '').strip()
    return Path(deger) if deger else app_paths.modeller_dir()


def karakter_klasorleri(k):
    kok = Path(k['kok'])
    return [kok / k['kategori'] / c['klasor'] for c in k.get('karakterler', [])]


def paketi_bul(klasor):
    """Karakter klasörü hangi pakete ait? (kayıt ya da None)"""
    hedef = _anahtar(klasor)
    for k in kayitlar():
        if any(_anahtar(p) == hedef for p in karakter_klasorleri(k)):
            return k
    return None


def _anahtar(yol):
    try:
        return os.path.normcase(str(Path(yol).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(str(yol))


def surum_anahtari(s):
    parca = []
    for p in str(s).replace('-', '.').replace('+', '.').split('.'):
        parca.append((0, int(p), '') if p.isdigit() else (1, 0, p))
    return tuple(parca)


def boyut_yazi(b):
    b = float(b or 0)
    for birim, carpan in (('GB', 1e9), ('MB', 1e6), ('KB', 1e3)):
        if b >= carpan:
            return f'{b / carpan:.1f} {birim}'.replace('.', ',')
    return f'{int(b)} B'


def _bos_alan(kok):
    p = Path(kok)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


# ---------------- önizleme ----------------
def onizleme(yol, kok):
    """Hızlı (sha okumadan) önizleme + çakışma analizi. PaketHatasi: paket geçersiz."""
    b = pd.paket_bilgisi(yol)
    ad, surum, kat = b['paket']['ad'], b['paket']['surum'], b['kategori']
    kok = Path(kok)
    motor = b.get('ses_motoru') or {}
    if motor.get('taban_gerekli'):
        t = motor.get('taban_model') or {}
        taban = app_paths.UYGULAMA_MODELLER / Path(str(t.get('yol', ''))).relative_to('models') if str(t.get('yol', '')).startswith('models/') else None
        if taban is None or not taban.is_file() or (t.get('boyut') and taban.stat().st_size != t['boyut']):
            raise PaketHatasi('Bu paketin sesleri için gereken ses motoru tabanı (XTTS) bu Yumi kurulumunda yok ya da farklı. '
                              'Önce Yumi\'yi güncelle.')
    mevcut = kayit(ad)
    if mevcut is None:
        durum = 'yeni'
    else:
        fark = (surum_anahtari(surum) > surum_anahtari(mevcut['surum'])) - (surum_anahtari(surum) < surum_anahtari(mevcut['surum']))
        if fark == 0:
            durum = 'ayni_kurulu' if mevcut.get('etkin') else 'ayni_bagli_degil'
        else:
            durum = 'guncelleme' if fark > 0 else 'eski_surum'
    kendi = {_anahtar(p) for p in karakter_klasorleri(mevcut)} if mevcut else set()
    cakisan = []
    for c in b['karakterler']:
        hedef = kok / kat / c['klasor']
        for diger in kayitlar():
            if diger['ad'] != ad and diger['kategori'] == kat and any(x['klasor'].casefold() == c['klasor'].casefold() for x in diger.get('karakterler', [])):
                cakisan.append({'klasor': c['klasor'], 'ad': c['ad'], 'kaynak': diger.get('baslik') or diger['ad']}); break
        else:
            if hedef.exists() and _anahtar(hedef) not in kendi:
                cakisan.append({'klasor': c['klasor'], 'ad': c['ad'], 'kaynak': 'paket kaydı olmayan klasör'})
    # 19 Kas (kullanıcı): aynı karakter Yumi'nin taradığı BAŞKA bir klasörde (kayıtsız eski .yumimodel, elle kopya,
    # başka paket klasörü) zaten varsa ikinci kez diske açılmaz; kurulumda otomatik atlanır.
    baska_yerde = []
    try:
        import karakterler
        hedef_kok = _anahtar(kok)
        for c in b['karakterler']:
            if any(x['klasor'].casefold() == c['klasor'].casefold() for x in cakisan):
                continue
            for kk in karakterler.dizin()['karakter']:
                yer = Path(kk['klasor'])
                if str(kk.get('kategori', '')).casefold() != kat.casefold() or yer.name.casefold() != c['klasor'].casefold():
                    continue
                if _anahtar(yer) in kendi or _anahtar(yer.parent.parent) == hedef_kok:
                    continue
                baska_yerde.append({'klasor': c['klasor'], 'ad': c['ad'], 'yer': str(yer)}); break
    except Exception:
        baska_yerde = []
    boyut = int(b.get('toplam_boyut') or sum(d['boyut'] for d in b['dosyalar']))
    bos = _bos_alan(kok)
    return {'yol': str(yol), 'bilgi': b, 'ad': ad, 'baslik': b['paket'].get('baslik') or ad, 'surum': surum, 'kategori': kat,
            'kisisel': bool(b.get('kisisel')), 'karakterler': [c['ad'] for c in b['karakterler']], 'boyut': boyut, 'bos': bos,
            'yeterli': bos > boyut + 512 * 1024 * 1024, 'durum': durum, 'mevcut': mevcut, 'cakisan': cakisan, 'baska_yerde': baska_yerde, 'kok': str(kok),
            'uyarilar': list(b.get('_uyarilar') or [])}


def onizleme_metni(o):
    satir = [f"<b>{o['baslik']}</b> · sürüm {o['surum']}" + (" · <b>kişisel paket</b>" if o['kisisel'] else ''),
             f"Kategori: {o['kategori']}",
             f"Karakterler ({len(o['karakterler'])}): {', '.join(o['karakterler'])}",
             f"Kaplayacağı alan: {boyut_yazi(o['boyut'])} · boş alan: {boyut_yazi(o['bos'])}",
             f"Yer: {o['kok']}"]
    if o['durum'] == 'guncelleme':
        satir.append(f"Kurulu sürüm {o['mevcut']['surum']} → {o['surum']} güncellenir; eski dosyalar silinmez, "
                     f"<i>{ESKI}</i> klasörüne taşınır.")
    elif o['durum'] == 'eski_surum':
        satir.append(f"<b>Dikkat:</b> bu, kurulu sürümden ({o['mevcut']['surum']}) daha eski bir sürüm.")
    if o.get('baska_yerde'):
        satir.append("Yumi'de zaten var, tekrar eklenmeyecek: " + ', '.join(c['ad'] for c in o['baska_yerde']) + '.')
    if o['kisisel']:
        satir.append('Kişisel paket: yalnız kendi kullanımın içindir, başkasıyla paylaşma.')
    return '<br>'.join(satir)


# ---------------- arka plan işleri ----------------
# 19 Kas (canlı test): iş önce aynı süreçte "arka plan" öncelikli iş parçacığındaydı → GIL'i tutan düşük öncelikli
# iş parçacığı yüzünden arayüz 23 s'ye kadar dondu, anime paketi 321 s sürdü. Artık açma/denetim AYRI SÜREÇTE
# (bu dosya `python paket_yonetici.py <girdi.json> <durum.json>`), işlemci önceliği "normalin altı"; Yumi yalnız durum
# dosyasını okur. Yumi kapanırsa işçi işini bitirip makbuzu yazar.
_COCUK = False  # işçi süreçte True: önbellek yenileme yalnız app_paths düzeyinde


class _Mantik:
    """Aynı süreçte çalışan iş mantığı: ilerleme (0..1), asama, hata, sonuc."""
    tur = 'is'

    def __init__(self):
        self.ilerleme = 0.0; self.asama = 'Başlıyor…'; self.hata = None; self.sonuc = None

    def yurut(self):
        try:
            self.sonuc = self.calis()
        except PaketHatasi as e:
            self.hata = str(e)
        except OSError as e:
            self.hata = f'Dosya işlemi başarısız: {e.strerror or e} ({getattr(e, "filename", "") or ""})'
        except Exception as e:  # beklenmedik: kullanıcıya kısa, günlüğe (işçi stderr → logs/paket-isci.log) tam
            import traceback; traceback.print_exc()
            self.hata = f'Beklenmedik hata: {e}'
        if self.hata is None:
            self.ilerleme = 1.0


class SurecIsi(threading.Thread):
    """Arayüzün izlediği iş: ayrı süreçte _Mantik çalıştırır. Alanlar: ilerleme, asama, bitti, hata, sonuc, islendi."""

    def __init__(self, tur, girdi):
        super().__init__(daemon=True, name='yumi-paket-izle')
        self.tur = tur; self.girdi = {'tur': tur, **girdi}
        self.ilerleme = 0.0; self.asama = 'Başlıyor…'; self.bitti = False; self.hata = None; self.sonuc = None
        self.islendi = False; self.basla_t = time.monotonic()

    def run(self):
        import subprocess, sys
        klasor = app_paths.data_dir() / 'paket_isleri'; klasor.mkdir(parents=True, exist_ok=True)
        kimlik = uuid.uuid4().hex[:10]; girdi, durum = klasor / f'{kimlik}-girdi.json', klasor / f'{kimlik}-durum.json'
        try:
            girdi.write_text(json.dumps(self.girdi, ensure_ascii=False), encoding='utf-8')
            (app_paths.data_dir() / 'logs').mkdir(parents=True, exist_ok=True)
            bayrak = (0x08000000 | 0x00004000) if os.name == 'nt' else 0  # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
            with open(app_paths.data_dir() / 'logs' / 'paket-isci.log', 'a', encoding='utf-8') as gunluk:
                surec = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), str(girdi), str(durum)],
                                         stdin=subprocess.DEVNULL, stdout=gunluk, stderr=gunluk, creationflags=bayrak,
                                         cwd=str(app_paths.UYGULAMA))
                son = {}
                while True:
                    bitti = surec.poll() is not None
                    try:
                        son = json.loads(durum.read_text(encoding='utf-8'))
                        self.ilerleme = float(son.get('ilerleme', self.ilerleme)); self.asama = son.get('asama', self.asama)
                    except (OSError, ValueError):
                        pass
                    if bitti:
                        break
                    time.sleep(0.25)
            if not son.get('bitti'):
                self.hata = f'Paket işçisi beklenmedik biçimde kapandı (çıkış {surec.returncode}; data/logs/paket-isci.log).'
            else:
                self.hata, self.sonuc = son.get('hata'), son.get('sonuc')
        except OSError as e:
            self.hata = f'Paket işçisi başlatılamadı: {e}'
        finally:
            for f in (girdi, durum):
                try: f.unlink()
                except OSError: pass
            app_paths.paket_onbellek_sifirla()
            if self.hata is None: self.ilerleme = 1.0
            self.bitti = True


def Kurulum(o, atla=(), uzerine_yaz=False):
    return SurecIsi('kurulum', {'o': o, 'atla': list(atla), 'uzerine_yaz': bool(uzerine_yaz)})


def YenidenBagla(ad):
    return SurecIsi('bagla', {'ad': ad})


class _KurulumMantigi(_Mantik):
    tur = 'kurulum'

    def __init__(self, o, atla=(), uzerine_yaz=False):
        super().__init__()
        self.o = o; self.atla = {a.casefold() for a in atla}; self.uzerine_yaz = uzerine_yaz

    def calis(self):
        o = self.o; b = o['bilgi']; kat = o['kategori']; kok = Path(o['kok'])
        cakisan = {c['klasor'].casefold() for c in o['cakisan']}
        secilen = [c for c in b['karakterler'] if c['klasor'].casefold() not in self.atla and (self.uzerine_yaz or c['klasor'].casefold() not in cakisan)]
        if not secilen:
            raise PaketHatasi('Kurulacak karakter kalmadı (hepsi atlandı).')
        kok.mkdir(parents=True, exist_ok=True)
        gecici_kok = kok / GECICI
        if gecici_kok.is_dir():  # önceki yarım kurulumdan kalanlar (yalnız bizim geçici klasörümüz)
            for eski in gecici_kok.iterdir():
                if time.time() - eski.stat().st_mtime > 3600:
                    shutil.rmtree(eski, ignore_errors=True)
        gecici = gecici_kok / f"{o['ad']}-{uuid.uuid4().hex[:8]}"
        tumu = len(secilen) == len(b['karakterler'])
        onekler = None if tumu else ([f"karakterler/{c['klasor']}" for c in secilen]
                                     + (['kategori_ortak'] if any(d['yol'].startswith('kategori_ortak/') for d in b['dosyalar']) else [])
                                     + [f'ortak/{x}' for x in b.get('ortak') or []])
        toplam = sum(d['boyut'] for d in b['dosyalar'] if onekler is None or any(d['yol'].startswith(p + '/') for p in onekler)) or 1
        self.asama = 'Doğrulanıyor ve açılıyor…'

        def ilerle(okunan, _t, _ad):
            self.ilerleme = 0.95 * okunan / toplam
        acilan = pd.ac(o['yol'], gecici, ilerleme=ilerle, sadece=onekler)
        try:
            self.asama = 'Yerine taşınıyor…'
            tasinan, eskiye = self._yerlestir(gecici, kok, kat, secilen, b)
        except BaseException:
            shutil.rmtree(gecici, ignore_errors=True)
            raise
        shutil.rmtree(gecici, ignore_errors=True)
        try:
            gecici_kok.rmdir()
        except OSError:
            pass
        # makbuz
        dosyalar = []
        for d in b['dosyalar']:
            if onekler is None or any(d['yol'].startswith(p + '/') for p in onekler):
                dosyalar.append({'yol': str(pd.kurulum_yolu(d['yol'], kat)), 'boyut': d['boyut'], 'sha256': d['sha256']})
        k = {'bicim': 'yumi-paket-kaydi', 'surum_kaydi': 1, 'ad': o['ad'], 'baslik': o['baslik'], 'surum': o['surum'],
             'kategori': kat, 'kisisel': o['kisisel'], 'kok': str(kok), 'etkin': True,
             'kurulum': time.strftime('%Y-%m-%dT%H:%M:%S'), 'kaynak_dosya': Path(o['yol']).name,
             'karakterler': [{'klasor': c['klasor'], 'ad': c['ad'], 'gorunumler': c.get('gorunumler', [])} for c in secilen],
             'ortak': list(b.get('ortak') or []), 'dosyalar': dosyalar, 'eski_tasinan': eskiye,
             'boyut': sum(d['boyut'] for d in dosyalar)}
        # Önceki sürümün (ya da üzerine yazılan başka paketin) yeni yerle aynı olmayan karakter klasörleri silinmez,
        # kendi kökünün _eski klasörüne taşınır; böylece kayıtsız kopya listede görünmez.
        yeni_yerler = {_anahtar(kok / kat / c['klasor']) for c in secilen}
        alinan = {c['klasor'].casefold() for c in secilen}
        zaman = time.strftime('%Y%m%d-%H%M%S')
        for onceki in kayitlar():
            ayni = onceki['ad'] == o['ad']
            if not ayni and not (self.uzerine_yaz and onceki['kategori'] == kat):
                continue
            for c, yer in zip(onceki.get('karakterler', []), karakter_klasorleri(onceki)):
                if not ayni and c['klasor'].casefold() not in alinan:
                    continue
                if _anahtar(yer) in yeni_yerler or not yer.exists():
                    continue
                okok = Path(onceki['kok']); arsiv = okok / ESKI / zaman / yer.relative_to(okok)
                arsiv.parent.mkdir(parents=True, exist_ok=True); os.replace(yer, arsiv); eskiye.append(str(arsiv))
        # üzerine yazılan karakterler başka paketin kaydından düşülür
        if self.uzerine_yaz:
            for diger in kayitlar():
                if diger['ad'] == o['ad'] or diger['kategori'] != kat:
                    continue
                kalan = [c for c in diger.get('karakterler', []) if c['klasor'].casefold() not in alinan]
                if len(kalan) != len(diger.get('karakterler', [])):
                    onek = {f"{kat}/{c['klasor']}/".casefold() for c in diger['karakterler'] if c['klasor'].casefold() in alinan}
                    diger['karakterler'] = kalan
                    diger['dosyalar'] = [d for d in diger.get('dosyalar', []) if not any(d['yol'].casefold().startswith(p) for p in onek)]
                    _yaz(diger)
        _yaz(k)
        self.asama = 'Tamamlandı'; self.ilerleme = 1.0
        return {'kayit': k, 'eski_tasinan': eskiye}

    def _yerlestir(self, gecici, kok, kat, secilen, b):
        """gecici/<kat>/<Ad>, gecici/<kat>/_ortak/*, gecici/_ortak/<ad> → kok altına. Var olan hedef _eski'ye taşınır.
        Herhangi bir adım başarısız olursa yapılan taşımalar ters sırayla geri alınır."""
        birimler = [(gecici / kat / c['klasor'], kok / kat / c['klasor']) for c in secilen]
        ko = gecici / kat / '_ortak'
        if ko.is_dir():
            birimler += [(p, kok / kat / '_ortak' / p.name) for p in sorted(ko.iterdir())]
        go = gecici / '_ortak'
        if go.is_dir():
            birimler += [(p, kok / '_ortak' / p.name) for p in sorted(go.iterdir())]
        zaman = time.strftime('%Y%m%d-%H%M%S')
        kok_gercek = kok.resolve()
        for _, hedef in birimler:  # hedefin klasörleri bağlantı (junction/symlink) üzerinden paket klasörü dışına çıkmasın
            ust = hedef.parent
            while ust != kok and ust.is_relative_to(kok):
                if ust.exists() and (ust.is_symlink() or ust.is_junction() or not ust.resolve().is_relative_to(kok_gercek)):
                    raise PaketHatasi(f'Paket klasöründe başka yere giden bir bağlantı var ({ust}); paket oraya kurulmaz.')
                ust = ust.parent
        yapilan, eskiye = [], []
        try:
            for kaynak, hedef in birimler:
                if not kaynak.exists():
                    continue
                if hedef.exists() or hedef.is_symlink():
                    arsiv = kok / ESKI / zaman / hedef.relative_to(kok)
                    arsiv.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(hedef, arsiv); yapilan.append((arsiv, hedef)); eskiye.append(str(arsiv))
                hedef.parent.mkdir(parents=True, exist_ok=True)
                os.replace(kaynak, hedef); yapilan.append((hedef, kaynak))
        except BaseException:
            for su_an, eski_yer in reversed(yapilan):
                try:
                    os.replace(su_an, eski_yer)
                except OSError:
                    pass
            raise
        return yapilan, eskiye


class _BaglaMantigi(_Mantik):
    """Bağlantısı kesik paketin dosyalarını (boyut + sha256) denetler; hepsi tamamsa kaydı etkinleştirir."""
    tur = 'bagla'

    def __init__(self, ad):
        super().__init__(); self.ad = ad

    def calis(self):
        k = kayit(self.ad)
        if k is None:
            raise PaketHatasi('Paket kaydı bulunamadı.')
        kok = Path(k['kok']); toplam = sum(d['boyut'] for d in k['dosyalar']) or 1; okunan = 0; sorunlu = []
        self.asama = 'Dosyalar denetleniyor…'
        for d in k['dosyalar']:
            yol = kok / Path(d['yol'])
            try:
                if yol.stat().st_size != d['boyut']:
                    sorunlu.append(d['yol']); okunan += d['boyut']; continue
                h = hashlib.sha256()
                with open(yol, 'rb') as f:
                    while True:
                        parca = f.read(1024 * 1024)
                        if not parca:
                            break
                        pd.kisit(len(parca))
                        h.update(parca); okunan += len(parca); self.ilerleme = 0.99 * okunan / toplam
                if h.hexdigest() != d['sha256']:
                    sorunlu.append(d['yol'])
            except OSError:
                sorunlu.append(d['yol']); okunan += d['boyut']
        if sorunlu:
            raise PaketHatasi(f'{len(sorunlu)} dosya eksik ya da değişmiş (ilk: {sorunlu[0]}). '
                              f'Paket bağlanmadı; .yumipaket dosyasını yeniden ekle.')
        k['etkin'] = True; k['baglanma'] = time.strftime('%Y-%m-%dT%H:%M:%S'); _yaz(k)
        self.asama = 'Tamamlandı'
        return {'kayit': k}


def baglantiyi_kes(ad):
    """Kaldır: dosyalar yerinde kalır, kayıt etkin değil olur."""
    k = kayit(ad)
    if k is None:
        raise PaketHatasi('Paket kaydı bulunamadı.')
    k['etkin'] = False; k['kaldirma'] = time.strftime('%Y-%m-%dT%H:%M:%S'); _yaz(k)
    return k


# ---------------- işçi süreç ----------------
if __name__ == '__main__':
    import sys
    _COCUK = True
    _girdi = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); _durum = Path(sys.argv[2])
    _arka = _arka_plan_kipi()
    _hiz = float(app_paths.env_value('PAKET_HIZ_MB', HIZ_SINIRI_MB) or 0)  # test düzeneği için ortam değişkeni; 0 = sınırsız
    pd.kisit_ayarla(_hiz)
    if _girdi['tur'] == 'kurulum':
        _is = _KurulumMantigi(_girdi['o'], _girdi.get('atla') or (), _girdi.get('uzerine_yaz'))
    else:
        _is = _BaglaMantigi(_girdi['ad'])
    def _durum_yaz(**ek):
        veri = {'ilerleme': _is.ilerleme, 'asama': _is.asama, 'arka_plan': _arka, 'hiz_mb': _hiz, **ek}
        gecici = _durum.with_suffix('.tmp'); gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding='utf-8')
        os.replace(gecici, _durum)
    _bitti = threading.Event()
    def _yazici():
        while not _bitti.wait(0.3):
            try: _durum_yaz()
            except OSError: pass
    threading.Thread(target=_yazici, daemon=True).start()
    _is.yurut(); _bitti.set()
    _durum_yaz(bitti=True, hata=_is.hata, sonuc=_is.sonuc)
