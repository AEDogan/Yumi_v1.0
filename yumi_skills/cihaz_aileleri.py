"""Ev ağı cihaz bulucu — protokol ailesi, imza ve sınıflandırma tabloları (yalnız veri).

Tasarım: marka/model varsayılmaz. Bir cihazın ailesi; kendi yayınladığı servis
türünden (mDNS), SSDP başlıklarından, Tuya/miIO/Roomba keşif yanıtlarından,
MAC üreticisinden (IEEE OUI), ana makine adından, açık imza portlarından,
kurulum kipindeki Wi‑Fi adından ya da Bluetooth LE yayınından çıkarılır.
Yeni aile/imza eklemek için kod değil, aşağıdaki tablolara satır eklenir.
Hiçbir kurala uymayan kayıt atılmaz; "tanınmayan" olarak listelenir.

Destek durumları (mevcut Yumi koduna göre, 16 Kasım 2026):
  yumi_var       Yumi'de çalışan bir bağlanma kodu var (canlı kabulü ayrıca gerekir).
  planli         Yerel yolu bilinen, Yumi'de henüz uygulanmamış/eksik aile.
  kopru_gerekir  Masaüstü Yumi'den doğrudan değil; köprü/denetleyici/hesap altyapısı gerekir.
  bilinmiyor     Yumi için yol belirlenmemiş ya da ev otomasyonu kapsamı dışında.
Güven düzeyleri: kesin (cihazın kendi protokol yanıtı/yayını), olasi (üretici,
ad ya da imza portu), tahmin (tek zayıf ipucu). Aynı aileyi iki ayrı yoklayıcı
destekliyorsa güven bir düzey yükselir.
Kategoriler: ev, kisisel_ag (bilgisayar/telefon/modem/yazıcı), taninmayan.
"""
from __future__ import annotations

DESTEK_DURUMLARI = ("yumi_var", "planli", "kopru_gerekir", "bilinmiyor")
GUVEN_SIRASI = {"tahmin": 1, "olasi": 2, "kesin": 3}
KATEGORILER = ("ev", "kisisel_ag", "taninmayan")

# Cihaz türleri: Yumi'nin DEVICE_TYPES kodlarıyla (light/plug/vacuum/tv) uyumlu.
TURLER = {
    "tv": "TV / medya oynatıcı",
    "plug": "Akıllı priz / anahtar",
    "light": "Işık / ampul",
    "vacuum": "Robot süpürge",
    "speaker": "Hoparlör",
    "media": "Medya cihazı",
    "bridge": "Köprü / hub",
    "appliance": "Ev aleti",
    "printer": "Yazıcı / tarayıcı",
    "router": "Modem / yönlendirici",
    "computer": "Bilgisayar / telefon",
    "camera": "Kamera",
    "sensor": "Sensör",
    "unknown": "Bilinmiyor",
}
KISISEL_TURLER = ("printer", "router", "computer")

_KOPRU = "Köprü/denetleyici gerekir."
_YOK = "Gerekmez."


def _a(etiket, destek, baglanma, protokol="", eslestirme="bilinmiyor", kategori="ev"):
    return {"etiket": etiket, "destek": destek, "baglanma": baglanma, "protokol": protokol,
            "eslestirme": eslestirme, "kategori": kategori}


