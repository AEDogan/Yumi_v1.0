# Yumi v1.0 — masaüstünde yaşayan Türkçe sesli asistan

Yumi, Windows masaüstünde dolaşan, seni dinleyip Türkçe konuşan bir asistan. Ses tanıma, ses üretimi ve komut
anlama **bilgisayarında yerel** çalışır; sohbet için Gemini/ChatGPT web oturumunu kullanır. İstersen bir 3D karakter
seçersin: masaüstünde yürür, koltuğa oturur, kendi sesiyle konuşur.

> **English:** A Turkish-speaking desktop voice assistant for Windows with local speech recognition (Whisper), local
> TTS (XTTS), a local intent model, smart-home control and optional 3D VRM characters with their own voices.

## Neler yapar
- 🎙️ **Sesli konuşma** — adıyla seslen, konuş; yerel Whisper dinler, yerel XTTS cevap verir.
- 🧠 **Yerel komut anlama** — alarm, sayaç, müzik, YouTube, ev komutları internete gitmeden.
- 💬 **Sohbet** — Gemini / ChatGPT web oturumu üzerinden.
- 🏠 **Akıllı ev** — ağdaki cihazları bulur, panelden ve sesle yönetir.
- 🎵 **YouTube ve müzik** — reklam atlama eklentisiyle; müziğe göre hareket.
- 🧍 **3D karakterler (VRM)** — masaüstünde gezinir, oturur, her karakter kendi sesiyle konuşur.

## Karakter paketleri
Karakterler ayrı indirilir: **[Yumi Models → Releases](https://github.com/AEDogan/yumi-models/releases)**

| Paket | İçerik |
|---|---|
| Anime seti | 10 karakter (VRM), her biri kendi ince ayarlı sesiyle |

Kurulum: paketi indir → Yumi'de **Model → + Paket ekle** (ya da dosyayı pencereye sürükle). Ayrıntı ve lisanslar
[yumi-models](https://github.com/AEDogan/yumi-models) sayfasında.

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
