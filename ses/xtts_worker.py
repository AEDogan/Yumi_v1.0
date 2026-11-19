"""G-S2 (18 Kas 2026): akış üretiminde metin bitince durdurma (hizalama; aşağıda HIZALAMA_*).
12 Kasım (is_148/149, Yumi'ye alındı): kısa metinde uzayan/geveleyen üretimi süre sınırıyla keser, akış sonu boyut hatasını yutar,
isteğe bağlı fp16 autocast. Persistent XTTS worker (runs inside runtime/xtts-env). stdout carries JSON lines only.

Request : {"model_dir": str, "checkpoint": str, "refs": [str], "text": str, "lang": "tr",
           "out": str, "params": {...}}
Response: {"ok": true, "out": str} or {"ok": false, "error": str}
One model stays loaded; switching characters reloads (each fine-tuned model is ~1.9 GB).
"""
import json, os, sys
protocol = sys.stdout
sys.stdout = sys.stderr
os.environ.setdefault("COQUI_TOS_AGREED", "1")
import soundfile as sf, torch, torchaudio

def _sf_load(uri, *args, **kwargs):
    data, rate = sf.read(uri, dtype="float32")
    tensor = torch.from_numpy(data)
    return (tensor.unsqueeze(0) if tensor.ndim == 1 else tensor.t()), rate
torchaudio.load = _sf_load
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
# G-F2 (18 Kas 2026): .pth ağırlıkları yalnız tensör olarak yüklenir (pickle ile kod çalışmaz). Xtts.load_checkpoint →
# trainer.io.load_fsspec → torch.load(weights_only=trainer.io._WEIGHTS_ONLY); torch>=2.4'te zaten True, burada sabitlenir.
# Ölçüm: Modeller + ana modüldeki 22 .pth weights_only=True ile yüklendi, tensörler weights_only=False ile birebir aynı
# (work/ayirma/f2/pth_weights_only.md).
import trainer.io as _trainer_io
_trainer_io._WEIGHTS_ONLY = True

CIHAZ = "cuda" if torch.cuda.is_available() else ("xpu" if hasattr(torch, "xpu") and torch.xpu.is_available() else None)
loaded = {"key": None, "model": None, "latents": {}}

def model_for(model_dir, checkpoint):
    key = (model_dir, checkpoint)
    if loaded["key"] != key:
        loaded["model"] = None; loaded["latents"] = {}
        config = XttsConfig(); config.load_json(os.path.join(model_dir, "config.json"))
        model = Xtts.init_from_config(config)
        model.load_checkpoint(config, checkpoint_path=os.path.join(model_dir, checkpoint),
                              vocab_path=os.path.join(model_dir, "vocab.json"), eval=True, strict=False, use_deepspeed=False)
        if CIHAZ:
            model.to(CIHAZ)  # F1b: ROCm/CUDA "cuda", Intel Arc "xpu"; CPU ortamında atlanır
        loaded.update(key=key, model=model)
    return loaded["model"]

def prepared(request):
    params = request.get("params", {})
    model = model_for(request["model_dir"], request["checkpoint"])
    refs = tuple(request["refs"])
    latents = loaded["latents"].get(refs)
    if latents is None:
        latents = model.get_conditioning_latents(audio_path=list(refs), gpt_cond_len=int(params.get("gpt_cond_len", 14)),
                                                 max_ref_length=30, sound_norm_refs=bool(params.get("sound_norm_refs", True)))
        loaded["latents"][refs] = latents
    return model, params, latents

_eq_onbellek = {}
def _eq_suzgec(db):
    """Ses başına tiz yükseltme (boğukluk için, 10 Kasım kullanıcı dinleme kabulü: japan_girl +7 dB).
    3 kHz üstü yumuşak geçişli raf; 257 dokulu doğrusal fazlı FIR (gecikme 128 örnek ~5 ms)."""
    if db not in _eq_onbellek:
        import numpy as np
        from scipy.signal import firwin2
        f = np.linspace(0, 12000, 241)
        g = 1 + (10 ** (db / 20) - 1) / (1 + np.exp(-(f - 3000) / 400))
        _eq_onbellek[db] = firwin2(257, f, g, fs=24000)
    return _eq_onbellek[db]

