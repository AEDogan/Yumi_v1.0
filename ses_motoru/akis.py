"""Kesintisiz konuşma akışı (B07): metni doğal sınırlardan böler, her bölümün sesini tek ve sürekli
bir ses çıkışında art arda çalar, bölümler arasına noktalamaya göre doğal durak koyar.

Karar (6 Kasım, araştırma özeti docs/3D-DISI-ISLER.md B07):
- Bölme cümle sonundan yapılır (tonlama en doğal). Yalnız İLK bölüm, cümle uzunsa ilk virgülden
  bölünür; böylece konuşma hızlı başlar, sonrası tam cümle olur. Sabit karakter sayısıyla bölme yok
  (kelime/tonlama bozulur, istek başı gecikme artar).
- Her bölümün baş/son sessizliği kırpılır, sonra durak tablosundaki süre eklenir: duraklar motorun
  rastgele boşluğundan değil, bu tablodan gelir. Okuma konuşmasında büyük sınır durakları ~0,5–0,6 s,
  kısa duraklar ~0,1–0,15 s (Campione & Véronis 2002); sohbet biraz daha kısa → nokta 0,42 s.
- Çalma tek sürekli çıkış akışıyla yapılır (dosya/oynatıcı değiştirme boşluğu yok). Akışlı motorlar
  (XTTS) bölümü parça parça doldurur; çalar üretim bitmeden çalmaya başlar.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque

import numpy as np

# Bölüm SONRASI durak (saniye). Konuşma doğallığı ayarı burada.
DURAKLAR = {".": 0.42, "!": 0.38, "?": 0.48, "…": 0.60, ";": 0.30, ":": 0.30, ",": 0.18, "\n": 0.65, "": 0.0}
ILK_BOLUM_VIRGUL_ESIGI = 90   # tamamlanmış ilk cümle bundan uzunsa virgülden bölünür
YARIM_CUMLE_VIRGUL_ESIGI = 40 # cümle henüz yazılıyorsa (LLM akışı) bu uzunluktan sonra virgülden bölünür
ILK_BOLUM_EN_AZ = 18          # virgülden ayrılan parça en az bu kadar karakter
XTTS_EN_UZUN = 170            # B11 (12 Kasım): XTTS Türkçede ~226 karakter üstünde bozuluyor/takılıyor; bölüm bunu aşmaz
ACLIK_ESIGI_S = 1.2           # çalarda bundan az ses kaldıysa sıradaki uzun cümle virgülden bölünür
KISALTMALAR = {"dr", "prof", "doç", "yrd", "av", "vb", "vs", "bkz", "örn", "st", "sn", "mr", "mrs", "no", "tel", "apt", "cad", "sok", "mah"}

_SON = re.compile(r"(\.\.\.|…|[.!?]+)([\"'”’)\]]*)(\s+|$)")
_PARAGRAF = re.compile(r"\n\s*\n|\n")
_VIRGUL = re.compile(r"[,;:](\s+)")


def temizle(metin: str) -> str:
    """Seslendirilmeyecek biçim işaretlerini atar (markdown yıldız, başlık, kod, madde)."""
    metin = re.sub(r"```.*?```", " ", metin, flags=re.S)
    metin = re.sub(r"[*_`#>]+", "", metin)
    metin = re.sub(r"^\s*[-•]\s+", "", metin, flags=re.M)
    metin = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", metin)
    from .sayi_okuma import sayilari_oku  # B10: "yüzde 98." -> "yüzde doksan sekiz." (sıra sayısı okunmasın)
    return re.sub(r"[ \t]+", " ", sayilari_oku(metin))


def _gercek_son(metin: str, m: re.Match, final: bool) -> bool:
    nokta = m.group(1)
    if m.group(3) == "" and not final:
        return False  # devamı gelmedi; "3." mü "3.5" mi bilinmez
    sonraki = metin[m.end():m.end() + 1]
    if sonraki and sonraki.islower():
        return False  # '"Harika!" dedi.' — Türkçede cümle büyük harfle başlar
    if nokta == ".":
        once = re.search(r"(\w+)$", metin[:m.start()])
        if once:
            kelime = once.group(1)
            if kelime.casefold() in KISALTMALAR or len(kelime) == 1:
                return False
            if kelime.isdigit():  # "5. sınıf" sıra sayısı: sonra küçük harf gelirse cümle bitmedi
                sonra = metin[m.end():m.end() + 1]
                if not sonra and not final:
                    return False
                if sonra and sonra.islower():
                    return False
    return True


def bolumle(metin: str, ilk: bool, final: bool, aclik: bool = False) -> tuple[list[tuple[str, float]], int]:
    """Akmakta olan metnin hazır kısmını bölümlere ayırır.

    metin: henüz seslendirilmemiş kısım. ilk: bu cevabın ilk bölümü mü. final: metin tamamlandı mı.
    aclik: çalarda az ses kaldı (Calar.kalan_s() < ACLIK_ESIGI_S); sıradaki uzun cümle virgülden bölünür.
    Dönüş: ([(bölüm metni, sonrasındaki durak s)], tüketilen karakter sayısı)
    """
    bolumler: list[tuple[str, float]] = []
    bas = 0
    while bas < len(metin):
        kalan = metin[bas:]
        aday = None
        for m in _SON.finditer(kalan):
            if _gercek_son(kalan, m, final):
                aday = m
                break
        p = _PARAGRAF.search(kalan)
        if p and (aday is None or p.start() < aday.start()) and kalan[:p.start()].strip():
            parca, durak, son = kalan[:p.start()], DURAKLAR["\n"], p.end()
        elif aday:
            isaret = aday.group(1)
            anahtar = "…" if isaret in ("...", "…") else isaret[-1]
            durak = DURAKLAR.get(anahtar, DURAKLAR["."])
            if "\n" in aday.group(3):
                durak = max(durak, DURAKLAR["\n"])
            parca, son = kalan[:aday.end(2)], aday.end()
        else:
            parca = None
        # İlk bölümde ya da çalar aç kalacakken: uzun cümlede ilk virgülden böl (sessizlik olmasın).
        if (ilk or aclik) and not bolumler:
            sinir = parca if parca is not None else kalan
            esik = ILK_BOLUM_VIRGUL_ESIGI if parca is not None else YARIM_CUMLE_VIRGUL_ESIGI
            if len(sinir) > esik:
                for v in _VIRGUL.finditer(sinir):
                    if v.start() >= ILK_BOLUM_EN_AZ and len(sinir) - v.end() >= ILK_BOLUM_EN_AZ:
                        parca, durak, son = sinir[:v.start() + 1], DURAKLAR[","], v.end()
                        break
        if parca is None:
            if final and kalan.strip():
                parca, durak, son = kalan, DURAKLAR[""], len(kalan)
            else:
                break
        if parca.strip():
            bolumler.append((parca.strip(), durak))
        bas += son
    bolumler = [p for metin_, durak_ in bolumler for p in _uzunu_bol(metin_, durak_)]
    if final and bolumler:
        son_metin = bolumler[-1][0]
        if son_metin and son_metin[-1].isalnum():
            son_metin += "."  # noktalamasız son: XTTS tonlaması cümle sonu gibi insin
        bolumler[-1] = (son_metin, 0.0)
    return bolumler, bas


def _uzunu_bol(metin: str, durak: float) -> list[tuple[str, float]]:
    """B11: XTTS sınırını aşan (çoğu noktalamasız) bölümü virgülden, yoksa kelime arasından böler.
    Parçalar arası kısa virgül durağı; son parça bölümün kendi durağını alır."""
    parcalar: list[tuple[str, float]] = []
    while len(metin) > XTTS_EN_UZUN:
        kesim = None
        for v in _VIRGUL.finditer(metin[:XTTS_EN_UZUN]):
            if v.start() >= 40:
                kesim = (v.start() + 1, v.end())
        if kesim is None:
            hedef = min(len(metin) // 2 + 10, 120) if len(metin) < 2 * XTTS_EN_UZUN else 120
            bosluk = metin.rfind(" ", 40, hedef + 1)
            if bosluk < 0:
                bosluk = metin.find(" ", hedef)
            if bosluk < 0:
                break
            kesim = (bosluk, bosluk + 1)
        parcalar.append((metin[:kesim[0]].strip(), DURAKLAR[","]))
        metin = metin[kesim[1]:].strip()
    if metin:
        parcalar.append((metin, durak))
    return parcalar


# --- ses işleme ----------------------------------------------------------------------------------

def kirp(x: np.ndarray, sr: int, bas: bool = True, son: bool = True, esik_db: float = -42.0,
         pay_s: float = 0.025) -> np.ndarray:
    """Baştaki/sondaki sessizliği kırpar, kenarlara 5 ms yumuşak geçiş koyar (tık sesi olmasın)."""
    if x.size == 0:
        return x
    pencere = max(1, int(sr * 0.01))
    n = x.size // pencere
    if n == 0:
        return x
    enerji = np.sqrt(np.mean(x[:n * pencere].reshape(n, pencere) ** 2, axis=1) + 1e-12)
    esik = max(10 ** (esik_db / 20), float(enerji.max()) * 10 ** (-38 / 20))
    sesli = np.nonzero(enerji > esik)[0]
    if sesli.size == 0:
        return x[:0]
    pay = int(sr * pay_s)
    i0 = max(0, sesli[0] * pencere - pay) if bas else 0
    i1 = min(x.size, (sesli[-1] + 1) * pencere + pay) if son else x.size
    y = x[i0:i1].astype(np.float32, copy=True)
    f = min(int(sr * 0.005), y.size // 2)
    if f:
        rampa = np.linspace(0.0, 1.0, f, dtype=np.float32)
        if bas:
            y[:f] *= rampa
        if son:
            y[-f:] *= rampa[::-1]
    return y


def yeniden_ornekle(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32, copy=False)
    n = int(round(x.size * sr_out / sr_in))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def wav_oku(veri: bytes) -> tuple[np.ndarray, int]:
    """WAV -> float32 mono. PCM 16/24/32 bit ve 32/64 bit float (Applio çıktısı) desteklenir."""
    import struct
    if veri[:4] != b"RIFF" or veri[8:12] != b"WAVE":
        raise ValueError("WAV değil")
    i, fmt, data = 12, None, None
    while i + 8 <= len(veri):
        kimlik, boy = veri[i:i + 4], struct.unpack("<I", veri[i + 4:i + 8])[0]
        govde = veri[i + 8:i + 8 + boy]
        if kimlik == b"fmt ":
            fmt = struct.unpack("<HHIIHH", govde[:16])
        elif kimlik == b"data":
            data = govde
        i += 8 + boy + (boy & 1)
    if fmt is None or data is None:
        raise ValueError("WAV parçaları eksik")
    bicim, kanal, sr, _, _, bit = fmt
    if bicim == 0xFFFE and len(veri) > 0:  # WAVE_FORMAT_EXTENSIBLE: alt biçim bit sayısından
        bicim = 3 if bit in (32, 64) and b"\x03\x00\x00\x00\x00\x00\x10\x00" in veri[:200] else 1
    if bicim == 3:
        x = np.frombuffer(data[: len(data) // (bit // 8) * (bit // 8)], dtype="<f4" if bit == 32 else "<f8").astype(np.float32)
    elif bit == 16:
        x = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    elif bit == 24:
        b = np.frombuffer(data[: len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608.0
    elif bit == 32:
        x = np.frombuffer(data[: len(data) // 4 * 4], dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"desteklenmeyen WAV: biçim {bicim}, {bit} bit")
    if kanal > 1:
        x = x[: x.size // kanal * kanal].reshape(-1, kanal).mean(axis=1)
    return np.clip(x, -1.0, 1.0), int(sr)


class SiraKilidi:
    """Geliş sırasıyla (FIFO) kilit: cümle 3, cümle 2'den önce üretilmesin."""

    def __init__(self) -> None:
        self._c = threading.Condition()
        self._sira = 0
        self._servis = 0

    def __enter__(self):
        with self._c:
            bilet = self._sira
            self._sira += 1
            while self._servis != bilet:
                self._c.wait()
        return self

    def __exit__(self, *_):
        with self._c:
            self._servis += 1
            self._c.notify_all()


