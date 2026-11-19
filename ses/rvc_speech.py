"""Konuşma metnini seslendirme bölümlerine ayırma.

12 Kasım (DUZEN paket 3 devamı): RVC/Applio yolu (OneDrive 'voice models', yerel Applio klasörü,
models/rvc, ONNX RVC) kaldırıldı; Yumi yalnız XTTS kullanır. Modül adı geri uyumluluk için korunur.
Eski tam hal: work/yedek-2026-11-12/kod4/rvc_speech.py
"""
import re, textwrap


def speech_parts(text):
    chunks=[]
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',text.strip()):
        chunks.extend(textwrap.wrap(sentence,width=120,break_long_words=True,break_on_hyphens=False))
    return chunks
