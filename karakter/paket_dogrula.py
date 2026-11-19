""".yumipaket doğrulayıcı ve açıcı (G-F2, 18 Kas 2026). Yalnız standart kütüphane; kod çalıştırmaz, yalnız veri okur.

Biçim (şema: karakter/paket_semasi.json):
  ZIP, sıkıştırmasız (STORED), Zip64. Kök:
    paket.json                      → paket bilgisi + her dosyanın yolu/boyutu/sha256
    karakterler/<Ad>/...            → kurulumda <modeller>/<kategori>/<Ad>/ (karakter klasörünün birebir hali)
    kategori_ortak/...              → kurulumda <modeller>/<kategori>/_ortak/ (guven.json, kaynaklar.json, LICENSES.md,
                                      arka_plan/ tema görselleri)
    ortak/<ad>/...                  → kurulumda <modeller>/_ortak/<ad>/ (karakterlerin ses.klasor ile başvurduğu ortak
                                      klasör; ör. anime paketinde meowko)
  İmza YOK (kullanıcı kararı 18 Kas): bütünlük paket içi sha256 listesiyle. paket.json'daki "imza" alanı ileride imza
  eklenebilsin diye ayrılmıştır; bu sürüm onu doğrulamaz (null değilse sonuçta imza='dogrulanmadi').

API (F3 kullanır):
  paket_bilgisi(yol)            → paket.json (yapı + yol + liste denetimi; sha okumaz; önizleme için hızlı)
  dogrula(yol, ilerleme=None)   → paket.json; her dosyanın boyut + sha256'sı da denetlenir (tam okuma)
  ac(yol, hedef, ilerleme=None) → hedef/ altına KURULUM DÜZENİYLE açar (<kat>/<Ad>/, <kat>/_ortak/, _ortak/<ad>/);
                                  yazarken sha yeniden denetlenir. hedef yoksa oluşturulur, varsa boş olmalı.
                                  Hata olursa bu çağrının yazdığı her şey geri alınır. Döner: {'paket':…, 'dosyalar':[…]}
  kurulum_yolu(arsiv_yolu, kategori) → kurulum köküne göre göreli yol (PurePosixPath)
  PaketHatasi                   → ValueError alt sınıfı; mesaj kullanıcıya gösterilebilir Türkçe metin.
  ilerleme(okunan_bayt, toplam_bayt, arsiv_yolu) isteğe bağlı geri çağırma.
"""
import hashlib, json, os, re, stat, unicodedata, zipfile
from pathlib import Path, PurePosixPath

