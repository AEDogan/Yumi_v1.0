"""Karakter adları: kurulu karakterlerin karakter.json'undan (görünüm adı); bir kerelik eski etiket göçü.

G-A2 (18 Kas): eski koda gömülü ad tablosu (NAMES) kaldırıldı; adlar karakter.json 'gorunumler[].ad' alanından gelir.
Göç yalnız KURULU karakterlerin adlarını settings.json'a yazar (modelsiz kurulumda hiçbir karakter adı yazılmaz).
"""
import json,os
from pathlib import Path
REVISION='2026-10-22-approved-1'

def names():
 """{görünüm anahtarı: ad} — kurulu karakterler (+ kuruluysa sprite paketi)."""
 import karakterler
 d=karakterler.dizin()
 sonuc={k:v['gorunum_adi'] for k,v in d['gorunum'].items()}
 if d.get('clippy'):
  from skins import SPRITE
  sonuc.setdefault(SPRITE,d['clippy']['ad'])
 return sonuc

def __getattr__(ad):
 if ad=='NAMES':return names()  # eski çağıranlar
 raise AttributeError(ad)

def migrate(settings):
 if settings.get('character_names_revision')==REVISION:return False
 profiles=settings.setdefault('voice_profiles',{})
 for key,name in names().items():
  saved=profiles.setdefault(key,{})
  if isinstance(saved,dict):saved.update(name=name,wake_alias=name)
 settings['character_names_revision']=REVISION
 return True

def refresh(settings,path=None):
 """Refresh only persisted name fields; leave live voice/UI state intact."""
 if path is None:
  from app_paths import data_dir
  path=data_dir()/'settings.json'
 try:saved=json.loads(Path(path).read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return False
 migrate(saved);changed=False
 settings['character_names_revision']=saved['character_names_revision']
 for key,profile in saved.get('voice_profiles',{}).items():
  if not isinstance(profile,dict):continue
  live=settings.setdefault('voice_profiles',{}).setdefault(key,{})
  if not isinstance(live,dict):continue
  for field in ('name','wake_alias'):
   if field in profile and live.get(field)!=profile[field]:live[field]=profile[field];changed=True
 return changed
