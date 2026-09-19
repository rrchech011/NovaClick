"""
NovaClick - Advanced Auto Clicker / Gelişmiş Otomatik Tıklayıcı
================================================================
Claude (Anthropic) ile birlikte geliştirilmiştir. / Built together with Claude (Anthropic).
License: MIT

Requirements:  pip install customtkinter pynput pystray Pillow
               (pystray + Pillow are optional: only needed for the system-tray feature)

Highlights
- Millisecond precision, random jitter, click hold time (important for games)
- 4 click methods: Cursor / Fixed point / Window (game mode) / Background
- Window mode: clicks a spot inside a chosen window, pauses when you leave it,
  optional "bring to front" flash mode
- Point sequences + macro recorder (F7)
- Global hotkey (F6), toggle or hold, start delay, time limit, failsafe corner
- Live stats + CPS graph, profiles, 5 accent colors, Turkish / English UI
"""

import collections
import json
import math
import os
import queue
import random
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import customtkinter as ctk
from pynput import keyboard, mouse

try:  # sistem tepsisi (opsiyonel)
    import pystray
    from PIL import Image

    HAS_TRAY = True
except Exception:  # pragma: no cover
    HAS_TRAY = False

try:
    from customtkinter import CTkCanvas as _Canvas
except ImportError:  # pragma: no cover
    from tkinter import Canvas as _Canvas

IS_WIN = sys.platform == "win32"

