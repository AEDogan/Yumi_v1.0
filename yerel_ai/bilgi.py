"""B08 internetli bilgi işleyicileri: hava (Open-Meteo, CC BY 4.0) ve döviz (TCMB today.xml). Ağ çağrıları arka planda çalışır.
Önbellek: şehir koordinatları kalıcı, tahmin 15 dk, kur 30 dk (bellekte). İnternet yoksa açıkça söyler."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .sayi_zaman import GUNLER, kucuk, lokatif, saat_coz, sayi_soyle, sayilar

ZAMAN_ASIMI = 5
INTERNET_YOK_HAVA = "Şu an internete bağlı olmadığım için hava durumuna bakamıyorum."
INTERNET_YOK_DOVIZ = "Şu an internete bağlı olmadığım için kurlara bakamıyorum."

WMO = {0: "açık", 1: "genelde açık", 2: "parçalı bulutlu", 3: "kapalı", 45: "sisli", 48: "kırağılı sisli", 51: "hafif çiseleyen", 53: "çiseleyen",
       55: "yoğun çiseleyen", 56: "dondurucu çisenti", 57: "dondurucu çisenti", 61: "hafif yağmurlu", 63: "yağmurlu", 65: "kuvvetli yağmurlu",
       66: "dondurucu yağmurlu", 67: "dondurucu yağmurlu", 71: "hafif karlı", 73: "karlı", 75: "yoğun karlı", 77: "kar taneli", 80: "hafif sağanaklı",
       81: "sağanaklı", 82: "şiddetli sağanaklı", 85: "kar sağanaklı", 86: "yoğun kar sağanaklı", 95: "gök gürültülü fırtınalı",
       96: "dolu ile gök gürültülü", 99: "şiddetli dolu ile gök gürültülü"}
YAGIS = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
KAR = {71, 73, 75, 77, 85, 86}

DOVIZ_AD = [(r"amerikan dolar\w*|abd dolar\w*|dolar\w*|usd", "USD", "dolar"), (r"euro\w*|avro\w*|eur\b", "EUR", "euro"),
            (r"sterlin\w*|pound\w*|gbp", "GBP", "sterlin"), (r"isviçre frang\w*|frank\w*|frang\w*|chf", "CHF", "İsviçre frangı"),
            (r"japon yen\w*|yen\w*|jpy", "JPY", "yen"), (r"ruble\w*|rub\b", "RUB", "ruble"), (r"riyal\w*|sar\b", "SAR", "riyal"),
            (r"dirhem\w*|aed", "AED", "dirhem"), (r"kanada dolar\w*|cad", "CAD", "Kanada doları"), (r"avustralya dolar\w*|aud", "AUD", "Avustralya doları"),
            (r"danimarka kron\w*|dkk", "DKK", "Danimarka kronu"), (r"isveç kron\w*|sek", "SEK", "İsveç kronu"), (r"norveç kron\w*|nok", "NOK", "Norveç kronu")]


def _getir(url, cozumle="json", zaman_asimi=ZAMAN_ASIMI, tarayici=False):
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Yumi" if tarayici else "Yumi-masaustu-asistani"
    istek = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as y:
        veri = y.read()
    return json.loads(veri) if cozumle == "json" else veri


def internet_hatasi(e):
    import socket
    import urllib.error
    return isinstance(e, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError))


def zaman_asimi_mi(e):
    import socket
    import urllib.error
    if isinstance(e, urllib.error.URLError) and isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
        return True
    return isinstance(e, (socket.timeout, TimeoutError))


# ------------------------------------------------------------------ hava
def sehir_ayikla(konum_parcasi: str | None):
    """"İzmir'de" -> "İzmir", "balıkesirde" -> "balıkesir", "ankara için" -> "ankara"."""
    if not konum_parcasi:
        return None
    s = konum_parcasi.strip(" ?.!,")
    s = re.split(r"['’]", s)[0]
    s = re.sub(r"\s+(için|da|de|ta|te)$", "", s, flags=re.I)
    if "'" not in konum_parcasi and "’" not in konum_parcasi:
        s = re.sub(r"(?<=[a-zçğıöşü]{3})(da|de|ta|te|nda|nde)$", "", s, flags=re.I)
    return s.strip() or None


def gun_sec(metin: str, simdi: dt.datetime):
    """-> ('simdi', None) | ('gun', tarih) | ('hafta', None) | ('aksam', tarih)."""
    m = kucuk(metin)
    if re.search(r"hafta sonu", m):
        return ("haftasonu", None)
    if re.search(r"önümüzdeki günler|bu hafta|hafta boyunca", m):
        return ("hafta", None)
    if re.search(r"yarından sonra|öbür gün|ertesi gün", m):  # B10
        return ("gun", simdi.date() + dt.timedelta(days=2))
    if "yarın" in m:
        return ("aksam" if "akşam" in m else "gun", simdi.date() + dt.timedelta(days=1))
    for i, g in enumerate(GUNLER):
        if re.search(rf"\b{g}\b|\b{g}(?:ya|ye|a|e|ı|i|u|ü)?\b", m) and not (g == "pazar" and "pazartesi" in m):
            fark = (i - simdi.weekday()) % 7
            return ("gun", simdi.date() + dt.timedelta(days=fark))
    if re.search(r"akşam|bu gece", m):
        return ("aksam", simdi.date())
    if re.search(r"\bbugün\b", m) and not re.search(r"şu an|şimdi|dışarısı", m):
        return ("gun", simdi.date())
    return ("simdi", None)


class Hava:
    def __init__(self, veri_klasoru: Path | None = None):
        self.dosya = Path(veri_klasoru) / "yerel_ai_konum.json" if veri_klasoru else None
        self.kayit = {"varsayilan": None, "sehirler": {}}
        if self.dosya and self.dosya.is_file():
            try:
                self.kayit.update(json.loads(self.dosya.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        self._tahmin = {}

    def _kaydet(self):
        if self.dosya:
            try:
                self.dosya.parent.mkdir(parents=True, exist_ok=True)
                gecici = self.dosya.with_suffix(".tmp")
                gecici.write_text(json.dumps(self.kayit, ensure_ascii=False, indent=1), encoding="utf-8")
                gecici.replace(self.dosya)
            except OSError:
                pass

    @property
    def varsayilan(self):
        return self.kayit.get("varsayilan")

    def varsayilan_yap(self, sehir):
        self.kayit["varsayilan"] = sehir; self._kaydet()

    def koordinat(self, sehir):
        anahtar = kucuk(sehir)
        if anahtar in self.kayit["sehirler"]:
            return self.kayit["sehirler"][anahtar]
        q = urllib.parse.urlencode({"name": sehir, "count": 1, "language": "tr", "format": "json"})
        d = _getir(f"https://geocoding-api.open-meteo.com/v1/search?{q}")
        if not d.get("results"):
            return None
        r = d["results"][0]
        k = {"ad": r.get("name", sehir), "enlem": r["latitude"], "boylam": r["longitude"]}
        self.kayit["sehirler"][anahtar] = k; self._kaydet()
        return k

    def tahmin(self, k):
        anahtar = (k["enlem"], k["boylam"])
        if anahtar in self._tahmin and time.time() - self._tahmin[anahtar][0] < 900:
            return self._tahmin[anahtar][1]
        q = urllib.parse.urlencode({"latitude": k["enlem"], "longitude": k["boylam"], "timezone": "auto", "forecast_days": 7,
                                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                                    "hourly": "temperature_2m,weather_code,precipitation_probability",
                                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"})
        d = _getir(f"https://api.open-meteo.com/v1/forecast?{q}")
        self._tahmin[anahtar] = (time.time(), d)
        return d

    def yanit(self, metin, sehir, simdi=None):
        """Ağ çağrısı içerir: arka planda çalıştırılır."""
        simdi = simdi or dt.datetime.now()
        try:
            k = self.koordinat(sehir)
            if not k:
                return f"{sehir} adında bir yer bulamadım."
            d = self.tahmin(k)
        except Exception as e:
            if zaman_asimi_mi(e):
                return "Hava durumu kaynağı şu an cevap vermiyor, biraz sonra tekrar dener misin?"
            return INTERNET_YOK_HAVA if internet_hatasi(e) else f"Hava durumuna bakarken bir sorun oldu: {e}"
        return hava_cumlesi(metin, k["ad"], d, simdi)


def _saat_eki(h):
    """Saat bulunma eki: 3'te, 15'te, 9'da, 10'da, 12'de, 20'de."""
    son = {0: "da", 1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da"}
    if h % 10 == 0:
        return {0: "da", 10: "da", 20: "de"}.get(h, "da")
    return son[h % 10]


def _yuvarla(x):
    return sayi_soyle(int(round(x)))


def hava_cumlesi(metin, ad, d, simdi):
    m = kucuk(metin)
    tur, gun = gun_sec(metin, simdi)
    gunluk = d["daily"]
    tarihler = [dt.date.fromisoformat(t) for t in gunluk["time"]]
    yagmur_sor = re.search(r"yağmur|yağacak|şemsiye|ıslan", m)
    kar_sor = re.search(r"\bkar\b|kar yağ", m)
    # 12 Kasım: "saat 3'teki hava durumu" -> o saatin tahmini (önceden şu anki hava okunuyordu)
    if re.search(r"\bsaat\s+\S", m) and not re.search(r"saatte|saatlik|kaç saat", m):
        try:
            hedef = saat_coz(metin, simdi)
        except Exception:
            hedef = None
        if hedef and tur == "gun" and gun and hedef.date() != gun:
            hedef = dt.datetime.combine(gun, hedef.time())
        if hedef:
            anahtar = hedef.strftime("%Y-%m-%dT%H:00")
            saatler = d.get("hourly", {}).get("time", [])
            if anahtar in saatler:
                j = saatler.index(anahtar)
                on = "" if hedef.date() == simdi.date() else "Yarın " if hedef.date() == simdi.date() + dt.timedelta(days=1) else GUNLER[hedef.weekday()].capitalize() + " "
                s = (f"{on}saat {sayi_soyle(hedef.hour)}'{_saat_eki(hedef.hour)} {lokatif(ad)} {_yuvarla(d['hourly']['temperature_2m'][j])} derece, "
                     f"hava {WMO.get(d['hourly']['weather_code'][j], 'değişken')}")
                olasilik = d["hourly"]["precipitation_probability"][j] or 0
                if yagmur_sor or kar_sor or olasilik >= 40:
                    s += f", yağış olasılığı yüzde {olasilik}"
                return s[0].upper() + s[1:] + "."
            return "O saat için henüz tahmin yok; en fazla bir hafta sonrasına bakabiliyorum."
    if tur == "simdi" and (yagmur_sor or kar_sor):  # 'şemsiye almalı mıyım' -> bugünün tahmini
        tur, gun = "gun", simdi.date()
    if tur == "simdi":
        c = d["current"]
        s = f"{lokatif(ad)} şu an {_yuvarla(c['temperature_2m'])} derece, hava {WMO.get(c['weather_code'], 'değişken')}"
        if abs(c["apparent_temperature"] - c["temperature_2m"]) >= 3:
            s += f", hissedilen {_yuvarla(c['apparent_temperature'])}"
        if c.get("wind_speed_10m", 0) >= 30:
            s += f", rüzgar saatte {_yuvarla(c['wind_speed_10m'])} kilometre"
        return s + "."
    if tur in ("hafta", "haftasonu"):
        secilen = [i for i, t in enumerate(tarihler) if (t.weekday() >= 5 if tur == "haftasonu" else True)][:2 if tur == "haftasonu" else 4]
        if not secilen:
            return "O günler için tahmin yok."
        parcalar = [f"{GUNLER[tarihler[i].weekday()].capitalize()} {_yuvarla(gunluk['temperature_2m_min'][i])} ile {_yuvarla(gunluk['temperature_2m_max'][i])} derece, "
                    f"{WMO.get(gunluk['weather_code'][i], 'değişken')}" for i in secilen]
        return f"{ad} için: " + "; ".join(parcalar) + "."
    if gun not in tarihler:
        return "O gün için henüz tahmin yok; en fazla bir hafta sonrasına bakabiliyorum."
    i = tarihler.index(gun)
    on = "Bugün" if gun == simdi.date() else "Yarın" if gun == simdi.date() + dt.timedelta(days=1) else GUNLER[gun.weekday()].capitalize()
    if tur == "aksam":
        saatler = [j for j, t in enumerate(d["hourly"]["time"]) if t.startswith(gun.isoformat()) and 18 <= int(t[11:13]) <= 22]
        if saatler:
            sic = [d["hourly"]["temperature_2m"][j] for j in saatler]
            kod = max((d["hourly"]["weather_code"][j] for j in saatler), key=lambda x: (x in YAGIS or x in KAR, x))
            olasilik = max(d["hourly"]["precipitation_probability"][j] or 0 for j in saatler)
            s = f"{'Bu' if on == 'Bugün' else on} akşam {lokatif(ad)} {_yuvarla(min(sic))} ile {_yuvarla(max(sic))} derece, {WMO.get(kod, 'değişken')}"
            if yagmur_sor or kar_sor or olasilik >= 40:
                s += f", yağış olasılığı yüzde {olasilik}"
            return s + "."
    s = (f"{on} {lokatif(ad)} en düşük {_yuvarla(gunluk['temperature_2m_min'][i])}, en yüksek {_yuvarla(gunluk['temperature_2m_max'][i])} derece, "
         f"hava {WMO.get(gunluk['weather_code'][i], 'değişken')}")
    if yagmur_sor or kar_sor:
        return s + ". " + _yagis_cumlesi(gunluk, i, bool(kar_sor), on)
    if (gunluk["precipitation_probability_max"][i] or 0) >= 40:
        s += f", yağış olasılığı yüzde {gunluk['precipitation_probability_max'][i]}"
    return s + "."


def _yagis_cumlesi(gunluk, i, kar, on):
    olasilik = gunluk["precipitation_probability_max"][i] or 0
    kod = gunluk["weather_code"][i]
    ad = "kar" if kar else "yağmur"
    if (kar and kod in KAR) or (not kar and kod in YAGIS) or olasilik >= 60:
        return f"{on} {ad} bekleniyor, olasılık yüzde {olasilik}." + (" Şemsiyeni al." if not kar else "")
    if olasilik >= 30:
        return f"{on} {ad} olasılığı yüzde {olasilik}, ihtimal düşük ama var."
    return f"{on} {ad} beklenmiyor."


# ------------------------------------------------------------------ döviz
class Doviz:
    """Kaynak sırası: TCMB today.xml (3 s) -> Frankfurter (Avrupa Merkez Bankası, mevcut briefing_skill ile aynı)."""

    def __init__(self):
        self._kur = None
        self._tcmb_atla = 0.0  # TCMB cevap vermediyse 6 saat doğrudan yedek kaynağa git (her soruda 3 s beklenmesin)

    def kurlar(self):
        if self._kur and time.time() - self._kur[0] < 1800:
            return self._kur[1]
        hatalar = []
        try:
            if time.time() < self._tcmb_atla:
                raise TimeoutError("TCMB geçici olarak atlandı")
            k = kur_cozumle(ET.fromstring(_getir("https://www.tcmb.gov.tr/kurlar/today.xml", "ham", 3, tarayici=True)))
            k["kaynak"] = "TCMB"
        except Exception as e:
            hatalar.append(e)
            if not str(e).startswith("TCMB geçici"):
                self._tcmb_atla = time.time() + 6 * 3600
            try:
                d = _getir("https://api.frankfurter.dev/v1/latest?base=TRY", zaman_asimi=4)
                t = d.get("date") or ""
                k = {"tarih": ".".join(reversed(t.split("-"))) if t else None, "kaynak": "Avrupa Merkez Bankası"}
                for kod, oran in (d.get("rates") or {}).items():
                    if oran:
                        k[kod] = (1 / oran, 1 / oran, kod)
            except Exception as e2:
                hatalar.append(e2)
                raise DovizHatasi(hatalar)
        self._kur = (time.time(), k)
        return k

    def yanit(self, metin):
        try:
            k = self.kurlar()
        except DovizHatasi as e:
            if all(internet_hatasi(h) and not zaman_asimi_mi(h) for h in e.hatalar):
                return INTERNET_YOK_DOVIZ
            return "Kur kaynakları şu an cevap vermiyor, biraz sonra tekrar dener misin?"
        except Exception as e:
            return f"Kurlara bakarken bir sorun oldu: {e}"
        return doviz_cumlesi(metin, k)


class DovizHatasi(Exception):
    def __init__(self, hatalar):
        super().__init__("; ".join(map(str, hatalar)))
        self.hatalar = hatalar


def kur_cozumle(kok):
    """TCMB XML -> {"tarih": "07.11.2026", "USD": (alış, satış, ad), ...} (1 birim için)."""
    k = {"tarih": kok.get("Tarih") or kok.get("Date")}
    for c in kok.findall("Currency"):
        kod = c.get("CurrencyCode") or c.get("Kod")
        try:
            birim = float(c.findtext("Unit") or 1)
            alis = float(c.findtext("ForexBuying") or c.findtext("BanknoteBuying"))
            satis = float(c.findtext("ForexSelling") or c.findtext("BanknoteSelling"))
        except (TypeError, ValueError):
            continue
        k[kod] = (alis / birim, satis / birim, c.findtext("Isim") or kod)
    return k


def doviz_cumlesi(metin, k):
    m = kucuk(metin)
    bulunan = []
    for desen, kod, ad in DOVIZ_AD:
        g = re.search(rf"\b(?:{desen})", m)
        if g and kod in k and not any(b[0] == kod for b in bulunan):
            bulunan.append((kod, ad, g.start()))
    tarih = f" ({k.get('kaynak', 'TCMB')} {k['tarih']})" if k.get("tarih") else ""
    if not bulunan:  # 'kurlar nasıl' -> dolar ve euro özeti
        ozet = [f"{ad} {_kur(k[kod][1])}" for _, kod, ad in DOVIZ_AD[:2] if kod in k]
        return ("Satış kurları: " + ", ".join(ozet) + f" lira{tarih}.") if ozet else "Hangi para birimine bakayım?"
    bulunan.sort(key=lambda b: b[2])
    n = sayilar(m)
    miktar = n[0] if n else None
    lira_once = re.search(r"\b(lira|tl)\b", m) and re.search(r"\b(lira|tl)\b", m).start() < bulunan[0][2]
    if len(bulunan) >= 2:  # '100 euro kaç dolar'
        (k1, a1, _), (k2, a2, _) = bulunan[:2]
        x = miktar or 1
        y = x * k[k1][1] / k[k2][1]
        return f"{sayi_soyle(x)} {a1} yaklaşık {sayi_soyle(round(y, 2))} {a2}{tarih}."
    kod, ad, _ = bulunan[0]
    alis, satis, _ = k[kod]
    if miktar and lira_once:  # '1000 lira kaç dolar'
        return f"{sayi_soyle(miktar)} lira yaklaşık {sayi_soyle(round(miktar / satis, 2))} {ad}{tarih}."
    if miktar:
        return f"{sayi_soyle(miktar)} {ad} yaklaşık {sayi_soyle(round(miktar * satis, 2))} lira{tarih}."
    if abs(alis - satis) < 1e-9:
        return f"1 {ad} {_kur(satis)} lira{tarih}."
    return f"1 {ad} alış {_kur(alis)}, satış {_kur(satis)} lira{tarih}."


def _kur(x):
    return sayi_soyle(round(x, 4 if x < 1 else 2))
