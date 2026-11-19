"""Persistent STT process, isolated from the desktop process memory limit."""
import atexit,json,os,queue,subprocess,sys,tempfile,threading
from pathlib import Path
_lock=threading.Lock()
_process=None
_results=None

def close():
    global _process
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:_process.wait(timeout=5)
        except subprocess.TimeoutExpired:_process.kill()
    _process=None

atexit.register(close)

ROOT=Path(__file__).resolve().parents[1]
GPU_PYTHON=ROOT/'runtime'/'xtts-gpu'/'Scripts'/'python.exe'
GPU_MODEL=ROOT/'models'/'whisper-large-v3-turbo'/'model.safetensors'
_gpu_lock=threading.Lock();_gpu=None;_gpu_lines=None;_gpu_failed=False
son_motor='cpu-small'  # tur kaydı için: hangi tanıyıcı kullanıldı

def gpu_ready():
    return GPU_PYTHON.is_file() and GPU_MODEL.is_file() and not _gpu_failed

def _gpu_start():
    """B06: Whisper large-v3-turbo ekran kartı işçisi (stt_gpu_worker.py). Model yükleme + ısınma ~10-20 s."""
    global _gpu,_gpu_lines
    env=os.environ.copy();env.update(PYTHONIOENCODING='utf-8',MIOPEN_FIND_MODE='FAST')
    try:from resource_guard import popen_worker as start
    except Exception:start=subprocess.Popen
    from app_paths import data_dir;(data_dir()/'logs').mkdir(parents=True,exist_ok=True)
    log=(data_dir()/'logs'/'stt-gpu-worker.log').open('w',encoding='utf-8')  # 12 Kasım: work/ yerine data/logs
    process=start([str(GPU_PYTHON),'-u','-B',str(ROOT/'ses'/'stt_gpu_worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    log.close()
    lines=queue.Queue()
    def read():
        for line in process.stdout:lines.put(line)
        lines.put('')
    threading.Thread(target=read,daemon=True,name='stt-gpu-oku').start()
    first=lines.get(timeout=180)
    if not first or not json.loads(first).get('ready'):
        process.kill();raise RuntimeError('GPU ses tanıma işçisi başlatılamadı (work/stt-gpu-worker.log).')
    _gpu,_gpu_lines=process,lines

def warm_gpu():
    """Açılışta arka planda çağrılır; ilk sözün model yüklemesini beklememesi için."""
    global _gpu_failed
    if not gpu_ready():return False
    with _gpu_lock:
        try:
            if _gpu is None or _gpu.poll() is not None:_gpu_start()
            return True
        except Exception:
            _gpu_failed=True;return False

def _gpu_transcribe(samples):
    global _gpu_failed,_gpu,son_motor
    import numpy as np
    with _gpu_lock,tempfile.TemporaryDirectory(prefix='yumi-stt-gpu-') as tmp:
        if _gpu is None or _gpu.poll() is not None:_gpu_start()
        path=Path(tmp)/'input.npy';np.save(path,np.asarray(samples,dtype='float32'),allow_pickle=False)
        _gpu.stdin.write(json.dumps({'path':str(path)})+'\n');_gpu.stdin.flush()
        try:line=_gpu_lines.get(timeout=30)
        except queue.Empty:
            _gpu.kill();_gpu=None;raise RuntimeError('GPU ses tanıma 30 saniyede yanıt vermedi.') from None
        if not line:_gpu=None;raise RuntimeError('GPU ses tanıma işçisi kapandı.')
        result=json.loads(line)
        if 'error' in result:raise RuntimeError(result['error'])
        son_motor='gpu-large-v3-turbo';return result['text'].strip().strip('\'"“”‘’`').strip()  # Whisper bazen cümleyi tırnağa alıyor

def transcribe(samples,wake_name):
    global _process,_results,_gpu_failed,son_motor
    if gpu_ready():
        try:return _gpu_transcribe(samples)
        except Exception as error:
            __import__('logging').getLogger('yumi.stt').warning('GPU ses tanıma başarısız, CPU Whisper small kullanılacak: %s',error)
            _gpu_failed=True
    son_motor='cpu-small'
    import numpy as np
    with _lock,tempfile.TemporaryDirectory(prefix='yumi-stt-') as tmp:
        if _process is None or _process.poll() is not None:
            env=os.environ.copy()
            env.update(PYTHONIOENCODING='utf-8',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
            executable=Path(sys.executable).with_name('python.exe')
            process=subprocess.Popen([str(executable),'-u','-B',str(Path(__file__).resolve()),'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            results=queue.Queue();_process=process;_results=results
            try:
                from resource_guard import hizli_surec;hizli_surec(process.pid)  # B10
            except Exception:pass
            def read():
                for line in process.stdout:
                    try:results.put(json.loads(line))
                    except ValueError:pass
                results.put({'error':'Metne çevirme süreci kapandı.'})
            threading.Thread(target=read,daemon=True).start()
        path=Path(tmp)/'input.npy';np.save(path,samples,allow_pickle=False)
        try:
            _process.stdin.write(json.dumps({'path':str(path),'name':wake_name})+'\n');_process.stdin.flush()
            result=_results.get(timeout=90)
        except (queue.Empty,OSError):
            close();raise RuntimeError('Metne çevirme 90 saniyede tamamlanmadı.') from None
        if 'error' in result:raise RuntimeError('Mikrofon metne çevirme: '+result['error'])
        return result['text']

if __name__=='__main__':
    protocol=sys.stdout;sys.stdout=sys.stderr
    import numpy as np
    from backend import _local_transcribe
    for line in sys.stdin:
        try:
            request=json.loads(line)
            result={'text':_local_transcribe(np.load(request['path'],allow_pickle=False),request['name'])}
        except Exception as error:result={'error':str(error)}
        protocol.write(json.dumps(result,ensure_ascii=False)+'\n');protocol.flush()
