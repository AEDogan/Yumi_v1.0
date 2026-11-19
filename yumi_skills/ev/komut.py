"""Türkçe ev komutu → (cihaz, yetenek, değer). Yerel, kural tabanlı; Gemini'ye gitmez.

    k = cozumle("salondaki televizyonun sesini 10 yap", cihazlar)
    k.durum: "tamam" | "sor" (hangi cihaz?) | "yok" (öyle cihaz yok) | "desteklenmiyor" | "anlamadim" | "ev_degil"

Kurallar: uydurma yok. Cihaz türü/adı geçmiyorsa "ev_degil" (eski yola bırakılır). Birden çok aday ve
çoğul/hepsi denmemişse "sor". Cihaz var ama istenen şey anlaşılmadıysa "anlamadim".
Türkçe ekler kök + \\w* ile; ünsüz yumuşaması (mutfak→mutfağa, ışık→ışığı) desenlerde.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .model import EvCihazi

# -- metin yardımcıları
def kucuk(s: str) -> str:
    return (s or "").replace("İ", "i").replace("I", "ı").lower()


def _temiz(s: str) -> str:
    s = kucuk(s)
    s = re.sub(r"[’`´]", "'", s)
    s = re.sub(r"[^\w%'\s-]", " ", s)
    return " ".join(s.split())


SAYI_SOZ = {"sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
            "dokuz": 9, "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70,
            "seksen": 80, "doksan": 90, "yüz": 100}


def sayi_bul(m: str) -> int | None:
    """İlk sayı: rakam ('10', '10'a', '%30') ya da yazı ('on beş', 'yirmiye'). 'bir' tek başına sayılmaz."""
    r = re.search(r"(?<![\w])%?\s?(\d{1,4})", m)
    if r:
        return int(r.group(1))
    toplam, var = 0, False
    for kelime in m.split():
        kok = re.sub(r"'.*$", "", kelime)
        es = next((v for k, v in sorted(SAYI_SOZ.items(), key=lambda x: -len(x[0]))
                   if kok == k or (kok.startswith(k) and len(kok) - len(k) <= 3 and k not in ("bir", "on", "altı", "yüz"))
                   or (k in ("on", "yüz", "altı") and re.fullmatch(k + r"(a|e|u|ü|ya|ye|ua|da|de|dan|den|ı|i|u|ü)?", kok))), None)
        if es is not None and not (kok == "bir" and not var):
            toplam += es
            var = True
        elif var:
            break
    return toplam if var else None


# -- sözlükler
TURLER = {  # tür: kök deseni (ünsüz yumuşaması dahil)
    "tv": r"(televizyon|tv\b|tivi|teve)",
    "light": r"(ışı[kğ]|lamba|ampul|avize|abajur|aydınlatma|\bled\b)",
    "plug": r"(priz)",
    "vacuum": r"(süpürge|robot süpürge|roborock|roomba)",
    "sensor": r"(tartı|terazi|baskül|kaç kiloyum|kilom kaç)",
}
COGUL = re.compile(r"\b(ışıklar|lambalar|prizler|hepsi|tümü|bütün|tüm|her ?şey)\w*")
ODALAR = ["yatak odası", "çalışma odası", "çocuk odası", "oturma odası", "misafir odası", "salon", "mutfak",
          "banyo", "koridor", "antre", "giriş", "balkon", "bahçe", "ofis", "tuvalet", "hol"]
UYGULAMALAR = {  # konuşma adı → aranacak anahtarlar (cihazın uygulama listesiyle eşlenir)
    "youtube": ("youtube",), "netflix": ("netflix",), "prime video": ("prime", "amazon"),
    "disney": ("disney",), "spotify": ("spotify",), "twitch": ("twitch",), "tabii": ("tabii",),
    "exxen": ("exxen",), "blutv": ("blutv", "blu tv"), "trt": ("trt",), "plex": ("plex",), "kodi": ("kodi",),
    "tarayıcı": ("browser", "tarayıcı", "web"), "apple tv": ("apple",), "youtube music": ("music",),
}
UYGULAMA_DESEN = {"youtube": r"(youtube|yutup|yutub|yu tüp|yutüp|yutip|yutıp|you tube)", "netflix": r"(netflix|netfliks)",
                  "prime video": r"(prime|amazon)", "disney": r"(disney|dizni)", "spotify": r"(spotify|spotifay)",
                  "twitch": r"(twitch|tviç)", "tabii": r"(tabii)", "exxen": r"(exxen|eksen)", "blutv": r"(blu ?tv)",
                  "trt": r"(trt)", "plex": r"(plex)", "kodi": r"(kodi)", "tarayıcı": r"(tarayıcı|internet tarayıcı)",
                  "apple tv": r"(apple tv)", "youtube music": r"(youtube music|yt music)"}

AC = r"(aç|açar|açsana|açın|yak|yaksana|çalıştır|başlat|devreye al)"
KAPAT = r"(kapat|kapa|söndür|durdur|kes)"
ARTIR = r"(aç|artır|arttır|yükselt|yükseğe|açar|açsana|fazlala|çoğalt|yukarı)"
AZALT = r"(kıs|kısar|kıssana|azalt|düşür|indir|alçalt|aşağı)"
SORU = re.compile(r"(\bkaç\b|kaçta|\bne\b|nedir|açık mı|kapalı mı|durum|son ölçüm|ölçümü|ölç|kaç kilo|pil\w*)")


@dataclass
class Komut:
    durum: str
    cihazlar: list[EvCihazi] = field(default_factory=list)
    yetenek: str = ""
    deger: Any = None
    adim: int | None = None
    goreli: float | None = None
    okuma: bool = False
    soru: str = ""
    adaylar: list[EvCihazi] = field(default_factory=list)
    tur: str = ""
    oda: str = ""
    icerik: str = ""          # 18 Kas: "YouTube'da X aç" → X ("müzik" gibi genel istek de olabilir)
    uygulama_adi: str = ""    # konuşmadaki uygulama ("youtube") — yanıt metni için

    @property
    def cihaz(self) -> EvCihazi | None:
        return self.cihazlar[0] if self.cihazlar else None


def _tur_bul(m: str) -> str:
    for tur, desen in TURLER.items():
        if re.search(r"\b" + desen, m):
            return tur
    return ""


def _oda_kok(oda: str) -> str:
    o = kucuk(oda).strip()
    if o.endswith(("sı", "si", "su", "sü")) and " " in o:
        return re.escape(o[:-1])           # "yatak odası" → "yatak odas" (odasında, odasındaki)
    if o.endswith("k"):
        return re.escape(o[:-1]) + "[kğ]"  # mutfak → mutfağa
    if o.endswith("t"):
        return re.escape(o[:-1]) + "[td]"
    return re.escape(o)


def oda_bul(m: str, cihazlar: list[EvCihazi]) -> str:
    odalar = {kucuk(c.oda) for c in cihazlar if c.oda} | set(ODALAR)
    for oda in sorted(odalar, key=len, reverse=True):
        if re.search(r"\b" + _oda_kok(oda) + r"\w*", m):
            return oda
    return ""


def _ad_eslesir(m: str, ad: str) -> bool:
    """Kullanıcı adı ('Başucu Lambası') metinde ekleriyle geçiyor mu? Her sözcüğün kökü aranır."""
    sozcukler = [s for s in _temiz(ad).split() if len(s) > 1]
    if not sozcukler:
        return False
    for s in sozcukler:
        kok = s[:-1] if len(s) > 4 and s[-1] in "ıiuü" else s
        kok = kok[:-1] + "[kğ]" if kok.endswith("k") else re.escape(kok)
        if not re.search(r"\b" + kok + r"\w*", m):
            return False
    return True


def _cihaz_turu(c: EvCihazi) -> str:
    if c.tur == "sensor" or "olcum_agirlik" in c.yetenekler:
        return "sensor"
    return c.tur


def _uygulama_bul(m: str) -> str:
    for ad in sorted(UYGULAMA_DESEN, key=len, reverse=True):
        if re.search(r"\b" + UYGULAMA_DESEN[ad], m):
            return ad
    return ""


def uygulama_secenegi(c: EvCihazi, ad: str) -> str:
    """Konuşmadaki uygulama adını cihazın kendi listesindeki seçeneğe çevirir ('' = yok)."""
    y = c.yetenekler.get("uygulama")
    if not y:
        return ""
    basliklar = y.protokol.get("adlar", {})
    anahtarlar = UYGULAMALAR.get(ad, (ad,))
    for s in y.secenekler:
        metin = f"{s} {basliklar.get(s, '')}".lower()  # cihaz dizgisi: Türkçe I kuralı uygulanmaz
        if ad == "youtube" and ("music" in metin or "kids" in metin):
            continue
        if any(a in metin for a in anahtarlar):
            return s
    return ""


UYGULAMA_GORUNEN = {"youtube": "YouTube", "netflix": "Netflix", "prime video": "Prime Video", "disney": "Disney+",
                    "spotify": "Spotify", "twitch": "Twitch", "youtube music": "YouTube Music", "tabii": "Tabii",
                    "exxen": "Exxen", "blutv": "BluTV", "trt": "TRT", "plex": "Plex", "kodi": "Kodi",
                    "tarayıcı": "Tarayıcı", "apple tv": "Apple TV"}
_ICERIK_AT = re.compile(
    r"^(televizyon\w*|tv\w*|tivi\w*|teve\w*|aç|açar|açsana|açın|açıver|açabilir\w*|aç\w*sın|çal|çalar|çalsana|çalın|"
    r"çalabilir\w*|çalıver|oynat\w*|başlat\w*|koy|koyar|koysana|koyabilir\w*|dinlet\w*|izlet\w*|göster\w*|ara|arat\w*|"
    r"bul|bana|bize|bir|şu|şunu|şunları|lütfen|hadi|haydi|da|de|ve|ile|üzerinden|uygulama\w*|içinde|için|"
    r"tekrar|yine|yeniden|mısın|misin|musun|müsün|mı|mi|mu|mü|şimdi|ama|bakalım|bakayım)$")


def icerik_ayikla(m: str, uyg: str, cihazlar: list[EvCihazi] | None = None, oda: str = "") -> str:
    """'televizyonda youtube'da tarkan şarkısı çal' → 'tarkan şarkısı'. Uygulama/TV/fiil/oda sözcükleri atılır."""
    desen = re.compile(r"^" + UYGULAMA_DESEN.get(uyg, re.escape(uyg)) + r"\S*")
    ad_kokleri = set()
    for c in cihazlar or []:
        for a in [c.kullanici_adi, *c.takma_adlar]:
            ad_kokleri |= {w for w in _temiz(a or "").split() if len(w) > 2}
    oda_desen = re.compile(r"^" + _oda_kok(oda) + r"\w*") if oda else None
    kalan = []
    m = re.sub(r"\b" + UYGULAMA_DESEN.get(uyg, re.escape(uyg)) + r"\S*", " ", m)  # çok sözcüklü ad ('you tube')
    sozcukler = m.split()
    if uyg in ("youtube music",):
        sozcukler = [w for w in sozcukler if not re.match(r"^music\S*", w)]
    for w in sozcukler:
        kok = re.sub(r"'.*$", "", w)
        if desen.match(w) or _ICERIK_AT.match(kok) or _ICERIK_AT.match(w):
            continue
        if any(kok.startswith(a[:max(3, len(a) - 2)]) for a in ad_kokleri):
            continue
        if oda_desen is not None and (oda_desen.match(w) or kok in oda.split()):
            continue
        if re.match(r"^(odası|odasında|odasındaki|odadaki|daki|deki)$", kok):
            continue
        kalan.append(kok)
    return " ".join(kalan).strip()


def giris_secenegi(c: EvCihazi, m: str) -> str:
    y = c.yetenekler.get("giris")
    r = re.search(r"hdmi\s*-?\s*(\d)", m)
    if not y or not r:
        return ""
    for s in y.secenekler:
        if re.search(r"hdmi\D*" + r.group(1) + r"\b", (s + " " + y.protokol.get("adlar", {}).get(s, "")).lower()):
            return s
    return ""


def _adim(m: str) -> int:
    n = None
    r = re.search(r"(\d+|" + "|".join(SAYI_SOZ) + r")\s*(kademe|adım|tık|birim|kere|defa)", m)
    if r:
        n = int(r.group(1)) if r.group(1).isdigit() else SAYI_SOZ[r.group(1)]
    if n:
        return max(1, min(n, 30))
    if re.search(r"\b(biraz|azıcık|bir tık|hafif|az\b)", m):
        return 2
    if re.search(r"\b(çok|iyice|epey|bayağı|baya)", m):
        return 8
    return 3


def _istek_coz(m: str, tur: str) -> tuple[str, Any, dict] | None:
    """Metinden (yetenek, değer, ek) çıkarır; anlaşılmazsa None. Cihazdan bağımsız."""
    ek: dict[str, Any] = {}
    soru = bool(SORU.search(m)) and not re.search(r"\b(yap|getir|ayarla|kıs|artır|azalt)\w*", m)
    # --- ölçüm / durum soruları
    if tur == "sensor":
        if re.search(r"(ölç|kaç|\bne\b|oku|son|göster|söyle|kilo)", m):
            return ("olcum_agirlik", None, {"okuma": True})
        return None
    if tur == "vacuum" and re.search(r"(pil|şarjı? kaç|batarya)", m) and not re.search(r"(gönder|dön|git)", m):
        return ("olcum_pil", None, {"okuma": True})
    if tur == "vacuum" and re.search(r"(ne durumda|nerede|ne yapıyor|durumu)", m):
        return ("durum_metni", None, {"okuma": True})
    # --- uygulama (içerik sözcükleri ses/kanal dalına düşmesin diye önce)
    uyg = _uygulama_bul(m)
    if uyg and (tur in ("tv", "") or re.search(r"\b(televizyon|tv)", m)):
        return ("uygulama", uyg, ek)
    # --- ses
    if re.search(r"\b(sessiz|sustur|sesi?ni? kapat|sesi?ni? kes)\w*", m) and not re.search(r"sessiz\w* (kapat|çıkar|kaldır)|sessizden", m):
        return ("sessiz", True, ek)
    if re.search(r"sessiz\w* (kapat|çıkar|kaldır)|sessizden çık|sesi?ni? geri aç", m):
        return ("sessiz", False, ek)
    if re.search(r"\bses(i|ini|in|ine|ini|ler)?\b|\bsesin\w*|\bses düzey", m):
        if soru and re.search(r"(kaç|ne|kaçta)", m):
            return ("ses_duzeyi", None, {"okuma": True})
        n = sayi_bul(m)
        if n is not None and not re.search(r"(kademe|adım|tık|kere|defa)", m) and re.search(r"(yap|getir|ayarla|olsun|'?[ae]\b|'?y[ae]\b|düzey|seviye|yüzde|%|\d)", m):
            return ("ses_duzeyi", n, ek)
        if re.search(r"\b" + AZALT, m):
            return ("ses_adim", "asagi", {"adim": _adim(m)})
        if re.search(r"\b" + ARTIR, m):
            return ("ses_adim", "yukari", {"adim": _adim(m)})
        return None
    # --- kanal
    if re.search(r"\bkanal", m):
        n = sayi_bul(m)
        if n is not None and not re.search(r"(kademe|adım|tık)", m):
            return ("kanal", n, ek)
        if re.search(r"(önceki|geri|aşağı|bir alt)", m):
            return ("kanal_adim", "asagi", {"adim": 1})
        if re.search(r"(sonraki|ileri|yukarı|değiştir|bir üst|geç)", m):
            return ("kanal_adim", "yukari", {"adim": 1})
        return None
    # --- giriş kaynağı
    if re.search(r"\bhdmi|\bkaynağ|\bgiriş\w* (değiştir|seç)", m):
        return ("giris", None, ek)
    # --- oynatma
    if tur == "tv":
        if re.search(r"\b(duraklat|beklet|pause)\w*", m):
            return ("oynatma", "duraklat", ek)
        if re.search(r"\b(devam ettir|devam et|oynat|play)\w*", m):
            return ("oynatma", "oynat", ek)
    # --- süpürge
    if tur == "vacuum":
        if re.search(r"(şarj|yuva|istasyon|eve dön|üsse|dock)", m):
            return ("supurge", "sarja_don", ek)
        if re.search(r"\b(durdur|duraklat|dur\b|beklet|kes)\w*", m):
            return ("supurge", "durdur", ek)
        if re.search(r"\b" + AC + r"\w*|\b(süpür(?!ge)|temizle|çalışsın|başlasın)\w*", m):
            return ("supurge", "baslat", ek)
        return None
    # --- parlaklık
    if tur == "light" and re.search(r"(parlaklı|yüzde|%|\bkıs\w*|\bloş|karart|azalt|artır|daha parlak|aydınlat)", m) \
            and not re.search(r"\b" + KAPAT + r"\w*", m):
        n = sayi_bul(m)
        if n is not None:
            return ("parlaklik", max(1, min(n, 100)), ek)
        if re.search(r"(kıs|loş|karart|azalt)", m):
            return ("parlaklik", None, {"goreli": -10 * _adim(m)})
        return ("parlaklik", None, {"goreli": 10 * _adim(m)})
    # --- güç durumu sorusu
    if soru and re.search(r"(açık mı|kapalı mı)", m):
        return ("guc", None, {"okuma": True})
    # --- güç
    if re.search(r"\b" + KAPAT + r"\w*", m):
        return ("guc", False, ek)
    if re.search(r"\b" + AC + r"\w*", m):
        return ("guc", True, ek)
    return None


def _destekler(c: EvCihazi, yetenek: str, okuma: bool) -> bool:
    if yetenek == "guc" and not okuma and (c.tur == "tv" and c.mac):
        return True  # açma: Wake-on-LAN
    if yetenek == "ses_adim":
        return "ses_adim" in c.yetenekler or ("ses_duzeyi" in c.yetenekler and c.yetenekler["ses_duzeyi"].yazilir)
    y = c.yetenekler.get(yetenek)
    if y is None:
        return False
    return y.okunur if okuma else y.yazilir


def _tur_adi(tur: str) -> str:
    return {"tv": "televizyon", "light": "ışık", "plug": "priz", "vacuum": "süpürge", "sensor": "tartı"}.get(tur, "cihaz")


def _belirtme(tur: str) -> str:
    return {"tv": "televizyonu", "light": "ışığı", "plug": "prizi", "vacuum": "süpürgeyi",
            "sensor": "tartıyı"}.get(tur, "cihazı")


def cozumle(metin: str, cihazlar: list[EvCihazi]) -> Komut:
    m = _temiz(metin)
    if not m:
        return Komut("ev_degil")
    # 1) kullanıcının verdiği ad/takma ad (en belirgin)
    adli = [c for c in cihazlar if any(_ad_eslesir(m, a) for a in [c.kullanici_adi, *c.takma_adlar] if a)]
    tur = _tur_bul(m)
    if not adli and not tur:
        # yalnız uygulama adı + "tv'de" yoksa ev komutu değildir ("YouTube'u aç" bilgisayarda)
        return Komut("ev_degil")
    oda = oda_bul(m, cihazlar)
    if adli:
        tur = tur or _cihaz_turu(adli[0])
    istek = _istek_coz(m, tur)
    if istek is None and not adli:
        return Komut("ev_degil")  # genel sözcük ('ışık hızı', 'televizyonda ne var'): eski yol karar versin
    if istek is None:
        return Komut("anlamadim", tur=tur, oda=oda,
                     soru=f"{_tur_adi(tur).capitalize()} için ne yapmamı istediğini anlayamadım.")
    yetenek, deger, ek = istek
    okuma = bool(ek.get("okuma"))
    # 2) aday cihazlar
    if adli:
        adaylar = adli
    else:
        adaylar = [c for c in cihazlar if _cihaz_turu(c) == tur or (tur == "light" and c.tur == "plug"
                                                                     and re.search(r"lamba", m))]
        if tur == "plug":
            adaylar = [c for c in cihazlar if c.tur == "plug"]
    if not adaylar:
        return Komut("yok", tur=tur, oda=oda, yetenek=yetenek,
                     soru=f"Bağlı bir {_tur_adi(tur)} bulamadım. Ev panelinden tarayıp ekleyebilirsin.")
    if oda:
        odadakiler = [c for c in adaylar if kucuk(c.oda) == oda]
        if not odadakiler:
            if len(adaylar) == 1 and not adaylar[0].oda:
                odadakiler = adaylar  # tek cihaz, odası atanmamış: o kastedilmiştir
            else:
                return Komut("sor", adaylar=adaylar, tur=tur, oda=oda, yetenek=yetenek,
                             soru=f"{oda.capitalize()} için kayıtlı {_tur_adi(tur)} yok. Hangisini kastettin: "
                                  + ", ".join(c.gorunen_ad for c in adaylar[:5]) + "?")
        adaylar = odadakiler
    destekleyen = [c for c in adaylar if _destekler(c, yetenek, okuma)]
    if len(adaylar) > 1 and not COGUL.search(m):
        hedef = destekleyen if len(destekleyen) == 1 else None
        if hedef is None:
            return Komut("sor", adaylar=adaylar, tur=tur, oda=oda, yetenek=yetenek,
                         soru=f"Hangi {_belirtme(tur)} kastediyorsun: "
                         + ", ".join(c.gorunen_ad for c in adaylar[:5]) + "?")
        adaylar = hedef
    if not destekleyen:
        c = adaylar[0]
        neden = c.erisim_notu if c.erisim != "hazir" else ""
        return Komut("desteklenmiyor", cihazlar=adaylar, yetenek=yetenek, deger=deger, tur=tur, oda=oda,
                     soru=f"{c.gorunen_ad} bunu desteklemiyor" + (f" ({neden})" if neden else "") + ".")
    hedefler = [c for c in adaylar if c in destekleyen]
    # 3) cihaza özgü değer çevirisi
    icerik, uyg_adi = "", ""
    if yetenek == "uygulama":
        uyg_adi = deger
        icerik = icerik_ayikla(m, deger, cihazlar, oda)
        secenek = uygulama_secenegi(hedefler[0], deger)
        if not secenek:
            return Komut("desteklenmiyor", cihazlar=hedefler, yetenek=yetenek, deger=deger, tur=tur, oda=oda,
                         soru=f"{hedefler[0].gorunen_ad} üzerinde {UYGULAMA_GORUNEN.get(deger, deger.title())} bulamadım.")
        deger = secenek
    if yetenek == "giris":
        secenek = giris_secenegi(hedefler[0], m)
        if not secenek:
            return Komut("anlamadim", cihazlar=hedefler, yetenek=yetenek, tur=tur, oda=oda,
                         soru="Hangi girişe geçeyim? Örneğin 'HDMI 1'.")
        deger = secenek
    return Komut("tamam", cihazlar=hedefler, yetenek=yetenek, deger=deger, adim=ek.get("adim"),
                 goreli=ek.get("goreli"), okuma=okuma, tur=tur, oda=oda, icerik=icerik, uygulama_adi=uyg_adi)


# -- kısa Türkçe sesli yanıtlar
def _ad(c: EvCihazi) -> str:
    return c.gorunen_ad


def yanit_metni(k: Komut, sonuclar: list) -> str:
    """Komut + adaptör Sonuc listesi → kısa sesli yanıt. Başarısızlık asla başarı gibi söylenmez."""
    if k.durum != "tamam":
        return k.soru or "Anlayamadım."
    basarili = [(c, s) for c, s in zip(k.cihazlar, sonuclar) if s.ok]
    if not basarili:
        s = sonuclar[0] if sonuclar else None
        if not (s and s.mesaj):
            return "Cihaza ulaşamadım."
        mesaj = s.mesaj if len(s.mesaj) <= 240 else s.mesaj[:237].rsplit(" ", 1)[0] + "…"
        return f"Olmadı: {mesaj}"
    c, s = basarili[0]
    cok = len(basarili) > 1
    ad = "Hepsi" if cok else _ad(c)
    y, d = k.yetenek, k.deger
    if k.okuma:
        v = s.deger
        if y == "olcum_agirlik":
            return f"Son ölçüm {str(v).replace('.', ',')} kilo." if v is not None else "Henüz ölçüm yok; tartıya çıkınca okurum."
        if y == "ses_duzeyi":
            return f"{ad} ses düzeyi {v}."
        if y == "olcum_pil":
            return f"{ad} pili yüzde {v}."
        if y == "guc":
            return f"{ad} {'açık' if v else 'kapalı'}."
        return f"{ad}: {v}."
    if y == "guc":
        if d and not s.dogrulandi:
            return f"{ad} için açma sinyali gönderdim; açıldığını doğrulayamadım."
        return f"{ad} {'açıldı' if d else 'kapatıldı'}."
    if y == "ses_duzeyi":
        return f"{ad} ses {s.deger if s.deger is not None else d}."
    if y == "ses_adim":
        return "Sesi kıstım." if d == "asagi" else "Sesi açtım."
    if y == "sessiz":
        return "Sessize aldım." if d else "Ses geri açıldı."
    if y == "uygulama":
        uyg = UYGULAMA_GORUNEN.get(k.uygulama_adi) or (str(d).split('.')[-1].title() if '.' in str(d) else str(d))
        bilgi = s.deger if isinstance(s.deger, dict) else {}
        if not s.dogrulandi:
            return f"{uyg} için isteği televizyona gönderdim ama açıldığını doğrulayamadım."
        if k.icerik and bilgi.get("icerik_eksik"):
            return f"{uyg} televizyonda açıldı ama '{k.icerik}' içeriğini gönderemedim; uygulamada aratman gerekebilir."
        if k.icerik:
            return f"{uyg} televizyonda açıldı, " + ("müzik çalıyor." if bilgi.get("genel") else f"{k.icerik} oynatılıyor.")
        return f"{uyg} televizyonda açıldı."
    if y in ("kanal", "kanal_adim"):
        return f"Kanal {d}." if y == "kanal" else "Kanalı değiştirdim."
    if y == "giris":
        return f"Giriş {d}."
    if y == "oynatma":
        return {"oynat": "Devam ediyor.", "duraklat": "Duraklattım.", "durdur": "Durdurdum."}.get(d, "Tamam.")
    if y == "supurge":
        return {"baslat": f"{ad} temizliğe başladı.", "durdur": f"{ad} durdu.",
                "sarja_don": f"{ad} şarja dönüyor."}.get(d, "Tamam.")
    if y == "parlaklik":
        return f"Parlaklık yüzde {int(s.deger if s.deger is not None else d)}."
    return "Tamam."


__all__ = ["Komut", "cozumle", "yanit_metni", "sayi_bul", "uygulama_secenegi", "icerik_ayikla"]
