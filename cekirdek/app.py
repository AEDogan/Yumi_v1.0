"""Yumi: Windows-native 3D desktop companion and voice assistant."""
from __future__ import annotations

import json
import math
import os
import queue
import random
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, QEvent, QPropertyAnimation, QPoint, QEasingCurve, QCoreApplication, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QAudioBufferOutput, QAudioFormat
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QScrollArea, QSystemTrayIcon,
    QVBoxLayout, QWidget, QSlider, QFileDialog, QSizePolicy, QLayout, QTabWidget, QGroupBox, QStackedWidget, QListWidget, QListWidgetItem, QMessageBox)

if QCoreApplication.instance() is None:QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from api import answer, speech, transcribe
from avatar import AvatarView
from overlay import DesktopCharacter
from system_audio import SystemAudio
from voice_profiles import profile,apply_profile,VOICES,OPENAI_VOICES,character_name,wake_command,ad_artigini_ayikla
from skins import available as available_skins, add_model, remove_model, skin_path, default_skin, valid_skin, is_builtin, SPRITE
from backend import Assistant, local_transcribe, local_speech, login, login_status, OFFLINE_MESSAGE, is_offline_error, offline_warning_speech, prepare_offline_warning
from platform_win import ActivityCounter, GlobalHotkey, protect, unprotect

from app_paths import ROOT,APP_ID,data_dir,env_value,migrated_default_name
from durable_json import atomic_json_write,load_json
from modelsiz import acik as modelsiz_acik  # C05: model gizli = modelsiz çalışma
DATA_DIR = data_dir()
import tur_kaydi;tur_kaydi.baslat(DATA_DIR)  # B10: data/konusma_kaydi/*.jsonl
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except PermissionError:
    raise RuntimeError(f'Yumi kullanıcı verisi açılamadı ({DATA_DIR}). Başka klasöre yazıp profilinizi bölmemek için başlatma durduruldu.') from None
os.environ['YUMI_DATA_DIR']=str(DATA_DIR)
SETTINGS_FILE = DATA_DIR / 'settings.json'
KEY_FILE = DATA_DIR / 'key.dat'
GEMINI_KEY_FILE = DATA_DIR / 'gemini-key.dat'
from dagitim import SISTEM_SESI  # G-A2: modelsiz kurulumda varsayılan Yumi sesi; karakter adı/sesi yazılmaz
DEFAULTS = {'theme':'ios','panel_opacity':94,'speech_voice':SISTEM_SESI,'skin':default_skin(),'voice':'coral','always_listen':False,'name_wake_enabled':False,'roam':True,'mic_device':'Otomatik','model':'gpt-5.4-mini','provider':'gemini-web','city':'','size':100,'sesli_cevap':'her_zaman','modelsiz_ses':'yerel','api_ses':'','api_ses_kilitli':False}  # SC1/SC2 (19 Kas): ses_cikisi.py


DEFAULTS.update(daily_scenarios=True,music_family='unknown',music_auto=True)

_speech_log=None
def speech_event(text):
    """B07 canlı gecikme kaydı: data/logs/ses-akis.log (soru → ilk metin → bölüm → ilk ses)."""
    global _speech_log
    import logging
    if _speech_log is None:
        _speech_log=logging.getLogger('yumi.ses_akis');_speech_log.setLevel(logging.INFO);_speech_log.propagate=False
        try:
            path=DATA_DIR/'logs'/'ses-akis.log';path.parent.mkdir(parents=True,exist_ok=True)  # 12 Kasım: work/ yerine data/logs (Yumi work/'süz çalışır)
            handler=logging.FileHandler(path,encoding='utf-8');handler.setFormatter(logging.Formatter('%(asctime)s.%(msecs)03d %(message)s','%H:%M:%S'))
            _speech_log.addHandler(handler)
        except OSError:pass
    _speech_log.info(text)
    try:
        import tur_kaydi;tur_kaydi.olay('akis',metin=str(text))
    except Exception:pass

def warm_speech(voice,data_dir):
    """B07: seçili karakter sesini açılışta arka planda hazırla (model yükleme + ilk GPU çağrısı)."""
    import logging
    try:
        if voice.startswith('xtts:'):
            from xtts_speech import warm
            warm(voice,data_dir);result='xtts'
        else:return
        speech_event(f'isitma tamam {voice} {result}')
    except Exception as error:
        speech_event(f'isitma HATA {voice} {error}')
        logging.getLogger('yumi.speech').warning('Ses ısıtma başarısız: %s (%s)',voice,error)

def load_settings():
    try:
        saved=load_json(SETTINGS_FILE,{},lambda value:isinstance(value,dict));settings={**DEFAULTS, **saved}
        settings_changed=False
        if settings.get('provider') not in ('gemini-web','chatgpt-web'):
            settings['provider']='gemini-web';settings_changed=True
        if settings.pop('gemini_model',None) is not None:settings_changed=True
        settings['name_wake_enabled']=bool(saved.get('name_wake_enabled',saved.get('always_listen',False)))
        if not valid_skin(settings.get('skin')):apply_profile(settings,default_skin())
        # ADLANDIRMA (13 Kasım): ses anahtarları model adıyla (xtts:meowko:kawaii → xtts:akira, xtts:anime:elaina:ince_ayar →
        # xtts:yumi). Eski anahtarlar da çalışır; göç öncesi ayarlar bir kez data/settings.adlandirma-oncesi.json'a yedeklenir.
        from xtts_speech import kanonik
        eski_sesler=[settings.get('speech_voice')]+[p.get('speech_voice') for p in settings.get('voice_profiles',{}).values() if isinstance(p,dict)]
        if any(v and kanonik(v)!=v for v in eski_sesler):
            yedek=SETTINGS_FILE.with_name('settings.adlandirma-oncesi.json')
            if not yedek.exists():
                try:atomic_json_write(yedek,saved)
                except OSError:pass
            settings['speech_voice']=kanonik(settings.get('speech_voice'))
            for p in settings.get('voice_profiles',{}).values():
                if isinstance(p,dict) and p.get('speech_voice'):p['speech_voice']=kanonik(p['speech_voice'])
            settings_changed=True
        # G-A2 (18 Kas): Edge TTS kaldırıldı — kayıtlı 'edge:' sesleri karakterin kendi sesine / varsayılan Yumi sesine göçer.
        from voice_profiles import varsayilan_ses
        if str(settings.get('speech_voice') or '').startswith('edge:'):
            settings['speech_voice']=varsayilan_ses(settings.get('skin'));settings_changed=True
        for anahtar,p in settings.get('voice_profiles',{}).items():
            if isinstance(p,dict) and str(p.get('speech_voice') or '').startswith('edge:'):
                p['speech_voice']=varsayilan_ses(anahtar);settings_changed=True
        native_voices={key for _,key,_ in VOICES}
        # A voice whose model is temporarily missing must not erase the saved choice;
        # only the active voice falls back (to the approved egirl) for this run.
        if settings.get('speech_voice') not in native_voices:
            from voice_profiles import varsayilan_ses
            settings['speech_voice']=varsayilan_ses(settings.get('skin'))  # G-A2: karakterin kendi sesi, yoksa varsayılan Yumi sesi (Edge kaldırıldı)
        for saved in settings.get('voice_profiles',{}).values():
            if isinstance(saved,dict) and str(saved.get('name') or '').strip():saved['name']=migrated_default_name(saved['name'])
        # Apply the user's approved voice once; later manual choices remain saved.
        if not settings.get('egirl_approved_v2') and 'rvc:egirl' in native_voices:
            settings['speech_voice']='rvc:egirl'
            current=profile(settings)
            current.update(speech_voice='rvc:egirl',gender='female')
            settings.setdefault('voice_profiles',{})[settings['skin']]=current
            settings['egirl_approved_v2']=True;settings_changed=True
        settings['speech_voice']=profile(settings)['speech_voice']
        settings['always_listen']=False
        from character_names import migrate
        if migrate(settings):settings_changed=True
        if settings_changed:save_settings(settings)
        return settings
    except (OSError, ValueError):
        return DEFAULTS.copy()


def save_settings(settings):
    atomic_json_write(SETTINGS_FILE,settings)


def load_key():
    try:
        return unprotect(KEY_FILE.read_bytes()).decode('utf-8')
    except (OSError, UnicodeError):
        return os.getenv('OPENAI_API_KEY','')


def load_gemini_key():
    try:return unprotect(GEMINI_KEY_FILE.read_bytes()).decode('utf-8')
    except (OSError,UnicodeError):return os.getenv('GEMINI_API_KEY','')


class Signals(QObject):
    hotkey = Signal()


SOZ_SONU_S=2.2  # 18 Kas (kullanıcı): kısa duraksamada kesmesin, söz bitince 1 sn daha bekle (1,2→2,2). B10: konuşma bitti saymak için sessizlik
TAKIP_DINLEME_S=2.0  # 18 Kas (kullanıcı): Yumi soru sorunca / "anlayamadım" deyince adsız dinleme penceresi; bu sürede ses başlamazsa susar
class MikrofonIzniYok(RuntimeError):
    """F1b: Windows mikrofon gizlilik izni kapalı (ses/mikrofon_izni.py)."""

class VoiceCapture:
    """Local VAD turns microphone sound into bounded WAV snippets."""
    def __init__(self, completed, status, device_name='Otomatik', on_manual=None, on_partial=None, on_live=None):
        self.completed = completed
        self.on_partial = on_partial  # B06: söz sürerken erken ad denetimi (adla çağırmada anında bip)
        self.on_live = on_live;self.next_live=.6  # ARAYUZ 13 Kasım: Yumi'ye konuşulurken duyulan yazı (canlı yazı)
        self.wake_hit=False;self.son_wake_hit=False;self.next_partial=.7
        self.status = status
        self.on_manual = on_manual
        self.blocks = queue.Queue(maxsize=100)
        self.stream = None
        self.always = False
        self.manual = False
        self.recording = []
        self.started = 0.0
        self.last_loud = 0.0
        self._suspended = False;self.resume_after=0.;self.voiced_seconds=0.
        self.device_name = device_name
        self.wake_name='Yumi'
        self.noise_floor=.008;self.had_speech=False;self.pre_roll=deque(maxlen=3);self.wake_armed_until=0.;self.level=0.
        self.sample_rate = 16000
        self.timer = QTimer()
        self.timer.timeout.connect(self._pump)
        self.timer.start(100)

    @property
    def suspended(self):return self._suspended

    @suspended.setter
    def suspended(self,value):
        value=bool(value)
        if value==self._suspended:return
        self._suspended=value
        self.recording=[];self.had_speech=False;self.pre_roll.clear();self.voiced_seconds=0.
        self.wake_armed_until=0.;self.wake_hit=False
        while not self.blocks.empty():
            try:self.blocks.get_nowait()
            except queue.Empty:break
        # Discard device buffers and the tail of our own speaker output.
        self.resume_after=time.perf_counter()+(.35 if not value else 0.)

    def _callback(self, data, frames, timing, flags):
        if self.suspended or time.perf_counter()<self.resume_after:return
        try:
            self.blocks.put_nowait((data[:,0].copy(),time.perf_counter()))
        except queue.Full:
            pass

    def ensure_stream(self):
        if self.stream is None:
            import mikrofon_izni  # F1b: izin kapalıyken akış açılır ama hep sessizlik gelir → önce açıkça söyle
            engel=mikrofon_izni.kapali()
            if engel:raise MikrofonIzniYok(engel)
            self._sifir_s=0.;self._sessiz_bildirildi=False
            devices=sd.query_devices()
            choices=[i for i,d in enumerate(devices) if d['max_input_channels']>0]
            if self.device_name!='Otomatik':
                choices.sort(key=lambda i:0 if devices[i]['name']==self.device_name else 1)
            else:
                default=sd.default.device[0]
                choices.sort(key=lambda i:0 if i==default else 1)
            errors=[]
            for index in choices:
                rates=list(dict.fromkeys([16000,int(devices[index]['default_samplerate'])]))
                for rate in rates:
                    try:
                        stream=sd.InputStream(device=index,samplerate=rate,channels=1,dtype='float32',
                                              blocksize=int(rate/10),callback=self._callback)
                        stream.start()
                        self.stream=stream
                        self.sample_rate=rate
                        return
                    except Exception as error:
                        errors.append(str(error))
            raise RuntimeError('Kullanılabilir mikrofon açılamadı. Windows ses giriş aygıtını ve mikrofon izinlerini kontrol edin.')

    def set_always(self, enabled):
        self.always = enabled
        if enabled:
            self.ensure_stream()
            self.status(f'“{self.wake_name}” diye seslen')
        elif not self.manual:
            self._stop_stream()
            self.status('Hazır')

    def toggle_manual(self):
        if self.manual:
            self.manual = False
            self._finish(requires_wake=False)
            if not self.always: self._stop_stream()
        else:
            self.ensure_stream()
            self.manual = True
            self.recording = [];self.had_speech=False;self.pre_roll.clear();self.voiced_seconds=0.
            self.started = time.perf_counter()
            self.last_loud = self.started
            self.status('Dinliyorum…')

    def _stop_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        while not self.blocks.empty():
            try: self.blocks.get_nowait()
            except queue.Empty: break

    def _finish(self, requires_wake=True):
        if not self.recording: return
        samples = np.concatenate(self.recording)
        self.recording = []
        voiced=self.voiced_seconds;self.voiced_seconds=0.
        if len(samples) >= self.sample_rate//2 and voiced>=.25:
            if self.sample_rate!=16000:
                length=max(1,round(len(samples)*16000/self.sample_rate))
                samples=np.interp(np.linspace(0,len(samples)-1,length),np.arange(len(samples)),samples).astype('float32')
            self.completed(samples, requires_wake)

    def arm_next_utterance(self,sure=10.):
        self.suspended=False;self.wake_armed_until=max(time.perf_counter(),self.resume_after)+sure;self.armed_soz=False;self.recording=[];self.had_speech=False;self.voiced_seconds=0.;self.status('Dinliyorum, söyle…')
    def _pump(self):
        while True:
            try:item=self.blocks.get_nowait()
            except queue.Empty:break
            block,now=item if isinstance(item,tuple) else (item,time.perf_counter())
            if self.suspended or now<self.resume_after:continue
            # F1b: izin reddinde Windows tam sıfır örnek verir (gerçek mikrofonda gürültü hiç sıfır olmaz) → 4 s sonra bir kez uyar
            if not np.any(block):
                self._sifir_s=getattr(self,'_sifir_s',0.)+len(block)/self.sample_rate
                if self._sifir_s>=4. and not getattr(self,'_sessiz_bildirildi',False):
                    self._sessiz_bildirildi=True
                    if getattr(self,'on_sessiz',None):self.on_sessiz()
            else:self._sifir_s=0.
            level=float(np.sqrt(np.mean(np.square(block))))
            self.level=level  # ARAYUZ: kayıttaki ses çubukları bunu okur
            if not self.manual and not self.always:continue
            start_threshold=max(.012,min(.035,self.noise_floor*3.))
            continue_threshold=max(.008,min(.025,self.noise_floor*1.8))
            loud=level>(continue_threshold if self.had_speech else start_threshold)
            if not self.had_speech and not loud:self.noise_floor=.98*self.noise_floor+.02*min(level,.015)
            if loud:
                self.voiced_seconds+=len(block)/self.sample_rate
                self.last_loud=now
                if not self.had_speech:
                    self.started=now;self.recording=list(self.pre_roll);self.had_speech=True;self.wake_hit=False;self.next_partial=.7;self.next_live=.6
                    self.armed_soz=now<self.wake_armed_until  # 18 Kas: pencere içinde başlayan söz, pencere dolsa da adsız kabul edilir
                    if self.manual or now<self.wake_armed_until:self.status('Seni dinliyorum…')
            if self.had_speech:
                self.recording.append(block)
                bekleme=not self.manual and now>=self.wake_armed_until and not getattr(self,'armed_soz',False)  # ad bekleniyor
                if bekleme and self.always and not self.wake_hit and self.on_partial and now-self.started>=self.next_partial and self.next_partial<=4.:
                    # B06: sözün bitmesini beklemeden ilk saniyelerde ad aranır; bulunursa owner bip çalar ve wake_hit=True yapar.
                    self.next_partial+=.8
                    try:self.on_partial(np.concatenate(self.recording))
                    except Exception:pass
                # ARAYUZ (13 Kasım): Yumi'ye konuşulurken (elle kayıt, "dinliyorum" süresi ya da ad duyulduktan sonra) ~0,8 s'de bir
                # son 12 s'nin ara tanıması → canlı yazı. Ortam konuşması (ad beklenirken) yazılmaz.
                if self.on_live and (self.manual or now<self.wake_armed_until or getattr(self,'armed_soz',False) or self.wake_hit) and now-self.started>=self.next_live:
                    self.next_live=now-self.started+.8
                    try:self.on_live(np.concatenate(self.recording)[-12*self.sample_rate:])
                    except Exception:pass
                uzun=bekleme and not self.wake_hit and now-self.started>=6  # ad duyulmadan 6 sn: ortam sesi/konuşma, kes
                if now-self.last_loud>=SOZ_SONU_S or now-self.started>=60 or uzun:
                    self.son_ses_t=self.last_loud;self.soz_baslangic_t=self.started
                    manual=self.manual;armed=time.perf_counter()<self.wake_armed_until or getattr(self,'armed_soz',False);self.armed_soz=False;self.manual=False;self.had_speech=False;self.pre_roll.clear();self.wake_armed_until=0.
                    self.son_wake_hit=self.wake_hit;self.son_armed=armed;self.wake_hit=False
                    self._finish(requires_wake=not(manual or armed))
                    if manual and not self.always:self._stop_stream()
                    if manual and self.on_manual:self.on_manual(False)
            else:
                self.pre_roll.append(block)
                if self.manual and now-self.started>=8:
                    self.manual=False;self.recording=[];self.status('Ses algılanmadı; tekrar deneyebilirsin.')
                    if not self.always:self._stop_stream()
                    if self.on_manual:self.on_manual(False)
        if self.manual and not self.had_speech and time.perf_counter()-self.started>=8:
            self.manual=False;self.recording=[];self.status('Ses algılanmadı; tekrar deneyebilirsin.')
            if not self.always:self._stop_stream()
            if self.on_manual:self.on_manual(False)
        if self.wake_armed_until and time.perf_counter()>self.wake_armed_until and not self.had_speech:
            self.wake_armed_until=0.;self.status(f'“{self.wake_name}” diye seslen')

    def close(self):
        self.timer.stop()
        self._stop_stream()


