"""Yumi kod klasörleri (12 Kasım, DUZEN paket 3). Kök .py dosyaları konularına göre klasörlerde; içe aktarma
adları değişmedi (`import skins`), bu modül klasörleri sys.path'e ve alt süreçler için PYTHONPATH'e ekler.
Kullanan: launch.py (ilk satır), live_voice/run_live.py, ses/wake_worker.py; .venv'de yumi_yollar.pth (setup_local.py yazar)."""
import os, sys
from pathlib import Path
KOK = Path(__file__).resolve().parent
KLASORLER = ("cekirdek", "arayuz", "ses", "karakter", "goruntu", "hareket", "sahne")

def yollar():
    return [KOK / k for k in KLASORLER] + [KOK]

def kur():
    for yol in reversed([str(y) for y in yollar()]):
        if yol not in sys.path: sys.path.insert(0, yol)
    mevcut = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    os.environ["PYTHONPATH"] = os.pathsep.join([str(y) for y in yollar()] + [p for p in mevcut if p not in {str(y) for y in yollar()}])

kur()
