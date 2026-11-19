"""İnternetsiz hesap: dört işlem, yüzde/indirim/zam/KDV, kare/karekök/küp, birim çevirme.
hesapla(metin) -> yanıt cümlesi ya da None (anlaşılamadı)."""
from __future__ import annotations

import math
import re

from .sayi_zaman import iyelik, kucuk, sayi_soyle, sayilar

OPLAR = [(r"artı|\+|topla\w*|ekle\w*", "+"), (r"eksi|−|çıkar\w*", "-"), (r"çarpı|kere|x|×|\*|çarp\w*", "*"), (r"bölü|÷|/|böl\w*", "/")]
OP_RE = re.compile(r"^(?:" + "|".join(f"(?P<o{i}>{p})" for i, (p, _) in enumerate(OPLAR)) + r")$")

BIRIM = {  # ad deseni -> (grup, temele çarpan)
    r"kilometre|km": ("uzunluk", 1000), r"mil\b|mile": ("uzunluk", 1609.344), r"metre|\bm\b": ("uzunluk", 1), r"santim\w*|cm\b": ("uzunluk", 0.01),
    r"milimetre|mm\b": ("uzunluk", 0.001), r"inç|inch": ("uzunluk", 0.0254), r"feet|fit\b|ayak": ("uzunluk", 0.3048), r"yarda": ("uzunluk", 0.9144),
    r"kilo\w*|kg\b": ("kütle", 1), r"gram|gr\b": ("kütle", 0.001), r"pound|libre": ("kütle", 0.45359237), r"ons": ("kütle", 0.028349523), r"ton\b": ("kütle", 1000),
    r"litre|lt\b": ("hacim", 1), r"mililitre|ml\b": ("hacim", 0.001), r"galon": ("hacim", 3.785411784),
    r"saniye|sn\b": ("zaman", 1), r"dakika|dk\b": ("zaman", 60), r"saat": ("zaman", 3600), r"gün": ("zaman", 86400), r"hafta": ("zaman", 604800),
    r"santigrat|celsius|selsiyus": ("sıcaklık", "C"), r"fahrenhayt|fahrenheit": ("sıcaklık", "F"),
}
BIRIM_ADI = {"uzunluk": None}


def _birim(t):
    for desen, deger in BIRIM.items():
        if re.match(rf"^(?:{desen})", t):
            return re.match(rf"^(?:{desen})", t).group(0), deger
    return None


def _birim_cevir(m):
    """'5 mil kaç kilometre' / '100 fahrenhayt kaç santigrat'."""
    g = re.search(r"([\d.,]+|[a-zçğıöşü ]+?)\s+([a-zçğıöşü]+)\w*\s+kaç\s+([a-zçğıöşü]+)", m)
    if not g:
        return None
    n = sayilar(g.group(1))
    b1, b2 = _birim(g.group(2)), _birim(g.group(3))
    if not n or not b1 or not b2 or b1[1][0] != b2[1][0]:
        return None
    x = n[-1]
    if b1[1][0] == "sıcaklık":
        y = x * 9 / 5 + 32 if b1[1][1] == "C" and b2[1][1] == "F" else (x - 32) * 5 / 9 if b1[1][1] == "F" and b2[1][1] == "C" else x
    else:
        y = x * b1[1][1] / b2[1][1]
    return f"{sayi_soyle(x)} {g.group(2)}, {sayi_soyle(round(y, 2))} {g.group(3)} eder."


def _yuzde(m):
    if "yüzde" not in m and "%" not in m:
        return None
    n = sayilar(m)
    if len(n) < 2:
        return None
    # yüzde oranı: 'yüzde'/'%' işaretinden hemen sonraki sayı
    oran_m = re.search(r"(?:yüzde|%)\s*([\w'’,.]+(?:\s+(?!lira|tl)[a-zçğıöşü]+)?)", m)
    oran = sayilar(oran_m.group(1))[0] if oran_m and sayilar(oran_m.group(1)) else n[1]
    diger = [x for x in n if x != oran] or [n[0]]
    a = diger[0]
    if re.search(r"indirim", m):
        return f"%{sayi_soyle(oran)} indirimle {sayi_soyle(a)}, {sayi_soyle(round(a * (1 - oran / 100), 2))} eder."
    if re.search(r"zam|kdv|vergi|artış|ekle", m):
        return f"{sayi_soyle(a)} üstüne %{sayi_soyle(oran)} ile {sayi_soyle(round(a * (1 + oran / 100), 2))} eder."
    if re.search(r"olan", m):  # 'yüzde 20'si 50 olan sayı'
        return f"Yüzde {iyelik(oran)} {sayi_soyle(a)} olan sayı {sayi_soyle(round(a * 100 / oran, 2))}."
    return f"{sayi_soyle(a)} sayısının yüzde {iyelik(oran)} {sayi_soyle(round(a * oran / 100, 2))} eder."


