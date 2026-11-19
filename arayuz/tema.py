"""Yumi temaları (12 Kasım, ARAYUZ; tasarım tuvali "Yumi tema önerileri").

7 tema: İnci, Gece, Taş, Sakura, Witcher kitap, Terminal, Disket. Her tema bir sözlük (renk, yazı tipi, köşe,
logo renkleri, süs türü). `stylesheet()` QSS üretir; `Dekor` panelin arkasına temaya özel çizim yapar
(Witcher: parşömen yaprağı + kalemle çizilen karakter görselleri, Terminal: tarama çizgileri, Sakura: yaprak).
Eski kayıtlı tema adları (ios, pearl, ios-dark, night, nexus, lavender) yenilerine eşlenir.
Yazı tipleri assets/fonts/ (SIL OFL, Google Fonts)."""
from pathlib import Path
import math, time

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / 'assets' / 'fonts'
LOGO = ROOT / 'assets' / 'yumi.svg'

ESKI = {'ios': 'inci', 'pearl': 'inci', 'ios-dark': 'gece', 'night': 'gece', 'nexus': 'gece', 'lavender': 'sakura'}

_ORTAK = dict(header_bg=None, header_text=None, rail_bg=None, rail_text=None, user_italic=False, asst_plain=False,
              user_rule=None, asst_rule=None, radius=18, bubble=18, corner=6, size=14, deco=None, bevel=False,
              brand='yumi', brand_size=21, brand_font=None, brand_weight=700, title_font=None, dark=False,
              composer_lines=False, field_border=None, header_grad=None)

TEMALAR = {
    'inci': dict(_ORTAK, ad='İnci', font='Manrope', bg='#F5F7FA', page='#F5F7FA', text='#12202F', muted='#5E6B7A',
                 accent='#2F62E9', on_accent='#FFFFFF', line='#DCE3EC', field='#FFFFFF', user_bg='#2F62E9',
                 user_text='#FFFFFF', asst_bg='#FFFFFF', asst_text='#12202F', asst_border='#E3E8EF',
                 rail_on_bg='#E6EDFD', rail_on_text='#1D3FA8', rec='#E5484D', soft='#E9EEF5',
                 logo=('#1d2439', '#b38ae5', '#85dfbd', '#1d2439')),
    'gece': dict(_ORTAK, ad='Gece', font='Figtree', bg='#15181E', page='#15181E', text='#F1F4F8', muted='#9AA3AF',
                 accent='#4D7BF5', on_accent='#FFFFFF', line='#272C35', field='#1E222A', user_bg='#3A6DF0',
                 user_text='#FFFFFF', asst_bg='#21252E', asst_text='#F1F4F8', asst_border='#21252E',
                 rail_on_bg='#232C40', rail_on_text='#C9D7FF', rec='#FF6369', soft='#1E222A', dark=True,
                 logo=('#E8ECF5', '#b38ae5', '#85dfbd', '#15181E')),
    'tas': dict(_ORTAK, ad='Taş', font='Schibsted Grotesk', bg='#EEEFEF', page='#EEEFEF', text='#161718',
                muted='#5D6166', accent='#161718', on_accent='#EEEFEF', line='#D3D5D8', field='#EEEFEF',
                user_bg='#DCDEE0', user_text='#161718', asst_bg='transparent', asst_text='#161718',
                asst_border='transparent', asst_rule='#161718', rail_on_bg='#161718', rail_on_text='#EEEFEF',
                rec='#161718', soft='#E2E4E6', radius=6, bubble=4, corner=4, composer_lines=True,
                logo=('#161718', '#8A8E93', '#EEEFEF', '#161718')),
    'sakura': dict(_ORTAK, ad='Sakura', font='M PLUS Rounded 1c', bg='#FFF8FA', page='#FFF8FA', text='#3A2430',
                   muted='#7D5F6C', accent='#E0457B', on_accent='#FFFFFF', line='#FBDCE6', field='#FFFFFF',
                   user_bg='#E0457B', user_text='#FFFFFF', asst_bg='#FFFFFF', asst_text='#3A2430',
                   asst_border='#FBDCE6', rail_on_bg='#FFE1EA', rail_on_text='#B3204F', rec='#E0457B',
                   soft='#FFEFF4', radius=28, bubble=22, corner=8, deco='sakura', brand_weight=800, brand_size=22,
                   logo=('#3A2430', '#F59DBB', '#FFE1EA', '#3A2430')),
    'witcher': dict(_ORTAK, ad='Witcher kitap', font='Alegreya', bg='#1C1B1B', page='#E9DDBF',
                    text='#2B2118', muted='#5A4130', accent='#8A2A1E', on_accent='#F1E6CA', line='#8A6A3E',
                    field='transparent', user_bg='transparent', user_text='#4A3424', asst_bg='transparent',
                    asst_text='#2B2118', asst_border='transparent', user_rule='#8A6A3E', user_italic=True,
                    asst_plain=True, rail_on_bg='#34312F', rail_on_text='#F0EEEA', rec='#8A2A1E', soft='#DCCB9F',
                    header_bg='#1C1B1B', header_text='#DAD7D0', rail_bg='#1C1B1B', rail_text='#9C9FA1',
                    radius=8, bubble=2, corner=2, size=15, deco='witcher', brand='Yumi',
                    brand_font='IM FELL English SC', title_font='IM FELL English SC', brand_weight=400,
                    brand_size=24, composer_lines=True, logo=('#DAD7D0', '#8E9194', '#8E2A1E', '#DAD7D0')),
    'terminal': dict(_ORTAK, ad='Terminal', font='VT323', bg='#0E1210', page='#03180A', text='#39FF6E',
                     muted='#2FD35E', accent='#39FF6E', on_accent='#031A0B', line='#1E8A3C', field='transparent',
                     user_bg='transparent', user_text='#B6FFC8', asst_bg='transparent', asst_text='#39FF6E',
                     asst_border='transparent', rail_on_bg='#39FF6E', rail_on_text='#031A0B', rec='#39FF6E',
                     soft='#06260F', radius=4, bubble=0, corner=0, size=19, deco='terminal', brand='yumi.exe',
                     brand_size=28, brand_weight=400, dark=True, field_border='#39FF6E',
                     logo=('#39FF6E', '#05200D', '#05200D', '#39FF6E')),
    # 13 Kasım (kullanıcı): Windows 98 renkleri ve yazı tipi — gri yüz #C0C0C0, lacivert→mavi başlık, beyaz/koyu kabartma,
    # sistemdeki Microsoft Sans Serif (Windows ile gelir, dağıtılmaz)
    'disket': dict(_ORTAK, ad='Disket', font='Microsoft Sans Serif', bg='#C0C0C0', page='#C0C0C0', text='#000000',
                   muted='#404040', accent='#000080', on_accent='#FFFFFF', line='#808080', field='#FFFFFF',
                   user_bg='transparent', user_text='#000080', asst_bg='transparent', asst_text='#000000',
                   asst_border='transparent', rail_on_bg='#C0C0C0', rail_on_text='#000000', rec='#C00000',
                   soft='#DFDFDF', header_bg='#000080', header_text='#FFFFFF', radius=0, bubble=0, corner=0,
                   header_grad='qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #000080,stop:1 #1084D0)',
                   bevel=True, brand='Yumi', brand_size=13, brand_weight=700, size=12,
                   logo=('#FFFFFF', '#1084D0', '#FFFFFF', '#000080')),
}
SIRA = ['inci', 'gece', 'tas', 'sakura', 'witcher', 'terminal', 'disket']