BICIM = 'yumi-paket'
BICIM_SURUMU = 1
CALISMA_ZAMANI = 'yumi-v1'            # bu Yumi'nin okuyabildiği paket çalışma zamanı
UZANTI = '.yumipaket'
IZINLI_UZANTILAR = frozenset({'.vrm', '.pth', '.json', '.wav', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.md'})
KOKLER = ('karakterler', 'kategori_ortak', 'ortak')
MAKS_PAKET_JSON = 16 * 1024 * 1024
MAKS_DOSYA_SAYISI = 20000
_KATEGORI = re.compile(r'^[a-z][a-z0-9_]{1,30}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')
_SURUM = re.compile(r'^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$')
_WIN_AYRILMIS = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
_YASAK_KARAKTER = set('<>:"|?*\\')
_PARCA = 1024 * 1024
# 19 Kas (kullanıcı): paket işleri diskin tamamını işgal etmesin. İşçi süreç `kisit_ayarla(MB/s)` ile hız sınırı koyar;
# her okunan parça (açmada aynı miktar yazılır) bu sayaçtan geçer. None = sınırsız (Yumi'nin kendi süreci, testler).
_kisit = None


class _HizKisiti:
    def __init__(self, bayt_s):
        self.bayt_s = float(bayt_s); self.t0 = None; self.n = 0

    def __call__(self, n):
        import time
        simdi = time.perf_counter()
        if self.t0 is None or self.n / self.bayt_s - (simdi - self.t0) < -1.0:  # uzun duraklamadan sonra birikmiş hak patlama yapmasın
            self.t0, self.n = simdi, 0
        self.n += n
        bekle = self.n / self.bayt_s - (simdi - self.t0)
        if bekle > 0.002:
            time.sleep(bekle)


def kisit_ayarla(mb_s):
    global _kisit
    _kisit = _HizKisiti(mb_s * 1024 * 1024) if mb_s else None


def kisit(n):
    if _kisit is not None:
        _kisit(n)


class PaketHatasi(ValueError):
    """Paket reddedildi; mesaj kullanıcıya gösterilebilir (Türkçe)."""


def _parca_denetle(parca, tam):
    if parca in ('', '.', '..'):
        raise PaketHatasi(f'Paketteki dosya yolu geçersiz ("." / ".." ya da boş bölüm): {tam}')
    if any(c in _YASAK_KARAKTER or ord(c) < 32 for c in parca):
        raise PaketHatasi(f'Paketteki dosya yolunda izin verilmeyen karakter var: {tam}')
    if parca != parca.strip() or parca.endswith('.'):
        raise PaketHatasi(f'Paketteki dosya yolu boşluk ya da nokta ile bitiyor: {tam}')
    if parca.split('.')[0].casefold() in _WIN_AYRILMIS:
        raise PaketHatasi(f'Paketteki dosya yolu Windows\'a ayrılmış bir ad içeriyor: {tam}')
    if len(parca) > 120:
        raise PaketHatasi(f'Paketteki dosya adı çok uzun: {tam}')


def yol_denetle(ad):
    """Arşiv içi yol güvenli mi? Mutlak yol, sürücü harfi, '..', ters bölü, izinli kök dışı → PaketHatasi.
    Döner: PurePosixPath (paket.json için de geçerli)."""
    if not isinstance(ad, str) or not ad:
        raise PaketHatasi('Paketteki bir dosya yolu boş ya da metin değil.')
    if unicodedata.normalize('NFC', ad) != ad:
        raise PaketHatasi(f'Paketteki dosya yolu standart Unicode biçiminde değil: {ad}')
    if '\\' in ad:
        raise PaketHatasi(f'Paketteki dosya yolunda ters bölü (\\) var: {ad}')
    if ad.startswith('/') or re.match(r'^[A-Za-z]:', ad):
        raise PaketHatasi(f'Pakette mutlak dosya yolu var (izin verilmez): {ad}')
    parcalar = ad.split('/')
    for p in parcalar:
        _parca_denetle(p, ad)
    if ad == 'paket.json':
        return PurePosixPath(ad)
    kok = parcalar[0]
    if kok not in KOKLER:
        raise PaketHatasi(f'Pakette izin verilen klasörlerin (karakterler/, kategori_ortak/, ortak/) dışında dosya var: {ad}')
    en_az = 2 if kok == 'kategori_ortak' else 3
    if len(parcalar) < en_az:
        raise PaketHatasi(f'Paketteki dosya yanlış yerde (karakter/ortak klasörü yok): {ad}')
    uzanti = PurePosixPath(ad).suffix.lower()
    if uzanti not in IZINLI_UZANTILAR:
        raise PaketHatasi(f'Pakette izin verilmeyen dosya türü var ({uzanti or "uzantısız"}): {ad}')
    return PurePosixPath(ad)


def kurulum_yolu(arsiv_yolu, kategori):
    """'karakterler/Haru/ses/x.pth' → '<kat>/Haru/ses/x.pth'; 'kategori_ortak/a' → '<kat>/_ortak/a';
    'ortak/meowko/b' → '_ortak/meowko/b'. Kök = modeller klasörü (VERI\\models)."""
    p = PurePosixPath(arsiv_yolu)
    kok, kalan = p.parts[0], PurePosixPath(*p.parts[1:])
    if kok == 'karakterler':
        return PurePosixPath(kategori) / kalan
    if kok == 'kategori_ortak':
        return PurePosixPath(kategori) / '_ortak' / kalan
    if kok == 'ortak':
        return PurePosixPath('_ortak') / kalan
    raise PaketHatasi(f'Kurulum yolu çıkarılamadı: {arsiv_yolu}')


def _arsiv_ac(yol):
    yol = Path(yol)
    if yol.suffix.lower() != UZANTI:
        raise PaketHatasi(f'Yalnız {UZANTI} uzantılı Yumi paketleri eklenebilir: {yol.name}')
    if not yol.is_file():
        raise PaketHatasi(f'Paket dosyası bulunamadı: {yol}')
    try:
        return zipfile.ZipFile(yol)
    except zipfile.BadZipFile as e:
        raise PaketHatasi(f'Paket dosyası bozuk ya da eksik kopyalanmış (ZIP okunamadı): {yol.name}') from e
    except OSError as e:
        raise PaketHatasi(f'Paket dosyası açılamadı: {yol.name} ({e})') from e


def _girdileri_denetle(arsiv):
    girdiler = arsiv.infolist()
    if len(girdiler) > MAKS_DOSYA_SAYISI:
        raise PaketHatasi('Pakette çok fazla dosya var.')
    adlar, kucuk = {}, set()
    for g in girdiler:
        ham = g.orig_filename
        if ham != g.filename or '\\' in ham:  # Windows'ta zipfile '\\' → '/' çevirir; özgün adı da denetle
            raise PaketHatasi(f'Paketteki dosya yolunda ters bölü (\\) var: {ham}')
        if g.is_dir():
            raise PaketHatasi(f'Pakette klasör girdisi var (beklenmiyor): {g.filename}')
        yol_denetle(g.filename)
        if g.flag_bits & 0x1:
            raise PaketHatasi(f'Pakette şifreli dosya var (desteklenmiyor): {g.filename}')
        if g.compress_type != zipfile.ZIP_STORED:
            raise PaketHatasi(f'Paketteki dosya sıkıştırılmış (yalnız sıkıştırmasız paketler kabul edilir): {g.filename}')
        mod = (g.external_attr >> 16) & 0xFFFF
        if mod and stat.S_ISLNK(mod):
            raise PaketHatasi(f'Pakette sembolik bağlantı var (izin verilmez): {g.filename}')
        anahtar = g.filename.casefold()
        if anahtar in kucuk:
            raise PaketHatasi(f'Pakette aynı adlı iki dosya var: {g.filename}')
        kucuk.add(anahtar)
        adlar[g.filename] = g
    if 'paket.json' not in adlar:
        raise PaketHatasi('Paketin içinde paket.json yok; bu bir Yumi paketi değil.')
    return adlar


def _paket_json_oku(arsiv, adlar):
    g = adlar['paket.json']
    if g.file_size > MAKS_PAKET_JSON:
        raise PaketHatasi('paket.json çok büyük.')
    try:
        veri = json.loads(arsiv.read(g).decode('utf-8'))
    except (zipfile.BadZipFile, OSError) as e:
        raise PaketHatasi('paket.json okunamadı; paket bozuk.') from e
    except (UnicodeDecodeError, ValueError) as e:
        raise PaketHatasi('paket.json geçerli bir JSON değil.') from e
    if not isinstance(veri, dict):
        raise PaketHatasi('paket.json geçerli bir paket bilgisi değil.')
    return veri


def _bilgi_denetle(veri):
    if veri.get('format') != BICIM:
        raise PaketHatasi('Bu bir Yumi model paketi değil (paket.json biçimi tanınmadı).')
    if veri.get('bicim_surumu') != BICIM_SURUMU:
        raise PaketHatasi(f'Paket biçimi sürümü {veri.get("bicim_surumu")!r} bu Yumi sürümünde desteklenmiyor.')
    if veri.get('yumi_calisma_zamani') != CALISMA_ZAMANI:
        raise PaketHatasi(f'Paket bu Yumi sürümüyle uyumlu değil (gereken: {veri.get("yumi_calisma_zamani")!r}).')
    kat = veri.get('kategori')
    if not isinstance(kat, str) or not _KATEGORI.match(kat):
        raise PaketHatasi('Paketin kategorisi geçersiz.')
    pk = veri.get('paket')
    if not isinstance(pk, dict) or not isinstance(pk.get('ad'), str) or not pk['ad'].strip() \
            or not isinstance(pk.get('surum'), str) or not _SURUM.match(pk['surum']):
        raise PaketHatasi('Paketin adı ya da sürümü geçersiz.')
    if not isinstance(veri.get('kisisel'), bool):
        raise PaketHatasi('Paketin "kisisel" bayrağı eksik.')
    if (kat == 'witcher') and not veri['kisisel']:
        raise PaketHatasi('Witcher paketi yalnız kişisel kullanım içindir; dağıtım paketi olarak kabul edilmez.')
    motor = veri.get('ses_motoru')
    if motor is not None:
        if not isinstance(motor, dict) or motor.get('ad') != 'xtts-v2':
            raise PaketHatasi('Paketin ses motoru desteklenmiyor (yalnız xtts-v2).')
        taban = motor.get('taban_model')
        if taban is not None and not (isinstance(taban, dict) and _SHA.match(str(taban.get('sha256', '')))):
            raise PaketHatasi('Paketin ses motoru taban model bilgisi geçersiz.')
    dosyalar = veri.get('dosyalar')
    if not isinstance(dosyalar, list) or not dosyalar:
        raise PaketHatasi('paket.json dosya listesi (sha256) eksik.')
    liste, kucuk = {}, set()
    for d in dosyalar:
        if not isinstance(d, dict):
            raise PaketHatasi('paket.json dosya listesinde geçersiz kayıt var.')
        yol, boyut, sha = d.get('yol'), d.get('boyut'), d.get('sha256')
        if yol == 'paket.json':
            raise PaketHatasi('paket.json kendi dosya listesinde olamaz.')
        yol_denetle(yol)
        if not isinstance(boyut, int) or isinstance(boyut, bool) or boyut < 0:
            raise PaketHatasi(f'paket.json\'da dosya boyutu geçersiz: {yol}')
        if not isinstance(sha, str) or not _SHA.match(sha):
            raise PaketHatasi(f'paket.json\'da sha256 geçersiz: {yol}')
        if yol.casefold() in kucuk:
            raise PaketHatasi(f'paket.json dosya listesinde aynı dosya iki kez var: {yol}')
        kucuk.add(yol.casefold())
        liste[yol] = d
    karakterler = veri.get('karakterler')
    if not isinstance(karakterler, list) or not karakterler:
        raise PaketHatasi('Pakette karakter listesi yok.')
    klasorler = set()
    for k in karakterler:
        if not isinstance(k, dict) or not isinstance(k.get('klasor'), str):
            raise PaketHatasi('paket.json karakter listesinde geçersiz kayıt var.')
        _parca_denetle(k['klasor'], k['klasor'])
        if f'karakterler/{k["klasor"]}/karakter.json' not in liste:
            raise PaketHatasi(f'Karakterin karakter.json dosyası pakette yok: {k["klasor"]}')
        klasorler.add(k['klasor'])
    gercek = {PurePosixPath(y).parts[1] for y in liste if y.startswith('karakterler/')}
    if gercek != klasorler:
        raise PaketHatasi('paket.json karakter listesi paketteki karakter klasörleriyle uyuşmuyor: '
                          + ', '.join(sorted(gercek ^ klasorler)))
    return liste


def _liste_ile_arsiv(liste, adlar):
    arsivdeki = set(adlar) - {'paket.json'}
    eksik = sorted(set(liste) - arsivdeki)
    fazla = sorted(arsivdeki - set(liste))
    if eksik:
        raise PaketHatasi(f'Pakette eksik dosya var ({len(eksik)}): ' + ', '.join(eksik[:5]))
    if fazla:
        raise PaketHatasi(f'Pakette listede olmayan fazladan dosya var ({len(fazla)}): ' + ', '.join(fazla[:5]))
    for yol, d in liste.items():
        if adlar[yol].file_size != d['boyut']:
            raise PaketHatasi(f'Dosya boyutu paket listesiyle uyuşmuyor (bozuk ya da değiştirilmiş): {yol}')


def _karakter_denetle(arsiv, veri, liste, adlar):
    """karakter.json'lar: biçim, kategori, görünüm dosyaları pakette mi, ses klasörü izinli yerde mi."""
    kat = veri['kategori']
    uyarilar = []
    ortaklar = {PurePosixPath(y).parts[1] for y in liste if y.startswith('ortak/')}
    for k in veri['karakterler']:
        yol = f'karakterler/{k["klasor"]}/karakter.json'
        try:
            kj = json.loads(arsiv.read(adlar[yol]).decode('utf-8-sig'))
        except (zipfile.BadZipFile, OSError) as e:
            raise PaketHatasi(f'karakter.json okunamadı (paket bozuk): {yol}') from e
        except (UnicodeDecodeError, ValueError) as e:
            raise PaketHatasi(f'karakter.json geçerli JSON değil: {yol}') from e
        if not isinstance(kj, dict) or kj.get('format') != 'yumi-karakter':
            raise PaketHatasi(f'karakter.json Yumi karakter biçiminde değil: {yol}')
        if kj.get('kategori') != kat:
            raise PaketHatasi(f'Karakterin kategorisi paketle uyuşmuyor ({kj.get("kategori")!r} ≠ {kat!r}): {yol}')
        if kj.get('paket', kat) == 'witcher' and not veri['kisisel']:
            raise PaketHatasi(f'Witcher karakteri dağıtım paketinde olamaz: {k["klasor"]}')
        for g in kj.get('gorunumler') or []:
            dosya = g.get('dosya') if isinstance(g, dict) else None
            if not isinstance(dosya, str) or PurePosixPath(dosya).name != dosya or '\\' in dosya:
                raise PaketHatasi(f'karakter.json görünüm dosya adı geçersiz: {yol}')
            if f'karakterler/{k["klasor"]}/{dosya}' not in liste:
                raise PaketHatasi(f'Görünüm dosyası pakette yok: karakterler/{k["klasor"]}/{dosya}')
        ses = kj.get('ses') or {}
        if isinstance(ses, dict) and ses.get('klasor'):
            hedef = os.path.normpath(os.path.join('M', kat, k['klasor'], str(ses['klasor']))).replace('\\', '/')
            parca = hedef.split('/')
            if parca[:3] == ['M', kat, k['klasor']]:
                pass  # karakterin kendi klasörü
            elif len(parca) == 3 and parca[:2] == ['M', '_ortak']:
                if parca[2] not in ortaklar:
                    uyarilar.append(f'{k["klasor"]}: ses klasörü _ortak/{parca[2]} pakette yok (başka paketten gelmeli)')
            else:
                raise PaketHatasi(f'Karakterin ses klasörü izin verilen yerlerin dışında: {yol} → {ses["klasor"]}')
    return uyarilar


def paket_bilgisi(yol):
    """Hızlı yapısal doğrulama (sha okumadan): biçim, yollar, liste ↔ arşiv, karakter.json'lar. Döner paket.json (+ '_uyarilar')."""
    with _arsiv_ac(yol) as arsiv:
        adlar = _girdileri_denetle(arsiv)
        veri = _paket_json_oku(arsiv, adlar)
        liste = _bilgi_denetle(veri)
        _liste_ile_arsiv(liste, adlar)
        uyarilar = _karakter_denetle(arsiv, veri, liste, adlar)
    veri = dict(veri)
    veri['_uyarilar'] = uyarilar
    veri['_imza'] = 'yok' if veri.get('imza') in (None, '', {}) else 'dogrulanmadi'
    return veri


def _akit(arsiv, girdi, beklenen, ilerleme, sayac, toplam, yaz=None):
    h = hashlib.sha256()
    try:
        with arsiv.open(girdi) as f:
            while True:
                parca = f.read(_PARCA)
                if not parca:
                    break
                kisit(len(parca))
                h.update(parca)
                if yaz is not None:
                    yaz.write(parca)
                sayac[0] += len(parca)
                if ilerleme:
                    ilerleme(sayac[0], toplam, girdi.filename)
    except zipfile.BadZipFile as e:
        raise PaketHatasi(f'Paketteki dosya bozuk ya da değiştirilmiş (ZIP denetimi tutmadı): {girdi.filename}') from e
    except (OSError, EOFError) as e:
        raise PaketHatasi(f'Paketteki dosya okunamadı (paket eksik ya da bozuk): {girdi.filename}') from e
    if h.hexdigest() != beklenen:
        raise PaketHatasi(f'Dosyanın sha256 değeri paket listesiyle uyuşmuyor (dosya değiştirilmiş): {girdi.filename}')


def dogrula(yol, ilerleme=None):
    """Tam doğrulama: paket_bilgisi + her dosyanın boyutu ve sha256'sı. Döner paket.json (+ '_uyarilar', '_imza')."""
    veri = paket_bilgisi(yol)
    toplam = sum(d['boyut'] for d in veri['dosyalar'])
    sayac = [0]
    with _arsiv_ac(yol) as arsiv:
        for d in veri['dosyalar']:
            _akit(arsiv, arsiv.getinfo(d['yol']), d['sha256'], ilerleme, sayac, toplam)
    return veri


def ac(yol, hedef, ilerleme=None, sadece=None):
    """Doğrulayıp hedef/ altına kurulum düzeniyle açar. Hata olursa bu çağrının yazdıkları geri alınır.
    sadece: isteğe bağlı arşiv klasörü önekleri (ör. ['karakterler/Haru', 'ortak/meowko', 'kategori_ortak']); verilirse
    yalnız onların altındaki dosyalar açılır (yapı denetimi yine tüm pakete yapılır; açılan her dosyanın sha'sı denetlenir)."""
    veri = paket_bilgisi(yol)
    secilen = veri['dosyalar']
    if sadece is not None:
        onekler = [str(o).strip('/') for o in sadece]
        secilen = [d for d in secilen if any(d['yol'] == o or d['yol'].startswith(o + '/') for o in onekler)]
        if not secilen:
            raise PaketHatasi('Seçilen klasörler pakette yok: ' + ', '.join(onekler))
    hedef = Path(hedef)
    olusturuldu = not hedef.exists()
    if not olusturuldu and any(hedef.iterdir()):
        raise PaketHatasi(f'Açma klasörü boş değil: {hedef}')
    hedef.mkdir(parents=True, exist_ok=True)
    kok = hedef.resolve()
    yazilan, klasorler = [], []
    toplam = sum(d['boyut'] for d in secilen)
    sayac = [0]
    try:
        with _arsiv_ac(yol) as arsiv:
            for d in secilen:
                goreli = kurulum_yolu(d['yol'], veri['kategori'])
                cikis = kok.joinpath(*goreli.parts)
                if not cikis.resolve().is_relative_to(kok):
                    raise PaketHatasi(f'Paketteki dosya açma klasörünün dışına yazmaya çalışıyor: {d["yol"]}')
                for ust in reversed(cikis.parents):
                    if ust.is_relative_to(kok) and ust != kok and not ust.exists():
                        ust.mkdir()
                        klasorler.append(ust)
                with open(cikis, 'xb') as f:
                    yazilan.append(cikis)
                    _akit(arsiv, arsiv.getinfo(d['yol']), d['sha256'], ilerleme, sayac, toplam, yaz=f)
    except BaseException:
        for p in reversed(yazilan):
            try:
                p.unlink()
            except OSError:
                pass
        for p in reversed(klasorler):
            try:
                p.rmdir()
            except OSError:
                pass
        if olusturuldu:
            try:
                hedef.rmdir()
            except OSError:
                pass
        raise
    return {'paket': veri, 'dosyalar': [str(p) for p in yazilan]}


if __name__ == '__main__':
    import sys, time
    for _akis in (sys.stdout, sys.stderr):
        try:
            _akis.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) < 2:
        print('Kullanım: python paket_dogrula.py <paket.yumipaket> [--hizli]')
        sys.exit(2)
    t = time.perf_counter()
    try:
        bilgi = paket_bilgisi(sys.argv[1]) if '--hizli' in sys.argv else dogrula(sys.argv[1])
    except PaketHatasi as e:
        print('REDDEDİLDİ:', e)
        sys.exit(1)
    print(f'GEÇERLİ: {bilgi["paket"]["ad"]} {bilgi["paket"]["surum"]} ({bilgi["kategori"]}, kisisel={bilgi["kisisel"]}), '
          f'{len(bilgi["karakterler"])} karakter, {len(bilgi["dosyalar"])} dosya, '
          f'{sum(d["boyut"] for d in bilgi["dosyalar"]) / 1e9:.2f} GB, sha {"atlandı" if "--hizli" in sys.argv else "tam"}, '
          f'imza={bilgi["_imza"]}, {time.perf_counter() - t:.1f} s')
    for u in bilgi['_uyarilar']:
        print('UYARI:', u)
