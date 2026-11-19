"""Conversation backends, local voice, and live weather follow-up."""
from __future__ import annotations
import base64, io, json, os, re, shutil, subprocess, threading, wave
from functools import lru_cache
from pathlib import Path
import numpy as np
import requests

ROOT=Path(__file__).resolve().parents[1]
OFFLINE_MESSAGE='Şu an internete bağlı olmadığım için sorunu cevaplayamıyorum. Ev komutların çalışmaya devam ediyor.'
HIDDEN={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
_whisper=None
_model=None
_model_lock=threading.Lock()

def _yalniz_exe(yol):
    """19 Kas (güvenlik): kullanıcı metni komut satırı argümanı olarak gider; .cmd/.bat cmd.exe'den geçer ve '&' gibi
    karakterlerle komut enjeksiyonuna açıktır. Yalnız gerçek .exe kabul edilir."""
    return yol if yol and str(yol).lower().endswith('.exe') else None

def ai_kapali():
    """19 Kas gözlem: test sürücüleri için tek anahtar (YUMI_AI_KAPALI=1). Sohbet sağlayıcısına (Gemini/ChatGPT web,
    API, CLI, Codex) hiçbir istek gitmez, tarayıcı açılmaz. Eskiden testler sağlayıcıyı 'openai' yapıyordu; load_settings
    bunu sessizce gemini-web'e çeviriyor, açılışta Gemini web'e bağlanılıyordu."""
    return os.environ.get('YUMI_AI_KAPALI','')=='1'

AI_KAPALI_YANIT='(Test: yapay zekâ kapalı.)'

def codex_path():
    candidate=_yalniz_exe(shutil.which('codex'))
    fallback=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/OpenAI/Codex/bin/codex.exe'
    return candidate or (str(fallback) if fallback.exists() else None)

def agy_path():
    candidate=_yalniz_exe(shutil.which('agy'))
    fallback=Path(os.environ.get('LOCALAPPDATA',''))/'agy/bin/agy.exe'
    return candidate or (str(fallback) if fallback.exists() else None)

def login_status():
    executable=codex_path()
    if not executable: return 'Codex CLI bulunamadı.'
    result=subprocess.run([executable,'login','status'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,**HIDDEN)
    return (result.stdout or result.stderr).strip()

def login():
    executable=codex_path()
    if not executable: raise RuntimeError('Codex CLI kurulu değil.')
    result=subprocess.run([executable,'login'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,**HIDDEN)
    if result.returncode: raise RuntimeError((result.stderr or result.stdout).strip()[-1000:])
    return login_status()

def local_transcribe(samples,wake_name='Yumi'):
    from stt_worker import transcribe
    return transcribe(samples,wake_name)

def _local_transcribe(samples,wake_name='Yumi'):
    from resource_guard import require_capacity,GiB
    require_capacity(GiB)
    global _model, _whisper
    whisper_dir=ROOT/'models/whisper-small'
    if (whisper_dir/'model.bin').exists():
        from faster_whisper import WhisperModel
        with _model_lock:
            if _whisper is None: _whisper=WhisperModel(str(whisper_dir),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1)
        segments,_=_whisper.transcribe(samples,language='tr',beam_size=5,vad_filter=True,initial_prompt=f'{wake_name} adlı sesli asistana Türkçe soru soruyorum. Hava durumu, şehir, İstanbul, Ankara.',condition_on_previous_text=False)
        return ' '.join(segment.text.strip() for segment in segments).strip()
    # 12 Kasım: Vosk yedeği kaldırıldı (adla çağırma ve ses tanıma Whisper; Vosk modelleri _silinecek'te).
    raise RuntimeError('Yerel Türkçe ses modeli (Whisper small) eksik. KURULUM.cmd dosyasını çalıştırın.')

class SpeechAudio(bytes):
    def __new__(cls,audio,boundaries=()):
        result=super().__new__(cls,audio);result.boundaries=tuple(boundaries);return result

@lru_cache(maxsize=32)
def local_speech(text,data_dir,voice='xtts:varsayilan'):
    # 12 Kasım: RVC/Applio kaldırıldı (rvc: sesleri aşağıda 'Desteklenmeyen ses motoru' hatası verir).
    # Kullanıcı kuralı: karakter sesi dışında ses çalınmaz (yedek yok). Hata yukarı gider, cümle atlanır.
    # G-A2 (18 Kas): Edge TTS kaldırıldı (edge: sesleri 'Desteklenmeyen ses motoru'; ayarlar varsayılan Yumi sesine göçer).
    if voice.startswith('xtts:') or voice.startswith('meowko'):
        from xtts_speech import synthesize
        if voice.startswith('meowko'):voice='xtts:meowko:'+('deep' if 'deep' in voice else 'kawaii')
        return synthesize(text,data_dir,voice)  # yedek ses yok (kullanıcı kuralı)
    raise RuntimeError(f'Desteklenmeyen ses motoru: {voice}')


def is_offline_error(error):
    """Only turn recognizable transport failures into an offline reply."""
    current=error
    while current is not None:
        if isinstance(current,(requests.ConnectionError,requests.ConnectTimeout,ConnectionError)):
            return True
        current=current.__cause__
    message=str(error).casefold()
    return any(word in message for word in (
        'name resolution','dns','network is unreachable','connection refused',
        'failed to connect','could not connect','internet connection',
        'network connection','getaddrinfo failed'))


def offline_warning_speech(data_dir,voice):
    """Use the same selected voice; never switch a female profile to a male voice."""
    import hashlib
    directory=Path(data_dir)
    name=hashlib.sha256(voice.encode('utf-8')).hexdigest()[:16]
    path=directory/'ses_onbellek'/('internet-yok-'+name+'.ses')
    if path.exists() and path.stat().st_size>100:return path.read_bytes()
    path.parent.mkdir(parents=True,exist_ok=True)
    audio=local_speech(OFFLINE_MESSAGE,directory,voice)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(audio);temporary.replace(path)
    return audio


def prepare_offline_warning(data_dir,voice):
    try:offline_warning_speech(data_dir,voice)
    except Exception:pass  # Online service may be unavailable; the selected voice stays unchanged.


class Assistant:
    def __init__(self,settings,data_dir):
        self.settings=settings
        self.data_dir=Path(data_dir)
        self.history=[]
        self.pending_weather=False
        self.weather_city=''
        self.weather_tomorrow=False
        self.weather_locations={}
        self.web=None;self.web_lock=threading.Lock();self.reply_cancel=threading.Event()
        self.chat_scope=None;self.chat_urls={}

    def warm_browser(self,provider=None):
        provider=provider or self.settings.get('provider')
        if provider not in ('chatgpt-web','gemini-web') or ai_kapali():return
        with self.web_lock:
            if self.web is None:
                from browser_chat import BrowserChat
                self.web=BrowserChat(self.data_dir)
        with self.web.lock:
            self.web.use_conversation(self.chat_scope,self.chat_urls)
            return self.web.warm(provider)

    def check_browser(self,provider=None):
        """B03 bekçi: web oturumu sağlıklı mı; değilse baştan kurar. Meşgulse None (denetlemez)."""
        provider=provider or self.settings.get('provider')
        if provider not in ('chatgpt-web','gemini-web') or ai_kapali() or self.web is None or not hasattr(self.web,'denetle'):return None
        return self.web.denetle(provider)

    def browser_login(self,finish=False,provider=None):
        if ai_kapali():return False
        with self.web_lock:
            if self.web is None:
                from browser_chat import BrowserChat
                self.web=BrowserChat(self.data_dir)
        provider=provider or self.settings.get('provider','chatgpt-web')
        if provider not in ('chatgpt-web','gemini-web'):provider='chatgpt-web'
        with self.web.lock:
            self.web.use_conversation(self.chat_scope,self.chat_urls)
            if finish:return self.web.finish_login(provider)
            return self.web.show_login(provider)

    def begin_reply(self):
        self.reply_cancel.clear()

    def cancel_reply(self):
        self.reply_cancel.set()
        if self.web:self.web.cancel_request()

    def close(self):
        self.cancel_reply()
        if self.web:self.web.close()

    def _karakter_adi(self):
        """19 Kas (kullanıcı): yapay zekâ seçili karakterin adıyla konuşur (Akira seçiliyse "ben Akira")."""
        try:
            from voice_profiles import character_name
            return character_name(self.settings)
        except Exception:
            return 'Yumi'
    def _gemini_cli(self,text,on_chunk=None,on_status=None):
        executable=agy_path()
        if not executable:raise RuntimeError('AGY CLI (Gemini) bulunamadı.')
        if on_status:on_status('Gemini düşünüyor…')
        name=self._karakter_adi()
        system_instruction=(
            f'Sen {name} adlı sevimli, zeki masaüstü sesli asistanısın. '
            'Kullanıcıyla samimi, doğal, sıcak ve akıcı Türkçe konuş. '
            'Sorulara ilk cümlede doğrudan cevap ver. Varsayılan yanıtın genellikle 1 veya 2 kısa cümle olsun. '
            'Metin seslendirileceği için kesinlikle Markdown, yıldız işareti (*), liste, tablo ve emoji kullanma. '
            'Gereksiz teknik detay ve yapmadığın bilgisayar işlemlerini anlatma.'
        )
        context_lines=[]
        for m in self.history[-10:]:
            role='Kullanıcı' if m.get('role')=='user' else name
            content=str(m.get('text','')).strip()
            if content:context_lines.append(f'{role}: {content}')
        history_str=('\nGeçmiş:\n'+'\n'.join(context_lines)) if context_lines else ''
        city=str(self.settings.get('city','')).strip()
        location_info=f' (Konum: {city})' if city else ''
        prompt=f"{system_instruction}{history_str}\n\nKullanıcı{location_info}: {text}\n{name}:"
        command=[executable,'--model','gemini-3.8-flash-low','--effort','low','--disable-slash-commands','-p',prompt]
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',**HIDDEN)
        output=[]
        try:
            while True:
                if self.reply_cancel.is_set():
                    process.kill()
                    break
                chunk=process.stdout.read(4)
                if not chunk:break
                output.append(chunk)
                if on_chunk:on_chunk(chunk)
            process.wait(timeout=30)
        except Exception:
            process.kill()
            raise
        full=''.join(output).strip()
        if not full and process.returncode!=0:
            err=process.stderr.read()[-800:]
            raise RuntimeError('Gemini CLI yanıt veremedi: '+err)
        return full

    def ask(self,text,key='',previous=None):
        return self.stream_ask(text,key,previous)

    def stream_ask(self,text,key='',previous=None,on_chunk=None,on_status=None):
        if ai_kapali():
            if on_chunk:on_chunk(AI_KAPALI_YANIT)
            self._remember(text,AI_KAPALI_YANIT);return AI_KAPALI_YANIT,None
        provider=self.settings.get('provider','gemini-cli')
        lowered=text.lower()
        if self.weather_city and ('kaynak' in lowered or 'nereden aldın' in lowered):
            message='Open-Meteo verilerini kullanıyorum.'
            if on_chunk:on_chunk(message)
            self._remember(text,message);return message,previous
        weather=any(term in lowered for term in ['hava durumu','hava nasıl','hava bugün','hava yarın','kaç derece']) or (bool(self.weather_city) and lowered.strip(' ?!. ') in ('yarın','peki yarın','ya yarın'))
        clock=self._clock_answer(lowered)
        if clock:
            if on_chunk:on_chunk(clock)
            self._remember(text,clock);return clock,previous
        pending_reply=self.pending_weather and not weather and len(re.findall(r"\w+",text))<=3
        if self.pending_weather and not weather and not pending_reply:
            # A longer sentence is a new topic, not the city answer.
            self.pending_weather=False
        if weather or pending_reply:
            default=self.settings.get('city','').strip() or self.weather_city
            tomorrow=self.weather_tomorrow if pending_reply else 'yarın' in lowered
            candidate=text.strip(' ?!.') if pending_reply else self._place_in_text(text)
            loc=self._lookup(candidate) if candidate else None
            if loc is None and pending_reply:
                # Unknown short reply: stop the weather follow-up and let the assistant answer.
                self.pending_weather=False;weather=False;pending_reply=False
            elif loc is None and not default:
                self.pending_weather=True;self.weather_tomorrow=tomorrow
                message='Hangi şehir için hava durumunu öğrenmek istiyorsun?'
                if on_chunk:on_chunk(message)
                self._remember(text,message);return message,previous
            if weather or pending_reply:
                self.pending_weather=False
                message=self._weather(loc['name'] if loc else default,tomorrow,loc)
                if on_chunk:on_chunk(message)
                self._remember(text,message);return message,previous

        if not key:
            try:
                from platform_win import unprotect
                kf=self.data_dir/'gemini-key.dat'
                if kf.is_file():key=unprotect(kf.read_bytes()).decode('utf-8')
            except Exception:pass

        if (provider in ('gemini','gemini-api') or provider=='gemini-cli') and key:
            from gemini_chat import stream_answer, DEFAULT_MODEL
            name=self._karakter_adi()
            model=self.settings.get('gemini_model',DEFAULT_MODEL)
            res=stream_answer(key,text,self.history,model=model,on_chunk=on_chunk,cancel=self.reply_cancel,on_status=on_status,name=name)
            message=res[0] if isinstance(res,tuple) else res
            self._remember(text,message);return message,None

        if provider in ('gemini-cli','agy'):
            message=self._gemini_cli(text,on_chunk=on_chunk,on_status=on_status)
            self._remember(text,message);return message,None
        if provider in ('chatgpt-web','gemini-web'):
            with self.web_lock:
                if self.web is None:
                    from browser_chat import BrowserChat
                    self.web=BrowserChat(self.data_dir)
            if on_status:on_status('Web sohbetine bağlanıyor…')
            with self.web.lock:
                self.web.use_conversation(self.chat_scope,self.chat_urls)
                self.web.karakter_adi=self._karakter_adi()
                self.web.ensure(provider)
                request_text=text
                city=str(self.settings.get('city','')).strip()
                if city and any(term in text.casefold() for term in ('hava','derece','yağmur','yagmur')):
                    place=self._place_in_text(text)
                    if not place:request_text+=' ('+city+')'
                message=self.web.ask(request_text,on_chunk,on_status=on_status)
            self._remember(text,message);return message,None
        if provider=='openai':
            from api import answer
            message,new_id=answer(key,text,previous,self.settings['model'],history=self.history)
            if on_chunk:on_chunk(message)
        else:
            message=self._codex(text);new_id=None
            if on_chunk:on_chunk(message)
        self._remember(text,message)
        return message,new_id

    def _remember(self,text,message):
        self.history.extend([{'role':'user','text':text},{'role':'assistant','text':message}])
        self.history=self.history[-24:]

    def _place_in_text(self,text):
        # Remove weather request wording, retaining an explicitly named place.
        words=re.findall(r"[a-zçğıöşü]+",text.casefold().replace("\u0307",""))
        filler=set("bugün yarın şu an hava havanın durumu durumunu durumu’nun nasıl kaç derece sıcaklık sıcaklığı söyle söyler söyleyebilir söyleyebilirmisin söyleyebilir misin söyleyip bilir bilirmisin bilir öğrenmek istiyorum olacak nedir peki için bana lütfen ya ne bir bilgi verir verebilir hakkında öğrenebilir ben şimdi acaba ve mi mı mu mü nu nü nı ni da de ta te nın nin nun nün".split())
        return ' '.join(word for word in words if word not in filler).strip()

    @staticmethod
    def _clock_answer(lowered):
        """Date/time questions are answered locally; web models may refuse them."""
        import datetime
        plain=lowered.replace('\u0307','')
        now=datetime.datetime.now()
        days=['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar']
        months=['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık']
        date=f'{now.day} {months[now.month-1]} {now.year} {days[now.weekday()]}'
        if re.search(r'saat ka[cç]|saat ne|saati söyle',plain):
            return f'Saat {now:%H:%M}.'
        if re.search(r'(bug[uü]n|hangi) (g[uü]nde|g[uü]n|tarih)|bug[uü]n ay[ıi]n ka[cç]|tarih ne|g[uü]nlerden ne|hangi g[uü]ndeyiz',plain):
            return f'Bugün {date}.'
        return ''
    @staticmethod
    def _plain(value):
        table=str.maketrans('çğıöşüâîû','cgiosuaiu')
        return re.sub(r'[^a-z0-9]','',str(value).casefold().replace('\u0307','').translate(table))
    def _lookup(self,place):
        """Return a geocoded place only when the result really matches the words."""
        key=place.strip().casefold()
        if not key:return None
        if key in self.weather_locations:return self.weather_locations[key]
        try:
            response=requests.get('https://geocoding-api.open-meteo.com/v1/search',params={'name':place,'count':5,'language':'tr','format':'json'},timeout=20)
            response.raise_for_status()
            results=response.json().get('results',[])
        except (requests.RequestException,ValueError):return None
        query=self._plain(place)
        for loc in results:
            names=[loc.get('name',''),loc.get('admin1',''),loc.get('admin2','')]
            if any(query and (self._plain(n).startswith(query) or query.startswith(self._plain(n)) and len(self._plain(n))>=3) for n in names if n):
                self.weather_locations[key]=loc;self.weather_locations[loc['name'].casefold()]=loc
                return loc
        return None
    def _weather(self,place,tomorrow=False,loc=None):
        loc=loc or self._lookup(place)
        if loc is None:
            return f'{place} için hava durumu bulunamadı.'
        self.weather_city=loc['name']
        response=requests.get('https://api.open-meteo.com/v1/forecast',params={'latitude':loc['latitude'],'longitude':loc['longitude'],'current':'temperature_2m,weather_code','daily':'temperature_2m_max,temperature_2m_min,precipitation_probability_max','timezone':'auto','forecast_days':2},timeout=20)
        response.raise_for_status()
        data=response.json(); day=1 if tomorrow else 0
        daily=data['daily']; current=data['current']
        code=current['weather_code']
        desc='açık' if code==0 else 'parçalı bulutlu' if code<=2 else 'bulutlu' if code==3 else 'sisli' if code<=48 else 'yağışlı' if code<71 else 'karlı' if code<85 else 'sağanaklı'
        probability=daily['precipitation_probability_max'][day]
        rain='Yağmur beklenmiyor.' if probability<10 else 'Yağmur ihtimali düşük.' if probability<30 else 'Yağmur ihtimali var.' if probability<60 else 'Yağmur olasılığı yüksek.'
        if tomorrow:return f"{loc['name']} için yarın {daily['temperature_2m_min'][day]:.0f}–{daily['temperature_2m_max'][day]:.0f} derece. "+rain
        return f"{loc['name']} için şu an {current['temperature_2m']:.0f} derece, {desc}. "+rain

    def _codex(self,text):
        executable=codex_path()
        if not executable: raise RuntimeError('Codex CLI bulunamadı. Ayarlardan OpenAI API seçebilir veya Codex kurabilirsiniz.')
        prompt=(f'Sen {self._karakter_adi()} adlı masaüstü sesli asistanısın. '+'Kullanıcıyla doğal Türkçe konuş. '
                'Türkçe düşünülmüş gibi akıcı, gündelik ve anlaşılır cümleler kur; kelime kelime çeviri gibi ifadelerden kaçın. '
                'Sen diye hitap et. İlk cümlede soruya doğrudan cevap ver. Selamı her yanıtta tekrarlama, kendini tanıtma. '
                'Varsayılan yanıtın bir veya iki kısa cümle olsun. Kullanıcı ayrıntı isterse genişlet. Kendiliğinden tarih, kaynak adı veya gereksiz teknik bilgi sayma. '
                'Konuşma geçmişindeki şehir, tercih ve takip sorularını kullan; belirsizlik varsa tek net soru sor. '
                'Sesli okunacak metinde tablo, emoji ve Markdown kullanma; doğal duraklar için noktalama kullan. '
                'Gerçekten erişmediğin ekranı gördüğünü veya bilgisayarda işlem yaptığını söyleme. '
                'Dosya okuma veya terminal komutu çalıştırma. Güncel bilgi gerektiğinde web araması kullan.\n')
        prompt+='Önceki konuşma: '+json.dumps(self.history,ensure_ascii=False)+'\nKullanıcı: '+text
        sandbox=self.data_dir/'conversation'; sandbox.mkdir(exist_ok=True)
        command=[executable,'exec','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','--ephemeral','--json','-c','web_search="cached"','-c','model_reasoning_effort="low"','-C',str(sandbox),'-']
        result=subprocess.run(command,input=prompt,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150,**HIDDEN)
        messages=[]
        for line in result.stdout.splitlines():
            try:
                event=json.loads(line)
                item=event.get('item',{})
                if event.get('type')=='item.completed' and item.get('type')=='agent_message': messages.append(item.get('text',''))
            except ValueError: pass
        if result.returncode or not messages:
            detail=(result.stderr or result.stdout)[-1500:]
            if 'login' in detail.lower() or '401' in detail: raise RuntimeError('Codex oturumu açık değil. Ayarlardaki Codex ile giriş düğmesini kullanın.')
            raise RuntimeError('Codex yanıt veremedi: '+detail)
        return messages[-1]
