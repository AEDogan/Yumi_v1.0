"""Türkçe sayı, süre ve saat çözücü (internetsiz, kural tabanlı). Niyet modelinin parça tahminine ek güvence.

sayilar("bin iki yüzün yüzde onu")        -> metin içindeki sayılar sırasıyla [1200, 10]
sure_s("bir buçuk saat sonra")            -> 5400 (saniye) ya da None
saat_coz("yarın sabah yedi buçukta", now) -> datetime ya da None
"""
from __future__ import annotations

import datetime as dt
import re

BIRLER = {"sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
ONLAR = {"on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90}
CARPAN = {"yüz": 100, "bin": 1000, "milyon": 1_000_000}
KELIME = {**BIRLER, **ONLAR, **CARPAN}
# sayı sözcüğünden sonra gelebilen ekler (yedi-de, beş-te, on-u, iki-yi, sekiz-e, dokuz-un, yüz-ün, bir-inci ...)
EKLER = sorted({"", "de", "da", "te", "ta", "e", "a", "i", "ı", "u", "ü", "ye", "ya", "yi", "yı", "yu", "yü", "den", "dan", "ten", "tan",
                "in", "ın", "un", "ün", "nin", "nın", "nun", "nün", "lik", "lık", "luk", "lük", "li", "lı", "lu", "lü", "inci", "ıncı",
                "uncu", "üncü", "ncı", "nci", "ncu", "ncü", "si", "sı", "su", "sü", "le", "la", "yle", "yla", "dir", "dır", "tir", "tır"}, key=len, reverse=True)
YARIM = {"buçuk": 0.5, "buçukta": 0.5, "buçuğa": 0.5, "buçuğu": 0.5}


def kucuk(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _sozcuk_sayi(t: str):
    """'yedide' -> 7, 'yüzün' -> 100, 'biraz' -> None."""
    t = t.strip("'’")
    if t.startswith("yüzde"):  # 'yüzde' yüzdelik sözcüğü, 100 değil
        return None
    for k in sorted(KELIME, key=len, reverse=True):
        if t.startswith(k) and t[len(k):].lstrip("'’") in EKLER:
            return KELIME[k]
    return None


def _rakam(t: str):
    m = re.fullmatch(r"%?(\d+(?:[.,]\d+)?)['’]?[a-zçğıöşü]*", t)
    if not m:
        return None
    v = m.group(1).replace(",", ".")
    return float(v) if "." in v else int(v)


def sayilar(metin: str) -> list:
    """Metindeki sayıları (rakam ya da yazı) sırayla döndürür; 'bin iki yüz' -> 1200, 'iki buçuk' -> 2.5."""
    sonuc, toplam, simdiki, var = [], 0, 0, False

    def bitir():
        nonlocal toplam, simdiki, var
        if var:
            sonuc.append(toplam + simdiki)
        toplam, simdiki, var = 0, 0, False

    for t in re.findall(r"[\w%'’.,:]+", kucuk(metin)):
        t = t.strip(".,")
        if not t:
            continue
        r = _rakam(t)
        if r is not None:
            bitir(); sonuc.append(r); continue
        if t in YARIM and (var or sonuc):
            if var:
                simdiki += 0.5; bitir()
            else:
                sonuc[-1] += 0.5
            continue
        n = _sozcuk_sayi(t)
        if n is None:
            bitir(); continue
        if n in (100, 1000, 1_000_000):
            if n == 100:
                simdiki = (simdiki or 1) * 100
            else:
                toplam = (toplam + (simdiki or 1)) * n; simdiki = 0
        elif var and ((n >= 10 and simdiki % 100 == 0) or (n < 10 and simdiki % 10 == 0 and (simdiki or toplam))):
            simdiki += n  # 'yüz on' -> 110, 'on iki' -> 12, 'bin iki' -> 1002
        else:
            bitir(); simdiki = n  # 'iki üç' -> iki ayrı sayı
        var = True
        if t != _kok(t):  # ekli sözcük ('yüzün', 'yedide') sayının bittiğini gösterir
            bitir()
    bitir()
    return sonuc


def _kok(t):
    for k in sorted(KELIME, key=len, reverse=True):
        if t.startswith(k):
            return k
    return t


BIRIM_S = [(r"saniye|sn\b", 1), (r"dakika|dk\b", 60), (r"saat", 3600), (r"gün", 86400), (r"hafta", 604800)]


def sure_s(metin: str):
    """Süre ifadesi -> saniye. 'beş dakika', '1 saat 20 dakika', 'yarım saat', 'çeyrek saat', 'bir buçuk saat'. Yoksa None."""
    m = kucuk(metin)
    toplam, bulundu = 0.0, False
    if re.search(r"\byarım saat", m):
        toplam += 1800; bulundu = True; m = re.sub(r"\byarım saat\w*", " ", m)
    if re.search(r"\bçeyrek saat", m):
        toplam += 900; bulundu = True; m = re.sub(r"\bçeyrek saat\w*", " ", m)
    if re.search(r"\byarım dakika", m):
        toplam += 30; bulundu = True; m = re.sub(r"\byarım dakika\w*", " ", m)
    # her birim için önündeki sayı öbeğini al
    for birim, carpan in BIRIM_S:
        for mm in re.finditer(rf"((?:[\w%'’.,]+\s+){{0,4}}?)({birim})\w*", m):
            once = mm.group(1)
            if birim == "saat" and re.search(r"\bsaat\s*\d|saat\s+(?:" + "|".join(KELIME) + r")\w*\s*(?:de|da|te|ta|e|a)?\b", mm.group(0) + m[mm.end():mm.end() + 12]) and not once.strip():
                continue  # 'saat 7'de' bir saattir, süre değil
            s = sayilar(once.split("ve")[-1]) if once.strip() else []
            if s:
                toplam += s[-1] * carpan; bulundu = True
            elif re.search(rf"\b(?:bir|{birim})", mm.group(0)) and once.strip() == "" and re.search(rf"^{birim}\w*lik|^{birim}\w*\s+sonra", m[mm.start(2):]):
                toplam += carpan; bulundu = True  # 'dakikalık' / 'saat sonra' tek başına -> 1
    return int(round(toplam)) if bulundu and toplam > 0 else None


GUNLER = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
AYLAR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"]


def saat_coz(metin: str, simdi: dt.datetime | None = None, sabah_tercih=False):
    """Saat ifadesi -> gelecekteki ilk datetime. 'saat 7'de', '19:30', 'yedi buçukta', 'sekize çeyrek kala', 'akşam 8', 'yarın sabah 7'.
    Belirsiz 1–12 saatlerde: sabah/akşam sözcüğü varsa ona göre; yoksa (sabah_tercih değilse) en yakın gelecek."""
    simdi = simdi or dt.datetime.now()
    m = kucuk(metin)
    saat = dakika = None
    hm = re.search(r"\b(\d{1,2})[:.](\d{2})\b", m)
    if hm:
        saat, dakika = int(hm.group(1)), int(hm.group(2))
    else:
        kala = re.search(r"([\w']+)\s+(çeyrek|yarım|[\w']+\s+dakika|[\w']+)\s+kala", m)
        gece = re.search(r"([\w']+)\s+(çeyrek|[\w']+\s+dakika|[\w']+)\s+geçe", m)
        if kala or gece:
            g = kala or gece
            s = sayilar(g.group(1))
            dk = 15 if g.group(2) == "çeyrek" else 30 if g.group(2) == "yarım" else (sayilar(g.group(2)) or [None])[0]
            if s and dk is not None:
                saat, dakika = int(s[0]), int(dk)
                if kala:
                    saat, dakika = (saat - 1) % 24, 60 - dakika
        if saat is None:
            ss = re.search(r"\bsaat\s+([\w'’ ]+)", m) or re.search(r"\b((?:\d{1,2}|" + "|".join(sorted(KELIME, key=len, reverse=True)) + r")[\w'’]*(?:\s+buçu\w*)?)\s*(?:'?(?:de|da|te|ta|e|a|ye|ya))?\b", m)
            if ss:
                parca = ss.group(1)
                s = sayilar(" ".join(parca.split()[:3]))
                if s and 0 <= s[0] < 24:
                    saat = int(s[0]); dakika = 30 if (s[0] % 1) else 0
                    if len(s) > 1 and s[1] < 60 and s[1] == int(s[1]) and not (s[0] % 1):
                        dakika = int(s[1])
    if saat is None or not (0 <= saat < 24) or not (0 <= (dakika or 0) < 60):
        return None
    dakika = dakika or 0
    ogleden_sonra = re.search(r"akşam|öğleden sonra|ikindi", m) or (re.search(r"\bgece\b", m) and saat >= 7)
    sabah = re.search(r"sabah|gece yarısı", m) or (re.search(r"\bgece\b", m) and saat < 7)
    gun = simdi.date()
    gun_belli = False
    if "yarın" in m:
        gun += dt.timedelta(days=1); gun_belli = True
    elif "öbür gün" in m or "ertesi gün" in m:
        gun += dt.timedelta(days=2); gun_belli = True
    else:
        for i, g in enumerate(GUNLER):
            if re.search(rf"\b{g}\w*", m) and not (g == "pazar" and "pazartesi" in m and not re.search(r"\bpazar\b|\bpazara\b|\bpazarı\b", m)):
                fark = (i - simdi.weekday()) % 7 or 7
                gun += dt.timedelta(days=fark); gun_belli = True
                break
    adaylar = []
    if saat == 12 and not hm and re.search(r"\bgece", m):
        saat, ogleden_sonra, sabah = 0, None, True  # 'gece 12' = gece yarısı
    if saat <= 12 and not hm or (hm and saat <= 12 and (ogleden_sonra or sabah)):
        if ogleden_sonra:
            adaylar = [saat % 12 + 12]
        elif sabah or sabah_tercih:
            adaylar = [saat % 12 if saat != 12 or re.search(r"gece", m) else 12]
        else:
            adaylar = [saat % 12, saat % 12 + 12] if saat != 12 else [12]
    else:
        adaylar = [saat]
    secenek = []
    for h in adaylar:
        t = dt.datetime.combine(gun, dt.time(h % 24, dakika))
        if not gun_belli:
            while t <= simdi:
                t += dt.timedelta(days=1)
        secenek.append(t)
    secenek = [t for t in secenek if t > simdi] or secenek
    return min(secenek)


def sayi_soyle(x) -> str:
    """Sonucu Türkçe yazım: 12.5 -> '12,5', 1234567 -> '1.234.567'."""
    if isinstance(x, float) and abs(x - round(x)) < 1e-9:
        x = int(round(x))
    if isinstance(x, int):
        return f"{x:,}".replace(",", ".")
    s = f"{x:,.4f}".rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


_IYELIK = {0: "ı", 1: "i", 2: "si", 3: "ü", 4: "ü", 5: "i", 6: "sı", 7: "si", 8: "i", 9: "u",
           10: "u", 20: "si", 30: "u", 40: "ı", 50: "si", 60: "ı", 70: "i", 80: "i", 90: "ı", 100: "ü", 1000: "i"}


def iyelik(x) -> str:
    """Sayıya iyelik eki: 10 -> "10'u", 20 -> "20'si", 75 -> "75'i", 2,5 -> "2,5'i"."""
    y = sayi_soyle(x)
    if isinstance(x, float) and abs(x - round(x)) > 1e-9:
        son = int(y.split(",")[-1][-1])
        return f"{y}'{_IYELIK[son] if son else 'ı'}"
    n = int(round(x))
    if n % 10:
        ek = _IYELIK[n % 10]
    elif n % 100:
        ek = _IYELIK[n % 100]
    elif n % 1000:
        ek = _IYELIK[100]
    else:
        ek = _IYELIK[1000] if n else _IYELIK[0]
    return f"{y}'{ek}"


def lokatif(ad: str) -> str:
    """Özel ada bulunma eki: İzmir'de, Ankara'da, Kars'ta, Sinop'ta, Rize'de, Van'da."""
    k = kucuk(ad)
    unlu = [h for h in k if h in "aeıioöuü"]
    son = unlu[-1] if unlu else "e"
    u = "a" if son in "aıou" else "e"
    sert = k[-1] in "çfhkpsşt"
    return f"{ad}'{'t' if sert else 'd'}{u}"
