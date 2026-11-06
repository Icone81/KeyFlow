"""keyflow.

Build sequences of key presses, mouse moves, clicks and waits, and trigger
them with global hotkeys. Windows only (uses pydirectinput, winreg, ctypes).
"""
import copy
import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
import traceback
from tkinter import ttk, messagebox, filedialog, colorchooser
from tkinter import font as tkfont

import keyboard
import pydirectinput

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

try:
    from PIL import ImageTk
except ImportError:
    ImageTk = None

try:
    import pystray
except ImportError:
    pystray = None

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

GFX = Image is not None and ImageTk is not None

# Directory for user data (JSON settings/sequences) and bundled resources are
# deliberately kept separate: PyInstaller extracts --add-data files to _MEIPASS.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR


def resource_path(filename):
    """Return the absolute path of a bundled resource in source and frozen mode."""
    return os.path.join(RESOURCE_DIR, filename)


ICON_FILE = resource_path("keyflow.ico")
CONFIG_FILE = os.path.join(BASE_DIR, "keyflow_sequences.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "keyflow_settings.json")
APP_TITLE = "KeyFlow"
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "KeyFlow"
MOUSE_BUTTONS = ("left", "right", "middle")

STEP_LABELS = {
    "key": "Key press",
    "combo": "Key combination",
    "move_click": "Move and click",
    "move": "Move mouse",
    "only_click": "Click at current position",
    "wait": "Wait",
}
STEP_KINDS = tuple(STEP_LABELS)
LABEL_TO_KIND = {label: kind for kind, label in STEP_LABELS.items()}

pydirectinput.PAUSE = 0.03
pydirectinput.FAILSAFE = False

DEFAULT_SEQUENCES = {}

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

# Base surfaces: charcoal with a subtle cool/blue undertone.
BG = "#111318"
CARD = "#191D25"
CARD2 = "#222834"
BORDER = "#343C4B"

# Text hierarchy.
FG = "#F1F2F5"
MUTED = "#9AA3B2"

# Primary accent palette: intentionally unchanged.
ACCENT = "#FFBF00"
ACCENT_H = "#FFE17A"
ACCENT_END = "#FF7070"
ACCENT_FG = "#1B1D22"
ACCENT_BUTTON_FG = "#0b0e17"

# Neutral controls: coordinated with the cool dark surfaces.
NEUTRAL_OFF_FG = "#778296"
NEUTRAL_HOVER = "#2B3444"
NEUTRAL_PRESS = "#374357"

# Accent-related states: intentionally unchanged.
ACCENT_PRESS = "#5a79e6"
ACCENT_OFF_FILL = "#2a3050"
ACCENT_OFF_FG = "#6b7390"

# Danger and success states use restrained, dark supporting fills.
DANGER_FILL = "#382329"
DANGER_HOVER = "#492A33"
DANGER_PRESS = "#59333E"
DANGER_OFF_FILL = "#251D23"
DANGER_OFF_FG = "#80616B"
DANGER = "#FF626C"

OK = "#55C995"
OK_FILL = "#19372F"

TOGGLE_OFF = "#414957"

SCROLLBAR_BG = CARD2
SCROLLBAR_THUMB = "#465064"
SCROLLBAR_HOVER = ACCENT
SCROLLBAR_PRESSED = ACCENT_H

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 18)
FONT_H2 = ("Segoe UI Semibold", 12)
FONT_SMALL = ("Segoe UI", 9)

# Every editable color used by the application. Aliases are included so the
# complete palette can be inspected and customized from the in-app editor.
COLOR_CONSTANTS = (
    "BG", "CARD", "CARD2", "BORDER", "FG", "MUTED",
    "ACCENT", "ACCENT_H", "ACCENT_END", "ACCENT_FG", "ACCENT_BUTTON_FG",
    "NEUTRAL_OFF_FG", "NEUTRAL_HOVER", "NEUTRAL_PRESS",
    "ACCENT_PRESS", "ACCENT_OFF_FILL", "ACCENT_OFF_FG",
    "DANGER_FILL", "DANGER_HOVER", "DANGER_PRESS",
    "DANGER_OFF_FILL", "DANGER_OFF_FG", "DANGER", "OK", "OK_FILL",
    "TOGGLE_OFF", "SCROLLBAR_BG", "SCROLLBAR_THUMB",
    "SCROLLBAR_HOVER", "SCROLLBAR_PRESSED",
)

def is_hex_color(value):
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


def get_color_palette():
    return {name: globals()[name] for name in COLOR_CONSTANTS}


def apply_color_palette(palette):
    """Apply valid color values to module-level theme constants."""
    if not isinstance(palette, dict):
        return
    for name in COLOR_CONSTANTS:
        value = palette.get(name)
        if is_hex_color(value):
            globals()[name] = value.upper()
    # Keep the custom canvas buttons synchronized with the live palette.
    RoundButton.STYLES["neutral"].update(
        fill=CARD2, hover=NEUTRAL_HOVER, press=NEUTRAL_PRESS, fg=FG,
        off_fill=CARD, off_fg=NEUTRAL_OFF_FG)
    RoundButton.STYLES["accent"].update(
        fill=ACCENT, hover=ACCENT_H, press=ACCENT_PRESS, fg=ACCENT_BUTTON_FG,
        off_fill=ACCENT_OFF_FILL, off_fg=ACCENT_OFF_FG)
    RoundButton.STYLES["danger"].update(
        fill=DANGER_FILL, hover=DANGER_HOVER, press=DANGER_PRESS, fg=DANGER,
        off_fill=DANGER_OFF_FILL, off_fg=DANGER_OFF_FG)


def setup_style(root):
    root.configure(bg=BG)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        ".", background=BG, foreground=FG, fieldbackground=CARD2,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        troughcolor=CARD, focuscolor=BG, font=FONT,
    )

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Inner.TFrame", background=CARD2)

    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=FONT_SMALL)
    style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
    style.configure("H2.TLabel", background=CARD, foreground=FG, font=FONT_H2)
    style.configure(
        "Section.TLabel", background=CARD, foreground=MUTED,
        font=("Segoe UI Semibold", 9)
    )
    style.configure(
        "Status.TLabel", background=CARD, foreground=MUTED,
        font=FONT_SMALL, padding=(12, 8)
    )

    style.configure(
        "TEntry", fieldbackground=CARD2, foreground=FG, insertcolor=FG,
        bordercolor=BORDER, padding=6
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure(
        "TCombobox", fieldbackground=CARD2, background=CARD2, foreground=FG,
        arrowcolor=MUTED, bordercolor=BORDER, padding=6,
        selectbackground=CARD2, selectforeground=FG
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", CARD2)],
        foreground=[("readonly", FG)],
        selectbackground=[("readonly", CARD2)],
        selectforeground=[("readonly", FG)],
        bordercolor=[("focus", ACCENT)]
    )

    root.option_add("*TCombobox*Listbox.background", CARD2)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_FG)
    root.option_add("*TCombobox*Listbox.font", FONT)

    # Listbox - selezione elementi nella colonna sinistra
    root.option_add("*Listbox.background", CARD2)
    root.option_add("*Listbox.foreground", FG)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", ACCENT_FG)
    root.option_add("*Listbox.font", FONT)
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Listbox.activestyle", "none")

    style.configure("TSeparator", background=BORDER)

    style.configure(
        "Treeview", background=CARD2, fieldbackground=CARD2, foreground=FG,
        borderwidth=0, rowheight=28, font=FONT
    )
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map(
        "Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", ACCENT_FG)]
    )
    style.configure(
        "Treeview.Heading", background=CARD2, foreground=MUTED,
        borderwidth=0, relief="flat",
        font=("Segoe UI Semibold", 9), padding=(8, 6)
    )
    style.map("Treeview.Heading", background=[("active", CARD2)])

    style.configure(
        "Vertical.TScrollbar",
        background=SCROLLBAR_THUMB,
        troughcolor=SCROLLBAR_BG,
        bordercolor=SCROLLBAR_BG,
        arrowcolor=SCROLLBAR_BG,
        lightcolor=SCROLLBAR_THUMB,
        darkcolor=SCROLLBAR_THUMB,
        borderwidth=0,
        relief="flat",
        arrowsize=10,
        width=10
    )
    thumb_map = [
        ("pressed", SCROLLBAR_PRESSED),
        ("active", SCROLLBAR_HOVER),
        ("!active", SCROLLBAR_THUMB)
    ]
    style.map(
        "Vertical.TScrollbar",
        background=thumb_map,
        lightcolor=thumb_map,
        darkcolor=thumb_map,
    )

    return style


# ---------------------------------------------------------------------------
# Antialiased graphics (supersampling with Pillow)
# ---------------------------------------------------------------------------
if GFX:
    RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
else:
    RESAMPLE = None

_corner_cache = {}
_button_cache = {}