# G-S2 (18 Kas 2026): metin bitince durdurma. XTTS cümle sonunda yazıda olmayan hece/kelime uyduruyordu (taban %21,9).
# GPT'nin metin token'larına dikkati izlenir: seçili hizalama kafalarında (katman, kafa) "stop_text" token'ına düşen dikkat
# (metin bölgesinde, start_text ve dil etiketi hariç normalize) metin okundukça yükselir, son kelimede tepe yapar (~0,4–0,6).
# Model metni bitirip uydurmaya başlayınca dikkat metnin başına/ortasına döner ve bu değer düşer → düştüğü adımda üretim
# durdurulur, ses o token'a kadar çözülür (kesim üretim anında; çalar uydurmayı hiç almaz). Kafalar 4 sesin (anime Yumi,
# varsayılan Yumi, Ciri, Geralt) 192 üretiminden seçildi (dikkat konumu–zaman ilişkisi en düzgün olanlar), seslerden bağımsız.
# Ölçüm ve gerekçe: work/ses_hece/DEVIR.md §4, work/ses_hece/s2/. Kapatmak: params["hizalama_dur"] = False ya da YUMI_HIZALAMA_DUR=0.
HIZALAMA_BASLAR = ((4, 2), (4, 4), (3, 4), (12, 3), (17, 8), (3, 11), (13, 4))
HIZALAMA_AYAR = {"kurmak": 0.3, "kurmak_n": 1.6, "dusus": 0.9, "sure": 1, "geri": 2, "en_erken": 6, "en_az_kuyruk": 5, "kuyruk_tepe": 0.44}

class _Hizalama:
    """c_attn kancası: seçili kafaların son sorgusunun metin bölgesine dikkatinden stop_text payı (adım başına bir sayı)."""
    def __init__(self, gpt2, baslar):
        self.nh = gpt2.config.n_head; self.hd = gpt2.config.n_embd // self.nh; self.olcek = self.hd ** -0.5
        self.baslar = {}
        for l, h in baslar: self.baslar.setdefault(l, []).append(h)
        self.etkin = False; self.K = {}; self.deger = {}
        self.kancalar = [gpt2.h[l].attn.c_attn.register_forward_hook(self._kanca(l)) for l in self.baslar]
    def basla(self, a, b):  # metin bölgesi [a, b): a = start_text; a+1 = dil etiketi; b-1 = stop_text
        self.a, self.b = a, b; self.K = {}; self.deger = {}; self.etkin = True
    def bitir(self):
        self.etkin = False; self.K = {}; self.deger = {}
    def _kanca(self, l):
        hs = self.baslar[l]
        def f(mod, inp, out):
            if not self.etkin: return
            E = out.shape[-1] // 3
            if l not in self.K:  # ilk (önek) geçişi: metin bölgesinin anahtarları bir kez saklanır
                if out.shape[1] < self.b: return
                self.K[l] = out[0, self.a + 2:self.b, E:2 * E].float().view(-1, self.nh, self.hd)[:, hs]  # [n, kafa, hd]
            q = out[0, -1, :E].float().view(self.nh, self.hd)[hs]
            s = torch.softmax(torch.einsum("hd,nhd->hn", q, self.K[l]) * self.olcek, -1)
            self.deger[l] = s[:, -1]
        return f
    def oku(self):
        if len(self.deger) != len(self.baslar): return None
        return float(torch.cat([self.deger[l] for l in self.baslar]).mean())

class _Durdurucu:
    """Adım başına stop-dikkati s verilir. Kurulma: s'nin tepesi ≥ max(kurmak, kurmak_n / n) (n = metin token sayısı; kısa
    metinde tek token'a düşen pay zaten yüksek). Kurulduktan sonra s < tepe × dusus olursa kesim: düşüşün başladığı adımdan
    `geri` token önce. Tepe zayıfsa (< kuyruk_tepe; uzun cümlenin son hecesi) kesim, s'nin eşiği ilk geçtiği adımdan en az
    en_az_kuyruk token sonraya ertelenir. İlk en_erken adımın değeri tepeye sayılmaz (başlangıçta dikkat dağınık)."""
    def __init__(self, n, kurmak=0.3, kurmak_n=1.6, dusus=0.9, sure=1, geri=2, en_erken=6, en_az_kuyruk=5, kuyruk_tepe=0.44):
        self.kurmak = max(float(kurmak), float(kurmak_n) / max(1, int(n)))
        self.dusus, self.sure, self.geri, self.en_erken = float(dusus), int(sure), int(geri), int(en_erken)
        self.en_az_kuyruk = None if en_az_kuyruk is None else int(en_az_kuyruk); self.kuyruk_tepe = float(kuyruk_tepe)
        self.tepe = 0.0; self.t = -1; self.alt = 0; self.ilk_alt = None; self.gecis = None
    def adim(self, s):
        self.t += 1
        if s is None: return None
        if self.gecis is None and self.t >= self.en_erken and s >= self.kurmak: self.gecis = self.t
        if self.tepe >= self.kurmak and s < self.tepe * self.dusus:
            if self.alt == 0: self.ilk_alt = self.t
            self.alt += 1
            if self.alt < self.sure: return None
            c = max(1, self.ilk_alt - self.geri)
            if self.en_az_kuyruk is not None and self.tepe < self.kuyruk_tepe and self.gecis is not None:
                c = max(c, self.gecis + self.en_az_kuyruk)
                if c > self.t + 1:
                    self.alt = 0; return None
            return c
        self.alt = 0
        if self.t >= self.en_erken: self.tepe = max(self.tepe, s)
        return None

