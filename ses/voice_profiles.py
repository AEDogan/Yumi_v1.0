"""Persist each character's voice preferences without guessing VRM gender."""
from app_paths import migrated_default_name
VOICE_CATALOG=[('Kore', 'female', 'net'), ('Puck', 'male', 'canlı'), ('Charon', 'male', 'anlatıcı'), ('Aoede', 'female', 'havadar'), ('Fenrir', 'male', 'coşkulu'), ('Leda', 'female', 'genç tını'), ('Zephyr', 'female', 'parlak'), ('Orus', 'male', 'kararlı'), ('Callirrhoe', 'female', 'rahat'), ('Autonoe', 'female', 'parlak'), ('Enceladus', 'male', 'nefesli'), ('Iapetus', 'male', 'net'), ('Umbriel', 'male', 'rahat'), ('Algieba', 'male', 'akıcı'), ('Despina', 'female', 'akıcı'), ('Erinome', 'female', 'net'), ('Algenib', 'male', 'pürüzlü'), ('Rasalgethi', 'male', 'anlatıcı'), ('Laomedeia', 'female', 'neşeli'), ('Achernar', 'female', 'yumuşak'), ('Alnilam', 'male', 'kararlı'), ('Schedar', 'male', 'dengeli'), ('Gacrux', 'female', 'olgun'), ('Pulcherrima', 'female', 'dışa dönük'), ('Achird', 'male', 'samimi'), ('Zubenelgenubi', 'male', 'gündelik'), ('Vindemiatrix', 'female', 'nazik'), ('Sadachbia', 'male', 'hareketli'), ('Sadaltager', 'male', 'bilgili'), ('Sulafat', 'female', 'sıcak')]
GEMINI_VOICE_NAMES=tuple(n for n,_,_ in VOICE_CATALOG)
from xtts_speech import voices as xtts_voices,kanonik
FAST_VOICES=xtts_voices()  # G-A2 (18 Kas): Edge TTS kaldırıldı; tüm sesler yerel XTTS
# 12 Kasım: RVC sesleri kaldırıldı (tüm karakterler XTTS; modeller _silinecek'te).
VOICES=FAST_VOICES + [(f'Gemini Live · {n} · {"Kadın" if g=="female" else "Erkek"} · {label}',f'gemini-live:{n}',g) for n,g,label in VOICE_CATALOG]
OPENAI_VOICES=['marin','cedar','coral','nova','shimmer','alloy','ash','ballad','echo','fable','onyx','sage','verse']
# G-A2 (18 Kas): sabit (değiştirilemez) ses profilleri koddan çıkarıldı → karakter.json gorunumler[].profil
# (karakterler.sabit_profil). Varsayılan ses: karakterin kendi sesi (karakter.json "ses"), yoksa varsayılan Yumi sesi.
def __getattr__(ad):
 if ad=='WITCHER_IMMUTABLE_VOICES':return sabit_profiller()  # eski çağıranlar
 raise AttributeError(ad)

def sabit_profiller():
 import karakterler
 return {k:p for k in karakterler.dizin()['gorunum'] if (p:=karakterler.sabit_profil(k))}

def varsayilan_ses(key=None):
 """Görünümün kendi karakter sesi (model adlı anahtar), yoksa varsayılan Yumi sesi (modelsiz kurulum)."""
 from dagitim import SISTEM_SESI
 import karakterler
 kayit=karakterler.gorunum(key) if key else None
 if kayit:
  from xtts_speech import model_sesleri
  if kayit['klasor'].name.casefold() in model_sesleri():return 'xtts:'+kayit['klasor'].name.casefold()
 return SISTEM_SESI

def profile(settings,key=None):
 key=key or settings['skin']
 import karakterler
 sabit=karakterler.sabit_profil(key) if key else None
 if sabit:
  res=dict(sabit);res['speech_voice']=kanonik(res['speech_voice'])
  res['wake_alias']=res['name'].split()[0]
  saved=settings.get('voice_profiles',{}).get(key)
  if isinstance(saved,dict) and 'speech_rate' in saved:res['speech_rate']=saved['speech_rate']  # ses sabit, hız kullanıcının
  return res
 saved=settings.get('voice_profiles',{}).get(key)
 from skins import default_name
 name=default_name(key)
 if isinstance(saved,dict):
  result={**{'name':name,'gender':'female','speech_voice':varsayilan_ses(key),'voice':'marin','adult':False},**saved}
  # Preserve the named voice in old profiles; the previous "any" catalog
  # allowed a contradictory gender filter to be saved alongside it.
  result['name']=name
  result['wake_alias']=''
  result['speech_voice']=kanonik(result['speech_voice'])  # ADLANDIRMA (13 Kasım): eski ses anahtarı → model adlı
  result.setdefault('size',settings.get('size',100) if key==settings['skin'] else 100)
  actual=next((g for _,v,g in VOICES if v==result['speech_voice']),None)
  if actual and result['gender']!='any':result['gender']=actual
  return result
 voice=kanonik(settings.get('speech_voice',varsayilan_ses(key)) if key==settings['skin'] else varsayilan_ses(key))
 gender=next((g for _,v,g in VOICES if v==voice),'female')
 return {'name':name,'gender':'female' if gender=='any' else gender,'speech_voice':voice,'voice':settings.get('voice','marin'),'adult':False,'size':settings.get('size',100) if key==settings['skin'] else 100}
