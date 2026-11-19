"""B08 ortak parçalar (torch'suz): etiket tablosu, BIO hizalama, çözme ve ölçümler.
Hem eğitim (egit.py) hem Yumi çalışma zamanı (ONNX) kullanır."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# Yerelde yürütülen niyetler (ilk sürüm: 4 grup + konuşma kontrolü). Geri kalanı Gemini'ye gider.
# 7 Kasım: aç/kapat ile ayarla aynı işleyiciye gider; ayrım parça (eylem/deger) ile yapılır -> tek niyet
BIRLESIK = {"cihaz_ac_kapat": "cihaz_kontrol", "cihaz_ayarla": "cihaz_kontrol"}
YEREL = {"cihaz_kontrol", "cihaz_ac_kapat", "cihaz_ayarla", "cihaz_durum_sor", "sahne_rutin", "sayac", "alarm", "hatirlatici", "kronometre",
         "takvim_ekle", "takvim_sor", "muzik_cal", "medya_kontrol", "ses_duzeyi", "tv_kontrol", "avatar_hareket", "avatar_gorunum",
         "karakter_degistir", "hava_durumu", "saat_tarih", "doviz", "hesap_birim", "iptal_sus", "onay", "ret", "tekrar"}


class Etiketler:
    def __init__(self, niyetler, parcalar):
        self.niyetler = list(niyetler)
        self.parcalar = list(parcalar)
        self.bio = ["O"] + [f"{o}-{p}" for p in self.parcalar for o in ("B", "I")]
        self.niyet_no = {n: i for i, n in enumerate(self.niyetler)}
        self.bio_no = {t: i for i, t in enumerate(self.bio)}

    @classmethod
    def oku(cls, yol):
        d = json.loads(Path(yol).read_text(encoding="utf-8"))
        return cls(d["niyetler"], d["parcalar"])

    def sozluk(self):
        return {"niyetler": self.niyetler, "parcalar": self.parcalar, "bio": self.bio}


def bio_hizala(offsets, aralik, et: Etiketler, yok=-100):
    """Token karakter aralıkları (offset_mapping) + parça aralıkları -> token başına BIO kimliği.
    Özel tokenler (0,0) -> yok. Parçaya giren ilk token B, sonrakiler I."""
    etiket = []
    onceki = None
    for s, e in offsets:
        if s == e:
            etiket.append(yok)
            continue
        bulunan = None
        for i, a in enumerate(aralik):
            if a["bas"] <= s < a["son"]:
                bulunan = i
                break
        if bulunan is None:
            etiket.append(et.bio_no["O"])
            onceki = None
        else:
            tur = aralik[bulunan]["tur"]
            etiket.append(et.bio_no[("I-" if onceki == bulunan else "B-") + tur])
            onceki = bulunan
    return etiket


def bio_coz(offsets, tahmin, et: Etiketler, metin=None):
    """Token BIO tahminleri -> [{"tur","bas","son"(,"metin")}] karakter aralıkları."""
    sonuc, acik = [], None
    for (s, e), t in zip(offsets, tahmin):
        if s == e:
            continue
        ad = et.bio[t]
        if ad.startswith("B-") or (ad.startswith("I-") and (acik is None or acik["tur"] != ad[2:])):
            if acik:
                sonuc.append(acik)
            acik = {"tur": ad[2:], "bas": s, "son": e}
        elif ad.startswith("I-") and acik:
            acik["son"] = e
        else:
            if acik:
                sonuc.append(acik)
            acik = None
    if acik:
        sonuc.append(acik)
    if metin is not None:
        for a in sonuc:
            a["metin"] = metin[a["bas"]:a["son"]]
    return sonuc


def olc(ornekler):
    """ornekler: [{"niyet", "tahmin", ("parcalar", "tahmin_parcalar")}] -> ölçümler."""
    n = len(ornekler)
    niyet_dogru = sum(o["niyet"] == o["tahmin"] for o in ornekler)
    yon_dogru = sum((o["niyet"] in YEREL) == (o["tahmin"] in YEREL) for o in ornekler)
    yanlis_yerel = sum((o["niyet"] not in YEREL) and (o["tahmin"] in YEREL) for o in ornekler)  # sohbet -> komut sanıldı (en kötü hata)
    karisiklik = Counter((o["niyet"], o["tahmin"]) for o in ornekler if o["niyet"] != o["tahmin"])
    tp = fp = fn = 0
    for o in ornekler:
        if "parcalar" not in o:
            continue
        gercek = {(a["tur"], a["bas"], a["son"]) for a in o["parcalar"]}
        tah = {(a["tur"], a["bas"], a["son"]) for a in o.get("tahmin_parcalar", [])}
        tp += len(gercek & tah)
        fp += len(tah - gercek)
        fn += len(gercek - tah)
    f1 = 2 * tp / max(1, 2 * tp + fp + fn) if (tp + fp + fn) else None
    return {"adet": n, "niyet_dogruluk": niyet_dogru / max(1, n), "yerel_gemini_dogruluk": yon_dogru / max(1, n),
            "sohbeti_komut_sanma": yanlis_yerel, "parca_f1": f1, "en_cok_karisan": karisiklik.most_common(10)}


class Kodlayici:
    """Eğitimde ve Yumi'de AYNI tokenizer: tokenizers.BertWordPieceTokenizer (büyük/küçük harf korunur).
    transformers 5.x BertTokenizerFast(vocab_file=...) sözlüğü yüklemiyor, her şeyi [UNK] yapıyordu (7 Kasım tanısı)."""

    def __init__(self, vocab):
        from tokenizers import BertWordPieceTokenizer
        self.tok = BertWordPieceTokenizer(str(vocab), lowercase=False, strip_accents=False)
        self.unk = self.tok.token_to_id("[UNK]")
        self.pad = self.tok.token_to_id("[PAD]")

    def kodla(self, metinler, maxlen=None):
        """-> (ids, mask, offsets) listeleri; maxlen verilirse kes + doldur."""
        if maxlen:
            self.tok.enable_truncation(maxlen); self.tok.enable_padding(length=maxlen, pad_id=self.pad)
        else:
            self.tok.no_truncation(); self.tok.no_padding()
        enc = self.tok.encode_batch(list(metinler))
        return [e.ids for e in enc], [e.attention_mask for e in enc], [e.offsets for e in enc]

    def unk_orani(self, metinler):
        ids, mask, _ = self.kodla(metinler)
        top = sum(len(i) - 2 for i in ids)
        return sum(i.count(self.unk) for i in ids) / max(top, 1)
