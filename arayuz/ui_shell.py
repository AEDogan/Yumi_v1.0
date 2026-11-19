"""Native presentation components. No transport, model or device ownership.
12 Kasım ARAYUZ: başlıkta Yumi logosu, kayıtta sese tepki veren kayan ses çubukları, ayrı Geçmiş sayfası,
üstte sekmeli Ayarlar bölümleri, tema süsleri (arayuz/tema.py)."""
import time
from collections import deque
from PySide6.QtCore import Qt,QSize,QByteArray,QRectF,QTimer
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor,QLinearGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QWidget,QHBoxLayout,QVBoxLayout,QGridLayout,QStackedWidget,
    QListWidget,QListWidgetItem,QPushButton,QToolButton,QButtonGroup,QSizePolicy,
    QFrame,QLabel,QScrollArea,QLayout,QLineEdit,QSizeGrip,QMenu)

PATHS={
 'chat':'<path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6 3V6a2 2 0 0 1 2-2Z"/>',
 'model':'<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a8 8 0 0 1 16 0v1"/>',
 'motion':'<circle cx="14" cy="4" r="2"/><path d="m8 9 5-2 3 5 5 1M13 7l-2 7-6 7m6-7 5 3 1 4M8 9l-4 5"/>',
 'home':'<path d="m3 11 9-8 9 8M5 10v11h14V10M10 21v-7h4v7"/>',
 'theme':'<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 5a7 7 0 0 1 0 14Z" fill="currentColor"/>',
 'settings':'<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
 'history':'<path d="M4 7v5h5M4 12a8 8 0 1 0 2-6M12 7v5l3 2"/>',
 'mic':'<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/>',
 'send':'<path d="m3 3 19 9-19 9 4-9-4-9ZM7 12h15"/>',
 'stop':'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
 'close':'<path d="m6 6 12 12M18 6 6 18"/>',
 'minimize':'<path d="M5 12h14"/>',
 'plus':'<path d="M12 5v14M5 12h14"/>',
 'back':'<path d="m15 5-7 7 7 7"/>',
 'search':'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
 'eye':'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
 'eyeoff':'<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
 'wave':'<path d="M7 12V7a1.5 1.5 0 0 1 3 0v4-7a1.5 1.5 0 0 1 3 0v7-6a1.5 1.5 0 0 1 3 0v7-3a1.5 1.5 0 0 1 3 0v6a7 7 0 0 1-13 3L3 13a1.5 1.5 0 0 1 2-2l2 1Z"/>',
 'info':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}

def icon(name,color='#596a80',size=22):
    path=PATHS.get(name,PATHS['chat']).replace('currentColor',color)
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    pixmap=QPixmap(size*2,size*2);pixmap.fill(Qt.GlobalColor.transparent);pixmap.setDevicePixelRatio(2.)
    painter=QPainter(pixmap);QSvgRenderer(QByteArray(svg.encode())).render(painter,QRectF(0,0,size,size));painter.end()
    return QIcon(pixmap)

class NavigationRail(QWidget):
    def __init__(self,actions,parent=None):
        super().__init__(parent);self.setObjectName('navigationRail');self.setFixedWidth(74)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        layout=QVBoxLayout(self);layout.setContentsMargins(8,8,8,12);layout.setSpacing(6)
        self.buttons={};self.group=QButtonGroup(self);self.group.setExclusive(True)
        for key,title,callback in actions:
            if key=='settings':layout.addStretch()  # Ayarlar sol altta (kullanıcı, 20:10)
            button=QToolButton();button.setObjectName('navButton');button.setText(title);button.setAccessibleName(title)
            button.setToolTip(title);button.setCheckable(True);button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(22,22));button.setFixedSize(58,58);button.clicked.connect(callback)
            self.group.addButton(button);layout.addWidget(button);self.buttons[key]=button
        self.buttons['chat'].setChecked(True)
    def recolor(self,color,active=None):
        for key,button in self.buttons.items():
            button.setIcon(icon(key,active if (active and button.isChecked()) else color))
    def select(self,key):
        if key in self.buttons:self.buttons[key].setChecked(True)
    def compact(self,height):
        small=height<400;tiny=height<290
        self.layout().setSpacing(2 if tiny else 4 if small else 6)
        for button in self.buttons.values():
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if tiny else Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setFixedSize(58,30 if tiny else 46 if small else 58)