# aile -> nitelikler. "eslestirme": kullanıcıdan eşleştirme anında ne istenecek.
AILELER = {
    "androidtv": _a("Android TV / Google TV", "yumi_var",
                    "Yerel eşleştirme (androidtvremote2); Yumi > Akıllı ev > TV eşleştir.", "android_tv",
                    "TV ekranında çıkan 6 haneli kodu Yumi'ye gir."),
    "googlecast": _a("Google Cast", "planli",
                     "Cast cihazı. Android/Google TV ise aynı adreste androidtv ailesiyle eşleşir.", "",
                     "Gerekmez (Cast); tam kontrol için Android TV eşleşmesi."),
    "dial": _a("DIAL (uygulama başlatma)", "yumi_var",
               "Yumi yalnız uygulama başlatabilir (ör. YouTube). Güç/ses kontrolü değildir.", "dlna_tv", _YOK),
    "webos": _a("LG webOS", "yumi_var",
                "webOS yerel ağ API'si (SSAP WebSocket); bir kez TV'de onay gerekir.", "webos",
                "TV ekranında Yumi'nin bağlanma isteğini kumandayla bir kez kabul et."),
    "tizen": _a("Samsung Tizen", "yumi_var",
                "Samsung yerel ağ API'si (REST + WebSocket); kumanda için bir kez TV'de onay gerekir.", "tizen",
                "TV ekranında Yumi'nin bağlanma isteğini kumandayla bir kez kabul et."),
    "roku": _a("Roku", "bilinmiyor", "Roku yerel ECP API'si; Yumi'de yol planlanmadı.", "",
               "TV ayarında ağdan kontrol izni (doğrulanmadı)."),
    "upnp-medya": _a("UPnP/DLNA medya", "yumi_var",
                     "UPnP RenderingControl/AVTransport: ses düzeyi, sessiz, oynatma (eşleştirmesiz).", "upnp_av", _YOK),
    "tuya": _a("Tuya / Smart Life", "planli",
               "Tuya yerel protokolü: yerel anahtar bir kez alınır, sonra ev ağından doğrudan kontrol.", "tuya",
               "Smart Life > Ben > ⚙ > Hesap ve Güvenlik'teki User Code'u gir, Yumi'nin gösterdiği QR'ı Smart Life ile okutup onayla."),
    "hue": _a("Philips Hue", "planli",
              "Bridge düğmesiyle eşleştirme; Yumi kodu var ama HTTPS düzeltmesi (E02) bekliyor.", "hue",
              "Hue Bridge üzerindeki düğmeye bas."),
    "shelly": _a("Shelly", "yumi_var", "Shelly yerel RPC (Gen2+).", "shelly",
                 "Gerekmez (cihazda parola tanımlıysa parolayı gir)."),
    "home_assistant": _a("Home Assistant", "yumi_var", "Yumi HA REST köprüsü.", "home_assistant",
                         "HA adresini ve uzun ömürlü belirteci gir."),
    "matter": _a("Matter", "kopru_gerekir",
                 "Matter denetleyicisi gerekir; Windows masaüstünde ayrı deneme (E04).", "",
                 "Cihazdaki/kutudaki Matter QR kodunu okut. " + _KOPRU),
    "homekit": _a("Apple HomeKit", "kopru_gerekir", "HAP denetleyicisi gerekir; Yumi'de yok.", "",
                  "HomeKit kurulum kodu. " + _KOPRU),
    "xiaomi": _a("Xiaomi miIO ailesi", "kopru_gerekir",
                 "miIO yerel protokolü cihaz belirteci (token) ister; belirteç Xiaomi hesabından alınır.", "xiaomi",
                 "Xiaomi Home hesabıyla bir kez giriş (belirteç için)."),
    "roborock": _a("Roborock", "kopru_gerekir",
                   "Yeni Roborock yerel protokolü; yerel anahtar Roborock hesabından alınır (python-roborock).", "",
                   "Roborock uygulama hesabıyla bir kez giriş (e-posta kodu)."),
    "roomba": _a("iRobot Roomba", "planli",
                 "Yerel MQTT (TLS); robotun parolası bir kez robottan alınır (roombapy, doğrulanmadı).", "",
                 "Robot yuvadayken HOME düğmesini ses gelene dek basılı tut (doğrulanmadı)."),
    "shark": _a("SharkNinja", "kopru_gerekir", "Bulut (Ayla) hesabı; yerel yol bilinmiyor.", "",
                "Shark hesabıyla giriş."),
    "ecovacs": _a("Ecovacs", "kopru_gerekir", "Bulut hesabı; yerel yol bilinmiyor.", "",
                  "Ecovacs hesabıyla giriş."),
    "midea": _a("Midea", "bilinmiyor", "Midea yerel/bulut yolu belirlenmedi.", "", "bilinmiyor"),
    "anker": _a("Anker / eufy", "bilinmiyor", "eufy cihazlarının bir kısmı Tuya tabanlıdır; yol belirlenmedi.", "",
                "bilinmiyor"),
    "tplink": _a("TP-Link Tapo / Kasa", "yumi_var", "Yumi'de Tapo/Kasa yolu var (python-kasa).", "tapo",
                 "Tapo için TP-Link hesabı e-posta/parolası; eski Kasa için gerekmez."),
    "yeelight": _a("Yeelight", "yumi_var", "Yeelight LAN kontrolü (TCP 55443).", "yeelight",
                   "Yeelight uygulamasında 'LAN kontrolü'nü aç."),
    "ble_tarti": _a("Bluetooth tartı", "yumi_var",
                    "Pasif Bluetooth LE reklamı okunur (bağlanılmaz); tartıya çıkınca ölçüm gelir.", "ble_tarti", _YOK),
    "roku": _a("Roku", "planli", "Roku ECP (TCP 8060) yerel API; Yumi'de adaptör henüz yok.", "", _YOK),
    "amazon": _a("Amazon Echo / Fire TV", "kopru_gerekir", "Üçüncü taraf yerel kontrol yolu yok.", "", _KOPRU),
    "sonos": _a("Sonos", "bilinmiyor", "Sonos yerel API'si; Yumi'de yol planlanmadı.", "", _YOK),
    "airplay": _a("AirPlay", "bilinmiyor", "AirPlay alıcısı; kontrol yolu değil.", "", _YOK),
    "spotify": _a("Spotify Connect", "bilinmiyor", "Spotify Connect hedefi; Spotify işi beklemede.", "", _YOK,
                  "kisisel_ag"),
    "esphome": _a("ESPHome", "bilinmiyor", "ESPHome yerel API'si; Yumi'de yol planlanmadı.", "", "bilinmiyor"),
    "wled": _a("WLED", "bilinmiyor", "WLED yerel JSON API'si; Yumi'de yol planlanmadı.", "", _YOK),
    "kurulum_ap": _a("Kurulum kipindeki cihaz", "bilinmiyor",
                     "Cihaz henüz ev Wi‑Fi'ına bağlanmamış, kendi kurulum ağını yayınlıyor.", "",
                     "Üretici uygulamasıyla Wi‑Fi kurulumunu tamamla, sonra yeniden tara."),
    "iot_modul": _a("Wi‑Fi IoT modülü", "bilinmiyor",
                    "Üretici yalnız modül/çip üreticisi (Espressif, Beken…); cihaz ailesi belirlenemedi.", "",
                    "bilinmiyor", "taninmayan"),
    "yazici": _a("Yazıcı / tarayıcı", "bilinmiyor", "Ev otomasyonu kapsamı dışında.", "", "—", "kisisel_ag"),
    "ag": _a("Ağ cihazı", "bilinmiyor", "Modem/yönlendirici; ev otomasyonu kapsamı dışında.", "", "—", "kisisel_ag"),
    "bilgisayar": _a("Bilgisayar / telefon", "bilinmiyor", "Ev otomasyonu kapsamı dışında.", "", "—", "kisisel_ag"),
    "upnp": _a("Genel UPnP", "bilinmiyor", "UPnP cihazı; ailesi belirlenemedi.", "", "bilinmiyor", "taninmayan"),
    "bilinmeyen": _a("Tanınmayan cihaz", "bilinmiyor", "Yayın/imza tabloda yok; tanınamadı.", "", "bilinmiyor",
                     "taninmayan"),
}

