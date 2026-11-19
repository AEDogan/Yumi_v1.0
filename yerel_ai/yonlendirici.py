"""B08 yönlendirici: niyet modeli + yerel işleyiciler. İnternetsiz: hesap, saat/tarih, sayaç, alarm, hatırlatıcı, kronometre, zar.

isle(metin) -> yanıt cümlesi (Yumi söyler) ya da None (Yumi eski yoldan devam: akıllı ev kalıpları, avatar komutları, Gemini).
Belirsizlik: güven >= EMIN uygula | ESIK..EMIN eylemse önce sor | < ESIK None (Gemini) | eksik bilgi -> geri sor | çözülemezse "anlayamadım".
Zamanlayıcıları mevcut beceri yürütür (yumi_skills/skills/time_skill.py: diske kaydeder, vakti gelince sesli uyarır).
"""
from __future__ import annotations

import datetime as dt
import random
import re
import threading
import time

from .bilgi import Doviz, Hava, gun_sec, sehir_ayikla
from .ev_medya import EvMedya
from .ogretme import OgretmeBellegi
from .spotify import KURULUM as SPOTIFY_KURULUM, Spotify
from .hesap import hesapla
from .sayi_zaman import AYLAR, GUNLER, kucuk, saat_coz, sure_s

ESIK, EMIN = 0.60, 0.85

# Canlı kabul (13 Kasım): "Gemini'ye sor …" / "ChatGPT'ye sor …" yerel cevabı atlar, soru doğrudan web sağlayıcısına gider.
# Whisper okunuşları: ceminay, cemini, jemini, gemini, çet ci pi ti, çetgipiti, chatgpt …
_WEB_AD = r"(?:gemini|gemin[aıi]y?|cemin[aıi]y?|ceminay|jemin[aıi]y?|cemini|chat\s?gpt|çet\s?gpt|çet\s?ci\s?pi\s?ti|çetcipiti|çat\s?ci\s?pi\s?ti)"
_WEB_EK = r"(?:\s?['’]?(?:y[ae]|[ae]))?(?=[\s,:;.!?-]|$)"
WEB_ONEK = re.compile(r"^\W*(?:hey\s+)?" + _WEB_AD + _WEB_EK + r"\s*(?:sor(?:ar\s*m[ıi]s[ıi]n|\s*bakal[ıi]m)?|söyle|de\s*ki)?\b[\s,:;.!?-]*(.*)$", re.I)
WEB_SONEK = re.compile(r"^(.*?)[\s,]*(?:diye\s+)?" + _WEB_AD + _WEB_EK + r"\s*(?:sor(?:ar\s*m[ıi]s[ıi]n)?|söyle)\W*$", re.I)


def web_zorla(metin: str):
    """'Gemini'ye sor X' / 'X, Gemini'ye sor' -> X; değilse None."""
    t = (metin or "").strip()
    m = WEB_SONEK.match(t)
    if m and m.group(1).strip():
        return m.group(1).strip(" ,.")
    m = WEB_ONEK.match(t)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None
BEKLEME_S = 40  # onay/eksik bilgi sorusunun geçerlilik süresi
ANLAMADIM = "Anlayamadım, tekrar söyler misin?"
EVET = re.compile(r"^(evet|olur|tamam|aynen|tabii|tabi|kesinlikle|yap|evet yap|olsun|doğru|he|hı hı)\b")
HAYIR = re.compile(r"^(hayır|yok|istemiyorum|vazgeç|vazgeçtim|iptal|boşver|boş ver|yapma|gerek yok|dur)\b")
IPTAL = re.compile(r"iptal|kapat|durdur|sil|kaldır|sustur|vazgeç")
TAKIP_S = 90  # B10: "ya sonraki gün?", "peki İzmir'de?" takip sorusunun geçerli olduğu süre
TAKIP_GUN = re.compile(r"^(?:ya|peki|e+|ee+|bir de|ya da)?\s*(?:bir\s+)?(?:sonraki|ertesi|öbür|bir sonraki|daha sonraki)\s+gün(?:ü|e)?\b")
TAKIP_ACIK_GUN = re.compile(r"^(?:ya|peki|bir de)\s+(yarın|bugün|yarından sonra|hafta sonu|bu hafta|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar)\w*\s*(?:ne olacak|nasıl|peki)?$")
TAKIP_SEHIR = re.compile(r"^(?:ya|peki|bir de)\s+(\S+?(?:['’]?(?:da|de|ta|te|nda|nde))|\S+\s+için)\s*(?:ne durumda|nasıl|ne olacak)?$")
TAKIP_DEGIL = {"ben", "sen", "biz", "siz", "onlar", "bura", "şura", "ora", "ev", "evde", "iş", "okul", "bende", "sende"}
KALAN = re.compile(r"kaç kaldı|ne kadar kaldı|kalan|listele|hangi|var mı|kaç tane")


