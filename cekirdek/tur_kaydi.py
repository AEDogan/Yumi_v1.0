"""B10: konuşma turu kaydı. Her tur (sesli ya da yazılı) olay olay, zaman damgasıyla yerel JSONL'e yazılır.

Dosya: data/konusma_kaydi/AAAA-AA-GG.jsonl (git dışı, yalnız bu bilgisayarda). Satır:
  {"tur": "20261109-223501-3", "zaman": ISO, "ms": turun başından (sesli turda konuşmanın bittiği andan) geçen ms,
   "olay": "stt" | "niyet" | "istem" | "cevap" | "akis" | ..., ...olaya özel alanlar}
Amaç: gecikmenin nereye gittiğini ölçmek ve gerçek cümlelerle yerel AI'ı (niyet modeli) iyileştirmek.
Kayıt hiçbir zaman Yumi'yi durdurmaz: her hata yutulur.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import threading
import time
from pathlib import Path

_kilit = threading.Lock()
_sayac = itertools.count(1)
_klasor: Path | None = None
_tur: str | None = None
_baslangic: dict[str, float] = {}


def baslat(veri_klasoru) -> None:
    global _klasor
    _klasor = Path(veri_klasoru) / "konusma_kaydi"


def yeni(kaynak: str, t0: float | None = None, **veri) -> str:
    """Yeni tur. t0: perf_counter cinsinden başlangıç (sesli turda konuşmanın bittiği an)."""
    global _tur
    tur = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{next(_sayac)}"
    with _kilit:
        _baslangic[tur] = t0 if t0 is not None else time.perf_counter()
        for eski in list(_baslangic)[:-20]:  # bellekte yalnız son turlar
            _baslangic.pop(eski, None)
        _tur = tur
    olay("tur_basladi", tur=tur, kaynak=kaynak, **veri)
    return tur


def simdiki() -> str | None:
    return _tur


def olay(ad: str, tur: str | None = None, **veri) -> None:
    if _klasor is None:
        return
    tur = tur or _tur
    if tur is None:
        return
    t0 = _baslangic.get(tur)
    kayit = {"tur": tur, "zaman": dt.datetime.now().isoformat(timespec="milliseconds"),
             "ms": round((time.perf_counter() - t0) * 1000) if t0 is not None else None, "olay": ad, **veri}
    try:
        satir = json.dumps(kayit, ensure_ascii=False, default=str)
        with _kilit:
            _klasor.mkdir(parents=True, exist_ok=True)
            with (_klasor / f"{dt.date.today():%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
                f.write(satir + "\n")
    except Exception:
        pass
