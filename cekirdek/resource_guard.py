"""Windows commit reserve and hard limits for Yumi-owned processes only."""
import ctypes,os
from ctypes import wintypes as w
GiB=1024**3
class Performance(ctypes.Structure):
    _fields_=[('cb',w.DWORD)]+[(n,ctypes.c_size_t) for n in ['CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable','SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize']]+[(n,w.DWORD) for n in ['HandleCount','ProcessCount','ThreadCount']]
class Basic(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
class IO(ctypes.Structure):
    _fields_=[(n,ctypes.c_ulonglong) for n in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
class Extended(ctypes.Structure):
    _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO)]+[(n,ctypes.c_size_t) for n in ['ProcessMemoryLimit','JobMemoryLimit','PeakProcessMemoryUsed','PeakJobMemoryUsed']]
def memory_status():
    if os.name!='nt':raise RuntimeError('Bellek koruması bu sistemde doğrulanmadı.')
    p=Performance();p.cb=ctypes.sizeof(p)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(p),p.cb):raise ctypes.WinError()
    return {'commit_free':(p.CommitLimit-p.CommitTotal)*p.PageSize,'commit_limit':p.CommitLimit*p.PageSize,'physical_free':p.PhysicalAvailable*p.PageSize}
def pressure(status=None,extra_bytes=0):
    s=memory_status() if status is None else status
    # 17 Kasım: commit payı 8 GiB sabitti; ROCm işçileri (STT 5,9 + XTTS 8,5 GB commit, ama yalnız ~4 GB gerçek RAM) boş commit'i
    # 7 GB'a indirince fiziksel RAM 17 GB boşken bile ses açılmıyordu. Fiziksel bellek boluysa commit payı 3 GiB'a iner
    # (sayfa dosyası zaten sistem yönetimli büyür); fiziksel de azsa eski 8 GiB / %10 payı geçerli.
    physical_ok=s['physical_free']-extra_bytes>=6*GiB
    reserve=3*GiB if physical_ok else max(8*GiB,int(s['commit_limit']*.10))
    return s['commit_free']-extra_bytes<reserve or s['physical_free']-extra_bytes<2*GiB
def require_capacity(extra_bytes=0):
    if pressure(extra_bytes=extra_bytes):raise RuntimeError('Diğer programlara bellek bırakmak için bu işlem başlatılmadı. Kullanılabilir bellek azaldı; Gemini metin sohbetini kullanabilirsin.')
def sahipsiz_iscileri_kapat(root):
    """12 Kasım: önceki Yumi zorla kapanınca ROCm ses işçileri (xtts_worker, stt_gpu_worker) asılı kalıp ~11 GB
    commit tutuyor ve Yumi bir daha açılmıyordu. Yalnız launch çağırır, o da tek-kopya kilidini aldıktan sonra:
    o anda başka Yumi yoktur, bu klasörün ses/*_worker.py süreçleri sahipsizdir. Döner: kapatılan PID listesi."""
    import subprocess
    if os.name!='nt':return []
    ses=str(root/'ses').lower()
    komut=("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
           "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        r=subprocess.run(['powershell','-NoProfile','-Command',komut],capture_output=True,text=True,timeout=20,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except Exception:return []
    kapatilan=[]
    for satir in r.stdout.splitlines():
        pid,_,cmd=satir.partition('\t');c=cmd.lower()
        if ses in c and ('xtts_worker.py' in c or 'stt_gpu_worker.py' in c) and pid.strip().isdigit():
            try:
                subprocess.run(['taskkill','/F','/PID',pid.strip()],capture_output=True,timeout=10,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));kapatilan.append(int(pid))
            except Exception:pass
    return kapatilan