def _tek(m):
    n = sayilar(m)
    if not n:
        return None
    x = n[0]
    if re.search(r"karekök", m):
        return f"{sayi_soyle(x)} sayısının karekökü {sayi_soyle(round(math.sqrt(x), 4))}." if x >= 0 else None
    if re.search(r"\bkare(?:si|sini)?\b", m):
        return f"{sayi_soyle(x)} sayısının karesi {sayi_soyle(x * x)}."
    if re.search(r"\bküp(?:ü|ünü)?\b", m):
        return f"{sayi_soyle(x)} sayısının küpü {sayi_soyle(x ** 3)}."
    return None


def _islem(m):
    """Sayı/işleç dizisi: '12 artı 5 çarpı 3', 'on iki bölü dört', '5 ile 7 çarp', "20'den 3 çıkar"."""
    dizi, sayi_parca = [], []

    def sayi_bitir():
        if sayi_parca:
            for x in sayilar(" ".join(sayi_parca)):
                dizi.append(("n", x))
            sayi_parca.clear()

    for t in re.findall(r"[\w%'’.,]+|[+\-*/×÷]", m):
        o = OP_RE.match(t.strip("'’"))
        if o:
            sayi_bitir()
            dizi.append(("o", OPLAR[int(next(k for k, v in o.groupdict().items() if v)[1:])][1]))
        elif sayilar(t):
            sayi_parca.append(t)
        else:
            sayi_bitir()
    sayi_bitir()
    n = [d for d in dizi if d[0] == "n"]
    o = [d for d in dizi if d[0] == "o"]
    if len(n) < 2 or not o:
        return None
    if len(o) == 1 and dizi[-1][0] == "o":  # '5 ile 7 çarp' / "20'den 3 çıkar" (işleç sonda)
        a, b, op = n[0][1], n[1][1], o[0][1]
        ifade = f"{a}{op}{b}"
    else:
        parca = []
        for tur, d in dizi:
            if tur == "n":
                if parca and parca[-1][0] == "n":
                    return None
                parca.append(("n", d))
            elif parca and parca[-1][0] == "n":
                parca.append(("o", d))
        if parca and parca[-1][0] == "o":
            parca.pop()
        if len(parca) < 3:
            return None
        ifade = "".join(str(d) for _, d in parca)
    if not re.fullmatch(r"[\d.+\-*/]+", ifade) or "**" in ifade or len(ifade) > 200:
        return None  # 19 Kas (güvenlik): '**' üs alma "9**9**9**9" ile Yumi'yi kilitleyebiliyordu
    try:
        y = eval(ifade, {"__builtins__": {}}, {})  # yalnız rakam ve + - * / (yukarıda doğrulandı)
    except ZeroDivisionError:
        return "Sıfıra bölme tanımsız."
    except Exception:
        return None
    goster = ifade.replace("*", " çarpı ").replace("/", " bölü ").replace("+", " artı ").replace("-", " eksi ")
    goster = re.sub(r"\d+(?:\.\d+)?", lambda k: sayi_soyle(float(k.group(0)) if "." in k.group(0) else int(k.group(0))), goster)
    return f"{goster.strip()}, {sayi_soyle(round(y, 2))} eder."


def hesapla(metin: str):
    m = kucuk(metin)
    for f in (_birim_cevir, _yuzde, _tek, _islem):
        try:
            r = f(m)
        except (ValueError, IndexError, ZeroDivisionError):
            r = None
        if r:
            return r
    return None