def _soyle_sure(s):
    s = int(s)
    g, s = divmod(s, 86400); sa, s = divmod(s, 3600); dk, sn = divmod(s, 60)
    p = [f"{g} gün" if g else "", f"{sa} saat" if sa else "", f"{dk} dakika" if dk else "", f"{sn} saniye" if sn else ""]
    return " ".join(x for x in p if x) or "0 saniye"


def _sifat_sure(s):
    """'5 dakika' -> '5 dakikalık', '30 saniye' -> '30 saniyelik', '2 saat' -> '2 saatlik'."""
    m = _soyle_sure(s)
    son = m.split()[-1]
    return m + {"dakika": "lık", "saat": "lik", "saniye": "lik", "gün": "lük"}[son]


def _soyle_zaman(t: dt.datetime, simdi: dt.datetime):
    gun = (t.date() - simdi.date()).days
    on = "bugün" if gun == 0 else "yarın" if gun == 1 else f"{t.day} {AYLAR[t.month - 1].capitalize()} {GUNLER[t.weekday()].capitalize()}"
    return f"{on} saat {t:%H:%M}"


class ArkaIs:
    """Arka planda çalışacak iş + hemen söylenecek ön cümle. Çağrılınca (metin, sesli_mi) döndürür:
    sesli_mi False ise Yumi sonucu yalnız sohbete yazar (ör. müzik başladı), True ise sesli söyler (ör. hata)."""

    def __init__(self, is_, onsoz):
        self.is_, self.onsoz = is_, onsoz

    def __call__(self):
        try:
            return self.is_()
        except Exception as e:  # arka plan işi asla sessizce düşmesin
            return (f"Bunu yapamadım: {e}", True)


