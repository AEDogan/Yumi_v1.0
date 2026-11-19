"""Tema girişi (geri uyumlu). 12 Kasım ARAYUZ: asıl tanımlar arayuz/tema.py; eski kayıtlı tema adları
(ios, pearl, ios-dark, night, nexus, lavender) yeni temalara eşlenir."""
import tema as _tema

def _renk(c, yedek):
    return yedek if c == 'transparent' else c

# (arka plan, yazı, soluk, vurgu, asistan, kullanıcı) — ThemePicker küçük resmi ve eski çağrılar için
PALETTES = {k: (t['page'], t['text'], t['muted'], t['accent'], _renk(t['asst_bg'], t['soft']), _renk(t['user_bg'], t['rail_on_bg']))
            for k, t in _tema.TEMALAR.items()}
for _eski, _yeni in _tema.ESKI.items():
    PALETTES.setdefault(_eski, PALETTES[_yeni])
THEMES = [(_tema.TEMALAR[k]['ad'], k) for k in _tema.SIRA]

def stylesheet(theme='inci', opacity=94):
    return _tema.stylesheet(theme, opacity)
