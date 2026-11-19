import base64
import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from durable_json import atomic_json_write,load_json

class SkillStorage:
    """
    %APPDATA%\\YumiDesktop\\skills_data.json üzerinde thread-safe kalıcı veri yönetimi sağlar.
    """
    def __init__(self, custom_dir: str | None = None):
        if custom_dir:
            self.base_dir = Path(custom_dir)
        else:
            from app_paths import data_dir
            self.base_dir = data_dir()
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tokens_dir = self.base_dir / "tokens"
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.base_dir / "skills_data.json"
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    def _default_schema(self) -> Dict[str, Any]:
        return {
            "timers": [],
            "alarms": [],
            "reminders": [],
            "lists": {
                "alışveriş": [],
                "yapılacaklar": []
            },
            "notes": [],
            "memories": {},
            "local_events": [],
            "routines": {
                "çalışma modu": [
                    {"skill": "set_timer", "args": {"duration_seconds": 1500, "label": "Pomodoro"}},
                    {"skill": "get_todo_list", "args": {"list_name": "yapılacaklar"}}
                ],
                "günaydın": [
                    {"skill": "daily_briefing", "args": {"city": "Istanbul"}}
                ]
            },
            "settings": {
                "default_city": "Istanbul",
                "calendar_provider": "ask",  # ask, google, outlook, both, local
                "music_platform": "youtube"
            },
            "user_rules": [],
            "smart_devices": {},
            "oem_connections": {},
            "rooms": ["Oturma Odası", "Yatak Odası", "Mutfak", "Çalışma Odası"]
        }

    def _load(self) -> Dict[str, Any]:
        defaults = self._default_schema()
        backup=self.db_file.with_name(self.db_file.name+".bak")
        loaded=load_json(self.db_file,defaults,lambda value:isinstance(value,dict))
        loaded=copy.deepcopy(loaded)
        for k,v in defaults.items():loaded.setdefault(k,copy.deepcopy(v))
        if not isinstance(loaded.get("smart_devices"),dict):raise RuntimeError("Akıllı cihaz kayıtlarının yapısı okunamıyor; skills_data.json korunuyor.")
        if not isinstance(loaded.get("oem_connections"),dict):raise RuntimeError("OEM bağlantı kayıtlarının yapısı okunamıyor; skills_data.json korunuyor.")
        migrated=self._decode_device_secrets(loaded)
        if migrated:self._save(loaded,keep_backup=False)
        return loaded

    @staticmethod
    def _decode_device_secrets(data):
        migrated=False
        secrets_to_decode=[]
        for device in data.get("smart_devices",{}).values():
            if isinstance(device,dict):secrets_to_decode.append((device,"token"))
        for account in data.get("oem_connections",{}).values():
            if isinstance(account,dict):
                secrets_to_decode.extend((account,key) for key in ("access_token","refresh_token") if key in account)
        for record,key in secrets_to_decode:
            token=record.get(key)
            if not isinstance(token,str) or not token:continue
            if token.startswith("dpapi:v1:"):
                try:
                    from platform_win import unprotect
                    record[key]=unprotect(base64.b64decode(token[9:],validate=True)).decode("utf-8")
                except Exception:
                    raise RuntimeError("Akıllı ev yetkisi bu Windows hesabında açılamadı; beceri dosyası ve şifreli değerler korundu.") from None
            else:migrated=True
        return migrated

    @staticmethod
    def _encode_device_secrets(data):
        protected=copy.deepcopy(data)
        secrets_to_encode=[]
        for device in protected.get("smart_devices",{}).values():
            if isinstance(device,dict):secrets_to_encode.append((device,"token"))
        for account in protected.get("oem_connections",{}).values():
            if isinstance(account,dict):
                secrets_to_encode.extend((account,key) for key in ("access_token","refresh_token") if key in account)
        for record,key in secrets_to_encode:
            token=record.get(key)
            if not isinstance(token,str) or not token or token.startswith("dpapi:v1:"):continue
            from platform_win import protect
            sealed=protect(token.encode("utf-8"))
            record[key]="dpapi:v1:"+base64.b64encode(sealed).decode("ascii")
        return protected

    def _save(self, data: Dict[str, Any] | None = None,keep_backup=True) -> None:
        with self._lock:
            target = data if data is not None else self._data
            atomic_json_write(self.db_file,self._encode_device_secrets(target),keep_backup=keep_backup)

    def get(self, section: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(section, default)

    def set(self, section: str, value: Any) -> None:
        with self._lock:
            self._data[section] = value
            self._save()

    def update_section(self, section: str, updater_fn) -> Any:
        with self._lock:
            current = self._data.get(section)
            updated = updater_fn(current)
            self._data[section] = updated
            self._save()
            return updated
