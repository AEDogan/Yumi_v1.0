"""Ev ağı cihaz bulucu — salt okunur yoklayıcılar ve ağsız ayrıştırıcılar.

Güvenlik sınırı: bu modül hiçbir cihaza komut, eşleştirme ya da oturum isteği
göndermez. Yaptıkları yalnızca:
  * mDNS/DNS-SD sorgusu ve dinleme (zeroconf),
  * SSDP M-SEARCH (çok noktaya) ve yanıt veren cihazın KENDİ bildirdiği
    LOCATION açıklama XML'ine HTTP GET,
  * Tuya yerel yayınlarını UDP 6666/6667/7000 üzerinde dinleme (gönderim yok),
  * yalnız zaten keşfedilmiş adreste bilinen kimliksiz bilgi uçlarına HTTP GET.
Alt ağ port taraması, internet isteği ya da kontrol çağrısı yoktur.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import select
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Kayit:
    """Bir yoklayıcının tek gözlemi (ham kanıt)."""
    yoklayici: str
    adres: str
    kayit: str              # servis türü, ST, yayın biçimi...
    ad: str = ""
    alanlar: dict[str, str] = field(default_factory=dict)


class YoklayiciHatasi(RuntimeError):
    pass


def _ozel_ipv4(adres: str) -> bool:
    try:
        ip = ipaddress.ip_address(adres)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local


def yerel_ipv4_adresleri() -> list[str]:
    """Bu bilgisayarın özel (ev ağı) IPv4 adresleri; link-local/loopback hariç."""
    adresler: list[str] = []
    try:
        import ifaddr  # .venv'de kurulu (zeroconf bağımlılığı)
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if isinstance(ip.ip, str) and _ozel_ipv4(ip.ip) and ip.ip not in adresler:
                    adresler.append(ip.ip)
    except Exception:
        pass
    if not adresler:
        try:
            for bilgi in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                adres = bilgi[4][0]
                if _ozel_ipv4(adres) and adres not in adresler:
                    adresler.append(adres)
        except OSError:
            pass
    return adresler


# ---------------------------------------------------------------- HTTP (GET)
class _YonlendirmeYok(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # yönlendirme izlenmez
        return None


_HTTP = urllib.request.build_opener(_YonlendirmeYok())


def _guvenli_get(url: str, beklenen_ip: str, zaman_asimi: float, sinir: int = 262_144) -> bytes:
    """Yalnız http, yalnız beklenen (keşfedilmiş, özel) IP'ye, kısa süreli GET."""
    return _guvenli_get_baslikli(url, beklenen_ip, zaman_asimi, sinir)[0]


def _guvenli_get_baslikli(url: str, beklenen_ip: str, zaman_asimi: float,
                          sinir: int = 262_144) -> tuple[bytes, dict[str, str]]:
    """``_guvenli_get`` ile aynı sınırlar; yanıt başlıklarını da döndürür (DIAL Application-URL)."""
    parca = urllib.parse.urlsplit(url)
    if parca.scheme != "http" or parca.hostname != beklenen_ip or not _ozel_ipv4(beklenen_ip):
        raise YoklayiciHatasi("adres keşfedilen cihaza ait değil; istek yapılmadı")
    if parca.username or parca.password:
        raise YoklayiciHatasi("kimlikli URL reddedildi")
    istek = urllib.request.Request(url, headers={"User-Agent": "Yumi-cihaz-bulucu/0.1"}, method="GET")
    with _HTTP.open(istek, timeout=max(0.2, zaman_asimi)) as yanit:
        return yanit.read(sinir), {k.casefold(): v for k, v in yanit.headers.items()}


# ---------------------------------------------------------------- mDNS
MDNS_SERVIS_LISTESI = "_services._dns-sd._udp.local."


def _txt_coz(ozellikler: dict | None) -> dict[str, str]:
    sonuc: dict[str, str] = {}
    for anahtar, deger in (ozellikler or {}).items():
        try:
            k = anahtar.decode("utf-8", "replace") if isinstance(anahtar, bytes) else str(anahtar)
            v = "" if deger is None else (deger.decode("utf-8", "replace") if isinstance(deger, bytes) else str(deger))
        except Exception:
            continue
        sonuc[k.strip().casefold()] = v.strip()[:200]
    return sonuc


def mdns_kaydi_olustur(servis_turu: str, ornek_adi: str, adresler: list[str], port: int | None,
                       ozellikler: dict | None, sunucu: str = "") -> Kayit:
    """zeroconf ServiceInfo verisinden (ağsız) Kayit üretir."""
    servis = servis_turu.removesuffix(".local.").removesuffix(".")
    ad = ornek_adi.removesuffix("." + servis_turu).removesuffix(servis_turu).rstrip(".")
    txt = _txt_coz(ozellikler)
    alanlar = {"servis": servis, "ad": ad}
    if port:
        alanlar["port"] = str(port)
    if sunucu:
        alanlar["sunucu"] = sunucu.rstrip(".")
    for anahtar in ("md", "fn", "ci", "dt", "vp", "manufacturer", "model", "mn", "ty", "usb_mfg", "usb_mdl"):
        if anahtar in txt:
            alanlar["txt_" + anahtar] = txt[anahtar]
    gorunen = txt.get("fn") or ad
    ipv4 = [a for a in adresler if _ozel_ipv4(a)]
    return Kayit("mdns", ipv4[0] if ipv4 else "", servis, gorunen, alanlar)


