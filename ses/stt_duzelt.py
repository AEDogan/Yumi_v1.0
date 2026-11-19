"""B06/B11 (12 Kasım): ses tanıma (Whisper) çıktısının son düzeltmesi.

1) Uydurma (hallucination) atma: Whisper sessizlik/gürültüde eğitim verisindeki altyazı kalıplarını yazar
   ("Altyazı M.K.", "İzlediğiniz için teşekkürler" …). 12 Kasım 13:18 kaydında "Altyazı M.K." Gemini'ye soru gitti.
   Kalıp metnin tamamıysa metin boşalır; sonuna eklenmişse yalnız o kısım atılır.
2) Sık yanlış duyulan sözcükler: "fıkra" → "fikre/fikra" (11 Kasım B11: Gemini fıkra yerine fikir anlattı).
"""
import re

_UYDURMA = [
    r"alt ?yaz[ıi](?:\s*:?\s*m\.?\s*k\.?)?",
    r"alt ?yaz[ıi]lar?\s+.{0,40}taraf[ıi]ndan.{0,30}",
    r"izledi[gğ]iniz i[cç]in te[sş]ekk[uü]r(?:ler| ederim| ederiz)?",
    r"abone olmay[ıi] unutmay[ıi]n(?:[ıi]z)?",
    r"bir sonraki videoda g[oö]r[uü][sş]mek [uü]zere",
    r"videoyu be[gğ]enmeyi unutmay[ıi]n",
    r"[\[(]\s*m[uü]zik\s*[\])]",
    r"[\[(]\s*alk[ıi][sş]lar?\s*[\])]",
]
_TAM = re.compile(r"^\s*(?:" + "|".join(_UYDURMA) + r")[\s.!…]*$", re.I)
_SON = re.compile(r"[\s.,!…]*(?:" + "|".join(_UYDURMA[:6]) + r")[\s.!…]*$", re.I)

_DUZELT = [
    (re.compile(r"\bfik(?:re|ra)(?=\s+(?:anlat|söyle|soyle|patlat))", re.I), "fıkra"),
    (re.compile(r"\bfik(?:re|ra)(?:y[ıi])?\s+anlats", re.I), "fıkra anlats"),
    (re.compile(r"\bbir fikre\b", re.I), "bir fıkra"),
]


def uydurma_mi(metin: str) -> bool:
    return bool(_TAM.match(metin or ""))


def duzelt(metin: str) -> str:
    metin = (metin or "").strip()
    if not metin or uydurma_mi(metin):
        return ""
    metin = _SON.sub("", metin).strip() or metin
    for kalip, yerine in _DUZELT:
        metin = kalip.sub(yerine, metin)
    return metin
