"""Use the user's default Chromium browser and real chat website, without API keys.

Only a dedicated Yumi profile is controlled; personal tabs and cookies are untouched.
The debugging endpoint is local and disappears when the owned process exits.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import winreg
from urllib.parse import urlparse

import requests
from websockets.sync.client import connect
from browser_runtime import BackgroundBrowser
from web_connection import WebConnectionError,status_for

SITES={'chatgpt-web':'https://chatgpt.com/','gemini-web':'https://gemini.google.com/?hl=tr'}


# Kullanıcı kuralı (12 Kasım 17:37): Gemini'de sık yeni sohbet açmak "olağan dışı trafik" (google.com/sorry) doğuruyor.
# Yeni sohbet en çok saatte bir; normalde hep aynı sohbet sürdürülür. Tüm BrowserChat örnekleri (testler dahil) bu
# ortak dosyayı kullanır: data/gemini-sohbet-siniri.json {saglayici: {url, yeni}}.
YENI_SOHBET_ARALIK_S = 3600
def _kok():
    p = Path(__file__).resolve().parent
    while p.parent != p and not (p / 'yumi_yollar.py').exists(): p = p.parent
    return p
try:
    from app_paths import data_dir as _data_dir  # G-A2: veri alanı (kurulumda %LOCALAPPDATA%\\Yumi\\data)
    SOHBET_SINIRI = _data_dir() / 'gemini-sohbet-siniri.json'
except Exception:
    SOHBET_SINIRI = _kok() / 'data' / 'gemini-sohbet-siniri.json'
def sohbet_adresi(url):
    return bool(url) and bool(re.search(r'/(app|c)/[0-9a-zA-Z_-]{6,}', urlparse(url).path or ''))
def _siniri_oku():
    try: return json.loads(SOHBET_SINIRI.read_text(encoding='utf-8'))
    except (OSError, ValueError): return {}
def _siniri_yaz(veri):
    try:
        SOHBET_SINIRI.parent.mkdir(parents=True, exist_ok=True); t = SOHBET_SINIRI.with_suffix('.tmp')
        t.write_text(json.dumps(veri, ensure_ascii=False), encoding='utf-8'); t.replace(SOHBET_SINIRI)
    except OSError: pass
def sohbet_kaydet(saglayici, url):
    if not sohbet_adresi(url): return
    veri = _siniri_oku(); g = veri.get(saglayici) or {}
    if g.get('url') == url: return
    g['url'] = url
    if url not in g.get('gorulen', []):  # daha önce görülmemiş adres = yeni sohbet açıldı
        g['yeni'] = time.time(); g['gorulen'] = (g.get('gorulen', []) + [url])[-20:]
        __import__('logging').getLogger('yumi.web').warning('Yeni web sohbeti acildi (%s)', saglayici)
    veri[saglayici] = g; _siniri_yaz(veri)
def son_sohbet(saglayici):
    g = _siniri_oku().get(saglayici) or {}
    return g.get('url') if sohbet_adresi(g.get('url')) else None
def yeni_sohbet_serbest(saglayici):
    g = _siniri_oku().get(saglayici) or {}
    return time.time() - float(g.get('yeni', 0) or 0) >= YENI_SOHBET_ARALIK_S
# B10 (kullanıcı onayı, 9 Kasım): eski "sadece yazıyla" ifadesi Gemini'ye "ses çıkaramıyorum" dedirtiyordu.
# 19 Kas (kullanıcı): seçili karakter kendi ağzıyla konuşur ("merhaba ben Akira"); ad her soruda gider, karakter değişince sohbet ortasında da geçerli.
VOICE_HINT='(Adın {ad}; sesli asistan {ad} olarak, kendi adınla cevap ver ve kendini başka bir adla tanıtma. Cevabın karakter sesiyle sesli okunacak. Türkçe, kısa ve konuşur gibi; madde işareti, emoji ve biçimlendirme yok. Yazım kurallarına uy: Türkçe harfler, cümle başı büyük harf, her cümle nokta, soru ya da ünlem işaretiyle bitsin.)'
SESSION_PROMPT='Sen sesli asistan {ad} adlı karaktersin; cevapların karakter sesiyle sesli okunuyor, yani konuşabiliyorsun. Türkçe, kısa ve konuşur gibi cevap ver; madde işareti, emoji ve biçimlendirme kullanma. Bu tercih için yalnızca «Tamam.» yaz.'
HIDDEN={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}

class MessageNotSubmitted(RuntimeError):
    def __init__(self,message,text):
        super().__init__(message)
        self.retry_text=text

class ConversationCancelled(RuntimeError):
    pass

def normal_browser_pids(directory):
    """Find only ordinary browser roots using Yumi's exact dedicated profile."""
    if os.name!='nt':return []
    import base64
    argument=subprocess.list2cmdline(['--user-data-dir='+str(directory)]).replace("'","''")
    script=("$yumiArgument='"+argument+"'; Get-CimInstance Win32_Process | Where-Object { "
            "$_.Name -in @('chrome.exe','msedge.exe','brave.exe','opera.exe','vivaldi.exe','chromium.exe') "
            "-and $_.CommandLine -notmatch '--type=|--headless' "
            "-and ($_.CommandLine.Contains($yumiArgument+' ') -or $_.CommandLine.EndsWith($yumiArgument)) "
            "} | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress")
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode('ascii')],capture_output=True,text=True,timeout=8,**HIDDEN)
    if result.returncode:raise RuntimeError('Yumi giriş penceresinin durumu kontrol edilemedi.')
    values=json.loads(result.stdout) if result.stdout.strip() else []
    return [int(value) for value in (values if isinstance(values,list) else [values])]