# Kurallar: (yoklayıcı, alan, eşleşme, desen, aile, tür, öncelik, güven)
#   yoklayıcı: mdns | ssdp | tuya | selam | envanter | imza | wifi | ble | bilgi_ucu | *
#   alan     : kaydın alanlar sözlüğündeki anahtar
#   eşleşme  : tam | icerir | onek (büyük/küçük harf duyarsız; boş desen + icerir = alan var)
#   aile     : boşsa kural yalnız tür ipucu verir;  tür: boşsa yalnız aile verir
#   öncelik  : yüksek olan kazanır;  güven: kesin | olasi | tahmin
KURALLAR = (
    # --- mDNS / DNS-SD servis türleri (cihazın kendi ilanı) ---
    ("mdns", "servis", "tam", "_androidtvremote2._tcp", "androidtv", "tv", 90, "kesin"),
    ("mdns", "servis", "tam", "_googlecast._tcp", "googlecast", "media", 70, "kesin"),
    ("mdns", "servis", "tam", "_matter._tcp", "matter", "", 60, "kesin"),
    ("mdns", "servis", "tam", "_matterc._udp", "matter", "", 60, "kesin"),
    ("mdns", "servis", "tam", "_matterd._udp", "matter", "", 60, "kesin"),
    ("mdns", "servis", "tam", "_hap._tcp", "homekit", "", 55, "kesin"),
    ("mdns", "servis", "tam", "_hap._udp", "homekit", "", 55, "kesin"),
    ("mdns", "servis", "tam", "_hue._tcp", "hue", "bridge", 85, "kesin"),
    ("mdns", "servis", "tam", "_shelly._tcp", "shelly", "plug", 85, "kesin"),
    ("mdns", "ad", "onek", "shelly", "shelly", "plug", 80, "olasi"),
    ("mdns", "servis", "tam", "_home-assistant._tcp", "home_assistant", "bridge", 85, "kesin"),
    ("mdns", "servis", "tam", "_miio._udp", "xiaomi", "", 75, "kesin"),
    ("mdns", "servis", "tam", "_amzn-wplay._tcp", "amazon", "media", 75, "kesin"),
    ("mdns", "servis", "tam", "_amzn-alexa._tcp", "amazon", "speaker", 75, "kesin"),
    ("mdns", "servis", "tam", "_sonos._tcp", "sonos", "speaker", 75, "kesin"),
    ("mdns", "servis", "tam", "_esphomelib._tcp", "esphome", "", 75, "kesin"),
    ("mdns", "servis", "tam", "_wled._tcp", "wled", "light", 80, "kesin"),
    ("mdns", "servis", "tam", "_airplay._tcp", "airplay", "media", 25, "kesin"),
    ("mdns", "servis", "tam", "_raop._tcp", "airplay", "speaker", 20, "kesin"),
    ("mdns", "servis", "tam", "_spotify-connect._tcp", "spotify", "speaker", 20, "kesin"),
    ("mdns", "servis", "tam", "_ipp._tcp", "yazici", "printer", 50, "kesin"),
    ("mdns", "servis", "tam", "_ipps._tcp", "yazici", "printer", 50, "kesin"),
    ("mdns", "servis", "tam", "_printer._tcp", "yazici", "printer", 50, "kesin"),
    ("mdns", "servis", "tam", "_pdl-datastream._tcp", "yazici", "printer", 50, "kesin"),
    ("mdns", "servis", "tam", "_uscan._tcp", "yazici", "printer", 45, "kesin"),
    ("mdns", "servis", "tam", "_companion-link._tcp", "bilgisayar", "computer", 15, "olasi"),
    ("mdns", "servis", "tam", "_smb._tcp", "bilgisayar", "computer", 10, "olasi"),
    ("mdns", "servis", "tam", "_workstation._tcp", "bilgisayar", "computer", 10, "olasi"),
    ("mdns", "servis", "tam", "_nearbypresence._tcp", "bilgisayar", "computer", 10, "olasi"),
    ("mdns", "txt_md", "icerir", "tv", "", "tv", 40, ""),
    ("mdns", "txt_md", "icerir", "nest", "", "speaker", 35, ""),
    ("mdns", "txt_md", "icerir", "google home", "", "speaker", 35, ""),
    ("mdns", "txt_md", "icerir", "chromecast", "", "media", 30, ""),
    ("mdns", "txt_ci", "tam", "2", "", "bridge", 50, ""),   # HomeKit kategori kodları
    ("mdns", "txt_ci", "tam", "5", "", "light", 50, ""),
    ("mdns", "txt_ci", "tam", "7", "", "plug", 50, ""),
    ("mdns", "txt_ci", "tam", "8", "", "plug", 45, ""),
    ("mdns", "txt_ci", "tam", "17", "", "camera", 50, ""),
    ("mdns", "txt_ci", "tam", "31", "", "tv", 50, ""),
    ("mdns", "txt_dt", "tam", "256", "", "light", 50, ""),  # Matter cihaz türü
    ("mdns", "txt_dt", "tam", "257", "", "light", 50, ""),
    ("mdns", "txt_dt", "tam", "266", "", "plug", 50, ""),
    ("mdns", "txt_dt", "tam", "35", "", "tv", 50, ""),
    ("mdns", "txt_dt", "tam", "116", "", "vacuum", 50, ""),

    # --- SSDP / UPnP ---
    ("ssdp", "st", "icerir", "lge-com:service:webos", "webos", "tv", 85, "kesin"),
    ("ssdp", "server", "icerir", "webos", "webos", "tv", 85, "kesin"),
    ("ssdp", "st", "onek", "urn:lge:device:tv", "webos", "tv", 80, "kesin"),
    ("ssdp", "st", "icerir", "samsung.com:device:remotecontrolreceiver", "tizen", "tv", 85, "kesin"),
    ("ssdp", "st", "icerir", "samsung.com:service:multiscreenservice", "tizen", "tv", 85, "kesin"),
    ("ssdp", "server", "icerir", "samsung", "tizen", "tv", 60, "olasi"),
    ("ssdp", "manufacturer", "icerir", "samsung electronics", "tizen", "", 55, "olasi"),
    ("ssdp", "st", "onek", "roku:ecp", "roku", "tv", 85, "kesin"),
    ("ssdp", "server", "icerir", "roku", "roku", "tv", 80, "olasi"),
    ("ssdp", "st", "icerir", "dial-multiscreen-org:service:dial", "dial", "tv", 35, "kesin"),
    ("ssdp", "server", "icerir", "ipbridge", "hue", "bridge", 85, "kesin"),
    ("ssdp", "hue-bridgeid", "icerir", "", "hue", "bridge", 85, "kesin"),
    ("ssdp", "server", "icerir", "tuya", "tuya", "", 70, "olasi"),
    ("ssdp", "server", "icerir", "sonos", "sonos", "speaker", 75, "kesin"),
    ("ssdp", "devicetype", "icerir", "mediarenderer", "upnp-medya", "media", 30, "kesin"),
    ("ssdp", "devicetype", "icerir", "mediaserver", "upnp-medya", "media", 25, "kesin"),
    ("ssdp", "st", "icerir", "mediarenderer", "upnp-medya", "media", 30, "kesin"),
    ("ssdp", "devicetype", "icerir", "internetgatewaydevice", "ag", "router", 40, "kesin"),
    ("ssdp", "st", "icerir", "internetgatewaydevice", "ag", "router", 40, "kesin"),
    ("ssdp", "devicetype", "icerir", "wfadevice", "ag", "router", 30, "olasi"),
    ("ssdp", "devicetype", "icerir", "printer", "yazici", "printer", 45, "kesin"),
    ("ssdp", "server", "icerir", "microsoft-windows", "bilgisayar", "computer", 15, "olasi"),
    ("ssdp", "st", "icerir", "", "upnp", "", 5, "kesin"),

    # --- Tuya yerel yayını / keşif yanıtı ---
    ("tuya", "servis", "tam", "tuya-yayin", "tuya", "", 95, "kesin"),

    # --- UDP keşif selamları ---
    ("selam", "servis", "tam", "miio-hello", "xiaomi", "", 80, "kesin"),
    ("selam", "servis", "tam", "roomba-mcs", "roomba", "vacuum", 90, "kesin"),
    ("selam", "servis", "tam", "kasa-sysinfo", "tplink", "plug", 85, "kesin"),
    ("selam", "servis", "tam", "yeelight", "yeelight", "light", 90, "kesin"),

    # --- Ağ envanteri: ağ geçidi, bu bilgisayar, rastgele MAC ---
    ("envanter", "bu_bilgisayar", "tam", "1", "bilgisayar", "computer", 100, "kesin"),
    ("envanter", "ag_gecidi", "tam", "1", "ag", "router", 65, "kesin"),
    ("envanter", "rastgele_mac", "tam", "1", "bilgisayar", "computer", 8, "tahmin"),
    # --- Ağ envanteri: MAC üreticisi (IEEE OUI) ---
    ("envanter", "uretici", "icerir", "tuya smart", "tuya", "", 45, "olasi"),
    ("envanter", "uretici", "icerir", "roborock", "roborock", "vacuum", 50, "olasi"),
    ("envanter", "uretici", "icerir", "irobot", "roomba", "vacuum", 50, "olasi"),
    ("envanter", "uretici", "icerir", "dreame", "xiaomi", "vacuum", 50, "olasi"),
    ("envanter", "uretici", "icerir", "sharkninja", "shark", "vacuum", 50, "olasi"),
    ("envanter", "uretici", "icerir", "ecovacs", "ecovacs", "vacuum", 50, "olasi"),
    ("envanter", "uretici", "icerir", "lumi united", "xiaomi", "bridge", 45, "olasi"),
    ("envanter", "uretici", "icerir", "xiaomi", "xiaomi", "", 15, "tahmin"),
    ("envanter", "uretici", "icerir", "signify", "hue", "", 45, "olasi"),
    ("envanter", "uretici", "icerir", "shelly", "shelly", "", 45, "olasi"),
    ("envanter", "uretici", "icerir", "allterco", "shelly", "", 45, "olasi"),
    ("envanter", "uretici", "icerir", "midea", "midea", "appliance", 40, "olasi"),
    ("envanter", "uretici", "icerir", "sonos", "sonos", "speaker", 45, "olasi"),
    ("envanter", "uretici", "icerir", "amazon", "amazon", "", 30, "tahmin"),
    ("envanter", "uretici", "icerir", "tp-link", "tplink", "", 15, "tahmin"),
    ("envanter", "uretici", "icerir", "espressif", "iot_modul", "", 20, "tahmin"),
    ("envanter", "uretici", "icerir", "beken", "iot_modul", "", 20, "tahmin"),
    ("envanter", "uretici", "icerir", "hui zhou gaoshengda", "iot_modul", "", 20, "tahmin"),
    ("envanter", "uretici", "icerir", "intel corporate", "bilgisayar", "computer", 30, "olasi"),
    ("envanter", "uretici", "icerir", "apple", "bilgisayar", "computer", 12, "tahmin"),
    ("envanter", "uretici", "icerir", "microsoft", "bilgisayar", "computer", 25, "olasi"),
    ("envanter", "uretici", "icerir", "dell", "bilgisayar", "computer", 25, "olasi"),
    ("envanter", "uretici", "icerir", "lenovo", "bilgisayar", "computer", 25, "olasi"),
    ("envanter", "uretici", "icerir", "seiko epson", "yazici", "printer", 30, "olasi"),
    ("envanter", "uretici", "icerir", "brother industries", "yazici", "printer", 30, "olasi"),
    ("envanter", "uretici", "icerir", "canon", "yazici", "printer", 30, "olasi"),
    # --- Ağ envanteri: ana makine adı (DHCP/ters DNS/NetBIOS) ---
    ("envanter", "ana_makine", "icerir", "roborock", "roborock", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "rockrobo", "roborock", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "roomba", "roomba", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "irobot", "roomba", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "dreame", "xiaomi", "vacuum", 55, "olasi"),
    ("envanter", "ana_makine", "icerir", "deebot", "ecovacs", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "ecovacs", "ecovacs", "vacuum", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "vacuum", "", "vacuum", 55, ""),
    ("envanter", "ana_makine", "icerir", "lgwebostv", "webos", "tv", 70, "olasi"),
    ("envanter", "ana_makine", "icerir", "shelly", "shelly", "", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "yeelink", "yeelight", "light", 60, "olasi"),
    ("envanter", "ana_makine", "icerir", "esp_", "iot_modul", "", 20, "tahmin"),
    ("envanter", "ana_makine", "icerir", "espressif", "iot_modul", "", 20, "tahmin"),
    ("envanter", "ana_makine", "icerir", "android", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "icerir", "iphone", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "icerir", "ipad", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "icerir", "galaxy", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "icerir", "redmi", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "onek", "desktop-", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "onek", "laptop-", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "icerir", "macbook", "bilgisayar", "computer", 35, "olasi"),
    ("envanter", "ana_makine", "onek", "npi", "yazici", "printer", 30, "tahmin"),
    ("envanter", "ana_makine", "onek", "brn", "yazici", "printer", 30, "tahmin"),

    # --- İmza portu yoklaması (yalnız envanterdeki adreslerde; bkz. IMZA_PORTLARI) ---
    ("imza", "port", "tam", "6668", "tuya", "", 55, "olasi"),
    ("imza", "port", "tam", "3001", "webos", "tv", 40, "tahmin"),
    ("imza", "port", "tam", "8002", "tizen", "tv", 40, "tahmin"),
    ("imza", "port", "tam", "8001", "tizen", "tv", 45, "olasi"),   # 18 Kas: TV platformu port imzası
    ("imza", "port", "tam", "3000", "webos", "tv", 35, "tahmin"),
    ("imza", "port", "tam", "8060", "roku", "tv", 55, "olasi"),
    ("imza", "port", "tam", "8009", "googlecast", "", 40, "tahmin"),
    ("imza", "port", "tam", "6466", "androidtv", "tv", 60, "olasi"),
    ("imza", "port", "tam", "58867", "roborock", "vacuum", 55, "olasi"),
    ("imza", "port", "tam", "8883", "roomba", "", 20, "tahmin"),
    ("imza", "port", "tam", "9999", "tplink", "", 30, "tahmin"),
    ("imza", "port", "tam", "55443", "yeelight", "light", 55, "olasi"),
    ("imza", "port", "tam", "6053", "esphome", "", 55, "olasi"),
    ("imza", "http_baslik", "icerir", "shelly", "shelly", "", 70, "olasi"),
    ("imza", "http_baslik", "icerir", "hue", "hue", "bridge", 60, "olasi"),
    ("imza", "http_baslik", "icerir", "home assistant", "home_assistant", "bridge", 70, "olasi"),
    ("imza", "http_baslik", "icerir", "esphome", "esphome", "", 70, "olasi"),
    ("imza", "http_baslik", "icerir", "tasmota", "iot_modul", "", 50, "olasi"),
    ("imza", "http_baslik", "icerir", "wled", "wled", "light", 70, "olasi"),
    ("imza", "http_baslik", "icerir", "printer", "yazici", "printer", 40, "olasi"),
    ("imza", "http_server", "icerir", "tasmota", "iot_modul", "", 50, "olasi"),
    ("imza", "tls_konu", "icerir", "irobot", "roomba", "vacuum", 70, "olasi"),
    ("imza", "tls_konu", "icerir", "roomba", "roomba", "vacuum", 70, "olasi"),
    ("imza", "tls_konu", "icerir", "philips hue", "hue", "bridge", 70, "olasi"),

    # --- Wi‑Fi çevresi: kurulum kipindeki cihazların kendi erişim noktaları ---
    ("wifi", "ssid", "onek", "smartlife", "tuya", "", 60, "olasi"),
    ("wifi", "ssid", "onek", "smart life", "tuya", "", 60, "olasi"),
    ("wifi", "ssid", "onek", "roborock-vacuum", "roborock", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "rockrobo", "roborock", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "dreame-vacuum", "xiaomi", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "icerir", "_miap", "xiaomi", "", 55, "olasi"),
    ("wifi", "ssid", "onek", "roomba-", "roomba", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "ecovacs", "ecovacs", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "deebot", "ecovacs", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "eufy robovac", "anker", "vacuum", 60, "olasi"),
    ("wifi", "ssid", "onek", "shelly", "shelly", "", 60, "olasi"),
    ("wifi", "ssid", "onek", "yeelink", "yeelight", "light", 60, "olasi"),
    ("wifi", "ssid", "onek", "esp_", "iot_modul", "", 30, "tahmin"),
    ("wifi", "ssid", "onek", "esp-", "iot_modul", "", 30, "tahmin"),
    ("wifi", "ssid", "icerir", "", "kurulum_ap", "", 1, "tahmin"),

    # --- Bluetooth LE: şirket kimliği (üretici verisi) ve servis UUID'leri ---
    # Kaynak: Bluetooth SIG assigned_numbers (company_identifiers.yaml, member_uuids.yaml), 16 Kas 2026.
    ("ble", "ble_sirket", "icerir", "0x07d0", "tuya", "", 85, "kesin"),       # Hangzhou Tuya
    ("ble", "ble_sirket", "icerir", "0x038f", "xiaomi", "", 80, "kesin"),     # Xiaomi Inc.
    ("ble", "ble_sirket", "icerir", "0x0600", "roomba", "vacuum", 85, "kesin"),  # iRobot
    ("ble", "ble_sirket", "icerir", "0x060f", "hue", "light", 80, "kesin"),   # Signify
    ("ble", "ble_sirket", "icerir", "0x0c4f", "shark", "", 70, "olasi"),      # SharkNinja
    ("ble", "ble_sirket", "icerir", "0x0cc2", "anker", "", 30, "tahmin"),     # Anker
    ("ble", "ble_sirket", "icerir", "0x0171", "amazon", "", 60, "olasi"),     # Amazon.com Services
    ("ble", "ble_sirket", "icerir", "0x06a8", "midea", "appliance", 60, "olasi"),  # GD Midea
    ("ble", "ble_sirket", "icerir", "0x02e5", "iot_modul", "", 20, "tahmin"),  # Espressif
    ("ble", "ble_sirket", "icerir", "0x004c", "bilgisayar", "computer", 30, "olasi"),  # Apple
    ("ble", "ble_sirket", "icerir", "0x0006", "bilgisayar", "computer", 30, "olasi"),  # Microsoft
    ("ble", "ble_sirket", "icerir", "0x0075", "bilgisayar", "computer", 15, "tahmin"),  # Samsung
    ("ble", "ble_sirket", "icerir", "0x00e0", "bilgisayar", "computer", 15, "tahmin"),  # Google
    ("ble", "ble_sirket", "icerir", "0x018e", "bilgisayar", "computer", 15, "tahmin"),  # Google LLC
    ("ble", "ble_sirket", "icerir", "0x00c4", "webos", "", 20, "tahmin"),     # LG Electronics
    ("ble", "ble_servis", "icerir", "fff6", "matter", "", 90, "kesin"),       # Matter devreye alma (CSA)
    ("ble", "ble_servis", "icerir", "fd50", "tuya", "", 85, "kesin"),         # Tuya
    ("ble", "ble_servis", "icerir", "fe95", "xiaomi", "", 80, "kesin"),       # Xiaomi MiBeacon
    ("ble", "ble_servis", "icerir", "fe0f", "hue", "light", 80, "kesin"),     # Signify
    ("ble", "ble_servis", "icerir", "fe2c", "bilgisayar", "computer", 25, "olasi"),  # Google Fast Pair
    ("ble", "ble_servis", "icerir", "181d", "ble_tarti", "sensor", 88, "kesin"),  # Weight Scale (SIG)
    ("ble", "ble_servis", "icerir", "181b", "ble_tarti", "sensor", 88, "kesin"),  # Body Composition (SIG)

    # --- Kimliksiz bilgi uçları ---
    ("bilgi_ucu", "os", "icerir", "tizen", "tizen", "tv", 88, "kesin"),
    ("bilgi_ucu", "kaynak", "tam", "googlecast-eureka", "googlecast", "", 70, "kesin"),
)