class MdnsYoklayici:
    """DNS-SD servis türü sorgusu + bilinen türlerin doğrudan taranması."""
    ad = "mdns"

    def __init__(self, ek_turler: tuple[str, ...] = ()):
        from .cihaz_aileleri import KURALLAR
        bilinen = {k[3] for k in KURALLAR if k[0] == "mdns" and k[1] == "servis"}
        self.bilinen_turler = sorted(t + ".local." for t in bilinen | set(ek_turler))
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf
        except ImportError as hata:
            raise YoklayiciHatasi("zeroconf kitaplığı yok") from hata
        try:
            zc = Zeroconf(ip_version=IPVersion.V4Only)
        except OSError as hata:
            raise YoklayiciHatasi(f"mDNS soketi açılamadı: {hata}") from hata
        kilit = threading.Lock()
        turler: set[str] = set()
        ornekler: dict[tuple[str, str], None] = {}

        def tur_gozlendi(zeroconf, service_type, name, state_change):
            with kilit:
                if service_type == MDNS_SERVIS_LISTESI:
                    turler.add(name if name.endswith(".") else name + ".")
                else:
                    ornekler[(service_type, name)] = None

        tarayicilar = []
        try:
            tarayicilar.append(ServiceBrowser(zc, MDNS_SERVIS_LISTESI, handlers=[tur_gozlendi]))
            tarayicilar.append(ServiceBrowser(zc, list(self.bilinen_turler), handlers=[tur_gozlendi]))
            taranan = set(self.bilinen_turler)
            cozum_payi = min(2.0, max(0.5, (bitis - time.monotonic()) * 0.3))
            while not iptal.is_set() and time.monotonic() < bitis - cozum_payi:
                with kilit:
                    yeni = sorted(t for t in turler if t not in taranan)
                if yeni:
                    taranan.update(yeni)
                    tarayicilar.append(ServiceBrowser(zc, yeni, handlers=[tur_gozlendi]))
                iptal.wait(0.2)
            self.notlar.append(f"DNS-SD tür sorgusu {len(turler)} servis türü döndürdü")
            kayitlar: list[Kayit] = []
            with kilit:
                bulunan = list(ornekler)
            for servis_turu, isim in bulunan:
                kalan = bitis - time.monotonic()
                if iptal.is_set() or kalan <= 0.05:
                    break
                bilgi = ServiceInfo(servis_turu, isim)
                if not bilgi.load_from_cache(zc):
                    bilgi.request(zc, int(min(800, kalan * 1000)))
                adresler = bilgi.parsed_addresses(IPVersion.V4Only) if bilgi.addresses else []
                kayitlar.append(mdns_kaydi_olustur(servis_turu, isim, adresler, bilgi.port,
                                                   bilgi.properties, bilgi.server or ""))
            # Bulunan ama hiçbir örneği olmayan servis türleri cihaz değildir; yalnız not edilir.
            return kayitlar
        finally:
            for t in tarayicilar:
                try:
                    t.cancel()
                except Exception:
                    pass
            try:
                zc.close()
            except Exception:
                pass


# ---------------------------------------------------------------- SSDP
SSDP_ADRES = ("239.255.255.250", 1900)
SSDP_HEDEFLER = ("ssdp:all", "upnp:rootdevice")


def ssdp_istegi(st: str, mx: int = 2) -> bytes:
    return ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
            f'MAN: "ssdp:discover"\r\nMX: {mx}\r\nST: {st}\r\n\r\n').encode("ascii")


def ssdp_yanitini_coz(veri: bytes, adres: str) -> Kayit | None:
    """SSDP yanıtını (HTTP/1.1 200 OK ya da NOTIFY) ayrıştırır; ağ kullanmaz."""
    try:
        metin = veri.decode("utf-8", "replace")
    except Exception:
        return None
    satirlar = metin.split("\r\n") if "\r\n" in metin else metin.split("\n")
    if not satirlar or not (satirlar[0].upper().startswith("HTTP/1.1 200") or satirlar[0].upper().startswith("NOTIFY")):
        return None
    basliklar: dict[str, str] = {}
    for satir in satirlar[1:]:
        if ":" in satir:
            k, v = satir.split(":", 1)
            basliklar[k.strip().casefold()] = v.strip()[:300]
    st = basliklar.get("st") or basliklar.get("nt") or ""
    alanlar = {"st": st}
    for k in ("server", "usn", "location", "hue-bridgeid", "x-user-agent"):
        if k in basliklar:
            alanlar[k] = basliklar[k]
    return Kayit("ssdp", adres, st, "", alanlar)


_UPNP_NS = "{urn:schemas-upnp-org:device-1-0}"


def upnp_aciklamasini_coz(xml_verisi: bytes) -> dict[str, str]:
    """UPnP aygıt açıklama XML'inden kök aygıtın kimlik alanlarını alır."""
    if b"<!DOCTYPE" in xml_verisi[:2048] or b"<!ENTITY" in xml_verisi:
        raise YoklayiciHatasi("DTD içeren açıklama reddedildi")
    kok = ET.fromstring(xml_verisi)
    aygit = kok.find(f"{_UPNP_NS}device")
    ns = _UPNP_NS
    if aygit is None:  # ad alanı belirtmeyen cihazlar
        aygit, ns = kok.find("device"), ""
    if aygit is None:
        return {}
    sonuc = {}
    for etiket, anahtar in (("friendlyName", "friendlyname"), ("manufacturer", "manufacturer"),
                            ("modelName", "modelname"), ("modelNumber", "modelnumber"),
                            ("deviceType", "devicetype"), ("modelDescription", "modeldescription")):
        deger = aygit.findtext(f"{ns}{etiket}")
        if deger:
            sonuc[anahtar] = deger.strip()[:200]
    udn = aygit.findtext(f"{ns}UDN")
    if udn:
        sonuc["udn"] = udn.strip()[:120]
    servisler = []
    for servis in aygit.iter(f"{ns}service"):
        ogeler = {e: (servis.findtext(f"{ns}{e}") or "").strip()[:200]
                  for e in ("serviceType", "controlURL", "SCPDURL", "eventSubURL")}
        if ogeler["serviceType"]:
            servisler.append(ogeler)
    if servisler:
        sonuc["upnp_servisler"] = json.dumps(servisler[:24], ensure_ascii=False)
    url_tabani = kok.findtext(f"{ns}URLBase")
    if url_tabani:
        sonuc["urlbase"] = url_tabani.strip()[:200]
    alt_turler = [d.text.strip() for d in aygit.iter(f"{ns}deviceType") if d.text][1:]
    if alt_turler:
        sonuc["alt_devicetype"] = ";".join(alt_turler[:8])[:300]
    return sonuc


