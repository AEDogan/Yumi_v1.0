"""Asgari WebSocket istemcisi (RFC 6455, yalnız metin çerçeveleri; stdlib). webOS ve Tizen için.

Ek paket gerektirmez. TLS'te TV'nin öz imzalı sertifikası kabul edilir ama ilk eşleştirmede
parmak izi kaydedilir ve sonraki bağlantılarda karşılaştırılır (TOFU sabitleme).
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import urllib.parse

from .tasima import TasimaHatasi, ev_agi_adresi


class WebSocket:
    def __init__(self, url: str, zaman_asimi: float = 5.0, parmak_izi: str = "", basliklar: dict | None = None):
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("ws", "wss") or not p.hostname or not ev_agi_adresi(p.hostname):
            raise TasimaHatasi("WebSocket yalnız ev ağı adresine")
        port = p.port or (443 if p.scheme == "wss" else 80)
        ham = socket.create_connection((p.hostname, port), timeout=zaman_asimi)
        self.parmak_izi = ""
        if p.scheme == "wss":
            bag = ssl.create_default_context()
            bag.check_hostname, bag.verify_mode = False, ssl.CERT_NONE
            ham = bag.wrap_socket(ham, server_hostname=p.hostname)
            der = ham.getpeercert(binary_form=True) or b""
            self.parmak_izi = hashlib.sha256(der).hexdigest()
            if parmak_izi and parmak_izi != self.parmak_izi:
                ham.close()
                raise TasimaHatasi("TV sertifikası değişmiş (parmak izi uyuşmuyor); yeniden eşleştirin")
        self.s = ham
        anahtar = base64.b64encode(os.urandom(16)).decode()
        yol = (p.path or "/") + (("?" + p.query) if p.query else "")
        ek = "".join(f"{k}: {v}\r\n" for k, v in (basliklar or {}).items())
        self.s.sendall((f"GET {yol} HTTP/1.1\r\nHost: {p.hostname}:{port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {anahtar}\r\nSec-WebSocket-Version: 13\r\n"
                        f"{ek}\r\n").encode())
        yanit = b""
        while b"\r\n\r\n" not in yanit:
            parca = self.s.recv(4096)
            if not parca:
                raise TasimaHatasi("WebSocket el sıkışması yarıda kaldı")
            yanit += parca
            if len(yanit) > 65536:
                raise TasimaHatasi("el sıkışma yanıtı çok uzun")
        bas, self._tampon = yanit.split(b"\r\n\r\n", 1)
        if b" 101 " not in bas.split(b"\r\n", 1)[0]:
            raise TasimaHatasi("WebSocket reddedildi: " + bas.split(b"\r\n", 1)[0].decode("latin-1"))
        beklenen = base64.b64encode(hashlib.sha1((anahtar + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                                 .encode()).digest()).decode()
        if beklenen.encode() not in bas:
            raise TasimaHatasi("Sec-WebSocket-Accept uyuşmuyor")

    def _oku(self, n: int) -> bytes:
        while len(self._tampon) < n:
            parca = self.s.recv(65536)
            if not parca:
                raise TasimaHatasi("bağlantı kapandı")
            self._tampon += parca
        veri, self._tampon = self._tampon[:n], self._tampon[n:]
        return veri

    def gonder(self, metin: str) -> None:
        yuk = metin.encode("utf-8")
        maske = os.urandom(4)
        n = len(yuk)
        bas = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                               bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                               bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(bas + maske + bytes(b ^ maske[i % 4] for i, b in enumerate(yuk)))

    def al(self) -> str:
        parcalar = b""
        while True:
            b1, b2 = self._oku(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._oku(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._oku(8))[0]
            maske = self._oku(4) if b2 & 0x80 else b""
            yuk = self._oku(n)
            if maske:
                yuk = bytes(b ^ maske[i % 4] for i, b in enumerate(yuk))
            if op == 0x8:
                raise TasimaHatasi("sunucu bağlantıyı kapattı")
            if op == 0x9:  # ping → pong
                self.s.sendall(bytes([0x8A, 0x80 | len(yuk)]) + b"\0\0\0\0" + yuk)
                continue
            if op in (0x1, 0x0, 0x2):
                parcalar += yuk
                if b1 & 0x80:
                    return parcalar.decode("utf-8", "replace")

    def kapat(self) -> None:
        try:
            self.s.sendall(bytes([0x88, 0x80]) + b"\0\0\0\0")
        except OSError:
            pass
        self.s.close()
