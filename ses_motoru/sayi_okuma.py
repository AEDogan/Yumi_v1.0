"""B10: seslendirmeden önce rakamları Türkçe yazıya çevirir.

Sorun (kullanıcı, 9 Kasım): "yağış olasılığı yüzde 98." -> ses modeli cümle sonu noktasını sıra sayısı sanıp
"doksan sekizinci" okuyordu. Kural: rakamdan sonra nokta + boşluk + KÜÇÜK harf -> sıra sayısı ("3. kat" -> "üçüncü kat");
nokta cümle sonundaysa (metin sonu ya da büyük harf) -> asıl sayı ("98." -> "doksan sekiz.").
Ayrıca: %98 -> yüzde doksan sekiz, 12,5 -> on iki virgül beş, 1.250 -> bin iki yüz elli, 18:30 -> on sekiz otuz, -3 -> eksi üç.
"""
from __future__ import annotations

import re

BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
BUYUK = [(10 ** 12, "trilyon"), (10 ** 9, "milyar"), (10 ** 6, "milyon"), (1000, "bin")]
SIRA = {"bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü", "beş": "beşinci", "altı": "altıncı",
        "yedi": "yedinci", "sekiz": "sekizinci", "dokuz": "dokuzuncu", "on": "onuncu", "yirmi": "yirminci",
        "otuz": "otuzuncu", "kırk": "kırkıncı", "elli": "ellinci", "altmış": "altmışıncı", "yetmiş": "yetmişinci",
        "seksen": "sekseninci", "doksan": "doksanıncı", "yüz": "yüzüncü", "bin": "bininci", "milyon": "milyonuncu",
        "milyar": "milyarıncı", "trilyon": "trilyonuncu", "sıfır": "sıfırıncı"}


def _uc(n: int) -> list[str]:
    y, kalan = divmod(n, 100)
    o, b = divmod(kalan, 10)
    k = ([] if y == 0 else ["yüz"] if y == 1 else [BIRLER[y], "yüz"])
    return k + ([ONLAR[o]] if o else []) + ([BIRLER[b]] if b else [])


def sayi_yazi(n: int) -> str:
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + sayi_yazi(-n)
    k = []
    for deger, ad in BUYUK:
        q, n = divmod(n, deger)
        if q:
            k += ([ad] if (q == 1 and ad == "bin") else _uc(q) + [ad]) if q < 1000 else sayi_yazi(q).split() + [ad]
    return " ".join(k + _uc(n))


def sira_yazi(n: int) -> str:
    k = sayi_yazi(n).split()
    k[-1] = SIRA.get(k[-1], k[-1])
    return " ".join(k)


_ONDALIK = re.compile(r"(?<![\w.,])(-?)(\d+),(\d+)(?![\d])")
_BINLIK = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+)(?![\d]|\.\d)")
_SAAT = re.compile(r"(?<![\w:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
_SIRA = re.compile(r"(?<![\w.,])(\d+)\.(?=\s+[a-zçğıöşü])")
_YUZDE = re.compile(r"%\s?(-?\d+(?:,\d+)?)")
_ARALIK = re.compile(r"(?<![\w.,])(\d+)\s?[-–]\s?(\d+)(?![\d])")
_SAYI = re.compile(r"(?:(?<=\s)|^|(?<=[(\"']))(-?)(\d+)(?![\d])|(?<![\w-])()(\d+)(?![\d])")


def _ondalik(m):
    on, tam, kesir = m.group(1), m.group(2), m.group(3)
    kesir_y = " ".join("sıfır" for _ in range(len(kesir) - len(kesir.lstrip("0")))) + (" " if kesir.startswith("0") and kesir.strip("0") else "")
    kesir_y += sayi_yazi(int(kesir)) if kesir.strip("0") else ""
    return ("eksi " if on else "") + sayi_yazi(int(tam)) + " virgül " + kesir_y.strip()


def sayilari_oku(metin: str) -> str:
    if not re.search(r"\d", metin):
        return metin
    metin = _YUZDE.sub(lambda m: "yüzde " + m.group(1), metin)
    metin = _SAAT.sub(lambda m: sayi_yazi(int(m.group(1))) + (" " + sayi_yazi(int(m.group(2))) if int(m.group(2)) else ""), metin)
    metin = _ONDALIK.sub(_ondalik, metin)
    metin = _BINLIK.sub(lambda m: sayi_yazi(int(m.group(1).replace(".", ""))), metin)
    metin = _SIRA.sub(lambda m: sira_yazi(int(m.group(1))), metin)
    metin = _ARALIK.sub(lambda m: f"{m.group(1)} ile {m.group(2)}", metin)
    metin = _SAYI.sub(lambda m: ("eksi " if m.group(1) else "") + sayi_yazi(int(m.group(2) or m.group(4))), metin)
    return metin
