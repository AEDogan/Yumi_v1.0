"""B08: ev / TV / medya / ses / sahne / avatar niyetlerini mevcut yürütücülere bağlar (yeni cihaz kodu yok).
- Akıllı ev ışık/priz/klima/süpürge: modelin parçalarından mevcut kalıp eşleştiricinin (yumi_skills/dispatcher.py) bildiği standart cümle
  üretilir ("salon ışığı kapat") ve arka planda çalıştırılır (ağ/LAN olabilir).
- TV, medya, ses düzeyi, sahne, müzik: beceri doğrudan çağrılır (control_smart_tv, media_transport_control, run_routine, play_media_or_ambient).
- Avatar: Yumi'nin kendi komut cümlesine çevrilir (app._local_command), arayüz iş parçacığında.
Her işleyici ('eylem', onay_sorusu, calistir) / ('soyle', metin) / None (eski yol) döndürür; calistir çağrılabilir iş döndürebilir (arka plan).
"""
from __future__ import annotations

import re

from .sayi_zaman import kucuk, sayilar

ODALAR = ["yatak odası", "çalışma odası", "çocuk odası", "oturma odası", "misafir odası", "salon", "mutfak", "banyo", "koridor", "antre", "giriş",
          "balkon", "başucu", "bahçe", "ofis", "tuvalet"]
ISIK = [  # (kök deseni — ünsüz yumuşaması dahil, kalıp eşleştiricinin bildiği biçim)
    (r"ışıklar", "ışıkları"), (r"ışı[kğ]", "ışığı"), (r"lambalar", "lambaları"), (r"gece lamba", "lambayı"), (r"lamba", "lambayı"),
    (r"avize", "ışığı"), (r"abajur", "lambayı"), (r"ampul", "ışığı"), (r"led\b|led şerit", "ışığı"), (r"priz", "prizi")]
PLATFORM = [(r"youtube ?music\w*|yt music", "youtube_music", "YouTube Music"), (r"spotify\w*", "spotify", "Spotify"),
            (r"youtube\w*|yutup\w*|yutub\w*", "youtube", "YouTube")]
VARSAYILAN_PLATFORM = re.compile(r"(?:hep|her zaman|varsayılan\w*|bundan sonra|artık).*(?:spotify|youtube)|(?:spotify|youtube).*(?:olsun|kullan|varsayılan)")
TURLER = ["caz", "rock", "pop", "klasik", "arabesk", "rap", "lo-fi", "lofi", "elektronik", "metal", "türk sanat", "türk halk", "blues", "jazz", "reggae",
          "fasıl", "türkü", "slow", "akustik", "piyano"]
AC = re.compile(r"\b(aç|yak|çalıştır|başlat|açık|yan)\w*")
KAPAT = re.compile(r"\b(kapat|kapa|söndür|kapalı|durdur|kes)\w*")


def oda_bul(metin):
    m = kucuk(metin)
    return next((o for o in ODALAR if re.search(rf"\b{o}", m)), None)


def isik_bul(metin):
    m = kucuk(metin)
    return next((bicim for desen, bicim in ISIK if re.search(rf"\b{desen}", m)), None)


def oda_lokatif(oda):
    """'salon' -> 'salonda', 'mutfak' -> 'mutfakta', 'yatak odası' -> 'yatak odasında', 'antre' -> 'antrede'."""
    if oda[-1] in "ıiuü" and oda.endswith(("sı", "si", "su", "sü")):
        return oda + "nda" if oda[-1] in "ıu" else oda + "nde"
    unlu = [h for h in oda if h in "aeıioöuü"]
    u = "a" if unlu and unlu[-1] in "aıou" else "e"
    return oda + ("t" if oda[-1] in "çfhkpsşt" else "d") + u


