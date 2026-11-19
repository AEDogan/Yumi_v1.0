"""Yumi ev otomasyonu (E06-3): ortak cihaz/yetenek modeli, protokol adaptörleri, kalıcı cihaz kaydı,
DPAPI'li sır deposu ve Türkçe komut eşleme. Qt'siz çekirdek; panel bölümü panel_ev.py'de.

Akış: cihaz_bulucu.kesfet() → yonetici.EvYoneticisi.tara() → her cihaz için uygun adaptörler
→ adaptor.yetenekler() (cihazdan SORGULANIR) → kayit.CihazKaydi (data/ev_cihazlari.json)
→ komut.cozumle() → yonetici.uygula() → adaptör (Tasima yazma kilidine tabi).
Yumi bağlantısı: yumi_baglanti.yonetici_al / EvKomutlari (yerel_ai/yonlendirici.py), SmartHomeSkill.ev_yonetici.
Adaptörler: upnp_av, dial, webos, tizen, android_tv, tuya_yerel, miio_cihaz, kasa, yeelight, roomba, ble_tarti,
beceri_sarmal (mevcut SmartHomeSkill kayıtları).
"""
