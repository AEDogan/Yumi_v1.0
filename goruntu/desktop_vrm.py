"""Bounded latest-frame bridge to the upstream material renderer.

Python owns animation, IK, source SpringBone and prop placement. The browser
only draws the final pose; it never runs a second physics simulation.
"""
import json,time,base64
import numpy as np
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from PySide6.QtCore import Qt,QUrl,QTimer
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QImage,QPixmap
from three_vrm_view import ThreeVRMView

PROP_SINK=ContextVar('yumi_prop_sink',default=None)

class DesktopVRM:
    def __init__(self,host):
        self.host=host;self.path=None;self.inflight=False;self.last=0.;self.props=[]
        self.failed=False;self.ready=False;self.generation=0
        # 19 Kas: zaman aşımı kalıcı düşüş olmasın (paket kurulurken arayüz donunca model yedek GL çizicide kalıyordu).
        self.son_begin=None;self.dusus_zamani=0.;self.deneme=0;self.dusus_yolu=None
        self.present_pending=False;self.disposed=False;self.paused=False;self.delivered=False;self.pending=None
        self.view=ThreeVRMView(host.parentWidget() or host,transparent=True);self.view.label.hide()
        self.display=QLabel(host.parentWidget() or host);self.display.setScaledContents(True)
        self.display.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.display.hide()
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.view.ready.connect(self._ready);self.view.failed.connect(self._failed)
        self.view.page.renderProcessTerminated.connect(lambda status,code:self._failed('Görsel motor durdu ('+str(code)+').'))
        self.view.hide()
    def preload(self,path):
        """M16 (17 Kas): yeni modelin three-vrm yüklemesini Python model kurulumundan ÖNCE başlat.
        begin()'in yol değişiminde yaptığı sıfırlamanın aynısı; yalnız yükleme ilk çizim + yoklama
        turunu beklemeden hemen gönderilir. Kurulum başarısız olursa begin() eski modelin yoluna döner."""
        if self.disposed or path is None:return
        path=Path(path).resolve()
        if path==self.path:return
        self.path=path;self.ready=False;self.failed=False;self.generation+=1;self.inflight=False;self.delivered=False;self.pending=None
        self.display.clear();self.display.hide()
        self.view.load_model(path);self.view.load_now()
    def _ready(self,status):
        if self.disposed or self.path is None or status.get('url')!=QUrl.fromLocalFile(str(self.path)).toString():return
        self.ready=True;self.deneme=0;self.view.page.runJavaScript('window.yumiVRM.pause(true)')
        # M16: hazır olur olmaz ilk pozu gönder (yükleme sırasında seyreltilmiş kare sırasını bekleme)
        self.host.next_frame=0.;self.host.update()
    def _failed(self,message):
        if self.disposed:return
        self.ready=False;self.failed=True;self.pending=None;self.view.hide();self.display.hide()
        self.dusus_zamani=time.perf_counter();self.dusus_yolu=self.path
        self.host.runtimeWarning.emit('three-vrm masaüstü çizimi açılamadı: '+message)
    def begin(self):
        if self.disposed:return False
        model=self.host.model
        if model is None:
            if self.path is not None:self.generation+=1
            self.view.hide();self.display.hide();self.ready=False;self.path=None;return False
        path=model.data.path.resolve()
        if path!=self.path:
            self.path=path;self.ready=False;self.failed=False;self.generation+=1;self.inflight=False;self.delivered=False;self.pending=None
            self.display.clear();self.display.hide()
            QTimer.singleShot(0,lambda p=path:self.view.load_model(p) if p==self.path else None)
        simdi=time.perf_counter()
        if self.son_begin is not None and simdi-self.son_begin>1.:
            # Arayüz iş parçacığı donmuştu (disk/CPU doygunluğu): bu süre çizicinin yanıt süresine sayılmaz.
            self.last+=simdi-self.son_begin
        self.son_begin=simdi
        if self.failed:
            # Geçici düşüşten sonra aynı modeli three-vrm'de yeniden yükle (en çok 3 kez, aralar 3/10/30 s).
            if self.dusus_yolu==path and self.deneme<3 and simdi-self.dusus_zamani>(3,10,30)[self.deneme]:
                self.deneme+=1;self.failed=False;self.path=None
                return self.begin()
            return False
        # First draw compiles this model's material shaders. Give it the same
        # bounded startup budget as the model loader, then enforce 5s per frame.
        if self.inflight and time.perf_counter()-self.last>(5 if self.delivered else 20):
            self._failed('Çizici yanıt süresi aşıldı.');return False
        geometry=self.host.geometry() if self.display.parentWidget() is self.host.parentWidget() else self.host.rect()
        if self.delivered and (self.display.geometry()!=geometry or self.display.isHidden()) and not self.present_pending:
            self.present_pending=True;QTimer.singleShot(0,self._present)
        self.props=[];self.pole_frame=None
        return self.ready
    def _present(self):
        self.present_pending=False
        if self.disposed or self.failed or self.path is None or self.paused or not self.delivered or not self.host.isVisible():return
        geometry=self.host.geometry() if self.display.parentWidget() is self.host.parentWidget() else self.host.rect()
        self.display.setGeometry(geometry);self.display.show();self.display.raise_()
    def pole(self,point,height,radius,visible,matrix):
        transform=np.eye(4);transform[:3,3]=point
        scale=np.diag([visible,visible,visible,1.])
        self.pole_frame={'matrix':(matrix@transform@scale).T.ravel().tolist(),'height':float(height),'radius':float(radius)}
    @contextmanager
    def capture_props(self):
        token=PROP_SINK.set(self if self.ready else None)
        try:yield
        finally:PROP_SINK.reset(token)
    def capture(self,asset,exclude,include,placements,animation_time,opacity):
        from OpenGL.GL import glGetDoublev,GL_MODELVIEW_MATRIX
        matrix=np.asarray(glGetDoublev(GL_MODELVIEW_MATRIX),float).T
        animation=asset.animation_matrices(animation_time) if animation_time is not None else {}
        url=QUrl.fromLocalFile(str(asset.path.resolve())).toString()
        self.view.guard.assets.add(asset.path.resolve())
        parts=[];ordinals={}
        for index,part in enumerate(asset.parts):
            ordinal=ordinals.get(part['node'],0);ordinals[part['node']]=ordinal+1
            name=part['name']
            if any(word.casefold() in name.casefold() for word in exclude):continue
            if include and not any(word.casefold() in name.casefold() for word in include):continue
            transform=matrix.copy()
            if placements is not None:
                if name not in placements:continue
                anchor,scale,target,yaw=placements[name]
                from furniture_scene import rotation
                translate=np.eye(4);translate[:3,3]=target
                resize=np.diag([*scale,1.]);shift=np.eye(4);shift[:3,3]=-anchor
                turn=np.eye(4);turn[:3,:3]=rotation(yaw)
                transform=transform@translate@resize@shift@turn
            if part['node'] in animation:transform=transform@animation[part['node']]
            parts.append({'part':index,'node':part['node'],'primitive':ordinal,'mesh':part['mesh'],'matrix':transform.T.ravel().tolist()})
        self.props.append({'url':url,'parts':parts,'opacity':float(opacity)})
    def submit(self,matrix):
        now=time.perf_counter()
        if self.disposed or self.paused or not self.host.isVisible() or not self.ready:return
        if self.inflight:
            # Pipeline: prepare one pose while the renderer draws the previous one.
            if self.pending is None and self.delivered:self.pending=(self._build(matrix,now),self.generation)
            return
        if now-self.last<1/60:return
        self._send(self._build(matrix,now))
    def _build(self,matrix,now):
        model=self.host.model;d=model.data
        # Batched local matrices: same per-node solve as before, sent as float64 bytes.
        if getattr(self,'_hierarchy_for',None) is not d:
            child=[n for n in range(len(d.nodes)) if d.parents.get(n) is not None]
            self._child=np.array(child,dtype=np.int64);self._parent=np.array([d.parents[n] for n in child],dtype=np.int64)
            self._hierarchy_for=d
        local=np.array(model.world,dtype=float,copy=True)
        if len(self._child):local[self._child]=np.linalg.solve(model.world[self._parent],model.world[self._child])
        nodes=base64.b64encode(np.ascontiguousarray(local.transpose(0,2,1),dtype='<f8').tobytes()).decode('ascii')
        canonical=np.eye(4);canonical[:3,:3]=d.flip*d.scale;canonical[:3,3]=-d.origin*d.scale
        frame={'width':self.host.width(),'height':self.host.height(),'dpr':self.host.devicePixelRatioF(),'matrix':(matrix@canonical).T.ravel().tolist(),'nodesB64':nodes,
               'expressions':[[mesh,index,float(value)] for (mesh,index),value in getattr(model,'expression_weights',{}).items()],
               'props':self.props,'pole':self.pole_frame}
        from seated_garment import patches
        frame['garments']=patches(model)
        from live_cloth import patches as live_cloth_patches
        live=live_cloth_patches(model,now)
        if live:
            owned={patch['part'] for patch in live}
            frame['garments']=[patch for patch in frame['garments'] if patch['part'] not in owned]+live
        return frame
    def _send(self,frame):
        self.last=time.perf_counter();self.inflight=True;generation=self.generation
        source='(()=>{try{window.yumiVRM.desktopFrame('+json.dumps(frame,separators=(',',':'),allow_nan=False)+');return JSON.stringify({status:window.yumiVRM.status,image:window.yumiVRM.capture()});}catch(e){return JSON.stringify({status:{error:String(e)},image:""});}})()'
        def done(value):
            if self.disposed or generation!=self.generation:return
            self.inflight=False
            try:
                result=json.loads(value);status=result['status']
                if status.get('error'):raise ValueError('renderer error')
                if not self.paused and self.host.isVisible():
                    data=result.get('image','').partition(',')[2]
                    image=QImage.fromData(base64.b64decode(data))
                    if image.isNull():raise ValueError('empty frame')
                    image.setDevicePixelRatio(frame['dpr']);self.display.setPixmap(QPixmap.fromImage(image));self.delivered=True
                    self._present()
            except (ValueError,TypeError,KeyError):self._failed('Son poz görüntüsü okunamadı.');return
            pending,self.pending=self.pending,None
            if pending is not None and pending[1]==self.generation and not self.disposed and not self.paused and self.ready:
                self._send(pending[0])
        self.view.page.runJavaScript(source,done)
    def pause(self,paused):
        self.paused=bool(paused)
        if self.disposed:return
        if paused:
            self.generation+=1;self.inflight=False;self.delivered=False;self.pending=None;self.display.hide()
        # Final poses are rendered by desktopFrame, including after resume.
        # The preview RAF must stay paused to avoid a duplicate render loop.
        self.view.page.runJavaScript('window.yumiVRM?.pause(true)')
    def dispose(self):
        if self.disposed:return
        self.disposed=True;self.generation+=1;self.ready=False
        self.view.dispose();self.display.hide()
