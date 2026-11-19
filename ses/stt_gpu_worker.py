"""B06: kalıcı ekran kartı ses tanıma işçisi — Whisper large-v3-turbo, runtime/xtts-gpu (ROCm torch), fp16.

stdout yalnız JSON satırı taşır. İstek: {"path": "<16 kHz float32 .npy>"} -> {"text": "...", "ms": 123}
Hazır olunca: {"ready": true, "ms": yükleme}. Hata: {"error": "..."} (işçi açık kalır).
İstemci: stt_worker.transcribe (GPU işçisi önce, olmazsa eski CPU Whisper small).
"""
import json, os, sys, time
protocol = sys.stdout
sys.stdout = sys.stderr
os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
from pathlib import Path
import numpy as np, torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

MODEL = Path(__file__).resolve().parents[1] / "models" / "whisper-large-v3-turbo"
# F1b: AMD (ROCm) ve NVIDIA (CUDA) torch.cuda, Intel Arc torch.xpu kullanır
DEV = "xpu" if not torch.cuda.is_available() and hasattr(torch, "xpu") and torch.xpu.is_available() else "cuda"


def yaz(proc, model, x):
    f = proc(x, sampling_rate=16000, return_tensors="pt").input_features.to(DEV, torch.float16)
    with torch.inference_mode():
        ids = model.generate(f, language="tr", task="transcribe", max_new_tokens=160)
    return proc.batch_decode(ids, skip_special_tokens=True)[0].strip()


def main():
    t = time.perf_counter()
    proc = WhisperProcessor.from_pretrained(MODEL)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL, torch_dtype=torch.float16).to(DEV).eval()
    yaz(proc, model, np.zeros(16000, dtype="float32"))  # GPU çekirdeklerini ilk canlı sözden önce derle
    protocol.write(json.dumps({"ready": True, "ms": round((time.perf_counter() - t) * 1000)}) + "\n"); protocol.flush()
    for line in sys.stdin:
        try:
            istek = json.loads(line)
            x = np.load(istek["path"], allow_pickle=False).astype("float32")
            t = time.perf_counter()
            cevap = {"text": yaz(proc, model, x), "ms": round((time.perf_counter() - t) * 1000)}
        except Exception as e:
            cevap = {"error": f"{type(e).__name__}: {e}"[:400]}
        protocol.write(json.dumps(cevap, ensure_ascii=False) + "\n"); protocol.flush()


if __name__ == "__main__":
    main()