def pencere_basliklari(pids):
    """Yumi giriş penceresinin (yalnız verilen süreçler) görünür üst pencere başlıkları. Sayfa içeriği okunmaz."""
    if os.name!='nt' or not pids:return []
    import ctypes
    from ctypes import wintypes
    user32=ctypes.windll.user32
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    hedef=set(pids);out=[]
    def topla(hwnd,_):
        owner=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value in hedef and user32.IsWindowVisible(hwnd):
            buf=ctypes.create_unicode_buffer(512);user32.GetWindowTextW(hwnd,buf,512)
            if buf.value:out.append(buf.value)
        return True
    user32.EnumWindows(callback_type(topla),0)
    return out

# Canlı kabul (13 Kasım, kullanıcı): "giriş yapınca pencere kendisi kapansın". Yalnız pencere BAŞLIĞI izlenir:
# önce bir giriş/doğrulama sayfası (Google Hesapları, OpenAI, Oturum aç …) görülür, sonra başlık sağlayıcının sohbet
# sayfasına (Gemini / ChatGPT) döner ve 3 sn öyle kalırsa giriş bitmiş sayılır. Zaten girişliyse kendiliğinden kapanmaz.
GIRIS_BASLIK=re.compile(r"(google hesap|google account|oturum a[cç]|sign in|log ?in|giri[sş] yap|openai|auth|do[gğ]rula|verify|"
                        r"[sş]ifre|password|hesap se[cç]|choose an account|bir dakika|just a moment|cloudflare|kay[ıi]t ol|sign up)",re.I)
SAGLAYICI_BASLIK={'chatgpt-web':re.compile(r"chatgpt",re.I),'gemini-web':re.compile(r"gemini",re.I)}

def giris_bekle(directory,provider,sure=900,devam=lambda:True):
    """Giriş tamamlanınca True; pencere kapanır/süre dolar/devam() False olursa None."""
    desen=SAGLAYICI_BASLIK.get(provider)
    if desen is None:return None
    basla=time.monotonic();pids=[];son_pid=0.;giris_goruldu=False;sabit=None
    while time.monotonic()-basla<sure and devam():
        if not pids or time.monotonic()-son_pid>15:
            try:pids=normal_browser_pids(directory)
            except Exception:pids=pids or []
            son_pid=time.monotonic()
            if not pids and time.monotonic()-basla>20:return None
        basliklar=pencere_basliklari(pids)
        if any(GIRIS_BASLIK.search(b) for b in basliklar):
            giris_goruldu=True;sabit=None
        elif giris_goruldu and any(desen.search(b) for b in basliklar):
            sabit=sabit or time.monotonic()
            if time.monotonic()-sabit>=3:return True
        else:sabit=None
        time.sleep(1.)
    return None

def close_browser_windows(pid):
    """Request normal window closure; never terminate a login process."""
    import ctypes
    from ctypes import wintypes
    user32=ctypes.windll.user32
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    def close(hwnd,_):
        owner=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user32.IsWindowVisible(hwnd):user32.PostMessageW(hwnd,0x0010,0,0)
        return True
    user32.EnumWindows(callback_type(close),0)

def browser_running(pid):
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.windll.kernel32;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return False
    try:
        code=wintypes.DWORD();return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(handle)

def short_reply(text):
    ends=list(re.finditer(r'(?<!\d)[.!?]+["”’\']*(?=\s|$)',text))
    return (text[:ends[4].end()],True) if len(ends)>=5 else (text,False)

def default_browser():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            prog_id=winreg.QueryValueEx(key,'ProgId')[0]
    except OSError:
        raise RuntimeError('Windows varsayılan tarayıcısı belirlenemedi.') from None
    command=''
    for hive,prefix in ((winreg.HKEY_CURRENT_USER,'Software\\Classes\\'),(winreg.HKEY_LOCAL_MACHINE,'Software\\Classes\\')):
        try:
            with winreg.OpenKey(hive,prefix+prog_id+r'\shell\open\command') as key:
                command=winreg.QueryValueEx(key,'')[0];break
        except OSError:pass
    match=re.match(r'^\s*"([^"]+\.exe)"',command,re.I)
    executable=Path(os.path.expandvars(match.group(1))) if match else None
    if executable is None or not executable.exists():
        known={'chromehtml':Path(os.environ.get('PROGRAMFILES',''))/'Google/Chrome/Application/chrome.exe',
               'msedgehtm':Path(os.environ.get('PROGRAMFILES(X86)',''))/'Microsoft/Edge/Application/msedge.exe'}
        executable=next((path for name,path in known.items() if prog_id.lower().startswith(name) and path.exists()),None)
    if executable is None:raise RuntimeError('Varsayılan tarayıcının çalıştırılabilir dosyası bulunamadı.')
    if executable.name.lower() not in ('chrome.exe','msedge.exe','brave.exe','opera.exe','vivaldi.exe','chromium.exe'):
        raise RuntimeError('Varsayılan tarayıcı '+executable.name+'. Görünmez bağlantı şu anda Chromium tabanlı tarayıcıları destekliyor.')
    return executable