# --------------------------------------------------------------------------
# Windows: yüksek DPI + 1 ms zamanlayıcı çözünürlüğü (hızlı tıklama için şart)
# --------------------------------------------------------------------------
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32 = ctypes.windll.advapi32
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p

    WM_MOUSEMOVE = 0x0200
    # kod -> (basma, bırakma, çift tık, MK_ bayrağı)
    BG_MESSAGES = {
        "left": (0x0201, 0x0202, 0x0203, 0x0001),
        "right": (0x0204, 0x0205, 0x0206, 0x0002),
        "middle": (0x0207, 0x0208, 0x0209, 0x0010),
    }

    def _window_title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def window_from_screen_point(x, y):
        """Ekran noktasındaki pencere: (hwnd, client_x, client_y, başlık, üst_pencere)."""
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return None
        pt = wintypes.POINT(int(x), int(y))
        user32.ScreenToClient(hwnd, ctypes.byref(pt))
        top = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
        return int(hwnd), pt.x, pt.y, _window_title(top), int(top)

    def screen_to_client(hwnd, x, y):
        pt = wintypes.POINT(int(x), int(y))
        user32.ScreenToClient(hwnd, ctypes.byref(pt))
        return pt.x, pt.y

    def client_to_screen(hwnd, x, y):
        pt = wintypes.POINT(int(x), int(y))
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return pt.x, pt.y

    def window_exists(hwnd):
        return bool(user32.IsWindow(hwnd))

    def is_foreground(top):
        fg = user32.GetForegroundWindow()
        return bool(fg) and int(fg) == int(top)

    def force_foreground(hwnd):
        """Pencereyi öne getirir (Windows'un odak kilidini AttachThreadInput ile aşar)."""
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            fg = user32.GetForegroundWindow()
            if fg and int(fg) == int(hwnd):
                return True
            cur = kernel32.GetCurrentThreadId()
            fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            attached = False
            if fg_tid and fg_tid != cur:
                attached = bool(user32.AttachThreadInput(cur, fg_tid, True))
            user32.BringWindowToTop(hwnd)
            ok = user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(cur, fg_tid, False)
            return bool(ok)
        except Exception:
            return False

    def is_admin():
        try:
            return bool(shell32.IsUserAnAdmin())
        except Exception:
            return False

    def window_elevated(hwnd):
        """Pencerenin süreci yönetici olarak mı çalışıyor? True / False / bilinmiyorsa None."""
        proc = tok = None
        try:
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not proc:
                return True if ctypes.GetLastError() == 5 else None  # erişim reddedildi -> büyük olasılıkla yönetici
            tok = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(proc, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
                return True if ctypes.GetLastError() == 5 else None
            elev = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            if not advapi32.GetTokenInformation(tok, 20, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(size)):
                return None  # TokenElevation = 20
            return bool(elev.value)
        except Exception:
            return None
        finally:
            for h in (tok, proc):
                try:
                    if h:
                        kernel32.CloseHandle(h)
                except Exception:
                    pass

    def relaunch_as_admin():
        """Programı yönetici olarak yeniden başlatır (UAC onayı ister)."""
        try:
            if getattr(sys, "frozen", False):
                exe, params = sys.executable, None
            else:
                exe, params = sys.executable, f'"{os.path.abspath(sys.argv[0])}"'
            return int(shell32.ShellExecuteW(None, "runas", exe, params, None, 1) or 0) > 32
        except Exception:
            return False

    def send_background_click(hwnd, cpos, code, count, hold=0.0, stop=None, spoof=False, top=None):
        """Fareyi/odağı hiç kullanmadan pencereye tıklama mesajı gönderir."""
        down, up, dbl, mk = BG_MESSAGES[code]
        lparam = ((cpos[1] & 0xFFFF) << 16) | (cpos[0] & 0xFFFF)
        if spoof:  # 'pencere aktif' taklidi (deneysel)
            t = top or hwnd
            user32.PostMessageW(t, 0x001C, 1, 0)  # WM_ACTIVATEAPP
            user32.PostMessageW(t, 0x0086, 1, 0)  # WM_NCACTIVATE
            user32.PostMessageW(t, 0x0006, 1, 0)  # WM_ACTIVATE (WA_ACTIVE)
            user32.PostMessageW(hwnd, 0x0007, 0, 0)  # WM_SETFOCUS
            user32.PostMessageW(hwnd, 0x0021, int(t), ((down & 0xFFFF) << 16) | 1)  # WM_MOUSEACTIVATE
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        for i in range(count):
            user32.PostMessageW(hwnd, dbl if i == 1 else down, mk, lparam)
            if hold > 0:
                if stop is not None:
                    stop.wait(hold)
                else:
                    time.sleep(hold)
            user32.PostMessageW(hwnd, up, 0, lparam)


LOG_PATH = Path.home() / ".novaclick.log"


def log_error(text):
    """Hataları ~/.novaclick.log dosyasına yazar (arayüz çökmesin, izi kalsın)."""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 200_000:
            LOG_PATH.unlink()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


if not IS_WIN:

    def is_admin():
        return False

    def window_elevated(hwnd):
        return None

    def relaunch_as_admin():
        return False


def resource_path(name):
    """Hem .py olarak hem PyInstaller exe'si olarak dosyayı bulur."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return str(Path(base) / name)


def detect_language():
    """Sistem diline göre varsayılan dil: Türkçe ise 'tr', değilse 'en'."""
    try:
        if IS_WIN:
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "tr" if lid == 0x1F else "en"
    except Exception:
        pass
    lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    return "tr" if lang.startswith("tr") else "en"


APP_NAME = "NovaClick"
APP_VERSION = "1.1.0"
REPO_URL = "https://github.com/rrchech011/NovaClick"
CONFIG_PATH = Path.home() / ".novaclick.json"
REC_HOTKEY = "f7"
MAX_POINTS = 100
HIST = 60  # CPS grafiğinde tutulan örnek sayısı

# --------------------------------------------------------------------------
# Tasarım sabitleri
# --------------------------------------------------------------------------
BG = "#080b14"
SIDEBAR = "#0c1120"
CARD = "#111827"
CARD_ALT = "#1a2234"
BORDER = "#222c42"
TEXT = "#e6eaf5"
MUTED = "#7f8aa6"
OK = "#22c55e"
WARN = "#f59e0b"
DANGER = "#ef4444"
DANGER_H = "#dc2626"
REC = "#f43f5e"

ACCENTS = {
    "blue": ("#3b82f6", "#2563eb"),
    "purple": ("#8b5cf6", "#7c3aed"),
    "green": ("#10b981", "#059669"),
    "orange": ("#f97316", "#ea580c"),
    "pink": ("#ec4899", "#db2777"),
}

PAGES = ["home", "target", "sequence", "game", "settings", "about"]
PAGE_ICONS = {
    "home": "⚡",
    "target": "🎯",
    "sequence": "📋",
    "game": "🎮",
    "settings": "⚙",
    "about": "ℹ",
}

DEFAULTS = {
    "lang": "",
    "hours": "0",
    "minutes": "0",
    "seconds": "0",
    "millis": "100",
    "jitter": 0,
    "hold": "10",
    "button": "left",
    "click_type": "single",
    "repeat_mode": "infinite",
    "repeat_count": "100",
    "time_limit": "0",
    "position_mode": "cursor",
    "x": "0",
    "y": "0",
    "pos_jitter": "0",
    "on_inactive": "pause",
    "spoof": False,
    "use_points": False,
    "points": [],
    "start_delay": "0",
    "failsafe": True,
    "topmost": False,
    "tray": False,
    "hotkey": "f6",
    "hotkey_mode": "toggle",
    "accent": "blue",
}

# Eski (v1.0) sürümün Türkçe etiketli ayar dosyalarını yeni kodlara çevirir
LEGACY = {
    "button": {"Sol": "left", "Sağ": "right", "Orta": "middle"},
    "click_type": {"Tek": "single", "Çift": "double", "Üçlü": "triple"},
    "repeat_mode": {"Sonsuz": "infinite", "Sayı": "count"},
    "position_mode": {"İmleç": "cursor", "Sabit": "fixed", "Arka plan": "background"},
    "hotkey_mode": {"Aç/Kapa": "toggle", "Basılı Tut": "hold"},
    "accent": {"Mavi": "blue", "Mor": "purple", "Yeşil": "green", "Turuncu": "orange", "Pembe": "pink"},
}
VALID = {
    "button": ("left", "right", "middle"),
    "click_type": ("single", "double", "triple"),
    "repeat_mode": ("infinite", "count"),
    "position_mode": ("cursor", "fixed", "window", "background"),
    "on_inactive": ("pause", "focus"),
    "hotkey_mode": ("toggle", "hold"),
    "accent": tuple(ACCENTS.keys()),
    "lang": ("", "tr", "en"),
}

BUTTONS = {
    "left": mouse.Button.left,
    "right": mouse.Button.right,
    "middle": mouse.Button.middle,
}
BTN_CODE = {mouse.Button.left: "left", mouse.Button.right: "right", mouse.Button.middle: "middle"}
COUNTS = {"single": 1, "double": 2, "triple": 3}

# Oyun ön ayarları: aralık (ms), basılı tutma (ms), sapma (±ms), konum sapması (px), yöntem
PRESETS = {
    "sim": dict(ms=60, hold=15, jitter=10, pj=2, mode="window"),
    "fast": dict(ms=34, hold=12, jitter=0, pj=0, mode="window"),
    "safe": dict(ms=120, hold=30, jitter=40, pj=3, mode="window"),
    "turbo": dict(ms=10, hold=5, jitter=0, pj=0, mode="fixed"),
}


def blend(c1, c2, t):
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def key_to_str(key):
    """pynput tuşunu karşılaştırılabilir bir metne çevirir."""
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char.lower()
        if key.vk is not None:
            return f"vk{key.vk}"
    return str(key)


# --------------------------------------------------------------------------
# Çeviriler / Translations
# --------------------------------------------------------------------------
STR = {
    "tr": {
        "app.sub": "Gelişmiş otomatik tıklayıcı",
        "nav.home": "Tıklama",
        "nav.target": "Hedef",
        "nav.sequence": "Dizi & Makro",
        "nav.game": "Oyun",
        "nav.settings": "Ayarlar",
        "nav.about": "Hakkında",
        # Sayfa başlıkları
        "page.home.title": "Tıklama",
        "page.home.sub": "Ne kadar hızlı ve nasıl tıklanacağını belirle",
        "page.target.title": "Hedef",
        "page.target.sub": "Nereye ve hangi yöntemle tıklanacağını seç",
        "page.sequence.title": "Dizi & Makro",
        "page.sequence.sub": "Birden fazla noktaya sırayla tıkla ya da hareketlerini kaydet",
        "page.game.title": "Oyun",
        "page.game.sub": "Oyunlar için hazır ayarlar ve ipuçları",
        "page.settings.title": "Ayarlar",
        "page.settings.sub": "Dil, görünüm ve davranış",
        "page.about.title": "Hakkında",
        "page.about.sub": "NovaClick hakkında",
        # Tıklama sayfası
        "card.interval": "Tıklama aralığı",
        "card.interval.sub": "İki tıklama arasındaki süre (toplamı alınır)",
        "unit.hours": "Saat",
        "unit.minutes": "Dakika",
        "unit.seconds": "Saniye",
        "unit.millis": "Milisaniye",
        "interval.quick": "Hızlı ayar:",
        "interval.jitter": "Rastgele sapma",
        "jitter.off": "Kapalı",
        "jitter.val": "± {v} ms",
        "card.click": "Tıklama ayarları",
        "opt.button": "Fare tuşu",
        "btn.left": "Sol",
        "btn.right": "Sağ",
        "btn.middle": "Orta",
        "opt.type": "Tıklama türü",
        "ctype.single": "Tek",
        "ctype.double": "Çift",
        "ctype.triple": "Üçlü",
        "opt.hold": "Basılı tutma (ms)",
        "hold.hint": "Oyunlar için 10–30 önerilir",
        "opt.repeat": "Tekrar",
        "rep.infinite": "Sonsuz",
        "rep.count": "Sayı",
        "opt.timelimit": "Süre sınırı (dk)",
        "timelimit.hint": "0 = sınırsız",
        # Hedef sayfası
        "card.mode": "Tıklama yöntemi",
        "mode.cursor": "İmleç",
        "mode.fixed": "Sabit",
        "mode.window": "Pencere",
        "mode.background": "Arka plan",
        "mode.desc.cursor": "İmlecin o an bulunduğu yere tıklar. En basit yöntem.",
        "mode.desc.fixed": "Ekranda seçtiğin sabit koordinata tıklar. Fare her tıklamada oraya gider, bu yüzden bilgisayarı aynı anda kullanamazsın.",
        "mode.desc.window": "Oyunlar için önerilir. Seçtiğin pencerenin belirli bir noktasına gerçek fare girdisiyle tıklar; pencereyi taşısan bile nokta pencereyle birlikte gider. Pencere aktif değilken duraklar (ya da öne getirir).",
        "mode.desc.background": "Fareyi hiç kullanmadan pencereye tıklama mesajı gönderir; bilgisayarı serbestçe kullanabilirsin. Tarayıcı ve klasik programlarda çalışır, çoğu oyun bu mesajları yok sayar.",
        "card.point": "Konum",
        "target.pick_pos": "🎯  Ekrandan seç",
        "target.pick_win": "🖥  Pencere seç",
        "target.picking": "Ekrana tıkla…",
        "target.none": "Hedef pencere seçilmedi",
        "target.win": "Hedef: {title}",
        "opt.posjitter": "Konum sapması (px)",
        "opt.inactive": "Pencere aktif değilken",
        "inact.pause": "Duraklat",
        "inact.focus": "Öne getir",
        # Dizi sayfası
        "card.seq": "Nokta dizisi",
        "seq.use": "Nokta dizisini kullan",
        "seq.desc": "Noktalara sırayla tıklanır ve başa dönülür. Her noktanın kendi bekleme süresi olabilir; boş bırakırsan genel aralık kullanılır. Noktalar Hedef sayfasındaki yönteme göre yorumlanır (Sabit: ekran, Pencere/Arka plan: pencere koordinatı).",
        "seq.add": "＋  Nokta ekle",
        "seq.record": "●  Makro kaydet (F7)",
        "seq.stop": "■  Kaydı durdur (F7)",
        "seq.clear": "Temizle",
        "seq.empty": "Henüz nokta yok. “Nokta ekle” ile ya da makro kaydederek başla.",
        "seq.wait": "Bekleme (ms)",
        "seq.auto": "otomatik",
        # Oyun sayfası
        "card.presets": "Hazır ayarlar",
        "preset.sim.title": "🖱  Tıklama simülatörü",
        "preset.sim.desc": "~16 CPS, 15 ms basılı tutma, hafif sapma · Pencere yöntemi",
        "preset.fast.title": "⚡  Hızlı",
        "preset.fast.desc": "~30 CPS, sapmasız · Pencere yöntemi",
        "preset.safe.title": "🎭  İnsan gibi",
        "preset.safe.desc": "~8 CPS, belirgin sapma, konum sapması · Pencere yöntemi",
        "preset.turbo.title": "🚀  Turbo",
        "preset.turbo.desc": "100 CPS · Sabit nokta (oyun dışı uygulamalar için)",
        "card.tips": "Oyun ipuçları",
        "tips.1": "•  Oyunlar tıklamayı genelde tek karede yakalamaya çalışır. “Basılı tutma” süresini 10–30 ms yapmak kaçırılan tıklamaları azaltır.",
        "tips.2": "•  Oyun için “Pencere” yöntemini kullan. Oyun penceresi aktif değilse NovaClick duraklar, yanlış pencereye tıklamaz.",
        "tips.3": "•  “Arka plan” yöntemi çoğu oyunda çalışmaz: oyun bu mesajları yok sayar. Bu bir hata değil, oyunların çalışma şekli.",
        "tips.4": "•  “Öne getir” seçeneği pencere aktif değilken oyunu bir an öne alıp tıklar ve geri döner. Deneysel; her tıklamada kısa bir titreme olur, yavaş aralıklarda kullan.",
        "tips.5": "•  Bazı oyunlar otomatik tıklamayı yasaklar. Oyunun kurallarını kontrol et; risk sana aittir.",
        # Ayarlar
        "card.lang": "Dil",
        "lang.tr": "Türkçe",
        "lang.en": "English",
        "card.look": "Görünüm",
        "opt.accent": "Vurgu rengi",
        "opt.topmost": "Her zaman üstte",
        "card.behavior": "Davranış",
        "opt.delay": "Başlangıç gecikmesi (sn)",
        "opt.failsafe": "Acil durdurma (fareyi sol üst köşeye götür)",
        "opt.tray": "Kapatınca sistem tepsisine küçült",
        "card.profiles": "Profiller",
        "profile.none": "Profil yok",
        "profile.load": "Yükle",
        "profile.delete": "Sil",
        "profile.save": "Kaydet",
        "profile.placeholder": "Yeni profil adı",
        # Hakkında
        "about.made": "Claude (Anthropic) ile birlikte geliştirilmiştir.",
        "about.desc": "Modern arayüzlü, gelişmiş ve açık kaynaklı otomatik tıklayıcı.",
        "about.github": "GitHub'da aç",
        "about.releases": "Sürümler",
        "card.keys": "Kısayollar",
        "about.keys": "F6  →  Başlat / durdur (değiştirilebilir)\nF7  →  Makro kaydını başlat / durdur\nSol üst köşe  →  Acil durdurma (Arka plan yöntemi hariç)",
        "about.license": "MIT Lisansı · Sorumluluk kullanıcıya aittir. Otomatik tıklamayı yasaklayan servislerde kullanmak hesabının kapatılmasına yol açabilir.",
        # Dock
        "dock.start": "BAŞLAT",
        "dock.stop": "DURDUR",
        "dock.cancel": "İPTAL",
        "dock.hotkey": "Kısayol",
        "dock.change": "Değiştir",
        "dock.capturing": "Tuşa bas…",
        "dock.hkmode": "Kısayol modu",
        "hkmode.toggle": "Aç/Kapa",
        "hkmode.hold": "Basılı Tut",
        "stat.clicks": "Tıklama",
        "stat.cps": "CPS",
        "stat.time": "Süre",
        "state.idle": "●  HAZIR",
        "state.running": "●  ÇALIŞIYOR",
        "state.waiting": "●  BEKLİYOR",
        "state.paused": "●  DURAKLADI",
        "state.recording": "●  KAYITTA",
        # Tepsi
        "opt.spoof": "Odak taklidi (deneysel)",
        "spoof.hint": "Pencereye “aktifsin” mesajı da yollar; bazı programlarda arka plan tıklamasını mümkün kılabilir. Oyun fareni ya da imleci kilitlerse kapat.",
        "target.test": "Test (3 tık)",
        "target.guide": "Bilgisayarı kullanırken arkada tıklasın → Arka plan (tarayıcı, klasik programlar). Oyunda tıklasın → Pencere (oyun aktifken fare meşgul olur). Emin değilsen pencereyi seç ve Test'e bas.",
        "card.diag": "Tanılama",
        "diag.lastkey": "Son algılanan tuş: {key} ({ago} sn önce)",
        "diag.nokey": "Henüz tuş algılanmadı. F6'ya basınca burada görünmüyorsa, kısayol o pencerede alınmıyor demektir.",
        "diag.self_admin": "NovaClick: yönetici olarak çalışıyor",
        "diag.self_user": "NovaClick: normal kullanıcı olarak çalışıyor",
        "diag.target_admin": "Hedef program: yönetici olarak çalışıyor",
        "diag.target_user": "Hedef program: normal",
        "diag.target_unknown": "Hedef program: seçilmedi ya da bilinmiyor",
        "diag.relaunch": "Yönetici olarak yeniden başlat",
        "diag.log": "Hata kaydı: {path}",
        "dock.rec": "KAYIT",
        "hint.test": "Test: 3 tıklama gönderiliyor…",
        "hint.need_admin": "Hedef program yönetici olarak çalışıyor: NovaClick'i de yönetici olarak başlat (Ayarlar → Tanılama), yoksa kısayol ve tıklama çalışmaz.",
        "hint.internal_error": "Beklenmeyen bir hata oldu, kayda yazıldı: {path}",
        "hint.relaunch_failed": "Yeniden başlatılamadı ya da onay verilmedi.",
        "tray.show": "Göster",
        "tray.toggle": "Başlat / Durdur",
        "tray.quit": "Çık",
        # İpuçları / mesajlar
        "hint.min_interval": "Aralık en az 1 ms olabilir, 1 ms olarak ayarlandı.",
        "hint.need_target": "Önce “Pencere seç” ile hedef pencereyi seç (Hedef sayfası).",
        "hint.pick_pos": "Sabit konumu seçmek için ekranda istediğin yere tıkla.",
        "hint.pick_window": "Hedef pencereyi öne getir ve tıklanmasını istediğin noktaya tıkla (o tıklama pencerede gerçekten de yapılır).",
        "hint.pos_set": "Konum seçildi: X={x}, Y={y}",
        "hint.window_set": "Hedef pencere seçildi (X={x}, Y={y}).",
        "hint.own_window": "NovaClick penceresini seçtin. Hedef pencerede bir noktaya tıkla.",
        "hint.no_window": "Pencere algılanamadı, tekrar dene.",
        "hint.done": "Belirlenen tekrar sayısı tamamlandı.",
        "hint.time": "Süre sınırına ulaşıldı, durduruldu.",
        "hint.failsafe": "Acil durdurma: fare sol üst köşeye götürüldü.",
        "hint.window_closed": "Hedef pencere kapandı, tıklama durduruldu.",
        "hint.bg_on": "Arka plan modu açık: fareyi serbestçe kullanabilirsin. Durdurmak için {key}.",
        "hint.window_on": "Pencere modu: hedef pencere aktifken tıklar, sen başka pencereye geçince duraklar. Durdurmak için {key}.",
        "hint.hotkey_prompt": "Yeni kısayol olarak kullanmak istediğin tuşa bas.",
        "hint.hotkey_set": "Kısayol {key} olarak ayarlandı.",
        "hint.profile_name": "Profil için bir ad yaz.",
        "hint.profile_saved": "“{name}” profili kaydedildi.",
        "hint.profile_loaded": "“{name}” profili yüklendi.",
        "hint.profile_deleted": "“{name}” profili silindi.",
        "hint.rec_on": "Kayıt başladı: istediğin yerlere tıkla. Bitirmek için F7.",
        "hint.rec_off": "Kayıt bitti: {n} nokta.",
        "hint.add_point": "Eklemek istediğin noktaya ekranda tıkla.",
        "hint.point_added": "Nokta eklendi: X={x}, Y={y}",
        "hint.max_points": "En fazla {n} nokta eklenebilir.",
        "hint.win_only": "Pencere ve Arka plan yöntemleri şimdilik sadece Windows'ta çalışır.",
        "hint.preset": "Hazır ayar uygulandı.",
        "hint.preset_target": "Hazır ayar uygulandı. Şimdi oyun penceresini seç.",
        "hint.need_points": "Dizi açık ama hiç nokta yok. Nokta ekle ya da diziyi kapat.",
        "hint.tray": "NovaClick sistem tepsisinde çalışmaya devam ediyor.",
    },
    "en": {
        "app.sub": "Advanced auto clicker",
        "nav.home": "Clicking",
        "nav.target": "Target",
        "nav.sequence": "Sequence & Macro",
        "nav.game": "Game",
        "nav.settings": "Settings",
        "nav.about": "About",
        "page.home.title": "Clicking",
        "page.home.sub": "Set how fast and how to click",
        "page.target.title": "Target",
        "page.target.sub": "Choose where and by which method to click",
        "page.sequence.title": "Sequence & Macro",
        "page.sequence.sub": "Click several points in order or record your own moves",
        "page.game.title": "Game",
        "page.game.sub": "Ready-made settings and tips for games",
        "page.settings.title": "Settings",
        "page.settings.sub": "Language, look and behavior",
        "page.about.title": "About",
        "page.about.sub": "About NovaClick",
        "card.interval": "Click interval",
        "card.interval.sub": "Time between two clicks (values are added up)",
        "unit.hours": "Hours",
        "unit.minutes": "Minutes",
        "unit.seconds": "Seconds",
        "unit.millis": "Milliseconds",
        "interval.quick": "Quick set:",
        "interval.jitter": "Random jitter",
        "jitter.off": "Off",
        "jitter.val": "± {v} ms",
        "card.click": "Click options",
        "opt.button": "Mouse button",
        "btn.left": "Left",
        "btn.right": "Right",
        "btn.middle": "Middle",
        "opt.type": "Click type",
        "ctype.single": "Single",
        "ctype.double": "Double",
        "ctype.triple": "Triple",
        "opt.hold": "Hold time (ms)",
        "hold.hint": "10–30 recommended for games",
        "opt.repeat": "Repeat",
        "rep.infinite": "Endless",
        "rep.count": "Count",
        "opt.timelimit": "Time limit (min)",
        "timelimit.hint": "0 = unlimited",
        "card.mode": "Click method",
        "mode.cursor": "Cursor",
        "mode.fixed": "Fixed",
        "mode.window": "Window",
        "mode.background": "Background",
        "mode.desc.cursor": "Clicks wherever the cursor currently is. The simplest method.",
        "mode.desc.fixed": "Clicks a fixed screen coordinate. The mouse jumps there on every click, so you cannot use the computer at the same time.",
        "mode.desc.window": "Recommended for games. Clicks a spot inside the chosen window with real mouse input; the spot follows the window if you move it. Pauses (or brings the window to front) while the window is inactive.",
        "mode.desc.background": "Sends click messages to the window without touching your mouse, so you can keep using the PC. Works in browsers and classic apps; most games ignore these messages.",
        "card.point": "Position",
        "target.pick_pos": "🎯  Pick on screen",
        "target.pick_win": "🖥  Pick window",
        "target.picking": "Click on screen…",
        "target.none": "No target window selected",
        "target.win": "Target: {title}",
        "opt.posjitter": "Position jitter (px)",
        "opt.inactive": "When window is inactive",
        "inact.pause": "Pause",
        "inact.focus": "Bring to front",
        "card.seq": "Point sequence",
        "seq.use": "Use point sequence",
        "seq.desc": "Points are clicked in order, then it loops. Each point can have its own wait time; leave it empty to use the global interval. Points follow the method on the Target page (Fixed: screen, Window/Background: window coordinates).",
        "seq.add": "＋  Add point",
        "seq.record": "●  Record macro (F7)",
        "seq.stop": "■  Stop recording (F7)",
        "seq.clear": "Clear",
        "seq.empty": "No points yet. Start with “Add point” or record a macro.",
        "seq.wait": "Wait (ms)",
        "seq.auto": "auto",
        "card.presets": "Presets",
        "preset.sim.title": "🖱  Click simulator",
        "preset.sim.desc": "~16 CPS, 15 ms hold, light jitter · Window method",
        "preset.fast.title": "⚡  Fast",
        "preset.fast.desc": "~30 CPS, no jitter · Window method",
        "preset.safe.title": "🎭  Human-like",
        "preset.safe.desc": "~8 CPS, strong jitter, position jitter · Window method",
        "preset.turbo.title": "🚀  Turbo",
        "preset.turbo.desc": "100 CPS · Fixed point (for non-game apps)",
        "card.tips": "Game tips",
        "tips.1": "•  Games usually try to catch a click within a single frame. Setting “Hold time” to 10–30 ms reduces missed clicks.",
        "tips.2": "•  Use the “Window” method for games. If the game window is not active, NovaClick pauses instead of clicking the wrong window.",
        "tips.3": "•  The “Background” method does not work in most games: they ignore these messages. This is not a bug, it is how games read input.",
        "tips.4": "•  “Bring to front” flashes the game to the front, clicks and returns while the window is inactive. Experimental; expect a short flicker on every click, so use slow intervals.",
        "tips.5": "•  Some games forbid automated clicking. Check the game's rules; the risk is yours.",
        "card.lang": "Language",
        "lang.tr": "Türkçe",
        "lang.en": "English",
        "card.look": "Appearance",
        "opt.accent": "Accent color",
        "opt.topmost": "Always on top",
        "card.behavior": "Behavior",
        "opt.delay": "Start delay (sec)",
        "opt.failsafe": "Failsafe (move the mouse to the top-left corner)",
        "opt.tray": "Minimize to system tray on close",
        "card.profiles": "Profiles",
        "profile.none": "No profiles",
        "profile.load": "Load",
        "profile.delete": "Delete",
        "profile.save": "Save",
        "profile.placeholder": "New profile name",
        "about.made": "Built together with Claude (Anthropic).",
        "about.desc": "A modern, feature-rich, open-source auto clicker.",
        "about.github": "Open on GitHub",
        "about.releases": "Releases",
        "card.keys": "Shortcuts",
        "about.keys": "F6  →  Start / stop (changeable)\nF7  →  Start / stop macro recording\nTop-left corner  →  Failsafe (except Background method)",
        "about.license": "MIT License · Use at your own risk. Automated clicking may violate the rules of some services and get your account banned.",
        "dock.start": "START",
        "dock.stop": "STOP",
        "dock.cancel": "CANCEL",
        "dock.hotkey": "Hotkey",
        "dock.change": "Change",
        "dock.capturing": "Press a key…",
        "dock.hkmode": "Hotkey mode",
        "hkmode.toggle": "Toggle",
        "hkmode.hold": "Hold",
        "stat.clicks": "Clicks",
        "stat.cps": "CPS",
        "stat.time": "Time",
        "state.idle": "●  READY",
        "state.running": "●  RUNNING",
        "state.waiting": "●  WAITING",
        "state.paused": "●  PAUSED",
        "state.recording": "●  RECORDING",
        "opt.spoof": "Focus spoofing (experimental)",
        "spoof.hint": "Also tells the window “you are active”; can make background clicks work in some programs. Turn it off if the game locks or hides your cursor.",
        "target.test": "Test (3 clicks)",
        "target.guide": "Click in the background while you use the PC → Background (browsers, classic apps). Click in a game → Window (your mouse is busy while the game is active). Not sure? Pick the window and press Test.",
        "card.diag": "Diagnostics",
        "diag.lastkey": "Last key detected: {key} ({ago} s ago)",
        "diag.nokey": "No key detected yet. If pressing F6 does not show up here, the hotkey is not received in that window.",
        "diag.self_admin": "NovaClick: running as administrator",
        "diag.self_user": "NovaClick: running as a normal user",
        "diag.target_admin": "Target program: running as administrator",
        "diag.target_user": "Target program: normal",
        "diag.target_unknown": "Target program: not selected or unknown",
        "diag.relaunch": "Restart as administrator",
        "diag.log": "Error log: {path}",
        "dock.rec": "REC",
        "hint.test": "Test: sending 3 clicks…",
        "hint.need_admin": "The target program runs as administrator: start NovaClick as administrator too (Settings → Diagnostics), otherwise hotkey and clicks will not work.",
        "hint.internal_error": "An unexpected error occurred and was logged: {path}",
        "hint.relaunch_failed": "Could not restart, or the prompt was declined.",
        "tray.show": "Show",
        "tray.toggle": "Start / Stop",
        "tray.quit": "Quit",
        "hint.min_interval": "Interval must be at least 1 ms, it was set to 1 ms.",
        "hint.need_target": "Pick the target window first with “Pick window” (Target page).",
        "hint.pick_pos": "Click anywhere on the screen to choose the fixed position.",
        "hint.pick_window": "Bring the target window to the front and click the spot you want clicked (that click is also performed in the window).",
        "hint.pos_set": "Position set: X={x}, Y={y}",
        "hint.window_set": "Target window selected (X={x}, Y={y}).",
        "hint.own_window": "You selected the NovaClick window. Click a spot in the target window instead.",
        "hint.no_window": "Could not detect a window, try again.",
        "hint.done": "The set number of repeats is complete.",
        "hint.time": "Time limit reached, stopped.",
        "hint.failsafe": "Failsafe: the mouse was moved to the top-left corner.",
        "hint.window_closed": "The target window was closed, clicking stopped.",
        "hint.bg_on": "Background mode is on: you can use your mouse freely. Press {key} to stop.",
        "hint.window_on": "Window mode: clicks while the target window is active and pauses when you switch away. Press {key} to stop.",
        "hint.hotkey_prompt": "Press the key you want to use as the new hotkey.",
        "hint.hotkey_set": "Hotkey set to {key}.",
        "hint.profile_name": "Type a name for the profile.",
        "hint.profile_saved": "Profile “{name}” saved.",
        "hint.profile_loaded": "Profile “{name}” loaded.",
        "hint.profile_deleted": "Profile “{name}” deleted.",
        "hint.rec_on": "Recording started: click where you want. Press F7 to finish.",
        "hint.rec_off": "Recording finished: {n} points.",
        "hint.add_point": "Click on the screen where you want to add the point.",
        "hint.point_added": "Point added: X={x}, Y={y}",
        "hint.max_points": "At most {n} points can be added.",
        "hint.win_only": "Window and Background methods currently work on Windows only.",
        "hint.preset": "Preset applied.",
        "hint.preset_target": "Preset applied. Now pick the game window.",
        "hint.need_points": "Sequence is on but has no points. Add points or turn it off.",
        "hint.tray": "NovaClick keeps running in the system tray.",
    },
}


# --------------------------------------------------------------------------
# Tıklama motoru (ayrı iş parçacığında çalışır)
# --------------------------------------------------------------------------
class ClickEngine:
    def __init__(self, events: queue.Queue):
        self.mouse = mouse.Controller()
        self.events = events
        self._stop = threading.Event()
        self._thread = None
        self.phase = "idle"  # idle | waiting | running | paused
        self.clicks = 0
        self.target = 0
        self.started_at = 0.0
        self.last_elapsed = 0.0
        self.stamps = collections.deque(maxlen=5000)

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, cfg):
        if self.active:
            return
        self._stop.clear()
        self.clicks = 0
        self.target = cfg["repeat"]
        self.stamps.clear()
        self.last_elapsed = 0.0
        self.started_at = time.perf_counter()
        self.phase = "waiting" if cfg["delay"] > 0 else "running"
        self._thread = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def cps(self):
        now = time.perf_counter()
        return sum(1 for t in list(self.stamps) if now - t <= 1.0)

    # ---- tıklama yardımcıları
    def _press_release(self, btn, hold):
        self.mouse.press(btn)
        try:
            if hold > 0:
                self._stop.wait(hold)
        finally:
            self.mouse.release(btn)

    def _real_click(self, cfg, code):
        btn = BUTTONS[code]
        for i in range(cfg["count"]):
            self._press_release(btn, cfg["hold"])
            if i < cfg["count"] - 1 and self._stop.wait(0.03):
                break

    def _click_at(self, cfg, sx, sy, code):
        pj = cfg["pos_jitter"]
        if pj:
            sx += random.randint(-pj, pj)
            sy += random.randint(-pj, pj)
        self.mouse.position = (sx, sy)
        self._stop.wait(0.002)
        # Roblox gibi oyunlar imleci ancak bir hareket olayı görünce "pencerenin içinde" sayıyor
        self.mouse.move(0, -1)
        self.mouse.move(0, 1)
        self._real_click(cfg, code)
        return "ok"

    def _focus_click(self, cfg, x, y, code):
        """Pencere aktif değilken: öne getir, tıkla, fareyi ve pencereyi eski yerine ver."""
        top = cfg["top"]
        prev_fg = user32.GetForegroundWindow()
        prev_pos = self.mouse.position
        if not force_foreground(top):
            return "paused"
        t0 = time.perf_counter()
        while not is_foreground(top):
            if time.perf_counter() - t0 > 0.25 or self._stop.wait(0.005):
                return "paused"
        self._stop.wait(0.015)
        sx, sy = client_to_screen(cfg["hwnd"], x, y)
        self._click_at(cfg, sx, sy, code)
        self.mouse.position = prev_pos
        if prev_fg and int(prev_fg) != int(top):
            force_foreground(prev_fg)
        return "ok"

    def _perform(self, cfg, x, y, code):
        """Bir tıklama uygular. Dönüş: ok | paused | closed | failsafe"""
        mode = cfg["mode"]
        if mode == "background":
            if not window_exists(cfg["hwnd"]):
                return "closed"
            send_background_click(
                cfg["hwnd"], (x, y), code, cfg["count"], cfg["hold"], self._stop, cfg.get("spoof", False), cfg.get("top")
            )
            return "ok"

        if cfg["failsafe"]:
            px, py = self.mouse.position
            if px <= 0 and py <= 0:
                return "failsafe"

        if mode == "window":
            if not window_exists(cfg["hwnd"]):
                return "closed"
            if is_foreground(cfg["top"]):
                sx, sy = client_to_screen(cfg["hwnd"], x, y)
                return self._click_at(cfg, sx, sy, code)
            if cfg["on_inactive"] == "focus":
                return self._focus_click(cfg, x, y, code)
            return "paused"

        if mode == "fixed":
            return self._click_at(cfg, x, y, code)
        self._real_click(cfg, code)  # cursor
        return "ok"

    def _run(self, cfg):
        reason = "manual"
        try:
            if cfg["delay"] > 0:
                if self._stop.wait(cfg["delay"]):
                    return
                self.phase = "running"
                self.started_at = time.perf_counter()

            points = cfg["points"]
            base, jitter = cfg["interval"], cfg["jitter"]
            limit = cfg["time_limit"]
            idx = 0
            next_t = time.perf_counter()

            while not self._stop.is_set():
                if limit and time.perf_counter() - self.started_at >= limit:
                    reason = "time"
                    break

                step = points[idx % len(points)] if points else None
                x, y = (step["x"], step["y"]) if step else cfg["pos"]
                code = (step.get("button") if step else None) or cfg["button_code"]

                status = self._perform(cfg, x, y, code)
                if status == "failsafe":
                    reason = "failsafe"
                    break
                if status == "closed":
                    reason = "window_closed"
                    break
                if status == "paused":
                    self.phase = "paused"
                    if self._stop.wait(0.1):
                        break
                    next_t = time.perf_counter()
                    continue
                if self.phase == "paused":
                    self.phase = "running"

                idx += 1
                self.clicks += 1
                self.stamps.append(time.perf_counter())

                if self.target and self.clicks >= self.target:
                    reason = "done"
                    break

                if step and step.get("wait") is not None:
                    gap = step["wait"]
                else:
                    gap = base + (random.uniform(-jitter, jitter) if jitter else 0.0)
                gap = max(gap, 0.001)
                next_t += gap
                wait = next_t - time.perf_counter()
                if wait > 0:
                    if self._stop.wait(wait):
                        break
                else:
                    # geride kaldık: art arda yığılma olmasın diye zamanı sıfırla
                    next_t = time.perf_counter()
        finally:
            if self.phase in ("running", "paused"):
                self.last_elapsed = time.perf_counter() - self.started_at
            self.phase = "idle"
            self.events.put(("finished", reason))


# --------------------------------------------------------------------------
# Canvas ile çizilen özel öğeler: büyük başlat "orb"u ve gradyanlı sayfa başlığı
# --------------------------------------------------------------------------
class Orb(_Canvas):
    """Büyük başlat düğmesi: parıltı, canlı CPS göstergesi ve dönen halka."""

    def __init__(self, master, size_px, on_click, bg):
        super().__init__(master, width=size_px, height=size_px, highlightthickness=0, bg=bg, cursor="hand2")
        self.size = size_px
        self.bg = bg
        self._on_click = on_click
        self.phase = "idle"
        self.accent = "#3b82f6"
        self.glyph, self.title, self.sub = "▶", "START", ""
        self.cps = 0.0
        self.peak = 20.0
        self.hover = False
        self.dirty = True
        self.bind("<Button-1>", lambda e: self._on_click())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))

    def _set_hover(self, value):
        self.hover = value
        self.dirty = True

    def set_state(self, phase, accent, glyph, title, sub):
        self.phase, self.accent = phase, accent
        self.glyph, self.title, self.sub = glyph, title, sub
        self.dirty = True

    def set_cps(self, cps):
        cps = float(cps)
        if int(cps) != int(self.cps):
            self.dirty = True
        self.cps = cps
        self.peak = max(20.0, cps * 1.15, self.peak * 0.995)

    def state_color(self):
        return {"running": OK, "waiting": WARN, "paused": WARN, "recording": REC}.get(self.phase, self.accent)

    def render(self, t):
        self.dirty = False
        self.delete("all")
        S = float(self.size)
        c = S / 2.0
        col = self.state_color()
        live = self.phase in ("running", "waiting", "paused", "recording")
        pulse = (math.sin(t * 3.2) + 1) / 2 if live else 0.0

        R = S * 0.335
        for i in range(16, 0, -1):  # parıltı: dışa doğru sönen halkalar (tuval kenarına taşmaz)
            r = R + i * S * 0.0098
            a = 0.010 * (17 - i) * (0.75 + 0.55 * pulse)
            self.create_oval(c - r, c - r, c + r, c + r, fill=blend(self.bg, col, min(a, 0.30)), outline="")

        w = max(6, int(S * 0.05))
        box = (c - R, c - R, c + R, c + R)
        self.create_arc(*box, start=225, extent=-270, style="arc", width=w, outline=blend(self.bg, "#ffffff", 0.10))
        frac = min(self.cps / max(self.peak, 1.0), 1.0)
        if frac > 0.01:
            self.create_arc(*box, start=225, extent=-270 * frac, style="arc", width=w, outline=col)

        r2 = R - w * 1.1
        inner = blend(CARD, col, 0.16 if self.hover else 0.09)
        self.create_oval(c - r2, c - r2, c + r2, c + r2, fill=inner, outline=blend(col, self.bg, 0.45), width=2)

        if self.phase in ("running", "waiting"):  # dönen halka
            r3 = r2 - S * 0.03
            for k in range(3):
                self.create_arc(
                    c - r3, c - r3, c + r3, c + r3, start=(t * 140 + k * 120) % 360, extent=38,
                    style="arc", width=3, outline=blend(inner, col, 0.85),
                )

        self.create_text(c, c - S * 0.095, text=self.glyph, fill=col, font=("Segoe UI", -int(S * 0.15), "bold"))
        self.create_text(c, c + S * 0.030, text=self.title, fill=TEXT, font=("Segoe UI", -int(S * 0.072), "bold"))
        if self.sub:
            self.create_text(c, c + S * 0.105, text=self.sub, fill=MUTED, font=("Consolas", -int(S * 0.05)))
        self.create_text(
            c, c + R * 0.98, text=f"{int(self.cps)} CPS", fill=col, font=("Segoe UI", -int(S * 0.055), "bold")
        )


class Banner(_Canvas):
    """Sayfa başlığı: vurgu renginden kararan gradyan, büyük silik simge, başlık ve alt yazı."""

    def __init__(self, master, app, name):
        super().__init__(master, width=10, height=int(92 * app.scale), highlightthickness=0, bg=BG)
        self.app = app
        self.name = name
        self.bind("<Configure>", lambda e: self.redraw())

    def redraw(self):
        app = self.app
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("all")
        if w < 40 or h < 20:
            return
        acc = app.accent
        c0, c1 = blend(BG, acc, 0.34), blend(BG, acc, 0.10)
        step = max(3, int(4 * app.scale))
        for x in range(0, w, step):
            t = x / float(w)
            col = blend(c0, c1, t / 0.55) if t < 0.55 else blend(c1, BG, (t - 0.55) / 0.45)
            self.create_rectangle(x, 0, x + step, h, fill=col, outline="")
        self.create_rectangle(0, 0, max(4, int(5 * app.scale)), h, fill=acc, outline="")
        self.create_text(
            w - int(26 * app.scale), h / 2, text=PAGE_ICONS[self.name], anchor="e",
            fill=blend(BG, acc, 0.38), font=("Segoe UI Emoji", -int(58 * app.scale)),
        )
        pad = int(26 * app.scale)
        self.create_text(
            pad, h * 0.38, anchor="w", text=app.t(f"page.{self.name}.title"), fill=TEXT,
            font=("Segoe UI", -int(28 * app.scale), "bold"),
        )
        self.create_text(
            pad, h * 0.72, anchor="w", text=app.t(f"page.{self.name}.sub"),
            fill=blend(MUTED, TEXT, 0.25), font=("Segoe UI", -int(13 * app.scale)),
        )


# --------------------------------------------------------------------------
# Dile duyarlı segmentli düğme (iç değer: dil bağımsız kod)
# --------------------------------------------------------------------------
class LSeg(ctk.CTkSegmentedButton):
    def __init__(self, master, app, codes, prefix, command=None, **kw):
        self._l_app = app
        self._l_codes = list(codes)
        self._l_prefix = prefix
        self._l_cmd = command
        self._l_code = self._l_codes[0]
        super().__init__(
            master,
            values=[app.t(f"{prefix}.{c}") for c in self._l_codes],
            command=self._l_changed,
            **kw,
        )

    def _l_label(self, code):
        return self._l_app.t(f"{self._l_prefix}.{code}")

    def _l_changed(self, label):
        for c in self._l_codes:
            if self._l_label(c) == label:
                self._l_code = c
                break
        if self._l_cmd:
            self._l_cmd(self._l_code)

    def code(self):
        return self._l_code

    def set_code(self, code):
        if code in self._l_codes:
            self._l_code = code
        self.set(self._l_label(self._l_code))

    def relabel(self):
        self.configure(values=[self._l_label(c) for c in self._l_codes])
        self.set(self._l_label(self._l_code))


# --------------------------------------------------------------------------
# Arayüz
# --------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title(f"{APP_NAME} {APP_VERSION}")
        self._fit_window()
        self.configure(fg_color=BG)
        self._set_icon()
        self.after(300, self._set_icon)

        self.events = queue.Queue()
        self.engine = ClickEngine(self.events)

        data = self._load_config()
        settings = self._normalize({**DEFAULTS, **data.get("last", {})})
        self.profiles = {
            name: self._normalize({**DEFAULTS, **prof})
            for name, prof in data.get("profiles", {}).items()
            if isinstance(prof, dict)
        }
        self.lang = settings["lang"] or detect_language()
        self.scale = self._detect_scale()
        self.banners = []
        self.last_key = ""
        self.last_key_t = 0.0
        self._last_press = 0.0
        self.target_elevated = None
        self._err_t = 0.0

        self.accent, self.accent_h = ACCENTS[settings["accent"]]
        self.accent_widgets = []
        self._i18n = []
        self._segs = []
        self.hotkey = settings["hotkey"]
        self.hotkey_mode = settings["hotkey_mode"]
        self.capturing_hotkey = False
        self._key_down = False
        self._last_phase = None
        self.current_page = "home"
        self._hint = ("", {})

        # hedef pencere (Pencere / Arka plan yöntemleri)
        self.target_hwnd = 0
        self.target_top = 0
        self.target_title = ""

        # nokta dizisi / makro
        self.points = []
        self.point_entries = []
        self.recording = False
        self._rec_t = None
        self._rec_listener = None

        self.cps_hist = collections.deque([0] * HIST, maxlen=HIST)
        self._tick = 0
        self.tray_icon = None
        self._quitting = False

        self.f_logo = ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        self.f_page = ctk.CTkFont(family="Segoe UI", size=26, weight="bold")
        self.f_h2 = ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        self.f_body = ctk.CTkFont(family="Segoe UI", size=13)
        self.f_small = ctk.CTkFont(family="Segoe UI", size=12)
        self.f_big = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self.f_num = ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        self.f_start = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")

        self._build_ui()
        self._apply_settings(settings)
        self._show_page("home")
        self._start_listeners()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._poll)
        self.after(40, self._anim)

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------
    def t(self, tkey, **fmt):
        # NOT: biçim alanı olarak "key" kullanılabilsin diye parametre adı tkey (eski hata: "multiple values for 'key'")
        s = STR.get(self.lang, STR["en"]).get(tkey)
        if s is None:
            s = STR["en"].get(tkey, tkey)
        return s.format(**fmt) if fmt else s

    def _detect_scale(self):
        try:
            return max(self.winfo_fpixels("1i") / 96.0, 1.0)
        except Exception:
            return 1.0

    def _fit_window(self):
        """Pencereyi ekrana sığacak şekilde boyutlandırır (küçük laptop ekranları için)."""
        try:
            scale = max(self.winfo_fpixels("1i") / 96.0, 1.0)
            sw, sh = self.winfo_screenwidth() / scale, self.winfo_screenheight() / scale
        except Exception:
            sw, sh = 1920, 1080
        w, h = int(min(1260, sw - 40)), int(min(820, sh - 90))
        self.geometry(f"{w}x{h}")
        self.minsize(min(1100, w), min(680, h))

    def _set_icon(self):
        ico = resource_path("novaclick.ico")
        if IS_WIN and Path(ico).exists():
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    def _reg(self, widget, key, attr="text"):
        """Metni kaydeder; dil değişince otomatik yenilenir. key: anahtar ya da fonksiyon."""
        self._i18n.append((widget, attr, key))
        widget.configure(**{attr: key() if callable(key) else self.t(key)})
        return widget

    def _acc(self, widget, kind):
        self.accent_widgets.append((widget, kind))
        return widget

    def _set_hint(self, hkey="", **fmt):
        self._hint = (hkey, fmt)
        self._render_hint()

    def _render_hint(self):
        key, fmt = self._hint
        self.hint.configure(text=self.t(key, **fmt) if key else "")

    # ---- yapı taşları
    def _lbl(self, parent, key, muted=True, font=None, **kw):
        w = ctk.CTkLabel(
            parent, text="", font=font or self.f_body, text_color=MUTED if muted else TEXT, **kw
        )
        return self._reg(w, key)

    def _entry(self, parent, width=80, height=40, font=None, center=True, placeholder=None):
        e = ctk.CTkEntry(
            parent,
            width=width,
            height=height,
            font=font or self.f_body,
            justify="center" if center else "left",
            fg_color=CARD_ALT,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=10,
        )
        if placeholder:
            self._reg(e, placeholder, "placeholder_text")
        return e

    def _seg(self, parent, codes, prefix, command=None):
        seg = LSeg(
            parent,
            self,
            codes,
            prefix,
            command,
            font=self.f_body,
            height=36,
            corner_radius=10,
            fg_color=CARD_ALT,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            selected_color=self.accent,
            selected_hover_color=self.accent_h,
            text_color=TEXT,
        )
        self._segs.append(seg)
        return self._acc(seg, "seg")

    def _switch(self, parent, key, command=None):
        sw = ctk.CTkSwitch(
            parent,
            text="",
            command=command,
            font=self.f_body,
            text_color=TEXT,
            fg_color=BORDER,
            progress_color=self.accent,
            button_color="#ffffff",
            button_hover_color="#e5e7eb",
        )
        self._acc(sw, "switch")
        return self._reg(sw, key)

    def _btn(self, parent, key, command, accent=False, width=100, height=34):
        b = ctk.CTkButton(
            parent,
            text="",
            command=command,
            width=width,
            height=height,
            font=self.f_body if accent else self.f_small,
            corner_radius=10,
            fg_color=self.accent if accent else CARD_ALT,
            hover_color=self.accent_h if accent else BORDER,
            text_color="#ffffff" if accent else TEXT,
            border_width=0 if accent else 1,
            border_color=BORDER,
        )
        if accent:
            self._acc(b, "btn")
        return self._reg(b, key)

    def _card(self, parent, row, title_key, sub_key=None):
        outer = ctk.CTkFrame(
            parent, fg_color=CARD, corner_radius=18, border_width=1, border_color=BORDER
        )
        outer.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        outer.grid_columnconfigure(0, weight=1)
        self._reg(
            ctk.CTkLabel(outer, text="", font=self.f_h2, text_color=TEXT), title_key
        ).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 0 if sub_key else 10))
        if sub_key:
            self._reg(
                ctk.CTkLabel(outer, text="", font=self.f_small, text_color=MUTED), sub_key
            ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 10))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 20))
        body.grid_columnconfigure(0, weight=1)
        return body

    def _row(self, body, r, key, with_label=False):
        """Solda etiket, sağda kontrol alanı olan satır. Sağ alan (frame) döner."""
        lbl = self._lbl(body, key, muted=False)
        lbl.grid(row=r, column=0, sticky="w", pady=6)
        holder = ctk.CTkFrame(body, fg_color="transparent")
        holder.grid(row=r, column=1, sticky="e", pady=6)
        body.grid_columnconfigure(1, weight=1)
        return (holder, lbl) if with_label else holder

    # ------------------------------------------------------------------
    # Yapılandırma
    # ------------------------------------------------------------------
    def _load_config(self):
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self):
        data = {"last": self._get_settings(), "profiles": self.profiles}
        try:
            CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _normalize(s):
        """Eski sürüm etiketlerini kodlara çevirir, geçersiz değerleri varsayılana döndürür."""
        s = dict(s)
        for key, mapping in LEGACY.items():
            if s.get(key) in mapping:
                s[key] = mapping[s[key]]
        for key, allowed in VALID.items():
            if s.get(key) not in allowed:
                s[key] = DEFAULTS[key]
        if not isinstance(s.get("points"), list):
            s["points"] = []
        clean = []
        for p in s["points"]:
            try:
                clean.append(
                    {
                        "x": int(p["x"]),
                        "y": int(p["y"]),
                        "button": p.get("button") if p.get("button") in BUTTONS else "left",
                        "wait": None if p.get("wait") in (None, "") else max(0, int(p["wait"])),
                    }
                )
            except Exception:
                continue
        s["points"] = clean[:MAX_POINTS]
        return s

    def _get_settings(self):
        self._sync_points()
        return {
            "lang": self.lang,
            "hours": self.e_hours.get(),
            "minutes": self.e_minutes.get(),
            "seconds": self.e_seconds.get(),
            "millis": self.e_millis.get(),
            "jitter": int(self.s_jitter.get()),
            "hold": self.e_hold.get(),
            "button": self.seg_button.code(),
            "click_type": self.seg_type.code(),
            "repeat_mode": self.seg_repeat.code(),
            "repeat_count": self.e_repeat.get(),
            "time_limit": self.e_timelimit.get(),
            "position_mode": self.pos_mode.code(),
            "x": self.e_x.get(),
            "y": self.e_y.get(),
            "pos_jitter": self.e_pj.get(),
            "on_inactive": self.seg_inactive.code(),
            "spoof": bool(self.sw_spoof.get()),
            "use_points": bool(self.sw_points.get()),
            "points": [dict(p) for p in self.points],
            "start_delay": self.e_delay.get(),
            "failsafe": bool(self.sw_failsafe.get()),
            "topmost": bool(self.sw_top.get()),
            "tray": bool(self.sw_tray.get()) if self.sw_tray is not None else False,
            "hotkey": self.hotkey,
            "hotkey_mode": self.hotkey_mode,
            "accent": self.accent_name,
        }

    @staticmethod
    def _set_entry(entry, text):
        prev = entry.cget("state")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, str(text))
        entry.configure(state=prev)

    def _apply_settings(self, s):
        self._set_entry(self.e_hours, s["hours"])
        self._set_entry(self.e_minutes, s["minutes"])
        self._set_entry(self.e_seconds, s["seconds"])
        self._set_entry(self.e_millis, s["millis"])
        self.s_jitter.set(s["jitter"])
        self._on_jitter(s["jitter"])
        self._set_entry(self.e_hold, s["hold"])
        self.seg_button.set_code(s["button"])
        self.seg_type.set_code(s["click_type"])
        self.seg_repeat.set_code(s["repeat_mode"])
        self._set_entry(self.e_repeat, s["repeat_count"])
        self._on_repeat_mode(s["repeat_mode"])
        self._set_entry(self.e_timelimit, s["time_limit"])
        self.pos_mode.set_code(s["position_mode"])
        self._set_entry(self.e_x, s["x"])
        self._set_entry(self.e_y, s["y"])
        self._set_entry(self.e_pj, s["pos_jitter"])
        self.seg_inactive.set_code(s["on_inactive"])
        (self.sw_spoof.select if s["spoof"] else self.sw_spoof.deselect)()
        self._on_mode(s["position_mode"])
        self.points = [dict(p) for p in s["points"]]
        self._rebuild_points()
        (self.sw_points.select if s["use_points"] else self.sw_points.deselect)()
        self._set_entry(self.e_delay, s["start_delay"])
        (self.sw_failsafe.select if s["failsafe"] else self.sw_failsafe.deselect)()
        (self.sw_top.select if s["topmost"] else self.sw_top.deselect)()
        self._on_topmost()
        if self.sw_tray is not None:
            (self.sw_tray.select if s["tray"] else self.sw_tray.deselect)()
        self.hotkey = s["hotkey"]
        self.l_hotkey.configure(text=self.hotkey.upper())
        self.hotkey_mode = s["hotkey_mode"]
        self.seg_hkmode.set_code(self.hotkey_mode)
        self._on_accent(s["accent"])
        self.seg_lang.set_code(self.lang)

    # ------------------------------------------------------------------
    # Arayüz kurulumu
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages = {}
        self.holders = {}
        for name in PAGES:
            holder = ctk.CTkFrame(self.content, fg_color="transparent")
            holder.grid(row=0, column=0, sticky="nsew", padx=(6, 6), pady=(10, 0))
            page = ctk.CTkScrollableFrame(
                holder,
                fg_color="transparent",
                scrollbar_button_color=BORDER,
                scrollbar_button_hover_color=MUTED,
            )
            page.pack(fill="both", expand=True)
            page.grid_columnconfigure(0, weight=1)
            self.holders[name] = holder
            self.pages[name] = page
            self._page_header(page, name)

        self._build_home(self.pages["home"])
        self._build_target(self.pages["target"])
        self._build_sequence(self.pages["sequence"])
        self._build_game(self.pages["game"])
        self._build_settings(self.pages["settings"])
        self._build_about(self.pages["about"])
        self._build_dock()

        self.hint = ctk.CTkLabel(self, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.hint.grid(row=1, column=0, columnspan=3, sticky="ew", padx=24, pady=(4, 12))

    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=214, corner_radius=0, fg_color=SIDEBAR)
        side.grid(row=0, column=0, rowspan=1, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 22))
        bolt = ctk.CTkLabel(logo, text="⚡", font=ctk.CTkFont(size=30), text_color=self.accent)
        self._acc(bolt, "text")
        bolt.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ctk.CTkLabel(logo, text=APP_NAME, font=self.f_logo, text_color=TEXT).grid(
            row=0, column=1, sticky="w"
        )
        self._lbl(logo, "app.sub", font=ctk.CTkFont(family="Segoe UI", size=10)).grid(
            row=1, column=1, sticky="w"
        )

        self._nav = {}
        self._nav_ind = {}
        for i, name in enumerate(PAGES):
            row = ctk.CTkFrame(side, fg_color="transparent")
            row.grid(row=1 + i, column=0, sticky="ew", padx=(0, 12), pady=2)
            row.grid_columnconfigure(1, weight=1)
            ind = ctk.CTkFrame(row, width=4, height=28, corner_radius=2, fg_color="transparent")
            ind.grid(row=0, column=0, padx=(6, 6))
            b = ctk.CTkButton(
                row,
                text="",
                height=42,
                corner_radius=10,
                anchor="w",
                font=self.f_body,
                fg_color="transparent",
                hover_color=CARD_ALT,
                text_color=TEXT,
                command=lambda n=name: self._show_page(n),
            )
            b.grid(row=0, column=1, sticky="ew")
            self._nav[name] = b
            self._nav_ind[name] = ind
        side.grid_rowconfigure(len(PAGES) + 1, weight=1)
        ctk.CTkLabel(side, text=f"v{APP_VERSION}", font=self.f_small, text_color=MUTED).grid(
            row=len(PAGES) + 2, column=0, pady=(0, 16)
        )

    def _page_header(self, page, name):
        banner = Banner(page, self, name)
        banner.grid(row=0, column=0, sticky="ew", padx=4, pady=(6, 16))
        self.banners.append(banner)

    def _show_page(self, name):
        self.current_page = name
        for n, holder in self.holders.items():
            if n == name:
                holder.grid()
            else:
                holder.grid_remove()
        self._refresh_nav()

    def _refresh_nav(self):
        for name, btn in self._nav.items():
            active = name == self.current_page
            btn.configure(
                text=f"  {PAGE_ICONS[name]}    {self.t('nav.' + name)}",
                fg_color=CARD_ALT if active else "transparent",
                text_color=self.accent if active else TEXT,
            )
            self._nav_ind[name].configure(fg_color=self.accent if active else "transparent")

    # ---- Sayfa: Tıklama
    def _build_home(self, page):
        body = self._card(page, 1, "card.interval", "card.interval.sub")
        for c in range(4):
            body.grid_columnconfigure(c, weight=1, uniform="iv")
        self.e_hours = self._entry(body, height=54, font=self.f_big)
        self.e_minutes = self._entry(body, height=54, font=self.f_big)
        self.e_seconds = self._entry(body, height=54, font=self.f_big)
        self.e_millis = self._entry(body, height=54, font=self.f_big)
        for i, (e, key) in enumerate(
            [
                (self.e_hours, "unit.hours"),
                (self.e_minutes, "unit.minutes"),
                (self.e_seconds, "unit.seconds"),
                (self.e_millis, "unit.millis"),
            ]
        ):
            e.grid(row=0, column=i, padx=5, sticky="ew")
            self._lbl(body, key).grid(row=1, column=i, pady=(4, 0))

        chips = ctk.CTkFrame(body, fg_color="transparent")
        chips.grid(row=2, column=0, columnspan=4, sticky="w", pady=(16, 0))
        self._lbl(chips, "interval.quick").pack(side="left", padx=(5, 8))
        for cps in (1, 5, 10, 20, 50, 100):
            ctk.CTkButton(
                chips,
                text=f"{cps} CPS",
                command=lambda c=cps: self._preset_cps(c),
                width=64,
                height=32,
                font=self.f_small,
                corner_radius=9,
                fg_color=CARD_ALT,
                hover_color=BORDER,
                text_color=TEXT,
                border_width=1,
                border_color=BORDER,
            ).pack(side="left", padx=3)

        jit = ctk.CTkFrame(body, fg_color="transparent")
        jit.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        jit.grid_columnconfigure(1, weight=1)
        self._lbl(jit, "interval.jitter", muted=False).grid(row=0, column=0, padx=(5, 12))
        self.s_jitter = self._acc(
            ctk.CTkSlider(
                jit,
                from_=0,
                to=500,
                number_of_steps=100,
                command=self._on_jitter,
                fg_color=CARD_ALT,
                progress_color=self.accent,
                button_color=self.accent,
                button_hover_color=self.accent_h,
            ),
            "slider",
        )
        self.s_jitter.grid(row=0, column=1, sticky="ew")
        self.l_jitter = ctk.CTkLabel(jit, text="", font=self.f_small, text_color=MUTED, width=70)
        self.l_jitter.grid(row=0, column=2, padx=(12, 5))

        body = self._card(page, 2, "card.click")
        self.seg_button = self._seg(self._row(body, 0, "opt.button"), list(BUTTONS), "btn")
        self.seg_button.pack()
        self.seg_type = self._seg(self._row(body, 1, "opt.type"), list(COUNTS), "ctype")
        self.seg_type.pack()

        holder = self._row(body, 2, "opt.hold")
        self._lbl(holder, "hold.hint", font=self.f_small).pack(side="left", padx=(0, 10))
        self.e_hold = self._entry(holder, width=70, height=36)
        self.e_hold.pack(side="left")

        holder = self._row(body, 3, "opt.repeat")
        self.seg_repeat = self._seg(holder, ["infinite", "count"], "rep", self._on_repeat_mode)
        self.seg_repeat.pack(side="left")
        self.e_repeat = self._entry(holder, width=70, height=36)
        self.e_repeat.pack(side="left", padx=(10, 0))

        holder = self._row(body, 4, "opt.timelimit")
        self._lbl(holder, "timelimit.hint", font=self.f_small).pack(side="left", padx=(0, 10))
        self.e_timelimit = self._entry(holder, width=70, height=36)
        self.e_timelimit.pack(side="left")

    # ---- Sayfa: Hedef
    def _build_target(self, page):
        body = self._card(page, 1, "card.mode")
        self.pos_mode = self._seg(body, ["cursor", "fixed", "window", "background"], "mode", self._on_mode)
        self.pos_mode.grid(row=0, column=0, sticky="w")
        self.l_mode_desc = ctk.CTkLabel(
            body, text="", font=self.f_small, text_color=MUTED, justify="left", anchor="w", wraplength=540
        )
        self.l_mode_desc.grid(row=1, column=0, sticky="w", pady=(12, 0))
        guide = self._lbl(body, "target.guide", font=self.f_small, wraplength=540, justify="left", anchor="w")
        guide.grid(row=2, column=0, sticky="w", pady=(10, 0))

        body = self._card(page, 2, "card.point")
        coords = ctk.CTkFrame(body, fg_color="transparent")
        coords.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(coords, text="X", font=self.f_body, text_color=MUTED).pack(side="left", padx=(2, 6))
        self.e_x = self._entry(coords, width=84, height=38)
        self.e_x.pack(side="left")
        ctk.CTkLabel(coords, text="Y", font=self.f_body, text_color=MUTED).pack(side="left", padx=(16, 6))
        self.e_y = self._entry(coords, width=84, height=38)
        self.e_y.pack(side="left")
        self.b_pick = self._btn(coords, "target.pick_pos", self._pick, accent=True, width=170, height=38)
        self.b_pick.pack(side="right")

        self.l_target = ctk.CTkLabel(
            body, text="", font=self.f_small, text_color=MUTED, anchor="w", justify="left", wraplength=540
        )
        self.l_target.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))

        holder = self._row(body, 2, "opt.posjitter")
        self.e_pj = self._entry(holder, width=70, height=36)
        self.e_pj.pack()
        self.row_inactive = self._row(body, 3, "opt.inactive", with_label=True)
        self.seg_inactive = self._seg(self.row_inactive[0], ["pause", "focus"], "inact")
        self.seg_inactive.pack()

        self.sw_spoof = self._switch(body, "opt.spoof")
        self.sw_spoof.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.l_spoof = self._lbl(body, "spoof.hint", font=self.f_small, wraplength=540, justify="left", anchor="w")
        self.l_spoof.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.b_test = self._btn(body, "target.test", self._test_click, width=150, height=36)
        self.b_test.grid(row=6, column=0, sticky="w", pady=(14, 0))

    # ---- Sayfa: Dizi & Makro
    def _build_sequence(self, page):
        body = self._card(page, 1, "card.seq")
        self.sw_points = self._switch(body, "seq.use")
        self.sw_points.grid(row=0, column=0, sticky="w")
        desc = ctk.CTkLabel(
            body, text="", font=self.f_small, text_color=MUTED, justify="left", anchor="w", wraplength=540
        )
        self._reg(desc, "seq.desc")
        desc.grid(row=1, column=0, sticky="w", pady=(8, 12))

        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="w")
        self.b_add = self._btn(bar, "seq.add", self._add_point, accent=True, width=140, height=36)
        self.b_add.pack(side="left")
        self.b_record = self._btn(bar, "seq.record", self._toggle_record, width=190, height=36)
        self.b_record.pack(side="left", padx=8)
        self._btn(bar, "seq.clear", self._clear_points, width=90, height=36).pack(side="left")

        self.points_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.points_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.points_frame.grid_columnconfigure(0, weight=1)

    # ---- Sayfa: Oyun
    def _build_game(self, page):
        body = self._card(page, 1, "card.presets")
        body.grid_columnconfigure((0, 1), weight=1, uniform="pr")
        for i, key in enumerate(PRESETS):
            b = ctk.CTkButton(
                body,
                text="",
                height=74,
                anchor="w",
                corner_radius=12,
                font=self.f_small,
                fg_color=CARD_ALT,
                hover_color=BORDER,
                text_color=TEXT,
                border_width=1,
                border_color=BORDER,
                command=lambda k=key: self._apply_preset(k),
            )
            self._reg(
                b,
                lambda k=key: f"{self.t('preset.' + k + '.title')}\n{self.t('preset.' + k + '.desc')}",
            )
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=5, pady=5)

        body = self._card(page, 2, "card.tips")
        for i in range(1, 6):
            lbl = ctk.CTkLabel(
                body, text="", font=self.f_small, text_color=TEXT, justify="left", anchor="w", wraplength=540
            )
            self._reg(lbl, f"tips.{i}")
            lbl.grid(row=i - 1, column=0, sticky="w", pady=4)

    # ---- Sayfa: Ayarlar
    def _build_settings(self, page):
        body = self._card(page, 1, "card.lang")
        self.seg_lang = self._seg(body, ["tr", "en"], "lang", self._set_language)
        self.seg_lang.grid(row=0, column=0, sticky="w")

        body = self._card(page, 2, "card.look")
        holder = self._row(body, 0, "opt.accent")
        self.accent_name = "blue"
        self.swatches = {}
        for code, (main, hover) in ACCENTS.items():
            b = ctk.CTkButton(
                holder,
                text="",
                width=34,
                height=34,
                corner_radius=17,
                fg_color=main,
                hover_color=hover,
                border_width=0,
                border_color="#ffffff",
                command=lambda c=code: self._on_accent(c),
            )
            b.pack(side="left", padx=4)
            self.swatches[code] = b
        self.sw_top = self._switch(body, "opt.topmost", command=self._on_topmost)
        self.sw_top.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        body = self._card(page, 3, "card.behavior")
        holder = self._row(body, 0, "opt.delay")
        self.e_delay = self._entry(holder, width=70, height=36)
        self.e_delay.pack()
        self.sw_failsafe = self._switch(body, "opt.failsafe")
        self.sw_failsafe.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.sw_tray = None
        if HAS_TRAY:
            self.sw_tray = self._switch(body, "opt.tray")
            self.sw_tray.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        body = self._card(page, 4, "card.profiles")
        self.om_profile = ctk.CTkOptionMenu(
            body,
            values=["-"],
            height=36,
            font=self.f_body,
            fg_color=CARD_ALT,
            button_color=BORDER,
            button_hover_color=MUTED,
            dropdown_fg_color=CARD,
            dropdown_hover_color=BORDER,
            text_color=TEXT,
        )
        self.om_profile.grid(row=0, column=0, columnspan=2, sticky="ew")
        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._btn(btns, "profile.load", self._load_profile, width=110, height=34).pack(side="left")
        self._btn(btns, "profile.delete", self._delete_profile, width=110, height=34).pack(side="left", padx=8)
        save = ctk.CTkFrame(body, fg_color="transparent")
        save.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        save.grid_columnconfigure(0, weight=1)
        self.e_profile = self._entry(save, height=36, center=False, placeholder="profile.placeholder")
        self.e_profile.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._btn(save, "profile.save", self._save_profile, accent=True, width=100, height=36).grid(row=0, column=1)
        self._refresh_profiles()

        body = self._card(page, 5, "card.diag")
        self.l_diag_key = ctk.CTkLabel(
            body, text="", font=self.f_small, text_color=MUTED, anchor="w", justify="left", wraplength=540
        )
        self.l_diag_key.grid(row=0, column=0, sticky="w")
        self.l_diag_self = ctk.CTkLabel(body, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.l_diag_self.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.l_diag_target = ctk.CTkLabel(body, text="", font=self.f_small, text_color=MUTED, anchor="w")
        self.l_diag_target.grid(row=2, column=0, sticky="w", pady=(2, 0))
        log_lbl = ctk.CTkLabel(
            body, text="", font=self.f_small, text_color=MUTED, anchor="w", justify="left", wraplength=540
        )
        self._reg(log_lbl, lambda: self.t("diag.log", path=str(LOG_PATH)))
        log_lbl.grid(row=3, column=0, sticky="w", pady=(6, 0))
        if IS_WIN:
            self._btn(body, "diag.relaunch", self._relaunch_admin, accent=True, width=230, height=36).grid(
                row=4, column=0, sticky="w", pady=(14, 0)
            )

    # ---- Sayfa: Hakkında
    def _build_about(self, page):
        body = self._card(page, 1, "page.about.title")
        title = ctk.CTkLabel(body, text=f"⚡ {APP_NAME}", font=self.f_page, text_color=TEXT)
        title.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(body, text=f"v{APP_VERSION}", font=self.f_small, text_color=MUTED).grid(
            row=1, column=0, sticky="w"
        )
        d = ctk.CTkLabel(body, text="", font=self.f_body, text_color=TEXT, justify="left", anchor="w", wraplength=540)
        self._reg(d, "about.desc")
        d.grid(row=2, column=0, sticky="w", pady=(10, 0))
        m = ctk.CTkLabel(body, text="", font=self.f_body, text_color=self.accent, justify="left", anchor="w", wraplength=540)
        self._acc(m, "text")
        self._reg(m, "about.made")
        m.grid(row=3, column=0, sticky="w", pady=(4, 12))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=4, column=0, sticky="w")
        self._btn(row, "about.github", lambda: webbrowser.open(REPO_URL), accent=True, width=150, height=36).pack(side="left")
        self._btn(row, "about.releases", lambda: webbrowser.open(REPO_URL + "/releases"), width=110, height=36).pack(side="left", padx=8)

        body = self._card(page, 2, "card.keys")
        k = ctk.CTkLabel(body, text="", font=self.f_body, text_color=TEXT, justify="left", anchor="w")
        self._reg(k, "about.keys")
        k.grid(row=0, column=0, sticky="w")
        lic = ctk.CTkLabel(body, text="", font=self.f_small, text_color=MUTED, justify="left", anchor="w", wraplength=540)
        self._reg(lic, "about.license")
        lic.grid(row=1, column=0, sticky="w", pady=(12, 0))

    # ---- Sağ panel (her sayfada görünür)
    def _build_dock(self):
        dock = ctk.CTkFrame(self, width=318, corner_radius=0, fg_color=SIDEBAR)
        dock.grid(row=0, column=2, sticky="nsew")
        dock.grid_propagate(False)
        dock.grid_columnconfigure(0, weight=1)

        self.pill = ctk.CTkLabel(
            dock, text="", font=self.f_small, text_color="#cbd5e1", fg_color=CARD_ALT,
            corner_radius=20, width=170, height=34,
        )
        self.pill.grid(row=0, column=0, pady=(28, 18))

        self.orb = Orb(dock, int(212 * self.scale), self._toggle, SIDEBAR)
        self.orb.grid(row=1, column=0)

        hk = ctk.CTkFrame(dock, fg_color="transparent")
        hk.grid(row=2, column=0, sticky="ew", padx=24, pady=(24, 0))
        hk.grid_columnconfigure(1, weight=1)
        self._lbl(hk, "dock.hotkey", muted=False).grid(row=0, column=0, sticky="w")
        self.l_hotkey = ctk.CTkLabel(
            hk, text="F6", font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=TEXT, fg_color=CARD_ALT, corner_radius=8, width=84, height=32,
        )
        self.l_hotkey.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.b_change = self._btn(hk, "dock.change", self._capture_hotkey, width=84, height=32)
        self.b_change.grid(row=0, column=2)

        self.seg_hkmode = self._seg(dock, ["toggle", "hold"], "hkmode", self._on_hotkey_mode)
        self.seg_hkmode.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 0))

        stats = ctk.CTkFrame(dock, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        stats.grid(row=4, column=0, sticky="ew", padx=20, pady=(22, 0))
        for c in range(3):
            stats.grid_columnconfigure(c, weight=1, uniform="st")
        self.st_clicks = ctk.CTkLabel(stats, text="0", font=self.f_num, text_color=TEXT)
        self.st_cps = ctk.CTkLabel(stats, text="0", font=self.f_num, text_color=TEXT)
        self.st_time = ctk.CTkLabel(stats, text="00:00", font=self.f_num, text_color=TEXT)
        for i, (w, key) in enumerate(
            [(self.st_clicks, "stat.clicks"), (self.st_cps, "stat.cps"), (self.st_time, "stat.time")]
        ):
            w.grid(row=0, column=i, pady=(14, 0))
            self._lbl(stats, key, font=self.f_small).grid(row=1, column=i)
        self.spark = _Canvas(stats, height=64, highlightthickness=0, bg=CARD)
        self.spark.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(10, 4))
        self.bar = self._acc(
            ctk.CTkProgressBar(stats, height=8, fg_color=CARD_ALT, progress_color=self.accent), "bar"
        )
        self.bar.grid(row=3, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 16))
        self.bar.set(0)

    # ------------------------------------------------------------------
    # Dil
    # ------------------------------------------------------------------
    def _set_language(self, lang):
        self.lang = lang
        for widget, attr, key in self._i18n:
            widget.configure(**{attr: key() if callable(key) else self.t(key)})
        for seg in self._segs:
            seg.relabel()
        self._refresh_nav()
        for b in self.banners:
            b.redraw()
        self._on_jitter(self.s_jitter.get())
        self._on_mode()
        self._rebuild_points()
        self._update_target_label()
        self._refresh_profiles(select=self.om_profile.get())
        self._render_hint()
        self._last_phase = None
        self._refresh_state()
        if self.recording:
            self.b_record.configure(text=self.t("seq.stop"))
        if self.capturing_hotkey:
            self.l_hotkey.configure(text=self.t("dock.capturing"))

    # ------------------------------------------------------------------
    # Olay işleyicileri (arayüz)
    # ------------------------------------------------------------------
    @staticmethod
    def _num(entry, default=0.0, cast=float):
        try:
            return max(cast(entry.get().strip().replace(",", ".")), 0)
        except ValueError:
            return default

    def _preset_cps(self, cps):
        for e in (self.e_hours, self.e_minutes, self.e_seconds):
            self._set_entry(e, 0)
        self._set_entry(self.e_millis, max(1, round(1000 / cps)))

    def _on_jitter(self, value):
        v = int(float(value))
        self.l_jitter.configure(text=self.t("jitter.off") if v == 0 else self.t("jitter.val", v=v))

    def _on_repeat_mode(self, value):
        self.e_repeat.configure(state="normal" if value == "count" else "disabled")

    def _on_topmost(self):
        self.attributes("-topmost", bool(self.sw_top.get()))

    def _on_hotkey_mode(self, code):
        self.hotkey_mode = code

    def _on_mode(self, code=None):
        code = code or self.pos_mode.code()
        winlike = code in ("window", "background")
        state = "disabled" if code == "cursor" else "normal"
        self.e_x.configure(state=state)
        self.e_y.configure(state=state)
        self.e_pj.configure(state="normal" if code in ("fixed", "window") else "disabled")
        self.b_pick.configure(
            text=self.t("target.pick_win" if winlike else "target.pick_pos"),
            state="disabled" if code == "cursor" else "normal",
        )
        holder, lbl = self.row_inactive
        if code == "window":
            holder.grid()
            lbl.grid()
        else:
            holder.grid_remove()
            lbl.grid_remove()
        if winlike:
            self.l_target.grid()
        else:
            self.l_target.grid_remove()
        self.l_mode_desc.configure(text=self.t("mode.desc." + code))
        for w in (self.sw_spoof, self.l_spoof):
            if code == "background":
                w.grid()
            else:
                w.grid_remove()
        self.b_test.configure(state="disabled" if code == "cursor" else "normal")
        self._update_target_label()

    def _update_target_label(self):
        if self.target_hwnd:
            self.l_target.configure(text=self.t("target.win", title=self.target_title), text_color=TEXT)
        else:
            self.l_target.configure(text=self.t("target.none"), text_color=MUTED)

    def _on_accent(self, code):
        self.accent_name = code
        self.accent, self.accent_h = ACCENTS.get(code, ACCENTS["blue"])
        for w, kind in self.accent_widgets:
            if kind == "seg":
                w.configure(selected_color=self.accent, selected_hover_color=self.accent_h)
            elif kind == "switch":
                w.configure(progress_color=self.accent)
            elif kind == "slider":
                w.configure(
                    progress_color=self.accent, button_color=self.accent, button_hover_color=self.accent_h
                )
            elif kind == "btn":
                w.configure(fg_color=self.accent, hover_color=self.accent_h)
            elif kind == "bar":
                w.configure(progress_color=self.accent)
            elif kind == "text":
                w.configure(text_color=self.accent)
        for c, b in self.swatches.items():
            b.configure(border_width=3 if c == code else 0)
        self._refresh_nav()
        for b in self.banners:
            b.redraw()
        self._last_phase = None
        self._refresh_state()

    # ---- Oyun ön ayarları
    def _apply_preset(self, key):
        p = PRESETS[key]
        for e in (self.e_hours, self.e_minutes, self.e_seconds):
            self._set_entry(e, 0)
        self._set_entry(self.e_millis, p["ms"])
        self._set_entry(self.e_hold, p["hold"])
        self.s_jitter.set(p["jitter"])
        self._on_jitter(p["jitter"])
        self._set_entry(self.e_pj, p["pj"])
        mode = p["mode"]
        if mode in ("window", "background") and not IS_WIN:
            mode = "fixed"
        self.pos_mode.set_code(mode)
        self._on_mode(mode)
        if mode == "window" and not self.target_hwnd:
            self._set_hint("hint.preset_target")
            self._show_page("target")
        else:
            self._set_hint("hint.preset")

    # ---- Başlat / durdur
    def _toggle(self):
        if self.recording:
            return
        if self.engine.active:
            self.engine.stop()
        else:
            self._start()

    def _start(self):
        if self.engine.active or self.recording:
            return
        self._set_hint("")
        cfg = self._build_cfg()
        if cfg is None:
            return
        self.engine.start(cfg)
        key = self.hotkey.upper()
        if cfg["mode"] == "background":
            self._set_hint("hint.bg_on", key=key)
        elif cfg["mode"] == "window":
            self._set_hint("hint.window_on", key=key)
        self._refresh_state()

    def _test_click(self):
        """Seçili yöntemle 3 deneme tıklaması gönderir: hedefte çalışıyor mu hızlıca gör."""
        if self.engine.active or self.recording:
            return
        cfg = self._build_cfg()
        if cfg is None:
            return
        cfg.update(
            repeat=3, interval=0.4, jitter=0.0, time_limit=0.0, delay=0.0, points=[],
            hold=min(self._num(self.e_hold) / 1000.0, 0.3),
        )
        self.engine.start(cfg)
        self._set_hint("hint.test")
        self._refresh_state()

    def _build_cfg(self):
        self._sync_points()
        h = self._num(self.e_hours)
        m = self._num(self.e_minutes)
        s = self._num(self.e_seconds)
        ms = self._num(self.e_millis)
        interval = h * 3600 + m * 60 + s + ms / 1000.0
        if interval < 0.001:
            interval = 0.001
            self._set_hint("hint.min_interval")

        repeat = 0
        if self.seg_repeat.code() == "count":
            repeat = int(self._num(self.e_repeat, default=0))

        mode = self.pos_mode.code()
        use_points = bool(self.sw_points.get())
        if use_points and not self.points:
            self._set_hint("hint.need_points")
            return None
        if use_points and mode == "cursor":
            mode = "fixed"
            self.pos_mode.set_code("fixed")
            self._on_mode("fixed")
        if mode in ("window", "background"):
            if not IS_WIN:
                self._set_hint("hint.win_only")
                return None
            if not self.target_hwnd:
                self._set_hint("hint.need_target")
                return None

        hold = self._num(self.e_hold) / 1000.0
        hold = min(hold, interval * 0.8)

        steps = []
        if use_points:
            for p in self.points:
                steps.append(
                    {
                        "x": p["x"],
                        "y": p["y"],
                        "button": p.get("button"),
                        "wait": None if p.get("wait") is None else p["wait"] / 1000.0,
                    }
                )

        return {
            "mode": mode,
            "interval": interval,
            "jitter": self.s_jitter.get() / 1000.0,
            "hold": hold,
            "pos_jitter": int(self._num(self.e_pj, default=0)),
            "button_code": self.seg_button.code(),
            "count": COUNTS[self.seg_type.code()],
            "repeat": repeat,
            "time_limit": self._num(self.e_timelimit) * 60.0,
            "pos": (int(self._num(self.e_x)), int(self._num(self.e_y))),
            "hwnd": self.target_hwnd,
            "top": self.target_top,
            "on_inactive": self.seg_inactive.code(),
            "spoof": bool(self.sw_spoof.get()),
            "points": steps,
            "delay": self._num(self.e_delay),
            "failsafe": bool(self.sw_failsafe.get()),
        }

    # ---- Konum / pencere seçme
    def _pick(self):
        mode = self.pos_mode.code()
        if mode == "cursor":
            return
        winlike = mode in ("window", "background")
        if winlike and not IS_WIN:
            self._set_hint("hint.win_only")
            return
        self.b_pick.configure(text=self.t("target.picking"), state="disabled")
        self._set_hint("hint.pick_window" if winlike else "hint.pick_pos")

        def on_click(x, y, button, pressed):
            if pressed:
                if winlike:
                    self.events.put(("pickwin", window_from_screen_point(x, y)))
                else:
                    self.events.put(("pos", int(x), int(y)))
                return False

        listener = mouse.Listener(on_click=on_click)
        listener.daemon = True
        listener.start()

    def _inside_self(self, x, y):
        try:
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            return x0 <= x <= x0 + self.winfo_width() and y0 <= y <= y0 + self.winfo_height()
        except Exception:
            return False

    def _point_from_screen(self, x, y):
        """Ekran noktasını, seçili yönteme uygun nokta koordinatına çevirir."""
        mode = self.pos_mode.code()
        if mode in ("window", "background"):
            if not IS_WIN:
                return None
            if not self.target_hwnd:
                info = window_from_screen_point(x, y)
                if not info or info[3].startswith(APP_NAME):
                    return None
                self.target_hwnd, cx, cy, self.target_title, self.target_top = info
                self._update_target_label()
                return cx, cy
            return screen_to_client(self.target_hwnd, x, y)
        return int(x), int(y)

    # ---- Nokta dizisi
    def _sync_points(self):
        """Satırlardaki bekleme kutularını nokta listesine yazar."""
        for i, e in enumerate(self.point_entries):
            if i >= len(self.points):
                break
            text = e.get().strip()
            try:
                self.points[i]["wait"] = max(0, int(float(text))) if text else None
            except ValueError:
                self.points[i]["wait"] = None

    def _rebuild_points(self):
        for w in self.points_frame.winfo_children():
            w.destroy()
        self.point_entries = []
        if not self.points:
            ctk.CTkLabel(
                self.points_frame, text=self.t("seq.empty"), font=self.f_small, text_color=MUTED, anchor="w",
                justify="left", wraplength=540,
            ).grid(row=0, column=0, sticky="w")
            return
        for i, p in enumerate(self.points):
            row = ctk.CTkFrame(self.points_frame, fg_color=CARD_ALT, corner_radius=10)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=str(i + 1), width=30, font=self.f_h2, text_color=self.accent).grid(
                row=0, column=0, padx=(10, 4), pady=8
            )
            ctk.CTkLabel(
                row,
                text=f"X {p['x']}   Y {p['y']}   ·   {self.t('btn.' + p['button'])}",
                font=self.f_body,
                text_color=TEXT,
                anchor="w",
            ).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text=self.t("seq.wait"), font=self.f_small, text_color=MUTED).grid(
                row=0, column=2, padx=(8, 6)
            )
            e = ctk.CTkEntry(
                row, width=72, height=28, font=self.f_small, justify="center", fg_color=CARD,
                border_color=BORDER, text_color=TEXT, placeholder_text=self.t("seq.auto"),
            )
            if p.get("wait") is not None:
                e.insert(0, str(p["wait"]))
            e.grid(row=0, column=3, padx=(0, 6))
            self.point_entries.append(e)
            ctk.CTkButton(
                row, text="✕", width=30, height=28, corner_radius=8, fg_color=CARD, hover_color=DANGER_H,
                text_color=TEXT, font=self.f_small, command=lambda i=i: self._del_point(i),
            ).grid(row=0, column=4, padx=(0, 8))

    def _del_point(self, i):
        self._sync_points()
        if 0 <= i < len(self.points):
            del self.points[i]
        self._rebuild_points()

    def _clear_points(self):
        self.points = []
        self._rebuild_points()

    def _add_point(self):
        if self.recording:
            return
        if len(self.points) >= MAX_POINTS:
            self._set_hint("hint.max_points", n=MAX_POINTS)
            return
        mode = self.pos_mode.code()
        if mode in ("window", "background") and not IS_WIN:
            self._set_hint("hint.win_only")
            return
        self.b_add.configure(text=self.t("target.picking"), state="disabled")
        self._set_hint("hint.add_point")

        def on_click(x, y, button, pressed):
            if pressed:
                self.events.put(("addpt", int(x), int(y), BTN_CODE.get(button, "left")))
                return False

        listener = mouse.Listener(on_click=on_click)
        listener.daemon = True
        listener.start()

    def _toggle_record(self):
        if self.engine.active:
            return
        if not self.recording:
            mode = self.pos_mode.code()
            if mode in ("window", "background") and not IS_WIN:
                self._set_hint("hint.win_only")
                return
            if mode == "cursor":
                self.pos_mode.set_code("fixed")
                self._on_mode("fixed")
            self.points = []
            self._rebuild_points()
            self.recording = True
            self._rec_t = None

            def on_click(x, y, button, pressed):
                if pressed and button in BTN_CODE:
                    self.events.put(("rec", time.perf_counter(), int(x), int(y), BTN_CODE[button]))

            self._rec_listener = mouse.Listener(on_click=on_click)
            self._rec_listener.daemon = True
            self._rec_listener.start()
            self.b_record.configure(text=self.t("seq.stop"), fg_color=REC, hover_color=DANGER_H)
            self._set_hint("hint.rec_on")
        else:
            self.recording = False
            try:
                if self._rec_listener:
                    self._rec_listener.stop()
            except Exception:
                pass
            self._rec_listener = None
            if self.points:
                self.points[-1]["wait"] = None
                self.sw_points.select()
            self._rebuild_points()
            self.b_record.configure(text=self.t("seq.record"), fg_color=CARD_ALT, hover_color=BORDER)
            self._set_hint("hint.rec_off", n=len(self.points))

    # ---- Kısayol değiştirme
    def _capture_hotkey(self):
        self.capturing_hotkey = True
        self.l_hotkey.configure(text=self.t("dock.capturing"))
        self._set_hint("hint.hotkey_prompt")

    # ---- Profiller
    def _refresh_profiles(self, select=None):
        names = sorted(self.profiles.keys())
        self.om_profile.configure(values=names or [self.t("profile.none")])
        self.om_profile.set(select if select in names else (names[0] if names else self.t("profile.none")))

    def _save_profile(self):
        name = self.e_profile.get().strip()
        if not name:
            self._set_hint("hint.profile_name")
            return
        self.profiles[name] = self._normalize({**DEFAULTS, **self._get_settings()})
        self._refresh_profiles(select=name)
        self.e_profile.delete(0, "end")
        self._set_hint("hint.profile_saved", name=name)
        self._save_config()

    def _load_profile(self):
        name = self.om_profile.get()
        if name in self.profiles:
            prof = dict(self.profiles[name])
            prof["lang"] = self.lang  # profil dili değiştirmesin
            self._apply_settings(self._normalize({**DEFAULTS, **prof}))
            self._set_hint("hint.profile_loaded", name=name)

    def _delete_profile(self):
        name = self.om_profile.get()
        if name in self.profiles:
            del self.profiles[name]
            self._refresh_profiles()
            self._set_hint("hint.profile_deleted", name=name)
            self._save_config()

    # ------------------------------------------------------------------
    # Global kısayol dinleyicisi (ayrı iş parçacığı -> kuyruk ile arayüze)
    # ------------------------------------------------------------------
    def _start_listeners(self):
        self.kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.kb_listener.daemon = True
        self.kb_listener.start()

    def _on_press(self, key):
        try:
            name = key_to_str(key)
            now = time.perf_counter()
            self.last_key, self.last_key_t = name, now
            gap, self._last_press = now - self._last_press, now
            if self.capturing_hotkey:
                self.capturing_hotkey = False
                self.events.put(("hotkey", name))
                return
            if name == REC_HOTKEY and name != self.hotkey:
                self.events.put(("rec_toggle",))
                return
            if name != self.hotkey:
                return
            # tuş tekrarını ele: bırakma olayı kaçsa bile yeni basış (>0.6 sn ara) kabul edilir
            if self._key_down and gap < 0.6:
                return
            self._key_down = True
            if self.hotkey_mode == "hold":
                self.events.put(("start",))
            elif self.engine.active:
                self.engine.stop()  # durdurma arayüze bağlı kalmasın: doğrudan bu iş parçacığından
            else:
                self.events.put(("toggle",))
        except Exception:
            log_error(traceback.format_exc())  # dinleyici iş parçacığı hata yüzünden ölmesin

    def _on_release(self, key):
        try:
            if key_to_str(key) == self.hotkey:
                self._key_down = False
                if self.hotkey_mode == "hold":
                    self.engine.stop()
                    self.events.put(("stop",))
        except Exception:
            log_error(traceback.format_exc())

    # ------------------------------------------------------------------
    # Ana döngü: olayları işle + arayüzü güncelle
    # ------------------------------------------------------------------
    def _poll(self):
        """Ana döngü. Tek bir hata yüzünden asla durmaz (eskiden kısayolun donmasının olası nedeni buydu)."""
        try:
            while True:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle(ev)
                except Exception:
                    self._report_error()
            self._update_stats()
            self._refresh_state()
            if self._tick % 10 == 0:
                self._update_diag()
            if self._tick % 16 == 0:
                self._watch_listener()
        except Exception:
            self._report_error()
        finally:
            if not self._quitting:
                self.after(60, self._poll)

    def _report_error(self):
        text = traceback.format_exc()
        log_error(text)
        now = time.time()
        if now - self._err_t > 3:  # arayüzü hint ile boğma
            self._err_t = now
            try:
                self._set_hint("hint.internal_error", path=str(LOG_PATH))
            except Exception:
                pass

    def report_callback_exception(self, exc, val, tb):
        """Tk düğme/olay hataları: sessizce kaybolmasın, kayda yazılsın."""
        log_error("".join(traceback.format_exception(exc, val, tb)))
        self._err_t = 0.0
        try:
            self._set_hint("hint.internal_error", path=str(LOG_PATH))
        except Exception:
            pass

    def _watch_listener(self):
        """Klavye dinleyicisi (kısayol) ölmüşse yeniden başlatır."""
        try:
            if not self.kb_listener.is_alive():
                log_error("kısayol dinleyicisi durmuştu, yeniden başlatıldı")
                self._start_listeners()
        except Exception:
            self._report_error()

    def _update_diag(self):
        if self.current_page != "settings":
            return
        if self.last_key_t:
            ago = int(time.perf_counter() - self.last_key_t)
            self.l_diag_key.configure(
                text=self.t("diag.lastkey", key=self.last_key.upper(), ago=ago), text_color=TEXT
            )
        else:
            self.l_diag_key.configure(text=self.t("diag.nokey"), text_color=MUTED)
        admin = is_admin()
        self.l_diag_self.configure(text=self.t("diag.self_admin" if admin else "diag.self_user"))
        el = self.target_elevated if self.target_hwnd else None
        key = "diag.target_admin" if el else ("diag.target_user" if el is False else "diag.target_unknown")
        self.l_diag_target.configure(text=self.t(key), text_color=WARN if (el and not admin) else MUTED)

    def _relaunch_admin(self):
        if not IS_WIN:
            return
        self._save_config()
        if relaunch_as_admin():
            self._quit()
        else:
            self._set_hint("hint.relaunch_failed")

    def _handle(self, ev):
        kind = ev[0]
        if kind == "toggle":
            self._toggle()
        elif kind == "start":
            self._start()
        elif kind == "stop":
            self.engine.stop()
        elif kind == "rec_toggle":
            self._toggle_record()
        elif kind == "hotkey":
            self.hotkey = ev[1]
            self.l_hotkey.configure(text=self.hotkey.upper())
            self._set_hint("hint.hotkey_set", key=self.hotkey.upper())
            self._last_phase = None
            self._refresh_state()
        elif kind == "pos":
            self._set_entry(self.e_x, ev[1])
            self._set_entry(self.e_y, ev[2])
            self.pos_mode.set_code("fixed")
            self._on_mode("fixed")
            self._set_hint("hint.pos_set", x=ev[1], y=ev[2])
        elif kind == "pickwin":
            info = ev[1]
            self._on_mode()
            if not info:
                self._set_hint("hint.no_window")
            elif info[3].startswith(APP_NAME):
                self._set_hint("hint.own_window")
            else:
                self.target_hwnd, cx, cy, self.target_title, self.target_top = info
                self.target_title = self.target_title or "?"
                self._set_entry(self.e_x, cx)
                self._set_entry(self.e_y, cy)
                self.target_elevated = window_elevated(self.target_hwnd) if IS_WIN else None
                self._update_target_label()
                if self.target_elevated and not is_admin():
                    self._set_hint("hint.need_admin")
                else:
                    self._set_hint("hint.window_set", x=cx, y=cy)
        elif kind == "addpt":
            self.b_add.configure(text=self.t("seq.add"), state="normal")
            if self._inside_self(ev[1], ev[2]):
                return
            pt = self._point_from_screen(ev[1], ev[2])
            if pt is None:
                self._set_hint("hint.no_window")
                return
            self._sync_points()
            self.points.append({"x": pt[0], "y": pt[1], "button": ev[3], "wait": None})
            self._rebuild_points()
            self._set_hint("hint.point_added", x=pt[0], y=pt[1])
        elif kind == "rec":
            if not self.recording or self._inside_self(ev[2], ev[3]):
                return
            if len(self.points) >= MAX_POINTS:
                return
            pt = self._point_from_screen(ev[2], ev[3])
            if pt is None:
                return
            if self.points and self._rec_t is not None:
                self.points[-1]["wait"] = int(round((ev[1] - self._rec_t) * 1000))
            self._rec_t = ev[1]
            self.points.append({"x": pt[0], "y": pt[1], "button": ev[4], "wait": None})
            self._rebuild_points()
        elif kind == "tray_show":
            self._show_from_tray()
        elif kind == "tray_quit":
            self._quit()
        elif kind == "finished":
            messages = {
                "done": "hint.done",
                "time": "hint.time",
                "failsafe": "hint.failsafe",
                "window_closed": "hint.window_closed",
            }
            self._set_hint(messages.get(ev[1], ""))
            self._last_phase = None
            self._refresh_state()

    def _refresh_state(self):
        if self.recording:
            phase = "recording"
        else:
            phase = self.engine.phase if self.engine.active else "idle"
        if phase == self._last_phase:
            return
        self._last_phase = phase
        key, fg, bg = {
            "running": ("state.running", "#052e16", OK),
            "paused": ("state.paused", "#451a03", WARN),
            "waiting": ("state.waiting", "#451a03", WARN),
            "recording": ("state.recording", "#ffffff", REC),
            "idle": ("state.idle", "#cbd5e1", CARD_ALT),
        }[phase]
        self.pill.configure(text=self.t(key), text_color=fg, fg_color=bg)
        glyph, title = {
            "running": ("■", "dock.stop"),
            "paused": ("■", "dock.stop"),
            "waiting": ("■", "dock.cancel"),
            "recording": ("●", "dock.rec"),
            "idle": ("▶", "dock.start"),
        }[phase]
        self.orb.set_state(phase, self.accent, glyph, self.t(title), self.hotkey.upper())

    def _anim(self):
        """Orb animasyonu (~25 kare/sn). Hata olsa bile döngü ölmez."""
        try:
            eng = self.engine
            self.orb.set_cps(eng.cps() if eng.active else 0)
            if self._last_phase in ("running", "waiting", "paused", "recording") or self.orb.dirty:
                self.orb.render(time.time())
        except Exception:
            self._report_error()
        finally:
            if not self._quitting:
                self.after(40, self._anim)

    def _update_stats(self):
        eng = self.engine
        self.st_clicks.configure(text=f"{eng.clicks:,}".replace(",", "."))
        cps = eng.cps() if eng.active else 0
        self.st_cps.configure(text=str(cps))
        if eng.active and eng.phase in ("running", "paused"):
            elapsed = time.perf_counter() - eng.started_at
        else:
            elapsed = eng.last_elapsed
        mm, ss = divmod(int(elapsed), 60)
        hh, mm = divmod(mm, 60)
        self.st_time.configure(text=f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}")
        self.bar.set(min(eng.clicks / eng.target, 1.0) if eng.target else 0)
        self._tick += 1
        if self._tick % 4 == 0:
            self.cps_hist.append(cps)
            self._draw_spark()

    def _draw_spark(self):
        c = self.spark
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        data = list(self.cps_hist)
        top = max(10, max(data))
        step = (w - 2) / (HIST - 1)
        pts = []
        for i, v in enumerate(data):
            pts.append((1 + i * step, h - 4 - (v / top) * (h - 12)))
        flat = [coord for p in pts for coord in p]
        c.create_polygon([1, h] + flat + [pts[-1][0], h], fill=blend(CARD, self.accent, 0.22), outline="")
        c.create_line(flat, fill=self.accent, width=2, smooth=True)
        c.create_text(w - 4, 8, text=f"max {top}", fill=MUTED, anchor="e", font=("Segoe UI", 8))

    # ------------------------------------------------------------------
    # Sistem tepsisi / kapanış
    # ------------------------------------------------------------------
    def _on_close(self):
        if HAS_TRAY and self.sw_tray is not None and self.sw_tray.get() and not self._quitting:
            self._hide_to_tray()
        else:
            self._quit()

    def _hide_to_tray(self):
        try:
            image = Image.open(resource_path("novaclick.ico")).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem(self.t("tray.show"), lambda: self.events.put(("tray_show",)), default=True),
                pystray.MenuItem(self.t("tray.toggle"), lambda: self.events.put(("toggle",))),
                pystray.MenuItem(self.t("tray.quit"), lambda: self.events.put(("tray_quit",))),
            )
            self.tray_icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
            self.tray_icon.run_detached()
            self.withdraw()
        except Exception:
            self._quit()

    def _show_from_tray(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.deiconify()
        self.lift()

    def _quit(self):
        self._quitting = True
        self._save_config()
        self.engine.stop()
        for lst in (getattr(self, "kb_listener", None), self._rec_listener):
            try:
                if lst:
                    lst.stop()
            except Exception:
                pass
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        if IS_WIN:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