class SsdpYoklayici:
    ad = "ssdp"

    def __init__(self, aciklama_oku: bool = True, en_fazla_aciklama: int = 40):
        self.aciklama_oku = aciklama_oku
        self.en_fazla_aciklama = en_fazla_aciklama
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        soketler = []
        for yerel in yerel_ipv4_adresleri() or ["0.0.0.0"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                if yerel != "0.0.0.0":
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(yerel))
                s.bind((yerel, 0))
                s.setblocking(False)
                soketler.append(s)
            except OSError as hata:
                self.notlar.append(f"{yerel} arayüzünde SSDP soketi açılamadı: {hata}")
        if not soketler:
            raise YoklayiciHatasi("SSDP soketi açılamadı")
        kayitlar: dict[tuple[str, str, str], Kayit] = {}
        try:
            gonderim_zamanlari = [time.monotonic(), time.monotonic() + 1.0]
            dinleme_sonu = min(bitis, time.monotonic() + 4.0)
            if self.aciklama_oku:
                dinleme_sonu = min(dinleme_sonu, bitis - min(2.5, (bitis - time.monotonic()) * 0.4))
            while not iptal.is_set() and time.monotonic() < dinleme_sonu:
                if gonderim_zamanlari and time.monotonic() >= gonderim_zamanlari[0]:
                    gonderim_zamanlari.pop(0)
                    for s in soketler:
                        for st in SSDP_HEDEFLER:
                            try:
                                s.sendto(ssdp_istegi(st), SSDP_ADRES)
                            except OSError as hata:
                                self.notlar.append(f"M-SEARCH gönderilemedi: {hata}")
                hazir, _, _ = select.select(soketler, [], [], 0.2)
                for s in hazir:
                    try:
                        veri, (adres, _) = s.recvfrom(4096)
                    except OSError:
                        continue
                    kayit = ssdp_yanitini_coz(veri, adres)
                    if kayit:
                        kayitlar.setdefault((adres, kayit.kayit, kayit.alanlar.get("usn", "")), kayit)
        finally:
            for s in soketler:
                s.close()
        sonuc = list(kayitlar.values())
        if self.aciklama_oku:
            self._aciklamalari_oku(sonuc, bitis, iptal)
        return sonuc

    def _aciklamalari_oku(self, kayitlar: list[Kayit], bitis: float, iptal: threading.Event) -> None:
        okunan: dict[str, dict[str, str] | None] = {}
        for kayit in kayitlar:
            konum = kayit.alanlar.get("location", "")
            if not konum:
                continue
            if konum not in okunan:
                kalan = bitis - time.monotonic()
                if iptal.is_set() or kalan < 0.3 or len(okunan) >= self.en_fazla_aciklama:
                    break
                try:
                    govde, basliklar = _guvenli_get_baslikli(konum, kayit.adres, min(1.5, kalan - 0.1))
                    okunan[konum] = upnp_aciklamasini_coz(govde)
                    if basliklar.get("application-url"):  # DIAL REST kökü (cihazın kendi bildirdiği)
                        okunan[konum]["dial_url"] = basliklar["application-url"][:200]
                except Exception as hata:
                    okunan[konum] = None
                    self.notlar.append(f"açıklama okunamadı ({kayit.adres}): {type(hata).__name__}")
            aciklama = okunan.get(konum)
            if aciklama:
                kayit.alanlar.update(aciklama)
                kayit.ad = aciklama.get("friendlyname", "")


# ---------------------------------------------------------------- Tuya yerel yayını
# Doğrulandı (16 Kas 2026, tinytuya kaynak kodu core/udp_helper.py, core/header.py,
# core/message_helper.py): UDP anahtarı md5(b"yGAdlopoPVldABfn"); 55AA çerçevesi
# ">4I" başlık + [retcode] + yük + CRC32 + 0x0000AA55; 3.1 cihazlar 6666'da açık JSON,
# 3.3/3.4 6667'de AES-128-ECB (PKCS7); 3.5 cihazlar 0x6699 çerçevesi ">IHIII" başlık,
# 12 bayt IV + AES-GCM (AAD = başlığın önek sonrası 14 baytı) + 16 bayt etiket + 0x00009966.
# Gerçek bir 3.5 cihaz yayınıyla doğrulanmadı.
TUYA_PORTLARI = (6666, 6667, 7000)
TUYA_UDP_ANAHTARI = hashlib.md5(b"yGAdlopoPVldABfn").digest()
_ONEK_55AA, _SONEK_55AA = 0x000055AA, 0x0000AA55
_ONEK_6699, _SONEK_6699 = 0x00006699, 0x00009966


def _pkcs7_kaldir(veri: bytes) -> bytes:
    if not veri or veri[-1] < 1 or veri[-1] > 16 or veri[-veri[-1]:] != bytes([veri[-1]]) * veri[-1]:
        raise ValueError("geçersiz dolgu")
    return veri[:-veri[-1]]