# DOM state is read from the visible site's own composer and assistant responses.
# There is no private service endpoint, cookie export or authentication bypass.
DOM = r"""(() => {
 const visible = e => !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
 const text = e => String(e?.innerText ?? e?.textContent ?? '').trim();
 const first = selectors => selectors.flatMap(s=>[...document.querySelectorAll(s)]).find(visible);
 const gemini = location.hostname.endsWith('gemini.google.com');
 const editor = first(gemini ? ['rich-textarea [contenteditable="true"]','[contenteditable="true"][role="textbox"]','textarea'] : ['#prompt-textarea','[contenteditable="true"][data-lexical-editor="true"]','textarea[data-id="root"]','[contenteditable="true"][role="textbox"]','textarea']);
 const oldReplies = [...document.querySelectorAll(gemini ? 'model-response' : '[data-message-author-role="assistant"]')].filter(visible);
 const replies = oldReplies.length ? oldReplies : [...document.querySelectorAll(gemini ? 'message-content, .model-response-text' : '[data-markdown-text-style="assistant-message"]')].filter(visible);
 window.__yumiReplyIds ||= new WeakMap();window.__yumiReplySerial ||= 0;
 const replyId=e=>{if(!e)return null;if(!window.__yumiReplyIds.has(e))window.__yumiReplyIds.set(e,++window.__yumiReplySerial);return window.__yumiReplyIds.get(e);};
 const texts = replies.map(e => {
   const content=e.querySelector('.markdown, message-content, .model-response-text') || e;
   if(!gemini)return text(content);
   const paragraphs=[...content.querySelectorAll('p')].filter(visible).map(p=>{
     const copy=p.cloneNode(true);copy.querySelectorAll('button,[role="button"],svg').forEach(n=>n.remove());return text(copy);
   }).filter(Boolean);
   return paragraphs.length ? paragraphs.join('\n') : text(content);
 });
 const buttons = [...document.querySelectorAll('button')].filter(visible);
 const stop = buttons.find(b=>/^(stop|stop generating|stop response|yanıtı durdur|durdur|üretimi durdur)$/i.test((b.getAttribute('aria-label')||b.getAttribute('title')||b.innerText).trim()) || b.matches('[data-testid="stop-button"],.stop-button'));
 const send = first(['button[data-testid="send-button"]','#composer-submit-button','button[aria-label="Send prompt"]','button[aria-label="Send message"]','button[aria-label="Mesaj gönder"]','button[aria-label="Gönder"]','button.send-button']);
 const login=[...buttons,...document.querySelectorAll('a')].some(e=>visible(e) && /^(sign in|log in|login|oturum aç|oturum açın|giriş yap)$/i.test(text(e)));
 const verification=/^https:\/\/(www\.)?google\.[^/]+\/sorry\//.test(location.href) || /just a moment|bir dakika lütfen|verify you are human|insan olduğunuzu|olağan dışı trafik|unusual traffic/i.test((document.title||'')+' '+text(document.body));
 return {editor:!!editor, login, verification, reply_id:replyId(replies.at(-1)),count:texts.length, text:texts.at(-1)||'', busy:!!stop, vis:document.visibilityState, stop_label:stop?String(stop.getAttribute('aria-label')||stop.innerText||'').trim().slice(0,40):'', draft:editor ? String(editor.value ?? editor.innerText ?? editor.textContent ?? '').trim() : '', users:document.querySelectorAll(gemini ? 'user-query, user-query-content' : '[data-message-author-role="user"], [data-user-message-bubble]').length, send:!!send && !send.disabled, url:location.href};
})()"""

SEND = r"""((text) => {
 const visible = e=>!!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
 const gemini=location.hostname.endsWith('gemini.google.com');
 const selectors=gemini?['rich-textarea [contenteditable="true"]','[contenteditable="true"][role="textbox"]','textarea']:['#prompt-textarea','[contenteditable="true"][data-lexical-editor="true"]','textarea[data-id="root"]','[contenteditable="true"][role="textbox"]','textarea'];
 const editor=selectors.flatMap(s=>[...document.querySelectorAll(s)]).find(visible);
 if(!editor) return false;
 editor.focus();
 if(editor.tagName==='TEXTAREA') {
   Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(editor,text);
   editor.dispatchEvent(new Event('input',{bubbles:true}));
 } else {
   const range=document.createRange();range.selectNodeContents(editor);
   const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
   document.execCommand('insertText',false,text);
   editor.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
 }
 return true;
})"""

CLICK_SEND = r"""(() => {
 const b=[...document.querySelectorAll('button[data-testid="send-button"],#composer-submit-button,button[aria-label="Send prompt"],button[aria-label="Send message"],button[aria-label="Mesaj gönder"],button[aria-label="Gönder"],button.send-button')].find(b=>b.offsetWidth && !b.disabled);
 if(b){const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};} return null;
})()"""

KOPMA_IZLERI=('Tarayıcı bağlantısı','Sohbet sayfası okunamadı','Varsayılan tarayıcı arka planda başlatılamadı','Tarayıcı başlaması zaman aşımına')

STOP = r"""(() => {
 const b=[...document.querySelectorAll('button')].find(b=>b.offsetWidth && (b.matches('[data-testid="stop-button"],.stop-button') || /^(stop|stop generating|stop response|yanıtı durdur|durdur|üretimi durdur)$/i.test((b.getAttribute('aria-label')||b.getAttribute('title')||b.innerText).trim())));
 if(b)b.click();return !!b;
})()"""