_hizalama = {"model": None, "nesne": None}
def _hizalama_for(model):
    if _hizalama["model"] is not model:
        if _hizalama["nesne"] is not None:
            for k in _hizalama["nesne"].kancalar: k.remove()
        _hizalama.update(model=model, nesne=_Hizalama(model.gpt.gpt, HIZALAMA_BASLAR))
    return _hizalama["nesne"]

def _akis_uret(model, text, language, gpt_cond_latent, speaker_embedding, stream_chunk_size=20, overlap_wav_len=1024,
               temperature=0.75, repetition_penalty=10.0, top_k=50, top_p=0.85, speed=1.0, durdur=None, durum=None):
    """Xtts.inference_stream (coqui-tts 0.28, tek cümle, bölmesiz) ile aynı + hizalama durdurması (durdur = ayar dict)."""
    import torch.nn.functional as F
    with torch.inference_mode():
        length_scale = 1.0 / max(speed, 0.05)
        gpt_cond_latent = gpt_cond_latent.to(model.device); speaker_embedding = speaker_embedding.to(model.device)
        ids = model.tokenizer.encode(text.strip().lower(), lang=language.split("-")[0])
        text_tokens = torch.IntTensor(ids).unsqueeze(0).to(model.device)
        fake_inputs = model.gpt.compute_embeddings(gpt_cond_latent, text_tokens)
        hz = du = None
        if durdur:
            hz = _hizalama_for(model); cl = gpt_cond_latent.shape[1]
            hz.basla(cl, cl + len(ids) + 2); du = _Durdurucu(len(ids), **durdur)
        gen = model.gpt.get_generator(fake_inputs=fake_inputs, top_k=top_k, top_p=top_p, temperature=temperature, do_sample=True,
                                      num_beams=1, num_return_sequences=1, length_penalty=1.0,
                                      repetition_penalty=float(repetition_penalty), output_attentions=False,
                                      output_hidden_states=True, return_dict_in_generate=True)
        last_tokens, all_latents = [], []
        wav_gen_prev = wav_overlap = None
        is_end = False
        try:
            while not is_end:
                try:
                    x, latent = next(gen)
                    last_tokens += [x]; all_latents += [latent]
                    if du is not None:
                        kes = du.adim(hz.oku())
                        if kes is not None:
                            if durum is not None: durum.update(kesim_token=kes, toplam_token=len(all_latents))
                            all_latents = all_latents[:kes]; is_end = True
                except StopIteration:
                    is_end = True
                if is_end or (stream_chunk_size > 0 and len(last_tokens) >= stream_chunk_size):
                    if not all_latents: break
                    gpt_latents = torch.cat(all_latents, dim=0)[None, :]
                    if length_scale != 1.0:
                        gpt_latents = F.interpolate(gpt_latents.transpose(1, 2), scale_factor=length_scale, mode="linear").transpose(1, 2)
                    wav_gen = model.hifigan_decoder(gpt_latents, g=speaker_embedding).squeeze()
                    if wav_gen_prev is not None and wav_gen.shape[0] <= wav_gen_prev.shape[0] - overlap_wav_len:
                        break  # kesim zaten çalınmış bölümün içinde: yeni ses yok
                    wav_chunk, wav_gen_prev, wav_overlap = model.handle_chunks(wav_gen, wav_gen_prev, wav_overlap,
                                                                                overlap_wav_len, is_final=is_end)
                    last_tokens = []
                    yield wav_chunk
        finally:
            if hz is not None: hz.bitir()
            gen.close()