def _ecb_coz(anahtar: bytes, veri: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    if not veri or len(veri) % 16:
        raise ValueError("blok uzunluğu hatalı")
    cozucu = Cipher(algorithms.AES(anahtar), modes.ECB()).decryptor()
    return _pkcs7_kaldir(cozucu.update(veri) + cozucu.finalize())


def _json_yuk(veri: bytes) -> dict | None:
    veri = veri.rstrip(b"\x00")
    bas = veri.find(b"{")
    if bas < 0:
        return None
    try:
        sonuc = json.loads(veri[bas:].decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    return sonuc if isinstance(sonuc, dict) else None


def tuya_yayinini_coz(veri: bytes) -> tuple[dict, str] | None:
    """Tuya UDP yayınını çözer → (json, biçim) ya da None. Ağ kullanmaz."""
    if len(veri) < 20:
        return None
    onek = struct.unpack(">I", veri[:4])[0]
    try:
        if onek == _ONEK_55AA:
            _, _, _, uzunluk = struct.unpack(">4I", veri[:16])
            if uzunluk < 8 or 16 + uzunluk > len(veri) or uzunluk > 4096:
                return None
            yuk = veri[16:16 + uzunluk - 8]
            if struct.unpack(">I", veri[16 + uzunluk - 4:16 + uzunluk])[0] != _SONEK_55AA:
                return None
            # Yükün başında 4 baytlık dönüş kodu (0) olabilir.
            govde = yuk[4:] if yuk[:4] == b"\x00\x00\x00\x00" else yuk
            if govde[:1] == b"{":
                acik = _json_yuk(govde)
                return (acik, "55aa-acik") if acik is not None else None
            for govde in (govde, yuk) if govde is not yuk else (yuk,):
                try:
                    cozulmus = _json_yuk(_ecb_coz(TUYA_UDP_ANAHTARI, govde))
                except ValueError:
                    continue
                if cozulmus is not None:
                    return cozulmus, "55aa-ecb"
            return None
        if onek == _ONEK_6699:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            _, _, _, _, uzunluk = struct.unpack(">IHIII", veri[:18])
            son = 18 + uzunluk + 4
            if uzunluk < 28 or son > len(veri) or struct.unpack(">I", veri[son - 4:son])[0] != _SONEK_6699:
                return None
            govde = veri[18:son - 4]
            iv, sifreli, etiket = govde[:12], govde[12:-16], govde[-16:]
            acik = AESGCM(TUYA_UDP_ANAHTARI).decrypt(iv, sifreli + etiket, veri[4:18])
            sonuc = _json_yuk(acik)
            return (sonuc, "6699-gcm") if sonuc is not None else None
        # Çerçevesiz ham ECB (tinytuya'nın son çare yolu)
        sonuc = _json_yuk(_ecb_coz(TUYA_UDP_ANAHTARI, veri))
        return (sonuc, "ham-ecb") if sonuc is not None else None
    except Exception:
        return None


def tuya_kaydi_olustur(veri: bytes, kaynak_ip: str, port: int) -> Kayit | None:
    cozum = tuya_yayinini_coz(veri)
    if cozum is None:
        return None
    js, bicim = cozum
    adres = str(js.get("ip") or kaynak_ip)
    if not _ozel_ipv4(adres):
        adres = kaynak_ip
    alanlar = {"servis": "tuya-yayin", "bicim": bicim, "port": str(port)}
    for anahtar, hedef in (("gwId", "cihaz_kimligi"), ("productKey", "urun_anahtari"),
                           ("version", "surum"), ("encrypt", "sifreli"), ("active", "etkin"),
                           ("ablilty", "yetenek"), ("ability", "yetenek"), ("mode", "mod")):
        if anahtar in js:
            alanlar[hedef] = str(js[anahtar])[:80]
    return Kayit("tuya", adres, "tuya-yayin", "", alanlar)


class TuyaYoklayici:
    """Tuya cihazlarının kendi yayınlarını yalnızca dinler; hiçbir paket göndermez."""
    ad = "tuya"

    def __init__(self, portlar: tuple[int, ...] = TUYA_PORTLARI):
        self.portlar = portlar
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        soketler = {}
        for port in self.portlar:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.bind(("", port))
                s.setblocking(False)
                soketler[s] = port
            except OSError as hata:
                self.notlar.append(f"UDP {port} dinlenemedi: {hata}")
        if not soketler:
            raise YoklayiciHatasi("Tuya yayın portlarının hiçbiri dinlenemedi")
        kayitlar: dict[str, Kayit] = {}
        ham_paket = cozulemeyen = 0
        try:
            while not iptal.is_set() and time.monotonic() < bitis:
                hazir, _, _ = select.select(list(soketler), [], [], 0.25)
                for s in hazir:
                    try:
                        veri, (adres, _) = s.recvfrom(2048)
                    except OSError:
                        continue
                    ham_paket += 1
                    kayit = tuya_kaydi_olustur(veri, adres, soketler[s])
                    if kayit is None:
                        cozulemeyen += 1
                        continue
                    kayitlar.setdefault(kayit.adres + "|" + kayit.alanlar.get("cihaz_kimligi", ""), kayit)
        finally:
            for s in soketler:
                s.close()
        self.notlar.append(f"{ham_paket} UDP paketi alındı, {cozulemeyen} tanesi Tuya yayını olarak çözülemedi")
        return list(kayitlar.values())


# ---------------------------------------------------------------- kimliksiz bilgi uçları
def cast_bilgisini_coz(veri: bytes) -> dict[str, str]:
    js = json.loads(veri.decode("utf-8", "replace"))
    bilgi = js.get("device_info") or {}
    sonuc = {"kaynak": "googlecast-eureka"}
    if js.get("name"):
        sonuc["friendlyname"] = str(js["name"])[:120]
    for k, h in (("manufacturer", "manufacturer"), ("model_name", "modelname")):
        if bilgi.get(k):
            sonuc[h] = str(bilgi[k])[:120]
    return sonuc


def samsung_bilgisini_coz(veri: bytes) -> dict[str, str]:
    js = json.loads(veri.decode("utf-8", "replace"))
    aygit = js.get("device") or {}
    sonuc = {"kaynak": "samsung-api-v2", "manufacturer": "Samsung"}
    for k, h in (("name", "friendlyname"), ("modelName", "modelname"), ("OS", "os"), ("type", "tip")):
        if aygit.get(k):
            sonuc[h] = str(aygit[k])[:120]
    return sonuc


# aile -> (URL şablonu, ayrıştırıcı). Yalnız o aileye zaten sınıflanmış adreste okunur.
BILGI_UCLARI: dict[str, tuple[str, Callable[[bytes], dict[str, str]]]] = {
    "googlecast": ("http://{ip}:8008/setup/eureka_info?params=name,device_info", cast_bilgisini_coz),
    "tizen": ("http://{ip}:8001/api/v2/", samsung_bilgisini_coz),
}


def bilgi_ucu_oku(aile: str, ip: str, zaman_asimi: float) -> Kayit:
    sablon, cozucu = BILGI_UCLARI[aile]
    alanlar = cozucu(_guvenli_get(sablon.format(ip=ip), ip, zaman_asimi, sinir=65_536))
    return Kayit("bilgi_ucu", ip, alanlar.get("kaynak", aile), alanlar.get("friendlyname", ""), alanlar)


# ================================================================ E06-3 ek yoklayıcılar (17 Kas 2026)
# Hepsi salt okunur: tablo okuma (ARP, Wi‑Fi listesi), bilinen keşif selamları (cihazın
# kendi keşif protokolü; durum değiştirmez), dar imza portuna TCP bağlantı (veri yok) ve
# pasif BLE reklam dinleme. Hiçbiri komut/eşleştirme göndermez.
import os
import re
import subprocess
import sys
from pathlib import Path

def _ev_klasoru(alt: str) -> Path:
    """Statik ev verisi (oui.csv) ve isteğe bağlı paketler (pydeps: bleak, tinytuya) için klasör.

    G-A2 (18 Kas): ikisi de programla dağıtılır (kullanıcı verisi değil): oui.csv → Yumi/assets/veri/,
    pydeps → Yumi/lib/ev/pydeps/ (kurulumda salt okunur uygulama klasörü).
    Sıra: YUMI_EV_<ALT> ortam değişkeni → uygulama içi yer → eski Yumi/data/ev/<alt> (geçiş) → geliştirme kopyası
    (work/cihaz_bulucu/<alt>, yalnız aday çalışırken; Yumi etkin kodu work/'e yol yazmaz).
    """
    ortam = os.environ.get("YUMI_EV_" + alt.upper())
    if ortam:
        return Path(ortam)
    burasi = Path(__file__).resolve()
    yeni = {"veri": burasi.parents[1] / "assets" / "veri", "pydeps": burasi.parents[1] / "lib" / "ev" / "pydeps"}
    adaylar = [yeni[alt]] if alt in yeni else []
    adaylar.append(burasi.parents[1] / "data" / "ev" / alt)          # eski yer (A2 öncesi)
    if burasi.parents[1].name == "aday":                           # work/cihaz_bulucu/aday/yumi_skills/x.py
        adaylar.append(burasi.parents[2] / alt)
    return next((a for a in adaylar if a.exists()), adaylar[0])


VERI_KLASORU = _ev_klasoru("veri")


def _komut(args: list[str], zaman_asimi: float) -> str:
    bayrak = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        cikti = subprocess.run(args, capture_output=True, timeout=max(0.5, zaman_asimi), creationflags=bayrak)
    except (OSError, subprocess.SubprocessError):
        return ""
    for kod in ("utf-8", "cp857", "cp1254", "latin-1"):
        try:
            return cikti.stdout.decode(kod)
        except UnicodeDecodeError:
            continue
    return ""


_MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})")
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def arp_tablosunu_coz(metin: str) -> dict[str, str]:
    """``arp -a`` / ``ip neigh`` / Get-NetNeighbor çıktısı → {ip: MAC (AA:BB:..)}; ağsız."""
    tablo: dict[str, str] = {}
    for satir in metin.splitlines():
        ip, mac = _IP_RE.search(satir), _MAC_RE.search(satir)
        if not ip or not mac:
            continue
        m = mac.group(1).replace("-", ":").upper()
        if m in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00") or m.startswith("01:00:5E") or m.startswith("33:33"):
            continue
        if _ozel_ipv4(ip.group(1)) and not ip.group(1).endswith(".255"):
            tablo[ip.group(1)] = m
    return tablo


