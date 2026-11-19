"""B08 çalışma zamanı: niyet modeli (models/niyet/niyet.onnx) işlemcide, internetsiz. Cümle başına ~4 ms.
anla(metin) -> {"niyet", "guven", "parcalar": [{"tur","bas","son","metin"}]} ya da model hazır değilse None."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .niyet.ortak import Etiketler, bio_coz

KOK = Path(__file__).resolve().parent

MODEL = KOK.parent / "models" / "niyet"


class Anlayici:
    def __init__(self, klasor: Path = MODEL, is_parcacigi=2):
        self.klasor = Path(klasor)
        self.is_parcacigi = is_parcacigi
        self.oturum = self.tok = self.et = None
        self.hata = None
        self._kilit = threading.Lock()
        self._hazir = threading.Event()

    def arka_planda_yukle(self):
        threading.Thread(target=self.yukle, name="YumiNiyetYukle", daemon=True).start()

    def yukle(self):
        with self._kilit:
            if self._hazir.is_set():
                return True
            try:
                import numpy as np  # noqa: F401
                import onnxruntime as ort
                from tokenizers import BertWordPieceTokenizer
                ayar = json.loads((self.klasor / "egitilmis" / "ayar.json").read_text(encoding="utf-8"))
                self.et = Etiketler(ayar["niyetler"], ayar["parcalar"])
                taban = Path(str(ayar.get("taban", "distilberturk"))).name
                adaylar = [self.klasor / taban / "vocab.txt", MODEL / taban / "vocab.txt", MODEL / "distilberturk" / "vocab.txt"]
                sozluk = next(y for y in adaylar if y.is_file())  # aday modeller (models/niyet/aday_*) kendi tabanının sözlüğünü kullanır
                self.tok = BertWordPieceTokenizer(str(sozluk), lowercase=False, strip_accents=False)
                self.tok.enable_truncation(int(ayar.get("maxlen", 48)))
                se = ort.SessionOptions()
                se.intra_op_num_threads = self.is_parcacigi  # ses/3D için işlemciyi boğmasın
                se.inter_op_num_threads = 1
                self.oturum = ort.InferenceSession(str(self.klasor / "niyet.onnx"), se, providers=["CPUExecutionProvider"])
                self._hazir.set()
                return True
            except Exception as e:  # model yoksa Yumi eski yoldan devam eder
                self.hata = f"{type(e).__name__}: {e}"
                return False

    @property
    def hazir(self):
        return self._hazir.is_set()

    def anla(self, metin: str):
        if not self.hazir or not metin.strip():
            return None
        import numpy as np
        # B10: eğitim verisi çoğunlukla küçük harf ve noktalamasız; Whisper ise "Sonraki gün?" biçiminde yazıyor.
        # PC ölçümü (is_032): Whisper biçiminde zor test %99,1 -> %93,6; küçük harf + sondaki noktalamasız %99,1.
        # Uzunluk korunursa parça konumları aynı kalır (yalnız sondan kırpılır); korunmazsa ham metin kullanılır.
        from .sayi_zaman import kucuk
        girdi = kucuk(metin)
        if len(girdi) != len(metin):
            girdi = metin
        girdi = girdi.rstrip(" .?!,;:…")
        e = self.tok.encode(girdi or metin)
        ids = np.array([e.ids], dtype=np.int64)
        niyet, parca = self.oturum.run(["niyet", "parca"], {"input_ids": ids, "attention_mask": np.ones_like(ids)})
        x = niyet[0] - niyet[0].max()
        p = np.exp(x) / np.exp(x).sum()
        k = int(p.argmax())
        return {"niyet": self.et.niyetler[k], "guven": float(p[k]), "parcalar": bio_coz(e.offsets, parca[0].argmax(-1).tolist(), self.et, metin)}
