"""
NovaClick - Gelişmiş Otomatik Tıklayıcı
=======================================
Claude (Anthropic) ile birlikte geliştirilmiştir. Lisans: MIT

Gereksinimler:  pip install customtkinter pynput

Özellikler
- Saat / dakika / saniye / milisaniye hassasiyetinde aralık + hızlı CPS ön ayarları
- Rastgele sapma (jitter) ile insan benzeri tıklama aralığı
- Sol / sağ / orta tuş, tek / çift / üçlü tıklama
- Sonsuz ya da belirli sayıda tekrar
- İmleç konumunda ya da sabit koordinatta tıklama (ekrandan konum seçme)
- ARKA PLAN MODU (Windows): seçtiğin pencerenin belirli noktasına, fareni ve
  klavyeni hiç kullanmadan tıklar. Alt-Tab yapıp PC'yi normal kullanabilirsin.
- Global kısayol (varsayılan F6): Aç/Kapa veya Basılı Tut modu, kısayol değiştirilebilir
- Başlangıç gecikmesi, acil durdurma (fareyi sol üst köşeye götür)
- Canlı istatistik: toplam tıklama, anlık CPS, süre, ilerleme çubuğu
- Profil kaydet / yükle / sil, tema vurgu rengi, her zaman üstte
- Ayarlar kapanışta otomatik kaydedilir (~/.novaclick.json)
"""

import collections
import json
import queue
import random
import sys
import threading
import time
from pathlib import Path

import customtkinter as ctk
from pynput import keyboard, mouse

# --------------------------------------------------------------------------
# Windows: yüksek DPI + 1 ms zamanlayıcı çözünürlüğü (hızlı tıklama için şart)
# --------------------------------------------------------------------------
if sys.platform == "win32":
    import ctypes

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

IS_WIN = sys.platform == "win32"

if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL

    WM_MOUSEMOVE = 0x0200
    # düğme adı -> (basma, bırakma, çift tık, MK_ bayrağı)
    BG_MESSAGES = {
        "Sol": (0x0201, 0x0202, 0x0203, 0x0001),
        "Sağ": (0x0204, 0x0205, 0x0206, 0x0002),
        "Orta": (0x0207, 0x0208, 0x0209, 0x0010),
    }

    def _window_title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def window_from_screen_point(x, y):
        """Ekran noktasındaki pencereyi bulur: (hwnd, client_x, client_y, başlık)."""
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return None
        pt = wintypes.POINT(int(x), int(y))
        user32.ScreenToClient(hwnd, ctypes.byref(pt))
        top = user32.GetAncestor(hwnd, 2)  # GA_ROOT: en üst pencere (başlık için)
        return int(hwnd), pt.x, pt.y, _window_title(top or hwnd)

    def window_exists(hwnd):
        return bool(user32.IsWindow(hwnd))

    def send_background_click(hwnd, cpos, button_name, count):
        """Fareyi/odağı hiç kullanmadan pencereye tıklama mesajı gönderir."""
        down, up, dbl, mk = BG_MESSAGES[button_name]
        lparam = ((cpos[1] & 0xFFFF) << 16) | (cpos[0] & 0xFFFF)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        for i in range(count):
            user32.PostMessageW(hwnd, dbl if i == 1 else down, mk, lparam)
            user32.PostMessageW(hwnd, up, 0, lparam)