def yon_bul(eylem, metin):
    """'aç' / 'kapat' / None. Önce modelin eylem parçası, yoksa cümle; 'karanlık' -> aç, 'aydınlık/göz kamaştırıyor' -> kapat değil (belirsiz)."""
    for kaynak in (eylem or "", kucuk(metin)):
        k = kucuk(kaynak)
        if KAPAT.search(k):
            return "kapat"
        if AC.search(k):
            return "aç"
    if re.search(r"karanlık|göremiyorum|hiçbir şey görünmüyor", kucuk(metin)):
        return "aç"
    return None


class EvMedya:
    def __init__(self, yonlendirici, kalip=None, yerel_komut=None):
        """kalip(metin) -> yanıt|None (skill_dispatcher.dispatch); yerel_komut(metin) -> yanıt|None (app._local_command, arayüz iş parçacığı)."""
        self.y, self.kalip, self.yerel_komut = yonlendirici, kalip, yerel_komut

    def isleyiciler(self):
        return {"cihaz_kontrol": self.cihaz, "tv_kontrol": self.tv, "medya_kontrol": self.medya, "ses_duzeyi": self.ses,
                "sahne_rutin": self.sahne, "muzik_cal": self.muzik, "avatar_hareket": self.avatar, "avatar_gorunum": self.avatar}

    # ------------------------------------------------------------ yardımcılar
    def _kalip_isi(self, standart):
        """Standart cümleyi kalıp eşleştiricide arka planda çalıştıran iş; eşleşmezse dürüstçe söyler."""
        def is_():
            r = self.kalip(standart) if self.kalip else None
            return r or f"'{standart}' komutunu çalıştıracak bağlı bir cihaz bulamadım. Akıllı ev panelinden cihaz ekleyebilirsin."
        return is_

    def _beceri_isi(self, ad, arg):
        return lambda: self.y._calistir(ad, arg)

    # ------------------------------------------------------------ akıllı ev
    def cihaz(self, metin, k, r):
        p = self.y._parca
        eylem = p(r, "eylem")
        # süpürge
        if re.search(r"süpürge|roborock", k):
            if re.search(r"şarj|yuva|istasyon", k):
                return ("eylem", "Süpürgeyi şarja göndereyim mi?", lambda: self._kalip_isi("süpürgeyi şarja gönder"))
            yon = yon_bul(eylem, metin)
            if yon is None:
                return None
            standart = "süpürgeyi başlat" if yon == "aç" else "süpürgeyi durdur"
            return ("eylem", f"{'Süpürgeyi başlatayım' if yon == 'aç' else 'Süpürgeyi durdurayım'} mı?", lambda: self._kalip_isi(standart))
        # klima / kombi derece
        if re.search(r"klima|kombi|termostat|ısıtıcı|derece", k):
            n = [x for x in sayilar(metin) if 5 <= x <= 35]
            if n and re.search(r"derece", k):
                cihaz = next((c for c in ("klima", "kombi", "termostat") if c in k), "kombi")
                standart = f"{cihaz} {int(n[0])} derece yap"
                return ("eylem", f"{cihaz.capitalize()} {int(n[0])} dereceye ayarlayayım mı?", lambda: self._kalip_isi(standart))
            return None  # aç/kapat ve 'biraz ısıt' kalıpta yok: eski yol (Gemini araçları)
        # ışık / priz
        nesne = isik_bul(p(r, "cihaz_turu") or "") or isik_bul(metin)
        if not nesne and re.search(r"karanlık|göremiyorum", k):
            nesne = "ışığı"
        if not nesne:
            return None
        if re.search(r"yüzde|%|parlak|kıs|loş|karart|azalt|artır|renk|mavi|kırmızı|yeşil|mor|beyaz", k) and not KAPAT.search(k):
            return None  # parlaklık/renk kalıpta yok: eski yol
        yon = yon_bul(eylem, metin)
        if yon is None:
            return None  # 'gözüm kamaşıyor' gibi yönü belirsiz: tahmin etme, eski yol
        oda = oda_bul(p(r, "oda") or metin)
        standart = " ".join(x for x in (oda, nesne, yon) if x)
        soru = f"{oda_lokatif(oda) + ' ' if oda else ''}{nesne} {'açayım' if yon == 'aç' else 'kapatayım'} mı?"
        ima = not (AC.search(k) or KAPAT.search(k))  # 'zifiri karanlık' gibi fiilsiz istek: her zaman önce sor
        return ("eylem", soru[0].upper() + soru[1:], lambda: self._kalip_isi(standart), ima)

    # ------------------------------------------------------------ TV
    def tv(self, metin, k, r):
        ad = "Salon TV" if "salon" in k else "Yatak Odası TV" if "yatak" in k else "televizyon"
        uyg = next((u for u in ("netflix", "youtube", "disney", "prime", "exxen", "blutv", "spotify", "trt", "tabii") if u in k), None)
        if uyg:
            return ("eylem", f"Televizyonda {uyg.capitalize()} açayım mı?", lambda: self._beceri_isi("control_smart_tv", {"device_name": ad, "action": "launch_app", "app_or_channel": uyg}))
        if re.search(r"ses", k):
            eylem = "mute" if re.search(r"sessiz|sustur|kapat", k) else "volume_down" if re.search(r"kıs|azalt|düşür", k) else "volume_up" if re.search(r"aç|artır|yükselt", k) else None
            if not eylem:
                return None
            return ("soyle_is", self._beceri_isi("control_smart_tv", {"device_name": ad, "action": eylem}))
        yon = yon_bul(None, metin)
        if yon is None:
            return None
        return ("eylem", f"Televizyonu {'açayım' if yon == 'aç' else 'kapatayım'} mı?",
                lambda: self._beceri_isi("control_smart_tv", {"device_name": ad, "action": "power_on" if yon == "aç" else "power_off"}))

    # ------------------------------------------------------------ medya / ses
    def medya(self, metin, k, r):
        if re.search(r"\b(kıs|azalt|sessize|sustur|sesi|sesini|bağırıyor|yükselt|duyamıyorum)\w*", k) and not re.search(r"duraklat|geç|atla|devam", k):
            return self.ses(metin, k, r)
        if re.search(r"sonraki|sıradaki|geç|atla|değiştir|başka", k):
            a = "next"
        elif re.search(r"önceki|geri dön|bir önceki", k):
            a = "previous"
        elif re.search(r"devam|kaldığın yerden|sürdür", k):
            a = "resume"
        elif re.search(r"duraklat|durdur|beklet|dur\b|dursun|bekle\b", k):
            a = "pause"
        elif re.search(r"kapat|sustur|bitir", k):
            a = "stop"
        else:
            return None
        return ("soyle_is", self._beceri_isi("media_transport_control", {"action": a}))

    def ses(self, metin, k, r):
        if re.search(r"yağmur sesi|şömine|beyaz gürültü|dalga sesi|orman sesi|kuş sesi|doğa sesi|ortam sesi", k):
            return self.muzik(metin, k, r)  # 'yağmur sesi aç' ses düzeyi sanılırsa
        if re.search(r"duraklat|durdur|sonraki|önceki|atla|devam et|kaldığın yerden|geç\b", k) and not re.search(r"\bses", k):
            return self.medya(metin, k, r)
        if re.search(r"sessize|sustur|sesi kapat|sessiz mod", k):
            return ("soyle_is", self._beceri_isi("media_transport_control", {"action": "mute"}))
        if re.search(r"yüzde|%|\d", k) and not re.search(r"biraz|az|çok", k):
            return None  # mutlak düzey ('sesi yüzde 30 yap') beceride yok: eski yol
        adim = 10 if re.search(r"iyice|çok|sonuna|en", k) else 3 if re.search(r"biraz|az|bir tık|azıcık", k) else 5
        if re.search(r"kıs|azalt|düşür|indir|bağırıyor|yüksek", k):
            motor = self.y.cilve() if self.y.cilve else None
            if motor and motor.tekrar_kis_mi():  # kısa sürede üçüncü 'kıs': karakterin cümlesi
                is_ = self._beceri_isi("media_transport_control", {"action": "volume_down", "steps": adim})
                return ("soyle_is", lambda: (is_(), self.y.kisilik("tekrar_kis", "Kıstım."))[1])
            return ("soyle_is", self._beceri_isi("media_transport_control", {"action": "volume_down", "steps": adim}))
        if re.search(r"aç|artır|yükselt|duyamıyorum|düşük|geri aç", k):
            return ("soyle_is", self._beceri_isi("media_transport_control", {"action": "volume_up", "steps": adim}))
        return None

    # ------------------------------------------------------------ sahne / müzik
    def sahne(self, metin, k, r):
        ad = self.y._parca(r, "sahne")
        if not ad:
            g = re.search(r"([a-zçğıöşü]+\s+(?:modu|mod|rutini))", k)
            ad = g.group(1) if g else None
        if not ad:
            return None
        ad = re.sub(r"(modu|mod)\w*$", "modu", kucuk(ad)).replace("rutinini", "rutini").replace("rutine", "rutini")
        return ("eylem", f"{ad.capitalize()} açayım mı?", lambda: self._beceri_isi("run_routine", {"routine_name": ad}))

    def platform_bul(self, k):
        for desen, kod, ad in PLATFORM:
            if re.search(desen, k):
                return kod, ad, desen
        return None

    def muzik(self, metin, k, r):
        if re.search(r"\b(dursun|durdur|duraklat|sus|kes)\w*", k) and not re.search(r"\b(çal|aç|koy|dinlet)\w*", k):
            return self.medya(metin, k, r)  # 'müzik dursun biraz' müzik isteği sanılırsa
        if re.search(r"\bses(i|ini)?\b.*\b(az|düşük|yüksek|kıs|aç|artır|azalt)|duyamıyorum|duymuyorum", k) and not re.search(r"yağmur sesi|şömine|dalga sesi|kuş sesi|doğa sesi|ortam sesi", k):
            return self.ses(metin, k, r)  # 'ses çok az duymuyorum aç biraz'
        pl = self.platform_bul(k)
        if pl and VARSAYILAN_PLATFORM.search(k):  # 'müziği hep spotify'dan aç' -> tercih olarak hatırla
            self.y.bellek.tercih_yap("muzik_platform", pl[0])
            if not re.sub(rf"['’]|\b(?:{pl[2]})|müzi\w*|şarkı\w*|hep|her zaman|varsayılan\w*|bundan sonra|artık|aç\w*|çal\w*|olsun|kullan\w*|uygulama\w*|\b(?:dan|den|tan|ten)\b", " ", k).strip():
                return ("soyle", f"Tamam, bundan sonra müziği {pl[1]} üzerinden açacağım.")
        platform = pl[0] if pl else self.y.bellek.tercih("muzik_platform", "youtube_music")  # varsayılan YouTube Music (kullanıcı, 11 Kasım)
        if not pl and re.search(r"yağmur sesi|şömine|beyaz gürültü|dalga sesi|orman sesi|kuş sesi|doğa sesi|ortam sesi", k):
            platform = "youtube"  # hazır ortam sesleri becerede YouTube'da
        if pl:  # platform adını sorgudan çıkar ('spotify'dan tarkan aç' -> 'tarkan')
            k = re.sub(rf"\b(?:{pl[2]})(?:'?(?:dan|den|tan|ten|da|de|ta|te|u|ü|ı|i))?\b", " ", k)
        def _parca(tur):  # parça yalnız platform adıysa ('Spotify') sorgu sayılmaz -> diğer parçaya geç
            v = self.y._parca(r, tur)
            return None if (v and pl and re.fullmatch(rf"(?:{pl[2]})\S*", kucuk(v).strip(" .!?,"))) else v
        sorgu = _parca("sanatci") or _parca("medya") or next((t for t in TURLER if re.search(rf"\b{t}", k)), None)
        if not sorgu:
            sorgu = re.sub(r"\b(yumi|lütfen|bana|bir|biraz|şarkı\w*|müzik\w*|çal\w*|aç\w*|koy\w*|dinlet\w*|başlat\w*|dinle\w*|istiyorum|bakalım|hemen|uyuyacağım|uyumak|uyurken|için|lazım)\b", " ", k)
            sorgu = " ".join(sorgu.split())
        sorgu = re.sub(r"['’]\w*", "", sorgu).strip()  # "tarkan'ı" -> "tarkan"
        if not sorgu:
            sorgu = "müzik"
        if pl and self.y._parca(r, "sanatci") and re.search(pl[2], kucuk(sorgu)):
            sorgu = re.sub(rf"(?:{pl[2]})\S*", "", kucuk(sorgu)).strip() or "müzik"
        # Geri bildirim: hemen "X açılıyor" söylenir; başarıda ikinci sesli cümle YOK (yalnız sohbete yazılır), sorun olursa sesli bildirilir.
        from .medya_oynat import bas_harf
        onsoz = self.y.kisilik("muzik_aciliyor", f"{bas_harf(sorgu)} açılıyor.", ad=bas_harf(sorgu))
        beceri = self._beceri_isi("play_media_or_ambient", {"query": sorgu, "platform_target": platform})
        ad = {"spotify": "Spotify", "youtube_music": "YouTube Music"}.get(platform, "YouTube")
        sanatci = self.y._parca(r, "sanatci")
        yalniz = bool(sanatci) and kucuk(sanatci).strip() == kucuk(sorgu).strip()

        def arama_sayfasi():
            sonuc = beceri()
            if sonuc.startswith("Bunu yapamadım"):
                return (f"{bas_harf(sorgu)} açılamadı: {sonuc[15:].strip(': ')}", True)
            return (f"Doğrudan çalamadım; {ad}'da '{bas_harf(sorgu)}' aramasını açtım, şarkıyı seçmen gerekiyor.", True)

        def is_(sorgu=sorgu, platform=platform, yalniz=yalniz):
            if platform == "spotify":
                if not self.y.spotify.client_id:  # oturum düştüyse cal() giriş sayfasını açıp yeniden bağlar (11 Kasım)
                    return arama_sayfasi()
                cevap = self.y.spotify.cal(sorgu, yalniz)
                if cevap and cevap.startswith("Spotify'da ") and cevap.endswith(" çalıyor."):
                    return (cevap, False)
                return (cevap, True) if cevap else arama_sayfasi()
            from .medya_oynat import oynat
            cevap = oynat(sorgu, platform, yalniz_sanatci=yalniz)
            return (cevap, False) if cevap else arama_sayfasi()
        return ("arka_onsoz", onsoz, is_)

    # ------------------------------------------------------------ avatar
    def avatar(self, metin, k, r):
        if re.search(r"\b(kıs|azalt|sessize|sustur|sesi|sesini|bağırıyor|yükselt|duyamıyorum)\w*", k):  # 'çok bağırıyor şunu kıs' avatar sanılırsa
            return self.ses(metin, k, r)
        if not self.yerel_komut:
            return None
        if re.search(r"dans|oyna", k):
            standart = "dans et"
        elif re.search(r"el salla|selam ver|merhaba de", k):
            standart = "el salla"
        elif re.search(r"\bbüyü|büyük ol", k):
            standart = "biraz büyü"
        elif re.search(r"küçül|küçük ol", k):
            standart = "biraz küçül"
        elif re.search(r"gizlen|saklan|kaybol", k):
            standart = "gizlen"
        elif re.search(r"görün|ortaya çık|geri gel", k):
            standart = "görün"
        elif re.search(r"dur\b|bırak|kes", k):
            standart = "hareketi durdur"
        else:
            return None
        y = self.yerel_komut(standart)
        return ("soyle", y) if y else None
