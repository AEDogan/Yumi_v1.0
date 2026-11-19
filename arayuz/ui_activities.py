"""Hareket sayfası: günlük senaryolar, müzik ve dans — kart görünümü (ARAYUZ, 13 Kasım).
Komutlar değişmedi (voice_actions.execute); yalnız yerleşim kartlara ve simgeli döşemelere geçti."""
from PySide6.QtCore import Qt,QSize,QByteArray,QRectF,QTimer
from PySide6.QtGui import QIcon,QPixmap,QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QComboBox,QCheckBox,
    QFrame,QScrollArea,QWidget,QSizePolicy)

SIMGE={
 'kitap':'<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2Z"/><path d="M4 19V5M8 7h7"/>',
 'bilgisayar':'<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
 'film':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>',
 'kahve':'<path d="M5 9h11v6a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5Z"/><path d="M16 11h2a2 2 0 0 1 0 4h-2M9 3v3M12 3v3"/>',
 'pencere':'<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M12 3v18M5 12h14"/>',
 'dinlen':'<path d="M20 15a8 8 0 1 1-9-11 6.5 6.5 0 0 0 9 11Z"/>',
 'toplanti':'<circle cx="8" cy="9" r="3"/><circle cx="17" cy="10" r="2.5"/><path d="M2 20a6 6 0 0 1 12 0M14 20a4.5 4.5 0 0 1 8 0"/>',
 'kalk':'<circle cx="12" cy="4" r="2"/><path d="M12 7v7M8 10l4-2 4 2M9 21l3-7 3 7"/>',
 'dans':'<circle cx="13" cy="4" r="2"/><path d="m6 11 4-3 4 1 4-3M10 8l1 6-4 7M11 14l5 2 1 5"/>',
 'direk':'<path d="M12 2v20"/><circle cx="16" cy="6" r="2"/><path d="m12 10 4-2 2 4M12 14l4 2-1 5"/>',
 'dur':'<rect x="6" y="6" width="12" height="12" rx="2"/>',
}

def _simge(ad,renk,boy=22):
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{renk}" '
         f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{SIMGE[ad]}</svg>')
    p=QPixmap(boy*2,boy*2);p.fill(Qt.GlobalColor.transparent);p.setDevicePixelRatio(2.)
    r=QPainter(p);QSvgRenderer(QByteArray(svg.encode())).render(r,QRectF(0,0,boy,boy));r.end();return QIcon(p)

def _tema_renk(owner):
    try:
        import tema
        t=tema.TEMALAR[tema.anahtar(owner.settings.get('theme','inci'))]
        return t['text'],t['accent']
    except Exception:return '#2B3440','#4F7CFF'

SENARYOLAR=[('Kitap oku','kitap oku','kitap'),('Bilgisayar','bilgisayara otur','bilgisayar'),('Film izle','film izle','film'),
            ('Kahve yap','kahve yap','kahve'),('Pencereden bak','pencereden bak','pencere'),('Dinlen','dinlen','dinlen'),
            ('Toplantı','toplantıya katıl','toplanti'),('Ayağa kalk','ayağa kalk','kalk')]
DANS=[('Dans et','dans et','dans'),('Direk dansı','direk dansı yap','direk'),('Durdur','dansı durdur','dur')]

class ActivitiesDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.setWindowFlags(Qt.WindowType.Widget);self.setModal(False)
        self.setObjectName('activityPage')
        renk,vurgu=_tema_renk(owner)
        outer=QVBoxLayout(self);outer.setContentsMargins(14,14,14,14);outer.setSpacing(12)
        header=QHBoxLayout();title=QLabel('Hareket');title.setObjectName('heading');header.addWidget(title,1)
        back=QPushButton('Sohbete dön');back.clicked.connect(self.reject);header.addWidget(back);outer.addLayout(header)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);scroll.viewport().setAutoFillBackground(False)
        icerik=QWidget();icerik.setObjectName('settingsContent');scroll.setWidget(icerik)
        layout=QVBoxLayout(icerik);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12);layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addWidget(scroll,1);self.scroll=scroll
        def kart(baslik,aciklama=None):
            f=QFrame();f.setObjectName('card');f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
            l=QVBoxLayout(f);l.setContentsMargins(10,10,10,10);l.setSpacing(8)
            b=QLabel(baslik);b.setObjectName('cardTitle');l.addWidget(b)
            if aciklama:a=QLabel(aciklama);a.setObjectName('caption');a.setWordWrap(True);l.addWidget(a)
            layout.addWidget(f);return l
        self.action_buttons={}
        def doseme(metin,komut,simge):
            b=QPushButton(metin);b.setObjectName('actionTile');b.setIcon(_simge(simge,renk,20));b.setIconSize(QSize(20,20))
            b.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed);b.setMinimumHeight(48)
            b.clicked.connect(lambda checked=False,komut=komut:self.run(komut));self.action_buttons[komut]=b;return b
        gunluk=kart('Günlük senaryolar','Yumi masaüstündeki eşyalarla bu işi yapar; yenisini seçince önce ayağa kalkar.')
        self.gunluk_grid=QGridLayout();self.gunluk_grid.setHorizontalSpacing(6);self.gunluk_grid.setVerticalSpacing(8)
        self.gunluk_doseme=[doseme(metin,komut,simge) for metin,komut,simge in SENARYOLAR]
        gunluk.addLayout(self.gunluk_grid)
        muzik=kart('Müzik ve dans')
        self.automatic=QCheckBox('Müziği otomatik algıla');self.automatic.setChecked(owner.settings.get('music_auto',True))
        self.automatic.toggled.connect(lambda value:self.run('otomatik müzik tepkisini '+('aç' if value else 'kapat')));muzik.addWidget(self.automatic)
        tur=QLabel('Müzik türü');tur.setObjectName('caption');muzik.addWidget(tur)
        self.genres=QComboBox();self.genres.addItem('Türü otomatik belirle','otomatik')
        from music_analysis import GENRES
        for key in GENRES:self.genres.addItem(key.title(),key)
        current=self.genres.findData(owner.settings.get('music_family','unknown'));self.genres.setCurrentIndex(max(0,current))
        self.genres.currentIndexChanged.connect(lambda _:self.run('müzik türü '+str(self.genres.currentData())));muzik.addWidget(self.genres)
        self.dans_grid=QGridLayout();self.dans_grid.setHorizontalSpacing(6);self.dans_grid.setVerticalSpacing(8)
        self.dans_doseme=[doseme(metin,komut,simge) for metin,komut,simge in DANS]
        muzik.addLayout(self.dans_grid);self._sutun=None;self._yerlestir()
        self.status=QLabel('');self.status.setObjectName('caption');self.status.setWordWrap(True);self.status.hide();layout.addWidget(self.status)
    def _yerlestir(self):
        """Döşemeler sığdığı kadar sütuna dizilir (iri yazılı temalarda — Terminal — tek sütun; taşma yok)."""
        vp=self.scroll.viewport().width() if hasattr(self,'scroll') else 0
        alan=(vp if vp>50 else self.width()-28)-20-2  # kart iç boşlukları + çerçeve
        def sutun(dosemeler,en_cok):
            gen=max(d.sizeHint().width() for d in dosemeler)
            for n in range(en_cok,1,-1):
                if n*gen+(n-1)*6<=alan:return n
            return 1
        yeni=(sutun(self.gunluk_doseme,2),sutun(self.dans_doseme,3))
        if yeni==self._sutun:return
        self._sutun=yeni
        for grid,dosemeler,n in ((self.gunluk_grid,self.gunluk_doseme,yeni[0]),(self.dans_grid,self.dans_doseme,yeni[1])):
            for d in dosemeler:grid.removeWidget(d)
            for i,d in enumerate(dosemeler):grid.addWidget(d,i//n,i%n)
    def resizeEvent(self,event):
        super().resizeEvent(event);self._yerlestir()
    def showEvent(self,event):
        super().showEvent(event);QTimer.singleShot(0,self._yerlestir)
    def run(self,command):
        from voice_actions import execute
        try:result=execute(self.owner,command)
        except Exception as error:result='Hareket başlatılamadı: '+str(error)
        if result:self.status.setText(result);self.status.show();self.owner.show_bubble(result)
