"""B08: Spotify'da doğrudan çalma (Spotify Web API, Authorization Code + PKCE; istemci sırrı yok).
Koşullar (Spotify kuralları, Şubat 2026): hesap Premium olmalı; geliştirici uygulamasını hesap sahibi kendisi oluşturur ve Client ID'yi Yumi'ye verir.
Yönlendirme adresi: http://127.0.0.1:8765/callback (Spotify 'localhost' kabul etmiyor, IP yazılmalı).
Yenileme anahtarı Windows DPAPI ile şifreli saklanır (<veri>/yerel_ai_spotify.json). Parola Yumi'ye hiç gelmez.
Ağ çağrıları arka planda çalıştırılır (yönlendiriciden çağrılabilir iş olarak)."""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8765
YONLENDIRME = f"http://127.0.0.1:{PORT}/callback"
KAPSAM = "user-modify-playback-state user-read-playback-state user-read-currently-playing"
API = "https://api.spotify.com/v1"
KURULUM = ("Spotify bağlantısı için bir kerelik hazırlık: 1) developer.spotify.com/dashboard adresinde Spotify hesabınla giriş yap, "
           "'Create app' de. 2) Ad olarak Yumi yaz, Redirect URI kutusuna http://127.0.0.1:8765/callback ekle, 'Web API'yi seç ve kaydet. "
           "3) Uygulamanın ayarlarındaki Client ID'yi kopyala ve bana 'Spotify kimliği' diye başlayıp yapıştırarak yaz. "
           "Not: Spotify bu özelliği yalnız Premium hesaplarda açıyor.")


def _koru(metin):
    try:
        from platform_win import protect
        return "dpapi:v1:" + base64.b64encode(protect(metin.encode("utf-8"))).decode("ascii")
    except Exception:
        return None  # DPAPI yoksa (Windows dışı) saklama: her açılışta yeniden onay


def _ac(metin):
    if not metin or not metin.startswith("dpapi:v1:"):
        return None
    try:
        from platform_win import unprotect
        return unprotect(base64.b64decode(metin[9:])).decode("utf-8")
    except Exception:
        return None


class SpotifyHatasi(Exception):
    pass


class OnayGerekli(SpotifyHatasi):
    """Yenileme anahtarı geçersizleşti: giriş/onay sayfası yeniden açılmalı (11 Kasım)."""


