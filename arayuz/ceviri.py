"""Türkçe Qt düğmeleri (18 Kasım): QMessageBox / QInputDialog / QFileDialog / QDialogButtonBox metinleri.

Açılışta ``turkce_yukle(app)`` çağrılır (cekirdek/app.py main, QApplication'dan hemen sonra):
1) PySide6'nın kendi çevirisi ``qtbase_tr.qm`` — yol QLibraryInfo'dan, yoksa PySide6 paketinin
   ``translations`` klasöründen (mutlak kullanıcı yolu yazılmaz; dağıtımda da paketle gelir).
2) Dosya yoksa/yüklenemezse ``_DugmeCevirmeni``: standart düğme metinlerini elle Türkçeye çevirir.
İkisi de kurulur; Qt son kurulan çevirmeni önce sorar, bulamazsa öncekine geçer.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

# Qt kaynak metni (ve & kısayollu biçimi) → Türkçe
DUGMELER = {
    "OK": "Tamam", "&OK": "&Tamam", "Cancel": "İptal", "&Cancel": "&İptal",
    "Yes": "Evet", "&Yes": "&Evet", "No": "Hayır", "&No": "&Hayır",
    "Yes to All": "Tümüne Evet", "Yes to &All": "Tümüne &Evet", "No to All": "Tümüne Hayır", "N&o to All": "Tümüne &Hayır",
    "Save": "Kaydet", "&Save": "&Kaydet", "Save All": "Tümünü Kaydet", "Open": "Aç", "&Open": "&Aç",
    "Close": "Kapat", "&Close": "&Kapat", "Apply": "Uygula", "Reset": "Sıfırla", "Help": "Yardım",
    "Discard": "Kaydetme", "Don't Save": "Kaydetme", "Close without Saving": "Kaydetmeden Kapat",
    "Abort": "Durdur", "Retry": "Yeniden Dene", "Ignore": "Yok Say", "Restore Defaults": "Varsayılanları Geri Yükle",
    "Show Details...": "Ayrıntıları Göster...", "Hide Details...": "Ayrıntıları Gizle...",
    "&Show Details...": "&Ayrıntıları Göster...", "&Hide Details...": "&Ayrıntıları Gizle...",
    "Look in:": "Konum:", "File &name:": "Dosya &adı:", "Files of type:": "Dosya türü:", "&Choose": "&Seç",
    "Back": "Geri", "Forward": "İleri", "Parent Directory": "Üst Klasör", "Create New Folder": "Yeni Klasör Oluştur",
    "List View": "Liste Görünümü", "Detail View": "Ayrıntılı Görünüm", "All Files (*)": "Tüm Dosyalar (*)",
    "Directory:": "Klasör:", "&New Folder": "&Yeni Klasör", "&Delete": "&Sil", "&Rename": "&Yeniden Adlandır",
}
BAGLAMLAR = {"QPlatformTheme", "QDialogButtonBox", "QMessageBox", "QInputDialog", "QFileDialog", "QColorDialog",
             "QErrorMessage", "QWizard", "QFontDialog", "QProgressDialog"}


class _DugmeCevirmeni(QTranslator):
    """qtbase_tr.qm bulunamazsa (ya da bir metni içermiyorsa) standart düğmeleri Türkçeye çevirir."""

    def translate(self, context, source_text, disambiguation=None, n=-1):  # noqa: D401 (Qt imzası)
        if context in BAGLAMLAR and source_text in DUGMELER:
            return DUGMELER[source_text]
        return ""

    def isEmpty(self):
        return False


def _ceviri_klasorleri() -> list[Path]:
    adaylar = []
    try:
        adaylar.append(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)))
    except Exception:
        pass
    try:
        import PySide6
        adaylar.append(Path(PySide6.__file__).resolve().parent / "translations")
        adaylar.append(Path(PySide6.__file__).resolve().parent / "Qt" / "translations")
    except Exception:
        pass
    return [a for a in dict.fromkeys(adaylar) if a.is_dir()]


def turkce_yukle(app=None) -> dict:
    """Türkçe çevirileri kurar. Dönüş: {'qtbase': yol|'' , 'yedek': True} (test/günlük için)."""
    app = app or QCoreApplication.instance()
    sonuc = {"qtbase": "", "yedek": False}
    if app is None:
        return sonuc
    QLocale.setDefault(QLocale(QLocale.Language.Turkish, QLocale.Country.Turkey))
    cevirmenler = getattr(app, "_yumi_cevirmenler", [])
    yedek = _DugmeCevirmeni(app)  # önce yedek: qtbase sonra kurulur ve önce sorulur; bulamadığını yedek verir
    if app.installTranslator(yedek):
        cevirmenler.append(yedek)
        sonuc["yedek"] = True
    for klasor in _ceviri_klasorleri():
        t = QTranslator(app)
        if t.load("qtbase_tr", str(klasor)) and app.installTranslator(t):
            cevirmenler.append(t)
            sonuc["qtbase"] = str(klasor / "qtbase_tr.qm")
            break
    app._yumi_cevirmenler = cevirmenler  # çöp toplayıcı silmesin
    return sonuc


__all__ = ["turkce_yukle", "DUGMELER"]