class MemoryJob:
    def __init__(self,total_bytes=6*GiB,process_bytes=4*GiB):
        if os.name!='nt':raise RuntimeError('Yerel bellek sınırı bu sistemde doğrulanmadı.')
        k=ctypes.WinDLL('kernel32',use_last_error=True);self.k=k
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
        k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];k.SetInformationJobObject.restype=w.BOOL
        k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.AssignProcessToJobObject.restype=w.BOOL
        k.GetCurrentProcess.restype=w.HANDLE
        k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
        k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
        self.handle=k.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        info=Extended();info.BasicLimitInformation.LimitFlags=0x100|0x200|0x2000|0x400|0x800  # 0x800: ağır ses işçileri kendi işine ayrılabilir
        info.ProcessMemoryLimit=process_bytes;info.JobMemoryLimit=total_bytes
        if not k.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            error=ctypes.get_last_error();self.close();raise ctypes.WinError(error)
    def attach(self,pid=None):
        process=self.k.GetCurrentProcess() if pid is None else self.k.OpenProcess(0x100|0x1,False,pid)
        if not process:raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.k.AssignProcessToJobObject(self.handle,process):raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if pid is not None:self.k.CloseHandle(process)
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None


class _PowerThrottling(ctypes.Structure):
    _fields_=[('Version',w.ULONG),('ControlMask',w.ULONG),('StateMask',w.ULONG)]
ABOVE_NORMAL_PRIORITY_CLASS=0x8000
def hizli_surec(pid=None,oncelik=ABOVE_NORMAL_PRIORITY_CLASS):
    """B10: Windows 11 penceresiz arka plan süreçlerini 'verimlilik moduna' alıp (EcoQoS) yavaş çekirdeklere
    atabiliyor; XTTS'in kelime kelime üretim döngüsü işlemciye bağlı olduğundan bu, Yumi içinde ilk sesi 8-11 s'ye
    çıkarıyordu (Yumi dışında 0,3 s). Hız kısıtlamasını kapatır ve önceliği 'normalin üstü' yapar. Hata olursa sessiz.
    Döner: {'kisitlama_kapali': bool, 'oncelik': bool}."""
    sonuc={'kisitlama_kapali':False,'oncelik':False}
    if os.name!='nt':return sonuc
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.SetProcessInformation.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];k.SetProcessInformation.restype=w.BOOL
    k.SetPriorityClass.argtypes=[w.HANDLE,w.DWORD];k.SetPriorityClass.restype=w.BOOL
    k.CloseHandle.argtypes=[w.HANDLE]
    h=k.GetCurrentProcess() if pid is None else k.OpenProcess(0x0200|0x1000,False,pid)  # SET_INFORMATION|QUERY_LIMITED
    if not h:return sonuc
    try:
        info=_PowerThrottling(1,0x1|0x4,0)  # EXECUTION_SPEED + IGNORE_TIMER_RESOLUTION denetimde, durum 0 = kısıtlama yok
        sonuc['kisitlama_kapali']=bool(k.SetProcessInformation(h,4,ctypes.byref(info),ctypes.sizeof(info)))  # 4 = ProcessPowerThrottling
        if oncelik:sonuc['oncelik']=bool(k.SetPriorityClass(h,oncelik))
    finally:
        if pid is not None:k.CloseHandle(h)
    return sonuc
CREATE_BREAKAWAY_FROM_JOB=0x01000000
_worker_job=None
def popen_worker(args,total_bytes=20*GiB,process_bytes=14*GiB,**kw):
    """B07: GPU ses işçilerini (XTTS ROCm, ONNX DirectML) Yumi'nin 16 GB'lık ortak işinden ayırıp kendi
    sınırlı işine koyar. Ortak işte kalınca model yüklerken sınıra çarpıp çöküyor, önizlemenin belleğini de
    tüketiyordu. Kendi işi KILL_ON_JOB_CLOSE: Yumi kapanınca işçiler de kapanır."""
    import subprocess
    global _worker_job
    flags=kw.pop('creationflags',0)
    if os.name!='nt':return subprocess.Popen(args,creationflags=flags,**kw)
    try:process=subprocess.Popen(args,creationflags=flags|CREATE_BREAKAWAY_FROM_JOB,**kw)
    except OSError:process=subprocess.Popen(args,creationflags=flags,**kw)  # eski başlatma: ayrılma izni yok
    try:
        if _worker_job is None:_worker_job=MemoryJob(total_bytes,process_bytes)
        _worker_job.attach(process.pid)
    except Exception:
        pass
    try:hizli_surec(process.pid)  # B10: ses işçisi verimlilik moduna düşmesin
    except Exception:pass
    return process
