"""YouTube reklam atlama eklentisinin (`eklenti/reklam_atla`) bildirimlerini dinler ve günlüğe yazar (12 Kasım).

Eklenti 127.0.0.1:8766/reklam-atlandi?olay=...&... adresine istek atar; önceden Yumi bu portu dinlemiyordu, bu yüzden
"Atla" çalışıp çalışmadığı görülemiyordu. Günlük: data/logs/reklam-atla.log (yalnız olay, buton sınıfı, site; adres yok).
Yalnız 127.0.0.1; port doluysa sessizce vazgeçer.
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KOK = Path(__file__).resolve().parents[1]
from app_paths import data_dir as _data_dir  # G-A2: günlük kullanıcı veri alanında
GUNLUK = _data_dir() / "logs" / "reklam-atla.log"
_sunucu = None


def yaz(satir: str, gunluk: Path = GUNLUK) -> None:
    gunluk.parent.mkdir(parents=True, exist_ok=True)
    with gunluk.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + satir + "\n")


class _Isleyici(BaseHTTPRequestHandler):
    gunluk = GUNLUK

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/reklam-atlandi":
            q = {k: v[0][:160] for k, v in parse_qs(u.query).items() if k in ("olay", "yol", "deneme", "sinif", "butonlar", "site")}
            yaz(" ".join(f"{k}={v!r}" for k, v in q.items()) or f"(bos bildirim; eski eklenti arka plani?) {u.query[:80]!r}", self.gunluk)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *_):
        pass


def baslat(gunluk: Path = GUNLUK) -> bool:
    global _sunucu
    if _sunucu is not None:
        return True
    try:
        _Isleyici.gunluk = gunluk
        _sunucu = ThreadingHTTPServer(("127.0.0.1", 8766), _Isleyici)
    except OSError:
        return False
    threading.Thread(target=_sunucu.serve_forever, daemon=True, name="reklam-dinleyici").start()
    return True


def durdur() -> None:
    global _sunucu
    if _sunucu is not None:
        _sunucu.shutdown(); _sunucu.server_close(); _sunucu = None