def anahtar(theme):
    theme = ESKI.get(theme, theme)
    return theme if theme in TEMALAR else 'inci'


def tema(theme):
    return TEMALAR[anahtar(theme)]


# ---------------------------------------------------------------- yazı tipleri
_aileler = None


def yazi_tiplerini_yukle():
    """assets/fonts içindeki TTF'leri bir kez yükler; {istenen ad: gerçek aile adı}."""
    global _aileler
    if _aileler is not None:
        return _aileler
    from PySide6.QtGui import QFontDatabase
    _aileler = {}
    # Disket (Windows 98): Windows'la gelen Microsoft Sans Serif/Tahoma doğrudan yüklenir (dağıtılmaz; yoksa atlanır)
    sistem = [Path(r'C:\Windows\Fonts') / f for f in ('micross.ttf', 'tahoma.ttf', 'tahomabd.ttf')]
    for yol in sorted(FONT_DIR.glob('*.ttf')) + [y for y in sistem if y.exists()]:
        kimlik = QFontDatabase.addApplicationFont(str(yol))
        for aile in QFontDatabase.applicationFontFamilies(kimlik) if kimlik >= 0 else []:
            _aileler.setdefault(aile.casefold(), aile)
    # ARAYUZ 20:15 (kullanıcı: "keskin, ince, g okunmuyor"): Windows ipucu (hinting) kapalı + yumuşatma → daha dolgun yazı
    try:
        from PySide6.QtGui import QFont, QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            f = QFont(app.font()); f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias); app.setFont(f)
    except Exception:
        pass
    return _aileler


def aile(ad):
    if not ad:
        return None
    return yazi_tiplerini_yukle().get(ad.casefold(), ad)


# ---------------------------------------------------------------- logo
def logo_svg(theme):
    d, t, b, n = tema(theme)['logo']
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><g fill="{d}"><ellipse cx="44" cy="109" rx="27" ry="35" transform="rotate(-30 44 109)"/><ellipse cx="91" cy="55" rx="29" ry="38" transform="rotate(-12 91 55)"/><ellipse cx="165" cy="55" rx="29" ry="38" transform="rotate(12 165 55)"/><ellipse cx="212" cy="109" rx="27" ry="35" transform="rotate(30 212 109)"/><path d="M128 105C90 105 79 129 59 156C35 188 54 232 89 232C107 232 112 225 128 225C144 225 149 232 167 232C202 232 221 188 197 156C177 129 166 105 128 105Z"/></g>'
            f'<g fill="{t}"><ellipse cx="44" cy="109" rx="14" ry="20" transform="rotate(-30 44 109)"/><ellipse cx="91" cy="55" rx="16" ry="23" transform="rotate(-12 91 55)"/><ellipse cx="165" cy="55" rx="16" ry="23" transform="rotate(12 165 55)"/><ellipse cx="212" cy="109" rx="14" ry="20" transform="rotate(30 212 109)"/></g>'
            f'<path fill="{b}" d="M86 145Q86 127 104 127H155Q174 127 174 145V175Q174 193 155 193H112L89 207L95 190Q86 186 86 175Z"/><g fill="{n}"><circle cx="110" cy="160" r="6"/><circle cx="130" cy="160" r="6"/><circle cx="150" cy="160" r="6"/></g></svg>')


def logo_pixmap(theme, size=30):
    from PySide6.QtCore import Qt, QByteArray, QRectF
    from PySide6.QtGui import QPixmap, QPainter
    from PySide6.QtSvg import QSvgRenderer
    pix = QPixmap(size * 2, size * 2); pix.fill(Qt.GlobalColor.transparent); pix.setDevicePixelRatio(2.)
    p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(logo_svg(theme).encode())).render(p, QRectF(0, 0, size, size)); p.end()
    return pix


# ---------------------------------------------------------------- QSS
def _rgba(color, alpha):
    if color == 'transparent':
        return 'transparent'
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f'rgba({r},{g},{b},{max(0, min(255, round(alpha * 2.55)))})'


def _anahtar_svgleri(t, klasor):
    """Açma/kapama anahtarı ve onay kutusu görselleri (QSS url ile)."""
    klasor.mkdir(parents=True, exist_ok=True)
    acik = klasor / 'anahtar_acik.svg'; kapali = klasor / 'anahtar_kapali.svg'
    if t['bevel'] or t['deco'] == 'terminal':
        on = f'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect x="1" y="1" width="18" height="18" fill="{t["field"] if t["field"] != "transparent" else t["page"]}" stroke="{t["text"]}" stroke-width="2"/><path d="M5 10l3 3 7-7" fill="none" stroke="{t["text"]}" stroke-width="2.4"/></svg>'
        off = f'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect x="1" y="1" width="18" height="18" fill="{t["field"] if t["field"] != "transparent" else t["page"]}" stroke="{t["text"]}" stroke-width="2"/></svg>'
    else:
        track_off = t['line'] if not t['dark'] else '#3A404A'
        knob = '#FFFFFF' if t['deco'] != 'witcher' else '#F1E6CA'
        on = f'<svg xmlns="http://www.w3.org/2000/svg" width="42" height="25"><rect width="42" height="25" rx="12.5" fill="{t["accent"]}"/><circle cx="29.5" cy="12.5" r="10" fill="{knob}"/></svg>'
        off = f'<svg xmlns="http://www.w3.org/2000/svg" width="42" height="25"><rect width="42" height="25" rx="12.5" fill="{track_off}"/><circle cx="12.5" cy="12.5" r="10" fill="{knob}"/></svg>'
    acik.write_text(on, encoding='utf-8'); kapali.write_text(off, encoding='utf-8')
    return acik.as_posix(), kapali.as_posix()


