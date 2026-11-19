"""Isolated offline upstream VRM renderer for import and source comparison."""
import json,logging
from pathlib import Path
from PySide6.QtCore import Qt,QUrl,QTimer,Signal,QCoreApplication
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QDialog,QPushButton
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings,QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
ROOT=Path(__file__).resolve().parents[1]/'vrm_runtime'
if QCoreApplication.instance() is None:QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

class LocalFilesOnly(QWebEngineUrlRequestInterceptor):
    def __init__(self,parent):super().__init__(parent);self.asset=None;self.assets=set()
    def interceptRequest(self,info):
        url=info.requestUrl();scheme=url.scheme()
        allowed=scheme in ('data','blob','about')
        if scheme=='file':
            target=Path(url.toLocalFile()).resolve()
            allowed=target.is_relative_to(ROOT) or target==self.asset or target in self.assets
        if not allowed:info.block(True)

class LocalPage(QWebEnginePage):
    def javaScriptConsoleMessage(self,level,message,line,source):
        logging.getLogger(__name__).warning('three-vrm viewer [%s:%s] %s',Path(source).name,line,message)
    def acceptNavigationRequest(self,url,kind,main):
        return url==QUrl.fromLocalFile(str(ROOT/'viewer.html')) or url.toString()=='about:blank'

class ThreeVRMView(QWidget):
    ready=Signal(dict);failed=Signal(str)
    def __init__(self,parent=None,path=None,transparent=False):
        super().__init__(parent);self.desktop=bool(transparent);self.model_error=None;self.status={};self.path=None;self.started=False;self.polling=False;self.load_requested=False;self.generation=0;self.disposed=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.web=QWebEngineView(self);layout.addWidget(self.web,1)
        self.label=QLabel('Karakter three-vrm ile hazırlanıyor…');self.label.setWordWrap(True);layout.addWidget(self.label)
        self.profile=QWebEngineProfile(self);self.guard=LocalFilesOnly(self.profile);self.profile.setUrlRequestInterceptor(self.guard)
        bg=QColor(0,0,0,0) if transparent else (self.palette().window().color() if hasattr(self,'palette') else QColor(245,245,248))
        self.page=LocalPage(self.profile,self.web);self.page.setBackgroundColor(bg);self.web.setPage(self.page)
        if transparent:self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,False)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,True)
        self.profile.downloadRequested.connect(lambda download:download.cancel())
        self.timer=QTimer(self);self.timer.setInterval(120);self.timer.timeout.connect(self.poll)
        self.web.loadFinished.connect(self._loaded);self.web.setUrl(QUrl.fromLocalFile(str(ROOT/'viewer.html')))
        if path:self.load_model(path)
    def load_model(self,path):
        self.path=Path(path).resolve();self.guard.asset=self.path;self.model_error=None;self.status={}
        self.generation+=1
        generation=self.generation;QTimer.singleShot(20000,lambda:self._timeout(generation))
        self.load_requested=False
        self.label.setText('Karakter three-vrm ile hazırlanıyor…')
        if self.started:self.timer.start()
    def load_now(self):
        """M16: görüntüleyici hazırsa yüklemeyi yoklama turunu beklemeden hemen gönder (hazır değilse eski yol)."""
        if self.started and self.path is not None and not self.disposed and not self.load_requested:self._load_model()
    def _loaded(self,ok):
        self.started=ok
        if not ok:self._error('three-vrm görüntüleyicisi açılamadı.');return
        if self.path:self.timer.start()
    def _load_model(self):
        self.load_requested=True
        url=QUrl.fromLocalFile(str(self.path)).toString()
        # M16: masaüstü köprüsü (şeffaf görünüm) önizleme kamerası kutusunu istemez
        # 18 Kas (goz_el): Witcher paketinde ters goz kapagi duzeltmesi; anime/retro icin bos -> cagri eskisiyle ayni
        from witcher_eyes import viewer_options
        extra=viewer_options(self.path)
        if extra:options=','+json.dumps({**({'desktop':True} if self.desktop else {}),**extra})
        else:options=',{desktop:true}' if self.desktop else ''
        self.page.runJavaScript('window.yumiVRM?.load('+json.dumps(url)+options+')')
        self.timer.start();generation=self.generation
        QTimer.singleShot(20000,lambda:self._timeout(generation))
    def _timeout(self,generation):
        if generation==self.generation and not self.disposed and not self.status.get('ready') and not self.model_error:self._error('three-vrm model yükleme süresi aşıldı.')
    def poll(self):
        if self.polling or self.disposed:return
        self.polling=True
        self.page.runJavaScript('JSON.stringify(window.yumiVRM?.status ?? null)',self._status)
    def _status(self,value):
        self.polling=False
        if self.disposed:return
        if isinstance(value,str):
            try:value=json.loads(value)
            except ValueError:return
        if not isinstance(value,dict):return
        if not self.load_requested:
            self._load_model();return
        if value.get('url')!=QUrl.fromLocalFile(str(self.path)).toString():return
        self.status=value
        if value.get('error'):self._error(value['error'])
        elif value.get('ready'):
            self.timer.stop();self.label.setText('three-vrm · modelin kendi malzemeleri ve fiziği');self.ready.emit(value)
    def _error(self,error):
        self.timer.stop();self.model_error=str(error);self.label.setText('Model açılamadı: '+str(error));self.failed.emit(str(error))
    def dispose(self):
        self.disposed=True;self.generation+=1
        self.timer.stop();self.page.runJavaScript('window.yumiVRM?.dispose()');self.web.stop()
    def hideEvent(self,event):
        super().hideEvent(event)
        if self.started:self.page.runJavaScript('window.yumiVRM?.pause(true)')
    def showEvent(self,event):
        super().showEvent(event)
        if self.started:self.page.runJavaScript('window.yumiVRM?.pause(false)')

