# Yumi v1.0 — masaüstü sesli asistan

Windows masaüstünde yaşayan, Türkçe konuşan sesli asistan. Python + PySide6 arayüz, yerel ses tanıma (Whisper),
yerel ses üretimi (XTTS), yerel komut anlama, Gemini/ChatGPT web sohbeti, YouTube/müzik, alarm/sayaç, akıllı ev
cihazları ve isteğe bağlı 3D karakter (VRM) paketleri.

Bu depo **yalnız kaynak kodu** içerir. Kurulum dosyası (Inno Setup), Python ortamları, ana modül modelleri
(Whisper, niyet, XTTS taban, varsayılan Yumi sesi) ve karakter paketleri depoda yoktur.

## Klasörler
| Klasör | İçerik |
|---|---|
| `cekirdek/` | Uygulama, sohbet arka uçları, yollar (`app_paths.py`) |
| `arayuz/` | Pencere, temalar, ayarlar, modelsiz kip |
| `ses/`, `ses_motoru/` | Ses tanıma/üretme işçileri, mikrofon, ses çıkışı |
| `yerel_ai/` | Yerel niyet yönlendirici, medya, ev komutları |
| `yumi_skills/` | Alarm/sayaç, akıllı ev paneli, beceriler |
| `karakter/` | Karakter kataloğu, `.yumipaket` doğrulama/kurulum |
| `goruntu/`, `hareket/`, `sahne/` | 3D çizim (three-vrm köprüsü), hareket, mobilya |
| `eklenti/reklam_atla/` | YouTube reklam atlama tarayıcı eklentisi |
| `assets/`, `items/`, `motions/` | Arayüz varlıkları, eşya modelleri, hareket dosyaları (lisanslar klasörlerde) |
| `lib/ev/` | Akıllı ev bağımlılıkları |
| `vrm_runtime/` | three-vrm Node çalışma zamanı (`npm install` ile `node_modules`) |

## Çalıştırma (geliştirme)
- Windows 10/11 x64, Python 3.12, Node.js, Microsoft Edge.
- `python -m venv .venv` → `.venv\Scripts\pip install -r requirements.txt`
- `vrm_runtime` içinde `npm install`
- Ana modül modelleri `models\` altına (depoda yok).
- `.venv\Scripts\pythonw.exe launch.py`

Kurulu sürümde program `C:\Program Files\Yumi` altında salt okunur durur; ayarlar, sohbet geçmişi ve eklenen
model paketleri `%LOCALAPPDATA%\Yumi` altındadır.

## Lisanslar
Üçüncü taraf varlıkların lisansları: `items/SOURCES_AND_LICENSES.json`, `motions/*LICENSE*`, `assets/fonts/OFL.txt`.
