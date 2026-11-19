"""C05 modelsiz çalışma: "Modeli gizle" (model_visible=False) = modelsiz kip.

Gizliyken VRM yüklenmez/bırakılır, modele bağlı davranışlar kapanır; ses, adla
çağırma, beceriler ve sohbet aynen sürer. Karakter kimliği (ad, ses, kişilik)
seçili modelden gelmeye devam eder; yalnız görüntü ve model işleri kapanır.
"""
import os,time
from PySide6.QtCore import Qt
from avatar import AvatarView

MESAJ='Modelsiz çalışıyorum; bu komut model açıkken kullanılır. "Görün" dersen modeli geri getiririm.'

MODEL_YOK_YAZISI='Kurulu model yok'
SES_YOK_YAZISI='Konuşma sesi kurulu değil (varsayılan Yumi sesi bulunamadı) · cevap yazılı gösterildi; Ayarlar’dan bir ses seçebilirsin.'

def acik(owner):
    """Modelsiz kip açık mı (= model gizli ya da hiç kurulu model yok)."""
    return getattr(owner,'_kurulu_model_yok',False) or not bool(getattr(owner,'settings',{}).get('model_visible',True))

def model_yok(owner):
    return bool(getattr(owner,'_kurulu_model_yok',False))

def model_yok_guncelle(owner):
    """Kurulu karakter olup olmadığını yeniden ölçer (açılış, model seçimi/kurulumu). Değişti mi döner."""
    from skins import kurulu_model_var
    try:yok=not kurulu_model_var()
    except Exception:yok=False
    eski=getattr(owner,'_kurulu_model_yok',None);owner._kurulu_model_yok=yok
    return eski is not None and eski!=yok

def ses_kurulu(owner,voice):
    """Hiç model yokken seçili XTTS sesinin dosyaları var mı? Model varken hep True (eski davranış aynen)."""
    if not model_yok(owner) or not str(voice).startswith('xtts:'):return True
    from xtts_speech import voices
    return voice in {key for _,key,_ in voices()}

class ModelsizAvatar(AvatarView):
    """AvatarView: modelsiz kipte skin ataması modeli yüklemez, yalnız anahtarı saklar."""
    def __init__(self,parent=None,transparent=False,kapali=lambda:False):
        # Modelsiz açılışta three-vrm köprüsünü (WebEngine) hiç kurma; gösterilince kurulur.
        atla=transparent and kapali() and os.environ.get('YUMI_DESKTOP_RENDERER','three-vrm')!='legacy'
        onceki=os.environ.get('YUMI_DESKTOP_RENDERER')
        if atla:os.environ['YUMI_DESKTOP_RENDERER']='legacy'
        try:super().__init__(parent,transparent)
        finally:
            if atla:
                if onceki is None:os.environ.pop('YUMI_DESKTOP_RENDERER',None)
                else:os.environ['YUMI_DESKTOP_RENDERER']=onceki
        if atla:self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop,False)
        self._kapali=kapali;self._bekleyen_skin=None;self.yukleme_sayisi=0;self.son_yukleme_suresi=None

    @property
    def skin(self):
        return self._skin if self._skin is not None else self._bekleyen_skin

    @skin.setter
    def skin(self,key):
        if self._kapali():
            from skins import valid_skin,default_skin
            self._bekleyen_skin=key if valid_skin(key) else default_skin();return
        once=self._skin;basla=time.perf_counter()
        AvatarView.skin.fset(self,key)
        if self._skin!=once:
            self.yukleme_sayisi+=1;self.son_yukleme_suresi=time.perf_counter()-basla
        self._bekleyen_skin=None

    def modeli_birak(self):
        """Model, eşya ve three-vrm köprüsünü bırakır; anahtar geri yükleme için saklanır."""
        if self._skin is not None:self._bekleyen_skin=self._skin
        if self.model is not None and self.isValid():
            self.makeCurrent()
            try:
                if self.furniture:self.furniture.release()
                self.model.release()
            finally:self.doneCurrent()
        self.furniture=None;self.model=None;self.clippy=None;self._skin=None
        self.model_error=None;self.hand_gesture=None;self.prop='none';self.pose='idle'
        bridge=self.three_desktop
        if bridge is not None:
            bridge.dispose()
            for widget in (bridge.view,bridge.display):widget.hide();widget.deleteLater()
            self.three_desktop=None

    def modeli_yukle(self):
        """Saklanan anahtarla modeli (ve gerekiyorsa three-vrm köprüsünü) yeniden kurar."""
        if self.transparent and self.three_desktop is None and os.environ.get('YUMI_DESKTOP_RENDERER','three-vrm')!='legacy':
            from desktop_vrm import DesktopVRM
            self.three_desktop=DesktopVRM(self)
        if self._skin is None and self._bekleyen_skin is not None:
            self.skin=self._bekleyen_skin

