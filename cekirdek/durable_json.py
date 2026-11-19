"""Atomic JSON persistence with one verified recovery copy."""
from __future__ import annotations
import json,os,shutil,warnings
from datetime import datetime,timezone
from pathlib import Path

def _read(path,validator=None):
    with Path(path).open('r',encoding='utf-8') as f:value=json.load(f)
    if validator and not validator(value):raise ValueError('unexpected JSON structure')
    return value

def _preserve(path):
    path=Path(path)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=path.with_name(path.name+'.corrupt-'+stamp)
    try:shutil.copy2(path,target);return target
    except OSError:return None

def load_json(path,default,validator=None):
    path=Path(path);backup=path.with_name(path.name+'.bak')
    if path.exists():
        try:return _read(path,validator)
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            preserved=_preserve(path)
            try:value=_read(backup,validator)
            except (OSError,ValueError,TypeError,json.JSONDecodeError):
                warnings.warn(f'{path.name} geçersiz; özgün dosya {preserved or "korunamadı"}. Yedek de geçerli değil; boş başlangıç kullanılıyor.',RuntimeWarning)
                return default
            atomic_json_write(path,value,keep_backup=False)
            warnings.warn(f'{path.name} doğrulanmış yedekten geri yüklendi; eski dosya {preserved or "korunamadı"}.',RuntimeWarning)
            return value
    if backup.exists():
        try:value=_read(backup,validator)
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            preserved=_preserve(backup)
            warnings.warn(f'{backup.name} geçersiz; özgün dosya {preserved or "korunamadı"}. Boş başlangıç kullanılıyor.',RuntimeWarning)
            return default
        atomic_json_write(path,value,keep_backup=False)
        warnings.warn(f'{path.name} eksikti; doğrulanmış yedek geri yüklendi.',RuntimeWarning)
        return value
    return default

def atomic_json_write(path,value,keep_backup=True):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    backup=path.with_name(path.name+'.bak');backup_temp=backup.with_name(backup.name+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        if keep_backup and path.exists():
            try:_read(path)
            except (OSError,ValueError,TypeError,json.JSONDecodeError):_preserve(path)
            else:
                with path.open('rb') as source,backup_temp.open('wb') as target:
                    shutil.copyfileobj(source,target);target.flush();os.fsync(target.fileno())
                os.replace(backup_temp,backup)
        os.replace(temporary,path)
    finally:
        for stale in (temporary,backup_temp):
            try:stale.unlink()
            except FileNotFoundError:pass
