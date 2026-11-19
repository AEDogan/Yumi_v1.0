"""Single instance launcher with crash logs for windowless startup."""
import yumi_yollar  # 12 Kasım: kod klasörleri sys.path + PYTHONPATH (alt süreçler için)
import ctypes,logging,os,sys
from ctypes import wintypes
from pathlib import Path
from app_paths import ROOT as root,APP_ID,data_dir
try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # 17 Kasım: görev çubuğunda Yumi kısayoluyla aynı simge ve grup
except Exception:pass
logs=data_dir()
logs.mkdir(parents=True,exist_ok=True)
logging.basicConfig(filename=logs/'yumi.log',level=logging.WARNING,format='%(asctime)s %(levelname)s %(message)s')
# app.main owns the only QApplication and handles local-socket activation.
ctypes.windll.kernel32.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
ctypes.windll.kernel32.CreateMutexW.restype=wintypes.HANDLE
ctypes.windll.kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\'+APP_ID)
baska_kopya=ctypes.windll.kernel32.GetLastError()==183  # kilit zaten varsa başka Yumi açık/açılıyor
def _paket_arg():
    """F1b: .yumipaket çift tık → "launch.py <dosya>"."""
    return next((a for a in sys.argv[1:] if a.lower().endswith('.yumipaket')),None)
def _acik_yumiye_gonder(yol):
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket
        _uyg=QCoreApplication.instance() or QCoreApplication([])
        s=QLocalSocket();s.connectToServer(APP_ID)
        if not s.waitForConnected(3000):return False
        s.write(('paket\t'+yol+'\n').encode('utf-8'));s.waitForBytesWritten(3000);s.disconnectFromServer();return True
    except Exception:
        logging.exception("Paket açık Yumi'ye gönderilemedi");return False
if baska_kopya and _paket_arg() and _acik_yumiye_gonder(_paket_arg()):
    sys.exit(0)
if baska_kopya:
    # Existing instance holds the mutex. Restore existing window:
    hwnd = ctypes.windll.user32.FindWindowW(None, 'Yumi · 3D Masaüstü Asistanı')
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    hwnd_char = ctypes.windll.user32.FindWindowW(None, 'Yumi · Masaüstü karakteri')
    if hwnd_char:
        ctypes.windll.user32.ShowWindow(hwnd_char, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd_char)
        sys.exit(0)
try:
    from startup_runtime import prepare_audio_runtime,guard_startup
    guard_startup(str(logs))
    from resource_guard import MemoryJob,GiB,require_capacity
    from resource_guard import pressure,sahipsiz_iscileri_kapat
    if not baska_kopya and pressure(extra_bytes=4*GiB):  # 12 Kasım: önceki Yumi'den asılı kalan ses işçileri belleği tutuyorsa kapat, sonra yeniden dene
        kapatilan=sahipsiz_iscileri_kapat(root)
        if kapatilan:
            import time;logging.getLogger("yumi.startup").warning("Sahipsiz ses iscileri kapatildi: %s",kapatilan);time.sleep(2)
    require_capacity(4*GiB)
    memory_job=MemoryJob(16*GiB,8*GiB)
    memory_job.attach()
    try:
        from resource_guard import hizli_surec;hizli_surec(oncelik=0)  # B10: ana süreç (ses çalar, akış) kısıtlanmasın; öncelik değişmez
    except Exception:pass
    logging.getLogger("yumi.startup").info("Memory limits attached; preparing audio")
    prepare_audio_runtime()
    logging.getLogger("yumi.startup").info("Audio ready; importing desktop application")
    from app import main
    sys.exit(main())
except Exception:
    logging.exception('Yumi startup failure')
    ctypes.windll.user32.MessageBoxW(None,f'Yumi açılamadı. Hata kaydı: {logs / "yumi.log"}','Yumi',16)
finally:
    if mutex:ctypes.windll.kernel32.CloseHandle(mutex)