def rastgele_mac(mac: str) -> bool:
    """Yerel yönetimli (telefonların rastgele) MAC: ilk baytın 0x02 biti."""
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


class OuiTablosu:
    """IEEE OUI (MA-L) CSV'si: Registry,Assignment,Organization Name,... (veri/oui.csv)."""

    def __init__(self, yol: Path | None = None):
        self.yol = yol or VERI_KLASORU / "oui.csv"
        self._tablo: dict[str, str] | None = None

    def _yukle(self) -> dict[str, str]:
        if self._tablo is None:
            self._tablo = {}
            try:
                import csv
                with open(self.yol, encoding="utf-8", errors="replace", newline="") as f:
                    for satir in csv.reader(f):
                        if len(satir) >= 3 and len(satir[1]) == 6:
                            self._tablo[satir[1].upper()] = satir[2].strip()
            except OSError:
                pass
        return self._tablo

    def uretici(self, mac: str) -> str:
        return self._yukle().get(mac.replace(":", "").replace("-", "").upper()[:6], "")


def varsayilan_ag_gecidi() -> str:
    metin = _komut(["route", "print", "-4", "0.0.0.0"] if os.name == "nt" else ["ip", "route"], 3.0)
    for satir in metin.splitlines():
        parca = satir.split()
        if os.name == "nt" and len(parca) >= 3 and parca[0] == "0.0.0.0" and parca[1] == "0.0.0.0":
            return parca[2]
        if os.name != "nt" and parca[:2] == ["default", "via"] and len(parca) > 2:
            return parca[2]
    return ""


def yerel_alt_aglar(gecit: str = "") -> list[tuple[str, int]]:
    """(yerel IPv4, önek) — özel adresli arayüzler; ağ geçidi biliniyorsa yalnız onun alt ağı (sanal kartlar elenir)."""
    sonuc: list[tuple[str, int]] = []
    try:
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if isinstance(ip.ip, str) and _ozel_ipv4(ip.ip):
                    sonuc.append((ip.ip, int(ip.network_prefix)))
    except Exception:
        sonuc = [(a, 24) for a in yerel_ipv4_adresleri()]
    if gecit:
        ayni = [(a, p) for a, p in sonuc
                if ipaddress.ip_address(gecit) in ipaddress.ip_network(f"{a}/{max(p, 16)}", strict=False)]
        sonuc = ayni or sonuc
    return sonuc


def arp_supur(alt_aglar: list[tuple[str, int]], bitis: float, iptal: threading.Event,
              en_fazla: int = 254) -> dict[str, str]:
    """Etkin ARP taraması (18 Kas): alt ağdaki her adrese yalnız ARP 'kimdir?' sorusu (Windows SendARP).
    Cihaza veri/komut gitmez; ARP önbelleğinde olmayan telefon/PC/IoT'yi de görünür kılar. {ip: MAC}."""
    if os.name != "nt":
        return {}
    import ctypes
    import struct
    try:
        send_arp = ctypes.windll.iphlpapi.SendARP
        send_arp.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        send_arp.restype = ctypes.c_ulong
    except Exception:
        return {}
    hedefler: list[str] = []
    for yerel, onek in alt_aglar:
        ag = ipaddress.ip_network(f"{yerel}/{max(int(onek), 24)}", strict=False)  # en çok /24 (254 adres)
        hedefler += [str(h) for h in ag.hosts() if str(h) != yerel]
    hedefler = list(dict.fromkeys(hedefler))[:en_fazla]
    sonuc: dict[str, str] = {}
    kilit = threading.Lock()

    def sor(ip: str):
        if iptal.is_set() or time.monotonic() > bitis:
            return
        hedef = struct.unpack("<I", socket.inet_aton(ip))[0]
        tampon = (ctypes.c_ubyte * 6)()
        uzunluk = ctypes.c_ulong(6)
        if send_arp(hedef, 0, ctypes.byref(tampon), ctypes.byref(uzunluk)) == 0 and uzunluk.value == 6:
            mac = ":".join(f"{b:02X}" for b in tampon)
            if mac not in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
                with kilit:
                    sonuc[ip] = mac
    isler = [threading.Thread(target=sor, args=(ip,), daemon=True, name="YumiArp") for ip in hedefler]
    for t in isler:  # her adres ayrı iş parçacığında: yanıtsız adresin ~1–3 sn beklemesi toplam süreyi uzatmaz
        t.start()
        time.sleep(0.006)  # ARP sorularını ~1,5 sn'ye yay (Wi‑Fi'ı bir anda yayınla boğma)
    for t in isler:
        t.join(max(0.0, bitis - time.monotonic()))
    with kilit:
        return dict(sonuc)


