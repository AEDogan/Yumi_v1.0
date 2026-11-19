"""Yumi yolları: UYGULAMA (kod + ana modül modelleri, yazılmaz) ve VERI (yazılabilir) kökleri.

G-A2 (18 Kas 2026, kullanıcı kararı 13:45/13:50):
- UYGULAMA = bu kodun bulunduğu `Yumi\\` klasörü. Kurulumda `C:\\Program Files\\Yumi` (salt okunur); çalışırken buraya
  hiçbir şey yazılmaz.
- VERI = kullanıcının yazılabilir alanı.
  * Geliştirme (UYGULAMA'da `gelistirme.flag` var ya da Program Files dışında çalışıyor): veri `Yumi\\data`,
    eklenen model paketleri `Yumi\\models\\<kategori>` (eski düzen aynen).
  * Kurulum (Program Files altında, `gelistirme.flag` yok): `%LOCALAPPDATA%\\Yumi\\data` ve `%LOCALAPPDATA%\\Yumi\\models`.
- Model listesi iki yeri okur: `UYGULAMA\\models` (yalnız ana modül: whisper, niyet, yamnet, music, _ortak, varsayilan_ses)
  + `VERI\\models\\<kategori>` (eklenen paketler). Geliştirmede ikisi aynı klasördür.
- Ortam değişkenleri (test düzenekleri): YUMI_DATA_DIR (veri klasörü), YUMI_MODELS_DIR (eklenen model paketlerinin kökü),
  YUMI_KURULUM=1 (kurulum kipini zorla; VERI kökü YUMI_VERI_KOKU ya da %LOCALAPPDATA%\\Yumi).
"""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UYGULAMA=ROOT
APP_ID=os.environ.get('YUMI_APP_ID') or 'YumiDesktopCompanion'  # F1b: kurulu kopyanın testi, açık geliştirme Yumi'siyle çakışmasın
DATA_NAME='YumiDesktop'
LEGACY_DATA_NAME='MikaDesktop'
UYGULAMA_MODELLER=UYGULAMA/'models'          # yalnız ana modül (setup ile gelir)
VARSAYILAN_SES=UYGULAMA_MODELLER/'varsayilan_ses'  # modelsiz kurulumda konuşan varsayılan Yumi sesi

def env_value(name,default=None):
    """Old test/installation overrides remain readable during migration."""
    return os.environ.get('YUMI_'+name,os.environ.get('MIKA_'+name,default))

def _program_files_altinda(yol):
    adaylar=[os.environ.get(k) for k in ('ProgramFiles','ProgramFiles(x86)','ProgramW6432')]
    yol=os.path.normcase(str(yol))
    return any(a and (yol+os.sep).startswith(os.path.normcase(a.rstrip('\\/'))+os.sep) for a in adaylar)

def gelistirme():
    """Geliştirme kipi mi? (veri ve eklenen modeller uygulama klasörünün içinde)."""
    zorla=env_value('KURULUM')
    if zorla is not None and str(zorla).strip() not in ('','0'):return False
    if (UYGULAMA/'gelistirme.flag').exists():return True
    return not _program_files_altinda(UYGULAMA)

def veri_koku():
    """Kurulumda %LOCALAPPDATA%\\Yumi; geliştirmede uygulama klasörü (data/ ve models/ onun altında)."""
    if gelistirme():return UYGULAMA
    override=env_value('VERI_KOKU')
    if override:return Path(override)
    yerel=os.environ.get('LOCALAPPDATA') or str(Path.home()/'AppData'/'Local')
    return Path(yerel)/'Yumi'

VERI=veri_koku()
PROJECT_DATA=VERI/'data'

def modeller_dir():
    """Eklenen model paketlerinin kökü (kategori klasörleri burada: <kök>/<kategori>/<karakter>/karakter.json)."""
    override=env_value('MODELS_DIR')
    if override:return Path(override)
    return VERI/'models'