def _gorunumler(owner):
    views=[getattr(owner,'avatar',None),getattr(getattr(owner,'overlay',None),'avatar',None)]
    return [v for v in views if isinstance(v,ModelsizAvatar)]

def gecis(owner):
    """model_visibility.apply içinden: gizliyken modeli bırak ve model işlerini durdur; görünürken yükle."""
    if acik(owner):
        if getattr(owner,'_modelsiz_durum',None) is True:return
        owner._modelsiz_durum=True
        modeli_isleri_durdur(owner)
        for view in _gorunumler(owner):view.modeli_birak()
        for name in ('roam_tick',):
            timer=getattr(owner,name,None)
            if timer is not None:timer.stop()
        overlay=getattr(owner,'overlay',None)
        if overlay is not None:
            for timer in (overlay.mask_timer,overlay.hit_timer):timer.stop()
    else:
        if getattr(owner,'_modelsiz_durum',None) is False:return
        owner._modelsiz_durum=False
        hatalar=[]
        for view in _gorunumler(owner):
            try:view.modeli_yukle()
            except Exception as error:hatalar.append(str(error))
        timer=getattr(owner,'roam_tick',None)
        if timer is not None and not timer.isActive():timer.start(16)
        overlay=getattr(owner,'overlay',None)
        if overlay is not None:
            if not overlay.mask_timer.isActive():overlay.mask_timer.start(50)
            if not overlay.hit_timer.isActive():overlay.hit_timer.start(16)
            overlay.sync()
        if hatalar and hasattr(owner,'show_error'):owner.show_error('Model yüklenemedi: '+hatalar[0])

def modeli_isleri_durdur(owner):
    """Dans, senaryo, yürüme, jest ve bekleyen tepkiyi kapatır (ses ve sohbete dokunmaz)."""
    runtime=getattr(owner,'music_runtime',None)
    if runtime is not None:
        try:runtime.stop(suppress=False)
        except Exception:pass
    director=getattr(owner,'daily_director',None)
    if director is not None:
        director.manual=None;director.current=None;director.scene=None;director.candidate=None
    anim=getattr(owner,'move_animation',None)
    if anim is not None:anim.stop()
    loco=getattr(owner,'locomotion',None)
    if loco is not None:
        try:loco.reset()
        except Exception:pass
    owner.pending_avatar_command=None;owner.pending_motion_path=None;owner.voice_target=None
    owner.manual_pose=None;owner.gesture_until=0.;owner._bekleyen_tepki=None
    if hasattr(owner,'voice_x'):del owner.voice_x

def _model_komutlari():
    from daily_scenarios import SCENARIOS
    from action_transition import ACTIONS,STOP
    komutlar=set(SCENARIOS)|set(ACTIONS)|set(STOP)
    komutlar|={'direk dansı yap','pole dance yap','ritme göre dans et','ritimle dans et','müzikle dans et',
               'büyü','küçül','biraz büyü','biraz küçül','uyu','yatağa git','yat uyu','oyun oyna'}
    # Kimlik/ayar komutları modelsiz da çalışır (ad, ses ve ayar değişir; model yüklenmez).
    komutlar-={'karakteri değiştir','sonraki karakter','el salla','merhaba de'}
    return komutlar

def komut_cevabi(owner,command):
    """Modelsizken modele dönük komuta kısa cevap; değilse None (komut normal yoldan gider)."""
    if not acik(owner):return None
    if model_yok(owner) and command in ('görün','geri gel'):return MODEL_YOK_YAZISI+'; önce Ayarlar’dan bir model kur.'
    if command in ('el salla','merhaba de'):return 'Merhaba!'
    if command in ('dur','yürümeyi durdur','hareketi durdur'):return 'Tamam.'
    gestures={'ok işareti yap','okey işareti yap','başparmağını kaldır','başparmakla onayla','elini beline koy','avuçlarını aç','işaret et','omuz silk'}
    if command in _model_komutlari() or command in gestures:return MESAJ
    return None
