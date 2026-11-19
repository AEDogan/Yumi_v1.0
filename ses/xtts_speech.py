"""Local fine-tuned XTTS voices through one persistent worker.

G-A2 (18 Kas): kod hiçbir karakter/ses adı bilmez. Karakter sesleri kurulu karakterlerin karakter.json "ses" alanından
(tur xtts_witcher | xtts_anime | meowko; ad, cins, varyant, surumler, eq_tiz_db); ana modülde yalnız XTTS tabanı
(UYGULAMA/models/_ortak/xtts_anime: temel.pth, config.json, vocab.json) ve varsayılan Yumi sesi
(UYGULAMA/models/varsayilan_ses, anahtar `xtts:varsayilan`) bulunur.

Voice keys (ADLANDIRMA, 13 Kasım): karakter sesleri model adıyla — xtts:<model>[:<sürüm>] (xtts:yumi, xtts:akira,
xtts:triss, xtts:yumi:temel). Eski iç anahtarlar (xtts:anime:<ses>:<sürüm>, xtts:meowko:<mod>, xtts:<witcher id>) aynen
çalışır; `cozumle` model adlı anahtarı iç anahtara, `kanonik` eskisini model adlısına çevirir. Sahipsiz (ses havuzu)
sesler eski anahtarıyla kalır.
12 Kasım (DUZEN): ses dosyaları Yumi içinde — karakter sesi models/<kategori>/<karakter>/ses/ (karakter.json,
karakterler.py), ortak anime XTTS tabanı models/_ortak/xtts_anime/, Meowko models/_ortak/meowko/, boştaki
anime sesleri models/_ortak/ses_havuzu/<ses>/ (varsa; 12 Kasım'dan beri work/ses_havuzu'nda). The Python runtime lives inside Yumi (runtime/xtts-gpu|xtts-env).
"""
import json, os, subprocess, tempfile, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT.parent
# B07: ekran kartı (ROCm) ortamı varsa o, yoksa eski CPU ortamı. MIOPEN_FIND_MODE=FAST şart
# (yoksa MIOpen ilk çağrıda saatlerce asılı kalabiliyor); ROCm süreci kendiliğinden kapanmaz -> kill.
GPU_PYTHON = ROOT / 'runtime' / 'xtts-gpu' / 'Scripts' / 'python.exe'
CPU_PYTHON = ROOT / 'runtime' / 'xtts-env' / 'Scripts' / 'python.exe'
PYTHON = GPU_PYTHON if GPU_PYTHON.is_file() else CPU_PYTHON
WORKER = ROOT / 'ses' / 'xtts_worker.py'
import karakterler
import app_paths
WITCHER_PARAMS = {'gpt_cond_len': 14, 'temperature': 0.62, 'repetition_penalty': 2.8, 'top_p': 0.82, 'speed': 1.0, 'sound_norm_refs': True}
# Anime XTTS sesleri (9 Kasım): models/xtts_anime/ (ses eğitimi 13 Kasım'dan beri ayrı projede).
# Anahtar xtts:anime:<ses>:<sürüm>; dosyalar yerinde güncellenirse anahtar ve karakter eşleşmesi değişmez.
# Parametreler kullanıcı dinleme kabulündeki üretimle aynı (XTTS-v2 varsayılanları).
ANIME = app_paths.UYGULAMA_MODELLER / '_ortak' / 'xtts_anime'  # XTTS tabanı: temel.pth, config.json, vocab.json (ana modül)
VARSAYILAN = app_paths.VARSAYILAN_SES  # varsayılan Yumi sesi: ince_ayar.pth, ref.wav, ses.json
ANIME_PARAMS = {'gpt_cond_len': 30, 'temperature': 0.75, 'repetition_penalty': 10.0, 'top_p': 0.85, 'speed': 1.0, 'sound_norm_refs': False}
ANIME_SURUM = {'temel': 'Temel', 'ince_ayar': 'İnce ayarlı', 'temiz_temel': 'Temiz ref., temel', 'temiz_ince_ayar': 'Temiz ref., ince ayarlı'}