class Spotify:
    def __init__(self, veri_klasoru: Path | None = None):
        self.dosya = Path(veri_klasoru) / "yerel_ai_spotify.json" if veri_klasoru else None
        self.client_id = None
        self._yenileme = None
        self._erisim, self._bitis = None, 0.0
        self._kilit = threading.Lock()
        if self.dosya and self.dosya.is_file():
            try:
                d = json.loads(self.dosya.read_text(encoding="utf-8"))
                self.client_id = d.get("client_id")
                self._yenileme = _ac(d.get("yenileme"))
            except (OSError, ValueError):
                pass

    # ------------------------------------------------------------ durum
    @property
    def bagli(self):
        return bool(self.client_id and self._yenileme)

    def _kaydet(self):
        if not self.dosya:
            return
        d = {"client_id": self.client_id, "yenileme": _koru(self._yenileme) if self._yenileme else None}
        try:
            self.dosya.parent.mkdir(parents=True, exist_ok=True)
            g = self.dosya.with_suffix(".tmp")
            g.write_text(json.dumps(d, indent=1), encoding="utf-8"); g.replace(self.dosya)
        except OSError:
            pass

    def kimlik_ayarla(self, client_id: str):
        self.client_id = client_id.strip(); self._yenileme = None; self._kaydet()

    def kopar(self):
        self._yenileme = self._erisim = None; self._kaydet()

    # ------------------------------------------------------------ onay (PKCE)
    def bagla(self, ac=webbrowser.open, bekleme_s=180):
        """Tarayıcıda Spotify onay sayfasını açar, 127.0.0.1:8765'te dönüşü bekler. -> söylenecek cümle."""
        if not self.client_id:
            return KURULUM
        dogrulayici = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
        meydan = base64.urlsafe_b64encode(hashlib.sha256(dogrulayici.encode()).digest()).rstrip(b"=").decode()
        durum = secrets.token_urlsafe(16)
        sonuc = {}

        class Isleyici(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if not self.path.startswith("/callback"):
                    self.send_response(404); self.end_headers(); return
                if q.get("state", [""])[0] != durum:
                    sonuc["hata"] = "güvenlik denetimi tutmadı"
                elif "error" in q:
                    sonuc["hata"] = q["error"][0]
                else:
                    sonuc["kod"] = q.get("code", [""])[0]
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
                mesaj = "Spotify bağlandı, bu sekmeyi kapatabilirsin." if "kod" in sonuc else "Spotify bağlantısı tamamlanamadı."
                self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{mesaj}</h2></body></html>".encode("utf-8"))

            def log_message(self, *a):
                pass

        try:
            sunucu = http.server.HTTPServer(("127.0.0.1", PORT), Isleyici)
        except OSError:
            return f"Bilgisayarda {PORT} numaralı bağlantı noktası kullanımda; Spotify bağlantısı şu an başlatılamadı."
        sunucu.timeout = 1
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": YONLENDIRME, "scope": KAPSAM,
            "code_challenge_method": "S256", "code_challenge": meydan, "state": durum})
        ac(url)
        son = time.time() + bekleme_s
        try:
            while not sonuc and time.time() < son:
                sunucu.handle_request()
        finally:
            sunucu.server_close()
        if "kod" not in sonuc:
            return f"Spotify bağlantısı tamamlanmadı ({sonuc.get('hata', 'süre doldu')})."
        try:
            self._anahtar_al({"grant_type": "authorization_code", "code": sonuc["kod"], "redirect_uri": YONLENDIRME,
                              "client_id": self.client_id, "code_verifier": dogrulayici})
        except SpotifyHatasi as e:
            return f"Spotify bağlantısı tamamlanmadı: {e}"
        return "Spotify bağlandı. Artık 'Spotify'dan şu şarkıyı çal' dediğinde doğrudan çalacağım."

    def _anahtar_al(self, form):
        istek = urllib.request.Request("https://accounts.spotify.com/api/token", data=urllib.parse.urlencode(form).encode(),
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(istek, timeout=8) as y:
                d = json.loads(y.read())
        except urllib.error.HTTPError as e:
            ayrinti = e.read().decode("utf-8", "ignore")[:200]
            if "invalid_grant" in ayrinti:
                self.kopar()
                raise OnayGerekli("Spotify onayı geçersizleşmiş, 'Spotify'ı bağla' diyerek yeniden onay ver") from None
            raise SpotifyHatasi(f"Spotify yanıtı {e.code}: {ayrinti}") from None
        self._erisim, self._bitis = d["access_token"], time.time() + int(d.get("expires_in", 3600)) - 60
        if d.get("refresh_token"):
            self._yenileme = d["refresh_token"]
        self._kaydet()

    def _erisim_anahtari(self):
        with self._kilit:
            if self._erisim and time.time() < self._bitis:
                return self._erisim
            if not self.bagli:
                raise SpotifyHatasi("Spotify bağlı değil")
            self._anahtar_al({"grant_type": "refresh_token", "refresh_token": self._yenileme, "client_id": self.client_id})
            return self._erisim

    def _istek(self, yontem, yol, govde=None, sorgu=None):
        url = API + yol + ("?" + urllib.parse.urlencode(sorgu) if sorgu else "")
        veri = json.dumps(govde).encode() if govde is not None else (b"" if yontem in ("PUT", "POST") else None)
        istek = urllib.request.Request(url, data=veri, method=yontem,
                                       headers={"Authorization": f"Bearer {self._erisim_anahtari()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(istek, timeout=8) as y:
                ham = y.read()
                try:
                    return json.loads(ham) if ham else {}
                except ValueError:  # bazı oynatıcı komutları JSON olmayan gövde döndürüyor (is_090)
                    return {}
        except urllib.error.HTTPError as e:
            ayrinti = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 403 and "PREMIUM" in ayrinti.upper():
                raise SpotifyHatasi("Spotify doğrudan çalmayı yalnız Premium hesaplarda izin veriyor") from None
            if e.code == 404 and "device" in ayrinti.lower():
                raise SpotifyHatasi("açık bir Spotify cihazı bulunamadı") from None
            raise SpotifyHatasi(f"Spotify yanıtı {e.code}: {ayrinti}") from None

    # ------------------------------------------------------------ çalma
    def _cihaz(self):
        cihazlar = self._istek("GET", "/me/player/devices").get("devices", [])
        bilgisayar = lambda: [c for c in cihazlar if c.get("type") == "Computer"]
        if not bilgisayar():  # Yumi bu bilgisayarda çalar: başka cihaz (ör. Echo Dot) olsa da önce masaüstü uygulamasını aç (10 Kasım)
            try:
                os.startfile("spotify:")  # type: ignore[attr-defined]
            except Exception:
                webbrowser.open("https://open.spotify.com")
            for _ in range(12):
                time.sleep(1.2)
                cihazlar = self._istek("GET", "/me/player/devices").get("devices", [])
                if bilgisayar():
                    break
        if not cihazlar:
            return None
        secim = bilgisayar()  # bilgisayar yoksa yalnız o an çalan başka cihaz kullanılır; boştaki hoparlöre (Echo vb.) kendiliğinden gönderilmez
        c = (next((c for c in secim if c.get("is_active")), None) or (secim[0] if secim else None)
             or next((c for c in cihazlar if c.get("is_active")), None))
        return c["id"] if c else None

    def _etkinlestir(self, cihaz):
        """Yeni açılan uygulama cihaz listesinde görünür ama etkin değildir; çal komutu kabul edilip ses başlamaz
        (is_088). Önce çalma bu cihaza devredilir."""
        try:
            d = self._istek("GET", "/me/player") or {}
        except SpotifyHatasi:
            d = {}
        if (d.get("device") or {}).get("id") != cihaz:
            self._istek("PUT", "/me/player", govde={"device_ids": [cihaz], "play": False})
            time.sleep(0.8)

    def _caliyor_mu(self, sure_s=3.0):
        son = time.time() + sure_s
        while time.time() < son:
            time.sleep(0.5)
            try:
                if (self._istek("GET", "/me/player") or {}).get("is_playing"):
                    return True
            except SpotifyHatasi:
                pass
        return False

    def cal(self, sorgu: str, yalniz_sanatci=False, _tekrar=False):
        """-> söylenecek cümle; Client ID yoksa None (çağıran arama sayfasına düşer).
        Oturum yoksa ya da geçersizleştiyse Spotify giriş/onay sayfasını kendiliğinden açar,
        onaydan sonra aynı isteği çalar (Gemini oturumu gibi; kullanıcı, 11 Kasım)."""
        if not self.client_id:
            return None
        if not self.bagli:
            if _tekrar:
                return None
            sonuc = self.bagla()
            if not self.bagli:
                return sonuc
        try:
            tur = "artist,track" if yalniz_sanatci else "track,artist,playlist"
            s = self._istek("GET", "/search", sorgu={"q": sorgu, "type": tur, "limit": 5})  # market=from_token ek izin (user-read-private) istiyor -> 403 (is_087)
            govde, ad = None, None
            sanatcilar = [a for a in (s.get("artists", {}).get("items") or []) if a]
            parcalar = [t for t in (s.get("tracks", {}).get("items") or []) if t]
            listeler = [p for p in (s.get("playlists", {}).get("items") or []) if p]
            if yalniz_sanatci and sanatcilar:
                govde, ad = {"context_uri": sanatcilar[0]["uri"]}, sanatcilar[0]["name"]
            elif parcalar and not re.search(r"liste|playlist|karışık|mix", sorgu.lower()):
                t = parcalar[0]
                # tek 'uris' boş oynatıcıda kabul edilip çalmıyor; albüm bağlamı + konum çalıyor (is_090)
                govde = ({"context_uri": t["album"]["uri"], "offset": {"uri": t["uri"]}} if (t.get("album") or {}).get("uri")
                         else {"uris": [t["uri"]]})
                ad = f"{', '.join(a['name'] for a in t.get('artists', [])[:2])} - {t['name']}"
            elif listeler:
                govde, ad = {"context_uri": listeler[0]["uri"]}, listeler[0]["name"]
            elif sanatcilar:
                govde, ad = {"context_uri": sanatcilar[0]["uri"]}, sanatcilar[0]["name"]
            if not govde:
                return f"Spotify'da '{sorgu}' için bir şey bulamadım."
            cihaz = self._cihaz()
            if not cihaz:
                return "Spotify açık bir cihazda görünmüyor; Spotify uygulamasını açıp tekrar dener misin?"
            self._etkinlestir(cihaz)
            for _ in range(2):  # komut kabul edilip ses başlamazsa bir kez daha (is_088)
                self._istek("PUT", "/me/player/play", govde=govde, sorgu={"device_id": cihaz})
                if self._caliyor_mu():
                    return f"Spotify'da {ad} çalıyor."
            return "Spotify komutu aldı ama çalma başlamadı; Spotify uygulamasına bir bakar mısın?"
        except OnayGerekli:
            if _tekrar:
                return "Spotify'da çalamadım: onay yenilenemedi."
            sonuc = self.bagla()
            return self.cal(sorgu, yalniz_sanatci, _tekrar=True) if self.bagli else sonuc
        except SpotifyHatasi as e:
            return f"Spotify'da çalamadım: {e}."
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