def apply_profile(settings,key):
 # Kullanıcı (10 Kasım): model değişince önceki modelin boyu korunur, varsayılana dönmez.
 boy=int(settings.get('size',100))
 previous=profile(settings);previous['size']=boy;settings.setdefault('voice_profiles',{})[settings['skin']]=previous
 saved=profile(settings,key);saved['size']=boy
 settings['skin']=key;settings.update(speech_voice=saved['speech_voice'],voice=saved.get('voice','marin'),size=boy);settings['voice_profiles'][key]=saved
 konusma_hizi_uygula(saved.get('speech_rate',1.0))
 return saved

def konusma_hizi_uygula(carpan):
 """Etkin modelin konuşma hızını XTTS üretimine uygular (12 Kasım, Model sayfası)."""
 import xtts_speech
 xtts_speech.hiz_ayarla(carpan)

def character_name(settings):
 return str(profile(settings).get('name','Yumi')).strip() or 'Yumi'

_SIK_KELIME={"sanki","sakin","kayit","lirai","kiraz","yemin","miras","seyir","siyah","sanal","viral","vitam","klasik","kalma","kaldi"}

def _mesafe(a,b):
 """Levenshtein uzaklığı (kısa adlar için)."""
 onceki=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  simdi=[i]
  for j,y in enumerate(b,1):simdi.append(min(onceki[j]+1,simdi[j-1]+1,onceki[j-1]+(x!=y)))
  onceki=simdi
 return onceki[-1]

def wake_command(text,name,bas=3):
 """Adla çağırma (B06): ad, sözün ilk `bas` kelimesi içinde ve Türkçe okunuş anahtarıyla eşleşmeli
 ("Şani, yarın hava nasıl?", "hey Kayto ışığı kapat"). Cümle ortasında geçen ad ("50 lira", "Amerika") uyandırmaz.
 Döner: (tanındı, adın arkasındaki komut)."""
 import re
 from wake_names import ad_anahtarlari,ses_anahtari
 anahtarlar=ad_anahtarlari(name)
 def yakin(k):
  # Whisper adı bir harf farklı yazabiliyor (Siana/Sienna, Yennefer/Yenefir): yalnız 5+ harfli adlarda 1 harf farkı;
  # kısa adlarda gündelik kelimelere (sana, şanlı) benzeme riski yüksek, orada yalnız tam okunuş eşleşmesi.
  if k in anahtarlar:return True
  if len(k)<5 or k in _SIK_KELIME:return False
  for a in anahtarlar:
   if len(a)>=5 and abs(len(a)-len(k))<=1 and _mesafe(a,k)<=1:return True
  return False
 for i,m in enumerate(re.finditer(r"[^\W\d_]+",text)):
  if i>=bas:break
  if yakin(ses_anahtari(m.group(0))):
   kalan=re.sub(r"^['’][^\W\d_]+","",text[m.end():])  # "Kaito'ya sor" -> "sor"
   return True,kalan.lstrip(" ,:;!?.'’-")
 return False,''

def ad_artigini_ayikla(text,name):
 """Erken denetim adı duyup son tanıma adı kesik yazdığında ("Akira" -> "Kira hava durumu...") baştaki ad artığını at
 (12 Kasım: "Kira" konum sanılıp "Kira'da hava..." okundu). Ad artığı: adın 3+ harflik baş/son parçası ya da 1 harf farkı."""
 import re
 from wake_names import ad_anahtarlari,ses_anahtari
 anahtarlar=ad_anahtarlari(name)
 m=re.match(r"\s*(?:hey\s+|hi\s+)?([^\W\d_]+)['’]?[^\W\d_]*",text,re.I)
 if not m:return text
 k=ses_anahtari(m.group(1))
 for a in anahtarlar:
  if len(k)>=3 and len(a)-len(k)<=2 and (a.endswith(k) or a.startswith(k)) or (len(k)>=3 and _mesafe(a,k)<=1):
   return text[m.end():].lstrip(" ,:;!?.'’-")
 return text

def refresh_voices():
 FAST_VOICES[:]=xtts_voices()
 VOICES[:]=FAST_VOICES+[(f'Gemini Live · {n} · {"Kadın" if g=="female" else "Erkek"} · {label}',f'gemini-live:{n}',g) for n,g,label in VOICE_CATALOG]