def _anime_klasor(ad):
    return karakterler.dizin()['anime_ses'].get(ad)

def _witcher_klasor(vid):
    return karakterler.dizin()['witcher_ses'].get(vid)

def _anime_hazir(ad):
    klasor = _anime_klasor(ad)
    return bool(klasor) and (klasor / 'ince_ayar.pth').is_file()

def _meowko():
    return karakterler.dizin().get('meowko_ses')

def _ses_bilgisi(klasor):
    """Sahipsiz (ses havuzu) sesin kendi ses.json'u: {ad, cins, surumler, eq_tiz_db}."""
    try:
        v = json.loads((Path(klasor) / 'ses.json').read_text(encoding='utf-8'))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def _anime_catalog():
    """{ses id: {ad, cins, surumler, eq_tiz_db}} — karakter.json "ses" alanlarından + havuz seslerinin ses.json'u
    (G-A2: eski ana modül sesler.json'un yerine)."""
    d = karakterler.dizin(); katalog = {}
    for k in d['karakter']:
        ses = k['veri'].get('ses') or {}
        if ses.get('tur') == 'xtts_anime' and ses.get('id'):
            bilgi = {x: ses[x] for x in ('ad', 'cins', 'surumler', 'eq_tiz_db') if x in ses}
            katalog.setdefault(str(ses['id']), bilgi)
    for sid, klasor in d['anime_ses'].items():
        if sid not in katalog:
            katalog[sid] = _ses_bilgisi(klasor)
    return katalog

def _witcher_bilgi(vid):
    """Witcher ses kimliği → (karakter klasör adı, görünen ad, cins) — karakter.json "ses" alanından."""
    for k in karakterler.dizin()['karakter']:
        ses = k['veri'].get('ses') or {}
        if ses.get('tur') == 'xtts_witcher' and str(ses.get('id')) == vid:
            return (k['klasor'].name, str(ses.get('ad') or k['ad']), str(ses.get('cins') or 'female'))
    return None

def __getattr__(ad):
    if ad == 'WITCHER_VOICES':  # eski çağıranlar: id -> (klasör, görünen ad, cins)
        return {vid: _witcher_bilgi(vid) for vid in karakterler.dizin()['witcher_ses'] if _witcher_bilgi(vid)}
    if ad == 'MEOWKO':
        return _meowko()
    raise AttributeError(ad)

_MS = {'dizin': None, 'veri': {}}

def model_sesleri():
    """{model anahtarı (klasör adı, küçük harf): {'model', 'eski' (iç anahtar tabanı), 'tur', 'varyant', 'cins'}}."""
    d = karakterler.dizin()
    if _MS['dizin'] is d: return _MS['veri']
    katalog = _anime_catalog(); veri = {}
    for k in d['karakter']:
        ses = k['veri'].get('ses') or {}; tur = ses.get('tur'); ad = k['klasor'].name; varyant = None
        if tur == 'meowko':
            eski = 'xtts:meowko:' + ('deep' if ses.get('mod') == 'deep' else 'kawaii'); cins = 'female'
        elif tur == 'xtts_anime' and ses.get('id'):
            sid = str(ses['id']); info = katalog.get(sid, {})
            varyant = ses.get('varyant') or 'ince_ayar'  # G-A2: eski eslestirme.json varyantı karakter.json'da
            if varyant not in info.get('surumler', ['temel', 'ince_ayar']): varyant = 'ince_ayar'
            eski = f'xtts:anime:{sid}'; cins = info.get('cins', 'female')
        elif tur == 'xtts_witcher' and ses.get('id'):
            vid = str(ses['id']); eski = f'xtts:{vid}'; cins = str(ses.get('cins') or 'female')
        else: continue
        veri.setdefault(ad.casefold(), {'model': ad, 'eski': eski, 'tur': tur, 'varyant': varyant, 'cins': cins})
    _MS.update(dizin=d, veri=veri)
    return veri

