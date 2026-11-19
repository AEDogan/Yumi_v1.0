from typing import Any, Dict, List

import json

from PySide6.QtCore import QMimeData, Qt, QThread, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QMenu,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .engine import YumiSkillEngine
from .device_catalog import DEVICE_CATEGORIES, INTEGRATIONS, device_types_for_category, integration_by_id, integrations_for_device_type


class _AsyncBridgeWorker(QThread):
    finished_signal = Signal(dict)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
            self.finished_signal.emit(res)
        except Exception as e:
            self.finished_signal.emit({"ok": False, "speech": str(e)})


class AssignDeviceDialog(QDialog):
    """Bir odaya cihaz atamak veya yeni cihaz eklemek için açılan pencere."""

    def __init__(self, room_name: str, engine: YumiSkillEngine, parent=None):
        super().__init__(parent)
        self.room_name = room_name
        self.engine = engine
        self.setWindowTitle(f"'{room_name}' Odasına Cihaz Ekle / Ata")
        self.setMinimumWidth(320)
        self.setObjectName("popupDialog")  # Witcher temasında parşömen zemin (arayuz/tema.py)
        self.setStyleSheet("font-size: 13px;")

        layout = QVBoxLayout(self)
        lbl = QLabel(f"<b>{room_name}</b> odasına eklemek istediğiniz cihazı seçin:")
        layout.addWidget(lbl)

        self.device_combo = QComboBox()
        devices: Dict[str, Any] = self.engine.storage.get("smart_devices", {})
        self.unassigned_keys = []
        for k, dev in devices.items():
            curr_room = dev.get("room", "")
            if curr_room != room_name:
                room_info = f" (Şu an: {curr_room})" if curr_room else " (Atanmamış)"
                self.device_combo.addItem(f"{dev.get('name')} [{dev.get('device_type')}]{room_info}", k)
                self.unassigned_keys.append(k)

        if not self.unassigned_keys:
            self.device_combo.addItem("Eklenebilecek boşta cihaz bulunamadı", None)

        layout.addWidget(self.device_combo)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Bu Odaya Ata")
        ok_btn.clicked.connect(self._on_assign)
        cancel_btn = QPushButton("İptal")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_assign(self):
        dev_key = self.device_combo.currentData()
        if not dev_key:
            QMessageBox.information(self, "Bilgi", "Seçilecek atanabilir cihaz yok.")
            return
        self.engine.smart_home.assign_device_to_room(dev_key, self.room_name)
        self.accept()


CIHAZ_MIME = "application/x-yumi-cihaz"
ATANMAMIS = "Atanmamış Cihazlar"