class SectionTabs(QWidget):
    """QTabWidget uyumlu bölüm seçici: üstte sekmeli (segmented) düğmeler (12 Kasım ARAYUZ)."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('sectionTabs')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        self.bar=QFrame();self.bar.setObjectName('segmented');self.bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.bar_layout=QHBoxLayout(self.bar);self.bar_layout.setContentsMargins(3,3,3,3);self.bar_layout.setSpacing(2)
        self.group=QButtonGroup(self);self.group.setExclusive(True);self.group.idClicked.connect(self.setCurrentIndex)
        self.stack=QStackedWidget();layout.addWidget(self.bar);layout.addWidget(self.stack,1)
        self.list=self  # eski kod self.tabs.list.* kullanmasın diye
    def addTab(self,widget,title):
        index=self.stack.addWidget(widget)
        button=QPushButton(title);button.setObjectName('segButton');button.setCheckable(True);button.setAccessibleName(title+' bölümü')
        self.group.addButton(button,index);self.bar_layout.addWidget(button,1)
        if index==0:button.setChecked(True)
        return index
    def setCurrentIndex(self,index):
        if 0<=index<self.stack.count():
            self.stack.setCurrentIndex(index);self.group.button(index).setChecked(True)
    def currentIndex(self):return self.stack.currentIndex()
    def count(self):return self.stack.count()
    def widget(self,index):return self.stack.widget(index)

class ThemePicker(QWidget):
    def __init__(self,combo,parent=None):
        super().__init__(parent);self.combo=combo;self.buttons={};self.group=QButtonGroup(self);self.group.setExclusive(True);layout=QGridLayout(self)
        layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        import tema
        for index in range(combo.count()):
            key=combo.itemData(index);t=tema.tema(key)
            button=QPushButton(combo.itemText(index));button.setObjectName('themeChoice');button.setCheckable(True)
            button.setAccessibleName(combo.itemText(index)+' teması');button.setMinimumHeight(76)
            self.group.addButton(button)
            button.setIcon(QIcon(tema_kucuk_resim(key)));button.setIconSize(QSize(84,52))
            button.clicked.connect(lambda checked=False,index=index:combo.setCurrentIndex(index))
            button.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);button.setMinimumWidth(60)  # 19 Kas: dar pencerede taşmasın
            layout.addWidget(button,index//2,index%2);self.buttons[key]=button
        combo.currentIndexChanged.connect(self.sync);self.sync()
    def sync(self,*args):
        for key,button in self.buttons.items():button.setChecked(key==self.combo.currentData())

def tema_kucuk_resim(key):
    """Tema seçicide küçük pencere resmi: çerçeve, menü, iki baloncuk, logo."""
    import tema
    t=tema.tema(key);w,h=84,52
    pix=QPixmap(w*2,h*2);pix.fill(Qt.GlobalColor.transparent);pix.setDevicePixelRatio(2.)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
    def renk(c,yedek):return QColor(yedek if c=='transparent' else c)
    p.setBrush(QColor(t['bg']));p.drawRoundedRect(QRectF(0,0,w,h),6 if t['radius'] else 0,6 if t['radius'] else 0)
    if t['header_bg']:p.setBrush(QColor(t['header_bg']));p.drawRect(QRectF(0,0,w,12))
    p.setBrush(renk(t['page'],t['bg']));p.drawRect(QRectF(16,12,w-18,h-14))
    p.setBrush(renk(t['asst_bg'],t['soft']));p.drawRoundedRect(QRectF(20,18,38,8),3,3)
    p.setBrush(renk(t['user_bg'],t['rail_on_bg']));p.drawRoundedRect(QRectF(44,30,34,8),3,3)
    p.setBrush(QColor(t['accent']));p.drawRoundedRect(QRectF(20,h-10,w-26,5),2,2)
    p.drawPixmap(QRectF(3,1,10,10).toRect(),tema.logo_pixmap(key,10))
    p.end();return pix

class MarkaYazisi(QWidget):
    """Yumi yazı markası (12 Kasım ARAYUZ): temaya göre yazı tipi; sade temalarda "yumı" + i noktası vurgu renginde
    yuvarlak (logodaki konuşma balonu noktalarına gönderme), Terminal'de yanıp sönen imleç."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setObjectName('brand');self.metin='yumi';self.key='inci';self._yerlesim()
        self.timer=QTimer(self);self.timer.timeout.connect(self.update)
    def setText(self,text):self.metin=text;self._yerlesim()
    def text(self):return self.metin
    def tema_ayarla(self,key):
        self.key=key;self._yerlesim()
        if key=='terminal':self.timer.start(530)
        else:self.timer.stop()
    def _ozellik(self):
        import tema
        from PySide6.QtGui import QFont
        t=tema.tema(self.key)
        if self.key in ('inci','gece','tas','sakura'):
            f=QFont(tema.aile('Fredoka SemiBold') or tema.aile(t['font']));f.setPixelSize(26 if self.key!='tas' else 24);nokta=True
            if self.key=='tas':f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,.4)
        elif self.key=='witcher':f=QFont(tema.aile('IM FELL English SC'));f.setPixelSize(26);nokta=False
        elif self.key=='terminal':f=QFont(tema.aile('VT323'));f.setPixelSize(30);nokta=False
        else:f=QFont('Microsoft Sans Serif');f.setPixelSize(14);f.setBold(True);nokta=False  # Windows 98 başlık çubuğu yazısı
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return t,f,nokta
    def _yerlesim(self):
        from PySide6.QtGui import QFontMetricsF
        t,f,nokta=self._ozellik();fm=QFontMetricsF(f)
        metin=self.metin.replace('i','ı') if nokta else self.metin
        self.setFixedSize(int(fm.horizontalAdvance(metin)+(16 if self.key=='terminal' else 6)),36);self.update()
    def paintEvent(self,event):
        from PySide6.QtGui import QFontMetricsF
        t,f,nokta=self._ozellik();fm=QFontMetricsF(f)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setRenderHint(QPainter.RenderHint.TextAntialiasing);p.setFont(f)
        renk=QColor(t['header_text'] or t['text']);p.setPen(renk)
        taban=(self.height()+fm.ascent()-fm.descent())/2
        metin=self.metin.replace('i','ı') if nokta else self.metin
        p.drawText(QRectF(0,0,self.width(),self.height()),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,metin)
        if nokta and 'ı' in metin:
            i=metin.index('ı');x=fm.horizontalAdvance(metin[:i])+fm.horizontalAdvance('ı')/2;r=max(2.4,fm.height()*.085)
            y=taban-fm.xHeight()-r*2.1;p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(t['accent'] if self.key!='gece' else '#7FA0FF'));p.drawEllipse(QRectF(x-r,y-r,2*r,2*r))
        if self.key=='terminal' and int(time.perf_counter()*1.9)%2==0:
            x=fm.horizontalAdvance(metin)+3;p.fillRect(QRectF(x,taban-fm.ascent()*.72,9,fm.ascent()*.78),renk)
        p.end()

