"""Signed, data-only character packages. Publisher keys never ship with Yumi."""
from pathlib import Path
from functools import lru_cache
import base64, hashlib, json, os, tempfile, zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
MAX_MODEL = 256 * 1024 * 1024
CHECKS = ('rig', 'idle', 'walk', 'sit_stand', 'dance', 'contacts', 'expressions', 'hair_cloth')
FILES = {'manifest.json', 'manifest.sig', 'model.vrm'}
import re as _re_grup
_GRUP = _re_grup.compile(r'^[a-z][a-z0-9_]{1,30}$')  # G-A2: paket kategorisi sabit liste değil; güvenli klasör adı

def grup_basligi(grup):
    """Model sayfasındaki grup başlığı: "<Kategori> paketi"."""
    return str(grup).replace('_', ' ').strip().capitalize() + ' paketi'

def __getattr__(ad):
    if ad == 'GROUPS':  # eski çağıranlar: kurulu kategoriler
        import karakterler
        return {g: grup_basligi(g) for g in karakterler.dizin()['kategoriler']}
    raise AttributeError(ad)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def validate_manifest(manifest):
    if manifest.get('format') != 'yumi-model-package' or manifest.get('version') != 1:
        raise ValueError('Model paketi sürümü desteklenmiyor.')
    if not isinstance(manifest.get('group'), str) or not _GRUP.match(manifest['group']):
        raise ValueError('Model paketi grubu geçersiz.')
    name = manifest.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 30 or not all(c.isalpha() or c in " -'" for c in name):
        raise ValueError('Paketin model adı geçersiz.')
    if manifest.get('runtime') != 'yumi-v1':
        raise ValueError('Paket bu Yumi sürümüyle uyumlu değil.')
    report = manifest.get('acceptance', {})
    if (report.get('model_sha256') != manifest.get('model_sha256') or
        report.get('suite') != 'yumi-character-v1' or
        any(report.get('checks', {}).get(check) != 'pass' for check in CHECKS)):
        raise ValueError('Modelin hareket ve fizik kabul testleri tamamlanmamış.')

def verify_manifest(raw, signature):
    try:
        manifest = json.loads(raw)
        trust = json.loads((ROOT / 'assets/characters/package-trust.json').read_text(encoding='utf-8'))
        key = trust['keys'][manifest['publisher']]
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(signature, raw)
        validate_manifest(manifest)
        return manifest
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError('Model paketi doğrulanamadı: ' + str(error)) from error
    except Exception as error:
        raise ValueError('Model paketi imzası geçersiz.') from error

def read_package(source):
    source = Path(source)
    if source.suffix.lower() != '.yumimodel':
        raise ValueError('Yalnız onaylı .yumimodel paketleri eklenebilir.')
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != 3 or {i.filename for i in entries} != FILES:
                raise ValueError('Paket dosyaları geçersiz.')
            limits = {'manifest.json': 65536, 'manifest.sig': 64, 'model.vrm': MAX_MODEL}
            if any(i.file_size > limits[i.filename] or i.flag_bits & 1 for i in entries):
                raise ValueError('Paket boyutu veya şifreleme desteklenmiyor.')
            raw = archive.read('manifest.json')
            signature = archive.read('manifest.sig')
            manifest = verify_manifest(raw, signature)
            model = archive.read('model.vrm')
            if digest(model) != manifest['model_sha256']:
                raise ValueError('Model dosyası paketten sonra değiştirilmiş.')
            return manifest, model, raw, signature
    except zipfile.BadZipFile as error:
        raise ValueError('Model paketi okunamadı.') from error

def install_package(source):
    manifest, model, raw, signature = read_package(source)
    from vrm import load_data
    from model_compatibility import profile
    # 12 Kasım (DUZEN): paket models/<grup>/<ad>/ altına kurulur, karakter.json ile (karakterler.py).
    import re as _re
    klasor_adi = _re.sub(r"[^\w\- ]+", "", manifest['name']).strip() or 'Karakter'
    from app_paths import modeller_dir  # G-A2: eklenen paketler kullanıcı veri alanına (VERI\\models)
    library = modeller_dir() / manifest['group'] / klasor_adi
    if library.exists() and not (library / 'karakter.json').exists():
        library = library.with_name(klasor_adi + '-' + digest(model)[:8])
    library.mkdir(parents=True, exist_ok=True)
    # Validate before publishing either file; no archive paths are extracted.
    with tempfile.TemporaryDirectory(dir=library) as folder:
        staging = Path(folder) / 'model.vrm'
        staging.write_bytes(model)
        report = profile(load_data(str(staging)))
        if not report['desktop_supported']:
            raise ValueError('Paketin iskeleti masaüstü hareketlerini desteklemiyor.')
        name = 'package-' + digest(model) + '.vrm'
        receipt = library / (name + '.json')
        staged_receipt = Path(folder) / 'receipt.json'
        staged_receipt.write_text(json.dumps({'manifest': base64.b64encode(raw).decode(), 'signature': base64.b64encode(signature).decode()}), encoding='utf-8')
        os.replace(staging, library / name)
        os.replace(staged_receipt, receipt)
    kart = library / 'karakter.json'
    try:
        veri = json.loads(kart.read_text(encoding='utf-8')) if kart.exists() else None
    except ValueError:
        veri = None
    if not isinstance(veri, dict) or veri.get('format') != 'yumi-karakter':
        veri = {'format': 'yumi-karakter', 'surum': 1, 'ad': manifest['name'], 'kategori': manifest['group'], 'yerlesik': False, 'gorunumler': []}
    if not any(g.get('anahtar') == 'vrm:' + name for g in veri['gorunumler']):
        veri['gorunumler'].append({'anahtar': 'vrm:' + name, 'dosya': name, 'ad': manifest['name']})
    kart.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding='utf-8')
    return 'vrm:' + name

@lru_cache(maxsize=128)
def _approved(path, size, modified, receipt_modified, trust_modified, kayit_adi=None):
    path = Path(path)
    try:
        receipt = path.with_name(path.name + '.json')
        if receipt.exists():
            doc = json.loads(receipt.read_text(encoding='utf-8'))
            manifest = verify_manifest(base64.b64decode(doc['manifest']), base64.b64decode(doc['signature']))
            return manifest if digest(path.read_bytes()) == manifest['model_sha256'] else None
        import karakterler  # G-A2: kişisel kullanım güven kaydı paketin _ortak/guven.json'unda (yalnız geliştirme)
        baseline = karakterler.guven_listesi()
        eski = ROOT / 'assets/characters/legacy-models.json'
        if eski.is_file():
            baseline = {**json.loads(eski.read_text(encoding='utf-8')), **baseline}
        entry = baseline.get(kayit_adi or path.name)  # 12 Kasım: dosya karakter klasöründe yeniden adlandırılmış olabilir
        return entry if entry and digest(path.read_bytes()) == entry['model_sha256'] else None
    except Exception:
        return None

def approved_model(path, kayit_adi=None):
    """kayit_adi: legacy-models.json'daki eski dosya adı (anahtarın `vrm:` sonrası); verilmezse dosya adı."""
    path = Path(path)
    try:
        info = path.stat()
        receipt = path.with_name(path.name + '.json')
        trust = ROOT / 'assets/characters/package-trust.json'
        return _approved(str(path), info.st_size, info.st_mtime_ns, receipt.stat().st_mtime_ns if receipt.exists() else 0, trust.stat().st_mtime_ns, kayit_adi)
    except OSError:
        return None
