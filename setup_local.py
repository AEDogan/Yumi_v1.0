"""Yerel Türkçe konuşma tanıma modelini (Whisper small) indirir. 12 Kasım: Vosk indirmesi kaldırıldı."""
from pathlib import Path
import io,zipfile,requests
root=Path(__file__).resolve().parent/'models'
root.mkdir(exist_ok=True)
import os
os.environ['HF_HUB_DISABLE_XET']='1'
from faster_whisper.utils import download_model
whisper=root/'whisper-small'
if not (whisper/'model.bin').exists():
    print('Whisper small Turkce konusma modeli indiriliyor (~480 MB)...')
    download_model('small',output_dir=str(whisper))
print('Whisper modeli hazir.')

# 12 Kasım (DUZEN paket 3): kod klasörleri bu Python ortamının arama yoluna (.pth) — yumi_yollar.KLASORLER
import site, sysconfig
sys_yol = Path(sysconfig.get_paths()['purelib'])
import yumi_yollar
(sys_yol / 'yumi_yollar.pth').write_text('\n'.join(str(y) for y in yumi_yollar.yollar()) + '\n', encoding='utf-8')
print('Kod klasorleri Python yoluna eklendi.')

# 17 Kasım: ev otomasyonu verisi (üretici tablosu, IEEE OUI) — yoksa indirilir; olmazsa ev taraması üretici adı olmadan çalışır
oui=Path(__file__).resolve().parent/'assets'/'veri'/'oui.csv'  # G-A2: programla dağıtılır (kurulumda gömülü)
if not oui.exists():
    try:
        oui.parent.mkdir(parents=True,exist_ok=True)
        r=requests.get('https://standards-oui.ieee.org/oui/oui.csv',timeout=60,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        r.raise_for_status(); oui.write_bytes(r.content); print('Ev cihazi uretici tablosu hazir.')
    except Exception as e:
        print('Ev cihazi uretici tablosu indirilemedi (istege bagli):',e)

# 17 Kasım: Masaüstü + Başlat menüsü kısayolu (Yumi logosu, konsolsuz)
try:
    import kisayol; print('Kisayol:',', '.join(kisayol.olustur()))
except Exception as e:
    print('Kisayol olusturulamadi:',e)