# --- çalar ---------------------------------------------------------------------------------------

class Bolum:
    """Bir konuşma bölümü: üretici iş parçacığı doldurur (tek seferde ya da parça parça), çalar okur."""

    def __init__(self, metin: str, durak: float, kimlik: int, sinirlar=(), sr: int = 48000):
        self.metin, self.durak, self.kimlik, self.sinirlar = metin, durak, kimlik, tuple(sinirlar)
        self._kilit = threading.Lock()
        self._parcalar: deque[np.ndarray] = deque()
        self.sr = int(sr)  # çalar hızı; gelen ses buna çevrilir
        self.bitti = False
        self.iptal = False
        self.hata: str | None = None
        self.ilk_parca_geldi = False
        self.calinan = 0      # çalınan örnek sayısı
        self.toplam = 0       # eklenen örnek sayısı (kırpma sonrası)
        self.basladi_t: float | None = None
        self.bitti_t: float | None = None
        # B07 (10 Kasım): ön tampon ve kesinti ölçümü
        self.parca_sayisi = 0
        self.ilk_parca_t: float | None = None
        self.bas_t: float | None = None  # bu bölümün üretiminin başladığı an (ilk parçada hesaplanır)
        self.olusma_t = time.perf_counter()
        self.uretim_bitti_t: float | None = None
        self._onceki = None  # üretim sıralı: önceki bölümün üretimi bitince bu başlar
        self.ilk_parca_n = 0
        self.uretim_hizi: float | None = None  # üretilen ses sn / geçen sn (ilk parçadan sonra)
        self.ac_kalma = 0                      # çalarken veri bitti (duyulan kesinti) sayısı

    def calmaya_hazir(self, hiz: float) -> bool:
        """Kısa ön tampon (B07, 11 Kasım): üretim gerçek zamandan rahatça hızlıysa ilk parçada başlar (bekleme yok).
        Yavaşsa cümle ortasında aç kalmayacak kadar ses birikince başlar: hazır ≥ tahmini_süre × (1 − 0,85·hız)
        (0,85 = parça zamanlaması oynaklığı payı). Hız: önceki bölümler (`hiz`) ve bu bölümün canlı hızından küçüğü.
        Uzun sessizlik olmasın diye ilk parçadan en çok 2,5 s sonra yine başlar."""
        if self.bitti:
            return True
        if not self.ilk_parca_geldi:
            return False
        simdi = time.perf_counter()
        gecen = simdi - (self.ilk_parca_t or simdi)
        canli = ((self.toplam - self.ilk_parca_n) / self.sr / gecen) if (self.parca_sayisi >= 2 and gecen > 0.05) else None
        h = min(hiz, canli) if canli is not None else hiz
        if canli is None and self.bas_t is not None and self.ilk_parca_t is not None and self.ilk_parca_t - self.bas_t > 1.5:
            h = min(h, 0.6)  # ilk parça geç geldi (soğuk başlangıç, is_105: hız 0,5): yavaş say
        # 12 Kasım 18:25 (is_148/149): XTTS bu kartta tek başına da ~1,0x (YouTube etkisiz); hedef 1–1,5 s'de konuşmaya
        # başlamak. Kural: en az 0,8 s ses birikince (bir parça + oynaklık payı) ya da aç kalmama koşulu sağlanınca başla;
        # cümle bittiyse hemen. En çok bekleme: ilk parçadan 1,2 s (hız < 0,7 ölçüldüyse 2,5 s).
        if gecen >= (1.2 if h >= 0.7 else 2.5):
            return True
        tahmini = max(len(self.metin) / 14.0, self.toplam / self.sr)
        hazir = self.toplam / self.sr
        kalan = max(0.0, tahmini - hazir)
        if h >= 1.3 and canli is not None:
            return hazir >= 0.4
        return hazir >= max(0.8, 1.3 * kalan * (1.0 / max(h, 0.2) - 1.0))

    def ekle(self, x: np.ndarray, sr: int) -> None:
        if self.iptal:
            raise RuntimeError("bölüm iptal edildi")
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        if int(sr) != self.sr:
            x = yeniden_ornekle(x, int(sr), self.sr)
        with self._kilit:
            if not self.ilk_parca_geldi:
                x = kirp(x, self.sr, bas=True, son=False)
                if x.size == 0:
                    return
                self.ilk_parca_geldi = True
                self.ilk_parca_t = time.perf_counter()
                o = self._onceki; self._onceki = None
                self.bas_t = max(self.olusma_t, (o.uretim_bitti_t or 0.0) if o is not None else 0.0)
                self.ilk_parca_n = x.size
            self._parcalar.append(x)
            self.toplam += x.size
            self.parca_sayisi += 1

    def bitir(self, hata: str | None = None) -> None:
        """Üretim bitti: henüz çalınmamış kuyruktaki son sessizliği kırp."""
        with self._kilit:
            if self._parcalar:
                kuyruk = np.concatenate(list(self._parcalar))
                kirpik = kirp(kuyruk, self.sr, bas=False, son=True)
                self.toplam -= kuyruk.size - kirpik.size
                self._parcalar.clear()
                if kirpik.size:
                    self._parcalar.append(kirpik)
            self.hata = hata
            self.bitti = True
            self.uretim_bitti_t = time.perf_counter()
            self._onceki = None
            if self.ilk_parca_t is not None and self.parca_sayisi >= 2:
                gecen = time.perf_counter() - self.ilk_parca_t
                if gecen > 0.05:
                    self.uretim_hizi = (self.toplam - self.ilk_parca_n) / self.sr / gecen

    def oku(self, n: int) -> np.ndarray:
        with self._kilit:
            cikti, gerek = [], n
            while gerek and self._parcalar:
                p = self._parcalar[0]
                if p.size <= gerek:
                    cikti.append(p)
                    gerek -= p.size
                    self._parcalar.popleft()
                else:
                    cikti.append(p[:gerek])
                    self._parcalar[0] = p[gerek:]
                    gerek = 0
            y = np.concatenate(cikti) if cikti else np.zeros(0, np.float32)
            self.calinan += y.size
            return y

    @property
    def tukendi(self) -> bool:
        with self._kilit:
            return self.bitti and not self._parcalar


