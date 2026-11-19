"""Connection states shared by background startup, sign-in and the chat UI."""
from dataclasses import dataclass

NAMES={'chatgpt-web':'ChatGPT','gemini-web':'Gemini'}

@dataclass(frozen=True)
class WebStatus:
    provider:str
    phase:str
    message:str

    def __bool__(self):return self.phase=='ready'
    def __str__(self):return self.message

class WebConnectionError(RuntimeError):
    def __init__(self,status,text=None):
        super().__init__(status.message)
        self.status=status
        self.retry_text=text

def status_for(provider,phase):
    name=NAMES.get(provider,'Web sohbeti')
    messages={
        'connecting':f'{name} hesabına arka planda bağlanılıyor…',
        'ready':f'{name} hazır · Bağlantı arka planda açık',
        'login_open':f'{name} giriş penceresi açık. Giriş veya doğrulamayı tamamlayıp “Giriş tamamlandı” düğmesine bas.',
        'login_required':f'{name} hesabına giriş gerekiyor. “Giriş yap” düğmesiyle açılan pencerede oturum aç.',
        'verification_required':f'{name} site doğrulaması istiyor. “Giriş yap” düğmesiyle açılan pencerede doğrulamayı kendin tamamla.',
        'unavailable':f'{name} bağlantısı hazırlanamadı. Sohbetin korunuyor; yeniden bağlanabilirsin.',
    }
    return WebStatus(provider,phase,messages[phase])
