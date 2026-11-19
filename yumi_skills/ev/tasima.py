"""Adaptörlerin ortak ağ katmanı: yalnız ev ağı (özel IPv4) adresleri, kısa zaman aşımı,
yönlendirme izlenmez ve YAZMA KİLİDİ.

Yazma kilidi: ``Tasima(yazma=False)`` (varsayılan) iken cihaz durumunu değiştirebilecek her
istek (GET dışı HTTP, adı Get/Query/List ile başlamayan SOAP eylemi, WebSocket'te okuma dışı
istek) ``YazmaKilitli`` fırlatır. Gerçek ağda salt okunur döküm bu kipte çalışır.
Testler sahte bir Tasima (aynı arayüz) verir; ağ kullanılmaz.
"""
from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape


class YazmaKilitli(PermissionError):
    pass


class TasimaHatasi(RuntimeError):
    pass


OKUMA_EYLEMI = re.compile(r"^(Get|Query|List|Browse|X_Get)", re.I)


def ev_agi_adresi(adres: str) -> bool:
    try:
        ip = ipaddress.ip_address(adres)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local


class _YonlendirmeYok(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _xml_guvenli(veri: bytes) -> ET.Element:
    if b"<!DOCTYPE" in veri[:2048] or b"<!ENTITY" in veri:
        raise TasimaHatasi("DTD içeren XML reddedildi")
    return ET.fromstring(veri)


def soap_govdesi(servis: str, eylem: str, argumanlar: dict[str, Any]) -> bytes:
    ic = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in argumanlar.items())
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{eylem} xmlns:u="{servis}">{ic}</u:{eylem}></s:Body></s:Envelope>').encode("utf-8")


def soap_yanitini_coz(veri: bytes) -> dict[str, str]:
    kok = _xml_guvenli(veri)
    govde = next((e for e in kok.iter() if e.tag.endswith("}Body") or e.tag == "Body"), None)
    if govde is None or not len(govde):
        raise TasimaHatasi("SOAP gövdesi yok")
    yanit = govde[0]
    if yanit.tag.endswith("Fault"):
        kod = next((e.text for e in yanit.iter() if e.tag.endswith("errorCode")), "")
        acik = next((e.text for e in yanit.iter() if e.tag.endswith("errorDescription")), "")
        raise TasimaHatasi(f"UPnP hatası {kod} {acik}".strip())
    return {c.tag.split("}")[-1]: (c.text or "") for c in yanit}