class ThreeVRMInspection(QDialog):
    def __init__(self,owner,path):
        super().__init__(owner);self.setWindowTitle('Karakter önizlemesi');self.setWindowFlags(Qt.WindowType.Widget)
        layout=QVBoxLayout(self);title=QLabel('Karakter önizlemesi');title.setStyleSheet('font-size:20px;font-weight:600');layout.addWidget(title)
        self.preview=ThreeVRMView(self,path);self.preview.setMinimumHeight(350);layout.addWidget(self.preview,1)
        note=QLabel('Modelin kendi malzemeleri ve tanımlı fiziği gösterilir. Bu görünüm masaüstü hareketlerini veya tam kumaş çarpışmasını doğrulamaz.');note.setWordWrap(True);layout.addWidget(note)
        close=QPushButton('Geri dön');close.clicked.connect(self.reject);layout.addWidget(close)
    def dispose(self):
        self.preview.dispose();self.deleteLater()


class ThreeVRMWindow(QWidget):
    """Önizleme kendi opak üst penceresinde: Yumi'nin ana penceresi şeffaf (WA_TranslucentBackground) ve
    Windows şeffaf pencere içindeki Chromium/WebGL çizimini göstermiyor (6 Kasım ölçümü:
    work/kuyruk/is_003_onizleme.py, şeffaf pencerede ekran boş, normal pencerede model görünüyor).
    12 Kasım ARAYUZ: çerçevesiz, temaya uygun pop-up; başlıktan sürüklenir; Yumi penceresinin ortasında açılır."""
    closed=Signal()
    def __init__(self,owner,path,ad=None,kullan=None):
        super().__init__(None,Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint);self.setWindowTitle('Karakter önizlemesi');self.resize(400,580)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);self.setObjectName('previewWindow');self._surukle=None
        try:
            import tema
            t=tema.tema(owner.settings.get('theme','inci')) if owner is not None else tema.tema('inci')
            sahne=t['page'] if t['dark'] else ('#16203A' if t['deco'] not in ('witcher','terminal') else ('#2E1F15' if t['deco']=='witcher' else '#021208'))
            if owner is not None:self.setStyleSheet(owner.styleSheet()+f' #previewWindow{{background:{t["page"] if t["deco"]!="witcher" else "#E9DDBF"};border:1px solid {t["line"]}}}')
        except Exception:sahne='#16203A'
        layout=QVBoxLayout(self);layout.setContentsMargins(16,12,16,16);layout.setSpacing(10)
        self.baslik=QWidget();bl=QHBoxLayout(self.baslik);bl.setContentsMargins(4,0,0,0)
        title=QLabel(ad or 'Karakter önizlemesi');title.setObjectName('heading');bl.addWidget(title,1)
        kapat=QPushButton('✕');kapat.setObjectName('iconButton');kapat.setFixedSize(34,34);kapat.setAccessibleName('Kapat');kapat.clicked.connect(self.close);bl.addWidget(kapat)
        self.baslik.installEventFilter(self);title.installEventFilter(self);layout.addWidget(self.baslik)
        self.preview=ThreeVRMView(self,path);self.preview.setMinimumHeight(360);layout.addWidget(self.preview,1)
        try:self.preview.page.setBackgroundColor(QColor(sahne))
        except Exception:pass
        self.preview.label.setObjectName('caption')
        ipucu=QLabel('Sürükleyerek döndür, tekerlekle yakınlaştır');ipucu.setObjectName('caption');layout.addWidget(ipucu)
        satir=QHBoxLayout();satir.setSpacing(8)
        close=QPushButton('Kapat');close.clicked.connect(self.close);satir.addWidget(close,1)
        if kullan:
            sec=QPushButton('Bu modeli kullan');sec.setObjectName('primaryButton');sec.clicked.connect(lambda:(self.close(),kullan()));satir.addWidget(sec,2)
        layout.addLayout(satir)
        if owner is not None:
            g=owner.frameGeometry();self.move(g.left()+max(0,(g.width()-self.width())//2),g.top()+max(0,(g.height()-self.height())//2))
    def eventFilter(self,obj,event):
        from PySide6.QtCore import QEvent
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
            self._surukle=event.globalPosition().toPoint()-self.pos();return True
        if event.type()==QEvent.Type.MouseMove and self._surukle is not None:
            self.move(event.globalPosition().toPoint()-self._surukle);return True
        if event.type()==QEvent.Type.MouseButtonRelease:self._surukle=None
        return super().eventFilter(obj,event)
    def closeEvent(self,event):
        self.preview.dispose();self.closed.emit();super().closeEvent(event)