# İmza portları: (port, okuma, açıklama). okuma: yok | http | tls
# Yalnız envanterde bulunan, kişisel olmayan adreslerde bağlantı denenir; veri gönderilmez
# (http/tls'de yalnız kök sayfa "GET /" başlığı ve TLS sertifika konusu okunur).
IMZA_PORTLARI = (
    (6668, "yok", "Tuya yerel"),
    (3001, "yok", "LG webOS (wss)"),
    (8002, "yok", "Samsung Tizen (wss)"),
    (8001, "yok", "Samsung Tizen REST (18 Kas)"),
    (3000, "yok", "LG webOS (ws) (18 Kas)"),
    (8060, "yok", "Roku ECP (18 Kas)"),
    (8009, "yok", "Google Cast"),
    (6466, "yok", "Android TV uzaktan kumanda"),
    (58867, "yok", "Roborock yerel (doğrulanmadı)"),
    (8883, "yok", "MQTT/TLS (Roomba vb.)"),
    (9999, "yok", "TP-Link Kasa"),
    (55443, "yok", "Yeelight LAN"),
    (6053, "yok", "ESPHome"),
    (80, "http", "kök sayfa başlığı"),
    (443, "tls", "TLS sertifika konusu"),
)

# UDP keşif selamları: (servis, port, istek baytları (hex), açıklama).
# miIO: python-miio 0.5.12 miioprotocol.discover ile doğrulandı.
# Roomba: roombapy topluluk kaynağına göre (bu turda kaynaktan doğrulanmadı).
UDP_SELAMLARI = (
    ("miio-hello", 54321, "21310020" + "ff" * 28, "Xiaomi miIO selamı"),
    ("roomba-mcs", 5678, b"irobotmcs".hex(), "iRobot keşif"),
)


def aile_bilgisi(aile: str) -> dict:
    return AILELER.get(aile, AILELER["bilinmeyen"])


def _eslesir(eslesme: str, desen: str, deger: str) -> bool:
    d, v = desen.casefold(), deger.casefold()
    if eslesme == "tam":
        return v == d
    if eslesme == "onek":
        return v.startswith(d)
    return d in v


def kurallara_uyanlar(yoklayici: str, alanlar: dict, kurallar=KURALLAR) -> list[tuple]:
    eslesen = []
    for kural in kurallar:
        kaynak, alan, eslesme, desen = kural[:4]
        if kaynak not in ("*", yoklayici):
            continue
        deger = alanlar.get(alan)
        if deger is not None and _eslesir(eslesme, desen, str(deger)):
            eslesen.append(kural)
    return eslesen