_PAKET={'kayitlar':None}
def paket_kayitlari():
    """F3 (19 Kas): data/paketler/*.json paket makbuzları (etkin ve bağlantısı kesik). Önbellekli; değişince
    paket_onbellek_sifirla() (paket_yonetici yazarken çağırır)."""
    if _PAKET['kayitlar'] is None:
        import json
        sonuc=[]
        klasor=data_dir()/'paketler'
        if klasor.is_dir():
            for yol in sorted(klasor.glob('*.json')):
                try:veri=json.loads(yol.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
                if isinstance(veri,dict) and veri.get('bicim')=='yumi-paket-kaydi' and veri.get('ad') and veri.get('kok') and veri.get('kategori'):
                    sonuc.append(veri)
        _PAKET['kayitlar']=sonuc
    return _PAKET['kayitlar']
def paket_onbellek_sifirla():
    _PAKET['kayitlar']=None
def kapali_karakter_klasorleri():
    """Bağlantısı kesik (etkin değil) paketlerin karakter klasörleri: dosyalar yerinde ama listede görünmez."""
    sonuc=set()
    for k in paket_kayitlari():
        if k.get('etkin'):continue
        for c in k.get('karakterler') or []:
            yol=Path(k['kok'])/k['kategori']/str(c.get('klasor',''))
            try:sonuc.add(os.path.normcase(str(yol.resolve())))
            except OSError:sonuc.add(os.path.normcase(str(yol)))
    return sonuc
def model_kokleri():
    """Karakter/model aranacak kökler: eklenen paketler önce (varsayılan kök + etkin paketlerin "Paket klasörü"
    kökleri), sonra ana modül (aynıysa bir kez)."""
    kokler=[]
    ek=[Path(k['kok']) for k in paket_kayitlari() if k.get('etkin')]
    for k in (modeller_dir(),*ek,UYGULAMA_MODELLER):
        try:anahtar=os.path.normcase(str(Path(k).resolve()))
        except OSError:anahtar=os.path.normcase(str(k))
        if anahtar not in [a for a,_ in kokler]:kokler.append((anahtar,Path(k)))
    return [k for _,k in kokler]

def ortak_klasor(ad):
    """`_ortak/<ad>` klasörünü model köklerinde arar (ör. xtts_anime ana modülde)."""
    for kok in model_kokleri():
        aday=kok/'_ortak'/ad
        if aday.is_dir():return aday
    return None

def _legacy_roots(parent):
    return [parent/DATA_NAME,parent/LEGACY_DATA_NAME]

def data_dir(base=None):
    """Kullanıcı verisi. Geliştirmede `Yumi\\data` (git dışı), kurulumda `%LOCALAPPDATA%\\Yumi\\data`.

    Geliştirmede ilk açılışta eski %APPDATA%\\YumiDesktop aynı diskte data/'ya taşınır (eski geçiş aynen);
    kurulumda eski konum aranmaz.
    """
    override=env_value('DATA_DIR')
    if override:return Path(override)
    if base is not None:
        # Tests and tools that pass an explicit parent keep the old layout.
        parent=Path(base);target=parent/DATA_NAME;old=parent/LEGACY_DATA_NAME
        if old.exists() and not target.exists():old.rename(target)
        if old.exists() and target.exists():
            raise RuntimeError('İki kullanıcı veri klasörü bulundu. Verileri birleştirmeden önce güvenli geçiş denetimi gerekiyor; hiçbir kayıt değiştirilmedi.')
        return target
    target=PROJECT_DATA
    if not gelistirme():return target
    appdata=os.environ.get('APPDATA')
    if appdata:
        existing=[old for old in _legacy_roots(Path(appdata)) if old.exists()]
        if len(existing)>1 or (existing and target.exists() and any(target.iterdir())):
            raise RuntimeError('Hem proje içinde hem AppData altında Yumi verisi bulundu. Birleştirmeden önce kontrol gerekiyor; hiçbir kayıt değiştirilmedi.')
        if existing:
            if target.exists():target.rmdir()  # empty placeholder only
            try:existing[0].rename(target)
            except OSError as error:
                import logging
                logging.getLogger('yumi.paths').warning('AppData verisi projeye taşınamadı, eski konum kullanılıyor: %s',error)
                return existing[0]
    return target

def migrated_default_name(value):
    value=str(value or '').strip()
    return 'Yumi' if not value or value.casefold()=='mika' else value