class Tasima:
    def __init__(self, yazma: bool = False, zaman_asimi: float = 3.0):
        self.yazma = yazma
        self.zaman_asimi = zaman_asimi
        self._acici = urllib.request.build_opener(_YonlendirmeYok())

    # -- yardımcılar
    def _url_denetle(self, url: str) -> None:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or not ev_agi_adresi(p.hostname):
            raise TasimaHatasi(f"yalnız ev ağı adresleri: {url[:60]}")
        if p.username or p.password:
            raise TasimaHatasi("kimlikli URL reddedildi")

    def yazma_denetle(self, ne: str) -> None:
        if not self.yazma:
            raise YazmaKilitli(f"salt okunur kip: '{ne}' gönderilmedi")

    def istek(self, yontem: str, url: str, govde: bytes | None = None, basliklar: dict | None = None,
              sinir: int = 1_048_576, yazma: bool | None = None) -> tuple[int, dict[str, str], bytes]:
        self._url_denetle(url)
        if (yazma if yazma is not None else yontem.upper() != "GET"):
            self.yazma_denetle(f"{yontem} {url}")
        bas = {"User-Agent": "Yumi-ev/0.1"}
        bas.update(basliklar or {})
        return self._ag(yontem, url, govde, bas, sinir)

    def _ag(self, yontem: str, url: str, govde: bytes | None, bas: dict, sinir: int) -> tuple[int, dict[str, str], bytes]:
        """Gerçek HTTP (testlerde sahte taşıma yalnız bunu ezer; adres/kilit denetimi yukarıda kalır)."""
        istek = urllib.request.Request(url, data=govde, headers=bas, method=yontem.upper())
        bag = None
        if url.startswith("https"):
            import ssl  # TV'ler öz imzalı sertifika kullanır; yalnız ev ağı adresinde
            bag = ssl.create_default_context()
            bag.check_hostname, bag.verify_mode = False, ssl.CERT_NONE
        try:
            acici = self._acici if bag is None else urllib.request.build_opener(
                _YonlendirmeYok(), urllib.request.HTTPSHandler(context=bag))
            with acici.open(istek, timeout=self.zaman_asimi) as y:
                return y.status, {k.casefold(): v for k, v in y.headers.items()}, y.read(sinir)
        except urllib.error.HTTPError as h:
            return h.code, {k.casefold(): v for k, v in (h.headers or {}).items()}, h.read(sinir) if h.fp else b""

    def get(self, url: str, sinir: int = 1_048_576) -> tuple[int, dict[str, str], bytes]:
        return self.istek("GET", url, sinir=sinir)

    def get_json(self, url: str) -> Any:
        kod, _, govde = self.get(url)
        if kod != 200:
            raise TasimaHatasi(f"HTTP {kod}")
        return json.loads(govde.decode("utf-8", "replace"))

    def get_xml(self, url: str) -> ET.Element:
        kod, _, govde = self.get(url)
        if kod != 200:
            raise TasimaHatasi(f"HTTP {kod}")
        return _xml_guvenli(govde)

    def soap(self, kontrol_url: str, servis: str, eylem: str, argumanlar: dict[str, Any] | None = None) -> dict[str, str]:
        okuma = bool(OKUMA_EYLEMI.match(eylem))
        kod, _, govde = self.istek(
            "POST", kontrol_url, soap_govdesi(servis, eylem, argumanlar or {}),
            {"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{servis}#{eylem}"'},
            yazma=not okuma)
        if kod not in (200, 500):
            raise TasimaHatasi(f"SOAP HTTP {kod}")
        return soap_yanitini_coz(govde)

    # -- Wake-on-LAN (durum değiştirir → yazma kilidine tabi)
    def wol_gonder(self, mac: str, yayin: str = "255.255.255.255", port: int = 9) -> bool:
        """Sihirli paket. MAC 12 onaltılık hane olmalı. Yazma kilidi kapalıysa YazmaKilitli."""
        temiz = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
        if len(temiz) != 12:
            raise ValueError("geçerli MAC adresi gerekli")
        self.yazma_denetle(f"Wake-on-LAN {mac}")
        self._udp_ag(bytes.fromhex("FF" * 6 + temiz * 16), yayin, port)
        return True

    def _udp_ag(self, paket: bytes, yayin: str, port: int) -> None:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(paket, (yayin, port))

    # -- ham TCP satır protokolleri (Yeelight, Kasa) için
    def tcp_istek(self, adres: str, port: int, veri: bytes, yazma: bool, sinir: int = 65536,
                  satir_sonu: bytes | None = b"\r\n") -> bytes:
        if not ev_agi_adresi(adres):
            raise TasimaHatasi(f"yalnız ev ağı adresleri: {adres}")
        if yazma:
            self.yazma_denetle(f"TCP {adres}:{port}")
        return self._tcp_ag(adres, port, veri, sinir, satir_sonu)

    def _tcp_ag(self, adres: str, port: int, veri: bytes, sinir: int, satir_sonu: bytes | None) -> bytes:
        import socket
        with socket.create_connection((adres, port), timeout=self.zaman_asimi) as s:
            s.sendall(veri)
            alinan = b""
            while len(alinan) < sinir:
                try:
                    parca = s.recv(4096)
                except socket.timeout:
                    break
                if not parca:
                    break
                alinan += parca
                if satir_sonu and alinan.endswith(satir_sonu):
                    break
            return alinan
