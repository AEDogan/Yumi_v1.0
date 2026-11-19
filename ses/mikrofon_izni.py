"""F1b (19 Kas): Windows mikrofon gizlilik izni. İzin kapalıyken Windows hata vermez, akış açılır ama hep sessizlik
gelir → Yumi dinler gibi görünüp "kalır". Açmadan önce kayıt defterinden bakılır; kapalıysa açık mesaj + Ayarlar.

Anahtar: HKCU/HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone
  Value = Allow|Deny (genel), NonPackaged\\Value (masaüstü uygulamaları), NonPackaged\\<exe yolu, '\\' yerine '#'>\\Value."""
import os, sys

KOK = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
AYAR_ADRESI = 'ms-settings:privacy-microphone'


def _deger(hive, yol):
    import winreg
    try:
        with winreg.OpenKey(hive, yol) as k:
            return str(winreg.QueryValueEx(k, 'Value')[0])
    except OSError:
        return None


def kapali():
    """İzin kapalıysa kullanıcıya gösterilecek mesaj, değilse None. Okunamazsa None (engelleme yok)."""
    if os.name != 'nt':
        return None
    try:
        import winreg
    except ImportError:
        return None
    if _deger(winreg.HKEY_LOCAL_MACHINE, KOK) == 'Deny':
        return 'Bu bilgisayarda mikrofon erişimi kapalı. Windows Ayarlar → Gizlilik ve güvenlik → Mikrofon bölümünden "Mikrofon erişimi"ni aç.'
    if _deger(winreg.HKEY_CURRENT_USER, KOK) == 'Deny':
        return 'Mikrofon erişimi kapalı. Windows Ayarlar → Gizlilik ve güvenlik → Mikrofon bölümünden "Mikrofon erişimi"ni aç.'
    if _deger(winreg.HKEY_CURRENT_USER, KOK + r'\NonPackaged') == 'Deny':
        return ('Masaüstü uygulamalarının mikrofonu kullanması kapalı. Windows Ayarlar → Gizlilik ve güvenlik → Mikrofon '
                'bölümünden "Masaüstü uygulamalarının mikrofonunuza erişmesine izin verin" seçeneğini aç.')
    for exe in {sys.executable, getattr(sys, '_base_executable', sys.executable)}:
        if exe and _deger(winreg.HKEY_CURRENT_USER, KOK + r'\NonPackaged' + '\\' + exe.replace('\\', '#')) == 'Deny':
            return ('Yumi\'nin mikrofonu kullanmasına Windows izin vermiyor. Windows Ayarlar → Gizlilik ve güvenlik → Mikrofon '
                    'bölümünde Python/Yumi için izni aç.')
    return None


def ayarlari_ac():
    try:
        os.startfile(AYAR_ADRESI)
    except OSError:
        pass