def cozumle(voice):
    """Model adlı anahtar (xtts:yumi, xtts:yumi:temel) → iç anahtar. Eski/bilinmeyen anahtarlar aynen döner."""
    parts = str(voice or '').split(':')
    if len(parts) >= 2 and parts[0] == 'xtts' and parts[1] not in ('anime', 'meowko', 'varsayilan'):
        m = model_sesleri().get(parts[1].casefold())
        if m:
            if m['tur'] == 'xtts_anime': return f"{m['eski']}:{parts[2] if len(parts) > 2 else m['varyant']}"
            return m['eski']
    return voice

def kanonik(voice):
    """Eski ses anahtarı → model adlı anahtar (ayar göçü). Sahibi olmayan ses (ses havuzu, Edge, Gemini) aynen kalır."""
    v = str(voice or '')
    if v.startswith('meowko'): v = 'xtts:meowko:' + ('deep' if 'deep' in v else 'kawaii')
    if not v.startswith('xtts:'): return voice
    parts = v.split(':'); ms = model_sesleri()
    if parts[1] not in ('anime', 'meowko'):
        if parts[1].casefold() in ms: return ':'.join(['xtts', parts[1].casefold()] + parts[2:])
    for ad, m in ms.items():
        if m['tur'] == 'xtts_anime':
            if parts[1] == 'anime' and len(parts) >= 3 and m['eski'] == f'xtts:anime:{parts[2]}':
                surum = parts[3] if len(parts) > 3 else 'ince_ayar'
                return f'xtts:{ad}' if surum == m['varyant'] else f'xtts:{ad}:{surum}'
        elif m['eski'] == v:
            return f'xtts:{ad}'
    return v

def voices():
    """Catalog rows (title, key, gender) for voices whose model files exist.
    ADLANDIRMA (13 Kasım): karakter sesleri "<Model> sesi" adıyla ve model adlı anahtarla; sahipsizler eski adıyla."""
    rows = []; sahipli = set()
    anime_var = (ANIME / 'temel.pth').is_file(); katalog = _anime_catalog(); MEOWKO = _meowko()
    if anime_var and (VARSAYILAN / 'ince_ayar.pth').is_file() and (VARSAYILAN / 'ref.wav').is_file():
        from dagitim import SISTEM_SESI, SISTEM_SESI_ADI
        rows.append((SISTEM_SESI_ADI, SISTEM_SESI, 'female'))  # modelsiz kurulumda da konuşan ses
    for ad, m in model_sesleri().items():
        if m['tur'] == 'meowko':
            if not (MEOWKO and (MEOWKO / 'meowko_final.pth').is_file()): continue
            rows.append((f"{m['model']} sesi", f'xtts:{ad}', 'female'))
        elif m['tur'] == 'xtts_witcher':
            vid = m['eski'].split(':')[1]; klasor = _witcher_klasor(vid)
            if not (klasor and (klasor / f'{vid}_final.pth').is_file()): continue
            rows.append((f"{m['model']} sesi", f'xtts:{ad}', m['cins']))
        else:
            sid = m['eski'].split(':')[2]
            if not (anime_var and _anime_hazir(sid)): continue
            rows.append((f"{m['model']} sesi", f'xtts:{ad}', m['cins']))
            for surum in katalog.get(sid, {}).get('surumler', ['temel', 'ince_ayar']):
                if surum != m['varyant']:
                    rows.append((f"{m['model']} sesi · {ANIME_SURUM.get(surum, surum)}", f'xtts:{ad}:{surum}', m['cins']))
        sahipli.add(m['eski'])
    for key, mode, title in (('xtts:meowko:kawaii', 'kawaii', 'Meowko · Kawaii (1.25x · Özel Yayıncı)'),
                             ('xtts:meowko:deep', 'deep', 'Meowko · Deep (1.15x · Tok Yayıncı)')):
        if key not in sahipli and MEOWKO and (MEOWKO / 'meowko_final.pth').is_file(): rows.append((title, key, 'female'))
    if anime_var:
        for ad, info in sorted(katalog.items()):
            if f'xtts:anime:{ad}' in sahipli or not _anime_hazir(ad): continue
            for surum in info.get('surumler', ['temel', 'ince_ayar']):
                rows.append((f"Ses havuzu · {info.get('ad', ad)} · {ANIME_SURUM.get(surum, surum)}", f'xtts:anime:{ad}:{surum}', info.get('cins', 'female')))
    return rows

