# Aktif Yumi beceri paketi — dar harita

Bu paket uygulamanın aktif import yoludur. related-projects altındaki standalone kopya ile karıştırma. Başlangıç ../DURUM.md.

- engine.py / dispatcher.py: yerel beceri kaydı ve yönlendirme.
- device_catalog.py: mevcut bağlantı adaptörleri için desteklenen kategori/marka ve model kapsamı; Alexa’dan kopyalanmış katalog değildir.
- oem_connectors.py: OEM hesabı, cihaz/yetenek sözleşmesi, kayıt defteri ve OAuth PKCE loopback temeli; her OEM'in resmi API adaptörü ayrı kaydedilir.
- ui_smart_home_panel.py: Yumi temalı kategori → cihaz türü → marka/bağlantı → destek/model kapsamı → adım adım yönerge akışı; oda ve cihaz yönetimi.
- skills/smart_home_skill.py: keşif, kayıt, Home Assistant güvenli bağlantısı ve sağlayıcı komutları. Xiaomi/Tuya hesap parolası alınmaz.
- android_tv_bridge.py: mevcut yerel TV kod/sertifika eşleştirmesi; çalışmış özelliği yeniden yapma.
- storage.py / ../durable_json.py: beceri verisi için atomik JSON yedekleme ve Windows DPAPI ile şifreli cihaz/OEM hesap belirteçleri; dosya içerikleri/sırlar gereksiz okunmamalı.
- engine.py: hassas cihaz eşleştirme argümanları model fonksiyon şemasından çıkarıldı; kullanıcı eşleştirmeyi panelden yapar.
- ../docs/CIHAZ-BAGLANTISI-ARASTIRMA.md: HA onboarding uygulaması ve gerçek model/cihaz kabulinde kalanlar.
- ../docs/OEM-50-ADAPTER-ENVANTERI.md: 50 üretici/ürün ailesinin resmi cloud, yerel/Matter, HA ve partner erişim yolu; hiçbirini uygulanmış gibi sunmaz.