class Calar:
    """Tek sürekli çıkış akışı. Bölümler sırayla, aralarında durakla çalınır.

    Ses aygıtı fabrikası değiştirilebilir (test için). Varsayılan: sounddevice OutputStream.
    """

    def __init__(self, akis_fabrikasi=None, sr: int = 48000, blok: int = 480):
        self._fabrika = akis_fabrikasi or self._sd_akis
        self.sr = sr
        self.blok = blok
        self._kilit = threading.Lock()
        self._bolumler: deque[Bolum] = deque()
        self._akis = None
        self._sayac = 0
        self._bekleme = 0            # bölümler arası kalan durak (örnek)
        self._bos_bloklar = 0
        self.seviye = 0.0            # ağız için anlık ses düzeyi
        self.su_an: Bolum | None = None
        self._mesgul_onceki = False
        self.son_hata: str | None = None
        self.hiz = 1.0               # son bölümlerin üretim hızı (ses sn / sn); is_148/149: bu kartta XTTS ~1,0x (ölçüldükçe güncellenir)
        self.ac_kalma_toplam = 0

    # -- üretici tarafı
    def yeni_bolum(self, metin: str, durak: float, sinirlar=()) -> Bolum:
        with self._kilit:
            self._sayac += 1
            b = Bolum(metin, durak, self._sayac, sinirlar, self.sr)
            b._onceki = getattr(self, '_son_bolum', None)
            self._son_bolum = b
            self._bolumler.append(b)
        self._ac()
        return b

    def durdur(self) -> None:
        with self._kilit:
            for b in self._bolumler:
                b.iptal = True
            self._bolumler.clear()
            self._bekleme = 0
            self.su_an = None
            self.seviye = 0.0

    def hazir(self) -> bool:
        """Ses aygıtı açılabiliyor mu (açılamazsa uygulama eski oynatıcıya düşer)."""
        self._ac()
        return self._akis is not None

    def mesgul(self) -> bool:
        with self._kilit:
            return bool(self._bolumler)

    def bosaldi(self) -> bool:
        """Meşgulden boşa geçişte bir kez True (tur bitti bildirimi)."""
        simdi = self.mesgul()
        gecis = self._mesgul_onceki and not simdi
        self._mesgul_onceki = simdi
        return gecis

    def kalan_s(self, kr_saniye: float = 14.0) -> float:
        """Çalarda sırada bekleyen konuşma süresi (üretilmemiş bölümler metin uzunluğundan tahmin)."""
        with self._kilit:
            toplam = self._bekleme / self.sr
            for b in self._bolumler:
                if b.bitti:
                    toplam += (b.toplam - b.calinan) / b.sr
                else:
                    toplam += max(len(b.metin) / kr_saniye, b.toplam / b.sr) - b.calinan / b.sr
                toplam += b.durak
            return max(0.0, toplam)

    def konum(self) -> tuple[float, float]:
        b = self.su_an
        if not b or not b.sr:
            return 0.0, 0.0
        return b.calinan / b.sr, (b.toplam / b.sr if b.bitti else 0.0)

    def bakim(self, bosta_kapat_s: float = 3.0) -> None:
        """Ana iş parçacığından: uzun süre boşta kalan akışı kapat (aygıtı tutmasın)."""
        if self._akis is not None and not self.mesgul() and self._bos_bloklar * self.blok > bosta_kapat_s * self.sr:
            akis, self._akis = self._akis, None
            try:
                akis.stop()
                akis.close()
            except Exception:
                pass

    def kapat(self) -> None:
        self.durdur()
        self._bos_bloklar = 10 ** 9
        self.bakim(0)

    # -- aygıt
    def _sd_akis(self, geri_cagir):
        import sounddevice as sd
        return sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32", blocksize=self.blok,
                               latency="low", callback=lambda out, n, t, s: geri_cagir(out[:, 0], n))

    def _ac(self) -> None:
        if self._akis is not None:
            return
        try:
            self._bos_bloklar = 0
            self._akis = self._fabrika(self.doldur)
            self._akis.start()
        except Exception as hata:  # aygıt yoksa sessiz tüket, uygulama kilitlenmesin
            self.son_hata = f"{type(hata).__name__}: {hata}"
            self._akis = None

    # -- ses iş parçacığı
    def doldur(self, out: np.ndarray, n: int) -> None:
        out[:] = 0.0
        yazilan = 0
        with self._kilit:
            while yazilan < n and self._bolumler:
                b = self._bolumler[0]
                if b.iptal:
                    self._bolumler.popleft()
                    continue
                if self.su_an is not b:
                    # sıradaki bölüme geçmeden önce durak
                    if self._bekleme > 0:
                        k = min(self._bekleme, n - yazilan)
                        self._bekleme -= k
                        yazilan += k
                        continue
                    if not b.calmaya_hazir(self.hiz):
                        break  # henüz yeterli ses yok: bekle (sessizlik)
                    self.su_an = b
                    b.basladi_t = time.perf_counter()
                y = b.oku(n - yazilan)
                if y.size:
                    b._aciktı = False
                out[yazilan:yazilan + y.size] = y
                yazilan += y.size
                if y.size == 0:
                    if b.tukendi:
                        b.bitti_t = time.perf_counter()
                        if b.uretim_hizi:
                            self.hiz = 0.5 * self.hiz + 0.5 * min(b.uretim_hizi, 4.0)
                        self._bolumler.popleft()
                        self._bekleme = int(b.durak * self.sr)
                        self.su_an = None
                        continue
                    if b.calinan and not getattr(b, '_aciktı', False):
                        b.ac_kalma += 1; self.ac_kalma_toplam += 1; b._aciktı = True
                    break  # üretim sürüyor, veri bekleniyor
            if not self._bolumler:
                # durak süresi boşta da işler; yeni bölüm geç gelirse fazladan beklemez
                self._bekleme = max(0, self._bekleme - (n - yazilan))
        rms = float(np.sqrt(np.mean(out[:n] ** 2))) if n else 0.0
        self.seviye = 0.6 * self.seviye + 0.4 * rms
        self._bos_bloklar = 0 if self.mesgul() else self._bos_bloklar + 1