# Konuşma hızı (12 Kasım, kullanıcı): modele özel ayar (profil speech_rate); sesin kendi temposunu çarpar.
HIZ = 1.0

def hiz_ayarla(carpan):
    global HIZ
    try: HIZ = max(0.7, min(1.5, float(carpan)))
    except (TypeError, ValueError): HIZ = 1.0

def _request_for(voice):
    request = _istek(cozumle(voice))
    request['params']['speed'] = round(float(request['params'].get('speed', 1.0)) * HIZ, 3)
    return request

def _istek(voice):
    parts = voice.split(':')
    if len(parts) >= 2 and parts[1] == 'varsayilan':
        if not ((VARSAYILAN / 'ince_ayar.pth').is_file() and (VARSAYILAN / 'ref.wav').is_file()):
            raise RuntimeError(f'Varsayılan Yumi sesi kurulu değil: {VARSAYILAN}')
        params = dict(ANIME_PARAMS)
        eq = _ses_bilgisi(VARSAYILAN).get('eq_tiz_db')
        if eq: params['eq_tiz_db'] = float(eq)
        return {'model_dir': str(ANIME), 'checkpoint': str(VARSAYILAN / 'ince_ayar.pth'), 'refs': [str(VARSAYILAN / 'ref.wav')], 'params': params}
    if parts[1] == 'meowko' or voice.startswith('meowko'):
        MEOWKO = _meowko()
        if MEOWKO is None: raise RuntimeError(f'XTTS ses klasörü bulunamadı: {voice}')
        mode = parts[2] if len(parts) > 2 else 'kawaii'
        refs = sorted(str(p) for p in MEOWKO.glob(f'ref_{mode}_*.wav')) or [str(MEOWKO / 'ref1.wav')]
        params = {'gpt_cond_len': 6, 'temperature': 0.85 if mode == 'kawaii' else 0.72, 'repetition_penalty': 2.4,
                  'top_p': 0.85, 'speed': 1.25 if mode == 'kawaii' else 1.15, 'sound_norm_refs': False}
        return {'model_dir': str(MEOWKO), 'checkpoint': 'meowko_final.pth', 'refs': refs, 'params': params}
    if parts[1] == 'anime':
        ad = parts[2] if len(parts) > 2 else ''
        surum = parts[3] if len(parts) > 3 else 'ince_ayar'
        folder = _anime_klasor(ad)
        if not ad or not _anime_hazir(ad): raise RuntimeError(f'Bilinmeyen XTTS sesi: {voice}')
        ref = folder / ('ref_temiz.wav' if surum.startswith('temiz') and (folder / 'ref_temiz.wav').is_file() else 'ref.wav')
        checkpoint = 'temel.pth' if surum in ('temel', 'temiz_temel') else str(folder / 'ince_ayar.pth')  # mutlak yol: işçi os.path.join ile model_dir'i yok sayar
        params = dict(ANIME_PARAMS)
        eq = _anime_catalog().get(ad, {}).get('eq_tiz_db')  # sesler.json: ses başına tiz (japan_girl +7 dB, 10 Kasım)
        if eq: params['eq_tiz_db'] = float(eq)
        return {'model_dir': str(ANIME), 'checkpoint': checkpoint, 'refs': [str(ref)], 'params': params}
    vid = parts[1]
    folder = _witcher_klasor(vid)
    if folder is None and _witcher_bilgi(vid) is None: raise RuntimeError(f'Bilinmeyen XTTS sesi: {voice}')
    if folder is None: raise RuntimeError(f'XTTS ses klasörü bulunamadı: {voice}')
    refs = [str(folder / f'ref{i}.wav') for i in range(1, 5) if (folder / f'ref{i}.wav').is_file()] or [str(folder / 'ref_clean.wav')]
    return {'model_dir': str(folder), 'checkpoint': f'{vid}_final.pth', 'refs': refs, 'params': dict(WITCHER_PARAMS)}

