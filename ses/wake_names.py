"""Explicit name pronunciations shared by local recognition and command parsing.

No fuzzy substring matching; syllable sequences must match in their entirety.
"""
import unicodedata

# G-A2 (18 Kas): karakter okunuşları koddan çıkarıldı → her karakterin karakter.json "okunuslar" alanı
# (karakterler.okunuslar()). Burada yalnız programın kendi adı ve modele bağlı olmayan genel okunuşlar kalır.
GENEL_OKUNUSLAR={'yumi':('you me',),'kai':(),'cat':('ket','katt'),'david':('davit','deyvid')}

def _okunuslar():
 sonuc=dict(GENEL_OKUNUSLAR)
 try:
  import karakterler
  for k,v in karakterler.okunuslar().items():sonuc[k]=tuple(dict.fromkeys(sonuc.get(k,())+tuple(v)))
 except Exception:pass
 return sonuc

def __getattr__(ad):
 if ad=='PRONUNCIATIONS':return _okunuslar()
 if ad=='ENGLISH_NAMES':return set(_okunuslar())-{'david'}
 raise AttributeError(ad)

def normalized(value):
 return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold().replace('ı','i')) if not unicodedata.combining(c))

def aliases(name):
 lowered=name.strip().replace('I','ı').replace('İ','i').lower();key=normalized(lowered)
 first=key.split()[0] if ' ' in key else key
 okunus=_okunuslar()
 return tuple(dict.fromkeys((lowered,key,first,*okunus.get(key,()),*okunus.get(first,()))))

def ses_anahtari(kelime):
 """B06: Türkçe okunuş anahtarı. Whisper adı nasıl yazarsa yazsın (Shani/Şani/Sani, Kaito/Kayto,
 Keira/Keyra, Lyra/Lira, Clara/Klara, Eddy/Edi, Triss/Tris, Syanna/Siyana, Victoria/Viktorya) aynı anahtara iner."""
 import re
 k=kelime.replace('I','ı').replace('İ','i').lower()
 for a,b in (('sh','ş'),('ch','ç'),('ph','f'),('th','t'),('ck','k'),('qu','kv'),('q','k'),('w','v'),('x','ks')):k=k.replace(a,b)
 k=re.sub(r'c(?=[aouılrkt]|$)','k',k)                                    # Clara -> klara (Türkçe c'ye dokunmaz: ciri)
 k=normalized(k)                                                          # ş->s, ç->c, ğ->g, ı/i->i, ö->o, ü->u
 k=re.sub(r'(?<=[aeiou])y(?=[^aeiou]|$)','i',k)                           # kayto/keyra -> kaito/keira
 k=re.sub(r'(?<=[^aeiou])y','i',k)                                        # lyra/eddy/viktorya/syanna -> lira/eddi/viktoria/sianna
 k=re.sub(r'iy(?=[aeiou])','i',k)                                         # siyana -> siana
 k=re.sub(r'(.)\1+',r'\1',k)                                              # triss/eddi/yennefer -> tris/edi/yenefer
 return k

def ad_anahtarlari(name):
 """Bir karakter adının tüm tek kelimelik okunuşlarının Türkçe okunuş anahtarları."""
 return {ses_anahtari(a) for a in aliases(name) if a and ' ' not in a}
