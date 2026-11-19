"""Ev paneli 'Tara ve ekle' sekmesi için bulunan cihazlar bölümü (PySide6).

Mevcut panelin içine gömülür; renk/yazı tipi koymaz — tüm görünüm Yumi temasının nesne adlarından gelir
(#card, #cardTitle, #caption, #primaryButton), böylece 7 temada okunurluk temanın kendi oranlarıyla kalır.
Her kart: ad, tür/adres/model, erişim durumu, cihazdan sorgulanan yetenekler; ad/oda verme; gerekirse
Eşleştir / Anahtar gir; hazır cihazda yetenek kontrolleri. Ağ işleri arka plan iş parçacığında yapılır.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from .model import ANAHTAR_GEREKLI, ESLESTIRME_GEREKLI, HAZIR, STANDART, YALNIZ_BULUT, EvCihazi

ERISIM_METNI = {HAZIR: "Hazır", ESLESTIRME_GEREKLI: "Eşleştirme gerekli", ANAHTAR_GEREKLI: "Anahtar gerekli",
                YALNIZ_BULUT: "Yalnız bulut (masaüstünden bağlanamaz)", "desteklenmiyor": "Desteklenmiyor"}
TUR_METNI = {"tv": "Televizyon", "light": "Işık", "plug": "Priz", "vacuum": "Robot süpürge", "sensor": "Sensör / tartı",
             "speaker": "Hoparlör", "media": "Medya cihazı", "bridge": "Köprü", "unknown": "Cihaz"}
ANAHTAR_ALANI = {"tuya_yerel": ("yerel_anahtar", "Tuya yerel anahtarı (local key)"),
                 "miio": ("token", "miIO token (32 hane)"), "roomba": ("parola", "Roomba parolası")}
GUC_METNI = {"acik": "Açık", "bekleme": "Bekleme modunda (ağda)", "kapali": "Kapalı / ağda görünmüyor",
             "bilinmiyor": "Bilinmiyor"}
DESTEK_METNI = {"yumi_var": "Yumi destekliyor", "planli": "Destek planlı (henüz yok)",
                "kopru_gerekir": "Yalnız üretici bulutu/uygulaması (yerel yol yok)", "bilinmiyor": "Desteklenmiyor"}
YOKLAYICI_ADI = {"mdns": "mDNS", "ssdp": "SSDP/UPnP", "tuya": "Tuya yayını", "selam": "cihaz selamları",
                 "envanter": "ARP + üretici", "wifi": "Wi‑Fi kurulum ağları", "ble": "Bluetooth", "imza": "port imzası",
                 "bilgi_ucu": "cihaz bilgi uçları"}
SECENEK_METNI = {"baslat": "Başlat", "durdur": "Durdur", "sarja_don": "Şarja dön", "oynat": "Oynat",
                 "duraklat": "Duraklat", "yukari": "Yukarı", "asagi": "Aşağı"}


class _Is(QThread):
    bitti = Signal(object)
    ilerleme = Signal(str, int)

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.bitti.emit(self.fn())
        except Exception as e:  # iş parçacığı hatası panelde gösterilir
            self.bitti.emit(e)


def bos_neden(tarama) -> str:
    """Hiç cihaz çıkmadığında Türkçe neden (yoklayıcı notlarından)."""
    if tarama is None:
        return "Tarama sonucu alınamadı."
    d = {y.ad: y for y in tarama.yoklayicilar}
    nedenler = []
    env = d.get("envanter")
    if env and env.kayit_sayisi <= 1:
        nedenler.append("ağda modem dışında hiçbir adres yanıt vermedi (bilgisayar doğru Wi‑Fi'a bağlı mı? "
                        "misafir ağı / 'AP yalıtımı' açık olabilir)")
    if d.get("ssdp") and d["ssdp"].kayit_sayisi == 0 and d.get("mdns") and d["mdns"].kayit_sayisi == 0:
        nedenler.append("yayın (SSDP/mDNS) yanıtı gelmedi: güvenlik duvarı gelen UDP'yi engelliyor olabilir "
                        "ya da cihazlar kapalı")
    hatalar = [f"{YOKLAYICI_ADI.get(y.ad, y.ad)}: {'; '.join(y.notlar)[:120]}" for y in tarama.yoklayicilar
               if y.durum in ("hata", "zaman_asimi")]
    if hatalar:
        nedenler.append("çalışmayan tarayıcılar — " + " | ".join(hatalar))
    return "Hiç cihaz bulunamadı. " + ("Olası neden: " + "; ".join(nedenler) + "." if nedenler else
                                       "Cihazların açık ve bu bilgisayarla aynı Wi‑Fi ağında olduğundan emin ol.")


def yetenek_ozeti(c: EvCihazi) -> str:
    parcalar = []
    for ad, y in sorted(c.yetenekler.items()):
        etiket = STANDART.get(ad, (ad,))[0]
        if ad == "uygulama" and y.secenekler:
            adlar = y.protokol.get("adlar", {})
            ornek = [adlar.get(s, s) for s in y.secenekler[:4]]
            etiket += f" ({', '.join(ornek)}{'…' if len(y.secenekler) > 4 else ''})"
        elif not y.yazilir:
            etiket += " (okunur)"
        parcalar.append(etiket)
    return ", ".join(parcalar) if parcalar else "—"


class EvCihazPaneli(QWidget):
    """yonetici: yumi_skills.ev.yonetici.EvYoneticisi; odalar: () -> list[str]; oda_ekle: (ad) -> None."""
    tarandi = Signal(object)   # bulunan EvCihazi listesi
    degisti = Signal()         # ad/oda kaydedildi (Odalar sekmesi yenilensin)

    def __init__(self, yonetici_fn: Callable[[], Any], odalar: Callable[[], list[str]] | None = None, parent=None,
                 oda_ekle: Callable[[str], Any] | None = None):
        super().__init__(parent)
        self.setObjectName("odaKapsayici")
        self._yonetici_fn = yonetici_fn
        self._odalar = odalar or (lambda: [])
        self._oda_ekle = oda_ekle
        self._isler: list[_Is] = []
        self.hedef_oda = ""
        self.son_tarama = None
        kok = QVBoxLayout(self)
        kok.setContentsMargins(0, 4, 0, 0)
        ust = QHBoxLayout()
        self.tara_dugmesi = QPushButton("Ağı tara")
        self.tara_dugmesi.setToolTip("Wi‑Fi ağındaki ve Bluetooth'taki tüm cihazları bulur (salt okunur keşif); "
                                     "desteklenenlerin yeteneklerini cihazdan sorgular")
        self.tara_dugmesi.setObjectName("primaryButton")
        self.tara_dugmesi.clicked.connect(lambda: self.tara())
        self.ble_kutusu = QCheckBox("Bluetooth (tartı vb.)")
        self.ble_kutusu.setChecked(True)
        ust.addWidget(self.tara_dugmesi, 2)
        ust.addWidget(self.ble_kutusu, 1)
        kok.addLayout(ust)
        self.hedef_etiketi = QLabel("")
        self.hedef_etiketi.setWordWrap(True)
        self.hedef_etiketi.hide()
        kok.addWidget(self.hedef_etiketi)
        self.ilerleme_cubugu = QProgressBar()
        self.ilerleme_cubugu.setTextVisible(True)
        self.ilerleme_cubugu.hide()
        kok.addWidget(self.ilerleme_cubugu)
        self.durum = QLabel("Henüz taranmadı. Kayıtlı ev cihazları aşağıda; ağdaki her şeyi görmek için 'Ağı tara'.")
        self.durum.setObjectName("caption")
        self.durum.setWordWrap(True)
        kok.addWidget(self.durum)
        self.liste = QVBoxLayout()
        self.liste.setSpacing(8)
        kok.addLayout(self.liste)
        self.diger_baslik = QLabel("Ağda görülen diğer cihazlar")
        self.diger_baslik.setObjectName("cardTitle")
        self.diger_baslik.hide()
        kok.addWidget(self.diger_baslik)
        self.diger = QVBoxLayout()
        self.diger.setSpacing(4)
        kok.addLayout(self.diger)

    def hedef_oda_ayarla(self, oda: str):
        """'+ Cihaz' ile gelindi: taranan cihaz kartlarında oda bu olur."""
        self.hedef_oda = oda or ""
        self.hedef_etiketi.setText(f"Bulunan cihazı '<b>{oda}</b>' odasına eklemek için kartında "
                                   "'Bu odaya ekle'ye bas." if oda else "")
        self.hedef_etiketi.setVisible(bool(oda))

    @property
    def yonetici(self):
        return self._yonetici_fn()

    # ------------------------------------------------------------ iş parçacığı
    def _calistir(self, fn, bitince, mesaj: str, ilerleme=None, once=None):
        self.durum.setText(mesaj)
        i = _Is(fn)
        if ilerleme is not None:
            i.ilerleme.connect(ilerleme)
        if once is not None:
            once(i)
        self._isler.append(i)

        def son(sonuc):
            if i in self._isler:
                self._isler.remove(i)
            if isinstance(sonuc, Exception):
                self.tara_dugmesi.setEnabled(True)
                self.ilerleme_cubugu.hide()
                self.durum.setText(f"Olmadı: {type(sonuc).__name__}: {sonuc}")
                return
            bitince(sonuc)
        i.bitti.connect(son)
        i.finished.connect(i.deleteLater)
        i.start()

    # ------------------------------------------------------------ tarama / gösterim
    def tara(self, sure: float = 12.0):
        ble = self.ble_kutusu.isChecked()
        self.tara_dugmesi.setEnabled(False)
        toplam = 8 if ble else 7  # yoklayıcı sayısı (+ bilgi uçları); çubuk yaklaşık ilerler
        self.ilerleme_cubugu.setRange(0, toplam + 1)
        self.ilerleme_cubugu.setValue(0)
        self.ilerleme_cubugu.setFormat("Ağ taranıyor… %v/%m")
        self.ilerleme_cubugu.show()
        biten: list[str] = []
        i_ref: list = []

        def ilerle(ad: str, sayi: int):
            biten.append(f"{YOKLAYICI_ADI.get(ad, ad)}: {sayi}")
            self.ilerleme_cubugu.setValue(min(len(biten), toplam))
            self.durum.setText("Taranıyor — " + ", ".join(biten[-4:]))

        def bitti(cihazlar):
            self.tara_dugmesi.setEnabled(True)
            self.ilerleme_cubugu.setValue(toplam + 1)
            self.ilerleme_cubugu.hide()
            self.son_tarama = getattr(self.yonetici, "son_tarama", None)
            self.goster(cihazlar)
            diger = self.diger_goster(cihazlar)
            if cihazlar or diger:
                self.durum.setText(f"{len(cihazlar)} kontrol edilebilir ev cihazı, {diger} başka cihaz bulundu. "
                                   "Desteklenmeyenler de aşağıda nedeniyle listelenir.")
            else:
                self.durum.setText(bos_neden(self.son_tarama))
            self.tarandi.emit(cihazlar)
        self._calistir(lambda: self._tara_is(i_ref, sure, ble), bitti, "Ağ ve Bluetooth taranıyor…", ilerle,
                       once=i_ref.append)

    def _tara_is(self, i_ref: list, sure: float, ble: bool):
        def ilerleme(ad, sayi):
            if i_ref:
                i_ref[0].ilerleme.emit(ad, int(sayi))
        return self.yonetici.tara(sure=sure, ble=ble, ilerleme=ilerleme)

    def yenile(self):
        try:
            self.goster(self.yonetici.cihazlar())
        except Exception as e:
            self.durum.setText(f"Kayıt okunamadı: {e}")

    def goster(self, cihazlar: list[EvCihazi]):
        while self.liste.count():
            w = self.liste.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)  # deleteLater beklenirken eski kart üstte görünmesin
                w.deleteLater()
        if not cihazlar:
            bos = QLabel("Ev cihazı bulunamadı. Cihazın açık ve aynı Wi‑Fi ağında olduğundan emin ol.")
            bos.setObjectName("caption")
            bos.setWordWrap(True)
            self.liste.addWidget(bos)
            return
        sira = {HAZIR: 0, ESLESTIRME_GEREKLI: 1, ANAHTAR_GEREKLI: 2}
        for c in sorted(cihazlar, key=lambda c: (sira.get(c.erisim, 3), c.gorunen_ad)):
            self.liste.addWidget(self._kart(c))

    def diger_goster(self, cihazlar: list[EvCihazi]) -> int:
        """Bulucunun gördüğü ama kontrol kartı olmayan her cihaz: tür, üretici, adres, neden desteklenmediği."""
        while self.diger.count():
            w = self.diger.takeAt(0).widget()
            if w is not None:
                w.hide(); w.setParent(None); w.deleteLater()
        tarama = self.son_tarama
        if tarama is None:
            self.diger_baslik.hide()
            return 0
        kart_adresleri = {c.adres for c in cihazlar if c.adres} | {c.mac.upper() for c in cihazlar if c.mac}
        sayi = 0
        for b in tarama.cihazlar:
            if (b.adres and b.adres in kart_adresleri) or (b.mac and b.mac.upper() in kart_adresleri):
                continue
            if b.alan("bu_bilgisayar") or "(bu bilgisayar)" in (b.ad or ""):
                continue
            uretici = b.marka or b.alan("uretici") or ""
            ad = b.ad or b.alan("ana_makine") or (uretici and f"{uretici} cihazı") or b.aile_etiketi or "Tanınmayan cihaz"
            yer = b.adres or (f"Bluetooth {b.alan('ble_adres')}" if b.alan("ble_adres") else "")
            if b.kategori == "kisisel_ag":
                durum = "Ev otomasyonu dışında (bilgisayar/telefon/modem)"
            elif b.destek == "yumi_var":
                durum = "Eşleştirme/anahtar gerekli ya da cihaz yanıt vermedi" + (f" — {b.eslestirme}" if b.eslestirme else "")
            else:
                durum = DESTEK_METNI.get(b.destek, "Desteklenmiyor") + (f" — {b.baglanma}" if b.baglanma else "")
            satir = QLabel(f"<b>{ad}</b> · {b.tur_etiketi or 'Cihaz'}" + (f" · {uretici}" if uretici and uretici not in ad else "")
                           + (f" · {yer}" if yer else "") + (f" · {b.mac}" if b.mac else "") + f"<br>{durum}")
            satir.setObjectName("caption")
            satir.setWordWrap(True)
            self.diger.addWidget(satir)
            sayi += 1
        self.diger_baslik.setVisible(sayi > 0)
        return sayi

    # ------------------------------------------------------------ kart
    def _kart(self, c: EvCihazi) -> QFrame:
        kart = QFrame()
        kart.setObjectName("card")
        dikey = QVBoxLayout(kart)
        dikey.setContentsMargins(12, 10, 12, 10)
        baslik = QLabel(c.gorunen_ad)
        baslik.setObjectName("cardTitle")
        baslik.setWordWrap(True)
        dikey.addWidget(baslik)
        bilgi = " · ".join(x for x in (TUR_METNI.get(c.tur, c.tur), c.oda.title() if c.oda else "",
                                         c.adres or (c.mac if c.aile == "ble_tarti" else ""),
                                         " ".join(x for x in (c.marka, c.model) if x)) if x)
        alt = QLabel(bilgi)
        alt.setObjectName("caption")
        alt.setWordWrap(True)
        dikey.addWidget(alt)
        erisim = QLabel(f"Erişim: {ERISIM_METNI.get(c.erisim, c.erisim)}" + (f" — {c.erisim_notu}" if c.erisim_notu else ""))
        erisim.setWordWrap(True)
        dikey.addWidget(erisim)
        if c.protokol.get("bu_taramada_yok"):
            yok = QLabel("Bu taramada yanıt vermedi (kapalı ya da ağdan çıkmış olabilir); kayıtlı bilgiler gösteriliyor.")
            yok.setObjectName("caption")
            yok.setWordWrap(True)
            dikey.addWidget(yok)
        if c.tur == "tv" and c.protokol.get("cevrimici"):
            g = QLabel(f"Durum: {GUC_METNI.get(c.protokol['cevrimici'], c.protokol['cevrimici'])}"
                       + (f" (son bakış {c.protokol['cevrimici_zamani']})" if c.protokol.get("cevrimici_zamani") else ""))
            g.setWordWrap(True)
            dikey.addWidget(g)
        yet = QLabel("Yapabildikleri: " + yetenek_ozeti(c))
        yet.setWordWrap(True)
        dikey.addWidget(yet)
        uy = c.yetenekler.get("uygulama")
        if uy and uy.secenekler:
            adlar = uy.protokol.get("adlar", {})
            kaynak = uy.protokol.get("liste_kaynagi", "")
            kaynak_metni = {"cihaz": "TV'nin kendi listesinden", "tablo": "bilinen uygulamalar TV'de yoklandı"}.get(kaynak, "")
            ul = QLabel("Uygulamalar" + (f" ({kaynak_metni})" if kaynak_metni else "") + ": "
                        + ", ".join(adlar.get(x) or x for x in uy.secenekler[:30]) + ("…" if len(uy.secenekler) > 30 else ""))
            ul.setObjectName("caption")
            ul.setWordWrap(True)
            dikey.addWidget(ul)

        # ad / oda (dar panelde taşmasın: ad tam satır, oda + kaydet alt satır)
        ad = QLineEdit(c.kullanici_adi)
        ad.setPlaceholderText("Sesli komut adı (ör. Salon TV)")
        dikey.addWidget(ad)
        satir = QHBoxLayout()
        oda = QComboBox()
        oda.setEditable(True)
        odalar = list(dict.fromkeys([*(self._odalar() or []), *( [c.oda] if c.oda else [])]))
        oda.addItem("")
        oda.addItems(odalar)
        oda.setCurrentText(c.oda or self.hedef_oda)
        kaydet = QPushButton(f"Bu odaya ekle ({self.hedef_oda})" if self.hedef_oda and not c.oda else "Adı/odayı kaydet")
        if self.hedef_oda and not c.oda:
            kaydet.setObjectName("primaryButton")
        kaydet.clicked.connect(lambda: self._ad_ver(c, ad.text(), oda.currentText()))
        oda.lineEdit().setPlaceholderText("Oda")
        satir.addWidget(oda, 1)
        satir.addWidget(kaydet)
        dikey.addLayout(satir)

        # eşleştirme / anahtar
        aileler = c.protokol.get("erisim_aileler", {}) or {c.aile: [c.erisim, c.erisim_notu]}
        islem = QHBoxLayout()
        if any(d[0] == ESLESTIRME_GEREKLI for d in aileler.values()):
            b = QPushButton("Eşleştir")
            b.setObjectName("primaryButton")
            b.clicked.connect(lambda: self._eslestir(c))
            islem.addWidget(b)
        for aile, d in aileler.items():
            if d[0] == ANAHTAR_GEREKLI and aile in ANAHTAR_ALANI:
                b = QPushButton("Anahtar gir")
                b.clicked.connect(lambda _=False, a=aile: self._anahtar(c, a))
                islem.addWidget(b)
        if c.yetenekler:
            oku = QPushButton("Durumu oku")
            oku.clicked.connect(lambda: self._oku(c))
            islem.addWidget(oku)
        islem.addStretch()
        dikey.addLayout(islem)
        if c.erisim == HAZIR:
            kontroller = self._kontroller(c)
            if kontroller is not None:
                dikey.addWidget(kontroller)
        return kart

    def _kontroller(self, c: EvCihazi) -> QWidget | None:
        """Yetenek kontrolleri; dar panelde taşmasın diye en çok üç kısa satır (düğmeler / değer / seçim)."""
        kap = QWidget()
        kap.setObjectName("odaKapsayici")
        dikey = QVBoxLayout(kap)
        dikey.setContentsMargins(0, 0, 0, 0)
        yy = c.yetenekler
        dugmeler, degerler, secimler = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        if ("guc" in yy and yy["guc"].yazilir) or c.tur == "tv":
            destek, ipucu = (True, "")
            if c.tur == "tv" and hasattr(self.yonetici, "ac_destegi"):
                try:
                    destek, ipucu = self.yonetici.ac_destegi(c)
                except Exception:
                    pass
            for metin, deger in (("Aç", True), ("Kapat", False)):
                b = QPushButton(metin)
                b.clicked.connect(lambda _=False, d=deger: self._uygula(c, "guc", d))
                if deger and c.tur == "tv":
                    b.setEnabled(destek)
                    b.setToolTip(("Ağdan açar (Wake-on-LAN / platform yolu). Açılmazsa: " if destek else "") + ipucu)
                if not deger and not ("guc" in yy and yy["guc"].yazilir):
                    b.setEnabled(False)
                    b.setToolTip("Kapatma için TV ile eşleştirme gerekli")
                dugmeler.addWidget(b)
        if "ses_adim" in yy or ("ses_duzeyi" in yy and yy["ses_duzeyi"].yazilir):
            for metin, deger in (("Ses −", "asagi"), ("Ses +", "yukari")):
                b = QPushButton(metin)
                b.clicked.connect(lambda _=False, d=deger: self._uygula(c, "ses_adim", d, adim=2))
                dugmeler.addWidget(b)
        if "sessiz" in yy and yy["sessiz"].yazilir:
            b = QPushButton("Sessiz")
            b.clicked.connect(lambda: self._uygula(c, "sessiz", True))
            dugmeler.addWidget(b)
        for ad in ("ses_duzeyi", "parlaklik"):
            y = yy.get(ad)
            if y and y.yazilir:
                kutu = QLineEdit()  # QSpinBox temalarda biçimlenmiyor; QLineEdit tema rengini alır
                en_az, en_cok = int(y.en_az or 0), int(y.en_cok or 100)
                kutu.setValidator(QIntValidator(en_az, en_cok, kutu))
                kutu.setPlaceholderText(("Ses " if ad == "ses_duzeyi" else "Parlaklık % ") + f"{en_az}–{en_cok}")
                b = QPushButton("Ayarla")
                b.clicked.connect(lambda _=False, a=ad, k=kutu: k.text().strip() and self._uygula(c, a, int(k.text())))
                degerler.addWidget(kutu, 1)
                degerler.addWidget(b)
        for ad in ("uygulama", "supurge", "giris", "fan_hizi"):
            y = yy.get(ad)
            if y and y.yazilir and y.secenekler:
                kutu = QComboBox()
                adlar = y.protokol.get("adlar", {})
                for s in y.secenekler:
                    kutu.addItem(adlar.get(s) or SECENEK_METNI.get(s, s), s)
                b = QPushButton("Gönder" if ad == "supurge" else "Aç" if ad == "uygulama" else "Seç")
                b.clicked.connect(lambda _=False, a=ad, k=kutu: self._uygula(c, a, k.currentData()))
                secimler.addWidget(kutu, 1)
                secimler.addWidget(b)
        var = False
        for satir in (dugmeler, degerler, secimler):
            if satir.count():
                if satir is dugmeler:
                    satir.addStretch()
                dikey.addLayout(satir)
                var = True
        return kap if var else None

    # ------------------------------------------------------------ eylemler
    def _ad_ver(self, c: EvCihazi, ad: str, oda: str):
        y = self.yonetici
        if y.kayit.al(c.kimlik) is None:
            y.kayit.ekle(c)
        if oda and self._oda_ekle is not None and oda not in (self._odalar() or []):
            try:
                self._oda_ekle(oda)
            except Exception:
                pass
        y.kayit.ad_ver(c.kimlik, ad, oda)
        self.durum.setText(f"Kaydedildi: {ad or c.ad}" + (f" ({oda})" if oda else ""))
        self.yenile()
        self.degisti.emit()

    def _uygula(self, c: EvCihazi, yetenek: str, deger, adim: int | None = None):
        self._calistir(lambda: self.yonetici.uygula(c, yetenek, deger, adim=adim),
                       lambda s: self.durum.setText(("Tamam: " if s.ok else "Olmadı: ") + (s.mesaj or "")),
                       f"{c.gorunen_ad}: komut gönderiliyor…")

    def _oku(self, c: EvCihazi):
        def bitti(d):
            gorunur = {STANDART.get(k, (k,))[0]: v for k, v in d.items() if not k.startswith("_")}
            self.durum.setText(f"{c.gorunen_ad}: " + (", ".join(f"{k}: {v}" for k, v in gorunur.items()) or "okunamadı")
                               + (f" (hata: {d['_hatalar']})" if d.get("_hatalar") else ""))
        self._calistir(lambda: self.yonetici.durum(c), bitti, f"{c.gorunen_ad}: durum okunuyor…")

    def _eslestir(self, c: EvCihazi):
        aileler = c.protokol.get("erisim_aileler", {})
        android = aileler.get("androidtv", [""])[0] == ESLESTIRME_GEREKLI
        if QMessageBox.question(self, "Eşleştir",
                                f"{c.gorunen_ad} ekranında bir onay istemi (Android TV'de 6 haneli kod) çıkacak. "
                                "Kumandayla kabul et. Devam edilsin mi?") != QMessageBox.StandardButton.Yes:
            return
        if not android:
            self._calistir(lambda: self.yonetici.eslestir(c),
                           lambda s: (self.durum.setText(("Eşleşti: " if s.ok else "Olmadı: ") + s.mesaj), self.yenile()),
                           "TV'deki istemi kabul et (60 sn)…")
            return

        def kod_iste(s):
            if not s.ok:
                self.durum.setText("Olmadı: " + s.mesaj)
                return
            kod, tamam = QInputDialog.getText(self, "Android TV", "TV ekranındaki 6 haneli kod:")
            if tamam and kod.strip():
                self._calistir(lambda: self.yonetici.eslestir(c, "androidtv", kod.strip()),
                               lambda s2: (self.durum.setText(("Eşleşti: " if s2.ok else "Olmadı: ") + s2.mesaj),
                                           self.yenile()), "Kod doğrulanıyor…")
        self._calistir(lambda: self.yonetici.eslestir(c, "androidtv"), kod_iste, "TV'de kod gösteriliyor…")

    def _anahtar(self, c: EvCihazi, aile: str):
        alan, etiket = ANAHTAR_ALANI[aile]
        deger, tamam = QInputDialog.getText(self, "Anahtar", etiket + ":", QLineEdit.EchoMode.Password)
        if not tamam or not deger.strip():
            return
        self._calistir(lambda: self.yonetici.anahtar_ver(c, **{alan: deger.strip()}),
                       lambda r: (self.durum.setText(f"Anahtar kaydedildi (şifreli). Yetenekler: "
                                                     f"{', '.join(r.get('yetenekler', [])) or 'okunamadı'}"),
                                  self.yenile()), "Anahtar deneniyor…")


__all__ = ["EvCihazPaneli", "yetenek_ozeti", "bos_neden"]