def stylesheet(theme='inci', opacity=94):
    key = anahtar(theme); t = TEMALAR[key]
    font = aile(t['font']) or 'Segoe UI'; brand_font = aile(t['brand_font']) or font; title_font = aile(t['title_font']) or font
    arrow = (ROOT / 'assets/chevron-down.svg').as_posix()
    try:
        from app_paths import data_dir
        klasor = data_dir() / 'onbellek' / 'tema' / key
    except Exception:
        import tempfile; klasor = Path(tempfile.gettempdir()) / 'Yumi' / 'onbellek' / 'tema' / key  # G-A2: uygulama klasörüne yazılmaz
    sw_on, sw_off = _anahtar_svgleri(t, klasor)
    bg = _rgba(t['bg'], opacity) if t['deco'] not in ('witcher', 'terminal') and not t['bevel'] else t['bg']
    hb = t['header_grad'] or t['header_bg'] or 'transparent'; ht = t['header_text'] or t['text']
    rb = t['rail_bg'] or 'transparent'; rt = t['rail_text'] or t['muted']
    R = t['radius']; B = t['bubble']; C = t['corner']
    bevel_out = 'border:2px solid;border-color:#FFFFFF #404040 #404040 #FFFFFF;' if t['bevel'] else ''
    bevel_in = 'border:2px solid;border-color:#808080 #FFFFFF #FFFFFF #808080;' if t['bevel'] else ''
    user = (f"background:transparent;color:{t['user_text']};border:0;border-right:2px solid {t['user_rule']};border-radius:0;padding:2px 12px 2px 0;font-style:italic"
            if t['user_rule'] else
            f"background:{t['user_bg']};color:{t['user_text']};border-radius:{B}px;border-bottom-right-radius:{C}px;padding:10px 14px")
    if t['deco'] == 'terminal':
        user = f"background:transparent;color:{t['user_text']};padding:2px 0"
    if t['bevel']:
        user = f"background:transparent;color:{t['user_text']};padding:2px 0;font-weight:600"
    if t['asst_rule']:
        asst = f"background:transparent;color:{t['asst_text']};border:0;border-left:2px solid {t['asst_rule']};border-radius:0;padding:2px 0 2px 12px"
    elif t['asst_plain'] or t['deco'] == 'terminal' or t['bevel']:
        asst = f"background:transparent;color:{t['asst_text']};padding:2px 0"
    else:
        asst = f"background:{t['asst_bg']};color:{t['asst_text']};border:1px solid {t['asst_border']};border-radius:{B}px;border-bottom-left-radius:{C}px;padding:10px 14px"
    if t['composer_lines']:
        composer = f"background:transparent;border:0;border-top:1.5px solid {t['line'] if key == 'witcher' else t['text']};border-bottom:{'1px solid ' + t['line'] if key == 'witcher' else '0'};border-radius:0"
    elif t['bevel']:
        composer = f"background:{t['bg']};{bevel_out}border-radius:0"
    elif t['deco'] == 'terminal':
        composer = f"background:transparent;border:1px solid {t['accent']};border-radius:0"
    else:
        composer = f"background:{t['field']};border:1.5px solid {t['line']};border-radius:{max(12, R - 2)}px"
    composer_rec = f"border-color:{t['accent']}" if not t['composer_lines'] else ''
    if t['bevel']:
        button = f"background:{t['bg']};color:{t['text']};{bevel_out}border-radius:0;padding:6px 12px;min-height:22px"
        button_hover = 'background:#D0D0D0'
    elif t['deco'] == 'terminal':
        button = f"background:transparent;color:{t['text']};border:1px solid {t['accent']};border-radius:0;padding:6px 12px;min-height:22px"
        button_hover = f"background:{t['soft']}"
    elif key == 'witcher':
        button = f"background:{_rgba('#8A6A3E', 12)};color:{t['text']};border:1px solid {t['line']};border-radius:4px;padding:8px 12px;min-height:22px"
        button_hover = f"background:{_rgba('#8A6A3E', 24)}"
    else:
        button = f"background:{t['soft']};color:{t['text']};border:1px solid transparent;border-radius:{min(12, R)}px;padding:8px 14px;min-height:22px;font-weight:600"
        button_hover = f"background:{_rgba(t['accent'], 14)}"
    group = (f"background:{t['field']};{bevel_in}border-radius:0;margin-top:20px;padding:18px 12px 12px" if t['bevel'] else
             f"background:transparent;border:1px solid {t['line']};border-radius:0;margin-top:20px;padding:18px 12px 12px" if t['deco'] == 'terminal' else
             f"background:{_rgba('#8A6A3E', 8)};border:1px solid {t['line']};border-radius:4px;margin-top:20px;padding:18px 12px 12px" if key == 'witcher' else
             f"background:{t['field'] if not t['dark'] else t['soft']};border:1px solid {t['line'] if t['field'] != 'transparent' else t['line']};border-radius:16px;margin-top:20px;padding:18px 12px 12px")
    page_bg = 'transparent' if t['deco'] in ('witcher', 'terminal', 'sakura') else t['page']
    dialog_bg = t['page'] if key != 'witcher' else '#E9DDBF'
    # 13 Kasım (kullanıcı): Witcher'da tüm sayfalar aynı parşömen yaprağının üstünde (PageStack çizer); beyaz alan kalmasın
    # 13 Kasım (kullanıcı): sayfalarda beyaz/gri alan kalmasın. QScrollArea içeriğini kendiliğinden boyar → saydam.
    # Açıklama yazıları sayfa zemininde (başlık rengiyle değil) okunur renkte.
    yaprak_qss = (f"#yaprakAlani #brandDescription,#yaprakAlani #caption{{color:{t['muted']}}}"
                  " #yaprakAlani QDialog #qt_scrollarea_viewport,#yaprakAlani QDialog QScrollArea>QWidget>QWidget{background:transparent}")
    if key == 'witcher':
        yaprak_qss += " #yaprakAlani QDialog,#yaprakAlani #settingsPage,#yaprakAlani #activityPage,#yaprakAlani QTabWidget>QWidget,#yaprakAlani QStackedWidget{background:transparent}"
        # 18 Kas (kullanıcı): ayrı pencere açılan diyaloglar (Ev '+ Cihaz', uyarı/soru/giriş kutuları) saydam kalınca
        # koyu zemin üstünde okunmuyordu -> parşömen zemin (gömülü sayfalar yukarıdaki kuralla saydam kalır).
        yaprak_qss += (" #yaprakAlani QDialog#popupDialog,#yaprakAlani QMessageBox,#yaprakAlani QInputDialog,"
                       f"#yaprakAlani QFileDialog{{background:#E9DDBF;color:{t['text']}}}")
    if t['bevel']:  # Windows 98 sekmeleri: kabartmalı gri, seçili sekme öne çıkar
        yaprak_qss += (" QTabWidget::pane{border:2px solid;border-color:#FFFFFF #404040 #404040 #FFFFFF;top:-2px}"
                       " QTabBar::tab{background:#C0C0C0;color:#000000;border:2px solid;border-color:#FFFFFF #404040 #C0C0C0 #FFFFFF;border-radius:0;padding:4px 10px;margin-right:0;margin-top:2px}"
                       " QTabBar::tab:selected{background:#C0C0C0;color:#000000;margin-top:0;padding-bottom:6px}")
    # 17 Kasım (kullanıcı): uyarı bandındaki (Sese yeniden bağlan / Yeniden bağlan) düğmeler koyu üst bantta okunur olsun
    uyari_dugme = '' if t['bevel'] else (f"#uyariBandi QPushButton{{background:{_rgba(ht, 10)};color:{ht};border:1px solid {_rgba(ht, 40)}}}"
                                          f" #uyariBandi QPushButton:hover{{background:{_rgba(ht, 20)}}}"
                                          f" #uyariBandi QPushButton:disabled{{color:{_rgba(ht, 45)};border-color:{_rgba(ht, 20)}}}")
    return f"""
 QWidget{{font-family:'{font}','Segoe UI',sans-serif;font-size:{t['size']}px;color:{t['text']}}}
 QMainWindow{{background:transparent}}
 #root{{background:{bg};border:{'0' if t['bevel'] else '1px solid ' + _rgba(t['muted'], 22)};border-radius:{R + 4 if R else 0}px;{bevel_out}}}
 #header{{background:{hb};border:0;{'border-top-left-radius:' + str(R + 3) + 'px;border-top-right-radius:' + str(R + 3) + 'px;' if hb != 'transparent' and R else ''}}}
 #header QLabel,#header QPushButton{{color:{ht}}}
 #stage{{background:{hb};border:0}}
 #uyariBandi{{background:{hb};border:0}}
 #uyariBandi QLabel{{background:transparent;color:{ht}}}
 {uyari_dugme}
 #brand{{font-family:'{brand_font}';font-size:{t['brand_size']}px;font-weight:{t['brand_weight']};color:{ht};letter-spacing:{'-0.6px' if key in ('inci', 'gece') else '0px'}}}
 #brandDescription,#status,#footer,#sidebarCaption,#caption{{color:{t['muted'] if hb == 'transparent' else (t['rail_text'] or ht)};font-size:12px}}
 #status{{padding:0 4px;font-style:{'italic' if key == 'witcher' else 'normal'}}}
 #navigationRail{{background:{rb};border:0;{('border-right:1px solid ' + t['line']) if key in ('tas', 'terminal') else ''}}}
 QToolButton#navButton{{background:transparent;border:1px solid transparent;border-radius:{0 if t['bevel'] or t['deco'] == 'terminal' else min(16, R)}px;color:{rt};font-size:{11 if key != 'terminal' else 16}px;font-weight:{700 if key == 'sakura' else 600};padding:4px;{('font-family:' + repr(title_font) + ';') if key == 'witcher' else ''}}}
 QToolButton#navButton:hover{{background:{_rgba(t['rail_on_bg'], 60) if not t['bevel'] else '#D0D0D0'};color:{t['rail_on_text'] if key != 'terminal' else t['text']}}}
 QToolButton#navButton:checked{{background:{t['rail_on_bg']};color:{t['rail_on_text']};{bevel_in if t['bevel'] else ''}{'border-color:#6E7174' if key == 'witcher' else ''}}}
 QToolButton#navButton:focus{{border:1px solid {t['accent']}}}
 #panel{{background:{page_bg};border:0;{bevel_in if t['bevel'] else ''}}}
 #chatPage,#historyPage,#chatStack{{background:transparent}}
 #heading{{font-family:'{title_font}';font-size:{19 if key != 'terminal' else 24}px;font-weight:{400 if key in ('witcher', 'terminal') else 700};color:{t['text']}}}
 #badge{{color:{t['muted']};font-size:12px;background:transparent}}
 QPushButton{{{button}}}
 QPushButton:hover{{{button_hover}}}
 QPushButton:pressed{{background:{_rgba(t['accent'], 22) if not t['bevel'] else '#B0B0B0'}}}
 QPushButton:focus,QToolButton:focus,QLineEdit:focus,QComboBox:focus{{border:1px solid {t['accent']}}}
 QPushButton:disabled,QToolButton:disabled{{color:{_rgba(t['muted'], 55)}}}
 #iconButton,#stageButton,#micButton,#historyButton,#backButton{{background:transparent;border:1px solid transparent;border-radius:{0 if t['bevel'] else 10}px;min-height:0;padding:0}}
 #iconButton:hover,#stageButton:hover,#micButton:hover,#historyButton:hover,#backButton:hover{{background:{_rgba(t['accent'], 12) if hb == 'transparent' else _rgba('#FFFFFF', 14)}}}
 #header #iconButton:hover{{background:{_rgba(ht, 14)}}}
 #primaryButton,#sendButton,#jumpButton,#newChat{{background:{t['accent']};color:{t['on_accent']};border:1px solid transparent;font-weight:600;{bevel_out if t['bevel'] else ''}}}
 #newChat{{border-radius:{0 if t['bevel'] else 17}px;padding:6px 14px;min-height:22px}}
 #sendButton{{padding:0;min-height:0;border-radius:{0 if t['bevel'] or key == 'terminal' else (21 if key in ('sakura', 'tas', 'witcher') else 14)}px}}
 #sendButton:hover,#primaryButton:hover,#newChat:hover{{background:{t['accent']};border:1px solid {t['text'] if not t['dark'] else t['on_accent']}}}
 #recordStop{{background:{t['rec'] if key != 'witcher' else 'qradialgradient(cx:0.4,cy:0.35,radius:0.75,fx:0.4,fy:0.35,stop:0 #B23A2A,stop:1 #6E1A12)'};border:{'2px solid #9A2A1C' if key == 'witcher' else '1px solid transparent'};border-radius:{0 if t['bevel'] or key == 'terminal' else 21}px;padding:0;min-height:0}}
 #jumpButton{{border-radius:9px;padding:4px;min-height:0}}
 #dangerButton{{background:transparent;color:{'#B4232A' if not t['dark'] else '#FF8A8F'};border:1px solid {_rgba('#B4232A', 35)}}}
 #dangerButton:disabled,#inspectButton:disabled{{color:{_rgba('#808080', 55)};border:1px solid {_rgba('#808080', 18)}}}
 QScrollArea,QScrollArea::viewport,#settingsContent,#messageContent{{background:transparent;border:0}}
 QScrollArea#chatScroll{{{('background:#FFFFFF;' + bevel_in) if t['bevel'] else 'background:transparent;border:0'}}}
 QLabel[role="assistant"]{{{asst}}}
 QLabel[role="user"]{{{user}}}
 QLabel[role="error"]{{background:{'#FCE8EA' if not t['dark'] else '#3A1D21'};color:{'#922A3B' if not t['dark'] else '#FFB4B7'};border-radius:{min(12, B + 2)}px;padding:12px}}
 #composer{{{composer}}}
 #composer[recording="true"]{{{composer_rec}}}
 #recordTime{{font-weight:600;color:{t['text']};font-size:{13 if key != 'terminal' else 18}px}}
 #liveText{{color:{t['muted']};font-size:{12 if key != 'terminal' else 16}px;font-style:{'italic' if key in ('witcher', 'tas') else 'normal'};padding:0 4px}}
 QLineEdit{{background:{t['field'] if t['field'] != 'transparent' else _rgba('#FFFFFF', 18)};border:1px solid {t['field_border'] or t['line']};padding:10px;border-radius:{0 if t['bevel'] or key == 'terminal' else min(12, R)}px;selection-background-color:{t['accent']};selection-color:{t['on_accent']};{bevel_in if t['bevel'] else ''}}}
 #messageInput{{background:transparent;border:0;padding:10px 4px;min-height:22px}}
 #searchInput{{background:{t['soft']};border:0;border-radius:{0 if t['bevel'] else 12}px;padding:10px 12px}}
 QDialog{{background:{dialog_bg}}} #settingsPage,#activityPage{{background:{dialog_bg}}}
 {yaprak_qss}
 #segmented{{background:{_rgba('#8A6A3E', 16) if key == 'witcher' else (t['line'] if not t['dark'] else t['soft'])};border-radius:{0 if t['bevel'] else 12}px;{bevel_in if t['bevel'] else ''}}}
 QPushButton#segButton{{background:transparent;border:0;border-radius:{0 if t['bevel'] else 9}px;padding:6px 8px;min-height:18px;color:{t['text'] if key == 'witcher' or t['bevel'] else t['muted']};font-weight:600}}
 QPushButton#segButton:checked{{background:{t['field'] if t['field'] != 'transparent' else t['page']};color:{t['text']};{bevel_out if t['bevel'] else ''}}}
 #themeChoice{{background:{t['field'] if t['field'] != 'transparent' else _rgba('#FFFFFF', 20)};border:1px solid {t['line']};padding:7px;min-height:60px;font-size:12px}}
 #themeChoice:checked{{border:2px solid {t['accent']}}}
 QGroupBox{{{group}}}
 #card{{{group.replace('margin-top:20px;padding:18px 12px 12px', 'margin-top:0')}}}
 #card QLabel{{background:transparent}}
 #cardTitle{{font-family:'{title_font}';font-weight:{400 if key in ('witcher', 'terminal') else 700};font-size:{t['size'] + (3 if key in ('witcher', 'terminal') else 1)}px;color:{t['text']}}}
 QPushButton#actionTile{{text-align:left;padding:8px 10px;font-weight:600}}
 QPushButton#roomToggle{{background:transparent;border:0;font-weight:700;text-align:left;padding:6px 4px}}
 QTabBar::tab:selected{{background:{t['accent']};color:{t['on_accent']};border-radius:{0 if t['bevel'] else 8}px}}
 QTabBar::tab{{margin-right:4px;border-radius:{0 if t['bevel'] else 8}px}}
 QPushButton#linkButton{{background:transparent;border:0;color:{t['accent'] if not t['dark'] else t['rail_on_text']};font-weight:600;padding:4px;text-align:left}}
 QGroupBox::title{{subcontrol-origin:margin;left:12px;font-weight:600}}
 QComboBox{{background:{t['field'] if t['field'] != 'transparent' else _rgba('#FFFFFF', 18)};border:1px solid {t['field_border'] or t['line']};border-radius:{0 if t['bevel'] or key == 'terminal' else 11}px;padding:9px 30px 9px 10px;min-height:22px;{bevel_in if t['bevel'] else ''}}}
 QComboBox::drop-down{{subcontrol-origin:padding;subcontrol-position:top right;width:28px;border:0}}
 QComboBox::down-arrow{{image:url({arrow});width:12px;height:8px;margin-right:7px}}
 QComboBox QAbstractItemView{{background:{t['page'] if key != 'witcher' else '#E9DDBF'};color:{t['text']};selection-background-color:{t['rail_on_bg']};selection-color:{t['rail_on_text']};padding:5px}}
 QCheckBox{{spacing:10px;min-height:34px}}
 QCheckBox::indicator{{width:{20 if t['bevel'] or key == 'terminal' else 42}px;height:{20 if t['bevel'] or key == 'terminal' else 25}px}}
 QCheckBox::indicator:checked{{image:url({sw_on})}} QCheckBox::indicator:unchecked{{image:url({sw_off})}}
 #chatList{{background:transparent;border:0;outline:0;padding:0}}
 #chatList::item{{border:0;padding:0;margin:1px 0;border-radius:{0 if t['bevel'] else 14}px}}
 #chatList::item:selected{{background:{t['field'] if t['field'] != 'transparent' and not t['dark'] else t['soft']}}}
 #chatList::item:hover{{background:{_rgba(t['accent'], 7)}}}
 #historyGroup{{color:{t['muted']};font-size:12px;font-weight:600;padding:12px 10px 4px}}
 #historyTitle{{font-weight:700;font-size:{14 if key != 'terminal' else 18}px;color:{t['text']}}}
 #historySnippet,#historyTime{{color:{t['muted']};font-size:{12 if key != 'terminal' else 16}px}}
 #historyAvatar{{background:{t['rail_on_bg']};color:{t['rail_on_text']};border-radius:{0 if t['bevel'] or key == 'terminal' else 15}px;font-weight:700;font-size:12px}}
 QTabWidget::pane{{border:0}} QTabBar::tab{{padding:9px;background:transparent;color:{t['muted']}}}
 QTabBar::tab:selected{{background:{t['rail_on_bg']};color:{t['rail_on_text']}}}
 QScrollBar:vertical{{background:transparent;width:6px;margin:2px}}
 QScrollBar::handle:vertical{{background:{_rgba(t['muted'], 40)};border-radius:3px;min-height:30px}}
 QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0}}
 QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{{background:transparent}}
 QMenu{{background:{t['page'] if key != 'witcher' else '#E9DDBF'};border:1px solid {t['line']};border-radius:{0 if t['bevel'] else 10}px;padding:6px}}
 QMenu::item{{padding:9px 18px;border-radius:6px}} QMenu::item:selected{{background:{t['rail_on_bg']};color:{t['rail_on_text']}}}
 QSlider::groove:horizontal{{height:4px;background:{t['line']};border-radius:2px}}
 QSlider::sub-page:horizontal{{background:{t['accent']};border-radius:2px}}
 QSlider::handle:horizontal{{width:16px;margin:-7px 0;background:{t['field'] if t['field'] != 'transparent' else t['page']};border:2px solid {t['accent']};border-radius:{0 if t['bevel'] else 10}px}}
 """