class EnvanterYoklayici:
    """ARP önbelleği + etkin ARP taraması (yalnız ARP sorusu) + MAC üreticisi + ağ geçidi + ana makine adı
    (ters DNS). Cihaza veri/komut göndermez."""
    ad = "envanter"

    def __init__(self, oui: OuiTablosu | None = None, ters_dns: bool = True, arp_metni: str | None = None,
                 supur: bool = True):
        self.oui = oui or OuiTablosu()
        self.ters_dns = ters_dns
        self.arp_metni = arp_metni
        self.supur = supur and arp_metni is None
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        supurulen: dict[str, str] = {}
        if self.supur:
            gecit0 = varsayilan_ag_gecidi()
            alt = yerel_alt_aglar(gecit0)
            # SSDP/mDNS yanıt penceresi (ilk ~4 sn) geçtikten sonra başla: ARP yayını çoklu yayın yanıtlarını boğmasın
            iptal.wait(max(0.0, min(4.0, bitis - time.monotonic() - 5.5)))
            supurulen = arp_supur(alt, min(bitis - 1.5, time.monotonic() + 5.0), iptal)
            self.notlar.append(f"etkin ARP taraması: {', '.join(f'{a}/{p}' for a, p in alt) or 'arayüz yok'} → "
                               f"{len(supurulen)} yanıt")
        metin = self.arp_metni if self.arp_metni is not None else _komut(
            ["arp", "-a"] if os.name == "nt" else ["ip", "neigh"], min(4.0, bitis - time.monotonic()))
        tablo = arp_tablosunu_coz(metin)
        for ip, mac in supurulen.items():
            if _ozel_ipv4(ip):
                tablo.setdefault(ip, mac)
        gecit = varsayilan_ag_gecidi() if self.arp_metni is None else ""
        yerel = set(yerel_ipv4_adresleri())
        adlar: dict[str, str] = {}
        if self.ters_dns and tablo:
            def coz(ip):
                try:
                    adlar[ip] = socket.gethostbyaddr(ip)[0][:80]
                except OSError:
                    pass
            isler = [threading.Thread(target=coz, args=(ip,), daemon=True) for ip in tablo]
            for t in isler:
                t.start()
            son = min(bitis, time.monotonic() + 2.5)
            for t in isler:
                t.join(max(0.0, son - time.monotonic()))
        kayitlar = []
        for ip, mac in sorted(tablo.items()):
            alanlar = {"mac": mac, "uretici": self.oui.uretici(mac)}
            if rastgele_mac(mac):
                alanlar["rastgele_mac"] = "1"
            if ip == gecit:
                alanlar["ag_gecidi"] = "1"
            if ip in yerel:
                alanlar["bu_bilgisayar"] = "1"
            ad = adlar.get(ip, "")
            if ad and ad != ip:
                alanlar["ana_makine"] = ad
            kayitlar.append(Kayit("envanter", ip, "arp", ad, alanlar))
        self.notlar.append(f"ARP: {len(tablo)} adres; ağ geçidi {gecit or '?'}; ters DNS {len(adlar)} ad")
        return kayitlar


# ---------------------------------------------------------------- keşif selamları (UDP)
def _kasa_sifrele(veri: bytes) -> bytes:
    anahtar, cikti = 171, bytearray()
    for b in veri:
        anahtar = anahtar ^ b
        cikti.append(anahtar)
    return bytes(cikti)


def _kasa_coz(veri: bytes) -> bytes:
    anahtar, cikti = 171, bytearray()
    for b in veri:
        cikti.append(anahtar ^ b)
        anahtar = b
    return bytes(cikti)


KASA_SORGUSU = b'{"system":{"get_sysinfo":{}}}'
YEELIGHT_ISTEGI = (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1982\r\n"
                   b'MAN: "ssdp:discover"\r\nST: wifi_bulb\r\n\r\n')

# (servis, hedef adres, port, istek). Hepsi üreticinin kendi KEŞİF sorgusudur; durum değiştirmez.
SELAMLAR = (
    ("miio-hello", "255.255.255.255", 54321, bytes.fromhex("21310020" + "ff" * 28)),
    ("roomba-mcs", "255.255.255.255", 5678, b"irobotmcs"),
    ("kasa-sysinfo", "255.255.255.255", 9999, _kasa_sifrele(KASA_SORGUSU)),
    ("yeelight", "239.255.255.250", 1982, YEELIGHT_ISTEGI),
)