class _Worker:
    def __init__(self):
        from ses_motoru.akis import SiraKilidi
        self.lock = SiraKilidi(); self.process = None  # cümleler geliş sırasıyla üretilsin
    def _start(self):
        if not PYTHON.is_file(): raise RuntimeError('XTTS çalışma ortamı bulunamadı (runtime/xtts-env).')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        env = os.environ.copy(); env.update(PYTHONIOENCODING='utf-8', MIOPEN_FIND_MODE='FAST', COQUI_TOS_AGREED='1')
        try:
            from resource_guard import popen_worker as start
        except Exception:
            start = subprocess.Popen
        from app_paths import data_dir; (data_dir() / 'logs').mkdir(parents=True, exist_ok=True)
        log = (data_dir() / 'logs' / 'xtts-worker.log').open('w', encoding='utf-8')  # çökme nedeni burada (12 Kasım: data/logs)
        self.process = start([str(PYTHON), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=log, text=True, encoding='utf-8', env=env, creationflags=flags)
        log.close()
        import queue
        lines = queue.Queue(); process = self.process
        def read():
            for line in process.stdout: lines.put(line)
            lines.put('')
        threading.Thread(target=read, daemon=True, name='xtts-oku').start()
        self.lines = lines
        first = self._line(180)
        if not first or not json.loads(first).get('ready'): self.stop(); raise RuntimeError('XTTS işçisi başlatılamadı.')
    def _line(self, timeout):
        import queue
        try: return self.lines.get(timeout=timeout)
        except queue.Empty:
            self.stop(); raise RuntimeError(f'XTTS işçisi {timeout:.0f} saniyede yanıt vermedi.') from None
    def run(self, request):
        with self.lock:
            if self.process is None or self.process.poll() is not None: self._start()
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n'); self.process.stdin.flush()
            line = self._line(240)
            if not line: self.stop(); raise RuntimeError('XTTS işçisi beklenmedik biçimde kapandı (data/logs/xtts-worker.log).')
            return json.loads(line)
    def run_stream(self, request, on_chunk):
        """Parçaları geldikçe on_chunk(float32, 24000) ile verir. on_chunk hata verirse (ör. bölüm iptal)
        protokol bozulmasın diye kalan satırlar yine okunup atılır."""
        import base64
        import numpy as np
        failed = None
        with self.lock:
            if self.process is None or self.process.poll() is not None: self._start()
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n'); self.process.stdin.flush()
            ilk = True
            while True:
                # B11 (12 Kasım): takılan üretim 120 s kilitlemesin. İlk parça model yükleme payıyla 60 s,
                # sonraki parçalar arası 15 s; aşılırsa işçi kapatılır, app aynı sesle bir kez yeniden dener.
                line = self._line(60 if ilk else 15)
                ilk = False
                if not line: self.stop(); raise RuntimeError('XTTS işçisi beklenmedik biçimde kapandı (data/logs/xtts-worker.log).')
                message = json.loads(line)
                if 'chunk' in message:
                    if failed is None:
                        try:
                            pcm = np.frombuffer(base64.b64decode(message['chunk']), dtype='<i2').astype(np.float32) / 32768.0
                            on_chunk(pcm, 24000)
                        except Exception as error:
                            failed = error
                    continue
                if not message.get('ok'): raise RuntimeError('XTTS akış hatası: ' + str(message.get('error')))
                if failed is not None: raise failed
                return message
    def stop(self):
        if self.process and self.process.poll() is None: self.process.kill()
        self.process = None

_worker = _Worker()
import atexit; atexit.register(_worker.stop)

# 12 Kasım 18:25 (is_148/149): XTTS bu kartta ~1,0x → sık söylenen kısa cümleler ("Müzik açılıyor.", "Anlayamadım, …",
# "Tamam, beş dakikalık sayaç kuruldu.") karakter sesiyle bir kez üretilip saklanır, sonra anında ve takılmadan çalınır.
# Yer: data/onbellek/ses/<ses anahtarı>/<metin özeti>.npy; yalnız ≤ 48 karakter, düzgün biten üretim; en çok 400 dosya/ses.
ONBELLEK_EN_UZUN = 48
ONBELLEK_EN_COK = 400

def _onbellek_yolu(text, voice):
    import hashlib, re as _re
    from app_paths import data_dir
    anahtar = hashlib.sha1(' '.join(str(text).split()).casefold().encode('utf-8')).hexdigest()[:16]
    klasor = _re.sub(r'[^\w.-]+', '_', cozumle(voice)) + ('' if HIZ == 1.0 else f'@{HIZ:g}')  # hız değişince eski kayıt kullanılmaz
    return data_dir() / 'onbellek' / 'ses' / klasor / f'{anahtar}.npy'

def stream(text, voice, on_chunk):
    """B07 akışlı üretim: cümle bitmeden ilk parça (~0,5 s) çalara gider. Kısa cümle önbellekteyse anında verilir."""
    import numpy as np
    text = str(text)
    kisa = len(text) <= ONBELLEK_EN_UZUN
    yol = _onbellek_yolu(text, voice) if kisa else None
    if yol is not None and yol.is_file():
        try:
            x = np.load(yol, allow_pickle=False).astype('float32')
            if x.size:
                on_chunk(x, 24000); return {'ok': True, 'done': True, 'sr': 24000, 'onbellek': True}
        except Exception:
            pass
    request = _request_for(voice)
    request.update(text=text, lang='tr', stream=True)
    if yol is None:
        return _worker.run_stream(request, on_chunk)
    parcalar = []
    def topla(x, sr=24000):
        parcalar.append(np.asarray(x, dtype='float32').reshape(-1).copy()); return on_chunk(x, sr)
    sonuc = _worker.run_stream(request, topla)
    try:
        if parcalar:
            yol.parent.mkdir(parents=True, exist_ok=True)
            np.save(yol, np.concatenate(parcalar), allow_pickle=False)
            eski = sorted(yol.parent.glob('*.npy'), key=lambda p: p.stat().st_mtime)
            for f in eski[:-ONBELLEK_EN_COK]: f.unlink(missing_ok=True)
    except OSError:
        pass
    return sonuc

def warm(voice, data_dir):
    """Açılışta arka planda: modeli ve referans gizil değerlerini yükler, kısa bir cümle üretir.
    Canlı konuşma akışlı yoldan (inference_stream) gider; o yolun GPU çekirdekleri ilk çağrıda derlenir
    ve ilk cevap 4-6 s gecikip takılıyordu (9 Kasım canlı test). Bu yüzden akış yolu da ısıtılır."""
    result = synthesize('Merhaba.', data_dir, voice)
    for metin in ('Merhaba!', 'Bugün seninle konuşmak gerçekten çok güzel, nasıl gidiyor?'):
        try:
            stream(metin, voice, lambda pcm, sr: None)
        except Exception:
            break
    return result

def synthesize(text, data_dir, voice='xtts:varsayilan'):
    request = _request_for(voice)
    with tempfile.TemporaryDirectory(prefix='xtts-', dir=str(data_dir)) as tmp:
        target = Path(tmp) / 'output.wav'
        request.update(text=str(text), lang='tr', out=str(target))
        result = _worker.run(request)
        if not result.get('ok') or not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError('XTTS ses sentezi başarısız: ' + str(result.get('error', 'boş çıktı')))
        return target.read_bytes()
