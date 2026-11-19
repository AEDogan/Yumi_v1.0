"""B08 sözlü öğretme belleği (yeniden eğitimsiz, anında). Bilgisayarda kalır: <veri>/yerel_ai_ogretme.json.

- "bundan sonra 'gece oldu' deyince gece modunu aç" / "'yatıyorum' demek 'ışıkları kapat' demek" -> ifade -> komut
- "hayır onu demek istemedim" -> "Ne demek istemiştin?" -> yanıt uygulanır ve önceki cümle o komut olarak öğrenilir
- "'gece oldu'yu unut" / "öğrettiklerimi say"
Düzeltmeler ayrıca <veri>/yerel_ai_duzeltmeler.jsonl'e yazılır (ileride kullanıcı isterse yerel yeniden eğitim için).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .sayi_zaman import kucuk

DOLGU = re.compile(r"\b(hey|yumi|lütfen|acaba|ya|şey|bi|bakalım|hemen|şimdi|teşekkürler)\b")
OGRET = [re.compile(r"^(?:bundan sonra|artık|bundan böyle)\s+(.+?)\s+(?:dediğimde|deyince|dersem|diyince|dediğim zaman|diyince de)\s+(.+?)$"),
         re.compile(r"^(.+?)\s+(?:dediğimde|deyince|dersem)\s+(.+?)\s+(?:yap|anla)\w*$"),
         re.compile(r"^(.+?)\s+demek\s+(.+?)\s+demek(?:tir)?$")]
DUZELT = re.compile(r"^(?:hayır|yok|yanlış)\b.*(?:demek istemedim|onu demedim|bunu demedim|yanlış anladın|öyle demedim)|^yanlış anladın|^onu demek istemedim")
UNUT = re.compile(r"^(.+?)\s*(?:'?(?:yı|yi|yu|yü|ı|i|u|ü))?\s+(?:komutunu|ifadesini|öğrettiğimi)?\s*unut$")
LISTE = re.compile(r"öğrettiklerimi (?:say|listele|söyle|göster)|neler öğrettim|ne öğrettim")


def anahtar(metin: str) -> str:
    k = kucuk(metin)
    k = re.sub(r"[\"'’“”.,!?]", " ", k)
    k = DOLGU.sub(" ", k)
    return " ".join(k.split())


def _temiz(t):
    return t.strip(" \"'’“”.,!?")


class OgretmeBellegi:
    def __init__(self, veri_klasoru: Path | None = None):
        self.dosya = Path(veri_klasoru) / "yerel_ai_ogretme.json" if veri_klasoru else None
        self.duzeltme_dosyasi = Path(veri_klasoru) / "yerel_ai_duzeltmeler.jsonl" if veri_klasoru else None
        self.ifadeler = {}  # anahtar -> {"ifade", "komut", "tarih"}
        self.tercihler = {}  # ör. muzik_platform -> spotify
        if self.dosya and self.dosya.is_file():
            try:
                d = json.loads(self.dosya.read_text(encoding="utf-8"))
                self.ifadeler, self.tercihler = d.get("ifadeler", {}), d.get("tercihler", {})
            except (OSError, ValueError):
                pass

    def _kaydet(self):
        if not self.dosya:
            return
        try:
            self.dosya.parent.mkdir(parents=True, exist_ok=True)
            g = self.dosya.with_suffix(".tmp")
            g.write_text(json.dumps({"ifadeler": self.ifadeler, "tercihler": self.tercihler}, ensure_ascii=False, indent=1), encoding="utf-8")
            g.replace(self.dosya)
        except OSError:
            pass

    def tercih(self, ad, varsayilan=None):
        return self.tercihler.get(ad, varsayilan)

    def tercih_yap(self, ad, deger):
        self.tercihler[ad] = deger; self._kaydet()

    def ogren(self, ifade, komut):
        self.ifadeler[anahtar(ifade)] = {"ifade": _temiz(ifade), "komut": _temiz(komut), "tarih": dt.datetime.now().isoformat(timespec="seconds")}
        self._kaydet()

    def unut(self, ifade):
        return self.ifadeler.pop(anahtar(ifade), None) is not None and (self._kaydet() or True)

    def bul(self, metin):
        e = self.ifadeler.get(anahtar(metin))
        return e["komut"] if e else None

    def duzeltme_yaz(self, metin, yanlis_niyet, dogru_metin):
        if not self.duzeltme_dosyasi:
            return
        try:
            self.duzeltme_dosyasi.parent.mkdir(parents=True, exist_ok=True)
            with self.duzeltme_dosyasi.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"metin": metin, "yanlis_niyet": yanlis_niyet, "dogru": dogru_metin,
                                    "tarih": dt.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------ cümle tanıma
    @staticmethod
    def ogretme_mi(metin):
        k = kucuk(metin).strip(" .!?")
        k = re.sub(r"^(?:yumi,?\s+|hey yumi,?\s+)", "", k)
        for d in OGRET:
            m = d.match(k)
            if m and len(m.group(1)) >= 2 and len(m.group(2)) >= 2:
                return _temiz(m.group(1)), _temiz(m.group(2))
        return None

    @staticmethod
    def duzeltme_mi(metin):
        return bool(DUZELT.search(kucuk(metin).strip(" .!?")))

    @staticmethod
    def unutma_mi(metin):
        m = UNUT.match(kucuk(metin).strip(" .!?"))
        return _temiz(m.group(1)) if m else None

    @staticmethod
    def liste_mi(metin):
        return bool(LISTE.search(kucuk(metin)))

    def liste_cumlesi(self):
        if not self.ifadeler:
            return "Henüz bana özel bir ifade öğretmedin."
        p = [f"'{e['ifade']}' deyince '{e['komut']}'" for e in list(self.ifadeler.values())[-8:]]
        return f"{len(self.ifadeler)} ifade öğrettin: " + "; ".join(p) + "."