class SesCubuklari(QWidget):
    """Kayıt sırasında sese tepki veren, soldan kayan mini çubuklar. Ses seviyesi `kaynak()` (0..~0,2 RMS)."""
    def __init__(self,kaynak,parent=None):
        super().__init__(parent);self.kaynak=kaynak;self.renk=QColor('#2F62E9');self.ikinci=None;self.genislik=3;self.aralik=3
        self.degerler=deque([0.]*120,maxlen=160);self.son=0.;self.setMinimumHeight(34);self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.timer=QTimer(self);self.timer.timeout.connect(self._tik)
    def basla(self):
        self.degerler.extend([0.]*40);self.timer.start(40);self.show()
    def dur(self):self.timer.stop()
    def renk_ayarla(self,renk,ikinci=None,genislik=3,aralik=3):
        self.renk=QColor(renk);self.ikinci=QColor(ikinci) if ikinci else None;self.genislik=genislik;self.aralik=aralik;self.update()
    def _tik(self):
        try:seviye=float(self.kaynak() or 0.)
        except Exception:seviye=0.
        # Canlı kabul (13 Kasım): sabit .09 ölçeği kullanıcının mikrofonunda (konuşma RMS ~.01–.03) çubukları
        # taban çizgisinde bırakıyordu → ölçek mikrofona uyarlanır: taban = ortam gürültüsü, tepe = son konuşma tepesi.
        taban=getattr(self,'taban',None);tepe=getattr(self,'tepe',.02)
        taban=seviye if taban is None else (min(seviye,taban*1.002+1e-5) if seviye<taban*1.5 else taban*1.002)
        tepe=max(seviye,tepe*.995,taban*3,.004);self.taban,self.tepe=taban,tepe
        hedef=max(0.,min(1.,(seviye-taban*1.3)/max(tepe-taban*1.3,1e-4)))**.7
        self.son=.45*self.son+.55*hedef
        titresim=.55+.45*((time.perf_counter()*7.3)%1.)
        self.degerler.append(max(.06,self.son*titresim))
        self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(Qt.PenStyle.NoPen)
        h=self.height();adim=self.genislik+self.aralik;adet=max(1,self.width()//adim)
        degerler=list(self.degerler)[-adet:]
        for i,v in enumerate(degerler):
            x=self.width()-(len(degerler)-i)*adim;bh=max(3.,v*(h-4))
            c=QColor(self.ikinci if (self.ikinci and i%3==0) else self.renk)
            c.setAlphaF(min(1.,.25+.75*(i/max(1,len(degerler)-1))**.7))
            p.setBrush(c);p.drawRoundedRect(QRectF(x,(h-bh)/2,self.genislik,bh),self.genislik/2,self.genislik/2)
        p.end()

class KayitNoktasi(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.setFixedSize(10,10);self.renk=QColor('#E5484D');self.timer=QTimer(self);self.timer.timeout.connect(self.update)
    def basla(self):self.timer.start(60)
    def dur(self):self.timer.stop()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);c=QColor(self.renk)
        c.setAlphaF(.4+.6*abs(((time.perf_counter()*.85)%1.)*2-1));p.setPen(Qt.PenStyle.NoPen);p.setBrush(c);p.drawEllipse(1,1,8,8);p.end()

def kayit_gorunumu(w,listening):
    """Kayıt açıkken yazı alanı yerine sayaç + ses çubukları; kapanınca geri döner."""
    if not hasattr(w,'ses_cubuklari'):return
    for widget in (w.input,w.send_button):widget.setVisible(not listening)
    for widget in (w.kayit_noktasi,w.kayit_suresi,w.ses_cubuklari):widget.setVisible(listening)
    w.composer_frame.setProperty('recording','true' if listening else 'false');w.composer_frame.style().unpolish(w.composer_frame);w.composer_frame.style().polish(w.composer_frame)
    if listening:
        w.kayit_baslangic=time.perf_counter();w.ses_cubuklari.basla();w.kayit_noktasi.basla();w.kayit_saati.start(250);_sure_yaz(w)
    else:
        w.ses_cubuklari.dur();w.kayit_noktasi.dur();w.kayit_saati.stop();w.live_text.hide()
    w.mic_button.setObjectName('recordStop' if listening else 'micButton');w.mic_button.style().unpolish(w.mic_button);w.mic_button.style().polish(w.mic_button)

def _sure_yaz(w):
    s=int(time.perf_counter()-getattr(w,'kayit_baslangic',time.perf_counter()));w.kayit_suresi.setText(f'{s//60}:{s%60:02d}')

def canli_yazi(w,text):
    """Duyulan sözün canlı yazısı (kayıt alanının üstünde)."""
    if not hasattr(w,'live_text'):return
    text=' '.join(str(text or '').split())
    w.live_text.setText(f'“{text[-80:]}…”' if text else '');w.live_text.setVisible(bool(text))

# ------------------------------------------------------------- geçmiş sayfası
def _zaman_etiketi(stamp,now):
    import datetime as dt
    a=dt.datetime.fromtimestamp(stamp);b=dt.datetime.fromtimestamp(now)
    if a.date()==b.date():return a.strftime('%H:%M')
    gunler=['Pzt','Sal','Çar','Per','Cum','Cmt','Paz']
    if (b.date()-a.date()).days<7:return gunler[a.weekday()]
    return a.strftime('%d.%m')

def _grup(stamp,now):
    import datetime as dt
    a=dt.datetime.fromtimestamp(stamp).date();b=dt.datetime.fromtimestamp(now).date();fark=(b-a).days
    return 'Bugün' if fark<=0 else 'Dün' if fark==1 else 'Bu hafta' if fark<7 else 'Daha eski'

def gecmis_doldur(w,chats,active,title,initial,now):
    """Sohbet listesi: tarih grupları + satır (baş harf, başlık, son mesaj, saat). Satır verisi UserRole=sohbet id."""
    liste=w.chat_list;liste.clear();aranan=w.history_search.text().strip().casefold() if hasattr(w,'history_search') else ''
    son_grup=None
    for chat in sorted(chats,key=lambda c:c['updated_at'],reverse=True):
        baslik=title(chat);son=next((m['text'] for m in reversed(chat['messages'])),'Henüz mesaj yok')
        if aranan and aranan not in baslik.casefold() and not any(aranan in m['text'].casefold() for m in chat['messages']):continue
        grup=_grup(chat['updated_at'],now)
        if grup!=son_grup:
            son_grup=grup;item=QListWidgetItem();item.setFlags(Qt.ItemFlag.NoItemFlags);item.setData(Qt.ItemDataRole.UserRole,None)
            label=QLabel(grup);label.setObjectName('historyGroup');item.setSizeHint(QSize(10,34));liste.addItem(item);liste.setItemWidget(item,label)
        item=QListWidgetItem();item.setData(Qt.ItemDataRole.UserRole,chat['id']);item.setToolTip(baslik)
        satir=QWidget();satir.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        r=QHBoxLayout(satir);r.setContentsMargins(10,9,10,9);r.setSpacing(10)
        av=QLabel(initial);av.setObjectName('historyAvatar');av.setFixedSize(30,30);av.setAlignment(Qt.AlignmentFlag.AlignCenter);r.addWidget(av,0,Qt.AlignmentFlag.AlignTop)
        metin=QVBoxLayout();metin.setSpacing(2);ust=QHBoxLayout();ust.setSpacing(8)
        b=QLabel(baslik);b.setObjectName('historyTitle');b.setMinimumWidth(0);b.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);ust.addWidget(b,1)
        z=QLabel(_zaman_etiketi(chat['updated_at'],now));z.setObjectName('historyTime');ust.addWidget(z);metin.addLayout(ust)
        s=QLabel(' '.join(son.split())[:90]);s.setObjectName('historySnippet');s.setMinimumWidth(0);s.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);metin.addWidget(s)
        r.addLayout(metin,1);item.setSizeHint(QSize(10,64));liste.addItem(item);liste.setItemWidget(item,satir)
        if chat['id']==active:liste.setCurrentItem(item)
    if liste.count()==0:
        item=QListWidgetItem();item.setFlags(Qt.ItemFlag.NoItemFlags);item.setData(Qt.ItemDataRole.UserRole,None)
        label=QLabel('Aramana uyan sohbet yok.' if aranan else 'Henüz sohbet yok. Yeni sohbet başlat.');label.setObjectName('historySnippet');label.setContentsMargins(10,14,10,14)
        item.setSizeHint(QSize(10,48));liste.addItem(item);liste.setItemWidget(item,label)