def resource_path(name):
    """Hem .py olarak hem PyInstaller exe'si olarak dosyayı bulur."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return str(Path(base) / name)


APP_NAME = "NovaClick"
APP_SUB = "Gelişmiş otomatik tıklayıcı"
CONFIG_PATH = Path.home() / ".novaclick.json"

# --------------------------------------------------------------------------
# Tasarım sabitleri
# --------------------------------------------------------------------------
BG = "#0a0e17"
CARD = "#121826"
CARD_ALT = "#1a2234"
BORDER = "#222c42"
TEXT = "#e6eaf5"
MUTED = "#7f8aa6"
OK = "#22c55e"
WARN = "#f59e0b"
DANGER = "#ef4444"
DANGER_H = "#dc2626"

ACCENTS = {
    "Mavi": ("#3b82f6", "#2563eb"),
    "Mor": ("#8b5cf6", "#7c3aed"),
    "Yeşil": ("#10b981", "#059669"),
    "Turuncu": ("#f97316", "#ea580c"),
    "Pembe": ("#ec4899", "#db2777"),
}

DEFAULTS = {
    "hours": "0",
    "minutes": "0",
    "seconds": "0",
    "millis": "100",
    "jitter": 0,
    "button": "Sol",
    "click_type": "Tek",
    "repeat_mode": "Sonsuz",
    "repeat_count": "100",
    "position_mode": "İmleç",
    "x": "0",
    "y": "0",
    "start_delay": "0",
    "failsafe": True,
    "topmost": False,
    "hotkey": "f6",
    "hotkey_mode": "Aç/Kapa",
    "accent": "Mavi",
}

BUTTONS = {
    "Sol": mouse.Button.left,
    "Sağ": mouse.Button.right,
    "Orta": mouse.Button.middle,
}
COUNTS = {"Tek": 1, "Çift": 2, "Üçlü": 3}


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
# Tıklama motoru (ayrı iş parçacığında çalışır)
# --------------------------------------------------------------------------
class ClickEngine:
    def __init__(self, events: queue.Queue):
        self.mouse = mouse.Controller()
        self.events = events
        self._stop = threading.Event()
        self._thread = None
        self.phase = "idle"  # idle | waiting | running
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

    def _run(self, cfg):
        reason = "manual"
        try:
            if cfg["delay"] > 0:
                if self._stop.wait(cfg["delay"]):
                    return
                self.phase = "running"
                self.started_at = time.perf_counter()

            btn, count = cfg["button"], cfg["count"]
            base, jitter = cfg["interval"], cfg["jitter"]
            next_t = time.perf_counter()

            while not self._stop.is_set():
                if cfg["bg"]:
                    # Arka plan modu: gerçek fare kullanılmaz, pencereye mesaj gider
                    if not window_exists(cfg["hwnd"]):
                        reason = "window_closed"
                        break
                    send_background_click(cfg["hwnd"], cfg["pos"], cfg["button_name"], count)
                else:
                    # Acil durdurma: imleç ekranın sol üst köşesindeyse dur
                    if cfg["failsafe"]:
                        x, y = self.mouse.position
                        if x <= 0 and y <= 0:
                            reason = "failsafe"
                            break

                    if cfg["fixed"]:
                        self.mouse.position = cfg["pos"]

                    self.mouse.click(btn, count)
                self.clicks += 1
                self.stamps.append(time.perf_counter())

                if self.target and self.clicks >= self.target:
                    reason = "done"
                    break

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
            if self.phase == "running":
                self.last_elapsed = time.perf_counter() - self.started_at
            self.phase = "idle"
            self.events.put(("finished", reason))


# --------------------------------------------------------------------------
# Arayüz
# --------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")

        self.title(f"{APP_NAME} — {APP_SUB}")
        self._set_icon()
        # customtkinter kendi ikonunu geç ekleyebiliyor, o yüzden bir kez daha uygula
        self.after(300, self._set_icon)
        self.geometry("1080x820")
        self.minsize(1000, 700)
        self.configure(fg_color=BG)

        self.events = queue.Queue()
        self.engine = ClickEngine(self.events)

        self.config_data = self._load_config()
        settings = {**DEFAULTS, **self.config_data.get("last", {})}
        self.profiles = dict(self.config_data.get("profiles", {}))

        self.accent_widgets = []
        self.accent, self.accent_h = ACCENTS.get(settings["accent"], ACCENTS["Mavi"])
        self.hotkey = settings["hotkey"]
        self.hotkey_mode = settings["hotkey_mode"]
        self.capturing_hotkey = False
        self._key_down = False
        self._last_phase = None
        self.bg_hwnd = 0
        self.bg_title = ""

        self.f_title = ctk.CTkFont(family="Segoe UI", size=28, weight="bold")
        self.f_h2 = ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        self.f_body = ctk.CTkFont(family="Segoe UI", size=13)
        self.f_small = ctk.CTkFont(family="Segoe UI", size=12)
        self.f_big = ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        self.f_num = ctk.CTkFont(family="Segoe UI", size=28, weight="bold")

        self._build_ui()
        self._apply_settings(settings)
        self._start_listeners()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._poll)

    def _set_icon(self):
        ico = resource_path("novaclick.ico")
        if IS_WIN and Path(ico).exists():
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

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
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Yardımcı bileşen üreticileri
    # ------------------------------------------------------------------
    def _acc(self, widget, kind):
        self.accent_widgets.append((widget, kind))
        return widget

    def _card(self, parent, title, row, subtitle=None):
        outer = ctk.CTkFrame(
            parent, fg_color=CARD, corner_radius=18, border_width=1, border_color=BORDER
        )
        outer.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(outer, text=title, font=self.f_h2, text_color=TEXT).grid(
            row=0, column=0, sticky="w", padx=22, pady=(18, 0 if subtitle else 10)
        )
        if subtitle:
            ctk.CTkLabel(
                outer, text=subtitle, font=self.f_small, text_color=MUTED
            ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 10))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 20))
        return body

    def _entry(self, parent, width=80, height=40, font=None, center=True):
        return ctk.CTkEntry(
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

    def _segmented(self, parent, values, command=None):
        seg = ctk.CTkSegmentedButton(
            parent,
            values=values,
            command=command,
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
        return self._acc(seg, "seg")

    def _switch(self, parent, text, command=None):
        sw = ctk.CTkSwitch(
            parent,
            text=text,
            command=command,
            font=self.f_body,
            text_color=TEXT,
            fg_color=BORDER,
            progress_color=self.accent,
            button_color="#ffffff",
            button_hover_color="#e5e7eb",
        )
        return self._acc(sw, "switch")

    def _label(self, parent, text, muted=True, font=None):
        return ctk.CTkLabel(
            parent, text=text, font=font or self.f_body, text_color=MUTED if muted else TEXT
        )

    def _small_button(self, parent, text, command, width=90):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=32,
            font=self.f_small,
            corner_radius=9,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
        )

    # ------------------------------------------------------------------
    # Arayüz kurulumu
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- Üst şerit
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 8))
        header.grid_columnconfigure(1, weight=1)

        logo = ctk.CTkLabel(
            header, text="⚡", font=ctk.CTkFont(size=30), text_color=self.accent
        )
        self._acc(logo, "text")
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(header, text=APP_NAME, font=self.f_title, text_color=TEXT).grid(
            row=0, column=1, sticky="w"
        )
        ctk.CTkLabel(header, text=APP_SUB, font=self.f_small, text_color=MUTED).grid(
            row=1, column=1, sticky="w"
        )
        self.pill = ctk.CTkLabel(
            header,
            text="●  HAZIR",
            font=self.f_small,
            text_color="#cbd5e1",
            fg_color=CARD_ALT,
            corner_radius=20,
            width=150,
            height=34,
        )
        self.pill.grid(row=0, column=2, rowspan=2, sticky="e")

        # ---- Gövde (kaydırılabilir, küçük ekranlar için)
        body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=(18, 10), pady=(4, 0))
        body.grid_columnconfigure(0, weight=3, uniform="col")
        body.grid_columnconfigure(1, weight=2, uniform="col")

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(10, 8))
        left.grid_columnconfigure(0, weight=1)
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="new", padx=(8, 10))
        right.grid_columnconfigure(0, weight=1)

        self._build_interval_card(left, 0)
        self._build_click_card(left, 1)
        self._build_position_card(left, 2)
        self._build_control_card(right, 0)
        self._build_stats_card(right, 1)
        self._build_advanced_card(right, 2)
        self._build_profile_card(right, 3)

        # ---- Alt bilgi çubuğu
        self.hint = ctk.CTkLabel(
            self,
            text="",
            font=self.f_small,
            text_color=MUTED,
            anchor="w",
        )
        self.hint.grid(row=2, column=0, sticky="ew", padx=32, pady=(6, 14))

    # ---- Aralık kartı
    def _build_interval_card(self, parent, row):
        body = self._card(
            parent, "Tıklama aralığı", row, "İki tıklama arasındaki süre (toplamı alınır)"
        )
        for c in range(4):
            body.grid_columnconfigure(c, weight=1, uniform="iv")

        self.e_hours = self._entry(body, height=52, font=self.f_big)
        self.e_minutes = self._entry(body, height=52, font=self.f_big)
        self.e_seconds = self._entry(body, height=52, font=self.f_big)
        self.e_millis = self._entry(body, height=52, font=self.f_big)
        for i, (e, name) in enumerate(
            [
                (self.e_hours, "Saat"),
                (self.e_minutes, "Dakika"),
                (self.e_seconds, "Saniye"),
                (self.e_millis, "Milisaniye"),
            ]
        ):
            e.grid(row=0, column=i, padx=5, sticky="ew")
            self._label(body, name).grid(row=1, column=i, pady=(4, 0))

        # Hızlı CPS ön ayarları
        chips = ctk.CTkFrame(body, fg_color="transparent")
        chips.grid(row=2, column=0, columnspan=4, sticky="w", pady=(16, 0))
        self._label(chips, "Hızlı ayar:").pack(side="left", padx=(5, 8))
        for cps in (1, 5, 10, 20, 50, 100):
            self._small_button(
                chips, f"{cps} CPS", lambda c=cps: self._preset_cps(c), width=64
            ).pack(side="left", padx=3)

        # Rastgele sapma
        jit = ctk.CTkFrame(body, fg_color="transparent")
        jit.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        jit.grid_columnconfigure(1, weight=1)
        self._label(jit, "Rastgele sapma", muted=False).grid(row=0, column=0, padx=(5, 12))
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
        self.l_jitter = self._label(jit, "Kapalı", font=self.f_small)
        self.l_jitter.grid(row=0, column=2, padx=(12, 5))

    # ---- Tıklama seçenekleri kartı
    def _build_click_card(self, parent, row):
        body = self._card(parent, "Tıklama ayarları", row)
        body.grid_columnconfigure(1, weight=1)

        self._label(body, "Fare tuşu", muted=False).grid(row=0, column=0, sticky="w", pady=6)
        self.seg_button = self._segmented(body, list(BUTTONS.keys()))
        self.seg_button.grid(row=0, column=1, sticky="e", pady=6)

        self._label(body, "Tıklama türü", muted=False).grid(row=1, column=0, sticky="w", pady=6)
        self.seg_type = self._segmented(body, list(COUNTS.keys()))
        self.seg_type.grid(row=1, column=1, sticky="e", pady=6)

        self._label(body, "Tekrar", muted=False).grid(row=2, column=0, sticky="w", pady=6)
        rep = ctk.CTkFrame(body, fg_color="transparent")
        rep.grid(row=2, column=1, sticky="e", pady=6)
        self.e_repeat = self._entry(rep, width=70, height=36)
        self.seg_repeat = self._segmented(rep, ["Sonsuz", "Sayı"], command=self._on_repeat_mode)
        self.seg_repeat.pack(side="left")
        self.e_repeat.pack(side="left", padx=(10, 0))

    # ---- Konum kartı
    def _build_position_card(self, parent, row):
        body = self._card(parent, "Tıklama konumu", row)
        body.grid_columnconfigure(1, weight=1)

        self.seg_pos = self._segmented(body, ["İmleç", "Sabit", "Arka plan"], command=self._on_pos_mode)
        self.seg_pos.grid(row=0, column=0, sticky="w", pady=(0, 12))

        coords = ctk.CTkFrame(body, fg_color="transparent")
        coords.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._label(coords, "X").pack(side="left", padx=(2, 6))
        self.e_x = self._entry(coords, width=80, height=36)
        self.e_x.pack(side="left")
        self._label(coords, "Y").pack(side="left", padx=(16, 6))
        self.e_y = self._entry(coords, width=80, height=36)
        self.e_y.pack(side="left")
        self.b_pick = self._acc(
            ctk.CTkButton(
                coords,
                text="🎯  Ekrandan seç",
                command=self._pick_position,
                height=36,
                font=self.f_body,
                corner_radius=10,
                fg_color=self.accent,
                hover_color=self.accent_h,
            ),
            "btn",
        )
        self.b_pick.pack(side="right")

        self.l_bg = self._label(body, "Hedef pencere seçilmedi", font=self.f_small)
        self.l_bg.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # ---- Kontrol kartı
    def _build_control_card(self, parent, row):
        body = self._card(parent, "Kontrol", row)
        body.grid_columnconfigure(0, weight=1)

        self.b_toggle = ctk.CTkButton(
            body,
            text="▶   BAŞLAT",
            command=self._toggle,
            height=64,
            font=self.f_big,
            corner_radius=14,
            fg_color=self.accent,
            hover_color=self.accent_h,
        )
        self.b_toggle.grid(row=0, column=0, sticky="ew")

        hk = ctk.CTkFrame(body, fg_color="transparent")
        hk.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        hk.grid_columnconfigure(1, weight=1)
        self._label(hk, "Kısayol", muted=False).grid(row=0, column=0, sticky="w")
        self.l_hotkey = ctk.CTkLabel(
            hk,
            text="F6",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color=TEXT,
            fg_color=CARD_ALT,
            corner_radius=8,
            width=90,
            height=32,
        )
        self.l_hotkey.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self._small_button(hk, "Değiştir", self._capture_hotkey, width=80).grid(row=0, column=2)

        self._label(body, "Kısayol modu").grid(row=2, column=0, sticky="w", pady=(16, 6))
        self.seg_mode = self._segmented(body, ["Aç/Kapa", "Basılı Tut"], command=self._on_hotkey_mode)
        self.seg_mode.grid(row=3, column=0, sticky="ew")

    # ---- İstatistik kartı
    def _build_stats_card(self, parent, row):
        body = self._card(parent, "Canlı istatistik", row)
        for c in range(3):
            body.grid_columnconfigure(c, weight=1, uniform="st")

        self.st_clicks = ctk.CTkLabel(body, text="0", font=self.f_num, text_color=TEXT)
        self.st_cps = ctk.CTkLabel(body, text="0", font=self.f_num, text_color=TEXT)
        self.st_time = ctk.CTkLabel(body, text="00:00", font=self.f_num, text_color=TEXT)
        for i, (w, name) in enumerate(
            [(self.st_clicks, "Tıklama"), (self.st_cps, "CPS"), (self.st_time, "Süre")]
        ):
            w.grid(row=0, column=i)
            self._label(body, name, font=self.f_small).grid(row=1, column=i)

        self.bar = self._acc(
            ctk.CTkProgressBar(body, height=8, fg_color=CARD_ALT, progress_color=self.accent),
            "bar",
        )
        self.bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        self.bar.set(0)

    # ---- Gelişmiş kart
    def _build_advanced_card(self, parent, row):
        body = self._card(parent, "Gelişmiş", row)
        body.grid_columnconfigure(0, weight=1)

        dl = ctk.CTkFrame(body, fg_color="transparent")
        dl.grid(row=0, column=0, sticky="ew")
        dl.grid_columnconfigure(0, weight=1)
        self._label(dl, "Başlangıç gecikmesi (sn)", muted=False).grid(row=0, column=0, sticky="w")
        self.e_delay = self._entry(dl, width=70, height=34)
        self.e_delay.grid(row=0, column=1)

        self.sw_failsafe = self._switch(body, "Acil durdurma (fareyi sol üst köşeye götür)")
        self.sw_failsafe.grid(row=1, column=0, sticky="w", pady=(14, 0))
        self.sw_top = self._switch(body, "Her zaman üstte", command=self._on_topmost)
        self.sw_top.grid(row=2, column=0, sticky="w", pady=(12, 0))

        ac = ctk.CTkFrame(body, fg_color="transparent")
        ac.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        ac.grid_columnconfigure(0, weight=1)
        self._label(ac, "Vurgu rengi", muted=False).grid(row=0, column=0, sticky="w")
        self.om_accent = ctk.CTkOptionMenu(
            ac,
            values=list(ACCENTS.keys()),
            command=self._on_accent,
            width=110,
            height=32,
            font=self.f_small,
            fg_color=CARD_ALT,
            button_color=BORDER,
            button_hover_color=MUTED,
            dropdown_fg_color=CARD,
            dropdown_hover_color=BORDER,
            text_color=TEXT,
        )
        self.om_accent.grid(row=0, column=1)

    # ---- Profil kartı
    def _build_profile_card(self, parent, row):
        body = self._card(parent, "Profiller", row)
        body.grid_columnconfigure(0, weight=1)

        self.om_profile = ctk.CTkOptionMenu(
            body,
            values=["Profil yok"],
            height=34,
            font=self.f_body,
            fg_color=CARD_ALT,
            button_color=BORDER,
            button_hover_color=MUTED,
            dropdown_fg_color=CARD,
            dropdown_hover_color=BORDER,
            text_color=TEXT,
        )
        self.om_profile.grid(row=0, column=0, sticky="ew")

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        btns.grid_columnconfigure((0, 1), weight=1)
        self._small_button(btns, "Yükle", self._load_profile).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._small_button(btns, "Sil", self._delete_profile).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        save = ctk.CTkFrame(body, fg_color="transparent")
        save.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        save.grid_columnconfigure(0, weight=1)
        self.e_profile = self._entry(save, height=34, center=False)
        self.e_profile.configure(placeholder_text="Yeni profil adı")
        self.e_profile.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._acc(
            ctk.CTkButton(
                save,
                text="Kaydet",
                command=self._save_profile,
                width=80,
                height=34,
                font=self.f_small,
                corner_radius=9,
                fg_color=self.accent,
                hover_color=self.accent_h,
            ),
            "btn",
        ).grid(row=0, column=1)
        self._refresh_profiles()

    # ------------------------------------------------------------------
    # Ayarlar <-> arayüz
    # ------------------------------------------------------------------
    @staticmethod
    def _set_entry(entry, text):
        prev = entry.cget("state")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, str(text))
        entry.configure(state=prev)

    def _get_settings(self):
        return {
            "hours": self.e_hours.get(),
            "minutes": self.e_minutes.get(),
            "seconds": self.e_seconds.get(),
            "millis": self.e_millis.get(),
            "jitter": int(self.s_jitter.get()),
            "button": self.seg_button.get(),
            "click_type": self.seg_type.get(),
            "repeat_mode": self.seg_repeat.get(),
            "repeat_count": self.e_repeat.get(),
            "position_mode": self.seg_pos.get(),
            "x": self.e_x.get(),
            "y": self.e_y.get(),
            "start_delay": self.e_delay.get(),
            "failsafe": bool(self.sw_failsafe.get()),
            "topmost": bool(self.sw_top.get()),
            "hotkey": self.hotkey,
            "hotkey_mode": self.hotkey_mode,
            "accent": self.om_accent.get(),
        }

    def _apply_settings(self, s):
        self._set_entry(self.e_hours, s["hours"])
        self._set_entry(self.e_minutes, s["minutes"])
        self._set_entry(self.e_seconds, s["seconds"])
        self._set_entry(self.e_millis, s["millis"])
        self.s_jitter.set(s["jitter"])
        self._on_jitter(s["jitter"])
        self.seg_button.set(s["button"])
        self.seg_type.set(s["click_type"])
        self.seg_repeat.set(s["repeat_mode"])
        self._set_entry(self.e_repeat, s["repeat_count"])
        self._on_repeat_mode(s["repeat_mode"])
        self.seg_pos.set(s["position_mode"])
        self._set_entry(self.e_x, s["x"])
        self._set_entry(self.e_y, s["y"])
        self._on_pos_mode(s["position_mode"])
        self._set_entry(self.e_delay, s["start_delay"])
        (self.sw_failsafe.select if s["failsafe"] else self.sw_failsafe.deselect)()
        (self.sw_top.select if s["topmost"] else self.sw_top.deselect)()
        self._on_topmost()
        self.hotkey = s["hotkey"]
        self.l_hotkey.configure(text=self.hotkey.upper())
        self.hotkey_mode = s["hotkey_mode"]
        self.seg_mode.set(self.hotkey_mode)
        self.om_accent.set(s["accent"])
        self._on_accent(s["accent"])

    @staticmethod
    def _num(entry, default=0.0, cast=float):
        try:
            return max(cast(entry.get().strip().replace(",", ".")), 0)
        except ValueError:
            return default

    def _build_cfg(self):
        h = self._num(self.e_hours)
        m = self._num(self.e_minutes)
        s = self._num(self.e_seconds)
        ms = self._num(self.e_millis)
        interval = h * 3600 + m * 60 + s + ms / 1000.0
        if interval < 0.001:
            interval = 0.001
            self.hint.configure(text="Aralık en az 1 ms olabilir, 1 ms olarak ayarlandı.")

        repeat = 0
        if self.seg_repeat.get() == "Sayı":
            repeat = int(self._num(self.e_repeat, default=0, cast=float))

        mode = self.seg_pos.get()
        bg = mode == "Arka plan"
        if bg:
            if not IS_WIN:
                self.hint.configure(text="Arka plan modu şimdilik sadece Windows'ta çalışır.")
                return None
            if not self.bg_hwnd:
                self.hint.configure(text="Önce “Pencere seç” ile hedef pencereyi seç.")
                return None
        fixed = mode == "Sabit"
        pos = (int(self._num(self.e_x)), int(self._num(self.e_y)))

        return {
            "interval": interval,
            "jitter": self.s_jitter.get() / 1000.0,
            "button": BUTTONS[self.seg_button.get()],
            "button_name": self.seg_button.get(),
            "bg": bg,
            "hwnd": self.bg_hwnd,
            "count": COUNTS[self.seg_type.get()],
            "repeat": repeat,
            "fixed": fixed,
            "pos": pos,
            "delay": self._num(self.e_delay),
            "failsafe": bool(self.sw_failsafe.get()),
        }

    # ------------------------------------------------------------------
    # Olay işleyicileri (arayüz)
    # ------------------------------------------------------------------
    def _preset_cps(self, cps):
        for e in (self.e_hours, self.e_minutes, self.e_seconds):
            self._set_entry(e, 0)
        self._set_entry(self.e_millis, max(1, round(1000 / cps)))

    def _on_jitter(self, value):
        v = int(float(value))
        self.l_jitter.configure(text="Kapalı" if v == 0 else f"± {v} ms")

    def _on_repeat_mode(self, value):
        self.e_repeat.configure(state="normal" if value == "Sayı" else "disabled")

    def _pick_text(self):
        return "🖥  Pencere seç" if self.seg_pos.get() == "Arka plan" else "🎯  Ekrandan seç"

    def _on_pos_mode(self, value):
        state = "normal" if value in ("Sabit", "Arka plan") else "disabled"
        self.e_x.configure(state=state)
        self.e_y.configure(state=state)
        self.b_pick.configure(text=self._pick_text())
        if value == "Arka plan":
            self.l_bg.grid()
        else:
            self.l_bg.grid_remove()

    def _on_topmost(self):
        self.attributes("-topmost", bool(self.sw_top.get()))

    def _on_hotkey_mode(self, value):
        self.hotkey_mode = value

    def _on_accent(self, name):
        self.accent, self.accent_h = ACCENTS.get(name, ACCENTS["Mavi"])
        for w, kind in self.accent_widgets:
            if kind == "seg":
                w.configure(selected_color=self.accent, selected_hover_color=self.accent_h)
            elif kind == "switch":
                w.configure(progress_color=self.accent)
            elif kind == "slider":
                w.configure(
                    progress_color=self.accent,
                    button_color=self.accent,
                    button_hover_color=self.accent_h,
                )
            elif kind == "btn":
                w.configure(fg_color=self.accent, hover_color=self.accent_h)
            elif kind == "bar":
                w.configure(progress_color=self.accent)
            elif kind == "text":
                w.configure(text_color=self.accent)
        self._last_phase = None  # ana butonu yeniden boya
        self._refresh_state()

    # ---- Başlat / durdur
    def _toggle(self):
        if self.engine.active:
            self.engine.stop()
        else:
            self._start()

    def _start(self):
        if self.engine.active:
            return
        self.hint.configure(text="")
        cfg = self._build_cfg()
        if cfg is None:
            return
        self.engine.start(cfg)
        if cfg["bg"]:
            self.hint.configure(
                text=f"Arka plan modu açık: fareyi ve klavyeyi serbestçe kullanabilirsin. Durdurmak için {self.hotkey.upper()}."
            )
        self._refresh_state()

    # ---- Konum seçme
    def _pick_position(self):
        bg = self.seg_pos.get() == "Arka plan"
        if bg and not IS_WIN:
            self.hint.configure(text="Arka plan modu şimdilik sadece Windows'ta çalışır.")
            return
        self.b_pick.configure(text="Ekrana tıkla…", state="disabled")
        self.hint.configure(
            text="Hedef pencereyi öne getir ve tıklanmasını istediğin noktaya tıkla."
            if bg
            else "Sabit konumu seçmek için ekranda istediğin yere tıkla."
        )

        def on_click(x, y, button, pressed):
            if pressed:
                if bg:
                    self.events.put(("bgwin", window_from_screen_point(x, y)))
                else:
                    self.events.put(("pos", int(x), int(y)))
                return False

        listener = mouse.Listener(on_click=on_click)
        listener.daemon = True
        listener.start()

    # ---- Kısayol değiştirme
    def _capture_hotkey(self):
        self.capturing_hotkey = True
        self.l_hotkey.configure(text="Tuşa bas…")
        self.hint.configure(text="Yeni kısayol olarak kullanmak istediğin tuşa bas.")

    # ---- Profiller
    def _refresh_profiles(self, select=None):
        names = sorted(self.profiles.keys())
        self.om_profile.configure(values=names or ["Profil yok"])
        self.om_profile.set(select if select in names else (names[0] if names else "Profil yok"))

    def _save_profile(self):
        name = self.e_profile.get().strip()
        if not name:
            self.hint.configure(text="Profil için bir ad yaz.")
            return
        self.profiles[name] = self._get_settings()
        self._refresh_profiles(select=name)
        self.e_profile.delete(0, "end")
        self.hint.configure(text=f"“{name}” profili kaydedildi.")
        self._save_config()

    def _load_profile(self):
        name = self.om_profile.get()
        if name in self.profiles:
            self._apply_settings({**DEFAULTS, **self.profiles[name]})
            self.hint.configure(text=f"“{name}” profili yüklendi.")

    def _delete_profile(self):
        name = self.om_profile.get()
        if name in self.profiles:
            del self.profiles[name]
            self._refresh_profiles()
            self.hint.configure(text=f"“{name}” profili silindi.")
            self._save_config()

    # ------------------------------------------------------------------
    # Global kısayol dinleyicisi (ayrı iş parçacığı -> kuyruk ile arayüze)
    # ------------------------------------------------------------------
    def _start_listeners(self):
        self.kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.kb_listener.daemon = True
        self.kb_listener.start()

    def _on_press(self, key):
        name = key_to_str(key)
        if self.capturing_hotkey:
            self.capturing_hotkey = False
            self.events.put(("hotkey", name))
            return
        if name != self.hotkey or self._key_down:
            return
        self._key_down = True
        if self.hotkey_mode == "Basılı Tut":
            self.events.put(("start",))
        else:
            self.events.put(("toggle",))

    def _on_release(self, key):
        if key_to_str(key) == self.hotkey:
            self._key_down = False
            if self.hotkey_mode == "Basılı Tut":
                self.events.put(("stop",))

    # ------------------------------------------------------------------
    # Ana döngü: olayları işle + arayüzü güncelle
    # ------------------------------------------------------------------
    def _poll(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self._update_stats()
        self._refresh_state()
        self.after(60, self._poll)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "toggle":
            self._toggle()
        elif kind == "start":
            self._start()
        elif kind == "stop":
            self.engine.stop()
        elif kind == "hotkey":
            self.hotkey = ev[1]
            self.l_hotkey.configure(text=self.hotkey.upper())
            self.hint.configure(text=f"Kısayol {self.hotkey.upper()} olarak ayarlandı.")
        elif kind == "pos":
            self._set_entry(self.e_x, ev[1])
            self._set_entry(self.e_y, ev[2])
            self.seg_pos.set("Sabit")
            self._on_pos_mode("Sabit")
            self.b_pick.configure(text="🎯  Ekrandan seç", state="normal")
            self.hint.configure(text=f"Konum seçildi: X={ev[1]}, Y={ev[2]}")
        elif kind == "bgwin":
            info = ev[1]
            self.b_pick.configure(text=self._pick_text(), state="normal")
            if not info:
                self.hint.configure(text="Pencere algılanamadı, tekrar dene.")
            elif info[3].startswith(APP_NAME):
                self.hint.configure(text="NovaClick penceresini seçtin. Hedef pencerede bir noktaya tıkla.")
            else:
                self.bg_hwnd, cx, cy, title = info
                self.bg_title = title or "(başlıksız pencere)"
                self._set_entry(self.e_x, cx)
                self._set_entry(self.e_y, cy)
                short = self.bg_title if len(self.bg_title) <= 46 else self.bg_title[:45] + "…"
                self.l_bg.configure(text=f"Hedef: {short}", text_color=TEXT)
                self.hint.configure(text=f"Hedef pencere seçildi (X={cx}, Y={cy}).")
        elif kind == "finished":
            messages = {
                "done": "Belirlenen tekrar sayısı tamamlandı.",
                "failsafe": "Acil durdurma: fare sol üst köşeye götürüldü.",
                "window_closed": "Hedef pencere kapandı, tıklama durduruldu.",
                "manual": "",
            }
            self.hint.configure(text=messages.get(ev[1], ""))
            self._last_phase = None
            self._refresh_state()

    def _refresh_state(self):
        phase = self.engine.phase if self.engine.active else "idle"
        if phase == self._last_phase:
            return
        self._last_phase = phase
        if phase == "running":
            self.pill.configure(text="●  ÇALIŞIYOR", text_color="#052e16", fg_color=OK)
            self.b_toggle.configure(text="■   DURDUR", fg_color=DANGER, hover_color=DANGER_H)
        elif phase == "waiting":
            self.pill.configure(text="●  BEKLİYOR", text_color="#451a03", fg_color=WARN)
            self.b_toggle.configure(text="■   İPTAL", fg_color=DANGER, hover_color=DANGER_H)
        else:
            self.pill.configure(text="●  HAZIR", text_color="#cbd5e1", fg_color=CARD_ALT)
            self.b_toggle.configure(text="▶   BAŞLAT", fg_color=self.accent, hover_color=self.accent_h)

    def _update_stats(self):
        eng = self.engine
        self.st_clicks.configure(text=f"{eng.clicks:,}".replace(",", "."))
        self.st_cps.configure(text=str(eng.cps() if eng.active else 0))
        if eng.active and eng.phase == "running":
            elapsed = time.perf_counter() - eng.started_at
        else:
            elapsed = eng.last_elapsed
        mm, ss = divmod(int(elapsed), 60)
        hh, mm = divmod(mm, 60)
        self.st_time.configure(text=f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}")
        if eng.target:
            self.bar.set(min(eng.clicks / eng.target, 1.0))
        else:
            self.bar.set(0)

    # ------------------------------------------------------------------
    def _on_close(self):
        self._save_config()
        self.engine.stop()
        try:
            self.kb_listener.stop()
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
