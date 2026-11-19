"""Local VRM library. Karakterler <model kökü>/<kategori>/<karakter>/ altında, karakter.json ile (karakterler.py).
Anahtarlar değişmedi (`vrm:<eski dosya adı>`). G-A2 (18 Kas): kod karakter adı bilmez; hiç model kurulu değilken
seçili görünüm MODELSIZ ('modelsiz') — modelsiz çalışma (Yumi sesi, görüntü yok). Eski skins/ klasörü yalnız geri uyumluluk
için okunur (yazılmaz)."""
from pathlib import Path
import shutil,hashlib,json
from vrm import load_data
import karakterler
ROOT=Path(__file__).resolve().parents[1]
LIBRARY=ROOT/'skins'
BUILTIN_ROOT=ROOT/'assets/characters'
_manifest=BUILTIN_ROOT/'manifest.json'
BUILTINS=json.loads(_manifest.read_text(encoding='utf-8'))['models'] if _manifest.is_file() else {}  # G-A2: dosya anime paketine taşındı; yoksa boş
MODELSIZ='modelsiz'  # hiç karakter kurulu değil: görüntüsüz çalışma anahtarı (ayarlarda skin)
SPRITE='Clippy'  # karakter.json "tur": "clippy" paketinin (retro) görünüm anahtarı; yalnız o paket kuruluyken geçerli

def _yerlesik(key):
    kayit=karakterler.gorunum(key)
    return bool(kayit and kayit['yerlesik']) or key in BUILTINS

def clippy_kurulu():
    """C05: sprite karakter (karakter.json "tur": "clippy") kurulu bir paket mi; modelsiz dağıtımda yoktur."""
    a=karakterler.sprite_klasoru()
    return a is not None and (a/'agent.json').is_file() and (a/'map.png').is_file()

def kurulu_model_var():
    """C05: kullanıcının seçebileceği kurulu bir karakter (VRM ya da Clippy paketi) var mı?"""
    for key in _tum_anahtarlar():
        try:
            if skin_path(key):return True
        except Exception:continue
    return clippy_kurulu()

def is_builtin(key):
    return (key==SPRITE and clippy_kurulu()) or _yerlesik(key)

def default_skin():
    """Varsayılan görünüm: karakter.json'da "varsayilan": true olan görünüm, yoksa ilk yerleşik, yoksa sprite paketi,
    hiçbiri yoksa MODELSIZ (görüntüsüz çalışma)."""
    gorunumler=karakterler.dizin()['gorunum']
    for key,kayit in gorunumler.items():
        if kayit.get('gorunum',{}).get('varsayilan') and skin_path(key):return key
    ilk=next((key for key,kayit in gorunumler.items() if kayit['yerlesik'] and skin_path(key)),None)
    if ilk:return ilk
    return SPRITE if clippy_kurulu() else MODELSIZ

def valid_skin(key):
    if not isinstance(key,str):return False
    if key==MODELSIZ:return not kurulu_model_var()
    return (key==SPRITE and clippy_kurulu()) or skin_path(key) is not None

def _kayitli_yol(key):
    kayit=karakterler.gorunum(key)
    if kayit:return kayit['yol'],kayit['yerlesik']
    name=key[4:]
    if key in BUILTINS:return BUILTIN_ROOT/name,True
    return LIBRARY/name,False

def skin_path(key):
    if not isinstance(key,str) or not key.startswith('vrm:'):return None
    name=key[4:]
    if Path(name).name!=name or Path(name).suffix.lower()!='.vrm':return None
    path,yerlesik=_kayitli_yol(key)
    if not path.is_file():return None
    if not yerlesik:
        from model_packages import approved_model
        if not approved_model(path,name):return None
    return path