class Yonlendirici:
    def __init__(self, anlayici, beceri, simdi=dt.datetime.now, veri_klasoru=None, kalip=None, yerel_komut=None, bildir=None, cilve=None):
        """anlayici: yerel_ai.anla.Anlayici; beceri(ad, argumanlar) -> {"speech":...} (skill_engine.execute_skill).
        İnternet gereken yanıtlar (hava, döviz) çağrılabilir iş olarak döner; Yumi arka planda çalıştırıp söyler."""
        self.anlayici, self.beceri, self.simdi = anlayici, beceri, simdi
        self.hava, self.doviz = Hava(veri_klasoru), Doviz()
        self.bekleyen = None
        self.son = None  # tanı: son karar
        self.isleyici = {"saat_tarih": self._saat_tarih, "hesap_birim": self._hesap, "sayac": self._sayac, "alarm": self._alarm,
                         "hatirlatici": self._hatirlatici, "kronometre": self._kronometre, "yazi_tura_zar": self._zar,
                         "hava_durumu": self._hava, "doviz": self._doviz}
        self.bellek = OgretmeBellegi(veri_klasoru)
        self.spotify = Spotify(veri_klasoru)
        self.bildir = bildir  # uzun süren arka plan işinin sonucu (ör. Spotify onayı) Yumi'ye bildirilir
        self.cilve = cilve      # () -> karakter_kisilik.Cilve (seçili karaktere göre); None: hep sade
        self.son_hareket = None  # cilvenin istediği avatar hareketi (Yumi oynatır)
        self.onceki = None      # (metin, niyet): 'hayır onu demek istemedim' düzeltmesi için
        self.yeni_metin = None  # öğretilen ifade eski yoldan gidecekse Yumi bu metni kullanır
        self.ev = EvMedya(self, kalip=kalip, yerel_komut=yerel_komut)
        self.isleyici.update(self.ev.isleyiciler())
        # E06-3 (17 Kasım): ev cihazı komutları (TV/ışık/priz/süpürge/tartı) niyet modelinden ÖNCE yerelde çözülür;
        # cihaz/tür adı geçmeyen cümleler eski yola kalır. yumi_skills/ev/yumi_baglanti.py
        try:
            from yumi_skills.ev.yumi_baglanti import EvKomutlari
            self.ev_komut = EvKomutlari(beceri=getattr(getattr(beceri, "__self__", None), "smart_home", None))
        except Exception:
            self.ev_komut = None
        # Açılış rutinleri (12 Kasım, kullanıcı): YouTube eklenti önbelleği temizliği vb. — yerel_ai/rutin_isler.py
        from .rutin_isler import RutinIsler
        self.rutin = RutinIsler(veri_klasoru)

    # ------------------------------------------------------------ giriş
    def isle(self, metin: str, _derinlik=0):
        if _derinlik == 0:
            self.yeni_metin = None
            self.son_hareket = None
        k = kucuk(metin).strip(" .!?,")
        if _derinlik == 0:
            soru = web_zorla(metin)
            if soru:
                self.bekleyen = None
                self.son = {"niyet": "web_zorla", "guven": 1.0, "parcalar": []}
                self.yeni_metin = soru  # app eski yola (Gemini/ChatGPT) yalnız soruyu gönderir
                return None
        if self.bekleyen and time.monotonic() - self.bekleyen["t"] > BEKLEME_S:
            self.bekleyen = None
        if self.bekleyen:
            yanit = self._bekleyeni_isle(metin, k)
            if yanit is not None or self.yeni_metin:
                return yanit
        # 19 Kas gözlem: harfsiz girdi (yalnız emoji/simge/rakam-dışı işaret) niyet modeline gitmez — "😀🔥…" müzik_cal'a
        # yönleniyordu. En az 2 harf yoksa yerel niyet yok; metin olduğu gibi sohbet sağlayıcısına gider.
        if sum(ch.isalpha() for ch in metin) < 2:
            self.son = None
            return None
        if _derinlik == 0:
            yanit = self._ogretme(metin)
            if yanit is not None or self.yeni_metin:
                return yanit
        if _derinlik == 0:
            takip = self._takip(metin, k)
            if takip is not None:
                return takip
        if _derinlik == 0 and self.ev_komut is not None:
            try:
                ev = self.ev_komut.isle(metin)
            except Exception:
                ev = None
            if ev is not None:
                self.bekleyen = None
                self.son = {"niyet": "ev_komut", "guven": 1.0, "parcalar": []}
                return self._sonuc(ev, 1.0, "ev_komut", metin)
        r = self.anlayici.anla(metin) if self.anlayici else None
        # Platform adı + çalma fiili açıkça müzik isteğidir ('Tarkan'ı Spotify'da aç' modelde karakter_degistir 0,44 çıktı, 10 Kasım).
        if r is not None and r.get("niyet") != "muzik_cal" and re.search(r"\b(spotify|youtube|yt music)", k) \
                and re.search(r"\b(aç|çal|oynat|başlat|koy|dinlet)\w*", k) and "muzik_cal" in self.isleyici:
            # model yanlış niyetteyken parçaları da güvenilmez ('Tar'/'kan'): sorgu cümleden temizlenerek çıkarılır
            r = dict(r, niyet="muzik_cal", guven=max(float(r.get("guven", 0)), EMIN), parcalar=[])
        self.son = r
        if _derinlik == 0 and r:
            self.onceki = (metin, r["niyet"])
        if not r or r["niyet"] not in self.isleyici or r["guven"] < ESIK:
            return None
        sonuc = self.isleyici[r["niyet"]](metin, k, r)
        return self._sonuc(sonuc, r["guven"], r["niyet"], metin)

    def _sonuc(self, sonuc, guven, niyet, metin):
        if sonuc is None:
            return None
        tur = sonuc[0]
        if tur == "arka_onsoz":  # ('arka_onsoz', hemen_soylenecek, is_) -> ArkaIs
            return ArkaIs(sonuc[2], sonuc[1])
        if tur in ("soyle", "arka", "soyle_is"):  # arka/soyle_is: çağrılabilir iş (ağ/cihaz), Yumi arka planda çalıştırır
            return sonuc[1]
        if tur == "eksik":  # ('eksik', soru)
            self.bekleyen = {"tur": "eksik", "niyet": niyet, "metin": metin, "t": time.monotonic()}
            return sonuc[1]
        if tur == "eylem":  # ('eylem', soru_cumlesi, calistir[, her_zaman_sor])
            if guven >= EMIN and not (len(sonuc) > 3 and sonuc[3]):
                return sonuc[2]()
            self.bekleyen = {"tur": "onay", "calistir": sonuc[2], "t": time.monotonic()}
            return sonuc[1]
        return self.kisilik("anlamadim", ANLAMADIM)

    def _spotify_komut(self, metin):
        k = kucuk(metin)
        kimlik = re.search(r"spotify\s+(?:kimliği|kimliğim|client id|id)\s*[:=]?\s*([0-9a-f]{32})\b", k)
        if kimlik:
            self.spotify.kimlik_ayarla(kimlik.group(1))
            self._spotify_onay_baslat()
            return "Spotify kimliğini kaydettim. Tarayıcıda Spotify onay sayfasını açıyorum; kabul edince haber vereceğim."
        if re.search(r"spotify\S*\s+(?:bağlantısını\s+)?(?:kes|kopar|kaldır|çıkış)", k):
            self.spotify.kopar()
            return "Spotify bağlantısını kaldırdım."
        if re.search(r"spotify\S*\s+(?:hesabımı\s+)?bağla|spotify bağlantısı(?:nı)?\s+(?:kur|yap|aç)", k):
            if not self.spotify.client_id:
                return SPOTIFY_KURULUM
            self._spotify_onay_baslat()
            return "Tarayıcıda Spotify onay sayfasını açıyorum; kabul edince haber vereceğim."
        return None

    def _spotify_onay_baslat(self):
        def is_():
            sonuc = self.spotify.bagla()
            if self.bildir:
                self.bildir(sonuc)
        threading.Thread(target=is_, name="YumiSpotifyOnay", daemon=True).start()

    def _ogretme(self, metin):
        sp = self._spotify_komut(metin)
        if sp is not None:
            return sp
        b = self.bellek
        if b.liste_mi(metin):
            return b.liste_cumlesi()
        unut = b.unutma_mi(metin)
        if unut and b.bul(unut):
            b.unut(unut)
            return f"Tamam, '{unut}' ifadesini unuttum."
        og = b.ogretme_mi(metin)
        if og:
            ifade, komut = og
            b.ogren(ifade, komut)
            return f"Tamam, bundan sonra '{ifade}' deyince '{komut}' komutunu uygulayacağım."
        if b.duzeltme_mi(metin):
            if not self.onceki:
                return "Neyi düzelteyim? Önce bir komut söylemelisin."
            self.bekleyen = {"tur": "duzeltme", "onceki": self.onceki, "t": time.monotonic()}
            return "Tamam, ne demek istemiştin?"
        komut = b.bul(metin)
        if komut:
            yanit = self.isle(komut, _derinlik=1)
            if yanit is None:
                self.yeni_metin = komut  # komut eski yoldan (avatar/akıllı ev kalıbı/Gemini) gitsin
            return yanit if yanit is not None else None
        return None

    def _bekleyeni_isle(self, metin, k):
        b, self.bekleyen = self.bekleyen, None
        if b["tur"] == "duzeltme":  # 'ne demek istemiştin?' yanıtı: öğren ve uygula
            if HAYIR.match(k):
                return "Tamam, vazgeçtim."
            onceki_metin, onceki_niyet = b["onceki"]
            self.bellek.ogren(onceki_metin, metin)
            self.bellek.duzeltme_yaz(onceki_metin, onceki_niyet, metin)
            yanit = self.isle(metin, _derinlik=1)
            if yanit is None:
                self.yeni_metin = metin
                return None
            return f"Anladım, öğrendim. {yanit}" if isinstance(yanit, str) else yanit
        if b["tur"] == "onay":
            if EVET.match(k):
                return b["calistir"]()
            if HAYIR.match(k):
                return "Tamam, yapmıyorum."
            return None  # başka bir şey söyledi: normal akış
        # eksik bilgi: önceki cümle + yanıt birlikte çözülür ('alarm kur' + 'yedide')
        if HAYIR.match(k):
            return "Tamam, vazgeçtim."
        birlesik = f"{b['metin']} {metin}"
        sonuc = self.isleyici[b["niyet"]](birlesik, kucuk(birlesik), {"niyet": b["niyet"], "guven": 1.0, "parcalar": [], "ek_yanit": metin})
        if sonuc and sonuc[0] == "eksik":
            return self.kisilik("anlamadim", ANLAMADIM)
        return self._sonuc(sonuc, 1.0, b["niyet"], birlesik)

    def kisilik(self, durum, sade, **deg):
        """Cilve seçilirse karakterin cümlesi, değilse sade cümle. Seçilen hareket son_hareket'e yazılır."""
        motor = self.cilve() if self.cilve else None
        if motor:
            try:
                cumle, hareket = motor.sec(durum, **deg)
            except Exception:
                cumle, hareket = None, None
            if cumle:
                self.son_hareket = hareket
                return cumle
        return sade

    def _calistir_cilveli(self, ad, arg, durum, **deg):
        """Beceriyi çalıştırır; yalnız başarıda cilveli cümleye izin verir (hata/bilgi cümlesi değişmez)."""
        try:
            r = (self.beceri(ad, arg) if self.beceri else None) or {}
        except Exception as e:
            return f"Bunu yapamadım: {e}"
        sade = r.get("speech") or "Tamam."
        return self.kisilik(durum, sade, **deg) if r.get("ok", True) else sade

    def _calistir(self, ad, arg):
        try:
            r = self.beceri(ad, arg) if self.beceri else None
        except Exception as e:
            return f"Bunu yapamadım: {e}"
        return (r or {}).get("speech") or "Tamam."

    @staticmethod
    def _parca(r, tur):
        return next((p["metin"] for p in r.get("parcalar", []) if p["tur"] == tur), None)

    # ------------------------------------------------------------ işleyiciler
    def _saat_tarih(self, metin, k, r):
        s = self.simdi()
        gun = s + dt.timedelta(days=1) if "yarın" in k else s - dt.timedelta(days=1) if "dün" in k else s
        if re.search(r"\bsaat\b|kaç oldu|saati söyle", k) and not re.search(r"tarih|günlerden|ayın kaçı|hangi gün", k):
            return ("soyle", f"Saat {s:%H:%M}.")
        if re.search(r"\byıl|hangi yıl|yılındayız", k):
            return ("soyle", f"{s.year} yılındayız.")
        if re.search(r"hangi ay|aylardan", k):
            return ("soyle", f"{AYLAR[s.month - 1].capitalize()} ayındayız.")
        if re.search(r"günlerden|hangi gün|ne günü", k) and "tarih" not in k:
            on = "Yarın" if gun.date() > s.date() else "Dün" if gun.date() < s.date() else "Bugün"
            return ("soyle", f"{on} {GUNLER[gun.weekday()].capitalize()}.")
        on = "Yarın" if gun.date() > s.date() else "Dün" if gun.date() < s.date() else "Bugün"
        return ("soyle", f"{on} {gun.day} {AYLAR[gun.month - 1].capitalize()} {gun.year}, {GUNLER[gun.weekday()].capitalize()}.")

    def _hesap(self, metin, k, r):
        y = hesapla(metin)
        return ("soyle", y) if y else ("soyle", "Bu hesabı anlayamadım, tekrar söyler misin?")

    def _sayac(self, metin, k, r):
        if KALAN.search(k) and not re.search(r"\bkur|başlat|ayarla", k):
            return ("soyle", self._calistir("list_timers", {}))
        if IPTAL.search(k):
            return ("soyle", self._calistir("cancel_timer", {}))
        s = sure_s(metin)
        if not s:
            return ("eksik", "Kaç dakikalık sayaç kurayım?")
        etiket = self._parca(r, "icerik") or "Sayaç"
        return ("eylem", f"{_sifat_sure(s).capitalize()} sayaç kurayım mı?", lambda: self._calistir_cilveli("set_timer", {"duration_seconds": s, "label": etiket}, "sayac_kuruldu", sure=_soyle_sure(s)))

    def _zaman_hedefi(self, metin, k, sabah=False):
        s = self.simdi()
        sure = sure_s(metin) if re.search(r"sonra|içinde|sonraya", k) else None
        if sure:
            return s + dt.timedelta(seconds=sure)
        return saat_coz(metin, s, sabah_tercih=sabah)

    def _alarm(self, metin, k, r):
        if IPTAL.search(k) or KALAN.search(k):
            return None  # alarm iptal/listeleme beceride yok: eski yol (Gemini) yanıtlasın
        s = self.simdi()
        sure = sure_s(metin) if re.search(r"sonra|içinde|sonraya", k) else None
        if sure:  # '5 dakika sonraya alarm' -> saniye hassasiyetli sayaç
            return ("eylem", f"{_sifat_sure(sure).capitalize()} alarm kurayım mı?", lambda: self._calistir_cilveli("set_timer", {"duration_seconds": sure, "label": "Alarm"}, "sayac_kuruldu", sure=_soyle_sure(sure)))
        hedef = self._zaman_hedefi(metin, k, sabah=bool(re.search(r"uyandır|uyan", k)))
        if not hedef:
            return ("eksik", "Saat kaçta?")
        soru = f"{_soyle_zaman(hedef, s)} için alarm kurayım mı?"
        if hedef - s > dt.timedelta(hours=24):  # beceri yalnız 24 saat içini kurar; uzaksa hatırlatıcı olarak
            return ("eylem", soru, lambda: self._calistir("set_reminder", {"text": "Alarm", "remind_at_iso": hedef.isoformat(timespec="minutes")}))
        durum = "gece_alarm" if s.hour >= 23 or s.hour < 4 else "alarm_kuruldu"
        return ("eylem", soru, lambda: self._calistir_cilveli("set_alarm", {"alarm_time_hhmm": f"{hedef:%H:%M}", "label": "Alarm"}, durum, saat=f"{hedef:%H:%M}"))

    def _hatirlatici(self, metin, k, r):
        if IPTAL.search(k) and not re.search(r"hatırlat\w*\s*$", k):
            return None
        hedef = self._zaman_hedefi(metin, k)
        if not hedef:
            return ("eksik", "Ne zaman hatırlatayım?")
        icerik = self._parca(r, "icerik")
        if not icerik:  # zaman ve komut sözcüklerini atıp kalanı içerik say
            icerik = re.sub(r"\b(yumi|lütfen|bana|beni|bunu|hatırlat\w*|unutma\w*|sonra\w*|saat|bugün|yarın|akşam|sabah|öğlen|gece|dakika\w*|saniye\w*|"
                            r"buçu\w*|çeyrek|kala|geçe|de|da|te|ta)\b|\d+[:.']?\d*\w*", " ", kucuk(metin))

            icerik = " ".join(w for w in icerik.split() if not re.fullmatch(r"(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli)\w*", w)).strip()
        icerik = icerik or "Hatırlatma"
        return ("eylem", f"{_soyle_zaman(hedef, self.simdi())} '{icerik}' hatırlatayım mı?",
                lambda: self._calistir_cilveli("set_reminder", {"text": icerik, "remind_at_iso": hedef.isoformat(timespec="minutes")}, "hatirlatici_kuruldu",
                                              icerik=icerik, zaman=_soyle_zaman(hedef, self.simdi())))

    def _kronometre(self, metin, k, r):
        if re.search(r"durdur|bitir|kapat|dur\b", k):
            return ("soyle", self._calistir("stopwatch_control", {"action": "stop"}))
        if re.search(r"sıfırla", k):
            return ("soyle", self._calistir("stopwatch_control", {"action": "reset"}))
        if re.search(r"kaç|ne kadar|göster|geçti", k):
            return ("soyle", self._calistir("stopwatch_control", {"action": "status"}))
        return ("soyle", self._calistir("stopwatch_control", {"action": "start"}))

    def _zar(self, metin, k, r):
        if "yazı" in k or "tura" in k:
            return ("soyle", f"{random.choice(['Yazı', 'Tura'])} geldi.")
        if "zar" in k:
            n = 2 if re.search(r"\biki zar", k) else 1
            z = [random.randint(1, 6) for _ in range(n)]
            return ("soyle", f"{' ve '.join(map(str, z))} geldi." + (f" Toplam {sum(z)}." if n > 1 else ""))
        a = re.search(r"(\d+|\w+)\s+ile\s+(\d+|\w+)\s+arası", k)
        from .sayi_zaman import sayilar
        n = sayilar(a.group(0)) if a else []
        lo, hi = (int(n[0]), int(n[1])) if len(n) >= 2 else (1, 10)
        return ("soyle", f"{random.randint(min(lo, hi), max(lo, hi))}.")

    # ------------------------------------------------------------ internetli bilgi
    def _hava(self, metin, k, r):
        # Karakter adı konum sanılmasın ("Selam kaito hava nasıl" -> Kaito adlı köy; 9 Kasım). Kural: ek almamış
        # çıplak karakter adı şehir sayılmaz; yer eki varsa ("Victoria'da", "Sora için") şehirdir.
        # Yumi tüm karakter adlarını ve okunuşlarını karakter_adlari'na yazar (adların çoğu bir yerde köy adı).
        adlar = getattr(self, "karakter_adlari", set())
        # B10: parça bir kelimenin parçası olabilir ("Kaito" -> "Ka" konum sanılıp "Ka'da" okundu); tam kelimeye genişlet
        konumlar = [self._tam_kelime(metin, p) for p in r.get("parcalar", []) if p["tur"] == "konum"]
        def sehir_mi(m):
            if not sehir_ayikla(m):
                return False
            cipl = m.strip(" ?.!,")
            c = cipl.casefold()
            # 12 Kasım: kesik ad ("Akira" -> "Kira") da ad sayılır: adın 3+ harflik baş/son parçası (ek almamışsa)
            ad_gibi = c in adlar or (len(c) >= 3 and any(len(a) - len(c) <= 2 and (a.endswith(c) or a.startswith(c)) for a in adlar if " " not in a))
            return not ad_gibi or re.search(rf"(?<!\w){re.escape(cipl)}\s+için\b", metin, re.I)
        sehir = next((sehir_ayikla(m) for m in konumlar if sehir_mi(m)), None)
        if not sehir and r.get("ek_yanit"):  # 'Hangi şehir için?' sorusunun yanıtı: varsayılan olarak hatırla
            sehir = sehir_ayikla(r["ek_yanit"])
            if sehir:
                self.hava.varsayilan_yap(sehir)
        sehir = sehir or self.hava.varsayilan
        if not sehir:
            return ("eksik", "Hangi şehir için bakayım? Bundan sonra o şehri hatırlarım.")
        self.son_konu = {"niyet": "hava_durumu", "metin": metin, "sehir": sehir, "gun": gun_sec(metin, self.simdi()), "t": time.monotonic()}
        return ("arka", lambda: self.hava.yanit(metin, sehir, self.simdi()))

    @staticmethod
    def _tam_kelime(metin, p):
        bas, son = p.get("bas"), p.get("son")
        if bas is None or son is None:
            return p["metin"]
        while bas > 0 and not metin[bas - 1].isspace():
            bas -= 1
        while son < len(metin) and not metin[son].isspace():
            son += 1
        return metin[bas:son]

    def _takip(self, metin, k):
        """B10: son konu hava ise kısa takip soruları ("ya sonraki gün?", "peki yarın?", "ya İzmir'de?") aynı konuda
        cevaplanır. Önceden bağlam yoktu; "sonraki gün?" Gemini'ye gidip "Salı." cevabı alıyordu (9 Kasım kaydı)."""
        son = getattr(self, "son_konu", None)
        if not son or time.monotonic() - son["t"] > TAKIP_S or son["niyet"] != "hava_durumu":
            return None
        k = k.strip(" ?.!,")
        sehir, yeni = son["sehir"], None
        simdi = self.simdi()
        if TAKIP_GUN.search(k):
            tur, gun = son["gun"]
            temel = gun if tur in ("gun", "aksam") and gun else simdi.date()
            hedef = temel + dt.timedelta(days=1)
            fark = (hedef - simdi.date()).days
            yeni = "yarın hava" if fark == 1 else "yarından sonra hava" if fark == 2 else f"{GUNLER[hedef.weekday()]} hava"
            if fark > 6:
                return "O gün için henüz tahmin yok; en fazla bir hafta sonrasına bakabiliyorum."
        elif (m := TAKIP_ACIK_GUN.search(k)):
            yeni = f"{m.group(1)} hava"
        elif (m := TAKIP_SEHIR.search(k)):
            aday = sehir_ayikla(m.group(1))
            if not aday or len(aday) < 3 or aday.casefold() in getattr(self, "karakter_adlari", set()) or kucuk(aday) in TAKIP_DEGIL:
                return None
            sehir, yeni = aday, son["metin"]
        if yeni is None:
            return None
        self.son = {"niyet": "hava_durumu", "guven": 1.0, "parcalar": [], "takip": True}
        self.son_konu = {**son, "metin": yeni, "sehir": sehir, "gun": gun_sec(yeni, simdi), "t": time.monotonic()}
        return lambda: self.hava.yanit(yeni, sehir, self.simdi())

    def _doviz(self, metin, k, r):
        return ("arka", lambda: self.doviz.yanit(metin))