class BrowserChat:
    karakter_adi='Yumi'  # backend her sorudan önce seçili karakterin adını yazar (19 Kas)
    def __init__(self,data_dir,isolated=False):
        self.directory=Path(data_dir)/'browser-profile';self.process=None;self.socket=None
        self.owns_browser=False;self.isolated=isolated
        self.lock=threading.RLock();self.sequence=0;self.provider=None;self.headed=False;self.url=None;self.urls={}
        self.cancel_event=threading.Event()
        self.conversation_scope=None
        self.status=status_for('', 'unavailable')
        self.target_id=None
        self.http=requests.Session();self.http.trust_env=False
        self.urls_file=Path(data_dir)/'browser-conversations.json'
        self.preferences_file=Path(data_dir)/'browser-preferences.json';self.prepared={}
        try:
            saved=json.loads(self.urls_file.read_text(encoding='utf-8'))
            self.urls={key:url for key,url in saved.items() if key in SITES and isinstance(url,str) and urlparse(url).hostname==urlparse(SITES[key]).hostname and urlparse(url).scheme=='https'}
        except (OSError,ValueError,AttributeError):pass
        try:
            saved=json.loads(self.preferences_file.read_text(encoding='utf-8'))
            if saved.get('version')==1 and isinstance(saved.get('conversations'),dict):self.prepared=saved['conversations']
        except (OSError,ValueError,AttributeError):pass

    def use_conversation(self,scope,urls):
        if scope is None or scope==self.conversation_scope:return
        self.conversation_scope=scope;self.urls=urls;self.url=None;self.provider=None
        # The local chat archive owns these URLs and expires them with the chat.
        self.urls_file=None

    def _hedef(self,provider):
        """Gidilecek adres: bu sohbetin adresi, yoksa en son kullanılan ortak sohbet (yeni sohbet açılmaz); hiç yoksa ana sayfa."""
        url=self.urls.get(provider)
        if sohbet_adresi(url):return url
        return son_sohbet(provider) or SITES[provider]

    def remember_url(self,url):
        if url and urlparse(url).scheme=='https' and urlparse(url).hostname==urlparse(SITES[self.provider]).hostname:
            self.url=url;self.urls[self.provider]=url
            sohbet_kaydet(self.provider,url)
            if self.urls_file is None:return
            temporary=self.urls_file.with_suffix('.tmp');temporary.parent.mkdir(parents=True,exist_ok=True)
            temporary.write_text(json.dumps(self.urls),encoding='utf-8');temporary.replace(self.urls_file)

    def rpc(self,method,params=None,timeout=8):
        if self.socket is None:raise RuntimeError('Tarayıcı bağlantısı yok.')
        self.sequence+=1;request_id=self.sequence
        self.socket.send(json.dumps({'id':request_id,'method':method,'params':params or {}}))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            event=json.loads(self.socket.recv(timeout=max(.01,deadline-time.monotonic())))
            if event.get('id')!=request_id:continue
            if 'error' in event:raise RuntimeError('Tarayıcı bağlantısı: '+event['error'].get('message','hata'))
            return event.get('result',{})
        raise RuntimeError('Tarayıcı bağlantısı zaman aşımına uğradı.')

    def evaluate(self,source):
        # A navigation can briefly remove the page's default JS context.
        # Retry only this explicit pre-execution error, never a timeout or a
        # partially completed submission that could duplicate a user message.
        for attempt in range(3):
            try:
                result=self.rpc('Runtime.evaluate',{'expression':source,'returnByValue':True,'awaitPromise':True});break
            except RuntimeError as error:
                transient=any(s in str(error) for s in ('Cannot find default execution context','Execution context was destroyed','Cannot find context with specified id'))
                if source not in (DOM,CLICK_SEND) or not transient or attempt==2:raise
                time.sleep(.2*(attempt+1))
        if 'exceptionDetails' in result:
            # A read-only page probe can run before its document exists during
            # navigation. Never retry SEND/CLICK or arbitrary JS exceptions.
            detail=result['exceptionDetails'];description=detail.get('exception',{}).get('description','')
            if source==DOM and 'TypeError' in description and any(s in description for s in ('null','undefined')):
                return {}
            raise RuntimeError('Sohbet sayfası okunamadı.')
        return result.get('result',{}).get('value')

    def attach(self,port,provider):
        base=f'http://127.0.0.1:{int(port)}'
        pages=self.http.get(base+'/json/list',timeout=3).json()
        target=self._hedef(provider)
        candidates=[] if self.isolated else [p for p in pages if p.get('type')=='page' and urlparse(p.get('url','')).hostname==urlparse(SITES[provider]).hostname]
        page=next((p for p in candidates if p.get('url')==target),None)
        if page is None and candidates:page=candidates[0]
        if page is None:page=self.http.put(base+'/json/new?'+target,timeout=3).json()
        endpoint=page['webSocketDebuggerUrl']
        if urlparse(endpoint).hostname not in ('127.0.0.1','localhost'):
            raise RuntimeError('Yumi tarayıcı bağlantısı yerel değil.')
        self.socket=connect(endpoint,proxy=None,open_timeout=3,max_size=8*1024*1024,ping_interval=None)
        self.target_id=page.get('id')
        self.provider=provider;self.headed=False
        self.rpc('Page.enable');self.rpc('Runtime.enable')
        self.rpc('Emulation.setFocusEmulationEnabled',{'enabled':True})
        # B03 (12 Kasım): oturum geri yüklenince bağlanılan sekme arka planda kalabiliyor (görünmez → yanıt akışı/çizim
        # durur, "durdur" düğmesi kaybolmaz → is_108'de 120 s zaman aşımı). Bağlanılan sekmeyi öne getir.
        try:self.rpc('Page.bringToFront',timeout=3)
        except Exception:pass
        self.yeni_baglanti=True
        if (self.conversation_scope is not None or sohbet_adresi(target)) and page.get('url')!=target:
            self.rpc('Page.navigate',{'url':target})
        self.url=target if (self.conversation_scope is not None or sohbet_adresi(target)) else page.get('url',target)

    def ensure(self,provider,headed=False):
        if provider not in SITES:raise ValueError('Bilinmeyen web asistanı.')
        # The live CDP connection is authoritative: Chromium's launch process
        # can exit after handing its command to an already running browser.
        if self.socket and self.socket.close_code is None and self.headed==headed and not self.saglikli():
            # B03: soket açık görünse de tarayıcı/sayfa ölmüş veya donmuş → oturumu baştan başlat.
            self._kopma_kaydi('ensure: tarayici yanit vermiyor');self.sifirla(sert=True)
        if self.socket and self.socket.close_code is None and self.headed==headed:
            if self.provider!=provider:
                if self.url:self.urls[self.provider]=self.url
                self.provider=provider;self.url=self._hedef(provider);self.rpc('Page.navigate',{'url':self.url})
            return
        if self.headed and self.process and self.process.poll() is None:
            raise WebConnectionError(self._status('login_open'))
        self.close();executable=default_browser();self.directory.mkdir(parents=True,exist_ok=True)
        portfile=self.directory/'DevToolsActivePort'
        if not headed and portfile.exists():
            try:
                self.attach(int(portfile.read_text().splitlines()[0]),provider)
                return
            except Exception:
                if self.socket:
                    try:self.socket.close()
                    except Exception:pass
                self.socket=None
        if not headed and normal_browser_pids(self.directory):
            self.provider=provider;self.headed=True
            raise WebConnectionError(self._status('login_open'))
        portfile.unlink(missing_ok=True)
        command=[str(executable),'--user-data-dir='+str(self.directory),'--remote-debugging-port=0',
                 '--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check',
                 '--disable-background-timer-throttling','--disable-renderer-backgrounding']
        # A private Windows desktop keeps normal Chromium out of the user's
        # desktop. Sign-in is the only flow that creates an interactive window.
        command+=['--window-size=1200,900','--restore-last-session']
        # Restore existing tabs first; attach selects/creates the provider tab.
        # Appending a URL here would add another tab on every browser restart.
        self.process=BackgroundBrowser(command,self.directory) if not headed else subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**HIDDEN)
        self.owns_browser=True
        self.provider=provider;self.headed=headed
        deadline=time.monotonic()+12
        try:
            while time.monotonic()<deadline:
                if self.process.poll() is not None:raise RuntimeError('Varsayılan tarayıcı arka planda başlatılamadı.')
                if portfile.exists():
                    lines=portfile.read_text().splitlines()
                    if lines:
                        try:
                            response=self.http.get(f'http://127.0.0.1:{int(lines[0])}/json/version',timeout=.5)
                            response.raise_for_status()
                            break
                        except (requests.RequestException,ValueError):pass
                time.sleep(.1)
            else:raise RuntimeError('Tarayıcı başlaması zaman aşımına uğradı.')
            self.attach(int(lines[0]),provider)
        except Exception:
            self.close();raise

    def show_login(self,provider):
        with self.lock:
            if provider not in SITES:raise ValueError('Bilinmeyen web asistanı.')
            if self.headed and self.process and self.process.poll() is None:
                if provider==self.provider:return self._status('login_open')
                raise WebConnectionError(self._status('login_open'))
            self.close();self.directory.mkdir(parents=True,exist_ok=True)
            if normal_browser_pids(self.directory):
                self.provider=provider;self.headed=True
                return self._status('login_open')
            # Authentication happens in a normal browser, without a debugging
            # endpoint or headless/automation flags. Never inspect credentials.
            self.process=subprocess.Popen([str(default_browser()),
                '--user-data-dir='+str(self.directory),'--disable-background-mode','--new-window',SITES[provider]],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**HIDDEN)
            self.provider=provider;self.headed=True;self.url=None
            return self._status('login_open')

    def finish_login(self,provider):
        with self.lock:
            if not self.headed and self.socket and self.socket.close_code is None:
                return self.warm(provider)
            # Close only this profile's explicit sign-in window, flush cookies,
            # then use the same normal browser on the private desktop.
            pids=normal_browser_pids(self.directory)
            for pid in pids:close_browser_windows(pid)
            deadline=time.monotonic()+8
            while any(browser_running(pid) for pid in pids):
                if time.monotonic()>=deadline:
                    raise RuntimeError('Yumi giriş penceresi kapanmayı bekliyor. Açık bir tarayıcı onayını tamamlayıp tekrar dene.')
                time.sleep(.1)
            if pids or self.headed:
                self.process=None;self.headed=False;self.provider=provider
            return self.warm(provider)

    def _status(self,phase):
        import logging
        logger=logging.getLogger('yumi.web');logger.setLevel(logging.INFO)
        if self.status.provider!=self.provider or self.status.phase!=phase:
            logger.info('Web connection provider=%s phase=%s',self.provider,phase)
        self.status=status_for(self.provider,phase)
        return self.status

    def warm(self,provider):
        with self.lock:
            if self.headed:
                if self.process and self.process.poll() is None:
                    return self._status('login_open')
                self.headed=False;self.process=None
            self.ensure(provider)
            self._status('connecting')
            deadline=time.monotonic()+30
            state={}
            while time.monotonic()<deadline:
                state=self.evaluate(DOM) or {}
                # Restored account cookies can resolve after the initial guest
                # shell. Do not report a lost login from that transient frame.
                if state.get('editor') and not state.get('login') and not state.get('verification') and not state.get('busy'):
                    self.remember_url(state.get('url'));return self._status('ready')
                time.sleep(.15)
            return self._status('verification_required' if state.get('verification') else 'login_required' if state.get('login') else 'unavailable')

    def prepare_session(self,state):
        if self.prepared.get(self.provider)==state.get('url'):return
        if not sohbet_adresi(state.get('url')):return  # VOICE_HINT her soruda zaten gidiyor
        self.ask(SESSION_PROMPT.format(ad=self.karakter_adi),_setup=True)
        state=self.evaluate(DOM) or {}
        self.remember_url(state.get('url'))
        self.prepared[self.provider]=state.get('url')
        temporary=self.preferences_file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':1,'conversations':self.prepared}),encoding='utf-8')
        temporary.replace(self.preferences_file)

    def read_aloud(self,on_start=None):
        with self.lock:
            if not self.socket:raise RuntimeError('Ses için açık web sohbeti bulunamadı.')
            text=(self.evaluate(DOM) or {}).get('text','')
            clipped,limited=short_reply(text)
            if limited and clipped.strip()!=text.strip():
                raise RuntimeError('Site yanıtı beş cümleyi aştığı için uzun metnin sesli okuması durduruldu. Yumi’daki kısa yanıtı bir TTS sesiyle dinleyebilirsin.')
            clicked=self.evaluate(r'''(() => {
                window.__yumiVoice={started:false,done:false};
                if(!window.__yumiVoiceHook){
                    window.__yumiVoiceHook=true;
                    const play=HTMLMediaElement.prototype.play;
                    HTMLMediaElement.prototype.play=function(...args){
                        window.__yumiVoice.started=true;window.__yumiVoice.done=false;
                        this.addEventListener('ended',()=>window.__yumiVoice.done=true,{once:true});
                        this.addEventListener('error',()=>window.__yumiVoice.done=true,{once:true});
                        return play.apply(this,args);
                    };
                }
                const gemini=location.hostname.endsWith('gemini.google.com');
                const replies=[...document.querySelectorAll(gemini?'model-response':'[data-message-author-role="assistant"]')];
                let root=replies.at(-1);
                if(root && !gemini)root=root.closest('article')||root.parentElement;
                const button=[...(root||document).querySelectorAll('button')].find(b=>
                    /read aloud|sesli oku|dinle|listen|listen to response/i.test(b.getAttribute('aria-label')||b.getAttribute('title')||b.innerText));
                if(!button)return false;button.click();return true;
            })()''')
            if not clicked:raise RuntimeError('Bu yanıtta sitenin sesli okuma düğmesi bulunamadı. Yumi için bir TTS sesi seçebilirsin.')
            # Explicitly detect an available site control; never substitute another voice.
            state=self.evaluate('window.__yumiVoice')
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                state=self.evaluate('window.__yumiVoice') or {}
                if state.get('started'):break
                time.sleep(.15)
            else:raise RuntimeError('Sitenin sesli okuması başlamadı. Tarayıcıya giriş bölümünde ses düğmesini kontrol et veya Yumi için bir TTS sesi seç.')
            if on_start:on_start()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                state=self.evaluate('window.__yumiVoice') or {}
                if state.get('done'):return
                time.sleep(.15)
            raise RuntimeError('Sitenin sesli okuması tamamlanmadı.')

    def ask(self,text,on_chunk=None,_setup=False,on_status=None):
        with self.lock:
            self.cancel_event.clear()
            original_text=text
            if self.headed:raise WebConnectionError(self._status('login_open'),text)
            state=self._hazir_bekle(text)
            if state.get('busy'):raise RuntimeError('Tarayıcıdaki önceki yanıt hâlâ sürüyor.')
            # Send one request only: a separate preference turn can block the real question.
            if not _setup:
                text=text.strip()+' '+VOICE_HINT.format(ad=self.karakter_adi)
                try:
                    import tur_kaydi;tur_kaydi.olay('istem',saglayici=self.provider,metin=text)
                except Exception:pass
            draft=state.get('draft','').strip()
            if draft and draft not in (original_text.strip(),text.strip()):
                raise MessageNotSubmitted('Web sayfasında başka bir taslak var. Taslağı korumak için yeni mesaj gönderilmedi.',original_text)
            self.remember_url(state.get('url'))
            if on_status:on_status('Mesaj gönderiliyor…')
            baseline=state['count'];old=state['text'];old_reply=state.get('reply_id')
            # Select the composer contents, then use Chromium's real input path.
            # Synthetic input events can leave Angular/React's send state stale.
            focused=self.evaluate(r"""(() => {
                const visible=e=>e && (e.offsetWidth || e.offsetHeight);
                const editor=[...document.querySelectorAll('rich-textarea [contenteditable="true"],#prompt-textarea,[contenteditable="true"][role="textbox"],textarea')].find(visible);
                if(!editor)return false;
                editor.focus();
                if(editor.tagName==='TEXTAREA')editor.select();
                else {const range=document.createRange();range.selectNodeContents(editor);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);}
                return true;
            })()""")
            if not focused:raise RuntimeError('Web sohbetinin mesaj kutusu bulunamadı.')
            self.rpc('Input.insertText',{'text':text[:4000]})
            submitted=False
            send_deadline=time.monotonic()+12
            while time.monotonic()<send_deadline:
                self._check_cancel()
                point=self.evaluate(CLICK_SEND)
                if point:
                    # Send from the focused composer. The native keyboard
                    # path is independent of a responsive button moving
                    # between coordinate sampling and mouse dispatch.
                    self.rpc('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13,'text':'\r','unmodifiedText':'\r'})
                    self.rpc('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
                    submitted=True;break
                time.sleep(.15)
            if not submitted:raise MessageNotSubmitted('Site mesajı göndermeye hazır olmadı. Mesaj kutuda korunuyor; yeniden deneyebilirsin.',original_text)
            # Never submit twice: a slow acknowledgement could duplicate a message.
            ack_deadline=time.monotonic()+15
            while time.monotonic()<ack_deadline:
                self._check_cancel()
                accepted=self.evaluate(DOM) or {}
                if accepted.get('users',0)>state.get('users',0) or accepted.get('busy') or accepted.get('count',0)>baseline:
                    self.remember_url(accepted.get('url'));break
                time.sleep(.15)
            else:raise RuntimeError('Site gönderimi doğrulamadı. Tekrar göndermeden önce web sohbetini kontrol et.')
            if on_status:on_status('Mesaj ulaştı · yanıt bekleniyor…')
            # Gemini can replace search/progress text with a rich result card.
            # Emit only the settled reply so provisional text is never spoken.
            # 13 Kasım (ChatGPT web): ChatGPT de "Düşünüyor/Searching" ara yazısını gerçek yanıtla değiştirebilir →
            # iki sağlayıcıda da yalnız yerleşmiş tam cümleler sese gider (ilk ses yine ilk cümleyle başlar).
            buffered=True
            # B03: Gemini'de yanıt bitmeden, yerleşmiş TAM cümleler sese verilir (arkasından yeni metin gelmiş ve
            # 0,3 sn değişmemiş). Ara durum yazıları (Web'de aranıyor…) hiç okunmaz; son kalan kısım bitişte gelir.
            sent={'metin':'','aday':'','aday_t':0.}
            def settled(current,final=False):
                if not buffered or not on_chunk:return
                if final:hedef=current
                else:
                    sinir=[m.end() for m in re.finditer(r'[.!?…]+["”’)]*\s+(?=\S)',current)]
                    if not sinir:return
                    hedef=current[:sinir[-1]]
                    now=time.monotonic()
                    if hedef!=sent['aday']:sent['aday']=hedef;sent['aday_t']=now;return
                    if now-sent['aday_t']<.3:return
                if not hedef.startswith(sent['metin']):
                    try:
                        import tur_kaydi;tur_kaydi.olay('akis',metin='gemini metni degisti; okunan kisim korunuyor')
                    except Exception:pass
                    return
                parca=hedef[len(sent['metin']):]
                if parca.strip():on_chunk(parca);sent['metin']=hedef
            def finish_reply(value):
                if value:settled(value,final=True)
                self.remember_url(state.get('url'))
                return value
            full='';stable=0.;last_change=time.monotonic();started=False;deadline=time.monotonic()+120
            saw_busy=bool(accepted.get('busy'));idle_since=None
            yeniden_baglandi=False
            while time.monotonic()<deadline:
                self._check_cancel()
                try:state=self.evaluate(DOM) or {}
                except Exception as error:
                    if yeniden_baglandi or not self.kopma_mi(error):raise
                    yeniden_baglandi=True
                    if not self._yanit_bagla():
                        raise ConversationCancelled('Web bağlantısı yanıt sırasında koptu; oturum yeniden kuruluyor, soruyu tekrar sorabilirsin.') from error
                    continue
                current=state.get('text','')
                if buffered and re.fullmatch(r"(?:Web['’]de aranıyor|Web’de aranıyor|Web'de aranıyor|Web.de aranıyor|Searching the web|Searching|Aranıyor|Düşünüyor|Düşünülüyor|Thinking|Thought for .*|.* düşünüldü)[. …]*",current.strip(),re.I):
                    current=''
                current,limit_reached=short_reply(current)
                # A previous long reply can differ from its clipped text.
                # Only a newly added assistant message belongs to this request.
                is_new=state.get('count',0)>baseline or (state.get('reply_id') is not None and state.get('reply_id')!=old_reply)
                if is_new and current:
                    if not started and on_status:on_status('Yanıt geliyor…')
                    started=True
                    if buffered:settled(current)
                    if current!=full:
                        if buffered:
                            pass
                        elif current.startswith(full):
                            delta=current[len(full):]
                            if delta and on_chunk:on_chunk(delta)
                        else:raise RuntimeError('Site yanıt metnini değiştirdi; görünen kısmi yanıt korunuyor.')
                        full=current;last_change=time.monotonic();stable=0.
                    else:stable=time.monotonic()-last_change
                    if limit_reached and self.provider!='gemini-web':
                        self.evaluate(STOP);return finish_reply(full)
                    if not state.get('busy') and stable>.8:
                        return finish_reply(full)
                # The user may stop generation on the website itself. Once
                # its composer is idle, do not wait for a nonexistent reply.
                if state.get('busy'):
                    saw_busy=True;idle_since=None
                elif state.get('busy') is False and state.get('editor'):
                    if idle_since is None:idle_since=time.monotonic()
                    idle_grace=2.0 if saw_busy else 15.0
                    if time.monotonic()-idle_since>idle_grace:
                        raise ConversationCancelled('Web yanıtı tamamlanmadan durdu; yeniden soru sorabilirsin.')
                else:idle_since=None
                if not started and time.monotonic()>deadline-30:
                    self.evaluate(STOP)
                    raise RuntimeError('Mesaj siteye ulaştı fakat yanıt başlamadı. Aynı mesajı tekrar göndermeden önce Ayarlar’dan sohbet sayfasını kontrol et.')
                time.sleep(.08)
            self.evaluate(STOP)
            raise RuntimeError('Web sohbeti zamanında tamamlanmadı; varsa görünen kısmi yanıt korunuyor.')

    # ---- B03 açık iş 2: kopmada kullanıcı müdahalesiz yeniden bağlanma ----
    def saglikli(self):
        """Soket + sahip olunan süreç + sayfa JS'i 3 sn içinde cevap veriyor mu."""
        if not self.socket or self.socket.close_code is not None:return False
        if self.owns_browser and self.process is not None and self.process.poll() is not None:return False
        try:
            return self.rpc('Runtime.evaluate',{'expression':'1','returnByValue':True},timeout=3).get('result',{}).get('value')==1
        except Exception:return False

    @staticmethod
    def kopma_mi(error):
        if isinstance(error,(WebConnectionError,ConversationCancelled,MessageNotSubmitted)):return False
        if isinstance(error,(ConnectionError,TimeoutError,OSError)):return True
        if type(error).__module__.startswith('websockets'):return True
        return isinstance(error,RuntimeError) and str(error).startswith(KOPMA_IZLERI)

    def _kopma_kaydi(self,neden):
        import logging;logging.getLogger('yumi.web').warning('Web baglantisi yeniden baslatiliyor: %s',neden)
        try:
            import tur_kaydi;tur_kaydi.olay('web_kopma',saglayici=self.provider,neden=neden)
        except Exception:pass

    def sifirla(self,sert=False):
        """Bağlantıyı bırakır. sert=True: Yumi profilinin asılı kalan tarayıcısını da kapatır (yalnız bu profil)."""
        self.close()
        if sert and not self.headed:
            try:pids=normal_browser_pids(self.directory)
            except Exception:pids=[]
            for pid in pids:
                try:subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=8,**HIDDEN)
                except Exception:pass
            deadline=time.monotonic()+6
            while pids and any(browser_running(pid) for pid in pids) and time.monotonic()<deadline:time.sleep(.1)
            (self.directory/'DevToolsActivePort').unlink(missing_ok=True)

    def _hazir_bekle(self,text):
        """Gönderimden ÖNCE: bağlan ve mesaj kutusunu bekle. Kopmada bir kez baştan başlatır, takılan sayfayı bir kez yeniler.
        Mesaj henüz gönderilmediği için tekrar denemek mükerrer mesaj üretmez."""
        provider=self.provider or 'chatgpt-web';yenilendi=False
        for deneme in range(2):
            try:
                self.ensure(provider)
                deadline=time.monotonic()+20
                while True:
                    self._check_cancel()
                    state=self.evaluate(DOM) or {}
                    if state.get('verification'):raise WebConnectionError(self._status('verification_required'),text)
                    if state.get('editor') and not state.get('busy') and state.get('url','').startswith(SITES[self.provider].split('?')[0]):
                        if getattr(self,'yeni_baglanti',False):
                            # Yeni (yeniden) bağlantı: geçmiş yüklenirken mesaj sayısı değişir; taban sayı yanlış olmasın.
                            state=self._sayfa_otursun(state)
                            self.yeni_baglanti=False
                        if state.get('editor') and not state.get('busy'):return state
                    if time.monotonic()>=deadline or (state.get('login') and not yenilendi):
                        if not yenilendi:
                            # Donmuş/eskimiş sayfa veya geç çözülen çerez: bir kez yenile.
                            yenilendi=True;self._kopma_kaydi('sayfa hazir degil; yenileniyor')
                            self.rpc('Page.reload',{'ignoreCache':False});time.sleep(1.5)
                            deadline=time.monotonic()+20;continue
                        if state.get('login'):raise WebConnectionError(self._status('login_required'),text)
                        raise WebConnectionError(self._status('unavailable'),text)
                    time.sleep(.15)
            except Exception as error:
                if deneme or not self.kopma_mi(error):raise
                self._kopma_kaydi(f'gonderim oncesi: {type(error).__name__}');self.sifirla(sert=True)
                self.provider=provider
        raise WebConnectionError(self._status('unavailable'),text)

    def _sayfa_otursun(self,state,sure=1.0,en_cok=12.):
        """Sohbet geçmişi yüklenene kadar bekle: mesaj/yanıt sayısı `sure` sn değişmeyince döner (en çok `en_cok` sn)."""
        # is_136: geçmiş, mesaj kutusu göründükten SONRA yükleniyor (count=0 → eski yanıt "yeni" sanıldı, soru kutuda kaldı).
        # Sohbet adresindeysek (/app/<kimlik>) geçmiş görünene kadar da bekle.
        def sohbette(st):return bool(re.search(r'/(app|c)/[0-9a-zA-Z_-]{6,}',st.get('url','') or ''))  # Gemini /app/<id>, ChatGPT /c/<uuid>
        imza=(state.get('count'),state.get('users'),state.get('url'));t=time.monotonic();son=time.monotonic()
        while time.monotonic()-t<en_cok:
            self._check_cancel();time.sleep(.2)
            yeni=self.evaluate(DOM) or {}
            y=(yeni.get('count'),yeni.get('users'),yeni.get('url'))
            if y!=imza:imza=y;son=time.monotonic()
            state=yeni or state
            gecmis_tamam=not sohbette(state) or (state.get('count',0)>0 and state.get('users',0)>0)
            if gecmis_tamam and time.monotonic()-son>=sure and state.get('editor') and not state.get('busy'):break
        return state

    def _yanit_bagla(self):
        """Yanıt beklerken soket koptu: tarayıcı yaşıyorsa yeniden bağlan (mesaj tekrar GÖNDERİLMEZ)."""
        provider=self.provider;self._kopma_kaydi('yanit beklerken')
        try:
            if self.socket:
                try:self.socket.close()
                except Exception:pass
            self.socket=None
            self.ensure(provider);return True
        except Exception:return False

    def denetle(self,provider):
        """Boştaki bekçi: meşgulse dokunmaz (None). Sağlıklıysa durumu döndürür, değilse oturumu baştan kurar."""
        if not self.lock.acquire(blocking=False):return None
        try:
            if self.headed and self.process and self.process.poll() is None:return self._status('login_open')
            if self.provider==provider and self.saglikli():
                try:state=self.evaluate(DOM) or {}
                except Exception:state={}
                if state.get('editor') and not state.get('login') and not state.get('verification'):
                    return self.status if self.status.phase=='ready' else self._status('ready')
                if state.get('busy'):return self.status
            self._kopma_kaydi('bekci: oturum hazir degil')
            if self.socket and not self.saglikli():self.sifirla(sert=True)
            return self.warm(provider)
        finally:self.lock.release()

    def cancel_request(self):
        # UI thread sets a flag only. CDP commands remain on the request worker.
        self.cancel_event.set()

    def _check_cancel(self):
        if self.cancel_event.is_set():
            self.evaluate(STOP)
            raise ConversationCancelled('Yanıt durduruldu; gelen metin korunuyor.')

    def close(self):
        if self.socket:
            try:
                if self.owns_browser:self.rpc('Browser.close')
                elif self.isolated:self.rpc('Page.close')
            except Exception:pass
            try:self.socket.close()
            except Exception:pass
        self.socket=None
        if self.process and self.owns_browser and not self.headed:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:pass
        if isinstance(self.process,BackgroundBrowser):self.process.release()
        self.process=None;self.owns_browser=False