def default_name(key):
    from character_names import names
    NAMES=names()
    if isinstance(key,str) and key.startswith('vrm:') and not _yerlesik(key) and Path(key[4:]).name==key[4:]:
        from model_packages import approved_model
        path,_=_kayitli_yol(key)
        entry=approved_model(path,key[4:])
        if entry:return entry['name']
    if key==MODELSIZ or (key==SPRITE and not clippy_kurulu()):return 'Yumi'  # C05: hiç model yoksa ad programın adı
    if key in NAMES:return NAMES[key]
    kayit=karakterler.gorunum(key)
    if kayit:return kayit['gorunum_adi']
    if key in BUILTINS:return BUILTINS[key]['name']
    if not key.startswith('vrm:'):return 'Yumi'
    path=skin_path(key)
    if path:
        try:
            meta=load_data(str(path.resolve())).meta
            name=str(meta.get('title') or meta.get('name') or '').strip()
            if name and not name.isdecimal() and not name.casefold().endswith('.vrm'):return name
        except (OSError,ValueError):pass
    return 'İsimsiz karakter'

def _tum_anahtarlar():
    keys=list(karakterler.dizin()['gorunum'])
    keys+=[key for key in BUILTINS if key not in keys]
    if LIBRARY.exists():
        keys+=['vrm:'+path.name for path in sorted(LIBRARY.glob('*.vrm')) if 'vrm:'+path.name not in keys]
    return keys

def available(settings=None):
    entries=[]
    for key in _tum_anahtarlar():
        try:
            if skin_path(key):entries.append(key)
        except Exception:continue
    if clippy_kurulu():entries.append(SPRITE)  # C05: paket yoksa listede gösterilmez
    return [(default_name(key),key) for key in entries]

def package_group(key):
    if key==SPRITE:
        k=karakterler.dizin()['clippy'];return k['kategori'] if k else None
    kayit=karakterler.gorunum(key)
    if kayit:return kayit['kategori']
    if key in BUILTINS:return 'anime'
    if isinstance(key,str) and key.startswith('vrm:') and Path(key[4:]).name==key[4:]:
        from model_packages import approved_model
        entry=approved_model(LIBRARY/key[4:],key[4:])
        if entry:return entry.get('group','anime')
    return None

def grouped_available(settings=None):
    """Kurulu paketler (kategori sırası alfabetik), başlık "<Kategori> paketi". Hiç paket yoksa boş liste."""
    from model_packages import grup_basligi
    entries=available(settings)
    return [(grup_basligi(group),[(name,key) for name,key in entries if package_group(key)==group])
            for group in karakterler.dizin()['kategoriler']]

def existing_model_key(source):
    source=Path(source).resolve()
    if not source.is_file():return None
    digest=hashlib.sha256(source.read_bytes()).digest()
    for key in _tum_anahtarlar():
        path,_=_kayitli_yol(key)
        if path.is_file() and hashlib.sha256(path.read_bytes()).digest()==digest:return key
    return None

def add_model(source):
    from model_packages import install_package
    key=install_package(source)
    karakterler.yenile()
    return key


def remove_model(key):
    # 12 Kasım (kullanıcı): yerleşik VRM'ler de kaldırılabilir; dosya silinmez, data/kaldirilan-modeller'e taşınır.
    if key==SPRITE:raise ValueError(default_name(key)+' kaldırılamaz.')
    path=skin_path(key)
    if path is None:return
    from app_paths import data_dir;target_dir=data_dir()/'kaldirilan-modeller';target_dir.mkdir(parents=True,exist_ok=True)  # 12 Kasım: work/ yerine data/
    target=target_dir/path.name;number=2
    while target.exists():target=target_dir/(path.stem+'-'+str(number)+'.vrm');number+=1
    izinli=(LIBRARY.resolve(),*[k.resolve() for k in karakterler.model_kokleri()])
    if not any(path.resolve().is_relative_to(k) for k in izinli) or not target.resolve().is_relative_to(target_dir.resolve()):raise ValueError('Invalid model path')
    shutil.move(str(path),str(target))
    karakterler.yenile()