def selam_yanitini_coz(servis: str, veri: bytes, adres: str) -> Kayit | None:
    """Selam yanıtını ayrıştırır (ağsız). Gönderdiğimiz paketin yankısını eler."""
    alanlar: dict[str, str] = {"servis": servis}
    if servis == "miio-hello":
        if len(veri) != 32 or veri[:2] != b"\x21\x31" or veri[4:8] == b"\xff" * 4:
            return None
        alanlar["cihaz_kimligi"] = str(struct.unpack(">I", veri[8:12])[0])
        alanlar["belirtec_acik"] = "1" if veri[16:32] not in (b"\x00" * 16, b"\xff" * 16) else "0"
        return Kayit("selam", adres, servis, "", alanlar)
    if servis == "roomba-mcs":
        js = _json_yuk(veri)
        if not js or "irobotmcs" == veri.decode("latin-1"):
            return None
        for k, h in (("hostname", "ana_makine"), ("robotname", "ad"), ("sku", "model"), ("mac", "mac"),
                     ("sw", "surum")):
            if js.get(k):
                alanlar[h] = str(js[k])[:80]
        if isinstance(js.get("cap"), dict):
            alanlar["irobot_cap"] = json.dumps(js["cap"])[:400]
        return Kayit("selam", adres, servis, alanlar.get("ad", ""), alanlar)
    if servis == "kasa-sysinfo":
        if veri == _kasa_sifrele(KASA_SORGUSU):
            return None
        js = _json_yuk(_kasa_coz(veri))
        bilgi = ((js or {}).get("system") or {}).get("get_sysinfo") or {}
        if not bilgi:
            return None
        for k, h in (("alias", "ad"), ("model", "model"), ("mic_type", "tip"), ("type", "tip"),
                     ("deviceId", "cihaz_kimligi"), ("mac", "mac"), ("relay_state", "role"),
                     ("is_dimmable", "kisilabilir"), ("is_color", "renkli")):
            if k in bilgi:
                alanlar[h] = str(bilgi[k])[:80]
        alanlar["kasa_sysinfo"] = json.dumps(bilgi, ensure_ascii=False)[:1500]
        return Kayit("selam", adres, servis, alanlar.get("ad", ""), alanlar)
    if servis == "yeelight":
        metin = veri.decode("utf-8", "replace")
        if not metin.upper().startswith("HTTP/1.1 200"):
            return None
        basliklar = {}
        for satir in metin.splitlines()[1:]:
            if ":" in satir:
                k, v = satir.split(":", 1)
                basliklar[k.strip().casefold()] = v.strip()[:400]
        for k, h in (("id", "cihaz_kimligi"), ("model", "model"), ("support", "yeelight_destek"),
                     ("power", "guc"), ("bright", "parlaklik"), ("name", "ad"), ("location", "location")):
            if basliklar.get(k):
                alanlar[h] = basliklar[k]
        return Kayit("selam", adres, servis, alanlar.get("ad", ""), alanlar)
    return None


class SelamYoklayici:
    """Bilinen yerel keşif selamları (miIO hello, iRobot, Kasa sysinfo, Yeelight)."""
    ad = "selam"

    def __init__(self, selamlar=SELAMLAR):
        self.selamlar = selamlar
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        soketler: dict[socket.socket, str] = {}
        yerel = set(yerel_ipv4_adresleri())
        for servis, hedef, port, istek in self.selamlar:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                s.bind(("", 0))
                s.setblocking(False)
                s.sendto(istek, (hedef, port))
                soketler[s] = servis
            except OSError as hata:
                self.notlar.append(f"{servis} selamı gönderilemedi: {hata}")
        kayitlar: dict[tuple, Kayit] = {}
        try:
            son = min(bitis, time.monotonic() + 3.0)
            while soketler and not iptal.is_set() and time.monotonic() < son:
                hazir, _, _ = select.select(list(soketler), [], [], 0.2)
                for s in hazir:
                    try:
                        veri, (adres, _) = s.recvfrom(4096)
                    except OSError:
                        continue
                    if adres in yerel or not _ozel_ipv4(adres):
                        continue
                    k = selam_yanitini_coz(soketler[s], veri, adres)
                    if k:
                        kayitlar.setdefault((adres, k.kayit), k)
        finally:
            for s in soketler:
                s.close()
        return list(kayitlar.values())


# ---------------------------------------------------------------- imza portları (2. aşama)
def tcp_acik(ip: str, port: int, zaman_asimi: float) -> bool:
    if not _ozel_ipv4(ip):
        return False
    try:
        with socket.create_connection((ip, port), timeout=zaman_asimi):
            return True  # bağlantı açılıp hemen kapanır; veri gönderilmez
    except OSError:
        return False


def http_imzasi(ip: str, zaman_asimi: float) -> dict[str, str]:
    try:
        govde, basliklar = _guvenli_get_baslikli(f"http://{ip}/", ip, zaman_asimi, sinir=16_384)
    except Exception:
        return {}
    sonuc = {}
    if basliklar.get("server"):
        sonuc["http_server"] = basliklar["server"][:120]
    m = re.search(rb"<title>(.*?)</title>", govde, re.I | re.S)
    if m:
        sonuc["http_baslik"] = m.group(1).decode("utf-8", "replace").strip()[:120]
    return sonuc


def tls_konusu(ip: str, port: int, zaman_asimi: float) -> str:
    import ssl
    if not _ozel_ipv4(ip):
        return ""
    bag = ssl.create_default_context()
    bag.check_hostname, bag.verify_mode = False, ssl.CERT_NONE  # yalnız sertifika KONUSU okunur
    try:
        with socket.create_connection((ip, port), timeout=zaman_asimi) as ham:
            with bag.wrap_socket(ham, server_hostname=ip) as s:
                der = s.getpeercert(binary_form=True)
        from cryptography import x509
        return x509.load_der_x509_certificate(der).subject.rfc4514_string()[:160]
    except Exception:
        return ""


class ImzaYoklayici:
    """Envanterdeki kişisel olmayan adreslerde dar imza port listesi (bkz. IMZA_PORTLARI)."""
    ad = "imza"

    def __init__(self, adresler: list[str], portlar=None, zaman_asimi: float = 0.6):
        from .cihaz_aileleri import IMZA_PORTLARI
        self.adresler = [a for a in adresler if _ozel_ipv4(a)][:32]
        self.portlar = portlar or IMZA_PORTLARI
        self.zaman_asimi = zaman_asimi
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        kayitlar: list[Kayit] = []
        kilit = threading.Lock()

        def yokla(ip):
            for port, okuma, _ in self.portlar:
                if iptal.is_set() or time.monotonic() > bitis:
                    return
                if not tcp_acik(ip, port, self.zaman_asimi):
                    continue
                alanlar = {"port": str(port)}
                if okuma == "http":
                    alanlar.update(http_imzasi(ip, 1.0))
                elif okuma == "tls":
                    konu = tls_konusu(ip, port, 1.0)
                    if konu:
                        alanlar["tls_konu"] = konu
                with kilit:
                    kayitlar.append(Kayit("imza", ip, f"tcp/{port}", "", alanlar))

        isler = [threading.Thread(target=yokla, args=(ip,), daemon=True) for ip in self.adresler]
        for t in isler:
            t.start()
        for t in isler:
            t.join(max(0.0, bitis - time.monotonic()))
        return list(kayitlar)


# ---------------------------------------------------------------- Wi‑Fi çevresi (kurulum kipi)
def wifi_listesini_coz(metin: str) -> list[str]:
    ssidler = []
    for satir in metin.splitlines():
        m = re.match(r"\s*SSID\s+\d+\s*:\s*(.*)$", satir)
        if m and m.group(1).strip() and m.group(1).strip() not in ssidler:
            ssidler.append(m.group(1).strip()[:64])
    return ssidler


