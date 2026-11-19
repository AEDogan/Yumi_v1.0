"""Ortak cihaz ve yetenek modeli (protokolden bağımsız)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Erişim durumları: masaüstü Yumi bu cihazı şu an kontrol edebilir mi?
HAZIR = "hazir"                       # ek bilgi gerekmeden okunur/yazılır
ANAHTAR_GEREKLI = "anahtar_gerekli"   # yerel anahtar/belirteç (Tuya local key, miIO token...)
ESLESTIRME_GEREKLI = "eslestirme_gerekli"  # TV ekranında onay, düğmeye basma, PIN
YALNIZ_BULUT = "yalniz_bulut"         # yerel yol yok → Android/bulut (kapsam dışı)
DESTEKLENMIYOR = "desteklenmiyor"     # adaptör yok / ev otomasyonu dışı
ERISIM_DURUMLARI = (HAZIR, ANAHTAR_GEREKLI, ESLESTIRME_GEREKLI, YALNIZ_BULUT, DESTEKLENMIYOR)

# Yetenek tipleri
BOOL, TAMSAYI, ONDALIK, SECIM, METIN, EYLEM = "bool", "int", "float", "enum", "str", "action"

# Standart yetenek adları → (Türkçe etiket, varsayılan tip). Adaptörler bu adları kullanır;
# komut eşleme ve panel yalnız bu sözlüğü bilir.
STANDART = {
    "guc": ("Aç/kapat", BOOL),
    "parlaklik": ("Parlaklık", TAMSAYI),
    "renk": ("Renk", METIN),
    "renk_sicakligi": ("Renk sıcaklığı", TAMSAYI),
    "ses_duzeyi": ("Ses düzeyi", TAMSAYI),
    "ses_adim": ("Sesi aç/kıs (adım)", SECIM),
    "sessiz": ("Sessize al", BOOL),
    "kanal": ("Kanal", TAMSAYI),
    "kanal_adim": ("Kanal ileri/geri", SECIM),
    "giris": ("Giriş kaynağı", SECIM),
    "oynatma": ("Oynat/duraklat/durdur", SECIM),
    "uygulama": ("Uygulama aç", SECIM),
    "tus": ("Kumanda tuşu", SECIM),
    "supurge": ("Süpürge (başlat/durdur/şarja dön)", SECIM),
    "mod": ("Çalışma kipi", SECIM),
    "hedef_sicaklik": ("Hedef sıcaklık", ONDALIK),
    "fan_hizi": ("Fan hızı", SECIM),
    "olcum_agirlik": ("Ağırlık", ONDALIK),
    "olcum_sicaklik": ("Sıcaklık", ONDALIK),
    "olcum_nem": ("Nem", ONDALIK),
    "olcum_guc": ("Anlık güç", ONDALIK),
    "olcum_akim": ("Akım", ONDALIK),
    "olcum_gerilim": ("Gerilim", ONDALIK),
    "olcum_pil": ("Pil", TAMSAYI),
    "durum_metni": ("Durum", METIN),
}


@dataclass
class Yetenek:
    ad: str                      # STANDART anahtarı
    tip: str
    okunur: bool = True
    yazilir: bool = False
    en_az: float | None = None
    en_cok: float | None = None
    adim: float | None = None
    birim: str = ""
    secenekler: list[str] = field(default_factory=list)
    kaynak: str = ""             # nereden çıkarıldı (ör. "UPnP RenderingControl SCPD", "webOS listApps")
    guven: str = "kesin"         # kesin: cihaz bildirdi | tahmin: değer kalıbından çıkarıldı
    protokol: dict[str, Any] = field(default_factory=dict)  # adaptöre özel (DP no, servis URL...)

    @property
    def etiket(self) -> str:
        return STANDART.get(self.ad, (self.ad, ""))[0]

    def deger_dogrula(self, deger: Any) -> Any:
        """Yazılacak değeri tipine göre doğrular/kırpar; geçersizse ValueError."""
        if not self.yazilir:
            raise ValueError(f"'{self.etiket}' yalnız okunur")
        if self.tip == BOOL:
            if isinstance(deger, str):
                deger = deger.casefold() in ("1", "true", "ac", "aç", "acik", "açık", "on", "evet")
            return bool(deger)
        if self.tip in (TAMSAYI, ONDALIK):
            try:
                sayi = float(deger)
            except (TypeError, ValueError):
                raise ValueError(f"'{self.etiket}' için sayı gerekli") from None
            if self.en_az is not None:
                sayi = max(self.en_az, sayi)
            if self.en_cok is not None:
                sayi = min(self.en_cok, sayi)
            return int(round(sayi)) if self.tip == TAMSAYI else sayi
        if self.tip == SECIM:
            if self.secenekler:
                for s in self.secenekler:
                    if str(deger).casefold() == s.casefold():
                        return s
                raise ValueError(f"'{deger}' geçerli değil; seçenekler: {', '.join(self.secenekler[:12])}")
            return str(deger)
        if self.tip == EYLEM:
            return None
        return str(deger)


@dataclass
class EvCihazi:
    kimlik: str                  # kalıcı kimlik (UDN, MAC, Tuya gwId, BLE adresi...)
    ad: str
    tur: str                     # cihaz_aileleri.TURLER anahtarı
    aile: str                    # protokol ailesi (webos, tizen, upnp_av, tuya, ble_tarti...)
    adres: str = ""
    mac: str = ""
    marka: str = ""
    model: str = ""
    erisim: str = DESTEKLENMIYOR
    erisim_notu: str = ""
    yetenekler: dict[str, Yetenek] = field(default_factory=dict)
    protokol: dict[str, Any] = field(default_factory=dict)   # adaptöre özel kalıcı veri (sır DEĞİL)
    oda: str = ""
    kullanici_adi: str = ""
    takma_adlar: list[str] = field(default_factory=list)
    yan_kimlikler: list[str] = field(default_factory=list)  # eşleştirmede kullanılan diğer kimlikler
    ek_aileler: list[str] = field(default_factory=list)     # aynı cihazdaki diğer adaptörler
    son_gorulme: str = ""

    @property
    def gorunen_ad(self) -> str:
        return self.kullanici_adi or self.ad or self.adres or self.kimlik

    def yetenek_ekle(self, y: Yetenek) -> None:
        """Aynı yetenek iki adaptörden gelirse yazılabilir/kesin olan kalır."""
        eski = self.yetenekler.get(y.ad)
        if eski is None or (y.yazilir and not eski.yazilir) or (eski.guven != "kesin" and y.guven == "kesin"
                                                                and y.yazilir == eski.yazilir):
            self.yetenekler[y.ad] = y

    def sozluk(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def sozlukten(cls, veri: dict[str, Any]) -> "EvCihazi":
        veri = dict(veri)
        yet = {k: Yetenek(**v) for k, v in (veri.pop("yetenekler", None) or {}).items()}
        bilinen = {f for f in cls.__dataclass_fields__}
        c = cls(**{k: v for k, v in veri.items() if k in bilinen})
        c.yetenekler = yet
        return c


@dataclass
class Sonuc:
    """Adaptör işlem sonucu: başarısızlık asla başarı gibi gösterilmez (E05)."""
    ok: bool
    mesaj: str = ""
    deger: Any = None
    dogrulandi: bool = False     # yazmadan sonra cihazdan geri okunarak doğrulandı mı