# ---------------------------------------------------------------- arka plan süsleri
class Dekor:
    """Panelin arkasına tema süsü çizer (olay süzgeci, QSS'te #panel saydam). Witcher'da karakter görselleri:
    boş sayfa → kalemle çizgi (yukarıdan aşağı) → gölge boyanır → bekler → silinir → sıradaki görsel."""
    DONGU = 30.0  # 13 Kasım (kullanıcı): görsel başına 30 s; çizim ~4 s, renk 3 s'de belirir, silinerek 3 s'de gider

    def __init__(self, panel, gorseller=lambda: [], zemin=None):
        from PySide6.QtCore import QObject, QEvent, QTimer
        self.panel = panel; self.theme = 'inci'; self.gorseller = gorseller; self._onbellek = {}; self._doku = None
        self.baslangic = time.perf_counter(); self._sira = 0; self._liste = []
        dekor = self

        class _Suzgec(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Paint:
                    dekor.ciz(obj)
                return False
        self.zemin = zemin
        self._suzgec = _Suzgec(panel); panel.installEventFilter(self._suzgec)
        if zemin is not None: zemin.installEventFilter(self._suzgec)  # Witcher: yaprak tüm sayfaların arkasında sabit
        self.timer = QTimer(panel); self.timer.timeout.connect(self._tik)

    def tema_ayarla(self, theme):
        self.theme = anahtar(theme); self._liste = []
        if self.theme == 'witcher':
            self.baslangic = time.perf_counter(); self._sira = 0; self.timer.start(60)
        else:
            self.timer.stop()
        self.panel.update()
        if self.zemin is not None:
            if self.zemin.layout() is not None:
                self.zemin.layout().setContentsMargins(*((16, 16, 18, 16) if self.theme == 'witcher' else (0, 0, 0, 0)))
            self.zemin.update()

    def gorselleri_yenile(self):
        self._liste = []; self.panel.update()

    def _tik(self):
        if self.panel.isVisible():
            self.panel.update()

    # -- yardımcılar
    def _parsomen_dokusu(self, boyut=None):
        """Parşömen (12 Kasım 23:50, kullanıcı: "gerçek parşömen deseni"): assets/doku/parsomen.jpg — fildişi zemin, yumuşak
        lekelenme, kısmi kahve halkası, küf benekleri, ince lifler, düzensiz eskimiş kenar. Döşenmez, panele gerilir;
        ölçeklenmiş hali boyut başına önbellekte (her karede yeniden ölçeklenmez). Üretici: work/araclar/parsomen_uret.py"""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPixmap
        if self._doku is None:
            from pathlib import Path
            yol = ROOT / 'assets' / 'doku' / 'parsomen_yaprak.png'  # tırtıklı kenar + gölge, RGBA
            img = QImage(str(yol))
            self._doku = img if not img.isNull() else False
            self._doku_olcekli = (None, None)
        if not self._doku or boyut is None:
            return None
        if self._doku_olcekli[0] != boyut:
            self._doku_olcekli = (boyut, QPixmap.fromImage(self._doku.scaled(boyut, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        return self._doku_olcekli[1]

    def _witcher_gorsel(self, yol):
        """(gölge görseli, çizgi görseli) QImage; çizgi hâli dodge yöntemiyle, kenarlar oval maskeyle yumuşak."""
        anahtar_ = str(yol)
        if anahtar_ in self._onbellek:
            return self._onbellek[anahtar_]
        while len(self._onbellek) >= 2:  # bellek: yalnız son iki görselin işlenmiş hali tutulur
            self._onbellek.pop(next(iter(self._onbellek)))
        try:
            import numpy as np
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
            kaynak = QImage(str(yol))
            if kaynak.isNull():
                raise ValueError('görsel okunamadı')
            kaynak = kaynak.scaled(760, 760, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            gri = kaynak.convertToFormat(QImage.Format.Format_Grayscale8)
            w, h = gri.width(), gri.height(); bpl = gri.bytesPerLine()
            g = np.frombuffer(gri.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, :w].astype('float32')
            def bulanik(a, r):
                # üç kez kutu bulanıklığı ≈ Gauss (PIL gerekmez)
                for _ in range(3):
                    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), mode='edge'), axis=1); a = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
                    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), mode='edge'), axis=0); a = (c[2 * r + 1:, :] - c[:-2 * r - 1, :]) / (2 * r + 1)
                return a
            blur = bulanik(255 - g, 4)
            dodge = np.clip(g * 255 / np.maximum(1, 255 - blur), 0, 255)
            yy, xx = np.mgrid[0:h, 0:w]
            maske = np.clip(1.6 - np.sqrt(((xx - w * .5) / (w * .55)) ** 2 + ((yy - h * .42) / (h * .55)) ** 2) * 1.6, 0, 1)
            cizgi = np.clip((255 - dodge - 18) * 2.2, 0, 255) * maske
            golge = np.clip(255 - g, 0, 255) * .9 * maske
            def rgba(alfa, renk):
                out = np.zeros((h, w, 4), dtype='uint8'); out[..., 0], out[..., 1], out[..., 2] = renk; out[..., 3] = alfa.astype('uint8')
                return QImage(out.tobytes(), w, h, QImage.Format.Format_RGBA8888).copy()
            renk = None
            from pathlib import Path as _P
            rk = _P(str(yol)).with_name(_P(str(yol)).stem + '_renk.png')
            if rk.exists():  # suluboya renk katmanı (pastel, kenarı yumuşak; çarpma kipiyle parşömene)
                ri = QImage(str(rk))
                if not ri.isNull():
                    renk = ri.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            # içerik sınırı (yatay): beyaz zeminde tek figürse sağa yaslanırken kesilmesin diye
            sut = (cizgi > 40).sum(0); dolu = np.where(sut > h * .01)[0]
            self._icerik = getattr(self, '_icerik', {}); self._icerik[anahtar_] = (dolu[0] / w, (dolu[-1] + 1) / w) if len(dolu) else (0., 1.)
            sonuc = (rgba(golge, (74, 52, 32)), rgba(cizgi, (43, 33, 24)), renk)
        except Exception:
            sonuc = None
        self._onbellek[anahtar_] = sonuc
        return sonuc

    # -- çizim
    def ciz(self, w):
        if self.theme == 'witcher':
            if self.zemin is not None and w is self.zemin:
                self._yaprak(w)
            elif self.zemin is None or w is not self.panel or True:
                self._witcher(w, yaprak=self.zemin is None)
        elif self.theme == 'terminal':
            self._terminal(w)
        elif self.theme == 'sakura':
            self._sakura(w)

    def _yaprak_rect(self, w):
        from PySide6.QtCore import QRectF
        return QRectF(w.rect()).adjusted(0, 0, -2, -2)

    def _yaprak(self, w):
        """Parşömen yaprağı (tırtıklı kenar + gölge görselin içinde). Sayfa kayarken yaprak sabit kalır."""
        from PySide6.QtGui import QPainter
        p = QPainter(w); p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self._yaprak_rect(w); doku = self._parsomen_dokusu(r.size().toSize())
        if doku is not None:
            p.drawPixmap(r.topLeft(), doku)
        p.end()

    def _witcher(self, w, yaprak=True):
        from PySide6.QtCore import Qt, QRectF, QPointF
        from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush, QPainterPath
        if yaprak:
            self._yaprak(w)
        # 13 Kasım 01:30 (kullanıcı: tırtığın yanında boydan boya düz çizgi): görsel + okunurluk geçişi düz dikdörtgene
        # kırpılıyordu. Artık ayrı katmana çizilip parşömen yaprağının kendi şekliyle (alfa) maskeleniyor.
        from PySide6.QtGui import QImage
        katman = QImage(w.size(), QImage.Format.Format_ARGB32_Premultiplied); katman.fill(0)
        p = QPainter(katman); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(w.rect()).adjusted(16, 14, -18, -18) if yaprak else QRectF(w.rect())
        # karakter görselleri
        if not self._liste:
            self._liste = [y for y in self.gorseller() if y and not str(y).endswith('_renk.png')]
        if self._liste:
            t = (time.perf_counter() - self.baslangic)
            sira = int(t // self.DONGU) % len(self._liste); f = (t % self.DONGU) / self.DONGU
            gorsel = self._witcher_gorsel(self._liste[sira])
            renkli_katman = None
            if gorsel:
                golge, cizgi, renk = gorsel
                # 13 Kasım (kullanıcı: obje kırpılmış): görsel panelin İÇİNE tam sığar, sağa yaslı, dikeyde ortalı
                oran = cizgi.width() / max(1, cizgi.height())
                if renk is None:  # çizim: büyük, sağa yaslı (kullanıcı 01:56: "şu anki Ciri kalsın")
                    yuk = r.height() * .92; gen = yuk * oran
                    x0, x1 = getattr(self, '_icerik', {}).get(str(self._liste[sira]), (0., 1.))
                    # havuzdaki yerlesim.json {"dosya.jpg": "eski"} → eski yerleşim (sağdan taşar); kullanıcı: Ciri böyle kalsın
                    from pathlib import Path as _P
                    yj = _P(str(self._liste[sira])).with_name('yerlesim.json')
                    try:
                        import json as _j; eski = _j.loads(yj.read_text(encoding='utf-8')).get(_P(str(self._liste[sira])).name) == 'eski'
                    except (OSError, ValueError):
                        eski = False
                    if not eski:  # figürün sağ kenarı panel içinde (kesilmez)
                        hedef = QRectF(r.right() - 10 - gen * x1, r.top() + 10, gen, yuk)
                    else:              # kareyi dolduran görsel (Ciri): eski yerleşim
                        hedef = QRectF(r.right() - gen * .66, r.top() + 10, gen, yuk)
                else:
                    yuk = r.height() * .9; gen = yuk * oran
                    if gen > r.width() * .94: gen = r.width() * .94; yuk = gen / oran
                    hedef = QRectF(r.right() - gen - 6, r.top() + (r.height() - yuk) / 2, gen, yuk)
                def ara(a, b, x): return max(0., min(1., (x - a) / (b - a)))
                # zaman çizelgesi (DONGU oranı): çizim .02-.15, renk/gölge .12-.22, silinme .88-.98 (≈3 s), sonra kısa boşluk
                ciz = ara(.02, .15, f); dolgu = ara(.12, .22, f); sil = ara(.88, .98, f)
                if len(self._liste) == 1 and t >= self.DONGU * .22:
                    # tek görsel (şu an yalnız Ciri): bir kez çizilir, sonra sabit kalır (silinip yeniden çizilmez)
                    ciz = dolgu = 1.0; sil = 0.0
                if ciz > 0 and sil < 1:
                    from PySide6.QtGui import QLinearGradient
                    bant = hedef.height() * .22
                    def silgi(img):
                        """Silinme: yukarıdan aşağı yumuşak kenarlı silgi geçer (geçtiği yer kaybolur)."""
                        if sil <= 0: return
                        q = QPainter(img); q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                        y0 = hedef.top() - bant + (hedef.height() + bant) * sil
                        g = QLinearGradient(0, y0, 0, y0 + bant); g.setColorAt(0, QColor(0, 0, 0, 0)); g.setColorAt(1, QColor(0, 0, 0, 255))
                        q.fillRect(QRectF(0, 0, img.width(), img.height()), QBrush(g)); q.end()
                    def bos():
                        im = QImage(w.size(), QImage.Format.Format_ARGB32_Premultiplied); im.fill(0); return im
                    # çizgi: kalem yukarıdan aşağı ilerler, ön kenarı yumuşak
                    cz = bos(); q = QPainter(cz); q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                    if renk is not None:  # suluboya resim: çizgisiz, yukarıdan aşağı boyanarak belirir
                        q.setOpacity(.92); q.drawImage(hedef, renk)
                    else:
                        q.setOpacity(.6); q.drawImage(hedef, cizgi)
                    if ciz < 1:
                        q.setOpacity(1); q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                        y1 = hedef.top() - bant + (hedef.height() + bant) * ciz
                        g = QLinearGradient(0, y1, 0, y1 + bant); g.setColorAt(0, QColor(0, 0, 0, 255)); g.setColorAt(1, QColor(0, 0, 0, 0))
                        q.fillRect(QRectF(0, 0, cz.width(), cz.height()), QBrush(g))
                    q.end(); silgi(cz)
                    if dolgu > 0 and renk is None:
                        dk = bos(); q = QPainter(dk); q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                        if renk is not None:
                            q.setOpacity(.9 * dolgu); q.drawImage(hedef, renk)
                        else:
                            q.setOpacity(.26 * dolgu); q.drawImage(hedef, golge)
                        q.end(); silgi(dk)
                        if renk is not None:
                            renkli_katman = dk  # aşağıda çarpma kipiyle parşömene
                        else:
                            p.drawImage(0, 0, dk)
                    p.drawImage(0, 0, cz)
                # yazı tarafı okunaklı kalsın: soldan sağa parşömen rengine solma
                from PySide6.QtGui import QLinearGradient
                sol = QLinearGradient(r.left(), 0, r.left() + r.width() * .6, 0)
                sol.setColorAt(0, QColor(236, 223, 190, 150)); sol.setColorAt(1, QColor(236, 223, 190, 0)); p.fillRect(r, QBrush(sol))
        p.end()
        renkli_katman = locals().get('renkli_katman')
        for hedef_img in ([katman, renkli_katman] if renkli_katman is not None else [katman]):
            self._kenar_maskele(w, hedef_img, yaprak)
        pw = QPainter(w)
        if renkli_katman is not None:
            pw.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply); pw.drawImage(0, 0, renkli_katman)
            pw.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        pw.drawImage(0, 0, katman); pw.end()

    def _kenar_maskele(self, w, img, yaprak):
        """Panel kenarında yumuşak solma + parşömen yaprağının şekliyle (gölge hariç) maskeleme."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QColor, QBrush, QImage, QLinearGradient
        p = QPainter(img)
        p.setOpacity(1); p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        W_, H_ = float(w.width()), float(w.height()); k = 34.0
        for x1, y1, x2, y2, uz in ((0, 0, W_, 0, W_), (0, 0, 0, H_, H_)):
            g = QLinearGradient(x1, y1, x2, y2); e = min(.45, k / max(1., uz))
            g.setColorAt(0, QColor(0, 0, 0, 0)); g.setColorAt(e, QColor(0, 0, 0, 255)); g.setColorAt(1 - e, QColor(0, 0, 0, 255)); g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(0, 0, W_, H_), QBrush(g))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # yaprak şekliyle maskele (yalnız yaprağın opak kısmında görünsün; gölge ve tırtık dışı boş kalır)
        maske = None
        if self.zemin is not None and not yaprak:
            from PySide6.QtCore import QPoint
            maske = self._parsomen_dokusu(self._yaprak_rect(self.zemin).size().toSize())
            ofset = w.mapTo(self.zemin, QPoint(0, 0))
        elif yaprak:
            maske = self._parsomen_dokusu(self._yaprak_rect(w).size().toSize()); ofset = None
        if maske is not None:
            if not hasattr(self, '_sert_maske') or self._sert_maske[0] != maske.cacheKey():
                # gölgeyi maskeden çıkar: yalnız neredeyse opak pikseller (yaprağın kendisi) geçer
                m = maske.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                import numpy as np
                b = np.frombuffer(m.constBits(), dtype=np.uint8, count=m.bytesPerLine() * m.height()).reshape(m.height(), m.bytesPerLine() // 4, 4)[:, :m.width()]
                a = np.clip((b[..., 3].astype('float32') - 200) * (255 / 55), 0, 255).astype('uint8')
                out = np.zeros((m.height(), m.width(), 4), dtype='uint8'); out[..., 3] = a
                self._sert_maske = (maske.cacheKey(), QImage(out.tobytes(), m.width(), m.height(), QImage.Format.Format_RGBA8888).copy())
            p.setOpacity(1); p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            if ofset is not None:
                p.drawImage(-ofset.x(), -ofset.y(), self._sert_maske[1])
            else:
                p.drawImage(0, 0, self._sert_maske[1])
        p.end()

    def _terminal(self, w):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush
        p = QPainter(w); r = QRectF(w.rect())
        g = QRadialGradient(r.center(), max(r.width(), r.height()) * .7)
        g.setColorAt(0, QColor('#06260F')); g.setColorAt(1, QColor('#021208'))
        p.fillRect(r, QBrush(g))
        p.setPen(QColor(0, 0, 0, 70))
        y = 0
        while y < r.height():
            p.drawLine(0, int(y), int(r.width()), int(y)); y += 3
        p.end()

    def _sakura(self, w):
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainter, QColor, QPainterPath
        p = QPainter(w); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        def cicek(cx, cy, s, renk):
            p.setPen(QColor(0, 0, 0, 0)); p.setBrush(renk)
            for i in range(5):
                p.save(); p.translate(cx, cy); p.rotate(i * 72)
                p.drawEllipse(QRectF(-s * .25, -s * .95, s * .5, s * .9)); p.restore()
        cicek(16, w.height() - 90, 40, QColor(255, 211, 224, 122))
        cicek(w.width() - 30, 40, 22, QColor(251, 220, 230, 170))
        p.end()