class DeviceCard(QWidget):
    """19 Kas (kullanıcı): cihaz kartı — iki satır (ad / düğmeler), dar pencerede taşmaz; tutup başka odaya sürüklenir."""

    def __init__(self, dev: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.dev = dev
        self._basla = None
        self.setObjectName("card"); self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Başka bir odaya taşımak için tutup sürükle")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._basla = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._basla is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._basla).manhattanLength() < QApplication.startDragDistance():
            return
        veri = QMimeData()
        veri.setData(CIHAZ_MIME, json.dumps({"name": self.dev.get("name", ""), "kimlik": self.dev.get("_ev_kimlik", ""),
                                             "room": self.dev.get("room", "")}, ensure_ascii=False).encode("utf-8"))
        surukle = QDrag(self); surukle.setMimeData(veri); surukle.setPixmap(self.grab())
        surukle.setHotSpot(self._basla); self._basla = None
        surukle.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        self._basla = None
        super().mouseReleaseEvent(event)


def cihaz_odaya(engine, dev_name: str, ev_kimlik: str, oda: str) -> None:
    """Cihazı odaya taşır (oda="" → odadan çıkar). Ev kaydı + eski beceri kaydı birlikte güncellenir."""
    if ev_kimlik:
        try:
            y = engine.smart_home.ev_yonetici()
            c = y.kayit.al(ev_kimlik)
            if c is not None:
                y.kayit.ad_ver(c.kimlik, None, oda)
        except Exception:
            pass
    if dev_name:
        try:
            engine.smart_home.assign_device_to_room(dev_name, oda)  # eski kayıtta yoksa etkisiz
        except Exception:
            pass


def cihaz_kaldir(engine, dev_name: str, ev_kimlik: str) -> None:
    """Cihazı Yumi'den tamamen kaldırır (ev kaydı + eski beceri kaydı). Cihazın kendisine bir şey gönderilmez."""
    if ev_kimlik:
        try:
            engine.smart_home.ev_yonetici().kayit.sil(ev_kimlik)
        except Exception:
            pass
    if dev_name:
        try:
            ad = dev_name.strip().lower()
            cihazlar = engine.storage.get("smart_devices", {}) or {}
            kalan = {k: v for k, v in cihazlar.items() if str(v.get("name", "")).strip().lower() != ad}
            if len(kalan) != len(cihazlar):
                engine.storage.set("smart_devices", kalan)
        except Exception:
            pass


class RoomAccordionItem(QWidget):
    """
    Tıklanınca açılıp kapanan (akordeon) tek bir oda başlığı bileşeni.
    Oda adının yanında '+' butonu ile odaya cihaz atanır, odadaki cihazlar altında listelenir.
    """

    device_action_signal = Signal(str, str, bool)  # action_type, device_name, is_on
    refresh_signal = Signal()
    add_device_signal = Signal(str)  # 18 Kas: '+ Cihaz' → 'Tara ve ekle' sekmesi bu oda için taramayı başlatır

    def __init__(self, room_name: str, devices: List[Dict[str, Any]], engine: YumiSkillEngine, parent=None):
        super().__init__(parent)
        self.room_name = room_name
        self.devices = devices
        self.engine = engine
        self.is_expanded = True
        self.setAcceptDrops(True)
        self._setup_ui()

    # --- sürükle bırak: kart bu odaya bırakılınca taşınır ---
    def _oda_degeri(self) -> str:
        return "" if self.room_name == ATANMAMIS else self.room_name

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(CIHAZ_MIME):
            event.acceptProposedAction(); self._vurgula(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(CIHAZ_MIME):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._vurgula(False)

    def dropEvent(self, event):
        self._vurgula(False)
        try:
            d = json.loads(bytes(event.mimeData().data(CIHAZ_MIME)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            event.ignore(); return
        if (d.get("room") or "") == self._oda_degeri():
            event.ignore(); return
        event.acceptProposedAction()
        self.cihazi_buraya(d.get("name", ""), d.get("kimlik", ""))

    def cihazi_buraya(self, ad: str, kimlik: str) -> None:
        cihaz_odaya(self.engine, ad, kimlik, self._oda_degeri())
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh_signal.emit)  # sürükleme kapanınca listeyi yeniden kur

    def _vurgula(self, acik: bool):
        h = getattr(self, "header_widget", None)
        if h is not None:
            h.setStyleSheet("#card { border: 2px dashed palette(highlight); }" if acik else "")

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 4, 0, 4)
        self.layout.setSpacing(2)

        # Başlık Çubuğu
        header_widget = QWidget(); self.header_widget = header_widget
        header_widget.setObjectName("card")  # ARAYUZ: renkler temadan
        header_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h_layout = QHBoxLayout(header_widget)
        h_layout.setContentsMargins(8, 4, 8, 4)

        self.toggle_btn = QPushButton(f"▼  {self.room_name} · {len(self.devices)}")
        self.toggle_btn.setObjectName("roomToggle")
        self.toggle_btn.setStyleSheet("text-align: left; padding-left: 6px;")  # 19 Kas: kırpılırsa adın başı görünsün
        # ARAYUZ (13 Kasım): oda adı uzun/yazı iri olsa da satır taşmaz (yatay kaydırma çıkmaz); ad tam hali ipucunda
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); self.toggle_btn.setMinimumWidth(40)
        self.toggle_btn.setToolTip(f"{self.room_name} ({len(self.devices)} cihaz)")
        self.toggle_btn.clicked.connect(self.toggle_expand)
        h_layout.addWidget(self.toggle_btn, 1)

        # '+' Odaya Cihaz Ekle/Ata Butonu (Atanmamış bölümünde yok: oraya kart sürüklenir ya da '⋯ → Odaya taşı')
        if self.room_name != ATANMAMIS:
            add_btn = QPushButton("+")  # 19 Kas: dar pencerede oda adına yer kalsın
            add_btn.setObjectName("primaryButton"); add_btn.setFixedSize(34, 30)
            add_btn.setStyleSheet("padding: 0px; font-size: 18px; font-weight: 600;")
            add_btn.setToolTip(f"Ağı tarayıp bulunan cihazı '{self.room_name}' odasına ekle")
            add_btn.clicked.connect(self._on_add_device_click)
            h_layout.addWidget(add_btn)

        # Odayı Sil Butonu (Atanmamış hariç)
        if self.room_name != ATANMAMIS:
            del_room_btn = QPushButton("✕")
            del_room_btn.setObjectName("iconButton"); del_room_btn.setFixedSize(30, 30)
            del_room_btn.setToolTip("Oda başlığını sil")
            del_room_btn.clicked.connect(self._on_delete_room_click)
            h_layout.addWidget(del_room_btn)

        self.layout.addWidget(header_widget)

        # Cihazlar Listesi İçerik Alanı
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(12, 4, 4, 8)
        self.content_layout.setSpacing(4)

        self._populate_devices()
        self.layout.addWidget(self.content_widget)

    def toggle_expand(self):
        self.is_expanded = not self.is_expanded
        self.content_widget.setVisible(self.is_expanded)
        arrow = "▼" if self.is_expanded else "►"
        self.toggle_btn.setText(f"{arrow}  {self.room_name} · {len(self.devices)}")

    def _populate_devices(self):
        # Önceki elemanları temizle
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.devices:
            empty_lbl = QLabel("Bu odada henüz cihaz yok. '+' ile ekle ya da başka odadan bir cihazı buraya sürükle.")
            empty_lbl.setObjectName("caption"); empty_lbl.setWordWrap(True); empty_lbl.setContentsMargins(6, 6, 6, 6)
            self.content_layout.addWidget(empty_lbl)
            return

        for dev in self.devices:
            dev_card = DeviceCard(dev)
            dikey = QVBoxLayout(dev_card)
            dikey.setContentsMargins(8, 4, 8, 4); dikey.setSpacing(4)

            dev_info = QLabel(f"<b>{dev.get('name')}</b><br><span style='font-size:12px'>{dev.get('protocol')}</span>")
            dev_info.setWordWrap(True)
            dev_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # 19 Kas: dar pencerede taşmasın
            dikey.addWidget(dev_info)

            tur_ = "ev" if dev.get("_ev_kimlik") else "test"
            anahtar = dev.get("_ev_kimlik") or dev.get("name")
            satir = QHBoxLayout(); satir.setSpacing(4)
            on_btn = QPushButton("Aç"); on_btn.setObjectName("primaryButton")
            on_btn.clicked.connect(lambda _, a=anahtar, t=tur_: self.device_action_signal.emit(t, a, True))
            off_btn = QPushButton("Kapat")
            off_btn.clicked.connect(lambda _, a=anahtar, t=tur_: self.device_action_signal.emit(t, a, False))
            daha = QPushButton("⋯"); daha.setObjectName("iconButton"); daha.setFixedWidth(34)
            daha.setToolTip("Odaya taşı · odadan çıkar · cihazı kaldır")
            daha.clicked.connect(lambda _, d=dev, btn=daha: self._cihaz_menusu(d, btn))
            for btn in (on_btn, off_btn):
                btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); btn.setMinimumWidth(36)
                satir.addWidget(btn, 1)
            satir.addWidget(daha)
            dikey.addLayout(satir)
            self.content_layout.addWidget(dev_card)

    def _cihaz_menusu(self, dev: Dict[str, Any], btn: QPushButton):
        menu = QMenu(self)
        tasi = menu.addMenu("Odaya taşı")
        try:
            odalar = self.engine.smart_home.get_rooms()
        except Exception:
            odalar = []
        simdiki = dev.get("room", "") or ""
        for oda in odalar:
            eylem = tasi.addAction(oda); eylem.setEnabled(oda != simdiki)
            eylem.triggered.connect(lambda _=False, o=oda: self._tasi(dev, o))
        if not odalar:
            tasi.addAction("Önce bir oda ekle").setEnabled(False)
        if simdiki:
            menu.addAction("Odadan çıkar").triggered.connect(lambda: self._tasi(dev, ""))
        menu.addSeparator()
        menu.addAction("Cihazı kaldır…").triggered.connect(lambda: self._kaldir(dev))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _tasi(self, dev: Dict[str, Any], oda: str):
        cihaz_odaya(self.engine, dev.get("name", ""), dev.get("_ev_kimlik", ""), oda)
        self.refresh_signal.emit()

    def _kaldir(self, dev: Dict[str, Any]):
        ad = dev.get("name", "") or "Cihaz"
        cevap = QMessageBox.question(self, "Cihazı kaldır",
                                     f"'{ad}' Yumi'den kaldırılsın mı?\nCihazın kendisine bir şey yapılmaz; istersen 'Tara ve ekle' ile yeniden eklersin.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if cevap != QMessageBox.StandardButton.Yes:
            return
        cihaz_kaldir(self.engine, dev.get("name", ""), dev.get("_ev_kimlik", ""))
        self.refresh_signal.emit()

    def _on_add_device_click(self):
        # 18 Kas (kullanıcı): eski "boşta cihaz" penceresi yerine doğrudan tarama; bağlı değilse eski pencere
        if getattr(self, "tarama_ile_ekle", False):
            self.add_device_signal.emit(self.room_name)
            return
        dlg = AssignDeviceDialog(self.room_name, self.engine, self)
        if dlg.exec():
            self.refresh_signal.emit()

    def _on_eject_device(self, dev_name: str, ev_kimlik: str = ""):
        cihaz_odaya(self.engine, dev_name, ev_kimlik, ""); self.refresh_signal.emit(); return
        if ev_kimlik:  # (eski yol, kullanılmıyor)
            try:
                y = self.engine.smart_home.ev_yonetici()
                c = y.kayit.al(ev_kimlik)
                if c is not None:
                    y.kayit.ad_ver(c.kimlik, c.kullanici_adi, "")
            except Exception:
                pass
        try:
            self.engine.smart_home.assign_device_to_room(dev_name, "")  # eski kayıtta yoksa etkisiz
        except Exception:
            pass
        self.refresh_signal.emit()

    def _on_delete_room_click(self):
        reply = QMessageBox.question(
            self,
            "Odayı Sil",
            f"'{self.room_name}' odasını silmek istediğinize emin misiniz? (Cihazlar silinmez, 'Atanmamış' bölümüne geçer)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for dev in self.devices:  # 19 Kas: ev kaydındaki cihazlar da 'Atanmamış'a geçsin
                if dev.get("_ev_kimlik"):
                    cihaz_odaya(self.engine, "", dev["_ev_kimlik"], "")
            self.engine.smart_home.delete_room(self.room_name)
            self.refresh_signal.emit()


class SmartHomePanelWidget(QWidget):
    """
    Yumi'nin ana penceresine doğrudan gömülebilen
    Odalar (Açılır Başlıklar/Akordeon) ve Akıllı Ev Yönetim Paneli.
    """

    def __init__(self, engine: YumiSkillEngine | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.engine = engine or YumiSkillEngine()
        self._active_worker: _AsyncBridgeWorker | None = None
        self._setup_ui()
        self.refresh_all()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Yumi · Akıllı Ev & Odalar")
        self.setMinimumWidth(0)  # 19 Kas (kullanıcı): pencere daralınca düğmeler dışarı taşıyordu; içerik genişliğe uyar
        # ARAYUZ (12 Kasım): sabit renkler kaldırıldı; sekmeler ve kartlar ana pencerenin temasından gelir
        # 13 Kasım: sekme zemini ve kaydırma alanı saydam (koyu temalarda beyaz/gri blok kalmasın)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }"
                           " QTabWidget::pane { border: 0; background: transparent; }"
                           " QTabWidget > QStackedWidget > QWidget, #odaKapsayici { background: transparent; }")

        root_layout = QVBoxLayout(self)
        header_lbl = QLabel("Akıllı Ev Odaları & Cihaz Yönetimi")
        header_lbl.setObjectName("heading"); header_lbl.hide()  # başlık sayfanın üstünde ("Ev")
        sub_lbl = QLabel("Cihazları odalara ata, odayı açıp aç/kapat dene veya yeni cihaz ekle.")
        sub_lbl.setWordWrap(True)
        sub_lbl.setObjectName("brandDescription")
        root_layout.addWidget(header_lbl)
        root_layout.addWidget(sub_lbl)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_rooms_tab(), "Odalar")
        self.tabs.addTab(self._kaydirilir(self._build_bridges_tab()), "Marka bağlantıları")
        self.tabs.addTab(self._kaydirilir(self._build_scan_and_manual_tab()), "Tara ve ekle")
        root_layout.addWidget(self.tabs)
        # ARAYUZ (13 Kasım): dar panelde formlar ezilmesin — etiket alanın üstünde, alanlar tam genişlik,
        # açılır listeler içeriği kadar genişlemeye zorlamasın.
        for f in self.findChildren(QFormLayout):
            f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for c in self.findChildren(QComboBox):
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon); c.setMinimumContentsLength(8)

        self.status_lbl = QLabel("Hazır.")
        self.status_lbl.setObjectName("caption")
        root_layout.addWidget(self.status_lbl)

    @staticmethod
    def _kaydirilir(page: QWidget) -> QScrollArea:
        """Uzun sekme içeriği dikey kayar; yatay kaydırma yok (sayfa panel genişliğine uyar)."""
        alan = QScrollArea(); alan.setWidgetResizable(True); alan.setFrameShape(QScrollArea.Shape.NoFrame)
        alan.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); alan.viewport().setAutoFillBackground(False)
        page.setObjectName("odaKapsayici"); alan.setWidget(page); return alan

    def _build_rooms_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Yeni Oda Ekleme Üst Çubuğu
        top_bar = QHBoxLayout()
        self.new_room_input = QLineEdit()
        self.new_room_input.setPlaceholderText("Yeni oda adı (Salon, Balkon…)")
        add_room_btn = QPushButton("+ Oda ekle")
        add_room_btn.setObjectName("primaryButton")
        add_room_btn.clicked.connect(self._on_add_new_room)
        self.new_room_input.setMinimumWidth(60); self.new_room_input.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        top_bar.addWidget(self.new_room_input, 2)
        top_bar.addWidget(add_room_btn, 0)
        layout.addLayout(top_bar)

        # Kaydırılabilir Açılır Oda Başlıkları (Akordeon Alanı)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.viewport().setAutoFillBackground(False)
        self.rooms_container = QWidget(); self.rooms_container.setObjectName("odaKapsayici")
        self.rooms_layout = QVBoxLayout(self.rooms_container)
        self.rooms_layout.setContentsMargins(4, 4, 4, 4)
        self.rooms_layout.setSpacing(6)
        self.rooms_layout.addStretch()
        self.scroll_area.setWidget(self.rooms_container)
        layout.addWidget(self.scroll_area)

        return page

    def _build_bridges_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        bridge_group = QGroupBox("Cihaz kurulumu")
        form = QFormLayout(bridge_group)

        self.bridge_category_combo = QComboBox()
        for category in DEVICE_CATEGORIES:
            self.bridge_category_combo.addItem(f"{category['icon']}  {category['label']}", category["id"])
        self.bridge_category_combo.currentIndexChanged.connect(self._on_bridge_category_changed)

        self.bridge_type_combo = QComboBox()
        self.bridge_type_combo.currentIndexChanged.connect(self._on_bridge_type_changed)

        self.bridge_platform_combo = QComboBox()
        self.bridge_platform_combo.currentIndexChanged.connect(self._on_bridge_platform_changed)
        self.bridge_model_scope = QLabel()
        self.bridge_model_scope.setWordWrap(True)
        self.bridge_model_scope.setObjectName("caption")

        self.bridge_user_input = QLineEdit()
        self.bridge_pass_input = QLineEdit()
        self.bridge_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.bridge_region_input = QLineEdit("eu")

        self.lbl_user = QLabel("API Key / E-posta / Köprü IP:")
        self.lbl_pass = QLabel("API Secret / Şifre / Token:")
        self.help_bridge_lbl = QLabel()
        self.help_bridge_lbl.setWordWrap(True)
        self.help_bridge_lbl.setObjectName("caption")

        form.addRow("1. Cihaz kategorisi:", self.bridge_category_combo)
        form.addRow("2. Cihaz türü:", self.bridge_type_combo)
        form.addRow("3. Marka / bağlantı:", self.bridge_platform_combo)
        form.addRow("4. Uyumlu ürün ve model kapsamı:", self.bridge_model_scope)
        form.addRow("5. Kurulum yönergesi:", self.help_bridge_lbl)
        form.addRow(self.lbl_user, self.bridge_user_input)
        form.addRow(self.lbl_pass, self.bridge_pass_input)
        self.bridge_region_label=QLabel("Ülke / bölge:")
        form.addRow(self.bridge_region_label,self.bridge_region_input)

        sync_btn = QPushButton("Bağlan ve cihazları bul")
        sync_btn.clicked.connect(self._on_sync_bridge)
        form.addRow("", sync_btn)

        layout.addWidget(bridge_group)
        tv_group = QGroupBox('Android / Google TV eşleştir')
        tv_form = QFormLayout(tv_group)
        self.tv_host = QLineEdit()
        self.tv_host.setPlaceholderText('TV IP adresi')
        self.tv_name = QLineEdit('Salon TV')
        self.tv_code = QLineEdit()
        self.tv_code.setMaxLength(6)
        tv_form.addRow('IP adresi:', self.tv_host)
        tv_form.addRow('Cihaz adı:', self.tv_name)
        tv_form.addRow('TV ekranındaki kod:', self.tv_code)
        begin = QPushButton('TV’de kodu göster')
        finish = QPushButton('Kodu doğrula ve kaydet')
        begin.clicked.connect(lambda: self._pair_tv(False))
        finish.clicked.connect(lambda: self._pair_tv(True))
        tv_form.addRow(begin)
        tv_form.addRow(finish)
        layout.addWidget(tv_group)
        layout.addStretch()
        self._on_bridge_category_changed()
        return page

    def _build_scan_and_manual_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Wi-Fi Tarama (18 Kas: tek "Ağı tara" düğmesi EvCihazPaneli'nde; ilerleme + tüm bulunanlar orada)
        scan_group = QGroupBox("Ağı tara")
        s_layout = QVBoxLayout(scan_group)
        self.scan_results_combo = QComboBox()
        self.scan_results_combo.setPlaceholderText("Elle kaydetmek için taranan cihazı seç (isteğe bağlı)")
        # E06-3 (17 Kasım): bulunan cihazlar + erişim durumu + cihazdan sorgulanan yetenekler + eşleştir/ad-oda/kontroller
        self.ev_paneli = None
        try:
            from .ev.panel_ev import EvCihazPaneli
            self.ev_paneli = EvCihazPaneli(self.engine.smart_home.ev_yonetici, self.engine.smart_home.get_rooms,
                                           oda_ekle=self.engine.smart_home.add_room)
            self.ev_paneli.tara_dugmesi.setObjectName("primaryButton")
            self.ev_paneli.tarandi.connect(self._on_ev_tarandi)
            self.ev_paneli.degisti.connect(self.refresh_all)
            s_layout.addWidget(self.ev_paneli)
            self.ev_paneli.yenile()
        except Exception as hata:
            self.ev_paneli = None
            hata_lbl = QLabel(f"Ev cihazı listesi yüklenemedi: {hata}")
            hata_lbl.setObjectName("caption"); hata_lbl.setWordWrap(True)
            s_layout.addWidget(hata_lbl)
            scan_btn = QPushButton("Ağı tara (eski yol)")
            scan_btn.clicked.connect(self._on_scan_wifi)
            s_layout.addWidget(scan_btn)
        layout.addWidget(scan_group)

        # Manuel Cihaz Ekleme Formu
        man_group = QGroupBox("Cihazı adıyla kaydet")
        form = QFormLayout(man_group)
        form.addRow("Taranan cihaz:", self.scan_results_combo)

        self.man_name = QLineEdit()
        self.man_name.setPlaceholderText("Örn: Başucu Lambası, Salon TV, Robot Süpürge")

        self.man_type = QComboBox()
        self.man_type.addItem("Işık / Lamba (Prizdeki lambalar dahil)", "light")
        self.man_type.addItem("Akıllı Televizyon (TV)", "tv")
        self.man_type.addItem("Robot Süpürge", "vacuum")
        self.man_type.addItem("Akıllı Priz", "plug")

        self.man_proto = QComboBox()
        for label, code in [
            ("Tuya / Smart Life", "tuya"),
            ("Akıllı TV (LG / Samsung / Android TV DIAL)", "dlna_tv"),
            ("Xiaomi Yeelight", "yeelight"),
            ("Xiaomi Mi Home / Roborock", "xiaomi"),
            ("Philips Hue", "hue"),
            ("IKEA DIRIGERA", "ikea_dirigera"),
            ("TP-Link Tapo / Kasa", "tapo"),
            ("Shelly (yerel RPC, Gen2+ / Gen3)", "shelly"),
            ("Home Assistant", "home_assistant"),
        ]:
            self.man_proto.addItem(label, code)

        self.man_ip = QLineEdit()
        self.man_ip.setPlaceholderText("Örn: 192.168.1.45")

        self.man_room_combo = QComboBox()
        self.man_token = QLineEdit()
        self.man_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.man_token.setPlaceholderText("Shelly RPC parolası / Local Key / Token / TV MAC (varsa)")
        self.man_id = QLineEdit()
        self.man_id.setPlaceholderText("Shelly çıkış no (varsayılan 0) / Tuya ID / HA entity_id")

        self.scan_results_combo.currentIndexChanged.connect(self._on_scan_item_picked)

        save_man_btn = QPushButton("Cihazı kaydet")
        save_man_btn.clicked.connect(self._on_save_manual)

        form.addRow("Yumi'deki Sesli Komut Adı:", self.man_name)
        form.addRow("Cihaz Türü:", self.man_type)
        form.addRow("Marka / Protokol:", self.man_proto)
        form.addRow("Atanacak Oda:", self.man_room_combo)
        form.addRow("Yerel Wi-Fi IP Adresi:", self.man_ip)
        form.addRow("Token / Local Key / TV MAC:", self.man_token)
        form.addRow("Cihaz / çıkış ID:", self.man_id)
        form.addRow("", save_man_btn)

        layout.addWidget(man_group)
        return page

    # --- YÖNETİM & GÜNCELLEME METOTLARI ---

    def refresh_all(self) -> None:
        """Odalar akordeonunu ve oda seçim listelerini günceller."""
        rooms: List[str] = self.engine.smart_home.get_rooms()
        devices: Dict[str, Any] = self.engine.storage.get("smart_devices", {})

        # Manuel ekleme sekmesindeki oda combo'sunu doldur
        self.man_room_combo.clear()
        self.man_room_combo.addItem("(Oda Atanmasın)", "")
        for r in rooms:
            self.man_room_combo.addItem(r, r)

        # Odalar Akordeonunu Yeniden İnşa Et
        while self.rooms_layout.count() > 1:
            item = self.rooms_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Cihazları odalarına göre grupla
        devices_by_room: Dict[str, List[Dict[str, Any]]] = {r: [] for r in rooms}
        unassigned_devices: List[Dict[str, Any]] = []

        devices = {k: dict(v) for k, v in devices.items()}
        self._eski_ev_esle(devices)
        for ev in self._ev_odali_cihazlar(devices):
            devices[ev["_ev_kimlik"]] = ev
        for dev in devices.values():
            room = dev.get("room", "").strip()
            if room and room in devices_by_room:
                devices_by_room[room].append(dev)
            else:
                unassigned_devices.append(dev)

        # 1. Tanımlı Odalar
        for room_name in rooms:
            room_devs = devices_by_room[room_name]
            acc_item = RoomAccordionItem(room_name, room_devs, self.engine, self)
            acc_item.device_action_signal.connect(self._on_device_action)
            acc_item.refresh_signal.connect(self.refresh_all)
            acc_item.add_device_signal.connect(self._on_room_add_device)
            acc_item.tarama_ile_ekle = True
            self.rooms_layout.insertWidget(self.rooms_layout.count() - 1, acc_item)

        # 2. Atanmamış Cihazlar Bölümü (Varsa en altta göster)
        if unassigned_devices:
            acc_unassigned = RoomAccordionItem(ATANMAMIS, unassigned_devices, self.engine, self)
            acc_unassigned.device_action_signal.connect(self._on_device_action)
            acc_unassigned.refresh_signal.connect(self.refresh_all)
            self.rooms_layout.insertWidget(self.rooms_layout.count() - 1, acc_unassigned)

    def _eski_ev_esle(self, eski: Dict[str, Any]) -> None:
        """18 Kas: elle kaydedilmiş eski cihaz (ör. 'Televizyon / dlna_tv') ev kaydındaki aynı cihazla (ad/IP)
        eşleşirse oda kartında gerçek platform gösterilir ve Aç/Kapat ortak yöneticiden (doğrulamalı) gider."""
        try:
            kayitli = self.engine.smart_home.ev_yonetici().kayit.tumu()
        except Exception:
            return
        from .ev.tv_yardim import PLATFORM_ADI
        for d in eski.values():
            ad, ip = str(d.get("name", "")).lower(), d.get("ip_address") or d.get("ip") or ""
            c = next((c for c in kayitli if c.gorunen_ad.lower() == ad or (c.kullanici_adi or "").lower() == ad
                      or (ip and c.adres == ip)), None)
            if c is None:
                continue
            aileler = [c.aile, *c.ek_aileler]
            d["_ev_kimlik"] = c.kimlik
            d["protocol"] = " + ".join(PLATFORM_ADI.get(a, a) for a in aileler) + (f" · {c.model}" if c.model else "")

    def _ev_odali_cihazlar(self, eski: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ev kaydındaki (data/ev_cihazlari.json) odası verilmiş cihazlar, Odalar sekmesinde gösterilmek üzere."""
        try:
            y = self.engine.smart_home.ev_yonetici()
            kayitli = y.kayit.tumu()
        except Exception:
            return []
        eslenen = {d.get("_ev_kimlik") for d in eski.values() if d.get("_ev_kimlik")}
        eski_adlar = {str(d.get("name", "")).lower() for d in eski.values()}
        eski_ipler = {d.get("ip_address") or d.get("ip") for d in eski.values()} - {None, ""}
        sonuc = []
        for c in kayitli:
            # 19 Kas: odası olmayan kayıtlı cihazlar da gösterilir ('Atanmamış Cihazlar'); önceden hiçbir yerde görünmüyordu
            if c.kimlik in eslenen or c.gorunen_ad.lower() in eski_adlar or (c.adres and c.adres in eski_ipler):
                continue
            sonuc.append({"name": c.gorunen_ad, "protocol": c.aile, "device_type": c.tur, "room": c.oda,
                          "_ev_kimlik": c.kimlik})
        return sonuc

    def _on_room_add_device(self, room: str) -> None:
        """'+ Cihaz': Tara ve ekle sekmesine geç, hedef odayı ayarla, taramayı başlat."""
        self.tabs.setCurrentIndex(2)
        if self.ev_paneli is not None:
            self.ev_paneli.hedef_oda_ayarla(room)
            if self.ev_paneli.tara_dugmesi.isEnabled():
                self.ev_paneli.tara()
        else:
            self._on_scan_wifi()
        self.status_lbl.setText(f"'{room}' için ağ taranıyor; bulunan cihazı kartındaki 'Bu odaya ekle' ile ekle.")

    def _on_ev_tarandi(self, cihazlar) -> None:
        from .ev.yonetici import eski_bicim
        self.scan_results_combo.clear()
        if not cihazlar:
            self.scan_results_combo.addItem("Kontrol edilebilir cihaz bulunamadı", None)
        else:
            self.scan_results_combo.addItem("-- Bulunan Cihazlardan Seçin --", None)
            for c in cihazlar:
                d = eski_bicim(c)
                self.scan_results_combo.addItem(f"{d['info']} - IP: {d['ip']}" if d.get('ip') else d['info'], d)
        self.refresh_all()

    def _on_add_new_room(self) -> None:
        name = self.new_room_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Uyarı", "Lütfen oluşturmak istediğiniz oda adını yazın.")
            return
        res = self.engine.smart_home.add_room(name)
        self.status_lbl.setText(res.get("speech", ""))
        self.new_room_input.clear()
        self.refresh_all()

    def _on_device_action(self, action_type: str, dev_name: str, turn_on: bool) -> None:
        if action_type == "ev":  # ev kaydı cihazı (kimlik): ortak yöneticiyle, sonuç doğrulanarak
            try:
                y = self.engine.smart_home.ev_yonetici()
                c = y.kayit.al(dev_name)
            except Exception:
                c = None
            if c is None:
                self.status_lbl.setText("Cihaz kaydı bulunamadı; yeniden tara.")
                return
            self.status_lbl.setText(f"'{c.gorunen_ad}' {'açılıyor' if turn_on else 'kapatılıyor'}…")
            self._start_worker(lambda: (lambda s: {"ok": s.ok, "speech": ("Tamam: " if s.ok else "Olmadı: ") + (s.mesaj or "")})(
                y.uygula(c, "guc", bool(turn_on))), self._on_worker_done)
            return
        self.status_lbl.setText(f"'{dev_name}' komutu gönderiliyor...")
        devices = self.engine.storage.get("smart_devices", {})
        dtype = "light"
        for d in devices.values():
            if d.get("name") == dev_name:
                dtype = d.get("device_type", "light")
                break

        if dtype == "vacuum":
            name,args='control_vacuum',{'action':'start' if turn_on else 'pause','device_name':dev_name}
        elif dtype == "tv":
            name,args='control_smart_tv',{'action':'power_on' if turn_on else 'power_off','device_name':dev_name}
        else:
            name,args='control_light_or_plug',{'device_name':dev_name,'state':'on' if turn_on else 'off'}
        self._start_worker(self.engine.execute_skill,self._on_worker_done,name,args)

    def _start_worker(self,fn,callback,*args):
        from PySide6.QtWidgets import QApplication
        if self._active_worker and self._active_worker.isRunning():
            self.status_lbl.setText('Önce devam eden cihaz işleminin bitmesini bekle.');return
        worker=_AsyncBridgeWorker(fn,*args);self._active_worker=worker
        app=QApplication.instance()
        if not hasattr(app,'_yumi_skill_workers'):app._yumi_skill_workers=[]
        app._yumi_skill_workers.append(worker)
        worker.finished_signal.connect(callback)
        def release():
            if self._active_worker is worker:self._active_worker=None
            if worker in app._yumi_skill_workers:app._yumi_skill_workers.remove(worker)
            worker.deleteLater()
        worker.finished.connect(release);worker.start()

    def _on_bridge_category_changed(self) -> None:
        category_id = self.bridge_category_combo.currentData()
        previous = self.bridge_type_combo.currentData()
        self.bridge_type_combo.blockSignals(True)
        self.bridge_type_combo.clear()
        options = device_types_for_category(category_id)
        for type_id, label in options:
            self.bridge_type_combo.addItem(label, type_id)
        selected = next((i for i, (type_id, _) in enumerate(options) if type_id == previous), 0)
        if options:
            self.bridge_type_combo.setCurrentIndex(selected)
        self.bridge_type_combo.blockSignals(False)
        self._on_bridge_type_changed()

    def _on_bridge_type_changed(self) -> None:
        device_type = self.bridge_type_combo.currentData()
        previous = self.bridge_platform_combo.currentData()
        self.bridge_platform_combo.blockSignals(True)
        self.bridge_platform_combo.clear()
        options = list(integrations_for_device_type(device_type))
        registered = self.engine.smart_home.list_oem_connectors().get("connectors", [])
        for spec in registered:
            if device_type == "all" or device_type in spec.get("device_types", []):
                options.append({"id": spec["id"], "label": spec["name"],
                                "model_scope": spec.get("supported_models", "Üretici destek listesine göre"),
                                "account_linking": spec.get("account_linking", "")})
        for entry in options:
            self.bridge_platform_combo.addItem(entry["label"], entry["id"])
        selected = next((i for i, entry in enumerate(options) if entry["id"] == previous), 0)
        if options:
            self.bridge_platform_combo.setCurrentIndex(selected)
        self.bridge_platform_combo.blockSignals(False)
        self._on_bridge_platform_changed()

    def _on_bridge_platform_changed(self) -> None:
        plat = self.bridge_platform_combo.currentData()
        entry = integration_by_id(plat)
        self.bridge_model_scope.setText(entry["model_scope"] if entry else "Bağlantı yöntemi seç.")
        hints = {
            "tuya_via_ha": (
                "Home Assistant adresi:",
                "Home Assistant erişim belirteci:",
                "Önce Home Assistant > Ayarlar > Cihazlar ve hizmetler > Entegrasyon ekle > Tuya adımlarında Smart Life uygulamasındaki User Code ve QR ile hesabını bağla. Sonra Yumi’ye kendi Home Assistant adresini ve profilinden ürettiğin erişim belirtecini ver. Bu, Tuya geliştirici API anahtarı değildir. Home Assistant kurulumu gerekir.",
            ),
            "xiaomi_via_ha": (
                "Home Assistant adresi:",
                "Home Assistant erişim belirteci:",
                "Önce Home Assistant’ta resmî Xiaomi Home entegrasyonunu hesap/OAuth akışıyla kur ve bölge/model desteğini doğrula. Sonra Yumi’ye Home Assistant adresini ve profilinden ürettiğin erişim belirtecini ver. Xiaomi cihazları her bölgede yerel çalışmaz.",
            ),
            "hue": (
                "Philips Hue Bridge IP Adresi:",
                "Hue Username (Boş bırakılabilir):",
                "Hue kutusunun üzerindeki fiziksel tuşa basıp aşağıdaki 'Köprüye Bağlan' butonuna tıklayın.",
            ),
            "ikea": (
                "IKEA DIRIGERA Hub IP Adresi:",
                "IKEA Hub Token:",
                "IKEA Home Smart (DIRIGERA) hub üzerindeki tüm akıllı ampul ve prizleri oda isimleriyle çeker.",
            ),
            "tapo": (
                "TP-Link (Tapo/Kasa) E-posta:",
                "TP-Link Şifresi:",
                "Evdeki Wi-Fi ağını tarayıp tüm TP-Link Tapo ve Kasa ampul/prizlerini Tapo isimleriyle ekler.",
            ),
            "home_assistant": (
                "Home Assistant URL (192.168.1.x:8123):",
                "Uzun Ömürlü Erişim Token'ı:",
                "Google Assistant/Alexa hesabındaki cihazlar Yumi’ye otomatik açılmaz. Önce cihazları Home Assistant’ta entegrasyon veya Matter controller ile bağla; sonra Home Assistant adresini ve uzun ömürlü tokenı gir. Yumi yalnız HA’nın sunduğu uyumlu entity ve komutları alır. Marka/model özellikleri entegrasyona göre değişir.",
            ),
        }
        u_lbl, p_lbl, desc = hints.get(plat, ("Kullanıcı / IP:", "Şifre / Token:", ""))
        self.lbl_user.setText(u_lbl)
        self.lbl_pass.setText(p_lbl)
        self.help_bridge_lbl.setText(desc)
        ha_route=plat in ("tuya_via_ha","xiaomi_via_ha","home_assistant")
        self.bridge_region_label.setVisible(not ha_route)
        self.bridge_region_input.setVisible(not ha_route)
        registered = next((item for item in self.engine.smart_home.list_oem_connectors().get("connectors", [])
                           if item.get("id") == plat), None)
        if registered:
            self.lbl_user.setText("OEM hesabı:")
            self.lbl_pass.setText("Giriş bilgisi:")
            self.bridge_user_input.clear();self.bridge_pass_input.clear()
            self.bridge_user_input.setVisible(False);self.bridge_pass_input.setVisible(False)
            self.lbl_user.setVisible(False);self.lbl_pass.setVisible(False)
            self.bridge_region_label.setVisible(False);self.bridge_region_input.setVisible(False)
            self.help_bridge_lbl.setText(
                f"{registered['name']} hesabı resmi yetkilendirme penceresinde bağlanır. "
                "Yumi kullanıcıdan üretici geliştirici anahtarı veya hesap parolası istemez. "
                + registered.get("supported_models", "Destek ve özellikler keşif yanıtına göre listelenir.")
            )
        else:
            self.bridge_user_input.setVisible(True);self.bridge_pass_input.setVisible(True)
            self.lbl_user.setVisible(True);self.lbl_pass.setVisible(True)

    def _on_sync_bridge(self) -> None:
        plat = self.bridge_platform_combo.currentData()
        registered = {item.get("id") for item in self.engine.smart_home.list_oem_connectors().get("connectors", [])}
        if plat in registered:
            self.status_lbl.setText("Resmi OEM hesabı bağlama penceresi açılıyor…")
            self._start_worker(self.engine.smart_home.link_oem_account_and_discover,
                               self._on_worker_done, plat)
            return
        if plat in ("tuya_via_ha","xiaomi_via_ha"):plat="home_assistant"
        user_val = self.bridge_user_input.text().strip()
        pass_val = self.bridge_pass_input.text().strip()
        region_val = self.bridge_region_input.text().strip() or "eu"
        if plat=="home_assistant" and (not user_val or not pass_val):
            self.status_lbl.setText("Home Assistant adresi ve erişim belirteci gerekli.");return

        self.status_lbl.setText(f"{plat.upper()} köprüsüne bağlanılıyor...")
        self._start_worker(self.engine.smart_home.sync_cloud_bridge_devices,self._on_worker_done,plat,user_val,pass_val,region_val)

    def _pair_tv(self, finish):
        host = self.tv_host.text().strip()
        code = self.tv_code.text().strip() if finish else ''
        if not host or (finish and len(code) != 6):
            self.status_lbl.setText('TV IP adresini ve TV’de görünen altı haneli kodu gir.');return
        self.status_lbl.setText('TV ile eşleştiriliyor…')
        self._start_worker(self.engine.smart_home.pair_android_tv, self._on_worker_done, host, code, self.tv_name.text().strip() or 'Salon TV')

    def _on_scan_wifi(self) -> None:
        # E06-3: discover_wifi_devices artık yeni bulucuyu (yumi_skills/ev) kullanır; yetenekler cihazdan sorgulanır
        if getattr(self, "ev_paneli", None) is not None:  # 18 Kas: ilerleme + tüm bulunanlar EvCihazPaneli'nde
            self.ev_paneli.tara()
            return
        self.status_lbl.setText("Ev ağı ve Bluetooth taranıyor; bulunan cihazların yetenekleri sorgulanıyor…")
        self._start_worker(self.engine.smart_home.discover_wifi_devices,self._on_scan_done)

    def _on_scan_done(self, res: Dict[str, Any]) -> None:
        self.status_lbl.setText(res.get("speech", ""))
        self.scan_results_combo.clear()
        discovered = res.get("discovered", [])
        if not discovered:
            self.scan_results_combo.addItem("Açık yayın yapan cihaz bulunamadı", None)
            return
        self.scan_results_combo.addItem("-- Bulunan Cihazlardan Seçin --", None)
        for d in discovered:
            self.scan_results_combo.addItem(f"{d['info']} - IP: {d['ip']}" if d.get('ip') else d['info'], d)
        if getattr(self, "ev_paneli", None) is not None:
            self.ev_paneli.yenile()

    def _on_scan_item_picked(self) -> None:
        data = self.scan_results_combo.currentData()
        if not data:
            return
        self.man_ip.setText(data.get("ip", ""))
        # E06-3: yeni bulucu tür/protokolü veriyle bildirir; metin tahmini yalnız eski sonuç biçimi için
        tur, proto = data.get("device_type", ""), data.get("protocol", "")
        i_tur, i_proto = self.man_type.findData(tur), self.man_proto.findData(proto)
        if i_tur >= 0 or i_proto >= 0:
            if i_tur >= 0: self.man_type.setCurrentIndex(i_tur)
            if i_proto >= 0: self.man_proto.setCurrentIndex(i_proto)
            if data.get("mac") and not self.man_token.text(): self.man_token.setText(data["mac"])
            if data.get("erisim") and data.get("erisim") != "hazir":
                self.status_lbl.setText(f"{data.get('info','')}: {data.get('erisim_notu') or data.get('erisim')}")
            return
        info_low = data.get("info", "").lower()
        if "tv" in info_low or "webos" in info_low or "samsung" in info_low or "dlna" in info_low:
            self.man_type.setCurrentIndex(1)
            self.man_proto.setCurrentIndex(1)
        elif "yeelight" in info_low:
            self.man_type.setCurrentIndex(0)
            self.man_proto.setCurrentIndex(2)
        elif "hue" in info_low:
            self.man_type.setCurrentIndex(0)
            self.man_proto.setCurrentIndex(4)

    def _on_save_manual(self) -> None:
        name = self.man_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Eksik Bilgi", "Lütfen cihaza bir ad verin (Örn: Başucu Lambası, Salon TV).")
            return
        res = self.engine.smart_home.register_smart_device(
            name=name,
            device_type=self.man_type.currentData(),
            brand_or_protocol=self.man_proto.currentData(),
            ip_address=self.man_ip.text().strip(),
            token_or_key=self.man_token.text().strip(),
            entity_id=self.man_id.text().strip(),
            room=self.man_room_combo.currentData() or "",
        )
        self.status_lbl.setText(res.get("speech", ""))
        self.man_name.clear()
        self.refresh_all()
        self.tabs.setCurrentIndex(0)

    def _on_worker_done(self, res: Dict[str, Any]) -> None:
        self.status_lbl.setText(res.get("speech", ""))
        self.bridge_user_input.clear();self.bridge_pass_input.clear()
        self.refresh_all()
        if res.get("ok"):
            self.tabs.setCurrentIndex(0)


class SmartHomeDialog(QDialog):
    """
    Yumi PageStack ile tam uyumlu, akordeon odalar ve akıllı cihaz yönetim sayfası.
    """

    def __init__(self, parent, engine: YumiSkillEngine | None = None):
        super().__init__(parent)
        self.owner = parent
        self.engine = engine or getattr(parent, "skill_engine", None) or YumiSkillEngine()
        self.setWindowTitle("Yumi · Akıllı Ev & Odalar")
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        # Üst Başlık ve Geri Dön Butonu
        title_bar = QHBoxLayout()
        header_title = QLabel("Ev")
        header_title.setObjectName("heading")
        title_bar.addWidget(header_title)
        title_bar.addStretch()

        back = QPushButton("Sohbete dön")
        back.setObjectName("secondaryButton")
        back.clicked.connect(self.reject)
        title_bar.addWidget(back)
        outer.addLayout(title_bar)

        # Panel
        self.panel = SmartHomePanelWidget(engine=self.engine, parent=self)
        outer.addWidget(self.panel, 1)