class SettingsDialog(QDialog):
    def __init__(self,parent):
        from voice_profiles import refresh_voices
        refresh_voices()
        super().__init__(parent);self.owner=parent;self.setWindowTitle('Yumi · Ayarlar');self.setWindowFlags(Qt.WindowType.Widget);self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint,False)
        from ui_shell import SectionTabs,ThemePicker
        outer=QVBoxLayout(self);outer.setContentsMargins(20,18,20,18);outer.setSpacing(18);title=QHBoxLayout();title.addWidget(QLabel('Ayarlar'));title.addStretch();back=QPushButton('Sohbete dön');back.clicked.connect(self.reject);title.addWidget(back);outer.addLayout(title);self.setObjectName('settingsPage');self.tabs=SectionTabs();outer.addWidget(self.tabs,1)
        def tab(title):
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.viewport().setAutoFillBackground(False)
            content=QWidget();content.setObjectName('settingsContent');scroll.setWidget(content);layout=QVBoxLayout(content);layout.setSpacing(12);layout.setAlignment(Qt.AlignmentFlag.AlignTop);self.tabs.addTab(scroll,title);return layout
        title.itemAt(0).widget().setObjectName('heading')
        # 12 Kasım arayüz (kullanıcı): bölümler Model · AI Web · Görünüm. Ses ve Davranış sekmeleri kalktı
        # (sesler modele bağlı); eski ses/anahtar alanları mantık bozulmasın diye gizli tutucuda yaşar.
        # 13 Kasım 02:10 (kullanıcı): "Arka plan doluluğu" işlevsiz → Görünüm sekmesi kalktı; kaydırıcı gizli tutucuda (kayıtlı değer korunur)
        character=tab('Model');ses_sekme=tab('Ses');assistant=tab('AI Web');themes=tab('Temalar');behavior=character  # SC1/SC2 (19 Kas): Ses ayrı bölüm
        self._gizli=QWidget(self);self._gizli.hide();sound=QVBoxLayout(self._gizli);appearance=sound
        self.theme=QComboBox()
        from themes import THEMES
        for title,key in THEMES:self.theme.addItem(title,key)
        import tema as _tema
        self.theme.setCurrentIndex(max(0,self.theme.findData(_tema.anahtar(parent.settings.get('theme','inci')))));self.theme.hide();self.theme_picker=ThemePicker(self.theme);themes.addWidget(self.theme_picker)
        self.opacity_label=QLabel();appearance.addWidget(self.opacity_label);self.opacity=QSlider(Qt.Orientation.Horizontal);self.opacity.setRange(45,100);self.opacity.setValue(parent.settings.get('panel_opacity',94));appearance.addWidget(self.opacity)
        self.opacity.valueChanged.connect(lambda value:self.opacity_label.setText(f'Arka plan doluluğu · %{value}'));self.opacity_label.setText(f'Arka plan doluluğu · %{self.opacity.value()}')
        self.theme.currentIndexChanged.connect(self.preview_theme)
        self.opacity.valueChanged.connect(self.preview_theme)
        hint=QLabel('Saydamlık yalnızca pencere arka planını etkiler; yazılar okunaklı kalır. Karakter masaüstünde görünür.');hint.setWordWrap(True);appearance.addWidget(hint)
        assistant.addWidget(QLabel('Sohbet sitesi'))
        self.provider=QComboBox()
        self.provider.addItem('Gemini','gemini-web')
        self.provider.addItem('ChatGPT','chatgpt-web')
        self.provider.setCurrentIndex(max(0,self.provider.findData(parent.settings.get('provider','gemini-web'))))
        assistant.addWidget(self.provider)
        account_note=QLabel('Yumi cevapları seçtiğin sitedeki kendi hesabından alır. Her hesaba bir kez giriş yapman yeter.')
        account_note.setWordWrap(True);assistant.addWidget(account_note)
        self.account_buttons={}
        self.browser_login=QPushButton('Giriş yap')
        self.browser_login.setObjectName('accountButton')
        self.browser_login.clicked.connect(lambda:self.login_account(self.provider.currentData()))
        assistant.addWidget(self.browser_login)
        self.account_buttons['gemini-web']=self.browser_login
        self.browser_hide=QPushButton('Giriş tamamlandı')
        self.browser_hide.clicked.connect(lambda:parent._browser_login(self.provider.currentData(),True))
        assistant.addWidget(self.browser_hide)
        self.browser_status=QLabel('Yumi açılışta seçili hesaba görünmeden bağlanır. Giriş gerekirse “Giriş yap” ile pencereyi aç, bitince “Giriş tamamlandı”ya bas.')
        self.browser_status.setWordWrap(True);assistant.addWidget(self.browser_status)
        parent.browser_status_changed.connect(self.show_browser_status)
        self.openai_group=QGroupBox();self.openai_group.hide()
        self.openai_connection=QComboBox();self.openai_connection.hide()
        self.signin=QPushButton();self.signin.hide()
        self.openai_api_group=QGroupBox();self.openai_api_group.hide()
        self.key=QLineEdit();self.key.hide()
        self.key_status=QLabel();self.key_status.hide()
        self.openai_model=QLineEdit(parent.settings.get('model','gpt-5.4-mini'));self.openai_model.hide()
        self.city=QLineEdit(parent.settings.get('city',''));sound.addWidget(self.city)  # AI Web'de yalnız site bağlantıları; şehir değeri korunur, Yumi gerekirse sorar
        sound.addWidget(QLabel('Bu karakter için tercih edilen ses tonu'))
        self.voice_gender=QComboBox()
        for title,key in [('Kadın','female'),('Erkek','male'),('Serbest seçim','any')]:self.voice_gender.addItem(title,key)
        current_profile=profile(parent.settings);self.voice_gender.setCurrentIndex(max(0,self.voice_gender.findData(current_profile['gender'])));sound.addWidget(self.voice_gender)
        sound.addWidget(QLabel('Ses motoru / konuşma modeli'));self.speech_voice=QComboBox();sound.addWidget(self.speech_voice)
        self.fill_voices(current_profile['speech_voice']);self.voice_gender.currentIndexChanged.connect(lambda _:self.fill_voices())
        self.voice=QComboBox();self.voice.addItems(OPENAI_VOICES);self.voice.setCurrentText(current_profile['voice']);sound.addWidget(self.voice)
        self.voice.setVisible(self.speech_voice.currentData()=='openai-tts');self.speech_voice.currentIndexChanged.connect(lambda _:self.voice.setVisible(self.speech_voice.currentData()=='openai-tts'))
        preview=QPushButton('Seçili sesi dene');preview.clicked.connect(self.preview_voice);sound.addWidget(preview)
        self.preview_status=QLabel();self.preview_status.setWordWrap(True);sound.addWidget(self.preview_status)
        from voice_preview import VoicePreview
        self.voice_preview=VoicePreview(self,parent,preview,self.preview_status)
        self.speech_voice.currentIndexChanged.connect(lambda *_:self.voice_preview.cancel())
        self.voice.currentTextChanged.connect(lambda *_:self.voice_preview.cancel())
        self.gemini_group=QGroupBox('Gemini Live ses bağlantısı');sound.addWidget(self.gemini_group);ga=QVBoxLayout(self.gemini_group)
        ga.addWidget(QLabel('API anahtarı yalnızca canlı ses ve ses önizlemesi içindir. Yazılı sohbet ücretsiz hesap bağlantısıyla çalışır.'))
        self.gemini_key=QLineEdit();self.gemini_key.setEchoMode(QLineEdit.EchoMode.Password);self.gemini_key.setPlaceholderText('Kayıtlı · değiştirmek için yeni anahtar gir' if parent.gemini_key else 'Google AI Studio anahtarı · yalnız ses için');ga.addWidget(self.gemini_key)
        save=QPushButton('Ses anahtarını kaydet');save.clicked.connect(self.save_gemini_key);ga.addWidget(save)
        self.gemini_status=QLabel('Ses anahtarı hazır.' if parent.gemini_key else 'Gemini Live sesli sohbeti ve önizleme için API anahtarı gerekli. Gemini hesabına giriş bu bağlantıyı açmaz.');self.gemini_status.setWordWrap(True);ga.addWidget(self.gemini_status)
        delete=QPushButton('Kaydedilmiş ses anahtarını sil');delete.clicked.connect(self.delete_gemini_key);ga.addWidget(delete)
        note=QLabel('Yalnız sağlayıcının native canlı sesleri kullanılıyor. Gemini bağlantısı hazır bekler; mikrofon düğmesi sesli sohbeti açar/kapatır. Beklemede ortam sesi gönderilmez. OpenAI canlı sesi için API erişimi gerekli; kayıtlı anahtar yok ve denenmedi.');note.setWordWrap(True);sound.addWidget(note)
        self.mic_label=QLabel('Mikrofon');self.mic_device=QComboBox();self.mic_device.addItem('Varsayılan mikrofon','Otomatik')
        self.mic_device.setMinimumHeight(42);self.mic_device.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.mic_device.setToolTip('Mikrofon seçmek için aç')
        try:
            from audio_devices import input_devices
            for index,name in input_devices(sd):
                self.mic_device.addItem(name,name)
                self.mic_device.setItemData(self.mic_device.count()-1,name,Qt.ItemDataRole.ToolTipRole)
        except Exception:pass
        self.mic_device.setCurrentIndex(max(0,self.mic_device.findData(parent.settings['mic_device'])))
        self.always=QCheckBox('Model adıyla sesli sohbet başlat');self.always.setToolTip('Yalnız etkin karakterin çağrı adı yerelde algılanır. Beklerken ortam sesi Gemini’ye gönderilmez. Adı söyleyip Dinliyor durumunu bekle.');self.always.setChecked(parent.settings.get('name_wake_enabled',False))
        self.character_drafts={};self.editing_skin=parent.settings['skin']
        # ARAYUZ: Model bölümü kartlar halinde (tasarım tuvali "Ayarlar · Model")
        def kart():
            f=QFrame();f.setObjectName('card');f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);l=QVBoxLayout(f);l.setContentsMargins(14,12,14,12);l.setSpacing(8);character.addWidget(f);return l
        kart1,kart2,kart3=kart(),kart(),kart()
        def ses_kart(baslik_metni):  # SC1/SC2 (19 Kas, kullanıcı): ses ayarları ayrı "Ses" bölümünde
            f=QFrame();f.setObjectName('card');f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);l=QVBoxLayout(f);l.setContentsMargins(14,12,14,12);l.setSpacing(8);ses_sekme.addWidget(f)
            b=QLabel(baslik_metni);b.setObjectName('caption');l.addWidget(b);return l
        skart1,skart2,skart3,skart4=ses_kart('Sesli cevap'),ses_kart('Konuşma'),ses_kart('Mikrofon'),ses_kart('Modelsiz çalışmada ses')
        baslik=QLabel('Model');baslik.setObjectName('caption');kart1.addWidget(baslik);self.skin=QComboBox();kart1.addWidget(self.skin);self.fill_skins(parent.settings['skin'])
        row=QHBoxLayout()
        inspect=QPushButton('Önizle');self.inspect_skin_button=inspect;inspect.setObjectName('inspectButton');inspect.setToolTip('Modeli ayrı pencerede 3B önizle');inspect.clicked.connect(self.inspect_skin);row.addWidget(inspect)
        remove=QPushButton('Kaldır');self.remove_skin_button=remove;remove.setToolTip('Seçili modeli kaldır');remove.clicked.connect(self.remove_skin);row.addWidget(remove);remove.setObjectName('dangerButton');kart1.addLayout(row)
        self.always.setText('Adını duyunca dinlemeye başla')
        self.character_drafts={};self.editing_skin=parent.settings['skin']
        self.adult_character=QCheckBox('Bu karakterin 18 yaşından büyük olduğunu doğruluyorum');self.adult_character.setChecked(bool(current_profile.get('adult',False)))
        self.skin.currentIndexChanged.connect(self.load_character_voice)
        # Yazar / ticari kullanım satırı kaldırıldı (kullanıcı, 12 Kasım); etiket yalnız hata bildirir.
        self.skin_info=QLabel();self.skin_info.setWordWrap(True);self.skin_info.hide();kart1.addWidget(self.skin_info);self.skin.currentIndexChanged.connect(self.describe_skin);self.describe_skin()
        # Konuşma hızı: modele özel (profilde speech_rate), XTTS 'speed' parametresini çarpar.
        self.rate_label=QLabel();skart2.addWidget(self.rate_label);self.rate=QSlider(Qt.Orientation.Horizontal);self.rate.setRange(70,150);self.rate.setSingleStep(5)
        self.rate.setValue(round(float(current_profile.get('speech_rate',1.0))*100));skart2.addWidget(self.rate)
        hiz_not=QLabel('Konuşma hızı seçili modele özel kaydedilir.');hiz_not.setWordWrap(True);hiz_not.setObjectName('caption');skart2.addWidget(hiz_not)
        self.rate.valueChanged.connect(lambda value:self.rate_label.setText(f'Konuşma hızı · {value/100:.2f}×'.replace('.',',')));self.rate_label.setText(f'Konuşma hızı · {self.rate.value()/100:.2f}×'.replace('.',','))
        self.size_label=QLabel();kart2.addWidget(self.size_label);self.size=QSlider(Qt.Orientation.Horizontal);self.size.setRange(50,180);self.size.setValue(parent.settings['size']);kart2.addWidget(self.size)
        self.size.valueChanged.connect(lambda value:self.size_label.setText(f'Karakter boyutu · %{value}'));self.size_label.setText(f"Karakter boyutu · %{parent.settings['size']}")
        self.profile_status=QLabel('Boyut ve konuşma hızı bu modele özel kaydedilir.');self.profile_status.setWordWrap(True);self.profile_status.setObjectName('caption');kart2.addWidget(self.profile_status)
        self.voice_gender.activated.connect(self._save_character_profile);self.speech_voice.activated.connect(self._save_character_profile);self.voice.activated.connect(self._save_character_profile)
        self.adult_character.clicked.connect(self._save_character_profile);self.size.sliderReleased.connect(self._save_character_profile);self.rate.sliderReleased.connect(self._save_character_profile)
        from windows_startup import enabled as startup_enabled
        self.roam=QCheckBox('Görev çubuğu boyunca gezinsin');self.roam.setChecked(parent.settings['roam'])
        self.roam.setToolTip('Elle sürüklemek gezinmeyi durdurur. Sağ tık > Görev çubuğuna dön ve gezin ile devam eder.');kart3.addWidget(self.roam)
        self.windows_startup=QCheckBox('Windows açılınca Yumi’yi başlat');self.windows_startup.setChecked(startup_enabled());kart3.addWidget(self.windows_startup)
        skart3.addWidget(self.mic_device);skart3.addWidget(self.always)
        self._ses_bolumu(skart1,skart4)
        self._paket_bolumu(character)  # F3 (19 Kas): .yumipaket ekle / kaldır / yeniden bağla
        close=QPushButton('Değişiklikleri kaydet');close.setObjectName('primaryButton');close.clicked.connect(self.accept);outer.addWidget(close)
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12);combo.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.preview_theme()
    # ---- SC1/SC2 (19 Kas 2026, kullanıcı): Ses bölümü — sesli cevap ayarı + modelsiz API sesi (work/docs/SES-CIKISI.md)
    def _ses_bolumu(self,k_mod,k_api):
        import ses_cikisi
        s=self.owner.settings
        self.sesli_cevap=QComboBox()
        for title,key in ses_cikisi.MODLAR:self.sesli_cevap.addItem(title,key)
        self.sesli_cevap.setCurrentIndex(max(0,self.sesli_cevap.findData(ses_cikisi.mod(self.owner))));k_mod.addWidget(self.sesli_cevap)
        self.sesli_cevap_not=QLabel();self.sesli_cevap_not.setWordWrap(True);self.sesli_cevap_not.setObjectName('caption');k_mod.addWidget(self.sesli_cevap_not)
        notlar={'her_zaman':'Yazsan da konuşsan da cevap sesli gelir.',
                'sesli_konusunca':'Yazarak sorarsan cevap yalnız yazılı gelir; mikrofonla sorarsan sesli gelir.',
                'sessiz':'Yumi hiç konuşmaz, cevaplar yazılı gelir. Mikrofon ve adla çağırma çalışmaya devam eder. Ses modeli kapatılır, bellek boşalır.'}
        def guncelle(*_):self.sesli_cevap_not.setText(notlar.get(self.sesli_cevap.currentData(),''))
        self.sesli_cevap.currentIndexChanged.connect(guncelle);guncelle()
        self.modelsiz_ses=QComboBox();self.modelsiz_ses.addItem('Yumi sesi (yerel)','yerel');self.modelsiz_ses.addItem('API ile ses · ElevenLabs','api')
        self.modelsiz_ses.setCurrentIndex(max(0,self.modelsiz_ses.findData(s.get('modelsiz_ses','yerel'))));k_api.addWidget(self.modelsiz_ses)
        self.model_var_not=QLabel('Kurulu model paketi var: Yumi modelin kendi sesini kullanır. API sesi yalnız hiç model yokken kullanılır; ayarların saklanır.')
        self.model_var_not.setWordWrap(True);self.model_var_not.setObjectName('caption');k_api.addWidget(self.model_var_not)
        self.api_kutu=QWidget();a=QVBoxLayout(self.api_kutu);a.setContentsMargins(0,0,0,0);a.setSpacing(8);k_api.addWidget(self.api_kutu)
        self.api_anahtar=QLineEdit();self.api_anahtar.setEchoMode(QLineEdit.EchoMode.Password);a.addWidget(self.api_anahtar)
        satir=QHBoxLayout();self.api_kaydet=QPushButton('Anahtarı kaydet');self.api_kilit=QPushButton('Kilitle');self.api_sil=QPushButton('Sil');self.api_sil.setObjectName('dangerButton')
        self.api_kilit.setToolTip('Kilitliyken anahtar değiştirilemez ve silinemez')
        for b in (self.api_kaydet,self.api_kilit,self.api_sil):satir.addWidget(b)
        a.addLayout(satir)
        satir2=QHBoxLayout();self.api_ses=QComboBox();satir2.addWidget(self.api_ses,1);self.api_getir=QPushButton('Sesleri getir');satir2.addWidget(self.api_getir);a.addLayout(satir2)
        kayitli=str(s.get('api_ses') or '')
        if kayitli.startswith('api:'):self.api_ses.addItem(s.get('api_ses_adi') or kayitli.split(':',2)[-1],kayitli)
        self.api_dene=QPushButton('Sesi dene');a.addWidget(self.api_dene)
        self.api_durum=QLabel();self.api_durum.setWordWrap(True);a.addWidget(self.api_durum)
        uyari=QLabel('API sesinde cevap metni ses sitesine (ElevenLabs) gönderilir ve hesabından kredi harcar. İnternet ya da kota yoksa cevap yazılı gelir.')
        uyari.setWordWrap(True);uyari.setObjectName('caption');a.addWidget(uyari)
        self.api_kaydet.clicked.connect(self._api_anahtar_kaydet);self.api_sil.clicked.connect(self._api_anahtar_sil);self.api_kilit.clicked.connect(self._api_kilit_degistir)
        self.api_getir.clicked.connect(self._api_sesleri_getir);self.api_dene.clicked.connect(self._api_dene)
        self.modelsiz_ses.currentIndexChanged.connect(self._api_alanlari);self.api_ses.currentIndexChanged.connect(self._api_alanlari)
        self._api_alanlari()
    def _api_alanlari(self,*_):
        import api_ses
        from modelsiz import model_yok
        yok=model_yok(self.owner);api=self.modelsiz_ses.currentData()=='api'
        self.model_var_not.setVisible(not yok);self.modelsiz_ses.setEnabled(yok)
        self.api_kutu.setVisible(api);self.api_kutu.setEnabled(yok)
        kayitli=bool(api_ses.anahtar_oku());kilitli=kayitli and bool(self.owner.settings.get('api_ses_kilitli'))
        self.api_anahtar.setEnabled(not kilitli);self.api_kaydet.setEnabled(not kilitli);self.api_sil.setEnabled(kayitli and not kilitli);self.api_sil.setVisible(not kilitli)  # kilitliyken kırmızı düğme etkin gibi görünmesin
        self.api_kilit.setEnabled(kayitli);self.api_kilit.setText('Kilidi aç' if kilitli else 'Kilitle')
        if kilitli:self.api_anahtar.clear()
        self.api_anahtar.setPlaceholderText('Kayıtlı · kilitli' if kilitli else ('Kayıtlı · değiştirmek için yeni anahtar gir' if kayitli else 'ElevenLabs API anahtarı'))
        self.api_getir.setEnabled(kayitli);self.api_dene.setEnabled(kayitli and bool(self.api_ses.currentData()))
        if not self.api_durum.text():self.api_durum.setText('Anahtar kayıtlı.' if kayitli else 'API anahtarını gir ve kaydet; sonra sesleri getir.')
    def _arka(self,is_,bitti):
        """Ağ işini arayüzü dondurmadan çalıştırır; bitti(sonuç, hata) ana iş parçacığında çağrılır."""
        fut=self.owner.executor.submit(is_)
        def bak():
            if not fut.done():QTimer.singleShot(100,bak);return
            try:sonuc,hata=fut.result(),None
            except Exception as error:sonuc,hata=None,error
            try:bitti(sonuc,hata)
            except RuntimeError:pass  # pencere kapandıysa
        QTimer.singleShot(100,bak)
    def _api_anahtar_kaydet(self):
        import api_ses
        deger=self.api_anahtar.text().strip()
        if not deger:self.api_durum.setText('Önce API anahtarını yaz.');return
        try:api_ses.anahtar_kaydet(deger)
        except Exception as error:self.api_durum.setText(f'Anahtar kaydedilemedi: {error}');return
        self.api_anahtar.clear();self.api_durum.setText('Anahtar kaydedildi. Sesler getiriliyor…');self._api_alanlari();self._api_sesleri_getir()
    def _api_anahtar_sil(self):
        import api_ses
        if QMessageBox.question(self,'API anahtarı','Kayıtlı API anahtarı silinsin mi?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        api_ses.anahtar_sil();self.owner.settings['api_ses_kilitli']=False;save_settings(self.owner.settings)
        self.api_durum.setText('Anahtar silindi.');self._api_alanlari()
    def _api_kilit_degistir(self):
        self.owner.settings['api_ses_kilitli']=not bool(self.owner.settings.get('api_ses_kilitli'));save_settings(self.owner.settings)
        self.api_durum.setText('Anahtar kilitlendi.' if self.owner.settings['api_ses_kilitli'] else 'Kilit açıldı; anahtarı değiştirebilir ya da silebilirsin.');self._api_alanlari()
    def _api_sesleri_getir(self):
        import api_ses
        self.api_getir.setEnabled(False);self.api_durum.setText('Sesler getiriliyor…')
        def bitti(sesler,hata):
            self.api_getir.setEnabled(True)
            if hata:self.api_durum.setText(str(hata));return
            secili=self.api_ses.currentData();self.api_ses.blockSignals(True);self.api_ses.clear()
            for ad,kimlik in sesler:self.api_ses.addItem(ad,f'api:elevenlabs:{kimlik}')
            self.api_ses.setCurrentIndex(max(0,self.api_ses.findData(secili)));self.api_ses.blockSignals(False)
            self.api_durum.setText(f'{len(sesler)} ses bulundu. Birini seçip “Sesi dene” ile dinle.' if sesler else 'Hesapta ses yok; ElevenLabs sitesinden bir ses ekle.');self._api_alanlari()
        self._arka(lambda:api_ses.sesler('elevenlabs'),bitti)
    def _api_dene(self):
        ses=self.api_ses.currentData()
        if not ses:return
        metin='Merhaba, ben Yumi. Sesim böyle duyuluyor.'
        segment=self.owner.calar.yeni_bolum(metin,0.0)
        self.owner.speech_executor.submit(self.owner._produce_segment,segment,metin,ses)
        self.api_durum.setText('Deneme sesi çalınıyor… Hata olursa ana pencerede yazar.')
    def _api_eksik_uyar(self):
        from modelsiz import model_yok
        import api_ses
        s=self.owner.settings
        if s.get('modelsiz_ses')!='api' or not model_yok(self.owner):return
        if not api_ses.anahtar_oku() or not str(s.get('api_ses') or '').startswith('api:'):
            self.owner.show_error('API sesi için anahtarı kaydet ve bir ses seç. Eksikken yerel Yumi sesi kullanılır.')
    # ---- F3 (19 Kas 2026): .yumipaket ekle / kaldır (bağlantı kes) / yeniden bağla — AYIRMA-PLANI G-F3
    def _paket_bolumu(self,layout):
        from PySide6.QtWidgets import QProgressBar
        f=QFrame();f.setObjectName('card');f.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True);k=QVBoxLayout(f);k.setContentsMargins(14,12,14,12);k.setSpacing(8);layout.addWidget(f)
        b=QLabel('Paketler');b.setObjectName('caption');k.addWidget(b)
        self.paket_liste=QVBoxLayout();self.paket_liste.setSpacing(6);k.addLayout(self.paket_liste)
        self.paket_bar=QProgressBar();self.paket_bar.setRange(0,1000);self.paket_bar.setTextVisible(False);self.paket_bar.setMaximumHeight(8);self.paket_bar.hide();k.addWidget(self.paket_bar)
        self.paket_durum=QLabel();self.paket_durum.setWordWrap(True);self.paket_durum.hide();k.addWidget(self.paket_durum)
        self.paket_ekle_dugme=QPushButton('+ Paket ekle');self.paket_ekle_dugme.setToolTip('Yumi model paketi (.yumipaket) ekle');self.paket_ekle_dugme.clicked.connect(self.add_skin);k.addWidget(self.paket_ekle_dugme)
        ipucu=QLabel('Paket dosyasını (.yumipaket) bu sayfaya sürükleyip bırakabilirsin. Ekleme arka planda sürer; Yumi bu sırada çalışmaya devam eder.')
        ipucu.setWordWrap(True);ipucu.setObjectName('caption');k.addWidget(ipucu)
        satir=QHBoxLayout();self.paket_klasor_yazi=QLabel();self.paket_klasor_yazi.setWordWrap(True);self.paket_klasor_yazi.setObjectName('caption');satir.addWidget(self.paket_klasor_yazi,1)
        degistir=QPushButton('Değiştir');degistir.setToolTip('Yeni paketlerin açılacağı klasör (ör. başka bir disk)');degistir.clicked.connect(self._paket_klasor_degistir);satir.addWidget(degistir)
        self.paket_klasor_varsayilan=QPushButton('Varsayılan');self.paket_klasor_varsayilan.clicked.connect(lambda:self._paket_klasor_ayarla(''));satir.addWidget(self.paket_klasor_varsayilan)
        k.addLayout(satir)
        self.setAcceptDrops(True)
        self._paket_gosterilen=None
        self._paket_zamanlayici=QTimer(self);self._paket_zamanlayici.timeout.connect(self._paket_izle);self._paket_zamanlayici.start(200)
        self._paket_listele();self._paket_klasor_yazisi();self._paket_izle()
    def _paket_klasor_yazisi(self):
        import paket_yonetici as py
        ozel=bool(str(self.owner.settings.get('paket_klasoru') or '').strip())
        self.paket_klasor_yazi.setText(f'Paket klasörü: {py.kok_sec(self.owner.settings)}'+('' if ozel else ' (varsayılan)'))
        self.paket_klasor_varsayilan.setVisible(ozel)
    def _paket_klasor_ayarla(self,yol):
        self.owner.settings['paket_klasoru']=str(yol or '');save_settings(self.owner.settings);self._paket_klasor_yazisi()
        self._paket_mesaj('Yeni paketler bu klasöre açılır; kurulu paketler bulundukları yerde kalır.')
    def _paket_klasor_degistir(self):
        import paket_yonetici as py
        yol=QFileDialog.getExistingDirectory(self,'Paket klasörü',str(py.kok_sec(self.owner.settings)))
        if yol:self._paket_klasor_ayarla(yol)
    def _paket_mesaj(self,metin):
        self.paket_durum.setText(metin);self.paket_durum.setVisible(bool(metin))
    def _paket_is_suruyor(self):
        i=getattr(self.owner,'paket_isi',None)
        return i is not None and not i.islendi
    def _paket_listele(self):
        import paket_yonetici as py
        while self.paket_liste.count():
            oge=self.paket_liste.takeAt(0);w=oge.widget()
            if w is not None:w.hide();w.setParent(None);w.deleteLater()  # 19 Kas: eski satır silinene kadar üst üste görünmesin
        kayitlar=py.kayitlar()
        if not kayitlar:
            bos=QLabel('Henüz paket eklenmedi.');bos.setObjectName('caption');self.paket_liste.addWidget(bos);return
        suruyor=self._paket_is_suruyor()
        for k in kayitlar:
            satir=QWidget();l=QHBoxLayout(satir);l.setContentsMargins(0,0,0,0)
            metin=f"{k.get('baslik') or k['ad']} · {k['surum']} · {len(k.get('karakterler',[]))} karakter · {py.boyut_yazi(k.get('boyut'))}"
            if k.get('kisisel'):metin+=' · kişisel'
            if not k.get('etkin'):metin+=' · bağlı değil'
            etiket=QLabel(metin);etiket.setWordWrap(True);etiket.setToolTip(f"Yer: {k['kok']}\nKarakterler: "+', '.join(c['ad'] for c in k.get('karakterler',[])));l.addWidget(etiket,1)
            if k.get('etkin'):
                d=QPushButton('Kaldır');d.setObjectName('dangerButton');d.setToolTip('Paketin bağlantısını kes; dosyalar silinmez');d.clicked.connect(lambda _=False,ad=k['ad']:self._paket_kaldir(ad))
            else:
                d=QPushButton('Yeniden bağla');d.setToolTip('Dosyaları denetleyip paketi yeniden bağla');d.clicked.connect(lambda _=False,ad=k['ad']:self._paket_yeniden_bagla(ad))
            d.setEnabled(not suruyor);l.addWidget(d);self.paket_liste.addWidget(satir)
    def _paket_izle(self):
        i=getattr(self.owner,'paket_isi',None)
        try:
            if i is not None and not i.islendi:
                self.paket_bar.show();self.paket_bar.setValue(int(i.ilerleme*1000))
                gecen=time.monotonic()-i.basla_t;kalan=''
                if i.ilerleme>0.03 and gecen>5:
                    sn=gecen*(1-i.ilerleme)/i.ilerleme;kalan=f' · ≈ {max(1,round(sn/60))} dk kaldı' if sn>=60 else f' · ≈ {max(1,int(sn))} sn kaldı'
                self._paket_mesaj(f'{i.asama} %{int(i.ilerleme*100)}{kalan}');self.paket_ekle_dugme.setEnabled(False)
                if self._paket_gosterilen is not i:self._paket_gosterilen=i;self._paket_listele()
                return
            self.paket_bar.hide();self.paket_ekle_dugme.setEnabled(True)
            if i is not None and self._paket_gosterilen is i:
                self._paket_gosterilen=None;self._paket_bitti_goster()
        except RuntimeError:pass
    def _paket_bitti_goster(self):
        self._paket_listele();self.fill_skins(self.owner.settings.get('skin'));self.describe_skin()
        if hasattr(self,'_api_alanlari'):self._api_alanlari()
        self._paket_mesaj(getattr(self.owner,'paket_son_mesaj','') or '')
    def _paket_baslat(self,is_):
        self.owner.paket_isi=is_;is_.start();self._paket_izle()
    def _paket_ekle_yol(self,yol):
        import paket_yonetici as py
        from paket_dogrula import PaketHatasi
        if self._paket_is_suruyor():self._paket_mesaj('Bir paket işlemi sürüyor; bitince tekrar dene.');return
        try:o=py.onizleme(yol,py.kok_sec(self.owner.settings))
        except (PaketHatasi,OSError) as error:
            QMessageBox.warning(self,'Paket eklenemedi',str(error));return
        Yes,No=QMessageBox.StandardButton.Yes,QMessageBox.StandardButton.No
        if o['durum']=='ayni_kurulu':
            QMessageBox.information(self,'Paket ekle',f"{o['baslik']} {o['surum']} zaten kurulu.");return
        if o['durum']=='ayni_bagli_degil':
            if QMessageBox.question(self,'Paket ekle',f"{o['baslik']} {o['surum']} kurulu ama bağlantısı kesik. Dosyalar denetlenip yeniden bağlansın mı?",Yes|No,Yes)==Yes:
                self._paket_baslat(py.YenidenBagla(o['ad']))
            return
        baska=o.get('baska_yerde') or []
        if baska and len(baska)>=len(o['karakterler']):
            QMessageBox.information(self,'Paket ekle',f"{o['baslik']} içindeki karakterler Yumi'de zaten var ({baska[0]['yer']}); tekrar eklenmedi.");return
        if not o['yeterli']:
            QMessageBox.warning(self,'Paket eklenemedi',f"Yeterli boş alan yok: gereken {py.boyut_yazi(o['boyut'])}, boş {py.boyut_yazi(o['bos'])} ({o['kok']}). Başka bir paket klasörü seçebilirsin.");return
        kutu=QMessageBox(self);kutu.setWindowTitle('Paket ekle');kutu.setTextFormat(Qt.TextFormat.RichText);kutu.setText(py.onizleme_metni(o))
        tamam=kutu.addButton({'guncelleme':'Güncelle','eski_surum':'Yine de kur'}.get(o['durum'],'Ekle'),QMessageBox.ButtonRole.AcceptRole)
        kutu.addButton('Vazgeç',QMessageBox.ButtonRole.RejectRole);kutu.exec()
        if kutu.clickedButton() is not tamam:return
        atla,uzerine=[c['klasor'] for c in baska],False  # başka klasörde zaten olanlar hiç açılmaz
        if o['cakisan']:
            liste=', '.join(f"{c['ad']} ({c['kaynak']})" for c in o['cakisan'])
            k2=QMessageBox(self);k2.setWindowTitle('Karakter zaten kurulu')
            k2.setText(f'Şu karakterler başka bir yerden zaten kurulu: {liste}.\nÜzerine yazılırsa eski klasörler silinmez, “_eski” klasörüne taşınır.')
            b_uz=k2.addButton('Üzerine yaz',QMessageBox.ButtonRole.AcceptRole);b_atla=k2.addButton('Atla',QMessageBox.ButtonRole.AcceptRole)
            k2.addButton('Vazgeç',QMessageBox.ButtonRole.RejectRole);k2.exec()
            if k2.clickedButton() is b_uz:uzerine=True
            elif k2.clickedButton() is b_atla:atla=atla+[c['klasor'] for c in o['cakisan']]
            else:return
        self._paket_baslat(py.Kurulum(o,atla=atla,uzerine_yaz=uzerine))
    def _paket_kaldir(self,ad):
        import paket_yonetici as py
        if self._paket_is_suruyor():self._paket_mesaj('Bir paket işlemi sürüyor; bitince tekrar dene.');return
        k=py.kayit(ad)
        if k is None:return
        cevap=QMessageBox.question(self,'Paketi kaldır',f"{k.get('baslik') or ad} kaldırılsın mı?\nDosyalar silinmez, yerinde kalır ({k['kok']}). İstediğin zaman “Yeniden bağla” ile geri gelir.",
                                   QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if cevap!=QMessageBox.StandardButton.Yes:return
        self.owner.paket_baglantisini_kes(ad)
        self._paket_bitti_goster()
    def _paket_yeniden_bagla(self,ad):
        import paket_yonetici as py
        if self._paket_is_suruyor():self._paket_mesaj('Bir paket işlemi sürüyor; bitince tekrar dene.');return
        self._paket_baslat(py.YenidenBagla(ad))
    def dragEnterEvent(self,event):
        urls=event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(u.toLocalFile().lower().endswith('.yumipaket') for u in urls):event.acceptProposedAction()
        else:event.ignore()
    def dropEvent(self,event):
        yollar=[u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile().lower().endswith('.yumipaket')]
        if yollar:
            event.acceptProposedAction();self.tabs.setCurrentIndex(0)
            QTimer.singleShot(0,lambda:self._paket_ekle_yol(yollar[0]))
    def preview_theme(self,*args):
        from themes import stylesheet
        style=stylesheet(self.theme.currentData(),self.opacity.value())
        self.owner.setStyleSheet(style)
        self.owner._refresh_icons(self.theme.currentData())
        self.setStyleSheet(style)
        # 12 Kasım 23:40 (kullanıcı): tema seçilince hemen kalıcı olsun. Önceden yalnız önizlemeydi; Sohbet'e dönünce
        # reject() → apply_theme() kaydedilmemiş eski temayı geri getiriyordu.
        if self.theme.currentData() and (self.owner.settings.get('theme')!=self.theme.currentData() or self.owner.settings.get('panel_opacity')!=self.opacity.value()):
            self.owner.settings.update(theme=self.theme.currentData(),panel_opacity=self.opacity.value())
            save_settings(self.owner.settings)
            if hasattr(self.owner,'dekor'):self.owner.dekor.gorselleri_yenile()
            if hasattr(self.owner,'overlay'):self.owner.overlay.setStyleSheet(style)
    def reject(self):
        if not self._save_character_profile():return
        self.owner.apply_theme()
        super().reject()
    def open_tool(self,action):
        QTimer.singleShot(0,action)
    def fill_voices(self,selected=None):
        previous=self.speech_voice.currentData();chosen=selected or previous;self.speech_voice.blockSignals(True);self.speech_voice.clear();gender=self.voice_gender.currentData()
        from modelsiz import model_yok
        from dagitim import SISTEM_SESI
        gizle_sistem=not model_yok(self.owner)  # 19 Kas (kullanıcı): model kuruluyken "Yumi sesi (varsayılan)" listede görünmez
        for title,key,tone in VOICES:
            if gizle_sistem and key==SISTEM_SESI:continue
            if gender=='any' or tone in (gender,'any'):
                self.speech_voice.addItem(title,key)
        index=self.speech_voice.findData(chosen)
        if index<0 or not self.speech_voice.model().item(index).isEnabled():
            index=next((i for i in range(self.speech_voice.count()) if self.speech_voice.model().item(i).isEnabled()),-1)
        self.speech_voice.setCurrentIndex(index);self.speech_voice.blockSignals(False)
        if previous!=self.speech_voice.currentData() and hasattr(self,'voice_preview'):self.voice_preview.cancel()
        if hasattr(self,'voice'):self.voice.setVisible(self.speech_voice.currentData()=='openai-tts')
    def show_browser_status(self,message,pending):
        self.browser_status.setText(message);self.browser_login.setEnabled(not pending);self.browser_hide.setEnabled(not pending)
        for button in self.account_buttons.values():button.setEnabled(not pending)

    def login_account(self,provider='gemini-web'):
        self.owner._browser_login(provider or 'gemini-web')

    def load_character_voice(self,*args,store_current=True):
        selected=self.skin.currentData()
        if not selected:return
        if store_current and getattr(self,'editing_skin',None):
            if not self._save_character_profile():
                self.skin.blockSignals(True);self.skin.setCurrentIndex(self.skin.findData(self.editing_skin));self.skin.blockSignals(False);return
        saved=self.character_drafts.get(selected,profile(self.owner.settings,selected));self.editing_skin=selected
        self.voice_gender.setCurrentIndex(max(0,self.voice_gender.findData(saved['gender'])));self.fill_voices(saved['speech_voice']);self.voice.setCurrentText(saved['voice']);self.voice.setVisible(self.speech_voice.currentData()=='openai-tts');self.adult_character.setChecked(bool(saved.get('adult',False)))
        if hasattr(self,'size'):self.size.setValue(int(saved.get('size',100)))
        if hasattr(self,'rate'):self.rate.setValue(round(float(saved.get('speech_rate',1.0))*100))

    def character_values(self):
        saved=profile(self.owner.settings,self.editing_skin)
        rate=self.rate.value()/100 if hasattr(self,'rate') else float(saved.get('speech_rate',1.0))
        return {**saved,'name':saved['name'],'wake_alias':'','gender':self.voice_gender.currentData(),'speech_voice':self.speech_voice.currentData(),'voice':self.voice.currentText(),'adult':self.adult_character.isChecked(),'size':self.size.value(),'speech_rate':rate}

    def _save_character_profile(self,*args):
        if not getattr(self,'editing_skin',None) or not hasattr(self,'size'):return True
        values=self.character_values()
        from voice_profiles import sabit_profiller
        sabit=sabit_profiller()  # G-A2: değiştirilemez ses profilleri karakter.json gorunumler[].profil
        if self.editing_skin==self.owner.settings.get('skin'):
            from voice_profiles import konusma_hizi_uygula
            konusma_hizi_uygula(values.get('speech_rate',1.0))
        if getattr(self,'editing_skin',None) in sabit:
            values.update(speech_voice=sabit[self.editing_skin]['speech_voice'],
                          voice=sabit[self.editing_skin]['voice'],
                          gender=sabit[self.editing_skin]['gender'])
        self.character_drafts[self.editing_skin]=values
        old=self.owner.settings
        profiles={**old.get('voice_profiles',{}),**self.character_drafts}
        if profiles==old.get('voice_profiles',{}):return True
        candidate={**old,'voice_profiles':profiles};active=profile(candidate)
        candidate.update(speech_voice=active['speech_voice'],voice=active.get('voice','marin'),size=int(active.get('size',old['size'])))
        try:save_settings(candidate)
        except OSError:
            self.profile_status.setText('Profil kaydedilemedi. Değişiklikler burada korunuyor; tekrar dene.');return False
        previous_name=character_name(old);previous_voice=old.get('speech_voice');previous_size=old.get('size')
        old.update(candidate);self.owner.voice_capture.wake_name=character_name(old)
        if previous_size!=old['size']:self.owner.overlay.set_scale(old['size'])
        self.owner._sync_name_wake()
        if previous_name!=character_name(old) or previous_voice!=old['speech_voice']:QTimer.singleShot(0,self.owner._warm_native)
        self.profile_status.setText('Bu modelin tercihleri kaydedildi.');return True

    def update_provider_fields(self,*args):
        self.openai_group.hide()
        if hasattr(self,'browser_login'):self.browser_login.setVisible(True)
        if hasattr(self,'browser_hide'):self.browser_hide.setVisible(True)
        if hasattr(self,'browser_status'):self.browser_status.setVisible(True)
    def preview_voice(self):
        self.voice_preview.start(self.speech_voice.currentData(),self.voice.currentText())

    def fill_skins(self,selected):
        self.skin.blockSignals(True)
        self.skin.clear()
        from skins import grouped_available
        for group,entries in grouped_available(self.owner.settings):
            self.skin.addItem(group if entries else group+' · henüz eklenmedi',None)
            self.skin.model().item(self.skin.count()-1).setEnabled(False)
            for title,key in entries:self.skin.addItem(title,key)
        index=self.skin.findData(selected);self.skin.setCurrentIndex(index if index>=0 else next((i for i in range(self.skin.count()) if self.skin.itemData(i)), -1))
        self.skin.blockSignals(False)
        if hasattr(self,'skin_info'):self.load_character_voice(store_current=False)

    def describe_skin(self):
        key=self.skin.currentData() or ''
        # 12 Kasım (kullanıcı): Kaldır yerleşik VRM'lerde de çalışır; dosya data/kaldirilan-modeller'e taşınır (geri getirilebilir).
        self.remove_skin_button.setEnabled(bool(skin_path(key)))
        self.remove_skin_button.setToolTip('Seçili modeli kaldır' if skin_path(key) else 'Bu model kaldırılamaz.')
        if hasattr(self,'inspect_skin_button'):self.inspect_skin_button.setEnabled(bool(skin_path(key)))  # 19 Kas: modelsizken soluk
        message='' if skin_path(key) or key==SPRITE else ('Henüz model paketi eklenmedi; Yumi modelsiz çalışıyor (varsayılan Yumi sesi).' if not key and self.skin.count()==0 else 'Karakter dosyası bulunamadı.')  # G-A2
        self.skin_info.setText(message);self.skin_info.setVisible(bool(message))

    def inspect_skin(self):
        path=skin_path(self.skin.currentData() or '')
        if not path:self.skin_info.setText('Önizleme için kütüphaneden bir VRM karakter seç.');self.skin_info.show();return
        from three_vrm_view import ThreeVRMWindow
        old=getattr(self.owner,'preview_window',None)
        if old is not None:old.close()
        window=ThreeVRMWindow(self.owner,path,self.skin.currentText(),kullan=self.accept);self.owner.preview_window=window
        window.closed.connect(lambda:setattr(self.owner,'preview_window',None))
        window.show();window.raise_();window.activateWindow()

    def add_skin(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Paket ekle',str(Path.home()/'Downloads'),'Yumi paketi (*.yumipaket);;Eski model paketi (*.yumimodel)')
        paketler=[p for p in paths if p.lower().endswith('.yumipaket')];paths=[p for p in paths if not p.lower().endswith('.yumipaket')]
        if paketler:
            self._paket_ekle_yol(paketler[0])
            if len(paketler)>1:self._paket_mesaj('Paketler tek tek eklenir; ilki ekleniyor, diğerlerini sonra ekle.')
        if not paths:return
        from model_setup import import_models
        def completed(keys):
            if keys:
                for key in keys:self.character_drafts[key]=dict(profile(self.owner.settings,key))
                self.fill_skins(keys[-1]);self.describe_skin()
        import_models(self.owner,paths,completed)

    def remove_skin(self):
        key=self.skin.currentData() or ''
        if not key.startswith('vrm:') or not skin_path(key):return
        import karakterler,paket_yonetici
        kayit=karakterler.gorunum(key);pk=paket_yonetici.paketi_bul(kayit['klasor']) if kayit else None
        if pk:  # F3: paket modelleri tek tek taşınmaz (makbuz bozulur); paket bütün olarak bağlantıdan çıkarılır
            QMessageBox.information(self,'Modeli kaldır',f"Bu model “{pk.get('baslik') or pk['ad']}” içinde. Paketi aşağıdaki Paketler bölümünden kaldırabilirsin; dosyalar silinmez.");return
        if sum(1 for _,k in available_skins(self.owner.settings) if k!=SPRITE and k!=key)==0:
            self.owner.show_error('Son model kaldırılamaz.');return
        name=self.skin.currentText()
        answer=QMessageBox.question(self,'Modeli kaldır',f'“{name}” kaldırılsın mı?\nDosya Yumi içinde data/kaldirilan-modeller klasörüne taşınır; istersen geri getirebilirsin.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            if self.owner.settings['skin']==key:
                fallback=default_skin()
                if fallback==key:fallback=next((k for _,k in available_skins(self.owner.settings) if k!=key),default_skin())
                self.owner.avatar.skin=fallback;self.owner.overlay.avatar.skin=fallback
                apply_profile(self.owner.settings,fallback);save_settings(self.owner.settings)
            remove_model(key);self.fill_skins(self.owner.settings['skin']);self.describe_skin()
        except Exception as error:self.owner.show_error('Model kaldırılamadı: '+str(error))

    def save_key(self):
        value=self.key.text().strip()
        if not value.startswith('sk-') or len(value)<25:
            self.key_status.setText('Geçerli bir OpenAI API anahtarı girin.'); return False
        try:
            temporary=KEY_FILE.with_suffix('.tmp');temporary.write_bytes(protect(value.encode('utf-8')));temporary.replace(KEY_FILE)
            self.owner.api_key=value
            self.owner.previous_id=None
            self.key.clear();self.key.setPlaceholderText('Kayıtlı · değiştirmek için yeni anahtar gir')
            self.key_status.setText('Anahtar Windows hesabınızla şifrelenerek kaydedildi.')
        except OSError as error:
            self.key_status.setText(str(error));return False
        return True

    def delete_key(self):
        try: KEY_FILE.unlink(missing_ok=True)
        except OSError: pass
        self.owner.api_key=os.getenv('OPENAI_API_KEY','')
        self.owner.previous_id=None
        self.key_status.setText('Kaydedilmiş anahtar silindi.')

    def save_gemini_key(self):
        value=self.gemini_key.text().strip()
        if len(value)<20:self.gemini_status.setText('Geçerli bir Gemini API anahtarı gir.');return False
        try:
            temporary=GEMINI_KEY_FILE.with_suffix('.tmp');temporary.write_bytes(protect(value.encode('utf-8')));temporary.replace(GEMINI_KEY_FILE);self.owner.gemini_key=value;self.gemini_key.clear();self.gemini_key.setPlaceholderText('Kayıtlı · değiştirmek için yeni anahtar gir');self.gemini_status.setText('Gemini anahtarı Windows hesabınla şifrelenerek kaydedildi.')
        except OSError as error:self.gemini_status.setText(str(error));return False
        return True
    def delete_gemini_key(self):
        GEMINI_KEY_FILE.unlink(missing_ok=True);self.owner.gemini_key=os.getenv('GEMINI_API_KEY','');self.gemini_status.setText('Kaydedilmiş Gemini anahtarı silindi.')

    def accept(self):
        if not self._save_character_profile():return
        if self.key.text().strip() and not self.save_key():return
        if self.gemini_key.text().strip() and not self.save_gemini_key():return
        from windows_startup import enabled as startup_enabled,set_enabled as set_startup
        try:
            if self.windows_startup.isChecked()!=startup_enabled():set_startup(self.windows_startup.isChecked())
        except OSError:
            self.owner.show_error('Windows başlangıç ayarı kaydedilemedi.');return
        old_always=self.owner.settings.get('name_wake_enabled',False)
        previous_provider=self.owner.settings['provider']
        previous_voice=self.owner.settings.get('speech_voice')
        secili_skin=self.skin.currentData() or self.owner.settings.get('skin')  # SC1 (19 Kas): modelsizde liste boş → None; kaydet çöküyordu
        if self.skin.currentData():self.character_drafts[secili_skin]=self.character_values()
        self.owner.settings.setdefault('voice_profiles',{}).update(self.character_drafts)
        self.owner.settings.update(theme=self.theme.currentData(),panel_opacity=self.opacity.value(),speech_voice=self.speech_voice.currentData() or self.owner.settings.get('speech_voice'),skin=secili_skin, voice=self.voice.currentText(),mic_device=self.mic_device.currentData(),
            provider=self.provider.currentData() or 'gemini-web',model=DEFAULTS['model'],city=self.city.text().strip(),size=self.size.value(),
            always_listen=False,name_wake_enabled=self.always.isChecked(),roam=self.roam.isChecked())
        onceki_ses_cikisi=tuple(self.owner.settings.get(k) for k in ('sesli_cevap','modelsiz_ses','api_ses'))
        self.owner.settings.update(sesli_cevap=self.sesli_cevap.currentData(),modelsiz_ses=self.modelsiz_ses.currentData(),
            api_ses=self.api_ses.currentData() or self.owner.settings.get('api_ses',''),api_ses_adi=self.api_ses.currentText() if self.api_ses.currentData() else self.owner.settings.get('api_ses_adi',''))
        if previous_provider!=self.owner.settings['provider']:self.owner.previous_id=None
        save_settings(self.owner.settings)
        # Karakter/ses değişince yeni sesi arka planda ısıt (ilk cevap gecikip takılmasın)
        if self.owner.settings.get('speech_voice')!=previous_voice:
            self.owner._ses_hazirla(str(self.owner.settings.get('speech_voice','')))
        elif onceki_ses_cikisi!=tuple(self.owner.settings.get(k) for k in ('sesli_cevap','modelsiz_ses','api_ses')):
            self.owner._ses_hazirla(str(self.owner.settings.get('speech_voice','')))  # SC1/SC2: XTTS'i kapat ya da yeniden ısıt
        self._api_eksik_uyar()
        self.owner._retry_browser()
        self.owner.voice_capture.wake_name=character_name(self.owner.settings)
        self.owner.apply_theme()
        self.owner.avatar.skin=self.owner.settings['skin']
        if hasattr(self.owner,'overlay') and hasattr(self.owner.overlay,'avatar'):
            self.owner.overlay.avatar.skin=self.owner.settings['skin']
        self.owner.overlay.set_scale(self.size.value())
        if self.owner.voice_capture.device_name!=self.mic_device.currentData():
            self.owner.voice_capture._stop_stream()
            self.owner.voice_capture.device_name=self.mic_device.currentData()
        self.owner._sync_name_wake()
        QTimer.singleShot(0,lambda:self.owner._warm_native(force=True))
        super().accept()


class YumiWindow(QMainWindow):
    browser_status_changed=Signal(str,bool)
    skill_alert_received=Signal(str,dict)
    skill_result_received=Signal(str,dict)
    def __init__(self):
        super().__init__()
        self.settings=load_settings()
        from modelsiz import model_yok_guncelle
        model_yok_guncelle(self)  # C05: hiç kurulu model yoksa modelsiz, ad "Yumi"
        for key in tuple(self.settings):
            if key.startswith('dance_') or key in ('auto_dance','adult_dance'):self.settings.pop(key)
        save_settings(self.settings)
        try:
            from voice_profiles import konusma_hizi_uygula
            konusma_hizi_uygula(profile(self.settings).get('speech_rate',1.0))
        except Exception:pass
        self.api_key=load_key()
        self.gemini_key=load_gemini_key()
        self.previous_id=None
        self.assistant=Assistant(self.settings,DATA_DIR)
        self.executor=ThreadPoolExecutor(max_workers=3)
        self.chat_executor=ThreadPoolExecutor(max_workers=1)
        self.results=queue.Queue()
        self._ses_hazirla(str(self.settings.get('speech_voice','')))
        def stt_isit():
            import stt_worker
            t=time.perf_counter();ok=stt_worker.warm_gpu();speech_event(f"stt gpu isitma {'tamam' if ok else 'yok/HATA'} {time.perf_counter()-t:.1f}s")
        self.executor.submit(stt_isit)  # B06: Whisper large-v3-turbo ekran kartında
        self.activity=ActivityCounter()
        self.system_audio=SystemAudio()
        self.manual_pose=None
        self.manual_pose_end=0
        self.last_user_action=time.perf_counter()
        self.busy=False
        self.reply_pending=False
        self.speech_queue=deque()
        self.speech_active=False
        from ses_motoru.akis import Calar
        self.calar=Calar()  # B07: kesintisiz konuşma çaları (yerel ONNX/XTTS sesleri)
        self.speech_executor=ThreadPoolExecutor(max_workers=3)
        self.stream_voice_ok={}
        self.speech_epoch=0
        self.chat_history=[]
        self.exiting=False
        self.drag_pos=None
        self.bubble_generation=0
        self.setWindowTitle('Yumi · 3D Masaüstü Asistanı')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(440,500)
        saved_size=self.settings.get('chat_window_size',[640,600])
        if not isinstance(saved_size,(list,tuple)) or len(saved_size)!=2 or not all(isinstance(n,int) and not isinstance(n,bool) for n in saved_size):saved_size=[640,600]
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(max(440,min(saved_size[0],available.width())),max(500,min(saved_size[1],available.height())))
        self._build_ui()
        from window_resize import WindowResize
        self.window_resize=WindowResize(self)
        self.resize_save_timer=QTimer(self);self.resize_save_timer.setSingleShot(True)
        self.resize_save_timer.timeout.connect(self._remember_window_size)
        self.chat_expiry=QTimer(self);self.chat_expiry.setInterval(60000);self.chat_expiry.timeout.connect(self._expire_chats);self.chat_expiry.start()
        import sys
        parent_dir=str(ROOT.parent)
        if parent_dir not in sys.path:sys.path.insert(0,parent_dir)
        try:
            from yumi_skills import YumiSkillEngine
            from yumi_skills.dispatcher import SkillDispatcher
            self.skill_alert_received.connect(self._on_skill_alert)
            self.skill_result_received.connect(self._on_skill_result)
            self.skill_engine=YumiSkillEngine(custom_storage_dir=str(DATA_DIR),on_alert_callback=self.skill_alert_received.emit)
            self.skill_engine.on_result=self.skill_result_received.emit
            self.skill_dispatcher=SkillDispatcher(self.skill_engine)
        except Exception:
            self.skill_engine=None
            self.skill_dispatcher=None
        try:  # B08 yerel niyet modeli (internetsiz komutlar); yoksa eski yol aynen çalışır
            from yerel_ai.anla import Anlayici
            from yerel_ai.yonlendirici import Yonlendirici
            self.anlayici=Anlayici();self.anlayici.arka_planda_yukle()
            self.yonlendirici=Yonlendirici(self.anlayici,self.skill_engine.execute_skill if self.skill_engine else None,veri_klasoru=DATA_DIR,
                kalip=self.skill_dispatcher.dispatch if self.skill_dispatcher else None,yerel_komut=self._local_command,
                bildir=lambda mesaj:self.results.put(('yerel_bildirim',mesaj)),cilve=self._cilve_motoru)
            if not env_value('TEST_OUTPUT'):self.yonlendirici.rutin.acilis()  # açılış rutinleri (yerel_ai/rutin_isler.py)
        except Exception as error:
            self.yonlendirici=None;speech_event(f'niyet modeli kapali: {error}')
        self.overlay=DesktopCharacter(self)
        self.move_animation=QPropertyAnimation(self.overlay,b'pos',self)
        self.move_animation.setDuration(2000)
        self.move_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        from model_visibility import apply as apply_model_visibility
        apply_model_visibility(self)
        self._tray()
        self.voice_capture=VoiceCapture(self._audio_complete,self.set_status,self.settings['mic_device'],on_manual=self._set_microphone_button,on_partial=self._wake_partial,on_live=self._canli_yazi)
        self.voice_capture.on_sessiz=lambda:QTimer.singleShot(0,self._mikrofon_uyari)  # F1b: izin reddi = hep sıfır ses
        self.voice_capture.wake_name=character_name(self.settings)
        self.audio_output=QAudioOutput(self)
        self.player=QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_buffers=QAudioBufferOutput(self)
        self.player.setAudioBufferOutput(self.audio_buffers)
        self.audio_buffers.audioBufferReceived.connect(self._speech_amplitude)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._playback_error)
        self.signals=Signals()
        self.signals.hotkey.connect(self._hotkey)
        self.hotkey=GlobalHotkey(self.signals.hotkey.emit)
        self.tick=QTimer(self); self.tick.timeout.connect(self._tick); self.tick.start(100)
        self.result_tick=QTimer(self); self.result_tick.timeout.connect(self._read_results); self.result_tick.start(100)
        self.roam_tick=QTimer(self); self.roam_tick.timeout.connect(self._roam); self.roam_tick.start(16)
        self.overlay.avatar.simulationStep.connect(self._render_movement)
        from fullscreen_pause import FullscreenPause
        self.fullscreen_pause=FullscreenPause(self)
        from media_activity import MediaActivity
        from music_runtime import MusicRuntime
        from daily_scenarios import DailyDirector
        self.media_activity=MediaActivity();self.media_activity.start()
        self.music_runtime=MusicRuntime(self);self.daily_director=DailyDirector(self)
        # C05: model gizliyse (modelsiz) zamanlayıcılar kurulduktan sonra model işlerini yeniden kapat.
        from modelsiz import gecis as modelsiz_gecis
        self._modelsiz_durum=None;modelsiz_gecis(self)
        if self.settings.get('name_wake_enabled',False):
            QTimer.singleShot(500,self._start_auto_listen)
        if not env_value('TEST_OUTPUT') and not env_value('DISABLE_LIVE'):
            QTimer.singleShot(900,self._warm_native)
        # The UI and active local conversation must exist before warm-up can
        # publish status or choose a saved website conversation.
        if not env_value('TEST_OUTPUT') and not env_value('DISABLE_BROWSER'):
            QTimer.singleShot(0,self._retry_browser)
        from yerel_ai.medya_duraklat import MuzikDuraklatici
        self.muzik_duraklatici=MuzikDuraklatici();self._muzik_niyet=None;self._bos_basladi=0.
        self.muzik_devam_timer=QTimer(self);self.muzik_devam_timer.timeout.connect(self._muzik_devam_kontrol);self.muzik_devam_timer.start(400)
        if not env_value('TEST_OUTPUT'):  # saat doğruluğu: açılıştan 30 s sonra, sonra 6 saatte bir (salt okunur)
            self.saat_denetim_timer=QTimer(self);self.saat_denetim_timer.timeout.connect(self._saat_denetle)
            QTimer.singleShot(30000,self._saat_denetle);self.saat_denetim_timer.start(6*3600*1000)
            self.web_bekci_timer=QTimer(self);self.web_bekci_timer.timeout.connect(self._web_bekci);self.web_bekci_timer.start(5000)
            try:  # YouTube reklam atlama eklentisinin bildirimleri → data/logs/reklam-atla.log (12 Kasım)
                from yerel_ai.reklam_dinleyici import baslat as _reklam_dinle;_reklam_dinle()
            except Exception:pass

    def _build_ui(self):
        from ui_shell import build_window
        build_window(self)
        self.input.textChanged.connect(self._update_send_button)

    def _refresh_icons(self,theme=None):
        """Simgeler, logo, marka yazısı, ses çubukları ve tema süsü seçili temanın renkleriyle (12 Kasım ARAYUZ)."""
        from ui_shell import icon
        import tema
        key=tema.anahtar(theme or self.settings.get('theme','inci'));t=tema.TEMALAR[key]
        text=t['text'];head=t['header_text'] or text;rail=t['rail_text'] or t['muted']
        if hasattr(self,'navigation'):self.navigation.recolor(rail,t['rail_on_text'])
        for name,button in getattr(self,'header_buttons',{}).items():button.setIcon(icon(name,head,20))
        if hasattr(self,'model_visibility_button'):
            from model_visibility import visible
            self.model_visibility_button.setIcon(icon('eye' if visible(self) else 'eyeoff',head,20))
        for name in ('wave_button','history_button','history_back'):
            if hasattr(self,name):getattr(self,name).setIcon(icon({'wave_button':'wave','history_button':'history','history_back':'back'}[name],t['muted'] if key!='terminal' else text,20))
        if hasattr(self,'new_chat_button'):self.new_chat_button.setIcon(icon('plus',t['on_accent'],16))
        if hasattr(self,'send_button'):self.send_button.setIcon(icon('send',t['on_accent'],18))
        if hasattr(self,'mic_button'):
            recording=self.mic_button.isChecked()
            if recording and key=='witcher':
                self.mic_button.setIcon(QIcon(tema.logo_pixmap('witcher',22)));self.mic_button.setIconSize(QSize(22,22))  # mühür
            else:
                self.mic_button.setIcon(icon('stop' if recording else 'mic','#FFFFFF' if recording and key not in ('terminal','disket') else (t['muted'] if not recording else text),18 if recording else 22))
        if hasattr(self,'logo_label'):self.logo_label.setPixmap(tema.logo_pixmap(key,30 if key!='disket' else 22));self.logo_label.setFixedSize(30 if key!='disket' else 22,30)
        if hasattr(self,'brand_label'):
            self.brand_label.setText(t['brand'])
            if hasattr(self.brand_label,'tema_ayarla'):self.brand_label.tema_ayarla(key)
        if hasattr(self,'ses_cubuklari'):
            self.ses_cubuklari.renk_ayarla(t['accent'] if key not in ('witcher','tas','disket') else ('#3A2A1C' if key=='witcher' else t['text'] if key=='tas' else '#1DB954'),
                                           '#F59DBB' if key=='sakura' else None,4 if key in ('sakura','terminal','disket') else (2 if key=='tas' else 3),4 if key=='sakura' else (2 if key in ('tas','disket') else 3))
            self.kayit_noktasi.renk=QColor(t['rec'])
        if hasattr(self,'dekor') and self.dekor.theme!=key:self.dekor.tema_ayarla(key)

    def _tema_gorselleri(self):
        """Kitap teması: seçili karakterin <kategori>/<Karakter>/arka_plan/ görselleri, sonra paket havuzları (png/jpg/webp)."""
        try:
            import karakterler
            klasorler=karakterler.tema_gorsel_klasorleri(self.settings.get('skin',''))  # G-A2: karakterin arka_plan/ + paketinin _ortak/arka_plan
            sonuc=[]
            for klasor in klasorler:
                if klasor and klasor.is_dir():sonuc+=sorted(p for p in klasor.iterdir() if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp'))
            return sonuc[:40]
        except Exception:return []

    def _set_microphone_button(self,listening):
        self.mic_button.setText('');self.mic_button.setChecked(listening)
        from ui_shell import kayit_gorunumu
        kayit_gorunumu(self,bool(listening))
        self._refresh_icons()

    def _route_page(self,key,opener):
        if self.pages.busy:return
        current=self.pages.currentWidget()
        if current is not self.panel:
            if key=='chat':
                self.navigation_pending=None;current.reject();return
            # sayfadan sayfaya doğrudan geç (araya sohbet girmesin); Ayarlar'dan çıkarken kaydetme davranışı korunur
            if hasattr(current,'_save_character_profile'):
                current._save_character_profile();self.apply_theme()
            self.navigation_pending=None;self._sayfa_degistir=True
            try:opener()
            finally:self._sayfa_degistir=False
            self.navigation.select(key);return
        self.navigation_pending=None;opener();self.navigation.select(key)

    def _nav_chat(self):
        self._route_page('chat',lambda:None)

    def _nav_settings(self,index=0,key='settings'):
        page=getattr(self,'settings_page',None)
        if page is not None and self.pages.currentWidget() is page:
            page.tabs.setCurrentIndex(index);self.navigation.select(key);return
        def open_section():
            self._settings()
            page=getattr(self,'settings_page',None)
            if page is not None:page.tabs.setCurrentIndex(index)
        self._route_page(key,open_section)

    def _activities(self):
        if self.pages.busy or getattr(self,'activity_page',None):return
        from ui_activities import ActivitiesDialog
        self.activity_page=ActivitiesDialog(self);self._push_page(self.activity_page)

    def apply_theme(self):
        from themes import stylesheet
        style=stylesheet(self.settings.get('theme','inci'),self.settings.get('panel_opacity',94))
        self.setStyleSheet(style);self._refresh_icons()
        if hasattr(self,'dekor'):self.dekor.gorselleri_yenile()
        if hasattr(self,'overlay'):self.overlay.setStyleSheet(style)

    def _jump_latest(self):
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def _update_jump(self,*args):
        bar=self.scroll.verticalScrollBar();self.jump_button.move(max(0,self.scroll.viewport().width()-144),max(0,self.scroll.viewport().height()-44))
        self.jump_button.setVisible(bar.maximum()-bar.value()>45);self.jump_button.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'avatar'):
            QTimer.singleShot(0,self._layout_stage)
        if hasattr(self,'resize_save_timer'):self.resize_save_timer.start(500)

    def _remember_window_size(self):
        if not self.isMaximized() and not self.isMinimized() and not self.isFullScreen():
            self.settings['chat_window_size']=[self.width(),self.height()]
            save_settings(self.settings)

    def _layout_stage(self):
        if hasattr(self,'size_grip'):
            root=self.centralWidget();self.size_grip.move(root.width()-20,root.height()-20);self.size_grip.raise_()
        if hasattr(self,'jump_button'):self._update_jump()
        if hasattr(self,'brand_description'):self.brand_description.setVisible(self.width()>=700)
        if hasattr(self,'navigation'):self.navigation.compact(self.pages.height())  # Geçmiş artık ayrı sayfa (ARAYUZ)

    def eventFilter(self,obj,event):
        if isinstance(getattr(self,'scroll',None),QScrollArea) and obj is self.scroll.viewport():
            if event.type()==QEvent.Type.Resize:
                QTimer.singleShot(0,self._layout_messages);QTimer.singleShot(0,self._update_jump)
            return False
        if obj is getattr(self,'stage',None) and event.type()==QEvent.Type.Resize:
            QTimer.singleShot(0,self._layout_stage)
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
            self.drag_pos=event.globalPosition().toPoint()-self.pos(); self.last_user_action=time.perf_counter(); return True
        if event.type()==QEvent.Type.MouseMove and self.drag_pos is not None:
            self.move(event.globalPosition().toPoint()-self.drag_pos); return True
        if event.type()==QEvent.Type.MouseButtonRelease:
            self.drag_pos=None; return True
        return super().eventFilter(obj,event)

    def _tray(self):
        icon=QIcon(str(ROOT/'assets/yumi.svg'));self.setWindowIcon(icon)
        self.tray=QSystemTrayIcon(icon,self);self.tray.setToolTip('Yumi')
        menu=QMenu(); menu.addAction('Yumi’yi göster',self._show)
        # C05: model gizliyken sağ tık menüsüne erişilemez; model seçimi ve ayarlar tepsiden.
        from overlay import model_menusu_doldur
        models=QMenu('Model seç',menu);menu.addMenu(models);menu.model_menu=models  # addMenu(başlık) değil: bkz. overlay.model_menusu_doldur
        models.aboutToShow.connect(lambda:model_menusu_doldur(models,self,self.overlay.select_skin))
        from model_visibility import add_action
        add_action(menu,self)
        menu.addAction('Ayarlar',lambda:(self._show(),self._settings()))
        menu.addAction('🏠 Akıllı Ev & Cihazlar',self._open_smart_home); menu.addAction('Konuş (Ctrl+Alt+M)',self._hotkey); menu.addSeparator(); menu.addAction('Çıkış',self.quit)
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self._show() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def _show(self):
        if not modelsiz_acik(self) and not getattr(getattr(self,'fullscreen_pause',None),'paused',False):self.overlay.show()
        self.show();self.raise_();self.activateWindow()
    def _login(self):
        self.set_status('Tarayıcıda Codex girişini tamamla…'); self.overlay.say('Tarayıcıda hesabına giriş yap.'); self._work('login',login)
    def _hotkey(self): self._show(); self._mic()
    def paket_ac(self,yol):
        """F1b: .yumipaket çift tık → Ayarlar açılır, paket ekleme akışı (önizleme + onay) başlar."""
        if self.exiting or not str(yol).lower().endswith('.yumipaket') or not Path(yol).is_file():return
        if self.pages.busy:QTimer.singleShot(500,lambda:self.paket_ac(yol));return
        if not getattr(self,'settings_page',None):self._settings()
        sayfa=getattr(self,'settings_page',None)
        if sayfa is not None:QTimer.singleShot(300,lambda:sayfa._paket_ekle_yol(str(yol)))
    def _settings(self):
        if self.pages.busy or getattr(self,'settings_page',None):return
        page=SettingsDialog(self);self.settings_page=page
        self._push_page(page)

    def _open_smart_home(self):
        if self.pages.busy or getattr(self,'smart_home_page',None):return
        try:
            from yumi_skills.ui_smart_home_panel import SmartHomeDialog
            page=SmartHomeDialog(self,engine=self.skill_engine)
            self.smart_home_page=page
            self._push_page(page)
        except Exception as e:
            self.show_error(f'Akıllı ev paneli açılamadı: {e}')

    def _on_skill_alert(self,alert_type,alert_data):
        if self.exiting:return
        msg=alert_data.get('message') or alert_type or 'Süreniz doldu!'
        self._on_skill_result('alert',{'ok':True,'speech':msg})
        self.add_message(msg,'assistant');self.show_bubble(msg)
        import ses_cikisi
        if ses_cikisi.model_sesi_yok(self) or ses_cikisi.mod(self)=='sessiz':
            # 19 Kas (kullanıcı): sesi olmayan model (Clippy) konuşmaz ama alarm sessiz kalmaz → klasik alarm bip sesi.
            # 19 Kas akşam (kullanıcı): sessiz kipte de alarm/sayaç bip çalar (konuşma yok).
            self._alarm_bip();self._save_chat_history();return
        self._speak(msg,bildirim=True)  # SC1 (19 Kas, kullanıcı): alarm/sayaç her zaman sesli (sessiz hariç)
        self._save_chat_history()
        self._speak_skill_result(msg)

    def _speak_skill_result(self,text):
        native=getattr(self,'native_audio',None)
        if native and native.active and native.feedback(text):return
        self._skill_feedback_fallback()

    def _skill_feedback_fallback(self):
        if not self.busy:self.set_status('Sonuç ekranda · Seslendirme kullanılamıyor')

    def _on_skill_result(self,name,result):
        if self.exiting:return
        from skill_reactions import reaction
        intent,style=reaction(name,result)
        if modelsiz_acik(self):self._bekleyen_tepki=None;return  # C05: modelsizken tepki beklenmez
        # Canlı kabul (13 Kasım): tepki (yüz/jest) cevabın sesi üretilmeden başlıyordu → sesli cevapta ilk ses çıktığı karede
        # (_tick 'ses basladi' / player.play) uygulanır; sessiz sonuçta ya da 8 sn içinde ses başlamazsa hemen/zaman aşımında.
        if result.get('speech'):
            self._bekleyen_tepki=(time.perf_counter(),intent,style);return
        self._tepki_uygula(intent,style)

    def _tepki_uygula(self,intent=None,style=None):
        if modelsiz_acik(self):self._bekleyen_tepki=None;return  # C05
        if intent is None:
            bekleyen=getattr(self,'_bekleyen_tepki',None)
            if not bekleyen:return
            _,intent,style=bekleyen
        self._bekleyen_tepki=None
        now=time.perf_counter()
        for view in (self.avatar,self.overlay.avatar):
            if view.model:view.model.skill_reaction=(now,intent)
        self.avatar.conversation.intent=intent
        scene=self.overlay.avatar.furniture or self.avatar.furniture
        if style and not scene and not self.avatar.hand_gesture and not getattr(getattr(self,'music_runtime',None),'enabled',False):
            self.avatar.hand_gesture=style;self.gesture_until=now+2.2;self.overlay.sync()

    def _start_skill_command(self,text,native=False):
        dispatcher=getattr(self,'skill_dispatcher',None)
        call=dispatcher.parse(text) if dispatcher else None
        if call is None:return False
        if not native:self.busy=True;self.voice_capture.suspended=True
        if not native:self.active_skill_requests=getattr(self,'active_skill_requests',0)+1
        self.set_status('İşlem yürütülüyor…')
        name,args=call
        def run():return text,self.skill_engine.execute_skill(name,args).get('speech','İşlem sonucu alınamadı.')
        self._work('skill_native' if native else 'skill_answer',run)
        return True

    def _push_page(self,page):
        page.finished.connect(lambda *_:self.pages.pop(page))
        if getattr(self,'_sayfa_degistir',False):return self.pages.degistir(page)
        return self.pages.setCurrentWidget(page)

    def _page_closed(self,page):
        if page is getattr(self,'settings_page',None):self.settings_page=None
        if page is getattr(self,'motion_dialog',None):self.motion_dialog=None
        if page is getattr(self,'smart_home_page',None):self.smart_home_page=None
        if page is getattr(self,'activity_page',None):self.activity_page=None
        pending=getattr(self,'navigation_pending',None)
        if pending:QTimer.singleShot(0,lambda:self._route_page(*pending))
        elif hasattr(self,'navigation') and self.pages.currentWidget() is self.panel:self.navigation.select('chat')

    def _browser_login(self,provider,finish=False):
        if getattr(self,'browser_login_pending',False):return
        if getattr(self,'browser_retry_pending',False):return
        if self.busy:
            self.set_status('Önce mevcut konuşmanın bitmesini bekle.');return
        self.settings['provider']=provider;save_settings(self.settings)
        if finish:self._giris_izleniyor=False
        self.browser_login_pending=True
        self.web_login_button.setEnabled(False);self.web_finish_button.setEnabled(False)
        self.browser_status_changed.emit('Giriş penceresi kapatılıyor, web sohbeti hazırlanıyor…' if finish else 'Normal tarayıcıda giriş penceresi açılıyor…',True)
        self._work('browser_login',self.assistant.browser_login,finish,provider)

    def _giris_izle(self,provider):
        """Canlı kabul (13 Kasım): giriş penceresi açıkken başlığı izle; giriş bitince 'Giriş tamamlandı'yı Yumi kendisi basar."""
        if getattr(self,'_giris_izleniyor',False) or provider not in ('chatgpt-web','gemini-web'):return
        web=getattr(self.assistant,'web',None)
        if web is None:return
        self._giris_izleniyor=True
        from concurrent.futures import Future
        sonuc=Future()
        def calis():
            try:
                from browser_chat import giris_bekle
                tamam=giris_bekle(web.directory,provider,devam=lambda:getattr(self,'_giris_izleniyor',False) and not self.exiting)
            except Exception as error:
                speech_event(f'giris izleme hatasi: {error}');tamam=None
            sonuc.set_result((provider,tamam));self.results.put(('giris_izle',sonuc))
        threading.Thread(target=calis,name='YumiGirisIzle',daemon=True).start()

    def _apply_web_status(self,value):
        if self.settings.get('provider') not in ('chatgpt-web','gemini-web'):
            if hasattr(self,'web_recovery'):self.web_recovery.setVisible(False)
            return
        from web_connection import WebStatus,status_for
        if not isinstance(value,WebStatus):
            value=status_for(self.settings['provider'],'ready' if value is True else 'unavailable')
        if value.provider!=self.settings['provider']:return
        ready=value.phase=='ready'
        self.web_recovery_text.setText(value.message)
        self.web_recovery.setVisible(not ready)
        self.web_login_button.setEnabled(value.phase!='connecting')
        self.web_finish_button.setEnabled(value.phase=='login_open')
        self.browser_status_changed.emit(value.message,value.phase=='connecting')
        if not self.busy:self.set_status(value.message)
    def _toggle_panel(self):
        showing=self.panel.isVisible(); self.panel.setVisible(not showing); self.resize(self.width(),400 if showing else 690)

    def set_status(self,text):
        self.status.setText(text);self.status.setToolTip(text)
        if hasattr(self,'chat_list'):
            self.chat_list.setEnabled(not self.busy);self.new_chat_button.setEnabled(not self.busy)
            self.delete_chat_button.setEnabled(not self.busy)
            self.chat_list.setToolTip('Sohbet değiştirmek için önce ses oturumunu veya yanıtı durdur.' if self.busy else 'Sohbeti aç')
        self._update_send_button()
        if hasattr(self,'stop_reply_button'):self.stop_reply_button.setVisible(bool(getattr(self,'reply_pending',False)) and self.settings.get('provider') in ('chatgpt-web','gemini-web'))

    def _update_send_button(self,*args):
        from behavior_priority import is_avatar_command
        if hasattr(self,'send_button'):
            local=is_avatar_command(self.input.text())
            self.send_button.setEnabled(local or not self.busy or (not self.reply_pending and (self.speech_active or bool(self.speech_queue) or self.calar.mesgul())))

    def _cancel_reply(self):
        if not self.reply_pending:return
        self.assistant.cancel_reply();self._clear_speech_queue();self.player.stop();self.speech_active=False;self.speech_failed=True
        self.avatar.speaking=False;self.avatar.mouth_level=0.;self.set_status('Yanıt durduruluyor…')
    def show_bubble(self,text,ms=4500):
        self.bubble.hide()
        self.overlay.say(text,ms)
    def _layout_messages(self):
        width=max(80,min(540,int(self.scroll.viewport().width()*.86)))
        for label in self.message_labels:
            label.ensurePolished()
            # ARAYUZ: baloncuk metin kadar genişler (en çok %86); uzun metin sarılır
            fm=label.fontMetrics();dogal=max([fm.horizontalAdvance(line) for line in label.text().split('\n')]+[0])+44
            genislik=max(60,min(width,dogal));label.setFixedWidth(genislik)
            # Fixed height from the previous layout must not become the next
            # heightForWidth minimum (otherwise every transcript tick adds 2px).
            label.setMinimumHeight(0)
            label.setMaximumHeight(16777215)
            label.setFixedHeight(max(36,label.heightForWidth(genislik)+2))
        self.message_layout.invalidate()
        self.message_layout.activate()

    def _save_chat_history(self):
        try:
            self.chat_store.update(self.chat_history)
            self._refresh_chat_list()
        except OSError:
            import logging
            logging.exception('Chat history could not be saved')

    def _load_chat_history(self):
        from chat_store import ChatStore
        self.chat_store=ChatStore(DATA_DIR)
        self._show_selected_chat()

    def _refresh_chat_list(self):
        from ui_shell import gecmis_doldur
        ad=character_name(self.settings) or 'Y'
        gecmis_doldur(self,self.chat_store.chats,self.chat_store.active,self.chat_store.title,ad[:1].upper(),self.chat_store.clock())

    def _show_selected_chat(self):
        for label in self.message_labels:label.hide();self.message_layout.removeWidget(label);label.deleteLater()
        self.message_labels=[];self.chat_history=[m.copy() for m in self.chat_store.current['messages']]
        self.assistant.history=[m.copy() for m in self.chat_history[-24:] if m.get('complete',True)]
        self.assistant.pending_weather=False;self.assistant.weather_city='';self.assistant.weather_tomorrow=False;self.previous_id=None
        self.assistant.chat_scope=self.chat_store.active;self.assistant.chat_urls=self.chat_store.current.setdefault('web_urls',{})
        if hasattr(self,'input'):self.input.clear()
        for item in self.chat_history:self.add_message(item['text'],item['role'],record=False)
        if not self.chat_history:self.add_message('Merhaba! Bana yazabilir veya mikrofonla konuşabilirsin.','assistant',record=False)
        self._refresh_chat_list()
        if hasattr(self,'native_audio'):self._warm_native(force=True)

    def _new_chat(self):
        if self.busy:return
        self._save_chat_history()
        if hasattr(self,'native_transcripts'):self.native_transcripts.new_session()
        self.chat_store.new();self._show_selected_chat()

    def _chat_context_menu(self,position):
        if self.busy:return
        item=self.chat_list.itemAt(position)
        if item is None:return
        key=item.data(Qt.ItemDataRole.UserRole)
        if not key:return
        menu=QMenu(self.chat_list);action=menu.addAction('Sohbeti sil')
        if menu.exec(self.chat_list.viewport().mapToGlobal(position))==action:self._delete_chat(key)

    def _delete_chat(self,key=None):
        if self.busy:return
        item=self.chat_list.currentItem()
        if key is None:key=item.data(Qt.ItemDataRole.UserRole) if item else None
        chat=next((c for c in self.chat_store.chats if c['id']==key),None)
        if chat is None:return
        answer=QMessageBox.question(self,'Sohbeti sil',f'“{self.chat_store.title(chat)}” sohbeti silinsin mi?\nBu bilgisayardaki mesajlar kaldırılacak.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:return
        if hasattr(self,'native_transcripts'):self.native_transcripts.new_session()
        selected=self.chat_store.active
        try:
            if not self.chat_store.delete(key):return
        except OSError:
            self.show_error('Sohbet silinemedi; geçmiş korundu.');return
        if key==selected:self._show_selected_chat()
        else:self._refresh_chat_list()
        self.set_status('Sohbet bu bilgisayardaki geçmişten silindi')

    def _select_chat_item(self,item):
        if self.busy:return
        key=item.data(Qt.ItemDataRole.UserRole)
        if not key:return
        from ui_shell import sohbet_goster
        sohbet_goster(self)
        if key==self.chat_store.active:return
        self._save_chat_history()
        if hasattr(self,'native_transcripts'):self.native_transcripts.new_session()
        if self.chat_store.select(key):self._show_selected_chat()

    def _expire_chats(self):
        # Never remove the selected conversation while audio/text is in flight.
        if self.busy:return
        active=self.chat_store.active
        from chat_store import RETENTION
        if self.chat_store.clock()-self.chat_store.current['updated_at']>RETENTION and hasattr(self,'native_transcripts'):self.native_transcripts.new_session()
        if self.chat_store.prune():
            if not any(c['id']==active for c in self.chat_store.chats):
                if self.chat_store.chats:self.chat_store.active=self.chat_store.chats[0]['id']
                else:self.chat_store.new(save=False)
                self._show_selected_chat()
            self.chat_store.save();self._refresh_chat_list()

    def add_message(self,text,role,record=True):
        if record and role in ('user','assistant'):
            self.chat_history.append({'role':role,'text':text})
        label=QLabel(text); label.setWordWrap(True); label.setProperty('role',role)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.message_labels.append(label)
        index=self.message_layout.count()-1
        self.message_layout.insertWidget(index,label,0,Qt.AlignmentFlag.AlignLeft if role!='user' else Qt.AlignmentFlag.AlignRight)
        def refresh():
            self._layout_messages()
            QTimer.singleShot(0,lambda:self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        QTimer.singleShot(0,refresh)
        return label
    def show_error(self,text): self.add_message(text,'error'); self.show_bubble(text,9000); self.set_status('Hata')

    def _work(self,kind,function,*args):
        executor=self.chat_executor if kind in ('answer','stream_answer','transcribe') else self.executor
        future=executor.submit(function,*args)
        future.add_done_callback(lambda result:self.results.put((kind,result)))

    def _send(self):
        text=self.input.text().strip()[:4000]  # 19 Kas (zorlama testi): üst sınır; yapıştırma/programatik metin de kesilir
        if not text or self.exiting:return  # 19 Kas gözlem: kapanış başladıysa yeni iş yok (havuzlar kapalı)
        if self.busy:
            from behavior_priority import is_avatar_command
            if is_avatar_command(text):
                result=self._local_command(text)
                if result:
                    self.input.clear();self.add_message(text,'user');self.add_message(result,'assistant')
                    self._save_chat_history();self.show_bubble(result)
                    return
            if self.reply_pending or not (self.speech_active or self.speech_queue or self.calar.mesgul()):return
            self._clear_speech_queue();self.player.stop();self.speech_active=False;self.busy=False
            self.avatar.speaking=False;self.avatar.mouth_level=0.
        self.input.clear(); self.add_message(text,'user'); self._save_chat_history()
        tur_kaydi.yeni('yazi',karakter=character_name(self.settings),ses=self.settings.get('speech_voice'),saglayici=self.settings.get('provider'))
        self._tur_kaynak='yazi'  # SC1: "yalnız sesli konuşunca" ayarı için tur kaynağı
        self._ask(text)
    def _local_command(self,text):
        command=text.lower().strip(' !?.')
        if command in ('akıllı ev','akıllı evi aç','akıllı ev menüsü','akıllı ev menüsünü aç','akıllı ev panelini aç','cihazları göster','akıllı cihazlar','odaları göster'):
            self._open_smart_home();return 'Akıllı ev ve cihazlar panelini açıyorum.'
        if getattr(self,'skill_dispatcher',None):
            skill_res=self.skill_dispatcher.dispatch(text)
            if skill_res:return skill_res
        from modelsiz import komut_cevabi
        modelsiz_cevap=komut_cevabi(self,command)  # C05: model gizliyken modele dönük komut
        if modelsiz_cevap is not None:return modelsiz_cevap
        from voice_actions import execute
        action=execute(self,command)
        if action is not None:return action
        if command in ('dans et','hadi dans et'):
            path=Path(__file__).resolve().parents[1]/'motions/quaternius-Dance_Loop.vrma'
            if not path.exists():return 'Dans animasyonu bulunamadı.'
            try:self._play_motion(path)
            except (ValueError,OSError) as error:return str(error)
            return 'Dans ediyorum.'
        if command in ('dansı durdur','dans etmeyi bırak','hareketi durdur'):
            self.manual_pose='idle';self.manual_pose_end=time.perf_counter()+3
            return 'Hareketi durdurdum.'
        if command in ('uyu','yatağa git','yat uyu','bilgisayara otur','çalışmaya başla','oyun oyna'):
            return 'Bu davranış şu anda kullanıma açık değil.'
        if command in ('el salla','merhaba de'):
            self._wave();return 'Merhaba!'
        if command in ('büyü','küçül','biraz büyü','biraz küçül'):
            self.settings['size']=max(50,min(180,self.settings['size']+(20 if 'büyü' in command else -20)))
            self.settings.setdefault('voice_profiles',{})[self.settings['skin']]={**profile(self.settings),'size':self.settings['size']}
            self.overlay.set_scale(self.settings['size']);save_settings(self.settings);return 'Boyutumu değiştirdim.'
        if command in ('gizlen','saklan'):
            from model_visibility import set_visible
            set_visible(self,False);self.hide();return 'Tekrar çağırana kadar gizleniyorum.'
        if command in ('görün','geri gel'):
            from model_visibility import set_visible
            set_visible(self,True);return 'Buradayım!'
        return None


    def _cilve_motoru(self):
        """Seçili karakterin kişiliği + kullanıcının kişilik seviyesi (sade/dengeli/cilveli). Karakter ya da ayar değişince yenilenir."""
        anahtar=(character_name(self.settings),self.settings.get('kisilik_seviyesi','dengeli'))
        if getattr(self,'_cilve_anahtar',None)!=anahtar:
            from karakter_kisilik import Cilve,karakter_kisiligi
            self._cilve=Cilve(karakter_kisiligi(anahtar[0]),anahtar[1]);self._cilve_anahtar=anahtar
        return self._cilve

    def _kisilik_hareket(self,ad):
        """Kişilik dosyasındaki hareket adını avatar tepkisine çevirir; bilinmeyen ad yok sayılır."""
        if not ad or modelsiz_acik(self):return
        now=time.perf_counter()
        if ad=='el_salla':self._wave();return
        niyet={'basparmak':'agree','mutlu':'agree','soru':'question','uzgun':'uncertain','sasir':'warning','acikla':'explain'}.get(ad)
        if not niyet:return
        for view in (self.avatar,self.overlay.avatar):
            if view.model:view.model.skill_reaction=(now,niyet)
        scene=self.overlay.avatar.furniture or self.avatar.furniture
        if ad=='basparmak' and not scene and not self.avatar.hand_gesture:
            self.avatar.hand_gesture='thumbs_up';self.gesture_until=now+2.2;self.overlay.sync()

    def _yerel_ai(self,text):
        """B08: niyet modeli + yerel işleyiciler (hesap, saat/tarih, sayaç, alarm, hatırlatıcı, kronometre, zar). None -> eski yol."""
        router=getattr(self,'yonlendirici',None)
        if router is None:return None
        if not getattr(router,'karakter_adlari',None):
            # Tüm karakter adları ve okunuşları: ek almamış çıplak ad hava durumunda şehir sayılmaz
            from wake_names import aliases
            from character_names import NAMES
            adlar=set()
            for tam in [*NAMES.values(),'Yumi']:  # G-A2: programın adı modelsizken de şehir sayılmaz
                for ad in (tam,tam.split()[0]):adlar.update(a.casefold() for a in (ad,*aliases(ad)) if a)
            router.karakter_adlari=adlar
        t=time.perf_counter()
        try:yanit=router.isle(text)
        except Exception as error:
            speech_event(f'niyet hatasi: {type(error).__name__}: {error}');return None
        r=router.son or {}
        if getattr(router,'son_hareket',None):self._kisilik_hareket(router.son_hareket)
        if getattr(self,'muzik_duraklatici',None) and self.muzik_duraklatici.bekliyor:self._muzik_niyet=r.get('niyet')
        speech_event(f"niyet {r.get('niyet','-')} {r.get('guven',0):.2f} {'yerel' if yanit else 'gec'} {(time.perf_counter()-t)*1000:.1f}ms")
        tur_kaydi.olay('niyet',niyet=r.get('niyet'),guven=round(float(r.get('guven',0) or 0),3),
                       parcalar=[{'tur':p.get('tur'),'metin':p.get('metin')} for p in r.get('parcalar',[]) or []],
                       takip=bool(r.get('takip')),karar='yerel' if yanit else 'gec',
                       yanit=yanit if isinstance(yanit,str) else (getattr(yanit,'onsoz',None) or ('arka_is' if callable(yanit) else None)),
                       ms_model=round((time.perf_counter()-t)*1000,1))
        return yanit

    def _muzik_duraklat(self):
        """Seslenince/mikrofon açılınca çalan müziği duraklat (arka planda; arayüzü bekletmez)."""
        d=getattr(self,'muzik_duraklatici',None)
        if not d or d.bekliyor:return
        calıyor=getattr(getattr(self,'media_activity',None),'state',{}).get('playing')
        if calıyor is False:return
        self._muzik_niyet=None;self._bos_basladi=0.
        threading.Thread(target=d.seslenince,name='YumiMuzikDuraklat',daemon=True).start()

    def _muzik_devam_kontrol(self):
        """Yumi dinlemeyi ve cevabı bitirip 1 s boşta kalınca, kendi duraklattığı müziği devam ettirir."""
        d=getattr(self,'muzik_duraklatici',None)
        if not d or not d.bekliyor:return
        vc=self.voice_capture
        dinliyor=vc.manual or time.perf_counter()<vc.wake_armed_until or bool(vc.recording)
        if self.busy or dinliyor or time.monotonic()-d.duraklatildi_t<2.0:
            self._bos_basladi=0.;return
        if not self._bos_basladi:
            self._bos_basladi=time.monotonic();return
        if time.monotonic()-self._bos_basladi<1.0:return
        self._bos_basladi=0.
        niyet=self._muzik_niyet
        threading.Thread(target=d.tur_bitti,args=(niyet,),name='YumiMuzikDevam',daemon=True).start()

    def _saat_denetle(self):
        def run():
            try:
                from yerel_ai.saat_denetim import denetle
                router=getattr(self,'yonlendirici',None)
                koord=None
                if router and router.hava.varsayilan:
                    from yerel_ai.sayi_zaman import kucuk;koord=router.hava.kayit.get('sehirler',{}).get(kucuk(router.hava.varsayilan))
                uyari=denetle(koord)
                if uyari:self.results.put(('saat_uyari',uyari))
            except Exception as error:
                speech_event(f'saat denetimi hatasi: {error}')
        threading.Thread(target=run,name='YumiSaatDenetim',daemon=True).start()

    def _uretim_suruyor(self):
        """Çalarda sesi henüz üretilmemiş bölüm var mı (B07: ağır işleri bunun bitmesine ertelemek için)."""
        calar=getattr(self,'calar',None)
        if calar is None:return False
        try:
            with calar._kilit:return any(not b.bitti for b in calar._bolumler)
        except Exception:return False

    def _yerel_arka(self,text,is_):
        """İnternet gereken yerel yanıt (hava, döviz): arayüzü dondurmadan arka planda; sonuç skill_answer yolundan söylenir."""
        self.busy=True;self.voice_capture.suspended=True
        self.active_skill_requests=getattr(self,'active_skill_requests',0)+1
        self.set_status('Bakıyorum…')
        def run():
            try:return text,is_()
            except Exception as error:return text,f'Buna bakarken bir sorun oldu: {error}'
        self._work('skill_answer',run)

    def _ask(self,text):
        if self.busy: return
        speech_event(f'soru gonderildi ({len(text)} kr)');self._first_text_logged=False
        tur_kaydi.olay('soru',metin=text)
        self.speech_failed=False
        self.assistant.begin_reply()
        local=self._yerel_ai(text)
        if getattr(local,'onsoz',None):  # ör. müzik: hemen "X açılıyor", iş arka planda; başarı sessiz, hata sesli
            self.busy=True;self.voice_capture.suspended=True;self.add_message(local.onsoz,'assistant');self.show_bubble(local.onsoz)
            self.assistant._remember(text,local.onsoz);self._save_chat_history();self._speak(local.onsoz)
            # B07 (12 Kasım): medya (YouTube/Spotify) açılışı ekran kartını/işlemciyi meşgul edip ön sözün üretimini
            # 7–13 s'ye uzatıyordu (ses-akis.log 13:18, 11 Kasım 13:51) → iş, ön sözün sesi üretilince (en çok 4 s) başlar.
            def onsoz_sonra(is_=local):
                t=time.monotonic();time.sleep(.3)
                while time.monotonic()-t<4 and self._uretim_suruyor():time.sleep(.05)
                return is_()
            self._work('yerel_sonuc',onsoz_sonra);return
        if callable(local):self._yerel_arka(text,local);return
        text=getattr(getattr(self,'yonlendirici',None),'yeni_metin',None) or text  # öğretilen ifade: eski yola komutun kendisi gider
        web_zorla=(getattr(getattr(self,'yonlendirici',None),'son',None) or {}).get('niyet')=='web_zorla'  # "Gemini'ye sor …"
        if web_zorla:speech_event('web_zorla: soru dogrudan web saglayicisina')
        if not web_zorla and local is None and self._start_skill_command(text):return
        local=None if web_zorla else (local or self._local_command(text))
        if local:
            tur_kaydi.olay('cevap',kaynak='yerel',metin=local)
            self.busy=True;self.voice_capture.suspended=True;self.add_message(local,'assistant');self.show_bubble(local)
            self.assistant._remember(text,local)
            self._save_chat_history()
            self._speak(local)
            return
        self.busy=True; self.reply_pending=True; self.voice_capture.suspended=True; self.set_status('Düşünüyor…')
        self.streaming_label = self.add_message('…', 'assistant',record=False)
        self.streaming_text = ''
        self.streaming_speech_offset = 0
        def on_chunk(chunk):
            self.results.put(('stream_chunk', chunk))
        def on_status(status):
            self.results.put(('connection_state',status))
        def runner():
            key = self.api_key
            return self.assistant.stream_ask(text, key, self.previous_id, on_chunk=on_chunk,on_status=on_status)
        self._work('stream_answer', runner)
    def _stream_voice(self,selected):
        """B07: bu ses kesintisiz çalar yolundan mı gider (ONNX RVC ya da XTTS)?"""
        if selected not in self.stream_voice_ok:
            # Tüm RVC sesleri (ONNX'i olmayan Applio sesleri dahil) ve XTTS kesintisiz çalardan:
            # sessizlik kırpma + doğal durak. Hız için ONNX: work/kuyruk/is_004 (models/onnx/<ad>.onnx).
            ok=selected.startswith(('xtts:','rvc:','api:'))  # SC2: API sesi de kesintisiz çalardan
            self.stream_voice_ok[selected]=ok
        # internet yok mesajını bu sesle önceden hazırla (internet varken), sonra çevrimdışı da çalar.
        # SC1/SC2: sessizde ve API sesinde XTTS başlatılmaz → hazırlık XTTS gerekince yapılır.
        hazir=self.__dict__.setdefault('_cevrimdisi_hazir',set())
        if selected.startswith(('xtts:','rvc:')) and selected not in hazir:
            import ses_cikisi
            if ses_cikisi.xtts_gerekli(self):
                hazir.add(selected);self.speech_executor.submit(prepare_offline_warning,DATA_DIR,selected)
        return self.stream_voice_ok[selected] and self.calar.hazir()

    def _produce_segment(self,segment,text,voice):
        """Arka planda bir konuşma bölümünü doldurur; XTTS parça parça, RVC tek seferde."""
        if segment.iptal:return
        from ses_motoru.akis import wav_oku
        try:
            if voice.startswith('xtts:'):
                from xtts_speech import stream
                ilk=[True]
                def ekle(pcm,sr):
                    if ilk[0]:ilk[0]=False;speech_event(f'bolum {segment.kimlik} ilk parca')
                    segment.ekle(pcm,sr)
                stream(text,voice,ekle)
            elif voice.startswith('api:'):  # SC2: modelsiz API sesi (ElevenLabs …)
                import api_ses
                ilk=[True]
                def ekle(pcm,sr):
                    if ilk[0]:ilk[0]=False;speech_event(f'bolum {segment.kimlik} ilk parca (api)')
                    segment.ekle(pcm,sr)
                api_ses.stream(text,voice,ekle)
            else:
                raise RuntimeError(f'Desteklenmeyen ses: {voice}')  # 12 Kasım: RVC/Applio kaldırıldı, yalnız XTTS
            segment.bitir()
            # B07 tanı (12 Kasım): üretilen ses süresi, oluşmadan bu yana geçen süre, ilk parçadan sonraki üretim hızı
            speech_event(f'bolum {segment.kimlik} uretim bitti ses={segment.toplam/segment.sr:.2f}s sure={time.perf_counter()-segment.olusma_t:.2f}s hiz={segment.uretim_hizi or 0:.2f}')
        except Exception as error:
            if segment.iptal:return
            speech_event(f'bolum {segment.kimlik} HATA {error}')
            __import__('logging').getLogger('yumi.speech').warning('Ses bölümü üretilemedi (%s): %s',voice,error)
            if voice.startswith('api:'):  # SC2 dikkat 1: API olmazsa yerel sese düşülmez; cevap yazılı kalır + uyarı
                segment.bitir(hata=str(error));self.results.put(('speech_warning','API sesi: '+str(error)));return
            # Kullanıcı kuralı: yalnız seçili karakter sesi. Yedek ses yok; aynı sesle bir kez yeniden dene, olmazsa cümleyi atla.
            try:
                if segment.toplam==0 and not segment.iptal:
                    if voice.startswith('xtts:'):
                        from xtts_speech import stream
                        stream(text,voice,segment.ekle)
                    else:
                        raise RuntimeError(f'Desteklenmeyen ses: {voice}')
                    segment.bitir();speech_event(f'bolum {segment.kimlik} yeniden denemede uretildi');return
            except Exception as retry:
                error=f'{error}; yeniden deneme: {retry}'
            segment.bitir(hata=str(error))
            self.results.put(('speech_warning',str(error)))

    def _produce_offline(self,segment,voice):
        """İnternet yok mesajı: karakter sesiyle önceden saklanan kayıt (data/ses_onbellek)."""
        from ses_motoru.akis import wav_oku
        try:
            samples,rate=wav_oku(offline_warning_speech(DATA_DIR,voice));segment.ekle(samples,rate);segment.bitir()
        except Exception as error:
            segment.bitir(hata=str(error));self.results.put(('speech_warning',f'internet yok mesajı hazır değil: {error}'))

    def _speak(self,text,voice=None,openai_voice=None,pause=None,bildirim=False):
        if not text.strip():return
        import ses_cikisi
        if not ses_cikisi.sesli_mi(self,bildirim):  # SC1: sessiz / yazıyla sorulan tur → yalnız yazılı cevap
            speech_event(f'sesli cevap kapali ({ses_cikisi.mod(self)}, tur={getattr(self,"_tur_kaynak","-")})');self._finish_turn();return
        self._son_soylenen=text  # 18 Kas: tur sonunda son cümle soru mu diye bakılır (takip dinleme)
        selected=ses_cikisi.etkin_ses(self,voice or self.settings['speech_voice'])  # SC2: modelsiz + API → API sesi
        from modelsiz import ses_kurulu,SES_YOK_YAZISI
        if not ses_kurulu(self,selected):  # C05: hiç model yokken ses dosyası yok → yazılı cevap, açık ileti
            speech_event(f'ses kurulu degil {selected}');self._finish_turn();self.set_status(SES_YOK_YAZISI)
            if not getattr(self,'_ses_yok_bildirildi',False):self._ses_yok_bildirildi=True;self.add_message(SES_YOK_YAZISI,'error',record=False)
            return
        if not selected.startswith(('rvc:','xtts:','api:')):
            self._finish_turn();return
        if text.strip()==OFFLINE_MESSAGE and selected.startswith('api:'):  # internet yok: API sesi de çalışmaz
            self._finish_turn();return
        if text.strip()==OFFLINE_MESSAGE and self._stream_voice(selected):
            segment=self.calar.yeni_bolum(OFFLINE_MESSAGE,0.0)
            self.speech_executor.submit(self._produce_offline,segment,selected);self.active_speech_voice=selected
            return
        if self._stream_voice(selected):
            from ses_motoru.akis import bolumle,temizle
            parts=[(text,pause)] if pause is not None else bolumle(text,ilk=not self.calar.mesgul(),final=True)[0]
            for part,gap in parts:
                part=temizle(part).strip()
                if not part:continue
                segment=self.calar.yeni_bolum(part,gap,getattr(text,'boundaries',()))
                speech_event(f'bolum {segment.kimlik} olustu: {part[:40]!r}')
                self.speech_executor.submit(self._produce_segment,segment,part,selected)
            self.active_speech_voice=selected
            return
        from rvc_speech import speech_parts
        parts=speech_parts(text) if selected.startswith('xtts:') else [text]
        for part in parts:
            prepared=self.executor.submit(local_speech,part,DATA_DIR,selected)
            self.speech_queue.append((part,selected,openai_voice,prepared))
        self._start_next_speech()

    def _start_next_speech(self):
        if self.speech_active:return
        if not self.speech_queue:
            self._finish_turn();return
        text,selected,openai_voice,prepared=self.speech_queue.popleft()
        self.speech_active=True
        self.active_speech_voice=selected
        self.active_speech_text=text
        if selected=='browser-voice':
            def play_browser():
                if not self.assistant.web:raise RuntimeError('Web sohbeti açık değil.')
                self.assistant.web.read_aloud(lambda:self.results.put(('browser_voice_started',text)))
            self._work('browser_voice',play_browser);return
        label=next((title for title,key,_ in VOICES if key==selected),selected)
        self.set_status(f'Ses hazırlanıyor · {label}…')
        epoch=self.speech_epoch
        prepared.add_done_callback(lambda result:self.results.put(('speech_ready',(result,epoch))))

    def _clear_speech_queue(self):
        self.speech_epoch+=1
        self.calar.durdur()
        for _,_,_,prepared in self.speech_queue:
            if prepared is not None:prepared.cancel()
        self.speech_queue.clear()

    def _queue_stream_speech(self,final=False):
        if getattr(self,'speech_failed',False):return
        if self.settings['speech_voice']=='browser-voice':
            if final and self.streaming_text.strip():self._speak(self.streaming_text)
            return
        remaining=self.streaming_text[self.streaming_speech_offset:]
        if self._stream_voice(self.settings['speech_voice']):
            # B07: doğal sınırlardan böl; ilk bölüm kısa (hızlı başlangıç), duraklar noktalamadan
            from ses_motoru.akis import bolumle
            from ses_motoru.akis import ACLIK_ESIGI_S
            starving=self.streaming_speech_offset>0 and self.calar.kalan_s()<ACLIK_ESIGI_S
            parts,used=bolumle(remaining,ilk=self.streaming_speech_offset==0,final=final,aclik=starving)
            self.streaming_speech_offset+=used
            for text,gap in parts:self._speak(text,pause=gap)
            return
        import re
        end=len(remaining) if final else 0
        if not final:
            for match in re.finditer(r'(?<!\d)[.!?](?:\s+)',remaining):end=match.end()
        if end:
            text=remaining[:end].strip()
            self.streaming_speech_offset+=end
            if text:self._speak(text)

    def _finish_turn(self):
        if getattr(self,'active_skill_requests',0):return
        if self.reply_pending or self.speech_active or self.speech_queue or self.calar.mesgul():return
        if getattr(self,'site_voice_fallback',False):
            self.site_voice_fallback=False
            text=getattr(self,'streaming_text','').strip()
            if text:
                self.set_status('Microsoft sesi kullanılamıyor; sitenin sesiyle okunuyor…')
                self._speak(text,voice='browser-voice');return
        self.busy=False;self.voice_capture.suspended=False
        tur_kaydi.olay('tur_bitti')
        self.set_status(self._bos_durum())
        if hasattr(self,'voice_capture'):self._sync_name_wake()
        son=(getattr(self,'_son_soylenen','') or '').strip();self._son_soylenen=''
        soru=son.rstrip(' "\'”’»)').endswith('?')  # 18 Kas (kullanıcı): Yumi soru sorduysa cevabı adsız dinle
        if getattr(self,'_dinle_konusma_sonra',False) or soru:
            self._dinle_konusma_sonra=False
            speech_event(f'takip dinleme {TAKIP_DINLEME_S}s ({"soru" if soru else "anlayamadim"})')
            self.voice_capture.arm_next_utterance(TAKIP_DINLEME_S);self.manual_pose='listen';self.manual_pose_end=time.perf_counter()+TAKIP_DINLEME_S+.5

    def _bos_durum(self):
        if getattr(self,'ses_hazirlaniyor',False):return 'Ses hazırlanıyor… (ilk cevabın sesi biraz gecikebilir)'
        return f'“{character_name(self.settings)}” diye seslen' if self.voice_capture.always else 'Hazır'

    def _ses_hazirla(self,voice):
        """Seçili sesi arka planda hazırla (model yükleme + GPU çekirdekleri); süre boyunca durum satırında göster."""
        if getattr(self,'exiting',False):return  # 19 Kas gözlem: kapanıştan sonra _tick ısıtma göndermesin ("cannot schedule new futures")
        def is_():
            self.results.put(('ses_hazirlik','basladi'));speech_event(f'isitma basladi {voice}')
            try:warm_speech(voice,DATA_DIR)
            finally:self.results.put(('ses_hazirlik','bitti'))
        self._isinmis_ses=voice
        import ses_cikisi
        if not ses_cikisi.xtts_gerekli(self):  # SC1/SC2: sessiz ya da API sesi → XTTS'i kapat, ısıtma yok
            if ses_cikisi.xtts_kapat():speech_event('xtts kapatildi (sessiz/api)')
            return
        if not voice.startswith(('xtts:','rvc:')):return
        from modelsiz import ses_kurulu
        if not ses_kurulu(self,voice):return  # C05: dosyası olmayan sesi ısıtma
        if getattr(self,'busy',False):  # B10: konuşma sürerken ısınma ses kuyruğunu tıkamasın; tur bitince dene
            QTimer.singleShot(2000,lambda:self._ses_hazirla(voice) if voice==self.settings.get('speech_voice') else None);return
        self.executor.submit(is_)

    def _media_status_changed(self,status):
        if status==QMediaPlayer.MediaStatus.EndOfMedia:
            self.speech_active=False
            self._start_next_speech()

    def _playback_error(self,*args):
        self.speech_active=False;self._clear_speech_queue()
        self.speech_failed=True
        self.show_error('Ses dosyası oynatılamadı: '+self.player.errorString())
        self._finish_turn()

    def _audio_complete(self,samples,requires_wake):
        if self.busy:return
        self._set_microphone_button(False)
        self._requires_wake=requires_wake;self._son_wake_hit=bool(getattr(self.voice_capture,'son_wake_hit',False));self.busy=True;self.voice_capture.suspended=True
        if self._son_wake_hit or getattr(self.voice_capture,'son_armed',False):self._bip(son=True)  # Alexa gibi: dinleme bitti, komut alındı
        vc=self.voice_capture;son=getattr(vc,'son_ses_t',None)
        meta=dict(konusma_s=round(len(samples)/16000,2),uyandirma_gerekli=bool(requires_wake),
                  soz_sonu_bekleme_s=round(time.perf_counter()-son,2) if son else None,soz_sonu_esik_s=SOZ_SONU_S,
                  ses=self.settings.get('speech_voice'),karakter=character_name(self.settings),saglayici=self.settings.get('provider'))
        if requires_wake:
            # B06: beklemede duyulan her söz yazıya çevrilir ama ad tanınmazsa hiçbir yere kaydedilmez (ortam konuşması).
            self._bekleyen_tur=(son,meta,time.perf_counter())
        else:
            tur_kaydi.yeni('ses',t0=son,**meta);tur_kaydi.olay('stt_basladi')
            self.set_status('Konuşman metne çevriliyor…')
        self._work('transcribe',local_transcribe,samples,character_name(self.settings))
    def _web_bekci(self):
        """B03: Yumi boştayken web oturumunu 20 s'de bir denetler; kopmuşsa kullanıcı müdahalesiz baştan kurar
        (hazır olmadıkça aralık 20→300 s artar). Konuşma, giriş penceresi ya da başka bağlantı denemesi sürerken dokunmaz."""
        if self.settings.get('provider') not in ('chatgpt-web','gemini-web') or getattr(self.assistant,'web',None) is None:return
        if self.busy or self.exiting or getattr(self,'web_bekci_calisiyor',False):return
        if getattr(self,'browser_retry_pending',False) or getattr(self,'browser_login_pending',False) or getattr(self,'reply_pending',False):return
        if time.monotonic()<getattr(self,'web_bekci_sonraki',0.):return
        self.web_bekci_calisiyor=True;self.web_bekci_sonraki=time.monotonic()+getattr(self,'web_bekci_aralik',20.)
        future=self.executor.submit(self.assistant.check_browser,self.settings['provider'])
        future.add_done_callback(lambda f:self.results.put(('browser_check',f)))

    def _retry_browser(self):
        if self.settings.get('provider') not in ('chatgpt-web','gemini-web'):
            if hasattr(self,'web_recovery'):self.web_recovery.setVisible(False)
            return
        if self.busy or self.exiting or getattr(self,'browser_retry_pending',False) or getattr(self,'browser_login_pending',False):return
        self.browser_retry_pending=True;self.web_retry_button.setEnabled(False)
        from web_connection import status_for
        self._apply_web_status(status_for(self.settings['provider'],'connecting'))
        self._work('browser_warm',self.assistant.warm_browser,self.settings['provider'])
    def _read_results(self):
        while True:
            try: kind,item=self.results.get_nowait()
            except queue.Empty: break
            if kind=='speech_ready':
                item,epoch=item
                if epoch!=self.speech_epoch:continue
                kind='speech'
            if kind=='wake_partial':
                try:ok=item.result()
                except Exception:ok=False
                vc=self.voice_capture
                if ok and vc.had_speech and not vc.wake_hit and not self.busy:
                    vc.wake_hit=True;self._bip();self._muzik_duraklat();self.set_status('🎙 Seni dinliyorum…')
                    self.manual_pose='listen';self.manual_pose_end=time.perf_counter()+8
                    speech_event('uyandirma erken (soz surerken)')
                continue
            if kind=='canli_yazi':
                try:metin=item.result() or ''
                except Exception:metin=''
                if self.voice_capture.had_speech and not self.busy and metin:
                    try:
                        from stt_duzelt import duzelt as _stt_duzelt;metin=_stt_duzelt(metin)
                    except Exception:pass
                    from ui_shell import canli_yazi;canli_yazi(self,metin)
                continue
            if kind=='connection_state':
                if self.reply_pending:self.set_status(item)
                continue
            if kind=='ses_hazirlik':
                self.ses_hazirlaniyor=item=='basladi'
                if not self.busy:self.set_status(self._bos_durum())
                continue
            if kind=='stream_chunk':
                chunk=item
                if getattr(self,'streaming_label',None):
                    self.streaming_text=(self.streaming_text or '')+chunk
                    if not getattr(self,'_first_text_logged',True):self._first_text_logged=True;speech_event('ilk metin geldi');tur_kaydi.olay('ilk_metin')
                    self.streaming_label.setText(self.streaming_text)
                    self._layout_messages()
                    self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
                    self._queue_stream_speech()
                continue
            if kind=='speech_warning':
                if str(item).startswith('API sesi: '):  # SC2: cevap yazılı kaldı; uyarı tur başına bir kez sohbete de yazılır
                    self.set_status(str(item)+' · cevap yazılı gösterildi.')
                    if time.monotonic()-getattr(self,'_api_uyari_t',-99)>20:  # aynı cevabın her cümlesi için ayrı satır yazma
                        self._api_uyari_t=time.monotonic();self.add_message(str(item)+' Cevap yazılı gösterildi.','error',record=False)
                    continue
                self.set_status('Karakter sesi bir cümlede üretilemedi; o cümle atlandı.');continue
            if kind in ('saat_uyari','yerel_bildirim'):
                self.add_message(item,'assistant');self.show_bubble(item,9000);self._save_chat_history();continue
            if kind=='browser_voice_started':
                self.avatar.conversation.begin(item);self.browser_voice_start=time.perf_counter();self.avatar.speaking=True
                self.set_status('Site sesiyle konuşuyor…');continue
            if kind=='browser_check':  # B03 bekçi: boştayken web oturumu denetimi (meşgulse None)
                self.web_bekci_calisiyor=False
                try:durum=item.result()
                except Exception as error:
                    durum=getattr(error,'status',None);speech_event(f'web bekci hatasi: {type(error).__name__}')
                if durum is None:continue
                if getattr(durum,'phase','')=='ready':self.web_bekci_aralik=20.
                else:self.web_bekci_aralik=min(300.,max(20.,getattr(self,'web_bekci_aralik',20.)*2))
                self.web_bekci_sonraki=time.monotonic()+self.web_bekci_aralik
                if not self.busy:self._apply_web_status(durum)
                continue
            future=item
            try: value=future.result()
            except Exception as error:
                __import__('logging').getLogger('yumi.tasks').error('Task failed: %s (%s)',kind,type(error).__name__)
                if kind in ('answer','stream_answer'):self.web_bekci_sonraki=0.  # B03: hatalı turdan sonra bekçi hemen denetlesin
                if kind=='skill_answer':self.active_skill_requests=max(0,getattr(self,'active_skill_requests',0)-1)
                if kind=='browser_login':
                    self.browser_login_pending=False
                    self._apply_web_status(getattr(error,'status',None));continue
                if kind=='browser_warm':
                    self.browser_retry_pending=False;self.web_retry_button.setEnabled(True)
                    self._apply_web_status(getattr(error,'status',None))
                    continue
                if kind in ('answer','stream_answer') and is_offline_error(error):
                    value=(OFFLINE_MESSAGE,self.previous_id)
                else:
                    if kind in ('answer','stream_answer'):
                        self.reply_pending=False
                        if getattr(error,'retry_text',None) and not self.input.text():
                            self.input.setText(error.retry_text)
                        if getattr(self,'streaming_label',None):
                            partial=getattr(self,'streaming_text','').strip()
                            if partial:self.streaming_label.setText(partial)
                            else:
                                self.streaming_label.hide();self.message_layout.removeWidget(self.streaming_label)
                                if self.streaming_label in self.message_labels:self.message_labels.remove(self.streaming_label)
                                self.streaming_label.deleteLater()
                            self._layout_messages()
                            if partial:
                                self.chat_history.append({'role':'assistant','text':partial,'complete':False})
                                self._save_chat_history()
                        self.streaming_label=None
                    elif kind in ('speech','browser_voice'):
                        self.avatar.speaking=False;self.avatar.mouth_level=0.;self.browser_voice_start=None
                        self.speech_active=False;self._clear_speech_queue()
                        self.streaming_speech_offset=len(getattr(self,'streaming_text',''))
                        self.speech_failed=True
                    else:self.busy=False;self.voice_capture.suspended=False
                    if kind=='speech' and not str(getattr(self,'active_speech_voice','')).startswith('rvc:') and '403' in str(error) and self.settings.get('provider') in ('chatgpt-web','gemini-web'):
                        self.site_voice_fallback=True
                        self.set_status('Microsoft sesi reddetti; yanıt sitenin sesiyle okunacak.')
                    elif hasattr(error,'status'):self._apply_web_status(error.status)
                    else:self.show_error(str(error))
                    if getattr(error,'retry_text',None):self.web_recovery.show()
                    self._finish_turn();continue
            if kind=='yerel_sonuc':
                metin,sesli=value
                tur_kaydi.olay('cevap',kaynak='yerel_sonuc',metin=metin,sesli=bool(sesli))
                self.add_message(metin,'assistant');self._save_chat_history()
                if sesli:
                    self.show_bubble(metin);self.busy=True;self.voice_capture.suspended=True;self._speak(metin)
                else:self.set_status(metin)
                continue
            if kind in ('skill_answer','skill_native'):
                if kind=='skill_answer':self.active_skill_requests=max(0,getattr(self,'active_skill_requests',0)-1)
                text,message=value
                tur_kaydi.olay('cevap',kaynak='yerel_'+kind,metin=message)
                self.add_message(message,'assistant');self.show_bubble(message)
                self.assistant._remember(text,message);self._save_chat_history()
                if kind=='skill_answer':self._speak(message)
                self._speak_skill_result(message)
                continue
            if kind=='login':
                self.add_message(value,'assistant'); self.show_bubble(value); self.set_status('Giriş durumu güncellendi')
            elif kind=='transcribe':
                self.busy=False
                from stt_duzelt import duzelt as _stt_duzelt  # B11: Whisper uydurmaları ("Altyazı M.K.") ve "fikre"→"fıkra"
                ham=value.strip();value=_stt_duzelt(ham)
                if ham and not value:speech_event(f'stt uydurma atildi ({len(ham.split())} kelime)')
                text=value.strip();self._tur_kaynak='ses'  # SC1: mikrofondan gelen tur
                import stt_worker
                recognized=False
                if self._requires_wake:
                    recognized,text=wake_command(text,character_name(self.settings))
                    if not recognized and getattr(self,'_son_wake_hit',False):recognized,text=True,ad_artigini_ayikla(value.strip(),character_name(self.settings))  # erken denetim adı duydu; kesik ad artığı atılır
                    if recognized and not getattr(self,'_son_wake_hit',False):self._bip()
                    if not recognized:
                        from wake_names import ses_anahtari
                        ilk=next(iter(value.split()),'');speech_event(f"uyandirma yok ({len(value.split())} kelime, ilk okunus: {ses_anahtari(ilk.strip(',.!?')) if ilk else '-'})")
                    if recognized:
                        son,meta,stt_t=getattr(self,'_bekleyen_tur',(None,{},None))
                        tur_kaydi.yeni('ses',t0=son,**meta)
                        tur_kaydi.olay('stt',metin=value.strip(),model=stt_worker.son_motor,ms_stt=round((time.perf_counter()-stt_t)*1000) if stt_t else None)
                        tur_kaydi.olay('uyandirma',taninan=True,komut=text)
                else:tur_kaydi.olay('stt',metin=text,model=stt_worker.son_motor)
                uydurma=bool(ham) and not value
                if text:self.add_message(text,'user');self._save_chat_history();self._ask(text)
                elif uydurma and (not self._requires_wake or recognized):
                    # B11 kararı (kullanıcı): anlaşılmayan ses uydurma metinle Gemini'ye gitmez; Yumi "anlayamadım" der ve yeniden dinler.
                    tur_kaydi.olay('stt_uydurma',metin=ham)
                    cevap='Anlayamadım, tekrar söyler misin?'
                    # Canlı kabul (13 Kasım): 10 sn'lik dinleme penceresi Yumi konuşurken doluyordu; tekrar söylenen cümle
                    # adsız sayılıp atılıyordu → pencere konuşma bitince (_finish_turn) açılır.
                    self._dinle_konusma_sonra=True;self.busy=True;self.voice_capture.suspended=True
                    self.add_message(cevap,'assistant');self.show_bubble(cevap);self._speak(cevap)
                elif self._requires_wake and recognized:
                    self._muzik_duraklat();self.voice_capture.arm_next_utterance();self.manual_pose='listen';self.manual_pose_end=time.perf_counter()+10
                else:self.voice_capture.suspended=False;self.set_status(self._bos_durum())
            elif kind in ('answer','stream_answer'):
                self.reply_pending=False
                message,self.previous_id=value
                tur_kaydi.olay('cevap',kaynak=self.settings.get('provider'),metin=message)
                if getattr(self,'streaming_label',None):
                    self.streaming_label.setText(message)
                    self._layout_messages()
                    self.chat_history.append({'role':'assistant','text':message})
                else:
                    self.add_message(message,'assistant')
                self.show_bubble(message)
                self._save_chat_history()
                self.streaming_text=message
                if not getattr(self,'speech_failed',False):self._queue_stream_speech(final=True)
                self.streaming_label=None
                if hasattr(self,'native_audio') and not self.native_audio.listening:self._warm_native(force=True)
                self._finish_turn()
            elif kind=='browser_warm':
                self.browser_retry_pending=False;self.web_retry_button.setEnabled(True)
                if getattr(value,'provider',self.settings['provider'])!=self.settings['provider']:
                    self._retry_browser();continue
                self._apply_web_status(value)
            elif kind=='browser_login':
                self.browser_login_pending=False
                self._apply_web_status(value)
                if getattr(value,'phase',None)=='login_open':self._giris_izle(getattr(value,'provider',None) or self.settings.get('provider'))
            elif kind=='giris_izle':
                self._giris_izleniyor=False
                saglayici,tamam=value
                if tamam and self.web_finish_button.isEnabled() and not getattr(self,'browser_login_pending',False):
                    self.set_status('Giriş algılandı, pencere kapatılıyor…')
                    self._browser_login(saglayici,True)
            elif kind=='browser_voice':
                self.avatar.speaking=False;self.avatar.mouth_level=0.;self.browser_voice_start=None
                self.speech_active=False;self._start_next_speech()
            elif kind=='speech':
                if getattr(self,'speech_failed',False):continue
                soundfile=DATA_DIR/(f'response-{time.monotonic_ns()}'+('.wav' if value[:4]==b'RIFF' else '.mp3'))
                soundfile.write_bytes(value)
                self.player.setSource(QUrl.fromLocalFile(str(soundfile)))
                for old_audio in sorted(DATA_DIR.glob('response-*.*'),key=lambda p:p.stat().st_mtime,reverse=True)[3:]:
                    if old_audio.suffix in ('.wav','.mp3'):
                        try:old_audio.unlink()
                        except OSError:pass
                self.avatar.conversation.begin(getattr(self,'active_speech_text',''),getattr(value,'boundaries',()))
                self.player.play(); self.avatar.speaking=True;self._tepki_uygula()
                label=next((title for title,key,_ in VOICES if key==getattr(self,'active_speech_voice',None)),'Seçili ses')
                self.set_status(f'Konuşuyor · {label}')

    def _speech_amplitude(self,buffer):
        if not buffer.isValid():
            self.avatar.mouth_level=0.;return
        formats={QAudioFormat.SampleFormat.Int16:(np.int16,32768.),QAudioFormat.SampleFormat.Int32:(np.int32,2147483648.),QAudioFormat.SampleFormat.Float:(np.float32,1.),QAudioFormat.SampleFormat.UInt8:(np.uint8,128.)}
        spec=formats.get(buffer.format().sampleFormat())
        if not spec:return
        samples=np.frombuffer(buffer.data(),dtype=spec[0]).astype(np.float32)
        if spec[0]==np.uint8:samples-=128.
        if samples.size:
            rms=float(np.sqrt(np.mean((samples/spec[1])**2)))
            self.avatar.mouth_level=float(np.clip((rms-.008)*5.5,0.,.85))

    def _playback_changed(self,state):
        if state==QMediaPlayer.PlaybackState.StoppedState:
            self.avatar.speaking=False; self.avatar.mouth_level=0.
    def _ensure_native(self):
        from native_live import NativeLive
        if not hasattr(self,'native_audio'):
            self.native_audio=NativeLive(self)
            self.native_audio.feedbackFailed.connect(self._skill_feedback_fallback)
            self.native_audio.stateChanged.connect(self._native_state)
            self.native_audio.playbackChanged.connect(self._native_playback)
            self.native_audio.transcriptChanged.connect(self._native_expression)
            self.native_audio.failed.connect(self._native_failed)
            self.native_audio.finished.connect(self._native_finished)
            self.native_audio.conversationPaused.connect(self._native_paused)
            from native_transcripts import NativeTranscriptView
            self.native_transcripts=NativeTranscriptView(self)
            self.native_audio.transcriptChanged.connect(self.native_transcripts.changed)
            self.native_audio.transcriptEnded.connect(self.native_transcripts.ended_turn)

    def _warm_native(self,force=False):
        if self.exiting or not self.gemini_key:return
        self._ensure_native()
        configuration=(self.settings.get('speech_voice','gemini-live:Kore'),character_name(self.settings),self.settings.get('mic_device','Otomatik'))
        if self.native_audio.active:
            if not force and (configuration==getattr(self,'native_configuration',None) or self.native_audio.listening):return
            self.native_audio.shutdown()
        selected=self.settings.get('speech_voice','gemini-live:Kore')
        if selected.startswith('gemini-live:'):
            try:
                self.native_audio.start(selected.split(':',1)[1],character_name(self.settings),history=self.chat_history,standby=True,microphone=self.settings.get('mic_device','Otomatik'))
                self.native_configuration=configuration
            except Exception as error:self._native_failed(str(error))

    def _mic(self):
        if not self.settings.get('speech_voice','').startswith('gemini-live:'):
            if self.busy:return
            if hasattr(self,'native_audio') and self.native_audio.active:self.native_audio.shutdown()
            try:
                if not self.voice_capture.manual:self._muzik_duraklat()  # dinlemeye başlarken müziği duraklat
                self.voice_capture.toggle_manual()
                self._set_microphone_button(self.voice_capture.manual)
            except MikrofonIzniYok as error:
                self._set_microphone_button(False);self._mikrofon_uyari(str(error))
            except Exception as error:
                self._set_microphone_button(False);self.show_error(str(error))
            return
        self._ensure_native()
        if self.native_audio.listening or self.native_audio.pending_activation or getattr(self,'native_conversation_active',False):
            self.native_audio.deactivate();return
        if self.busy:
            self._set_microphone_button(False)
            self.show_bubble('Önce mevcut yanıtı tamamla veya durdur.');return
        self._warm_native()
        selected=self.settings.get('speech_voice','gemini-live:Kore')
        if not selected.startswith('gemini-live:'):
            self._set_microphone_button(False)
            self.show_error('Bu ses yalnız ses örneğidir; canlı ses dönüşümü henüz bağlı değil. Ayarlar → Ses bölümünden Gemini Live sesi seç.' if selected.startswith('rvc:') else 'Sesli sohbet için Ayarlar → Ses bölümünden Gemini Live sesi seç.');return
        self.avatar.conversation.begin('');self.native_expression_turn=None;self.native_expression_text='';self.native_speaking=False
        self.native_error=None;self.native_conversation_active=True;self.busy=True;self.voice_capture.suspended=True
        if hasattr(self,'native_transcripts'):self.native_transcripts.new_session()
        self._set_microphone_button(True);self.mic_button.setToolTip('Gemini canlı sesi durdur')
        try:
            if not self.native_audio.active:self.native_audio.start(selected.split(':',1)[1],character_name(self.settings),history=self.chat_history,standby=True,microphone=self.settings.get('mic_device','Otomatik'))
            if not self.native_audio.activate():raise RuntimeError('Ses oturumu etkinleştirilemedi.')
        except Exception as error:
            self._native_failed(str(error));self._native_finished()

    def _native_command(self,text):
        from avatar_commands import command_text
        command=command_text(text,character_name(self.settings),'')
        if command:
            if self._start_skill_command(command,native=True):return
            result=self._local_command(command)
            if result:self.show_bubble(result)
        else:self._start_skill_command(text,native=True)

    def _native_expression(self,role,turn,text,mode):
        if role!='assistant':return
        if getattr(self,'native_expression_turn',None)!=turn:
            self.native_expression_turn=turn;self.native_expression_text=''
            self.avatar.conversation.begin('')
        old=self.native_expression_text
        self.native_expression_text=(text if mode=='snapshot' else old+text)[:16000]
        from conversation_motion import classify
        self.avatar.conversation.text=self.native_expression_text
        self.avatar.conversation.intent=classify(self.native_expression_text)

    def _native_playback(self,audible,level):
        now=time.perf_counter()
        if audible:
            if not getattr(self,'native_speaking',False):self.native_voice_start=now-self.avatar.conversation.position
            self.native_last_audible=now;self.native_speaking=True;self.avatar.speaking=True
            self.avatar.mouth_level=min(.85,max(0.,(level-.004)*5.5))
        else:
            self.avatar.mouth_level=0.
            if now-getattr(self,'native_last_audible',0.)>.18:self.native_speaking=False;self.avatar.speaking=False
        self.overlay.sync()

    def _native_state(self,text):
        self.set_status(text)
        if text.startswith(('Gemini bağlantısı hazır','Gemini bağlı','Dinliyor · Gemini Live','Seni dinliyor')):
            self.native_error=None;self.native_recovery.hide()
            self.native_reconnect_button.setEnabled(True)
        if text.startswith('Seni dinliyor') or text.startswith('Canlı ses durduruluyor'):
            self.native_speaking=False;self.avatar.speaking=False;self.avatar.mouth_level=0.
            self.avatar.conversation.position=0.
            self.overlay.sync()

    def _native_failed(self,text):
        self.native_error=text
        self.native_recovery_text.setText(text);self.native_recovery.show()
        self.native_reconnect_button.setEnabled(True)
        self.set_status('Ses bağlantısı kapalı · Yazılı sohbet kullanılabilir')
        if getattr(self,'native_conversation_active',False):self.show_error(text)

    def _reconnect_native(self):
        if self.busy or self.exiting:return
        if not self.gemini_key:
            self.native_recovery_text.setText('Canlı ses için Ayarlar → Ses → Gemini Live ses bağlantısı bölümüne Google AI Studio API anahtarını ekle. Gemini hesabına giriş yazılı sohbet içindir; canlı ses bağlantısını açmaz.')
            return
        if not self.settings.get('speech_voice','').startswith('gemini-live:'):
            self.native_recovery_text.setText('Ayarlar → Ses bölümünden bir Gemini Live sesi seç.')
            return
        self.native_reconnect_button.setEnabled(False)
        self.native_recovery_text.setText('Ses bağlantısı kuruluyor… Mikrofon beklemede kalacak.')
        self._warm_native(force=True)

    def _native_paused(self):
        self.native_speaking=False;self.avatar.speaking=False;self.avatar.mouth_level=0.
        if hasattr(self,'native_transcripts'):self.native_transcripts.finish_session()
        self.native_conversation_active=False;self.busy=False;self.voice_capture.suspended=False
        self._set_microphone_button(False);self.mic_button.setToolTip('Hazır bağlantıyla sesli sohbeti başlat')
        self._sync_name_wake()
        self._warm_native()

    def _native_finished(self):
        if not getattr(self,'native_conversation_active',False):
            if getattr(self,'voice_restart',False):
                self.voice_restart=False;QTimer.singleShot(200,self._warm_native)
            return
        self.native_conversation_active=False
        self.native_speaking=False;self.avatar.speaking=False;self.avatar.mouth_level=0.;self.avatar.conversation.position=0.
        if hasattr(self,'native_transcripts'):self.native_transcripts.finish_session()
        self.busy=False;self.voice_capture.suspended=False
        self._set_microphone_button(False);self.mic_button.setToolTip('Gemini canlı ses başlat / durdur')
        self.set_status(getattr(self,'native_error',None) or 'Ses bağlantısı kapalı · Mikrofonla yeniden dene')
        if getattr(self,'voice_restart',False):
            self.voice_restart=False;QTimer.singleShot(200,self._mic)
        elif hasattr(self,'voice_capture'):self._sync_name_wake()
    def _start_auto_listen(self):
        self._sync_name_wake()
    def _sync_name_wake(self):
        """B06: adla çağırma artık Vosk değil Whisper ile: mikrofon beklemede dinler (VoiceCapture 'always'), her söz
        yazıya çevrilir ve ad Türkçe okunuş anahtarıyla aranır (voice_profiles.wake_command). Eski Vosk işçisi kaldırıldı (12 Kasım)."""
        if self.exiting:return
        enabled=bool(self.settings.get('name_wake_enabled',False))
        self.voice_capture.wake_name=character_name(self.settings)
        try:
            if enabled!=self.voice_capture.always:self.voice_capture.set_always(enabled)
        except MikrofonIzniYok as error:
            self._wake_failed('Adla çağırma için mikrofon izni gerekli.');self._mikrofon_uyari(str(error))
        except Exception as error:self._wake_failed(f'Adla çağırma için mikrofon açılamadı: {error}')
    def _mikrofon_uyari(self,mesaj=None):
        """F1b: mikrofon izni kapalı / hep sessizlik → oturumda bir kez, "Ayarları aç" düğmeli uyarı (pencere kendiliğinden açılır)."""
        if self.exiting or getattr(self,'_mikrofon_uyarildi',False):return
        self._mikrofon_uyarildi=True
        mesaj=mesaj or ('Mikrofondan hiç ses gelmiyor. Windows mikrofon izni kapalı olabilir ya da mikrofon sessize alınmış. '
                        'Windows Ayarlar → Gizlilik ve güvenlik → Mikrofon bölümünden izni kontrol et.')
        self.set_status('Mikrofon izni gerekli')
        kutu=QMessageBox(QMessageBox.Icon.Warning,'Yumi · Mikrofon',mesaj,QMessageBox.StandardButton.Close,self)
        ac=kutu.addButton('Ayarları aç',QMessageBox.ButtonRole.AcceptRole)
        kutu.setDefaultButton(ac);self._show();kutu.raise_();kutu.activateWindow();kutu.exec()
        if kutu.clickedButton() is ac:
            import mikrofon_izni;mikrofon_izni.ayarlari_ac()
        self._mikrofon_uyarildi=False  # izin açılıp yeniden denenirse tekrar uyarabilsin
        try:self.voice_capture._sessiz_bildirildi=True
        except Exception:pass
    def _wake_partial(self,samples):
        """B06: söz sürerken (0,7 s, 1,5 s … 4 s) kısa tanıma; ad duyulursa hemen bip (söz sonunu beklemeden).
        Yalnız ekran kartı Whisper'ı varsa (işlemcide yavaş). Metin hiçbir yere kaydedilmez."""
        if getattr(self,'_wake_partial_busy',False) or self.busy:return
        import stt_worker
        if not stt_worker.gpu_ready():return
        self._wake_partial_busy=True;name=character_name(self.settings)
        def bak():
            try:
                metin=stt_worker.transcribe(samples,name)
                return bool(metin) and wake_command(metin,name)[0]
            finally:self._wake_partial_busy=False
        self.executor.submit(bak).add_done_callback(lambda f:self.results.put(('wake_partial',f)))
    def _canli_yazi(self,samples):
        """ARAYUZ (13 Kasım): konuşurken duyulan yazı. Yalnız ekran kartı Whisper'ı hazırsa; aynı anda tek ara tanıma.
        Metin yalnız ekranda gösterilir, kaydedilmez; asıl tanıma söz bitince ayrıca yapılır."""
        if getattr(self,'_canli_busy',False) or self.busy:return
        import stt_worker
        if not stt_worker.gpu_ready():return
        self._canli_busy=True;name=character_name(self.settings)
        def tani():
            try:return stt_worker.transcribe(samples,name)
            finally:self._canli_busy=False
        self.executor.submit(tani).add_done_callback(lambda f:self.results.put(('canli_yazi',f)))
    def _bip(self,son=False):
        """Adla çağırma geri bildirimi (Alexa/Google gibi): ad duyulunca yükselen iki ton (dinliyorum),
        komut alınınca alçalan kısa ton (anladım). data/ses_onbellek/bip_*.wav ilk kullanımda üretilir."""
        try:
            import winsound,wave
            yol=DATA_DIR/'ses_onbellek'/('bip_son.wav' if son else 'bip_basla.wav')
            if not yol.is_file():
                yol.parent.mkdir(parents=True,exist_ok=True);sr=24000
                def ton(f,s):
                    t=np.arange(int(sr*s))/sr;z=np.sin(2*np.pi*f*t)*np.sin(np.pi*t/s)**2;return z
                sinyal=(np.concatenate([ton(1175,.06),np.zeros(int(sr*.01)),ton(784,.08)])*.35 if son else
                        np.concatenate([ton(880,.07),np.zeros(int(sr*.012)),ton(1320,.11)])*.5)
                with wave.open(str(yol),'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes((sinyal*32767).astype('<i2').tobytes())
            winsound.PlaySound(str(yol),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        except Exception:pass
    def _alarm_bip(self):
        """Alarm/sayaç bitti sesi (konuşmayan modeller için): 3 kez 4'lü 'bip bip bip bip', ~3,6 s.
        data/ses_onbellek/alarm_bip.wav ilk kullanımda üretilir."""
        try:
            import winsound,wave
            yol=DATA_DIR/'ses_onbellek'/'alarm_bip.wav'
            if not yol.is_file():
                yol.parent.mkdir(parents=True,exist_ok=True);sr=24000
                def ton(f,s):
                    t=np.arange(int(sr*s))/sr;zarf=np.minimum(1,np.minimum(t,s-t)/.005);return np.sin(2*np.pi*f*t)*zarf
                sus=lambda s:np.zeros(int(sr*s))
                grup=np.concatenate([np.concatenate([ton(1000,.09),sus(.07)]) for _ in range(4)])
                sinyal=np.concatenate([np.concatenate([grup,sus(.55)]) for _ in range(3)])*.45
                with wave.open(str(yol),'wb') as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes((sinyal*32767).astype('<i2').tobytes())
            winsound.PlaySound(str(yol),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        except Exception:pass
    def _wake_failed(self,message):
        # A transient microphone failure must not erase the user's preference.
        # Background retry failures belong in service status, not chat history.
        self.set_status(message)
    def _motion_library(self):
        if self.pages.busy or getattr(self,'motion_dialog',None):return
        from motion_ui import MotionDialog
        self.motion_dialog=MotionDialog(self);self._push_page(self.motion_dialog)

    def _play_motion(self,path):
        from vrma import MotionClip
        clip=MotionClip(path)
        if not self.avatar.model or not self.overlay.avatar.model:raise ValueError('Önce bir VRM karakter seç.')
        from voice_actions import stop
        stop(self)
        if self.overlay.avatar.furniture is not None:
            self.pending_motion_path=str(path);self.overlay.avatar.furniture.request_exit()
            self.show_bubble('Önce kalkıyorum, ardından animasyonu oynatacağım.');return
        for view in (self.avatar,self.overlay.avatar):
            if not view.model:raise ValueError('Önce bir VRM karakter seç.')
            view.model.clip=clip;view.model.clip_start=time.perf_counter()-view.clock
        self.manual_pose='clip';self.manual_pose_end=time.perf_counter()+clip.duration+.1
        self.show_bubble('Animasyon: '+Path(path).stem)
    def _wave(self):
        if modelsiz_acik(self):return  # C05
        from voice_actions import stop
        stop(self)
        self.last_user_action=time.perf_counter(); self.manual_pose='wave'; self.manual_pose_end=time.perf_counter()+7.7; self.show_bubble('Merhaba! 👋')


    # ---- F3 (19 Kas 2026): paket işleri ana pencerede sonuçlanır (Ayarlar kapalı olsa da)
    def _paket_isi_bitti(self):
        i=self.paket_isi;i.islendi=True
        import paket_yonetici as py
        if i.hata:
            mesaj=('Paket eklenemedi: ' if i.tur=='kurulum' else 'Paket bağlanamadı: ')+i.hata
            self.add_message(mesaj,'error',record=False)
        else:
            py.degisti();k=i.sonuc['kayit']
            mesaj=f"{k.get('baslik') or k['ad']} {k['surum']} {'eklendi' if i.tur=='kurulum' else 'yeniden bağlandı'}: {len(k.get('karakterler',[]))} karakter."
            if i.sonuc.get('eski_tasinan'):mesaj+=f" Önceki dosyalar silinmedi: {Path(k['kok'])/py.ESKI}"
            self._paket_model_yenile()
            self.add_message(mesaj,'assistant',record=False)
        self.paket_son_mesaj=mesaj;self.set_status(mesaj[:140])
        speech_event(f'paket {i.tur} bitti hata={i.hata!r} sure={time.monotonic()-i.basla_t:.1f}s')
    def _paket_model_yenile(self,aktif_gitti=False):
        """Paket listesi değişti: seçili model geçersizse ya da kaldırılan paketteyse varsayılana (yoksa modelsize) geç."""
        from skins import default_skin,valid_skin
        from modelsiz import model_yok_guncelle
        if aktif_gitti or getattr(self,'_kurulu_model_yok',False) or not valid_skin(self.settings.get('skin')):
            self.overlay.select_skin(default_skin())
        else:model_yok_guncelle(self)
    def paket_baglantisini_kes(self,ad):
        """Kaldır: kayıt etkin değil olur, dosyalar yerinde kalır. Etkin model o paketteyse önce varsayılana/modelsize geçilir."""
        import paket_yonetici as py,karakterler
        from skins import SPRITE
        k=py.kayit(ad)
        if k is None:return None
        skin=self.settings.get('skin')
        kayit=karakterler.dizin()['clippy'] if skin==SPRITE else karakterler.gorunum(skin)
        aktif=bool(kayit) and any(py._anahtar(kayit['klasor'])==py._anahtar(p) for p in py.karakter_klasorleri(k))
        py.baglantiyi_kes(ad)
        self._paket_model_yenile(aktif_gitti=aktif)
        mesaj=f"{k.get('baslik') or ad} kaldırıldı; dosyalar yerinde, “Yeniden bağla” ile geri gelir."
        self.paket_son_mesaj=mesaj;self.add_message(mesaj,'assistant',record=False);speech_event(f'paket {ad} baglanti kesildi aktif={aktif}')
        return k

    def _tick(self):
        i=getattr(self,'paket_isi',None)
        if i is not None and i.bitti and not i.islendi:self._paket_isi_bitti()  # F3
        # B10: ses hangi yoldan değişirse değişsin (ayarlar, karakter seçici, sesli komut) yeni sesi boşta ısıt.
        # 23:16 kaydı: Shani'ye geçişte ısınma çalışmadı, ilk cümle model yüklemesini bekledi (metinden sonra 9,7 s).
        ses=self.settings.get('speech_voice','')
        if ses!=getattr(self,'_isinmis_ses',None) and not getattr(self,'busy',False):self._ses_hazirla(str(ses))
        if getattr(getattr(self,'fullscreen_pause',None),'paused',False):return
        now=time.perf_counter()
        bekleyen=getattr(self,'_bekleyen_tepki',None)
        if bekleyen and time.perf_counter()-bekleyen[0]>8:self._tepki_uygula()
        if self.calar.bosaldi():
            onceki=getattr(self,'calar_segment',None)
            if onceki is not None and onceki.ac_kalma:speech_event(f'bolum {onceki.kimlik} KESINTI {onceki.ac_kalma} kez')
            self.calar_segment=None;self.avatar.speaking=False;self.avatar.mouth_level=0.
            self._finish_turn()
        self.calar.bakim()
        if getattr(self,'native_speaking',False):
            self.avatar.conversation.position=now-self.native_voice_start
            self.avatar.conversation.duration=0.
            if now-getattr(self,'native_last_audible',0.)>.3:self.native_speaking=False;self.avatar.speaking=False;self.avatar.mouth_level=0.
        elif getattr(self,'browser_voice_start',None):
            self.avatar.conversation.position=now-self.browser_voice_start
            self.avatar.conversation.duration=0.
            self.avatar.mouth_level=min(.85,max(0.,self.system_audio.sample())*4)
        elif self.calar.mesgul() and self.calar.su_an is None and getattr(self,'calar_segment',None) is None:
            # Mimik–ses senkronu (kullanıcı, 12 Kasım): bölüm sırada ama ses henüz çalmıyor (üretim/ön tampon) →
            # konuşma jesti/yüz/ağız başlamaz; ilk ses çıktığı karede başlar.
            self.avatar.speaking=False;self.avatar.mouth_level=0.
        elif self.calar.mesgul():
            segment=self.calar.su_an
            if segment is not None and segment is not getattr(self,'calar_segment',None):
                onceki=getattr(self,'calar_segment',None)
                if onceki is not None and onceki.ac_kalma:speech_event(f'bolum {onceki.kimlik} KESINTI {onceki.ac_kalma} kez')
                self.calar_segment=segment
                speech_event(f'bolum {segment.kimlik} ses basladi tampon={segment.toplam/segment.sr:.2f}s hiz={self.calar.hiz:.2f}')
                self.avatar.conversation.begin(segment.metin,segment.sinirlar)
                self._tepki_uygula()
                label=next((title for title,key,_ in VOICES if key==getattr(self,'active_speech_voice',None)),'Seçili ses')
                self.set_status(f'Konuşuyor · {label}')
            self.avatar.conversation.position,self.avatar.conversation.duration=self.calar.konum()
            self.avatar.speaking=True
            self.avatar.mouth_level=float(np.clip((self.calar.seviye-.008)*5.5,0.,.85))
        else:
            self.avatar.conversation.position=self.player.position()/1000.
            self.avatar.conversation.duration=self.player.duration()/1000.
        if modelsiz_acik(self):  # C05: ses hattı yukarıda sürer; dans/senaryo/poz işleri kapalı
            self.avatar.hand_gesture=None;return
        if self.settings.get('skin')==SPRITE:
            if not getattr(self,'clippy_actions_stopped',False):
                self.music_runtime.stop(suppress=False)
                self.music_runtime.enabled=False;self.music_runtime._rest()
                self.daily_director.cancel()
                self.pending_avatar_command=None;self.voice_target=None;self.manual_pose=None
                self.clippy_actions_stopped=True
            self.move_animation.stop()
            self.avatar.pose='idle';self.avatar.prop='none';self.avatar.hand_gesture=None
            self.avatar.clippy_state=('thinking' if self.busy else 'listening' if getattr(getattr(self,'native_audio',None),'listening',False) else 'idle')
            self.overlay.sync()
            return
        self.clippy_actions_stopped=False
        from voice_actions import music
        if now>=getattr(self,'gesture_until',0.):self.avatar.hand_gesture=None
        music(self,now)
        self.daily_director.tick(now)
        if self.manual_pose and now>self.manual_pose_end:self.manual_pose=None
        performing=self.music_runtime.active
        pose='clip' if performing else 'idle' if self.avatar.speaking else self.manual_pose or 'idle'
        if pose not in ('idle','walk','wave','listen','clip'):pose='idle'
        if pose!='walk':self.move_animation.stop()
        self.avatar.pose=pose;self.avatar.prop='none'
        self.overlay.sync()






    def _render_movement(self,dt):
        if modelsiz_acik(self) or self.exiting:return  # C05; 19 Kas: kapanışta hareket/ısıtma döngüsü durur
        self.last_render_movement=time.perf_counter();self.in_render_movement=True
        try:
            self._roam();self._tick()
            x=getattr(self,'roam_x',float(self.overlay.x()))-self.overlay.x()
            self.overlay.avatar.subpixel_x=x if abs(x)<=1.5 else 0.
        finally:self.in_render_movement=False

    def _roam(self):
        if modelsiz_acik(self):return  # C05: gizliyken (modelsiz) gezinme yok
        if self.settings.get('skin')==SPRITE:return
        if getattr(getattr(self,'fullscreen_pause',None),'paused',False):return
        if not self.settings.get('model_visible',True) or not self.overlay.isVisible() or self.overlay.drag is not None:
            from locomotion import halt
            halt(self);self.roam_clock=time.perf_counter();return
        from action_transition import dispatch
        if dispatch(self):return
        if getattr(self.overlay.avatar,'furniture',None):return
        if not getattr(self,'in_render_movement',False) and time.perf_counter()-getattr(self,'last_render_movement',0)<.05:return
        now=time.perf_counter();previous=getattr(self,'roam_clock',now);self.roam_clock=now
        dt=max(0.,min(.05,now-previous))
        self.overlay.contain()
        from voice_actions import travel
        if travel(self,dt):return
        if getattr(getattr(self,'music_runtime',None),'enabled',False):return
        self.avatar.walking_turn=False
        if not self.settings['roam'] or self.overlay.manually_placed or self.overlay.drag is not None or now-self.last_user_action<20 or self.busy or self.avatar.speaking or not self.overlay.isVisible():
            from locomotion import halt
            halt(self)
            return
        if self.manual_pose not in (None,'walk','idle') or self.avatar.pose not in ('idle','walk'):return
        left,right=self.overlay.walk_limits()
        if right-left<2:return
        direction=getattr(self,'walk_direction',-1)
        x=max(left,min(right,getattr(self,'roam_x',float(self.overlay.x()))))
        if abs(x-self.overlay.x())>1.5:x=float(self.overlay.x())
        if (direction<0 and x<=left+.5) or (direction>0 and x>=right-.5):direction=-direction
        self.walk_direction=direction;self.avatar.walk_direction=direction
        target=90*direction
        self.avatar.walking_turn=True;self.overlay.sync()
        # Turn on planted feet before travelling in the new direction.
        turning=abs(self.overlay.avatar.yaw.angle-target)>5
        self.manual_pose='idle' if turning else 'walk';self.manual_pose_end=now+.25
        if turning:
            from locomotion import halt
            halt(self)
        if not turning:
            from locomotion import stride_step
            x=max(left,min(right,x+stride_step(self,direction,dt)))
            self.overlay.move(round(x),self.overlay.y())
        self.roam_x=x

    def closeEvent(self,event):
        if self.exiting: event.accept()
        else: event.ignore(); self.hide()
    def quit(self):
        if not self.exiting:  # 19 Kas gözlem: zorlama testinde quit'i kim çağırdı belli olmadı → ilk çağrıda çağıranı günlüğe yaz
            import traceback,logging;logging.getLogger('yumi').info('Çıkış istendi: %s',''.join(traceback.format_stack(limit=8)[:-1]))
        self.exiting=True
        if any(worker.isRunning() for worker in getattr(QApplication.instance(),'_yumi_skill_workers',[])):
            QTimer.singleShot(100,self.quit);return
        if getattr(self,'skill_engine',None):
            self.skill_engine.time.stop_worker()
            self.skill_engine.smart_home.close()
        if hasattr(self,'music_runtime'):self.music_runtime.stop()
        if hasattr(self,'media_activity'):self.media_activity.stop()
        if hasattr(self,'fullscreen_pause'):self.fullscreen_pause.shutdown()
        if hasattr(self,'native_audio'):self.native_audio.shutdown()
        self.exiting=True
        self.assistant.close()
        if getattr(self.overlay.avatar,'three_desktop',None):self.overlay.avatar.three_desktop.dispose()
        self.overlay.close()
        self.hotkey.close(); self.voice_capture.close(); self.player.stop(); self.tray.hide()
        self.calar.kapat();self.speech_executor.shutdown(wait=False,cancel_futures=True)
        self.chat_executor.shutdown(wait=False,cancel_futures=True)
        self.executor.shutdown(wait=False,cancel_futures=True)
        QApplication.quit()


def main():
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    app=QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    try:  # 18 Kas: Evet/Hayır/Tamam/İptal — Qt düğmeleri Türkçe (arayuz/ceviri.py)
        from ceviri import turkce_yukle;turkce_yukle(app)
    except Exception:
        import logging;logging.getLogger("yumi").warning("Türkçe Qt çevirisi yüklenemedi",exc_info=True)

    client=QLocalSocket()
    client.connectToServer(APP_ID)
    if client.waitForConnected(400):
        import ctypes
        h1 = ctypes.windll.user32.FindWindowW(None, 'Yumi · 3D Masaüstü Asistanı')
        h2 = ctypes.windll.user32.FindWindowW(None, 'Yumi · Masaüstü karakteri')
        if h1 or h2:
            paket=next((a for a in sys.argv[1:] if a.lower().endswith('.yumipaket')),None)
            client.write(('paket\t'+paket+'\n').encode('utf-8') if paket else b'show\n')  # F1b: .yumipaket çift tık
            client.waitForBytesWritten(400)
            client.disconnectFromServer()
            return 0
        client.disconnectFromServer()

    server=QLocalServer()
    server.removeServer(APP_ID)
    window=YumiWindow()
    screen=app.primaryScreen().availableGeometry()
    window.move(screen.right()-window.width()-20,screen.bottom()-window.height()-10)
    window._show()
    from startup_runtime import mark_startup_ready
    QTimer.singleShot(0,mark_startup_ready)

    def on_new_connection():
        conn=server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(500)
            istek=bytes(conn.readAll()).decode('utf-8','replace').strip()
            window._show()
            if istek.startswith('paket\t'):window.paket_ac(istek.split('\t',1)[1])  # F1b: .yumipaket çift tık
            conn.disconnectFromServer()
    server.newConnection.connect(on_new_connection)
    server.listen(APP_ID)
    ilk_paket=next((a for a in sys.argv[1:] if a.lower().endswith('.yumipaket')),None)
    if ilk_paket:QTimer.singleShot(1500,lambda:window.paket_ac(ilk_paket))  # F1b: Yumi kapalıyken çift tık

    if env_value('TEST_OUTPUT'):
        def finish_test():
            Path(env_value('TEST_OUTPUT')).parent.mkdir(parents=True,exist_ok=True)
            window.overlay.grab().save(env_value('TEST_OUTPUT'))
            window.quit()
        QTimer.singleShot(2500,finish_test)
    return app.exec()


if __name__=='__main__':
    sys.exit(main())