class WifiYoklayici:
    """``netsh wlan show networks`` (yalnız çevredeki ağ adlarını okur)."""
    ad = "wifi"

    def __init__(self):
        self.notlar: list[str] = []

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        if os.name != "nt":
            return []
        ssidler = wifi_listesini_coz(_komut(["netsh", "wlan", "show", "networks"], min(4.0, bitis - time.monotonic())))
        self.notlar.append(f"{len(ssidler)} Wi‑Fi ağı görüldü (yalnız kurulum kipi imzaları cihaz sayılır)")
        from .cihaz_aileleri import KURALLAR
        kayitlar = []
        for ssid in ssidler:
            k = Kayit("wifi", "", "ssid", ssid, {"ssid": ssid})
            # yalnız bilinen kurulum kipi imzası taşıyan ağlar cihaz olarak listelenir
            if any(r[0] == "wifi" and r[3] and ssid.casefold().startswith(r[3]) or
                   (r[0] == "wifi" and r[2] == "icerir" and r[3] and r[3] in ssid.casefold()) for r in KURALLAR):
                kayitlar.append(k)
        return kayitlar


# ---------------------------------------------------------------- Bluetooth LE (pasif)
PYDEPS = _ev_klasoru("pydeps")


def ble_kaydi_olustur(adres: str, ad: str, rssi: int | None, uretici: dict, servisler: list[str],
                      servis_verisi: dict) -> Kayit:
    """bleak AdvertisementData alanlarından Kayit (ağsız)."""
    def kisa(u: str) -> str:
        u = str(u).lower()
        return u[4:8] if u.endswith("-0000-1000-8000-00805f9b34fb") and len(u) == 36 else u
    alanlar = {"servis": "ble", "ble_adres": adres}
    if uretici:
        alanlar["ble_sirket"] = ",".join(f"0x{int(k):04x}" for k in sorted(uretici))
        alanlar["ble_uretici_verisi"] = ";".join(f"0x{int(k):04x}={bytes(v).hex()}" for k, v in sorted(uretici.items()))[:300]
    kisalar = sorted({kisa(u) for u in list(servisler) + list(servis_verisi)})
    if kisalar:
        alanlar["ble_servis"] = ",".join(kisalar)[:300]
    if servis_verisi:
        alanlar["ble_servis_verisi"] = ";".join(f"{kisa(k)}={bytes(v).hex()}" for k, v in servis_verisi.items())[:300]
    if rssi is not None:
        alanlar["rssi"] = str(rssi)
    if ad:
        alanlar["ad"] = ad[:60]
    return Kayit("ble", "", "ble", ad or "", alanlar)


BLE_ALT_SUREC = r"""
import asyncio, json, sys, time
sys.path.insert(0, sys.argv[2])
from bleak import BleakScanner
gorulen = {}
def geri(a, r):
    gorulen[a.address] = {"adres": a.address, "ad": r.local_name or a.name or "", "rssi": r.rssi,
        "uretici": {str(k): bytes(v).hex() for k, v in (r.manufacturer_data or {}).items()},
        "servisler": list(r.service_uuids or []),
        "servis_verisi": {str(k): bytes(v).hex() for k, v in (r.service_data or {}).items()}}
async def tara():
    async with BleakScanner(detection_callback=geri):
        await asyncio.sleep(float(sys.argv[1]))
asyncio.run(tara())
print("BLEJSON" + json.dumps(list(gorulen.values())))
"""


class BleYoklayici:
    """Pasif BLE reklam dinleme (bleak; lib/ev/pydeps). Bağlanmaz.

    Ayrı alt süreçte çalışır: pydeps'teki winrt sürümü Yumi .venv'indeki winrt (medya denetimi) ile
    çakışmasın ve asyncio döngüsü Yumi'nin iş parçacıklarına karışmasın (PC'de is_603: aynı süreçte
    'winrt.runtime._internals.load_projection yok' hatası görüldü).
    """
    ad = "ble"

    def __init__(self, sure: float = 6.0, alt_surec=None):
        self.sure = sure
        self.notlar: list[str] = []
        self._alt_surec = alt_surec  # test: callable(sure) -> list[dict]

    def _alt_surecte_tara(self, sure: float) -> list[dict]:
        if self._alt_surec is not None:
            return self._alt_surec(sure)
        if not PYDEPS.is_dir():
            raise YoklayiciHatasi(f"bleak yok: {PYDEPS} bulunamadı")
        bayrak = 0x08000000 if os.name == "nt" else 0
        py = Path(sys.executable)
        if py.name.lower() == "pythonw.exe" and (py.parent / "python.exe").exists():
            py = py.parent / "python.exe"
        r = subprocess.run([str(py), "-X", "utf8", "-c", BLE_ALT_SUREC, f"{sure:.1f}", str(PYDEPS)],
                           capture_output=True, timeout=sure + 15, creationflags=bayrak)
        cikti = r.stdout.decode("utf-8", "replace")
        for satir in cikti.splitlines():
            if satir.startswith("BLEJSON"):
                return json.loads(satir[7:])
        hata = (r.stderr.decode("utf-8", "replace").strip().splitlines() or ["çıktı yok"])[-1]
        raise YoklayiciHatasi(f"BLE taraması yapılamadı: {hata[:200]}")

    def calistir(self, bitis: float, iptal: threading.Event, baglam: dict | None = None) -> list[Kayit]:
        sure = max(1.0, min(self.sure, bitis - time.monotonic() - 1.0))
        if iptal.is_set():
            return []
        try:
            ham = self._alt_surecte_tara(sure)
        except YoklayiciHatasi:
            raise
        except Exception as hata:
            raise YoklayiciHatasi(f"BLE taraması yapılamadı: {type(hata).__name__}: {hata}") from hata
        kayitlar = []
        for a in ham:
            uretici = {int(k): bytes.fromhex(v) for k, v in (a.get("uretici") or {}).items()}
            sv = {k: bytes.fromhex(v) for k, v in (a.get("servis_verisi") or {}).items()}
            kayitlar.append(ble_kaydi_olustur(a.get("adres", ""), a.get("ad", ""), a.get("rssi"), uretici,
                                              a.get("servisler") or [], sv))
        return kayitlar