def handle_stream(request):
    """B07: parça parça üret; her parça {"chunk": base64 PCM16 24 kHz} satırı, sonunda done."""
    import base64
    import numpy as np
    model, params, (gpt, speaker) = prepared(request)
    db = float(params.get("eq_tiz_db") or 0)
    h = _eq_suzgec(db) if db else None
    zi = np.zeros(len(h) - 1) if h is not None else None
    def gonder(x):
        pcm = (x.clip(-1, 1) * 32767).astype("<i2").tobytes()
        protocol.write(json.dumps({"chunk": base64.b64encode(pcm).decode("ascii")}) + "\n"); protocol.flush()
    # 12 Kasım (is_148): "Tarkan açılıyor." 2 kelimeye 5 s ses (geveleme) → beklenen sürenin 1,8 katı + 0,7 s'de kes.
    hiz_ = float(params.get("speed", 0.94)) or 1.0
    sinir = int(24000 * (len(request["text"]) / 13.0 / hiz_ * 1.8 + 0.7))
    uretilen = 0
    import contextlib
    oto = torch.autocast(CIHAZ, dtype=torch.float16) if params.get("fp16") and CIHAZ else contextlib.nullcontext()
    durdur = params.get("hizalama_dur", True)
    if os.environ.get("YUMI_HIZALAMA_DUR", "1").strip() == "0": durdur = False
    if durdur is True: durdur = dict(HIZALAMA_AYAR)
    elif isinstance(durdur, dict): durdur = dict(HIZALAMA_AYAR, **durdur)
    durum = {}
    akis = _akis_uret(model, request["text"], request.get("lang", "tr"), gpt, speaker,
                      stream_chunk_size=int(params.get("stream_chunk_size", 20)),
                      temperature=float(params.get("temperature", 0.62)),
                      repetition_penalty=float(params.get("repetition_penalty", 2.8)),
                      top_p=float(params.get("top_p", 0.82)), speed=float(params.get("speed", 0.94)),
                      durdur=durdur or None, durum=durum)
    while True:
        try:
            with oto:
                chunk = next(akis)
        except StopIteration:
            break
        except RuntimeError as e:  # is_148: "Input and output sizes should be greater than 0" akış sonunda
            if uretilen and "sizes should be greater than 0" in str(e): break
            raise
        x = chunk.detach().float().cpu().numpy().reshape(-1)
        dur = uretilen + x.size > sinir
        if dur: x = x[:max(0, sinir - uretilen)]
        uretilen += x.size
        if h is not None and x.size:
            from scipy.signal import lfilter
            x, zi = lfilter(h, 1.0, x, zi=zi)
        if x.size: gonder(x)
        if dur:
            akis.close(); break
    if h is not None:  # süzgeç gecikmesinde kalan son 5 ms
        from scipy.signal import lfilter
        gonder(lfilter(h, 1.0, np.zeros(len(h) // 2), zi=zi)[0])
    return {"ok": True, "done": True, "sr": 24000, **({"tani": durum} if durum else {})}

def handle(request):
    if request.get("stream"):
        return handle_stream(request)
    model, params, (gpt, speaker) = prepared(request)
    out = model.inference(text=request["text"], language=request.get("lang", "tr"), gpt_cond_latent=gpt, speaker_embedding=speaker,
                          temperature=float(params.get("temperature", 0.62)), repetition_penalty=float(params.get("repetition_penalty", 2.8)),
                          top_p=float(params.get("top_p", 0.82)), speed=float(params.get("speed", 0.94)), enable_text_splitting=True)
    wav = out["wav"]
    db = float(params.get("eq_tiz_db") or 0)
    if db:
        import numpy as np
        wav = np.convolve(np.asarray(wav, dtype="float32").reshape(-1), _eq_suzgec(db), mode="same").clip(-1, 1)
    sf.write(request["out"], wav, 24000)
    return {"ok": True, "out": request["out"]}

protocol.write(json.dumps({"ready": True}) + "\n"); protocol.flush()
for line in sys.stdin:
    try:
        response = handle(json.loads(line))
    except Exception as error:  # report, keep serving
        response = {"ok": False, "error": f"{type(error).__name__}: {error}"[:500]}
    protocol.write(json.dumps(response) + "\n"); protocol.flush()
