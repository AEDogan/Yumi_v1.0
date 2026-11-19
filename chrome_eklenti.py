"""F1b (19 Kas, kullanıcı): reklam atlama eklentisini Yumi'nin Chrome YouTube profiline yönlendirmeli kurma.
Chrome 137+ mağaza dışı eklentiyi kendiliğinden yüklemiyor; burada eklentiler sayfası açılır, klasör yolu panoya
kopyalanır ve üç adım gösterilir. Edge'de buna gerek yok (eklenti kendiliğinden yüklenir, yerel_ai/youtube_tarayici.py).
Çağıran: kurulum son ekranı (isteğe bağlı kutu) ve Başlat menüsü kısayolu. Kullanım: pythonw chrome_eklenti.py"""
import yumi_yollar  # noqa: F401  kod klasörleri sys.path'e
import ctypes, os, subprocess
from pathlib import Path


def _chrome():
    for k in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        p = Path(os.environ.get(k, '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'
        if p.is_file():
            return p
    return None


def _panoya(metin):
    try:
        subprocess.run(['clip'], input=metin.encode('utf-16-le'), check=False, creationflags=0x08000000)
    except OSError:
        pass


def main():
    from yerel_ai.youtube_tarayici import PROFIL, EKLENTI, _eklenti_profilde
    kutu = ctypes.windll.user32.MessageBoxW
    chrome = _chrome()
    if chrome is None:
        kutu(None, 'Bu bilgisayarda Google Chrome bulunamadı.\n\nYumi YouTube\'u Microsoft Edge\'de açar; reklam atlama eklentisi '
             'orada kendiliğinden çalışır, bir şey yapman gerekmez.', 'Yumi · Chrome eklentisi', 0x40)
        return
    if _eklenti_profilde(PROFIL):
        kutu(None, 'Reklam atlama eklentisi Yumi\'nin Chrome profilinde zaten kurulu.', 'Yumi · Chrome eklentisi', 0x40)
        return
    PROFIL.mkdir(parents=True, exist_ok=True)
    _panoya(str(EKLENTI))
    subprocess.Popen([str(chrome), f'--user-data-dir={PROFIL}', '--no-first-run', '--no-default-browser-check', 'chrome://extensions/'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kutu(None, 'Chrome, Yumi\'nin YouTube profilinde eklentiler sayfasıyla açıldı. Üç adım:\n\n'
         '1) Sağ üstteki "Geliştirici modu" anahtarını aç.\n'
         '2) Sol üstte "Paketlenmemiş öğe yükle"ye bas.\n'
         '3) Açılan pencerede adres çubuğuna yapıştır (Ctrl+V), Enter, sonra "Klasör seç".\n\n'
         'Klasör yolu panoya kopyalandı:\n' + str(EKLENTI) + '\n\n'
         'Bundan sonra Yumi YouTube\'u bu Chrome profilinde açar ve reklamları atlar.', 'Yumi · Chrome eklentisi', 0x40)


if __name__ == '__main__':
    main()