def sohbet_goster(w):
    w.chat_stack.setCurrentIndex(0)
def gecmis_goster(w):
    w._refresh_chat_list();w.chat_stack.setCurrentIndex(1);w.history_search.setFocus()

def build_window(w):
    """Build controls around the existing action handlers and state fields."""
    from avatar import AvatarView
    from page_stack import PageStack
    root=QWidget();root.setObjectName('root');w.setCentralWidget(root)
    outer=QVBoxLayout(root);outer.setContentsMargins(1,1,1,1);outer.setSpacing(0)
    header=QFrame();header.setObjectName('header');header.setFixedHeight(60);header.installEventFilter(w)
    row=QHBoxLayout(header);row.setContentsMargins(18,6,12,4);row.setSpacing(10)
    w.logo_label=QLabel();w.logo_label.setObjectName('logo');w.logo_label.setFixedSize(30,30);w.logo_label.installEventFilter(w);row.addWidget(w.logo_label)
    title=MarkaYazisi();title.installEventFilter(w);w.brand_label=title;row.addWidget(title)
    description=QLabel('Masaüstü asistanın');description.setObjectName('brandDescription');w.brand_description=description;row.addWidget(description);row.addStretch()
    from model_visibility import visible,set_visible
    w.model_visibility_button=QPushButton();w.model_visibility_button.setProperty('iconOnly',True)
    w.model_visibility_button.setObjectName('iconButton');w.model_visibility_button.setFixedSize(34,34)
    w.model_visibility_button.setAccessibleName('Modeli gizle veya göster')
    w.model_visibility_button.clicked.connect(lambda:set_visible(w,not visible(w)));row.addWidget(w.model_visibility_button)
    w.header_buttons={}
    for key,tip,callback in [('minimize','Pencereyi gizle',w.hide),('close','Sistem tepsisine küçült',w.hide)]:
        button=QPushButton();button.setObjectName('iconButton');button.setFixedSize(34,34);button.setToolTip(tip);button.setAccessibleName(tip);button.clicked.connect(callback);row.addWidget(button);w.header_buttons[key]=button
    outer.addWidget(header)
    stage=QFrame();stage.setObjectName('stage');stage.setFixedHeight(26)
    row=QHBoxLayout(stage);row.setContentsMargins(22,0,18,6)
    from modelsiz import ModelsizAvatar,acik as modelsiz_acik
    w.avatar=ModelsizAvatar(stage,kapali=lambda:modelsiz_acik(w));w.avatar.skin=w.settings['skin'];w.avatar.hide();w.avatar.timer.stop()
    w.bubble=QLabel('',stage);w.bubble.hide()
    w.status=QLabel('Hazır');w.status.setObjectName('status');w.status.setMinimumWidth(0);w.status.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);row.addWidget(w.status,1)
    outer.addWidget(stage);w.stage=stage
    w.web_recovery=QWidget();recovery=QVBoxLayout(w.web_recovery)
    w.web_recovery.setObjectName('uyariBandi');w.web_recovery.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)  # 17 Kasım: uyarı bandı her temada üst bant renklerinde okunur
    recovery.setContentsMargins(22,6,18,8)
    w.web_recovery_text=QLabel('Web bağlantısı hazır değil. Sohbetin korunuyor.');w.web_recovery_text.setWordWrap(True)
    w.web_recovery_text.setMinimumWidth(0);recovery.addWidget(w.web_recovery_text)
    actions=QGridLayout();actions.setColumnStretch(0,1);actions.setColumnStretch(1,1);actions.setColumnStretch(2,1);recovery.addLayout(actions)
    w.web_retry_button=QPushButton('Yeniden bağlan');w.web_retry_button.clicked.connect(w._retry_browser);actions.addWidget(w.web_retry_button,0,0)
    for text,finish in [('Site doğrulamasını aç',False),('Doğrulamayı tamamladım',True)]:
        button=QPushButton('Giriş tamamlandı' if finish else 'Giriş yap');button.setAccessibleName(text);button.setToolTip(text);button.clicked.connect(lambda _=False,finish=finish:w._browser_login(w.settings['provider'],finish));actions.addWidget(button,0,2 if finish else 1)
        if finish:w.web_finish_button=button;button.setEnabled(False)
        else:w.web_login_button=button
    outer.addWidget(w.web_recovery);w.web_recovery.hide()
    w.native_recovery=QWidget();recovery=QHBoxLayout(w.native_recovery)
    w.native_recovery.setObjectName('uyariBandi');w.native_recovery.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)  # 17 Kasım: uyarı bandı her temada üst bant renklerinde okunur
    recovery.setContentsMargins(22,6,18,8)
    w.native_recovery_text=QLabel();w.native_recovery_text.setWordWrap(True)
    w.native_recovery_text.setMinimumWidth(0);recovery.addWidget(w.native_recovery_text,1)
    w.native_reconnect_button=QPushButton('Sese yeniden bağlan')
    w.native_reconnect_button.clicked.connect(w._reconnect_native);recovery.addWidget(w.native_reconnect_button)
    outer.addWidget(w.native_recovery);w.native_recovery.hide()
    body=QHBoxLayout();body.setContentsMargins(0,0,0,0);body.setSpacing(0);outer.addLayout(body,1)
    w.navigation=NavigationRail([
        # 12 Kasım 19:00 (kullanıcı): tek Ayarlar düğmesi; içinde 0 Model, 1 AI Web, 2 Temalar (Görünüm 13 Kasım'da kalktı).
        ('chat','Sohbet',w._nav_chat),
        ('motion','Hareket',lambda:w._route_page('motion',w._activities)),
        ('home','Ev',lambda:w._route_page('home',w._open_smart_home)),
        ('settings','Ayarlar',lambda:w._nav_settings(0,'settings'))])
    w.navigation.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Ignored)
    w.navigation.group.buttonToggled.connect(lambda *_:w._refresh_icons())
    body.addWidget(w.navigation)
    w.pages=PageStack(reduced_motion=w.settings.get('reduce_motion',False));w.pages.pageClosed.connect(w._page_closed)
    # 13 Kasım: sayfalar bir çerçevede; Witcher'da çerçeve parşömen yaprağını çizer, iç boşluk sayfaları tırtıklı kenarın içine alır
    w.yaprak_alani=QWidget();w.yaprak_alani.setObjectName('yaprakAlani');_ya=QVBoxLayout(w.yaprak_alani);_ya.setContentsMargins(0,0,0,0);_ya.addWidget(w.pages)
    body.addWidget(w.yaprak_alani,1)
    w.panel=QFrame();w.panel.setObjectName('panel');w.pages.addWidget(w.panel)
    import tema
    w.dekor=tema.Dekor(w.panel,lambda:w._tema_gorselleri() if hasattr(w,'_tema_gorselleri') else [],zemin=w.yaprak_alani)  # 13 Kasım: Witcher yaprağı sayfa çerçevesinde
    layout=QVBoxLayout(w.panel);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
    w.chat_stack=QStackedWidget();w.chat_stack.setObjectName('chatStack');layout.addWidget(w.chat_stack)
    # --- sohbet görünümü
    chat_page=QWidget();chat_page.setObjectName('chatPage');w.chat_stack.addWidget(chat_page)
    cl=QVBoxLayout(chat_page);cl.setContentsMargins(16,10,18,16);cl.setSpacing(10)
    top=QHBoxLayout();top.setSpacing(6)
    name=QLabel('Sohbet');name.setObjectName('heading');top.addWidget(name);top.addStretch()
    w.badge=QLabel('');w.badge.setObjectName('badge');w.badge.hide()
    w.history_button=QPushButton();w.history_button.setObjectName('historyButton');w.history_button.setFixedSize(34,34);w.history_button.setToolTip('Sohbet geçmişi');w.history_button.setAccessibleName('Sohbet geçmişi');w.history_button.clicked.connect(lambda:gecmis_goster(w));top.addWidget(w.history_button)
    w.wave_button=QPushButton();w.wave_button.setObjectName('stageButton');w.wave_button.setFixedSize(34,34);w.wave_button.setAccessibleName('El salla');w.wave_button.setToolTip('El salla');w.wave_button.clicked.connect(w._wave);top.addWidget(w.wave_button)
    cl.addLayout(top)
    # eski kodla uyum: chat_toggle/chat_sidebar/chat_messages artık kullanılmıyor (ayrı Geçmiş sayfası)
    w.chat_toggle=QPushButton();w.chat_toggle.setCheckable(True);w.chat_toggle.hide()
    w.chat_messages=chat_page
    w.scroll=QScrollArea();w.scroll.setObjectName('chatScroll');w.scroll.setWidgetResizable(True);w.scroll.setFrameShape(QFrame.Shape.NoFrame);w.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);w.scroll.viewport().setAutoFillBackground(False)
    w.message_box=QWidget();w.message_box.setObjectName('messageContent');w.message_layout=QVBoxLayout(w.message_box)
    w.message_layout.setContentsMargins(4,8,4,4);w.message_layout.setSpacing(12);w.message_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize);w.message_layout.addStretch();w.message_labels=[]
    w.scroll.setWidget(w.message_box);w.scroll.viewport().installEventFilter(w);cl.addWidget(w.scroll,1)
    w.jump_button=QPushButton('Son mesaja dön',w.scroll.viewport());w.jump_button.setObjectName('jumpButton');w.jump_button.setFixedSize(132,34);w.jump_button.clicked.connect(w._jump_latest);w.jump_button.hide()
    w.scroll.verticalScrollBar().valueChanged.connect(w._update_jump);w.scroll.verticalScrollBar().rangeChanged.connect(w._update_jump)
    w.live_text=QLabel('');w.live_text.setObjectName('liveText');w.live_text.setMinimumWidth(0);w.live_text.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);w.live_text.hide();cl.addWidget(w.live_text)
    w.composer_frame=composer_frame=QFrame();composer_frame.setObjectName('composer');composer_frame.setMinimumHeight(56);composer=QHBoxLayout(composer_frame);composer.setContentsMargins(8,6,6,6);composer.setSpacing(8)
    w.mic_button=QPushButton();w.mic_button.setObjectName('micButton');w.mic_button.setCheckable(True);w.mic_button.setFixedSize(42,42);w.mic_button.setAccessibleName('Sesli sohbeti başlat veya durdur');w.mic_button.setToolTip('Sesli sohbeti başlat / durdur');w.mic_button.clicked.connect(w._mic);composer.addWidget(w.mic_button)
    w.kayit_noktasi=KayitNoktasi();w.kayit_noktasi.hide();composer.addWidget(w.kayit_noktasi)
    w.kayit_suresi=QLabel('0:00');w.kayit_suresi.setObjectName('recordTime');w.kayit_suresi.hide();composer.addWidget(w.kayit_suresi)
    w.ses_cubuklari=SesCubuklari(lambda:getattr(getattr(w,'voice_capture',None),'level',0.));w.ses_cubuklari.hide();composer.addWidget(w.ses_cubuklari,1)
    w.kayit_saati=QTimer(w);w.kayit_saati.timeout.connect(lambda:_sure_yaz(w))
    w.input=QLineEdit();w.input.setMaxLength(4000);w.input.setMinimumWidth(40);w.input.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);w.input.setObjectName('messageInput');w.input.setPlaceholderText('Yumi’ye bir şey yaz…');w.input.setAccessibleName('Mesajın');w.input.returnPressed.connect(w._send);composer.addWidget(w.input,1)
    w.send_button=QPushButton();w.send_button.setObjectName('sendButton');w.send_button.setFixedSize(42,42);w.send_button.setToolTip('Mesajı gönder');w.send_button.setAccessibleName('Mesajı gönder');w.send_button.clicked.connect(w._send);composer.addWidget(w.send_button)
    w.stop_reply_button=QPushButton('Durdur');w.stop_reply_button.hide();w.stop_reply_button.clicked.connect(w._cancel_reply);composer.addWidget(w.stop_reply_button)
    cl.addWidget(composer_frame)
    # --- geçmiş görünümü
    history_page=QWidget();history_page.setObjectName('historyPage');w.chat_stack.addWidget(history_page)
    hl=QVBoxLayout(history_page);hl.setContentsMargins(12,10,18,14);hl.setSpacing(8)
    top=QHBoxLayout();top.setSpacing(6)
    w.history_back=QPushButton();w.history_back.setObjectName('backButton');w.history_back.setFixedSize(34,34);w.history_back.setToolTip('Sohbete dön');w.history_back.setAccessibleName('Sohbete dön');w.history_back.clicked.connect(lambda:sohbet_goster(w));top.addWidget(w.history_back)
    name=QLabel('Geçmiş');name.setObjectName('heading');top.addWidget(name);top.addStretch()
    w.new_chat_button=QPushButton('Yeni sohbet');w.new_chat_button.setObjectName('newChat');w.new_chat_button.clicked.connect(lambda:(w._new_chat(),sohbet_goster(w)));top.addWidget(w.new_chat_button)
    hl.addLayout(top)
    w.history_search=QLineEdit();w.history_search.setObjectName('searchInput');w.history_search.setPlaceholderText('Sohbetlerde ara');w.history_search.setAccessibleName('Sohbetlerde ara');w.history_search.setClearButtonEnabled(True)
    w.history_search.textChanged.connect(lambda *_:w._refresh_chat_list());hl.addWidget(w.history_search)
    w.chat_list=QListWidget();w.chat_list.setObjectName('chatList');w.chat_list.setAccessibleName('Sohbet geçmişi');w.chat_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
    w.chat_list.itemClicked.connect(w._select_chat_item);w.chat_list.itemActivated.connect(w._select_chat_item)
    w.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);w.chat_list.customContextMenuRequested.connect(w._chat_context_menu);hl.addWidget(w.chat_list,1)
    w.delete_chat_button=QPushButton('Sohbeti sil');w.delete_chat_button.hide();w.delete_chat_button.clicked.connect(lambda:w._delete_chat())
    retention=QLabel('Sohbetler son mesajdan 5 gün sonra silinir. Silmek için sağ tıkla.');retention.setObjectName('caption');retention.setWordWrap(True);hl.addWidget(retention)
    w.chat_sidebar=history_page
    w._load_chat_history()
    # Alt bilgi satırı kaldırıldı (kullanıcı, 12 Kasım); boyut tutamacı satır kaplamadan sağ alt köşede durur.
    w.size_grip=QSizeGrip(root);w.size_grip.setFixedSize(17,17);w.size_grip.raise_()
    w.apply_theme()