def _hex_to_rgb(color):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def mix_colors(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _corner_disc(radius):
    if radius not in _corner_cache:
        supersample = 8
        size = radius * 2
        big = Image.new("L", (size * supersample, size * supersample), 0)
        ImageDraw.Draw(big).ellipse(
            (0, 0, size * supersample - 1, size * supersample - 1), fill=255)
        _corner_cache[radius] = big.resize((size, size), RESAMPLE)
    return _corner_cache[radius]


def rounded_rect_image(width, height, radius, fill):
    radius = max(1, min(radius, width // 2, height // 2))
    disc = _corner_disc(radius)
    mask = Image.new("L", (width, height), 255)
    mask.paste(disc.crop((0, 0, radius, radius)), (0, 0))
    mask.paste(disc.crop((radius, 0, 2 * radius, radius)), (width - radius, 0))
    mask.paste(disc.crop((0, radius, radius, 2 * radius)), (0, height - radius))
    mask.paste(disc.crop((radius, radius, 2 * radius, 2 * radius)),
               (width - radius, height - radius))
    image = Image.new("RGBA", (width, height), fill)
    image.putalpha(mask)
    return image


def toggle_image(width, height, progress):
    supersample = 6
    big = Image.new("RGBA", (width * supersample, height * supersample), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle((0, 0, width * supersample - 1, height * supersample - 1),
                           radius=height * supersample // 2,
                           fill=mix_colors(TOGGLE_OFF, ACCENT, progress))
    pad = 3 * supersample
    knob = height * supersample - 2 * pad
    x0 = pad + (width * supersample - 2 * pad - knob) * progress
    draw.ellipse((x0, pad, x0 + knob, pad + knob), fill="#ffffff")
    return big.resize((width, height), RESAMPLE)


def parent_bg(widget):
    try:
        return widget.cget("background")
    except tk.TclError:
        pass
    try:
        style_name = widget.cget("style") or widget.winfo_class()
        color = ttk.Style().lookup(style_name, "background")
        if color:
            return color
    except tk.TclError:
        pass
    return BG


class Card(tk.Frame):
    """Container with antialiased rounded corners."""

    def __init__(self, parent, fill=CARD, radius=14, padding=12):
        bg = parent_bg(parent)
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self._card_fill = fill
        self._card_radius = radius
        self._card_size = (0, 0)
        self._card_image = None
        padx, pady = padding if isinstance(padding, tuple) else (padding, padding)
        self._card_bg = tk.Label(self, bd=0, highlightthickness=0, bg=bg if GFX else fill)
        self._card_bg.place(x=0, y=0, relwidth=1, relheight=1)
        style = {CARD: "Card.TFrame", CARD2: "Inner.TFrame"}.get(fill, "Card.TFrame")
        self.body = ttk.Frame(self, style=style)
        self.body.pack(fill="both", expand=True, padx=padx, pady=pady)
        self.bind("<Configure>", self._on_card_configure)

    def _on_card_configure(self, event):
        if not GFX:
            return
        size = (event.width, event.height)
        if size == self._card_size or min(size) < 2 * self._card_radius:
            return
        self._card_size = size
        self._card_image = ImageTk.PhotoImage(
            rounded_rect_image(size[0], size[1], self._card_radius, self._card_fill))
        self._card_bg.configure(image=self._card_image)


class Pill(tk.Label):
    """Small rounded status badge."""

    def __init__(self, parent):
        super().__init__(parent, bg=parent_bg(parent), bd=0, highlightthickness=0,
                         font=("Segoe UI Semibold", 9), compound="center")
        self._pill_font = tkfont.Font(root=parent, font=("Segoe UI Semibold", 9))
        self._pill_image = None

    def set_state(self, text, fill, fg):
        if GFX:
            width = self._pill_font.measure(text) + 30
            self._pill_image = ImageTk.PhotoImage(rounded_rect_image(width, 26, 13, fill))
            self.configure(image=self._pill_image, text=text, fg=fg)
        else:
            self.configure(text=text, bg=fill, fg=fg, padx=14, pady=5)


class ToggleSwitch(tk.Canvas):
    W, H = 46, 26
    STEPS = 6

    def __init__(self, parent, variable, command=None, bg=None):
        super().__init__(parent, width=self.W, height=self.H, bg=bg or parent_bg(parent),
                         highlightthickness=0, bd=0, cursor="hand2", takefocus=0)
        self.variable = variable
        self.command = command
        self._tg_progress = 1.0 if variable.get() else 0.0
        self._tg_anim = None
        self._tg_frames = {}
        self._tg_item = self.create_image(0, 0, anchor="nw") if GFX else None
        self.bind("<Button-1>", self._toggle)
        self._tg_trace = variable.trace_add("write", self._on_var)
        self.bind("<Destroy>", self._on_destroy)
        self._show(self._tg_progress)

    def _frame(self, progress):
        key = round(progress * self.STEPS)
        if key not in self._tg_frames:
            self._tg_frames[key] = ImageTk.PhotoImage(
                toggle_image(self.W, self.H, key / self.STEPS))
        return self._tg_frames[key]

    def _show(self, progress):
        if GFX:
            self.itemconfigure(self._tg_item, image=self._frame(progress))
            return
        self.delete("all")
        on = progress >= 0.5
        color = ACCENT if on else TOGGLE_OFF
        self.create_oval(1, 1, 25, 25, fill=color, outline=color)
        self.create_oval(21, 1, 45, 25, fill=color, outline=color)
        self.create_rectangle(13, 1, 33, 25, fill=color, outline=color)
        x = 25 if on else 4
        self.create_oval(x, 4, x + 17, 21, fill="#ffffff", outline="#ffffff")

    def _on_var(self, *_):
        if self.winfo_exists():
            self._animate(1.0 if self.variable.get() else 0.0)

    def _animate(self, target):
        if self._tg_anim is not None:
            self.after_cancel(self._tg_anim)
            self._tg_anim = None

        def tick():
            diff = target - self._tg_progress
            if abs(diff) < 1e-6:
                self._tg_anim = None
                return
            step = 1.0 / self.STEPS
            self._tg_progress += max(-step, min(step, diff))
            self._show(self._tg_progress)
            self._tg_anim = self.after(14, tick)

        tick()

    def _toggle(self, _event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        try:
            self.variable.trace_remove("write", self._tg_trace)
        except Exception:
            pass
        if self._tg_anim is not None:
            try:
                self.after_cancel(self._tg_anim)
            except Exception:
                pass
            self._tg_anim = None


class RoundButton(tk.Canvas):
    STYLES = {
        "neutral": dict(
            fill=CARD2,
            hover=NEUTRAL_HOVER,
            press=NEUTRAL_PRESS,
            fg=FG,
            off_fill=CARD,
            off_fg=NEUTRAL_OFF_FG
        ),

        "accent": dict(
            fill=ACCENT,
            hover=ACCENT_H,
            press=ACCENT_PRESS,
            fg=ACCENT_BUTTON_FG,
            off_fill=ACCENT_OFF_FILL,
            off_fg=ACCENT_OFF_FG
        ),

        "danger": dict(
            fill=DANGER_FILL,
            hover=DANGER_HOVER,
            press=DANGER_PRESS,
            fg=DANGER,
            off_fill=DANGER_OFF_FILL,
            off_fg=DANGER_OFF_FG
        ),
    }
    HEIGHT = 34

    def __init__(self, parent, text, command=None, style="neutral", min_width=0,
                 state="normal"):
        font_spec = FONT_BOLD if style == "accent" else FONT
        self._btn_font = tkfont.Font(root=parent, font=font_spec)
        natural = max(min_width, self._btn_font.measure(text) + 32)
        super().__init__(parent, width=natural, height=self.HEIGHT, bg=parent_bg(parent),
                         highlightthickness=0, bd=0, takefocus=0)
        self.text = text
        self.command = command
        self.kind = style
        self._btn_state = state
        self._btn_width = natural
        self._btn_height = self.HEIGHT
        self._btn_hover = False
        self._btn_pressed = False
        self._btn_image = None
        self._btn_bg = (self.create_image(0, 0, anchor="nw") if GFX
                        else self.create_rectangle(0, 0, natural, self.HEIGHT, width=0))
        self._btn_label = self.create_text(0, 0, text=text, font=self._btn_font)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_resize)
        self._render()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        handled = False
        if "state" in kw:
            self._btn_state = kw.pop("state")
            handled = True
        if "text" in kw:
            self.text = kw.pop("text")
            handled = True
        if "command" in kw:
            self.command = kw.pop("command")
            handled = True
        result = super().configure(**kw) if (kw or not handled) else None
        if handled:
            self._render()
        return result

    config = configure

    def _colors(self):
        style = self.STYLES[self.kind]
        if self._btn_state == "disabled":
            return style["off_fill"], style["off_fg"]
        if self._btn_pressed and self._btn_hover:
            return style["press"], style["fg"]
        if self._btn_hover:
            return style["hover"], style["fg"]
        return style["fill"], style["fg"]

    def _render(self):
        fill, fg = self._colors()
        width, height = self._btn_width, self._btn_height
        if GFX:
            key = (width, height, fill)
            image = _button_cache.get(key)
            if image is None:
                if len(_button_cache) > 300:
                    _button_cache.clear()
                image = ImageTk.PhotoImage(rounded_rect_image(width, height, 9, fill))
                _button_cache[key] = image
            self._btn_image = image
            self.itemconfigure(self._btn_bg, image=image)
        else:
            self.coords(self._btn_bg, 0, 0, width, height)
            self.itemconfigure(self._btn_bg, fill=fill)
        self.coords(self._btn_label, width / 2, height / 2)
        self.itemconfigure(self._btn_label, text=self.text, fill=fg)
        super().configure(cursor="arrow" if self._btn_state == "disabled" else "hand2")

    def _set_hover(self, value):
        self._btn_hover = value
        if not value:
            self._btn_pressed = False
        self._render()

    def _on_press(self, _event):
        if self._btn_state == "disabled":
            return
        self._btn_pressed = True
        self._render()

    def _on_release(self, event):
        was_pressed = self._btn_pressed
        self._btn_pressed = False
        self._render()
        inside = 0 <= event.x < self._btn_width and 0 <= event.y < self._btn_height
        if was_pressed and inside and self._btn_state != "disabled" and self.command:
            self.command()

    def _on_resize(self, event):
        if event.width > 1 and (event.width, event.height) != (self._btn_width, self._btn_height):
            self._btn_width, self._btn_height = event.width, event.height
            self._render()


class AutoScrollbar(ttk.Scrollbar):
    """Scrollbar that hides itself when everything is visible."""

    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.grid_remove()
        else:
            self.grid()
        super().set(lo, hi)


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------
# Private DLLs so we never mutate ctypes.windll.user32 (shared with pydirectinput).
class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_user32 = _kernel32 = _dwmapi = _shcore = None
_MONITORENUMPROC = None
if os.name == "nt":
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")
    try:
        _shcore = ctypes.WinDLL("shcore")
    except OSError:
        _shcore = None

    HWND, BOOL = wintypes.HWND, wintypes.BOOL
    _user32.GetParent.argtypes = [HWND]
    _user32.GetParent.restype = HWND
    _user32.GetForegroundWindow.restype = HWND
    _user32.BringWindowToTop.argtypes = [HWND]
    _user32.SetForegroundWindow.argtypes = [HWND]
    _user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.c_void_p]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, BOOL]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _user32.MonitorFromWindow.argtypes = [HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = HWND
    _user32.GetMonitorInfoW.argtypes = [HWND, ctypes.POINTER(MONITORINFO)]
    _user32.GetMonitorInfoW.restype = BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    _user32.GetCursorPos.restype = BOOL
    _user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    _user32.SystemParametersInfoW.restype = BOOL
    _user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowPos.argtypes = [
        HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = BOOL
    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        BOOL, HWND, wintypes.HDC, ctypes.POINTER(RECT), ctypes.c_ssize_t)
    _user32.EnumDisplayMonitors.argtypes = [
        HWND, ctypes.POINTER(RECT), _MONITORENUMPROC, ctypes.c_ssize_t]
    _user32.EnumDisplayMonitors.restype = BOOL
    _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    _user32.SetProcessDpiAwarenessContext.restype = BOOL
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


def tk_hwnd(window):
    """Return the Win32 HWND of a Tk toplevel, or None."""
    if _user32 is None:
        return None
    try:
        window.update_idletasks()
        wid = window.winfo_id()
        return _user32.GetParent(wid) or wid
    except Exception:
        return None


def apply_window_icon(window):
    if os.name == "nt" and os.path.isfile(ICON_FILE):
        try:
            window.iconbitmap(default=ICON_FILE)
        except tk.TclError:
            pass


def apply_dark_titlebar(window):
    hwnd = tk_hwnd(window)
    if hwnd is None or _dwmapi is None:
        return
    try:
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE, 19 = same attribute on older builds.
        for attribute in (20, 19):
            if _dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def bring_to_front(window):
    try:
        window.lift()
        hwnd = tk_hwnd(window)
        if hwnd is not None:
            foreground = _user32.GetForegroundWindow()
            if int(foreground or 0) != int(hwnd or 0):
                current_tid = _kernel32.GetCurrentThreadId()
                foreground_tid = _user32.GetWindowThreadProcessId(foreground, None)
                attached = bool(foreground_tid and foreground_tid != current_tid and
                                _user32.AttachThreadInput(foreground_tid, current_tid, True))
                try:
                    _user32.BringWindowToTop(hwnd)
                    _user32.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        _user32.AttachThreadInput(foreground_tid, current_tid, False)
        window.focus_force()
    except Exception:
        pass


def _screen_fallback(window):
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def _work_area(window, reference):
    """Return the work area (left, top, right, bottom) of the monitor holding `reference`."""
    if _user32 is not None:
        try:
            monitor = _user32.MonitorFromWindow(reference.winfo_id(), 2)  # NEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(info)
            if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                return work.left, work.top, work.right, work.bottom
        except Exception:
            pass
    return _screen_fallback(window)


def get_monitor_rects():
    """Return [(x, y, width, height), ...] for every monitor (absolute desktop coordinates)."""
    if _user32 is None or _MONITORENUMPROC is None:
        raise OSError("Monitor enumeration is only available on Windows.")
    monitors = []

    def callback(hmonitor, _hdc, _rect_ptr, _lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            r = info.rcMonitor
            monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    proc = _MONITORENUMPROC(callback)
    if not _user32.EnumDisplayMonitors(None, None, proc, 0) or not monitors:
        raise RuntimeError("Windows did not report any monitor.")
    return monitors


def get_cursor_position():
    if _user32 is None:
        raise OSError("Cursor capture is only available on Windows.")
    point = POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point.x, point.y


def primary_work_area():
    """Return (left, top, right, bottom) of the primary monitor's work area, or None."""
    if _user32 is None:
        return None
    try:
        rect = RECT()
        if _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return None


def make_click_through(window):
    """Make a Tk window ignore the mouse, never take focus, and stay out of Alt+Tab."""
    hwnd = tk_hwnd(window)
    if hwnd is None:
        return
    try:
        # GWL_EXSTYLE = -20; LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE
        style = _user32.GetWindowLongPtrW(hwnd, -20)
        _user32.SetWindowLongPtrW(
            hwnd, -20, style | 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000)
    except Exception:
        pass


def position_overlay(window, x, y, width, height):
    """Place a borderless Tk window on absolute desktop coordinates."""
    hwnd = tk_hwnd(window)
    if hwnd is None:
        window.geometry(f"{width}x{height}+{x}+{y}")
        return
    # SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
    if not _user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0004 | 0x0010 | 0x0040):
        raise ctypes.WinError(ctypes.get_last_error())


def center_window(window, parent=None, width=None, height=None):
    window.update_idletasks()
    width = window.winfo_width() if width is None else width
    height = window.winfo_height() if height is None else height
    left, top, right, bottom = _work_area(window, parent if parent is not None else window)
    try:
        use_parent = parent is not None and parent.winfo_viewable()
    except tk.TclError:
        use_parent = False
    if use_parent:
        cx = parent.winfo_rootx() + parent.winfo_width() // 2
        cy = parent.winfo_rooty() + parent.winfo_height() // 2
    else:
        cx, cy = (left + right) // 2, (top + bottom) // 2
    x = max(left, min(cx - width // 2, right - width))
    y = max(top, min(cy - height // 2, bottom - height))
    window.geometry(f"{width}x{height}+{x}+{y}")


def make_tray_image():
    """Load the same bundled ICO used by the Tk windows for the system tray."""
    if Image is None:
        return None
    if os.path.isfile(ICON_FILE):
        try:
            with Image.open(ICON_FILE) as source:
                return source.convert("RGBA").copy()
        except Exception:
            pass
    image = Image.new("RGBA", (64, 64), (18, 20, 26, 255))
    if ImageDraw is not None:
        draw = ImageDraw.Draw(image)
        rgb = tuple(int(ACCENT[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        fg = tuple(int(ACCENT_FG[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=rgb)
        draw.text((25, 23), "K", fill=fg)
    return image


def enable_per_monitor_dpi_awareness():
    """Ask Windows for coordinates that match the physical resolution of each monitor."""
    if _user32 is None:
        return
    try:
        _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        if _shcore is not None:
            try:
                _shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Steps: validation, summaries, durations
# ---------------------------------------------------------------------------
def is_valid_key_name(key):
    """Return True if pydirectinput knows this key name."""
    mapping = getattr(pydirectinput, "KEYBOARD_MAPPING", None)
    return mapping is None or key.lower() in mapping


def normalize_step(step):
    """Validate a step loaded from JSON and return a clean copy.

    Legacy "click" steps are converted to "move_click".
    Raises ValueError if the step is invalid.
    """
    if not isinstance(step, dict):
        raise ValueError("Every step must be a JSON object.")
    kind = step.get("type")
    if kind == "click":
        kind = "move_click"
    if kind not in STEP_KINDS:
        raise ValueError(f"Unknown step type: {kind!r}")
    try:
        if kind == "key":
            key = str(step["key"]).strip().lower()
            if not key or not is_valid_key_name(key):
                raise ValueError
            return {"type": "key", "key": key}
        if kind == "combo":
            keys = [str(k).strip().lower() for k in step["keys"] if str(k).strip()]
            if not keys or any(not is_valid_key_name(k) for k in keys):
                raise ValueError
            return {"type": "combo", "keys": keys}
        if kind in ("move_click", "move", "only_click"):
            result = {"type": kind}
            if kind != "only_click":
                result["x"], result["y"] = int(step["x"]), int(step["y"])
            if kind != "move":
                button = step.get("button", "left")
                if button not in MOUSE_BUTTONS:
                    raise ValueError
                result["button"] = button
            return result
        # kind == "wait"
        if step.get("random"):
            low, high = float(step["min"]), float(step["max"])
            if low < 0 or high < low:
                raise ValueError
            return {"type": "wait", "random": True, "min": low, "max": high}
        seconds = float(step["seconds"])
        if seconds < 0:
            raise ValueError
        return {"type": "wait", "seconds": seconds}
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Invalid '{kind}' step: {step}") from None


def normalize_sequences(data):
    """Validate a whole {hotkey: [steps]} mapping and return a clean copy."""
    if not isinstance(data, dict):
        raise ValueError("The JSON must be an object that maps each hotkey to a list of steps.")
    result = {}
    for hotkey, steps in data.items():
        name = str(hotkey).strip().lower()
        if not name:
            raise ValueError("Hotkey names cannot be empty.")
        if name in result:
            raise ValueError(f"Duplicate hotkey: {name.upper()}")
        if not isinstance(steps, list):
            raise ValueError(f"The steps of {name.upper()} must be a list.")
        result[name] = [normalize_step(step) for step in steps]
    return result


def step_summary(step):
    """Return (action label, detail text) for the steps table."""
    kind = step.get("type")
    if kind == "key":
        return STEP_LABELS["key"], step["key"]
    if kind == "combo":
        return STEP_LABELS["combo"], " + ".join(step["keys"])
    if kind == "move_click":
        return STEP_LABELS[kind], (
            f"{step.get('button', 'left')} button · X={step['x']}, Y={step['y']}")
    if kind == "move":
        return STEP_LABELS[kind], f"X={step['x']}, Y={step['y']}"
    if kind == "only_click":
        return STEP_LABELS[kind], f"{step.get('button', 'left')} button"
    if kind == "wait":
        if step.get("random"):
            return "Random wait", f"{step['min']:g} – {step['max']:g} s"
        return STEP_LABELS[kind], f"{step['seconds']:g} s"
    return "Unknown", str(kind)


def wait_duration(step):
    if step.get("random"):
        low, high = sorted((float(step["min"]), float(step["max"])))
        return random.uniform(low, high)
    return float(step["seconds"])


# ---------------------------------------------------------------------------
# Configuration and settings
# ---------------------------------------------------------------------------
def _write_json_atomic(path, data):
    """Write JSON through a temporary file so a crash cannot corrupt the target."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_sequences():
    """Return (sequences, warning). `warning` is None unless the file was unusable."""
    defaults = copy.deepcopy(DEFAULT_SEQUENCES)
    if not os.path.isfile(CONFIG_FILE):
        return defaults, None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return normalize_sequences(json.load(f)), None
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return defaults, f"Could not load {os.path.basename(CONFIG_FILE)} ({exc}); defaults loaded."


def save_sequences(sequences):
    _write_json_atomic(CONFIG_FILE, sequences)


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def save_settings(settings):
    try:
        _write_json_atomic(SETTINGS_FILE, settings)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Start with Windows
# ---------------------------------------------------------------------------
def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(__file__)}" --tray'


def is_autostart_enabled():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
        return str(value).strip().lower() == autostart_command().strip().lower()
    except OSError:
        return False


def set_autostart(enabled):
    if winreg is None:
        raise OSError("Start with Windows is only supported on Windows.")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class ThemedToplevel(tk.Toplevel):
    """Withdrawn, iconed, dark-titlebar dialog. Call show_modal() when the body is ready."""

    def __init__(self, parent, title, *, resizable=False):
        super().__init__(parent)
        self.withdraw()
        self.configure(bg=BG)
        self.title(title)
        if not resizable:
            self.resizable(False, False)
        apply_window_icon(self)
        self.parent_win = parent
        self.result = None
        self.transient(parent)

    def show_modal(self, focus_widget=None, min_width=0):
        self.update_idletasks()
        center_window(self, self.parent_win,
                      max(self.winfo_reqwidth(), min_width), self.winfo_reqheight())
        self.deiconify()
        self.wait_visibility()
        apply_dark_titlebar(self)
        self.grab_set()
        (focus_widget or self).focus_set()


class PromptDialog(ThemedToplevel):
    def __init__(self, parent, title, prompt):
        super().__init__(parent, title)
        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        ttk.Label(body, text=prompt).grid(row=0, column=0, sticky="w")
        self.var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=self.var, width=34)
        entry.grid(row=1, column=0, pady=(8, 16), sticky="ew")
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, sticky="e")
        RoundButton(buttons, "OK", self.accept, style="accent", min_width=80).pack(side="right")
        RoundButton(buttons, "Cancel", self.destroy, min_width=80).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self.accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.show_modal(entry, min_width=380)

    def accept(self):
        self.result = self.var.get()
        self.destroy()


class StepDialog(ThemedToplevel):
    def __init__(self, parent, step=None):
        super().__init__(parent, "Step")
        self._ready = False

        step = step or {"type": "key", "key": ""}
        # Convert legacy or unknown steps so the dialog can always display them.
        if step.get("type") == "click":
            step = dict(step, type="move_click")
        if step.get("type") not in STEP_KINDS:
            step = {"type": "move_click", "x": step.get("x", 0), "y": step.get("y", 0),
                    "button": step.get("button", "left")}
        self.kind_var = tk.StringVar(value=step["type"])
        self.kind_label_var = tk.StringVar(value=STEP_LABELS[step["type"]])
        self.key_var = tk.StringVar(value=step.get("key", ""))
        self.combo_var = tk.StringVar(value=", ".join(step.get("keys", [])))
        self.x_var = tk.StringVar(value=str(step.get("x", 0)))
        self.y_var = tk.StringVar(value=str(step.get("y", 0)))
        self.wait_var = tk.StringVar(value=str(step.get("seconds", 0.1)))
        self.random_var = tk.BooleanVar(value=bool(step.get("random", False)))
        self.min_var = tk.StringVar(value=str(step.get("min", 0.5)))
        self.max_var = tk.StringVar(value=str(step.get("max", 1.0)))
        self.button_var = tk.StringVar(value=step.get("button", "left"))

        self.capture_active = False
        self.capture_original = (self.x_var.get(), self.y_var.get())
        self.capture_pressed = False
        self.capture_overlays = []
        self.grab_button = None
        self.capture_label = None

        body = ttk.Frame(self, padding=20)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Step type").grid(row=0, column=0, sticky="w", pady=4)
        kind_box = ttk.Combobox(body, textvariable=self.kind_label_var, state="readonly",
                                width=24, values=list(STEP_LABELS.values()))
        kind_box.grid(row=0, column=1, sticky="ew", pady=4, padx=(10, 0))
        self.fields = ttk.Frame(body)
        self.fields.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        self.kind_label_var.trace_add("write", lambda *_: self._on_kind_changed())
        self.render_fields()
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        RoundButton(buttons, "OK", self.accept, style="accent", min_width=80).pack(side="right")
        RoundButton(buttons, "Cancel", self._close_dialog, min_width=80).pack(
            side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self.accept())
        self.bind("<Escape>",
                  lambda _e: self.cancel_capture() if self.capture_active else self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._close_dialog)
        self._ready = True
        self.show_modal(min_width=440)

    def _on_kind_changed(self):
        self.kind_var.set(LABEL_TO_KIND.get(self.kind_label_var.get(), "key"))
        self.render_fields()

    def fit(self):
        self.update_idletasks()
        center_window(self, self.parent_win, max(self.winfo_reqwidth(), 440),
                      self.winfo_reqheight())

    def ensure_size(self):
        if not self.winfo_exists():
            return
        self.update_idletasks()
        cur_w, cur_h = self.winfo_width(), self.winfo_height()
        width = max(cur_w, self.winfo_reqwidth())
        height = max(cur_h, self.winfo_reqheight())
        if (width, height) != (cur_w, cur_h):
            self.geometry(f"{width}x{height}")

    def set_capture_text(self, text):
        if self.capture_label is not None and self.capture_label.winfo_exists():
            self.capture_label.configure(text=text)
            self.after_idle(self.ensure_size)

    def render_fields(self):
        if self.capture_active:
            self.cancel_capture()
        for widget in self.fields.winfo_children():
            widget.destroy()
        self.grab_button = None
        self.capture_label = None
        kind = self.kind_var.get()
        pad = {"padx": (0, 10), "pady": 4}
        if kind == "key":
            ttk.Label(self.fields, text="Key (e.g. b, enter, space)").grid(
                row=0, column=0, sticky="w", **pad)
            ttk.Entry(self.fields, textvariable=self.key_var, width=24).grid(
                row=0, column=1, pady=4)
        elif kind == "combo":
            ttk.Label(self.fields, text="Keys separated by commas").grid(
                row=0, column=0, sticky="w", **pad)
            ttk.Entry(self.fields, textvariable=self.combo_var, width=24).grid(
                row=0, column=1, pady=4)
            ttk.Label(self.fields, text="Example: ctrl, shift, s", style="Muted.TLabel").grid(
                row=1, column=1, sticky="w")
        elif kind in ("move_click", "move", "only_click"):
            if kind in ("move_click", "move"):
                ttk.Label(self.fields, text="X").grid(row=0, column=0, sticky="w", **pad)
                ttk.Entry(self.fields, textvariable=self.x_var, width=10).grid(
                    row=0, column=1, sticky="w", pady=4)
                ttk.Label(self.fields, text="Y").grid(row=1, column=0, sticky="w", **pad)
                ttk.Entry(self.fields, textvariable=self.y_var, width=10).grid(
                    row=1, column=1, sticky="w", pady=4)
                self.grab_button = RoundButton(self.fields, "GRAB coordinates",
                                               self.start_capture)
                self.grab_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 6))
                wrap = int(380 * self.winfo_fpixels("1i") / 96)
                self.capture_label = ttk.Label(
                    self.fields, text="Press GRAB to capture the coordinates",
                    style="Muted.TLabel", wraplength=wrap, justify="left")
                self.capture_label.grid(row=3, column=0, columnspan=2, sticky="w")
            if kind in ("move_click", "only_click"):
                row = 4 if kind == "move_click" else 0
                ttk.Label(self.fields, text="Mouse button").grid(
                    row=row, column=0, sticky="w", **pad)
                ttk.Combobox(self.fields, textvariable=self.button_var, state="readonly",
                             width=10, values=MOUSE_BUTTONS).grid(
                    row=row, column=1, sticky="w", pady=4)
        elif kind == "wait":
            mode_row = ttk.Frame(self.fields)
            mode_row.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            ToggleSwitch(mode_row, self.random_var, command=self.update_wait_mode).pack(
                side="left")
            ttk.Label(mode_row, text="Random duration (between minimum and maximum)").pack(
                side="left", padx=(10, 0))
            self.fixed_frame = ttk.Frame(self.fields)
            ttk.Label(self.fixed_frame, text="Seconds").grid(
                row=0, column=0, sticky="w", **pad)
            ttk.Entry(self.fixed_frame, textvariable=self.wait_var, width=12).grid(
                row=0, column=1, sticky="w", pady=4)
            self.random_frame = ttk.Frame(self.fields)
            ttk.Label(self.random_frame, text="Minimum (s)").grid(
                row=0, column=0, sticky="w", **pad)
            ttk.Entry(self.random_frame, textvariable=self.min_var, width=12).grid(
                row=0, column=1, sticky="w", pady=4)
            ttk.Label(self.random_frame, text="Maximum (s)").grid(
                row=1, column=0, sticky="w", **pad)
            ttk.Entry(self.random_frame, textvariable=self.max_var, width=12).grid(
                row=1, column=1, sticky="w", pady=4)
            self.update_wait_mode(refit=False)
        if self._ready:
            self.fit()

    def update_wait_mode(self, refit=True):
        self.fixed_frame.grid_forget()
        self.random_frame.grid_forget()
        if self.random_var.get():
            self.random_frame.grid(row=1, column=0, columnspan=2, sticky="w")
        else:
            self.fixed_frame.grid(row=1, column=0, columnspan=2, sticky="w")
        if refit and self._ready:
            self.fit()

    def _close_dialog(self):
        if self.capture_active:
            self.cancel_capture()
        self.destroy()

    # ------------------------------------------------------------ GRAB
    def start_capture(self):
        """Create one overlay per monitor and capture absolute desktop coordinates."""
        if self.capture_active:
            return
        if os.name != "nt":
            messagebox.showerror("Capture not supported",
                                 "Coordinate capture is only implemented for Windows.",
                                 parent=self)
            return

        self.capture_active = True
        self.capture_pressed = False
        self.capture_original = (self.x_var.get(), self.y_var.get())
        self.capture_overlays = []

        try:
            for x, y, width, height in get_monitor_rects():
                overlay = tk.Toplevel(self)
                self.capture_overlays.append(overlay)
                overlay.overrideredirect(True)
                overlay.configure(bg="black", cursor="crosshair")
                overlay.attributes("-topmost", True)
                overlay.attributes("-alpha", 0.12)
                overlay.geometry(f"{width}x{height}+0+0")
                overlay.bind("<ButtonPress-1>", self._capture_press)
                overlay.bind("<ButtonRelease-1>", self._capture_click)
                overlay.bind("<ButtonPress-3>", lambda _e: self.cancel_capture())
                overlay.bind("<Escape>", lambda _e: self.cancel_capture())
                overlay.update_idletasks()
                overlay.wait_visibility()
                position_overlay(overlay, x, y, width, height)

            self.capture_overlays[0].grab_set()
            self.capture_overlays[0].focus_force()
        except Exception as exc:
            self._finish_capture()
            messagebox.showerror("Capture error",
                                 f"Could not start coordinate capture:\n{exc}", parent=self)
            return

        if self.grab_button is not None:
            self.grab_button.configure(state="disabled")
        self.set_capture_text(
            "GRAB active: move the mouse; left click confirms, Esc or right click cancels.")
        self._poll_capture()

    def _poll_capture(self):
        """Update the coordinates in real time while the mouse moves."""
        if not self.capture_active or not self.winfo_exists():
            return
        try:
            if keyboard.is_pressed("esc"):
                self.cancel_capture()
                return
            x, y = get_cursor_position()
            self.x_var.set(str(x))
            self.y_var.set(str(y))
            self.after(20, self._poll_capture)
        except Exception as exc:
            self.cancel_capture()
            messagebox.showerror("Capture error", str(exc), parent=self)

    def _capture_press(self, _event):
        self.capture_pressed = True
        return "break"

    def _capture_click(self, _event):
        if not self.capture_active or not self.capture_pressed:
            return "break"
        x, y = get_cursor_position()
        self.x_var.set(str(x))
        self.y_var.set(str(y))
        self._finish_capture()
        self.set_capture_text(f"Coordinates captured: X={x}, Y={y}")
        return "break"

    def _finish_capture(self):
        """Destroy every overlay and restore the dialog's focus and grab."""
        self.capture_active = False
        self.capture_pressed = False
        overlays, self.capture_overlays = self.capture_overlays, []
        for overlay in overlays:
            try:
                overlay.grab_release()
            except tk.TclError:
                pass
            try:
                if overlay.winfo_exists():
                    overlay.destroy()
            except tk.TclError:
                pass

        try:
            self.grab_set()
        except tk.TclError:
            pass
        bring_to_front(self.parent_win)
        bring_to_front(self)
        try:
            self.after(100, self._refocus)
        except tk.TclError:
            pass
        if self.grab_button is not None and self.grab_button.winfo_exists():
            self.grab_button.configure(state="normal")

    def _refocus(self):
        if self.winfo_exists() and not self.capture_active:
            bring_to_front(self.parent_win)
            bring_to_front(self)

    def cancel_capture(self):
        if not self.capture_active:
            return
        self._finish_capture()
        self.x_var.set(self.capture_original[0])
        self.y_var.set(self.capture_original[1])
        self.set_capture_text("Capture cancelled; coordinates restored")

    # ---------------------------------------------------------- result
    def accept(self):
        if self.capture_active:
            self.cancel_capture()
        kind = self.kind_var.get()
        try:
            if kind == "key":
                key = self.key_var.get().strip().lower()
                if not key:
                    raise ValueError("Enter a key.")
                self._check_key(key)
                self.result = {"type": "key", "key": key}
            elif kind == "combo":
                keys = [k.strip().lower() for k in self.combo_var.get().split(",") if k.strip()]
                if not keys:
                    raise ValueError("Enter at least one key.")
                for key in keys:
                    self._check_key(key)
                self.result = {"type": "combo", "keys": keys}
            elif kind == "move_click":
                x = self._parse_int(self.x_var.get(), "X")
                y = self._parse_int(self.y_var.get(), "Y")
                self.result = {"type": "move_click", "x": x, "y": y,
                               "button": self.button_var.get()}
            elif kind == "move":
                x = self._parse_int(self.x_var.get(), "X")
                y = self._parse_int(self.y_var.get(), "Y")
                self.result = {"type": "move", "x": x, "y": y}
            elif kind == "only_click":
                self.result = {"type": "only_click", "button": self.button_var.get()}
            elif kind == "wait":
                if self.random_var.get():
                    low = self._parse_seconds(self.min_var.get(), "minimum")
                    high = self._parse_seconds(self.max_var.get(), "maximum")
                    if high < low:
                        raise ValueError("The maximum must be greater than or equal to the minimum.")
                    self.result = {"type": "wait", "random": True, "min": low, "max": high}
                else:
                    seconds = self._parse_seconds(self.wait_var.get(), "wait")
                    self.result = {"type": "wait", "seconds": seconds}
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc), parent=self)
            return
        self.destroy()

    @staticmethod
    def _check_key(key):
        if not is_valid_key_name(key):
            raise ValueError(f"Unknown key name: '{key}'.")

    @staticmethod
    def _parse_int(text, label):
        try:
            return int(text.strip())
        except ValueError:
            raise ValueError(f"{label} must be an integer.") from None

    @staticmethod
    def _parse_seconds(text, label):
        try:
            value = float(text.strip().replace(",", "."))
        except ValueError:
            raise ValueError(f"The {label} value must be a number (e.g. 0.5).") from None
        if value < 0:
            raise ValueError("The wait time cannot be negative.")
        return value


# ---------------------------------------------------------------------------
# Loop overlay (top-right of the desktop)
# ---------------------------------------------------------------------------
class LoopOverlay:
    """Translucent, click-through badges in the top-right corner of the desktop.

    One badge per looping sequence, stacked vertically. Hidden when nothing loops.
    """
    PILL_H = 26
    KEY = "#010203"         # colour made fully transparent by Windows
    MARGIN = 16
    GAP = 8

    def __init__(self, root):
        self.root = root
        self.entries = {}   # hotkey -> current cycle number (insertion order = start order)
        self.window = None
        self.canvas = None
        self._font = tkfont.Font(root=root, font=("Segoe UI Semibold", 9))
        self._images = {}
        self._redraw_job = None

    # -- public API (call from the Tk main thread) ----------------------
    def show(self, hotkey, cycle):
        self.entries[hotkey] = cycle
        self._schedule()

    def hide(self, hotkey):
        if self.entries.pop(hotkey, None) is not None:
            self._schedule()

    # -- internals -------------------------------------------------------
    def _schedule(self):
        # Coalesce bursts of updates (fast loops) into a single redraw.
        if self._redraw_job is None:
            self._redraw_job = self.root.after_idle(self._redraw)

    def _ensure_window(self):
        if self.window is not None:
            return
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.configure(bg=self.KEY)
        win.attributes("-topmost", True)
        try:
            win.attributes("-transparentcolor", self.KEY)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(win, bg=self.KEY, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        make_click_through(win)
        self.window = win

    def _pill_image(self, width):
        key = (width, OK_FILL)
        image = self._images.get(key)
        if image is None:
            image = ImageTk.PhotoImage(
                rounded_rect_image(width, self.PILL_H, self.PILL_H // 2, OK_FILL))
            self._images[key] = image
        return image

    def _redraw(self):
        self._redraw_job = None
        if not self.entries:
            if self.window is not None:
                self.window.withdraw()
            return
        self._ensure_window()

        scale = self.root.winfo_fpixels("1i") / 96
        margin, gap = round(self.MARGIN * scale), round(self.GAP * scale)
        labels = [f"●  {hotkey.upper()}  ·  CYCLE {cycle}"
                  for hotkey, cycle in self.entries.items()]
        widths = [self._font.measure(text) + 30 for text in labels]
        total_w = max(widths)
        total_h = len(labels) * self.PILL_H + (len(labels) - 1) * gap

        self.canvas.delete("all")
        if len(self._images) > 80:
            self._images.clear()
        self.canvas.configure(width=total_w, height=total_h)
        y = 0
        for text, width in zip(labels, widths):
            x0 = total_w - width   # right-align the badges
            if GFX:
                self.canvas.create_image(x0, y, anchor="nw", image=self._pill_image(width))
            else:
                self.canvas.create_rectangle(x0, y, total_w, y + self.PILL_H,
                                             fill=OK_FILL, width=0)
            self.canvas.create_text(x0 + width / 2, y + self.PILL_H / 2, text=text,
                                    fill=OK, font=self._font)
            y += self.PILL_H + gap

        area = primary_work_area()
        if area is None:
            area = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        left, top, right, _bottom = area
        self.window.geometry(f"{total_w}x{total_h}+{right - margin - total_w}+{top + margin}")
        self.window.deiconify()
        self.window.attributes("-topmost", True)
        self.window.lift()


# ---------------------------------------------------------------------------
# Color palette editor
# ---------------------------------------------------------------------------
class ColorPaletteEditor(ThemedToplevel):
    def __init__(self, app):
        super().__init__(app.root, "KeyFlow – Color palette", resizable=True)
        self.app = app
        self.geometry("590x690")
        self.minsize(520, 420)
        self.updating = False
        self.vars = {}
        self.swatches = {}

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Color palette", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Changes are applied immediately. Press Save to keep them across restarts.",
            style="Muted.TLabel", justify="left").pack(anchor="w", pady=(3, 12))

        area = ttk.Frame(outer)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        rows = ttk.Frame(self.canvas)
        rows.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        canvas_window = self.canvas.create_window((0, 0), window=rows, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(canvas_window, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for index, name in enumerate(COLOR_CONSTANTS):
            row = ttk.Frame(rows, padding=(4, 5))
            row.grid(row=index, column=0, sticky="ew")
            rows.columnconfigure(0, weight=1)
            ttk.Label(row, text=name, style="Card.TLabel", width=23).pack(side="left")
            variable = tk.StringVar(value=globals()[name])
            self.vars[name] = variable
            entry = ttk.Entry(row, textvariable=variable, width=11)
            entry.pack(side="left", padx=(8, 6))
            swatch = tk.Label(row, bg=globals()[name], width=4, height=1,
                              bd=1, relief="solid", highlightthickness=0)
            swatch.pack(side="left", padx=(0, 7))
            self.swatches[name] = swatch
            RoundButton(row, "Choose…", lambda n=name: self._choose(n),
                        min_width=82).pack(side="left")
            variable.trace_add("write", lambda *_a, n=name, v=variable: self._edit(n, v.get()))
            entry.bind("<FocusOut>", lambda _e, n=name, v=variable: self._edit(n, v.get()))

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(12, 0))
        self.status_var = tk.StringVar(value="Live preview enabled")
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True)
        RoundButton(footer, "Save", self._save, style="accent", min_width=90).pack(side="right")
        RoundButton(footer, "Close", self.close, min_width=90).pack(side="right", padx=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.deiconify()
        self.wait_visibility()
        apply_dark_titlebar(self)

    def _edit(self, name, value):
        if self.updating or not is_hex_color(value):
            return
        value = value.upper()
        palette = get_color_palette()
        palette[name] = value
        self.updating = True
        try:
            self.vars[name].set(value)
            self.swatches[name].configure(bg=value)
        finally:
            self.updating = False
        self.app.apply_live_palette(palette)

    def _choose(self, name):
        result = colorchooser.askcolor(color=self.vars[name].get(), parent=self,
                                       title=f"Choose {name}")
        if result and result[1]:
            self._edit(name, result[1])

    def _save(self):
        self.app.settings["color_palette"] = get_color_palette()
        if save_settings(self.app.settings):
            self.status_var.set("Palette saved")
            self.app.set_status("Color palette saved.")
        else:
            messagebox.showerror("Color palette",
                                 "Could not save the color palette to the settings file.",
                                 parent=self)

    def sync_chrome(self):
        try:
            self.configure(bg=BG)
            self.canvas.configure(bg=BG)
        except tk.TclError:
            pass

    def close(self):
        self.app.color_editor = None
        self.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class KeyFlowApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.settings = load_settings()
        apply_color_palette(self.settings.get("color_palette", {}))
        setup_style(self.root)
        apply_window_icon(self.root)
        apply_dark_titlebar(self.root)

        self.tray_icon = None
        self.tray_thread = None
        self.tray_available = pystray is not None and Image is not None
        self.quitting = False
        self.dirty = False
        self.color_editor = None

        self.sequences, startup_warning = load_sequences()
        self.current_hotkey = None
        self.seq_keys = []

        # Execution state (shared with the worker and keyboard threads).
        self.run_lock = threading.Lock()
        self.running = False
        self.active_hotkey = None
        self.active_loop = False
        self.stop_event = threading.Event()

        # Callbacks from other threads (keyboard, tray, worker) go through this queue
        # so that every Tk call happens on the main thread.
        self.ui_queue = queue.Queue()

        # Desktop overlay shown while a sequence is looping.
        self.overlay = LoopOverlay(self.root)

        # Loop setting is stored independently for every hotkey/sequence.
        self.sequence_loops = self.settings.get("sequence_loops", {})
        if not isinstance(self.sequence_loops, dict):
            self.sequence_loops = {}
        self.loop_var = tk.BooleanVar(value=False)

        self.hotkey_handles = []
        self.sequences_enabled = bool(self.settings.get("sequences_enabled", True))
        self.autostart_enabled = is_autostart_enabled()
        self.sequences_var = tk.BooleanVar(value=self.sequences_enabled)
        self.autostart_var = tk.BooleanVar(value=self.autostart_enabled)

        self.build_ui()
        self.update_state_pill()
        self.refresh_sequence_list()
        self.fit_main_window()
        self.register_hotkeys()
        if startup_warning:
            self.set_status(startup_warning)

        self.root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.root.bind("<Unmap>", self.on_minimize)
        self.root.after(30, self._drain_ui_queue)

    # --------------------------------------------------- thread plumbing
    def post_ui(self, func, *args):
        """Schedule `func(*args)` on the Tk main thread. Safe to call from any thread."""
        self.ui_queue.put((func, args))

    def _drain_ui_queue(self):
        try:
            while True:
                func, args = self.ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        if not self.quitting:
            self.root.after(30, self._drain_ui_queue)

    def fit_main_window(self):
        self.root.update_idletasks()
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.minsize(width, height)
        center_window(self.root, width=width, height=height)

    def mark_dirty(self, dirty=True):
        self.dirty = dirty
        self.root.title(f"{APP_TITLE} *" if dirty else APP_TITLE)

    # ------------------------------------------------------------- tray
    def on_minimize(self, event):
        if event.widget is self.root and self.root.state() == "iconic":
            self.minimize_to_tray()

    def minimize_to_tray(self):
        if not self.tray_available:
            messagebox.showwarning(
                "System tray unavailable",
                "To use the notification area, install the dependencies:\n"
                "python -m pip install pystray Pillow",
                parent=self.root)
            return
        if self.quitting:
            return
        self.root.withdraw()
        if self.tray_icon is None:
            image = make_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Open KeyFlow Editor", self._tray_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Enable hotkey sequences", self._tray_toggle_sequences,
                                 checked=lambda item: self.sequences_enabled),
                pystray.MenuItem("Start with Windows", self._tray_toggle_autostart,
                                 checked=lambda item: self.autostart_enabled),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._tray_exit),
            )
            self.tray_icon = pystray.Icon("KeyFlow", image, APP_TITLE, menu)
            self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self.tray_thread.start()

    def refresh_tray_menu(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def _tray_show(self, icon=None, item=None):
        self.post_ui(self.restore_from_tray)

    def _tray_toggle_sequences(self, icon=None, item=None):
        self.post_ui(self.toggle_sequences_from_menu)

    def _tray_toggle_autostart(self, icon=None, item=None):
        self.post_ui(self.toggle_autostart_from_menu)

    def _tray_exit(self, icon=None, item=None):
        self.post_ui(self.request_close)

    def restore_from_tray(self):
        if self.quitting:
            return
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    # --------------------------------------------------------- toggles
    def toggle_sequences_from_menu(self):
        self.sequences_var.set(not self.sequences_var.get())
        self.on_toggle_sequences()

    def toggle_autostart_from_menu(self):
        self.autostart_var.set(not self.autostart_var.get())
        self.on_toggle_autostart()

    def on_toggle_sequences(self):
        self.sequences_enabled = bool(self.sequences_var.get())
        self.settings["sequences_enabled"] = self.sequences_enabled
        save_settings(self.settings)
        self.update_state_pill()
        self.refresh_tray_menu()
        self.set_status("Hotkey sequences enabled." if self.sequences_enabled else
                        "Hotkey sequences disabled (manual execution is still available).")

    def on_toggle_autostart(self):
        wanted = bool(self.autostart_var.get())
        try:
            set_autostart(wanted)
        except OSError as exc:
            self.autostart_var.set(not wanted)
            messagebox.showerror("Start with Windows", str(exc), parent=self.root)
            return
        self.autostart_enabled = wanted
        self.refresh_tray_menu()
        self.set_status("The program will start with Windows (minimized to the tray)." if wanted
                        else "Start with Windows disabled.")

    def update_state_pill(self):
        if self.sequences_enabled:
            self.state_pill.set_state("●  HOTKEYS ACTIVE", OK_FILL, OK)
        else:
            self.state_pill.set_state("●  HOTKEYS PAUSED", DANGER_FILL, DANGER)

    def set_status(self, text):
        self.status_var.set(text)

    # --------------------------------------------------------------- UI
    def build_ui(self):
        main = ttk.Frame(self.root, padding=(20, 14, 20, 12))
        main.pack(fill="both", expand=True)
        header = ttk.Frame(main)
        header.pack(fill="x")
        titles = ttk.Frame(header)
        titles.pack(side="left")
        ttk.Label(titles, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Build key and click sequences and trigger them with a global hotkey.",
                  style="Muted.TLabel").pack(anchor="w")
        self.state_pill = Pill(header)
        self.state_pill.pack(side="right", anchor="n")

        settings = ttk.Frame(main)
        settings.pack(fill="x", pady=(12, 10))
        settings.columnconfigure(0, weight=1, uniform="s")
        settings.columnconfigure(1, weight=1, uniform="s")
        self._build_setting_card(
            settings, 0, "Enable hotkey sequences",
            "When off, hotkeys do not start sequences.", self.sequences_var,
            self.on_toggle_sequences, padx=(0, 6))
        self._build_setting_card(
            settings, 1, "Start with Windows",
            "Launches minimized to the tray when you sign in.", self.autostart_var,
            self.on_toggle_autostart, padx=(6, 0))

        body = ttk.Frame(main)
        body.pack(fill="both", expand=True)

        # Sequences sidebar
        side_card = Card(body, fill=CARD, radius=14, padding=12)
        side_card.pack(side="left", fill="y", padx=(0, 12))
        side = side_card.body
        ttk.Label(side, text="SEQUENCES", style="Section.TLabel").pack(anchor="w")
        list_card = Card(side, fill=CARD2, radius=10, padding=4)
        list_card.pack(fill="both", expand=True, pady=(8, 10))
        list_wrap = list_card.body
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)
        self.seq_list = tk.Listbox(
            list_wrap, width=20, height=7, bd=0, highlightthickness=0, relief="flat",
            bg=CARD2, fg=FG, selectbackground=ACCENT, selectforeground=ACCENT_FG,
            activestyle="none", exportselection=False, font=("Segoe UI", 11))
        self.seq_list.grid(row=0, column=0, sticky="nsew")
        seq_scroll = AutoScrollbar(list_wrap, orient="vertical", command=self.seq_list.yview)
        seq_scroll.grid(row=0, column=1, sticky="ns")
        self.seq_list.configure(yscrollcommand=seq_scroll.set)
        self.seq_list.bind("<<ListboxSelect>>", lambda _e: self.on_sequence_select())
        side_buttons = ttk.Frame(side, style="Card.TFrame")
        side_buttons.pack(fill="x")
        side_buttons.columnconfigure(0, weight=1, uniform="sb")
        side_buttons.columnconfigure(1, weight=1, uniform="sb")
        RoundButton(side_buttons, "+ New", self.new_sequence, style="accent").grid(
            row=0, column=0, sticky="ew")
        RoundButton(side_buttons, "Delete", self.delete_sequence, style="danger").grid(
            row=0, column=1, sticky="ew", padx=(8, 0))

        # Steps panel
        steps_outer = Card(body, fill=CARD, radius=14, padding=12)
        steps_outer.pack(side="left", fill="both", expand=True)
        steps_card = steps_outer.body
        self.steps_title_var = tk.StringVar(value="Steps")
        steps_header = ttk.Frame(steps_card, style="Card.TFrame")
        steps_header.pack(fill="x")
        ttk.Label(steps_header, textvariable=self.steps_title_var, style="H2.TLabel").pack(
            side="left", anchor="w")
        loop_box = ttk.Frame(steps_header, style="Card.TFrame")
        loop_box.pack(side="right")
        ttk.Label(loop_box, text="Loop", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        self.loop_switch = ToggleSwitch(loop_box, self.loop_var, command=self.on_toggle_loop)
        self.loop_switch.pack(side="left")
        ttk.Label(steps_card, text="Executed from top to bottom", style="CardMuted.TLabel").pack(
            anchor="w", pady=(0, 8))
        table_card = Card(steps_card, fill=CARD2, radius=10, padding=4)
        table_card.pack(fill="both", expand=True)
        table = table_card.body
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.step_tree = ttk.Treeview(table, columns=("n", "type", "detail"), show="headings",
                                      selectmode="browse", height=7)
        self.step_tree.heading("n", text="#", anchor="w")
        self.step_tree.heading("type", text="ACTION", anchor="w")
        self.step_tree.heading("detail", text="DETAILS", anchor="w")
        self.step_tree.column("n", width=48, stretch=False, anchor="w")
        self.step_tree.column("type", width=170, stretch=False, anchor="w")
        self.step_tree.column("detail", width=240, anchor="w")
        self.step_tree.grid(row=0, column=0, sticky="nsew")
        self.step_tree.bind("<Double-1>", lambda _e: self.edit_step())
        step_scroll = AutoScrollbar(table, orient="vertical", command=self.step_tree.yview)
        step_scroll.grid(row=0, column=1, sticky="ns")
        self.step_tree.configure(yscrollcommand=step_scroll.set)
        toolbar = ttk.Frame(steps_card, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(10, 0))
        RoundButton(toolbar, "+ Add", self.add_step).pack(side="left")
        RoundButton(toolbar, "Edit", self.edit_step).pack(side="left", padx=6)
        RoundButton(toolbar, "Remove", self.remove_step, style="danger").pack(side="left")
        RoundButton(toolbar, "▼", lambda: self.move_step(1), min_width=40).pack(side="right")
        RoundButton(toolbar, "▲", lambda: self.move_step(-1), min_width=40).pack(
            side="right", padx=6)

        # Bottom bar
        bottom = ttk.Frame(main)
        bottom.pack(fill="x", pady=(12, 0))
        self.run_button = RoundButton(bottom, "▶  Run sequence", self.run_selected,
                                      style="accent")
        self.run_button.pack(side="left")
        self.stop_button = RoundButton(bottom, "■  Stop", self.stop_sequence, style="danger",
                                       state="disabled")
        self.stop_button.pack(side="left", padx=8)
        RoundButton(bottom, "Hide to tray", self.minimize_to_tray).pack(side="right")
        RoundButton(bottom, "Load JSON", self.load_json).pack(side="right", padx=8)
        RoundButton(bottom, "Save", self.save).pack(side="right")

        status_card = Card(main, fill=CARD, radius=10, padding=(8, 4))
        status_card.pack(fill="x", pady=(12, 0))
        self.status_var = tk.StringVar(
            value="Ready. Global hotkeys are active.")
        status_row = ttk.Frame(status_card.body, style="Card.TFrame")
        status_row.pack(fill="x")
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel",
                  anchor="w").pack(side="left", fill="x", expand=True)
        RoundButton(status_row, "⚙ Colors", self.open_color_editor,
                    min_width=104).pack(side="right", padx=(8, 0), pady=2)


    def open_color_editor(self):
        editor = self.color_editor
        if editor is not None:
            try:
                if editor.winfo_exists():
                    editor.deiconify()
                    editor.lift()
                    return
            except tk.TclError:
                pass
        self.color_editor = ColorPaletteEditor(self)

    def apply_live_palette(self, palette):
        old_card, old_card2 = CARD, CARD2
        apply_color_palette(palette)
        setup_style(self.root)
        self.root.configure(bg=BG)
        _button_cache.clear()

        def refresh(widget):
            try:
                if isinstance(widget, Card):
                    if widget._card_fill == old_card:
                        widget._card_fill = CARD
                        widget.body.configure(style="Card.TFrame")
                    elif widget._card_fill == old_card2:
                        widget._card_fill = CARD2
                        widget.body.configure(style="Inner.TFrame")
                    widget._card_bg.configure(bg=BG if GFX else widget._card_fill)
                    widget._card_size = (0, 0)
                    if GFX:
                        width, height = widget.winfo_width(), widget.winfo_height()
                        if width > 1 and height > 1:
                            widget._card_image = ImageTk.PhotoImage(
                                rounded_rect_image(width, height, widget._card_radius,
                                                   widget._card_fill))
                            widget._card_bg.configure(image=widget._card_image)
                elif isinstance(widget, RoundButton):
                    widget.configure(bg=parent_bg(widget.master))
                    widget._render()
                elif isinstance(widget, ToggleSwitch):
                    widget.configure(bg=parent_bg(widget.master))
                    widget._tg_frames.clear()
                    widget._show(widget._tg_progress)
                elif isinstance(widget, Pill):
                    widget.configure(bg=BG)
                elif isinstance(widget, tk.Listbox):
                    widget.configure(bg=CARD2, fg=FG, selectbackground=ACCENT,
                                     selectforeground=ACCENT_FG)
                elif isinstance(widget, tk.Canvas):
                    widget.configure(bg=parent_bg(widget.master))
                elif isinstance(widget, tk.Frame):
                    try:
                        current = widget.cget("bg")
                        if current in (old_card, old_card2, BG):
                            widget.configure(bg={old_card: CARD, old_card2: CARD2, BG: BG}[current])
                    except tk.TclError:
                        pass
            except (tk.TclError, AttributeError):
                pass
            for child in widget.winfo_children():
                refresh(child)

        refresh(self.root)
        self.update_state_pill()
        self.overlay._images.clear()
        if self.overlay.entries:
            self.overlay._schedule()
        if self.color_editor is not None:
            self.color_editor.sync_chrome()

    def _build_setting_card(self, parent, column, title, description, variable, command, padx):
        card = Card(parent, fill=CARD, radius=14, padding=(14, 10))
        card.grid(row=0, column=column, sticky="ew", padx=padx)
        inner = card.body
        inner.columnconfigure(0, weight=1)
        ttk.Label(inner, text=title, style="Card.TLabel", font=FONT_BOLD).grid(
            row=0, column=0, sticky="w")
        ttk.Label(inner, text=description, style="CardMuted.TLabel", wraplength=300,
                  justify="left").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ToggleSwitch(inner, variable, command=command).grid(
            row=0, column=1, rowspan=2, padx=(12, 0))

    # ---------------------------------------------------- sequences/steps
    def refresh_sequence_list(self, select=None):
        keys = sorted(self.sequences)
        self.seq_keys = keys
        if select in self.sequences:
            target = select
        elif self.current_hotkey in self.sequences:
            target = self.current_hotkey
        elif keys:
            target = keys[0]
        else:
            target = None
        self.seq_list.delete(0, tk.END)
        for key in keys:
            count = len(self.sequences[key])
            noun = "step" if count == 1 else "steps"
            self.seq_list.insert(tk.END, f"  {key.upper()}   ·   {count} {noun}")
        if target is not None:
            index = keys.index(target)
            self.seq_list.selection_set(index)
            self.seq_list.see(index)
        self.current_hotkey = target
        self.populate_steps()
        self.update_loop_option()

    def on_sequence_select(self):
        selected = self.seq_list.curselection()
        if not selected:
            return
        self.current_hotkey = self.seq_keys[selected[0]]
        self.populate_steps()
        self.update_loop_option()

    def on_toggle_loop(self):
        if not self.current_hotkey:
            self.loop_var.set(False)
            return
        self.sequence_loops[self.current_hotkey] = bool(self.loop_var.get())
        self.settings["sequence_loops"] = self.sequence_loops
        save_settings(self.settings)
        state = "enabled" if self.loop_var.get() else "disabled"
        self.set_status(f"Loop {state} for {self.current_hotkey.upper()}.")

    def update_loop_option(self):
        enabled = (bool(self.sequence_loops.get(self.current_hotkey, False))
                   if self.current_hotkey else False)
        self.loop_var.set(enabled)

    def populate_steps(self):
        self.step_tree.delete(*self.step_tree.get_children())
        if self.current_hotkey:
            self.steps_title_var.set(f"Steps · {self.current_hotkey.upper()}")
            for i, step in enumerate(self.sequences[self.current_hotkey], 1):
                kind, detail = step_summary(step)
                self.step_tree.insert("", tk.END, values=(f"{i:02d}", kind, detail))
        else:
            self.steps_title_var.set("Steps")

    def refresh_steps(self):
        self.refresh_sequence_list(self.current_hotkey)

    def selected_index(self):
        selected = self.step_tree.selection()
        return self.step_tree.index(selected[0]) if selected else None

    def select_step(self, index):
        children = self.step_tree.get_children()
        if children:
            index = max(0, min(index, len(children) - 1))
            self.step_tree.selection_set(children[index])
            self.step_tree.see(children[index])

    def new_sequence(self):
        dialog = PromptDialog(self.root, "New sequence",
                              "Trigger hotkey (e.g. f8, ctrl+alt+1):")
        self.root.wait_window(dialog)
        key = (dialog.result or "").strip().lower()
        if not key:
            return
        if key in self.sequences:
            messagebox.showerror("Already exists",
                                 "A sequence is already assigned to this hotkey.",
                                 parent=self.root)
            return
        try:
            keyboard.parse_hotkey(key)
        except Exception as exc:
            messagebox.showerror("Invalid hotkey", f"'{key}' is not a valid hotkey:\n{exc}",
                                 parent=self.root)
            return
        self.sequences[key] = []
        self.mark_dirty()
        self.refresh_sequence_list(key)
        self.register_hotkeys()

    def delete_sequence(self):
        key = self.current_hotkey
        if not key:
            return
        if messagebox.askyesno("Confirm", f"Delete the sequence {key.upper()}?",
                               parent=self.root):
            del self.sequences[key]
            self.sequence_loops.pop(key, None)
            self.settings["sequence_loops"] = self.sequence_loops
            save_settings(self.settings)
            self.current_hotkey = None
            self.mark_dirty()
            self.refresh_sequence_list()
            self.register_hotkeys()

    def add_step(self):
        if not self.current_hotkey:
            messagebox.showinfo("No sequence selected",
                                "Create or select a sequence before adding steps.",
                                parent=self.root)
            return
        dialog = StepDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self.sequences[self.current_hotkey].append(dialog.result)
            self.mark_dirty()
            self.refresh_steps()
            self.select_step(len(self.sequences[self.current_hotkey]) - 1)

    def edit_step(self):
        index = self.selected_index()
        if index is None or not self.current_hotkey:
            return
        old = self.sequences[self.current_hotkey][index]
        dialog = StepDialog(self.root, old)
        self.root.wait_window(dialog)
        if dialog.result:
            self.sequences[self.current_hotkey][index] = dialog.result
            self.mark_dirty()
            self.refresh_steps()
            self.select_step(index)

    def remove_step(self):
        index = self.selected_index()
        if index is None or not self.current_hotkey:
            return
        del self.sequences[self.current_hotkey][index]
        self.mark_dirty()
        self.refresh_steps()
        self.select_step(index)

    def move_step(self, direction):
        index = self.selected_index()
        if index is None or not self.current_hotkey:
            return
        steps = self.sequences[self.current_hotkey]
        new_index = index + direction
        if not 0 <= new_index < len(steps):
            return
        steps[index], steps[new_index] = steps[new_index], steps[index]
        self.mark_dirty()
        self.refresh_steps()
        self.select_step(new_index)

    # ------------------------------------------------------- JSON files
    def save(self):
        """Save the sequences to disk. Returns True on success."""
        try:
            save_sequences(self.sequences)
        except OSError as exc:
            messagebox.showerror("Save error", str(exc), parent=self.root)
            return False
        self.mark_dirty(False)
        self.set_status(f"Configuration saved to {os.path.abspath(CONFIG_FILE)}")
        return True

    def load_json(self):
        path = filedialog.askopenfilename(
            title="Load configuration",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = normalize_sequences(json.load(f))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            messagebox.showerror("Load error", str(exc), parent=self.root)
            return
        self.sequences = data
        self.sequence_loops = {k: v for k, v in self.sequence_loops.items() if k in data}
        self.settings["sequence_loops"] = self.sequence_loops
        save_settings(self.settings)
        self.current_hotkey = None
        self.mark_dirty()
        self.refresh_sequence_list()
        self.register_hotkeys()
        self.set_status(f"Configuration loaded: {path}")

    # ---------------------------------------------------------- hotkeys
    def unregister_hotkeys(self):
        for handle in self.hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self.hotkey_handles = []

    def register_hotkeys(self):
        self.unregister_hotkeys()
        failed = []
        for hotkey in self.sequences:

            try:
                handle = keyboard.add_hotkey(hotkey, self.on_hotkey, args=(hotkey,),
                                             suppress=False, trigger_on_release=False)
                self.hotkey_handles.append(handle)
            except Exception:
                failed.append(hotkey.upper())

        if failed:
            self.set_status(f"Could not register hotkeys: {', '.join(failed)}")

    def on_hotkey(self, hotkey):
        """Called on the keyboard thread when a registered hotkey is pressed."""
        if self.quitting:
            return
        with self.run_lock:
            running = self.running
            active = self.active_hotkey
        if running:
            if active == hotkey:
                self.stop_event.set()
                self.post_ui(self.set_status, f"Stop requested for {hotkey.upper()}…")
            return
        if not self.sequences_enabled:
            return
        self.start_sequence(hotkey)

    def start_sequence(self, hotkey):
        with self.run_lock:
            if self.running or hotkey not in self.sequences:
                return
            steps = [dict(step) for step in self.sequences[hotkey]]
            if not steps:
                self.post_ui(self.set_status, f"The sequence {hotkey.upper()} is empty.")
                return
            loop = bool(self.sequence_loops.get(hotkey, False))
            self.running = True
            self.active_hotkey = hotkey
            self.active_loop = loop
            self.stop_event.clear()
        self.post_ui(self.sequence_started, hotkey, loop)
        threading.Thread(target=self.execute_steps, args=(steps, loop, hotkey),
                         daemon=True).start()

    def sequence_started(self, hotkey, loop=False):
        suffix = " · LOOP ON" if loop else ""
        self.set_status(f"Running {hotkey.upper()}{suffix}…")
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    @staticmethod
    def run_step(step):
        kind = step.get("type")
        if kind == "key":
            pydirectinput.press(step["key"])
        elif kind == "combo":
            pressed = []
            try:
                for key in step["keys"]:
                    pydirectinput.keyDown(key)
                    pressed.append(key)
                time.sleep(0.03)
            finally:
                for key in reversed(pressed):
                    pydirectinput.keyUp(key)
        elif kind in ("click", "move_click"):
            pydirectinput.moveTo(int(step["x"]), int(step["y"]))
            time.sleep(0.05)
            pydirectinput.click(button=step.get("button", "left"))
        elif kind == "move":
            pydirectinput.moveTo(int(step["x"]), int(step["y"]))
        elif kind == "only_click":
            pydirectinput.click(button=step.get("button", "left"))

    def execute_steps(self, steps, loop=False, hotkey=None):
        """Worker thread: run the steps once, or repeatedly while looping."""
        error = None
        try:
            if self.stop_event.wait(0.15):
                return
            cycle = 0
            while not self.stop_event.is_set():
                cycle += 1
                if loop and hotkey:
                    self.post_ui(self.overlay.show, hotkey, cycle)
                for step in steps:
                    if self.stop_event.is_set():
                        break
                    if step.get("type") == "wait":
                        if self.stop_event.wait(wait_duration(step)):
                            break
                    else:
                        self.run_step(step)
                if not loop or self.stop_event.wait(0.01):
                    break
        except Exception as exc:
            error = str(exc)
        finally:
            stopped = self.stop_event.is_set()
            with self.run_lock:
                self.running = False
                self.active_hotkey = None
                self.active_loop = False
            if hotkey:
                self.post_ui(self.overlay.hide, hotkey)
            self.post_ui(self.sequence_finished, stopped, error)

    def sequence_finished(self, stopped=False, error=None):
        self.run_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        if error:
            self.set_status(f"Error: {error}")
        else:
            self.set_status("Sequence stopped." if stopped else "Sequence completed.")

    def run_selected(self):
        if self.current_hotkey:
            self.start_sequence(self.current_hotkey)

    def stop_sequence(self):
        self.stop_event.set()
        self.set_status("Stop requested…")

    # ------------------------------------------------------------ exit
    def request_close(self):
        """Close requested by the user (window X or tray menu): offer to save changes."""
        if self.quitting:
            return
        if self.dirty:
            if self.root.state() == "withdrawn":
                self.restore_from_tray()
            answer = messagebox.askyesnocancel(
                "Unsaved changes", "Save your changes before exiting?", parent=self.root)
            if answer is None:
                return
            if answer and not self.save():
                return
        self.close()

    def close(self):
        """Shut everything down immediately (also used by the exit hotkey)."""
        if self.quitting:
            return
        self.quitting = True
        self.stop_event.set()
        self.unregister_hotkeys()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.after(50, self.root.destroy)


if __name__ == "__main__":
    enable_per_monitor_dpi_awareness()
    root = tk.Tk()
    app = KeyFlowApp(root)
    if "--tray" in sys.argv and app.tray_available:
        root.after(300, app.minimize_to_tray)
    root.mainloop()