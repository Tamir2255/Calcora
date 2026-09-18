from datetime import datetime, timedelta
import hashlib
import json
import os
import re
import smtplib
import threading
import time
from email.message import EmailMessage

# Base directory — same folder as main.py, so images are always found
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Supabase sync ─────────────────────────────────────────────────────────────
try:
    import sys
    sys.path.insert(0, BASE_DIR)
    import supabase_sync as fb
    FB_AVAILABLE = True
except Exception:
    fb           = None
    FB_AVAILABLE = False

# ── Session state ─────────────────────────────────────────────────────────────
SESSION = {
    "role":         None,   # "owner" or "worker"
    "worker_name":  None,
    "worker_id":    None,
    "store_id":     None,
    "store_name":   None,
    "store_code":   None,
    "owner_uid":    None,
}

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import (Color, Ellipse, Line, Rectangle,
                            RoundedRectangle, Triangle)
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.uix.image import Image as KivyImage
from kivy.uix.filechooser import FileChooserListView


# ── Constants ─────────────────────────────────────────────────────────────────

VAT_RATE      = 0.18
DATA_FILE     = os.path.join(BASE_DIR, "calcora_data.json")
PROFILE_FILE  = os.path.join(BASE_DIR, "calcora_profile.json")
AUTH_FILE     = os.path.join(BASE_DIR, "calcora_auth.json")
PIN_FILE      = os.path.join(BASE_DIR, "calcora_pin.json")
STORES_FILE   = os.path.join(BASE_DIR, "calcora_stores.json")


# ── Store helpers ─────────────────────────────────────────────────────────────

def load_stores():
    """Return dict with active store id and list of extra stores.
    Handles both old list format and new dict format."""
    try:
        if os.path.exists(STORES_FILE):
            with open(STORES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Old format was a plain list — convert it
            if isinstance(data, list):
                return {"active": "default", "list": data,
                        "default_name": "Main Store",
                        "default_biz": get_biz_type()}
            # New format is a dict
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"active": "default", "list": [],
            "default_name": "Main Store", "default_biz": get_biz_type()}

def save_stores(data):
    try:
        with open(STORES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass

def get_active_store_id():
    return load_stores().get("active", "default")

def store_data_file(store_id):
    return os.path.join(BASE_DIR, f"calcora_data_{store_id}.json")

def store_profile_file(store_id):
    return os.path.join(BASE_DIR, f"calcora_profile_{store_id}.json")

def store_pin_file(store_id):
    return os.path.join(BASE_DIR, f"calcora_pin_{store_id}.json")

# Notification helpers

def _format_notification_text(prefix, item_name, store_name, suffix=None):
    if item_name:
        text = f"{prefix} {item_name}: {store_name}"
    else:
        text = f"{prefix}: {store_name}"
    return f"{text} {suffix}" if suffix else text


def _send_email(to_email, subject, body):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = os.environ.get("SMTP_PORT", "465")
    smtp_user = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or f"noreply@{smtp_server or 'localhost'}")
    if not smtp_server or not smtp_user or not smtp_password or not to_email:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP_SSL(smtp_server, int(smtp_port), timeout=10) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"[Email send failed] {e}")
        return False


def send_app_notification(store_id, message, worker_name=None, subtotal=0):
    if not (FB_AVAILABLE and fb and fb.is_online()):
        return False
    resolved_store_id = store_id
    stores_data = load_stores()
    if store_id == "default":
        resolved_store_id = stores_data.get("default_online_id", store_id)
    else:
        for item in stores_data.get("list", []):
            if item.get("id") == store_id and item.get("online_id"):
                resolved_store_id = item.get("online_id")
                break
    def _push():
        try:
            fb.push_notification(resolved_store_id, message,
                                 worker_name=worker_name or "",
                                 subtotal=subtotal)
        except Exception as e:
            print(f"[Notification push failed] {e}")
    threading.Thread(target=_push, daemon=True).start()
    return True


def _ensure_subscription_fields(profile):
    if not profile.get("subscription_expires"):
        profile["subscription_expires"] = (
            datetime.now().date() + timedelta(days=30)
        ).isoformat()
    if not profile.get("subscription_status"):
        profile["subscription_status"] = "active"
    return profile

# Calcora brand palette — brighter and more colorful
C_BG     = (0.06, 0.09, 0.16, 1)
C_PANEL  = (0.12, 0.18, 0.30, 1)
C_PANEL2 = (0.18, 0.26, 0.42, 1)
C_BLUE   = (0.18, 0.52, 1.00, 1)
C_GREEN  = (0.10, 0.88, 0.42, 1)
C_PURPLE = (0.55, 0.22, 0.95, 1)
C_WHITE  = (1,    1,    1,    1)
C_GREY   = (0.60, 0.68, 0.80, 1)
C_ERROR  = (1.00, 0.35, 0.35, 1)
C_GOLD   = (1.00, 0.82, 0.20, 1)
C_CYAN   = (0.10, 0.85, 0.95, 1)
C_ORANGE = (1.00, 0.55, 0.10, 1)

ROW_H  = dp(46)
BTN_H  = dp(50)
HDR_H  = dp(36)
BACK_W = dp(90)
RADIUS = dp(14)

def apply_theme(mode):
    """Apply the owner-selected app theme to new screens/widgets."""
    global C_BG, C_PANEL, C_PANEL2, C_WHITE, C_GREY
    if mode == "light":
        C_BG     = (0.93, 0.96, 0.98, 1)
        C_PANEL  = (1.00, 1.00, 1.00, 1)
        C_PANEL2 = (0.86, 0.91, 0.96, 1)
        C_WHITE  = (0.07, 0.10, 0.16, 1)
        C_GREY   = (0.35, 0.42, 0.52, 1)
    else:
        C_BG     = (0.06, 0.09, 0.16, 1)
        C_PANEL  = (0.12, 0.18, 0.30, 1)
        C_PANEL2 = (0.18, 0.26, 0.42, 1)
        C_WHITE  = (1,    1,    1,    1)
        C_GREY   = (0.60, 0.68, 0.80, 1)
    try:
        Window.clearcolor = C_BG
    except Exception:
        pass

def load_theme():
    try:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("theme", "dark")
    except Exception:
        pass
    return "dark"

# ── Business types ────────────────────────────────────────────────────────────
# needs_capital: whether buying cost tracking is required
# needs_unit_pb: whether unit buying price matters
# units: common units for this business
# examples: shown as hint text

BUSINESS_TYPES = {
    "Home Retail": {
        "desc":         "Rice, sugar, soap, household items",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["kg", "g", "L", "mL", "pcs", "pkt", "box"],
        "icon":         "🏠",
        "color":        (0.15, 0.47, 0.95, 1),
    },
    "Hardware Shop": {
        "desc":         "Building materials, tools, paint, pipes",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["pcs", "m", "L", "kg", "box", "roll", "bag"],
        "icon":         "🔨",
        "color":        (0.85, 0.45, 0.10, 1),
    },
    "Fashion & Clothing": {
        "desc":         "Clothes, shoes, accessories",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["pcs", "pair", "set", "dozen"],
        "icon":         "👗",
        "color":        (0.75, 0.15, 0.75, 1),
    },
    "Holesale": {
        "desc":         "Bulk goods for resale, distributors, and wholesalers",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["pcs", "box", "crate", "packet", "dozen", "sack", "carton"],
        "icon":         "📦",
        "color":        (0.10, 0.65, 0.85, 1),
    },
    "Spare Parts": {
        "desc":         "Mechanic & vehicle spare parts",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["pcs", "set", "pair", "box"],
        "icon":         "⚙️",
        "color":        (0.50, 0.50, 0.60, 1),
    },
    "Supermarket": {
        "desc":         "Mixed goods, groceries, beverages",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["pcs", "kg", "L", "pkt", "crate", "dozen", "box"],
        "icon":         "🏪",
        "color":        (0.10, 0.65, 0.35, 1),
    },
    "Grocery Store": {
        "desc":         "Fresh produce, vegetables, fruits",
        "needs_capital": True,
        "needs_unit_pb": True,
        "units":        ["kg", "g", "bunch", "pcs", "tray", "bag"],
        "icon":         "🥦",
        "color":        (0.20, 0.75, 0.20, 1),
    },
    "Craft & Art": {
        "desc":         "Handmade crafts, paintings, pottery",
        "needs_capital": False,
        "needs_unit_pb": False,
        "units":        ["pcs", "set", "piece"],
        "icon":         "🎨",
        "color":        (0.95, 0.70, 0.10, 1),
    },
}

def get_biz_type():
    """Read business type from the ACTIVE store's profile file."""
    try:
        app = App.get_running_app()
        pf  = app.active_profile_file() if app else PROFILE_FILE
        if not os.path.exists(pf):
            pf = PROFILE_FILE        # fallback to default
        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f:
                return json.load(f).get("biz_type", "Home Retail")
    except Exception:
        pass
    return "Home Retail"

def biz_config():
    """Return config dict for current active store's business type."""
    return BUSINESS_TYPES.get(get_biz_type(), BUSINESS_TYPES["Home Retail"])

def app_currency():
    """Read currency from active store profile."""
    try:
        from kivy.app import App
        app = App.get_running_app()
        pf  = app.active_profile_file() if app else PROFILE_FILE
        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f:
                return json.load(f).get("currency", "UGX")
    except Exception:
        pass
    return "UGX"


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_number(value):
    value = value.strip()
    if not value:
        return 0
    fraction = re.search(r"[-+]?\d+(?:\.\d+)?\s*/\s*[-+]?\d+(?:\.\d+)?", value)
    if fraction:
        top, bot = fraction.group(0).replace(" ", "").split("/", 1)
        try:
            return float(top) / float(bot)
        except ZeroDivisionError:
            return 0
    number = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return float(number.group(0)) if number else 0


def parse_unit(value):
    value = value.strip()
    match = re.search(r"[A-Za-z]+(?:\s+[A-Za-z]+)*$", value)
    return match.group(0).strip() if match else ""


def today_short():
    return datetime.now().strftime("%d/%m")


def money(value):
    return f"{value:,.2f}"


def stock_recommendation(item):
    total_added = item.get("total_quantity_added", 0)
    threshold   = total_added * 0.25
    if total_added == 0:
        return "No sales data yet"
    if item["quantity"] <= 0:
        return "Out of stock — restock immediately"
    if item["quantity"] <= threshold:
        return "Advised to stock more"
    return "Stock level is okay"


# ── Popup ─────────────────────────────────────────────────────────────────────

def confirm_popup(title, message, on_confirm):
    content = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(18))
    with content.canvas.before:
        Color(*C_PANEL)
        content._cbg = RoundedRectangle(pos=content.pos, size=content.size,
                                         radius=[dp(12)])
    content.bind(
        pos=lambda w, v: setattr(w._cbg, "pos",  v),
        size=lambda w, v: setattr(w._cbg, "size", v),
    )
    content.add_widget(Label(
        text=message, color=C_WHITE, halign="center",
        text_size=(dp(260), None), size_hint_y=None, height=dp(60),
    ))
    buttons = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))
    popup = Popup(
        title=title, content=content,
        size_hint=(0.82, None), height=dp(210),
        auto_dismiss=True,
        background_color=(*C_PANEL[:3], 1),
        title_color=C_GREEN,
    )
    def _yes(*_):
        popup.dismiss()
        on_confirm()

    yes_btn = CalcoraButton(text="Yes, continue",
                             background_color=(0.75, 0.12, 0.12, 1))
    yes_btn.bind(on_release=_yes)
    cancel_btn = CalcoraButton(text="Cancel", background_color=C_PANEL2)
    cancel_btn.bind(on_release=popup.dismiss)
    buttons.add_widget(yes_btn)
    buttons.add_widget(cancel_btn)
    content.add_widget(buttons)
    popup.open()


# ── Reusable widgets ──────────────────────────────────────────────────────────

class CalcoraButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", C_BLUE)
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down   = ""
        self.color             = C_WHITE
        self.bold              = True
        self.halign            = "center"
        self.valign            = "middle"
        self._base_color       = list(self.background_color)
        with self.canvas.before:
            self._c    = Color(*self.background_color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                           radius=[RADIUS])
        self.bind(pos=self._sync, size=self._sync,
                  background_color=self._color_changed)

    def _sync(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size

    def _color_changed(self, *_):
        self._c.rgba = self.background_color

    def on_size(self, *_):
        self.text_size = self.size
        self.font_size = min(self.width * 0.07, self.height * 0.30, dp(22))

    def on_press(self):
        bc = list(self.background_color)
        Animation(background_color=[bc[0], bc[1], bc[2], 0.65],
                  duration=0.08).start(self)

    def on_release(self):
        bc = list(self.background_color)
        Animation(background_color=[bc[0], bc[1], bc[2], 1.0],
                  duration=0.14).start(self)


class StyledInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal  = ""
        self.background_active  = ""
        self.background_color   = C_PANEL2
        self.foreground_color   = C_WHITE
        self.hint_text_color    = (*C_GREY[:3], 0.7)
        self.cursor_color       = C_GREEN
        if not self.padding or self.padding == [6, 6, 6, 6]:
            self.padding = [dp(14), dp(12), dp(14), dp(12)]
        self.font_size = dp(15)


class ResponsiveLabel(Label):
    def __init__(self, max_size, width_ratio, height_ratio, min_size=12, **kwargs):
        super().__init__(**kwargs)
        self.max_size     = max_size
        self.width_ratio  = width_ratio
        self.height_ratio = height_ratio
        self.min_size     = min_size
        self.bind(size=self._layout)

    def _layout(self, *_):
        self.text_size = self.size
        self.font_size = max(
            dp(self.min_size),
            min(self.width * self.width_ratio,
                self.height * self.height_ratio,
                dp(self.max_size)),
        )


class PanelBox(BoxLayout):
    def __init__(self, radius=None, bg_color=None, border_color=None, **kwargs):
        super().__init__(**kwargs)
        r  = radius       or RADIUS
        c  = bg_color     or C_PANEL
        bc = border_color or C_BLUE
        with self.canvas.before:
            Color(*c)
            self._pbg  = RoundedRectangle(pos=self.pos, size=self.size,
                                           radius=[r])
            Color(*bc)
            self._pbdr = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, float(r)),
                width=1.4)
        self.bind(pos=self._psync, size=self._psync)

    def _psync(self, *_):
        self._pbg.pos   = self.pos
        self._pbg.size  = self.size
        r = float(RADIUS)
        self._pbdr.rounded_rectangle = (
            self.x, self.y, self.width, self.height, r)


# ── Calcora logo image ────────────────────────────────────────────────────────

class CalcoraLogo(KivyImage):
    """Displays calcora logo.png; falls back to blank widget if file missing."""
    def __init__(self, **kwargs):
        kwargs.setdefault("allow_stretch", True)
        kwargs.setdefault("keep_ratio",    True)
        super().__init__(**kwargs)
        self.source = os.path.join(BASE_DIR, "calcora logo.png")


# ── Gradient background ───────────────────────────────────────────────────────

class GradientBG(Widget):
    """Dark gradient bg with subtle store-type specific accent color."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_):
        self.canvas.clear()
        btype = get_biz_type()
        cfg   = BUSINESS_TYPES.get(btype, BUSINESS_TYPES["Home Retail"])
        accent = cfg["color"]

        steps    = 20
        is_light = C_BG[0] > 0.5
        top_c    = (0.98, 1.00, 1.00) if is_light else (0.09, 0.14, 0.24)
        bot_c    = (0.88, 0.93, 0.98) if is_light else (0.04, 0.07, 0.13)
        with self.canvas:
            for i in range(steps):
                t = i / steps
                r = top_c[0]*(1-t) + bot_c[0]*t
                g = top_c[1]*(1-t) + bot_c[1]*t
                b = top_c[2]*(1-t) + bot_c[2]*t
                Color(r, g, b, 1)
                h = self.height / steps
                Rectangle(pos=(self.x, self.y + i*h), size=(self.width, h+1))

            # Accent glow circles in top-right and bottom-left
            Color(*accent[:3], 0.07)
            Ellipse(pos=(self.x + self.width*0.55, self.y + self.height*0.55),
                    size=(self.width*0.65, self.width*0.65))
            Color(*accent[:3], 0.05)
            Ellipse(pos=(self.x - self.width*0.25, self.y - self.height*0.10),
                    size=(self.width*0.55, self.width*0.55))

            # Store-type decorative pattern in bottom-right corner
            self._draw_store_pattern(btype, accent)

    def _draw_store_pattern(self, btype, accent):
        """Draw subtle store-type icons as background watermark."""
        import math
        w, h = self.width, self.height
        a    = (*accent[:3], 0.06)   # very subtle

        with self.canvas:
            Color(*a)
            if btype == "Home Retail":
                # Bag shapes (rectangles with rounded tops)
                for i, (bx, by, bw, bh) in enumerate([
                    (w*0.72, h*0.08, w*0.12, w*0.16),
                    (w*0.86, h*0.05, w*0.10, w*0.13),
                    (w*0.60, h*0.04, w*0.09, w*0.12),
                ]):
                    RoundedRectangle(pos=(bx, by), size=(bw, bh),
                                      radius=[dp(6)])
                # Small circles = soap/sweets
                for cx2, cy2, cr in [(w*0.78,h*0.30,w*0.04),
                                      (w*0.88,h*0.35,w*0.03),
                                      (w*0.68,h*0.28,w*0.03)]:
                    Ellipse(pos=(cx2-cr, cy2-cr), size=(cr*2, cr*2))

            elif btype == "Hardware Shop":
                # Nail shapes (thin rectangles)
                for i in range(5):
                    nx = w*0.62 + i*w*0.07
                    ny = h*0.06
                    Rectangle(pos=(nx, ny), size=(w*0.012, h*0.14))
                    Rectangle(pos=(nx - w*0.012, ny + h*0.11),
                              size=(w*0.036, h*0.025))
                # Pipe shapes (rounded rectangles)
                RoundedRectangle(pos=(w*0.65, h*0.28),
                                  size=(w*0.28, w*0.06), radius=[dp(8)])
                RoundedRectangle(pos=(w*0.70, h*0.36),
                                  size=(w*0.22, w*0.05), radius=[dp(8)])
                # Cement bag
                RoundedRectangle(pos=(w*0.72, h*0.46),
                                  size=(w*0.18, w*0.12), radius=[dp(4)])

            elif btype == "Fashion & Clothing":
                # Hanger shapes (triangles + lines)
                for i in range(3):
                    hx = w*0.62 + i*w*0.12
                    hy = h*0.30
                    Line(points=[hx, hy+h*0.06, hx+w*0.10, hy+h*0.06,
                                 hx+w*0.05, hy], width=dp(2))
                    Line(points=[hx+w*0.05, hy, hx+w*0.05, hy+h*0.04],
                         width=dp(2))
                # Shoe silhouette (rounded rectangle)
                RoundedRectangle(pos=(w*0.68, h*0.08),
                                  size=(w*0.22, w*0.09), radius=[dp(12)])
                RoundedRectangle(pos=(w*0.68, h*0.08+w*0.07),
                                  size=(w*0.12, w*0.07), radius=[dp(8)])

            elif btype == "Spare Parts":
                # Gear shapes (circles with inner circle)
                for cx2, cy2, r2 in [(w*0.78, h*0.20, w*0.08),
                                      (w*0.65, h*0.35, w*0.06)]:
                    Line(circle=(cx2, cy2, r2), width=dp(3))
                    Line(circle=(cx2, cy2, r2*0.5), width=dp(2))
                    # Gear teeth
                    for ang in range(0, 360, 45):
                        import math as m
                        rad = m.radians(ang)
                        tx  = cx2 + r2 * m.cos(rad)
                        ty  = cy2 + r2 * m.sin(rad)
                        Rectangle(pos=(tx-dp(3), ty-dp(3)), size=(dp(6), dp(6)))

            elif btype == "Supermarket":
                # Shopping cart lines
                cart_x, cart_y = w*0.68, h*0.20
                Line(points=[cart_x, cart_y+h*0.08,
                             cart_x+w*0.20, cart_y+h*0.08,
                             cart_x+w*0.17, cart_y+h*0.02,
                             cart_x+w*0.03, cart_y+h*0.02], width=dp(2))
                Line(points=[cart_x-w*0.04, cart_y+h*0.10,
                             cart_x, cart_y+h*0.08], width=dp(2))
                Ellipse(pos=(cart_x+w*0.04, cart_y-h*0.01), size=(dp(8), dp(8)))
                Ellipse(pos=(cart_x+w*0.14, cart_y-h*0.01), size=(dp(8), dp(8)))
                # Shelves
                for i in range(3):
                    Rectangle(pos=(w*0.62, h*0.36+i*h*0.06),
                              size=(w*0.30, dp(3)))

            elif btype == "Grocery Store":
                # Leaf/vegetable shapes
                for i, (lx, ly) in enumerate([(w*0.70,h*0.28),(w*0.82,h*0.20),
                                               (w*0.76,h*0.38)]):
                    Ellipse(pos=(lx, ly), size=(w*0.09, w*0.13))
                # Basket
                Line(points=[w*0.65,h*0.10, w*0.65,h*0.06,
                             w*0.88,h*0.06, w*0.88,h*0.10], width=dp(2))
                Line(ellipse=(w*0.65, h*0.05, w*0.23, h*0.10, 180, 360),
                     width=dp(2))

            elif btype == "Craft & Art":
                # Palette circle + paintbrush
                Ellipse(pos=(w*0.70, h*0.18), size=(w*0.18, w*0.18))
                Line(points=[w*0.82, h*0.38, w*0.92, h*0.28,
                             w*0.94, h*0.30, w*0.84, h*0.40], width=dp(3))
                # Color dots on palette
                for dx, dy in [(0.02,0.05),(0.10,0.02),(0.14,0.10),(0.06,0.14)]:
                    Ellipse(pos=(w*0.70+w*dx, h*0.18+w*dy),
                            size=(w*0.025, w*0.025))


# ── Base screen ───────────────────────────────────────────────────────────────

class CalcoraScreen(Screen):

    def make_page(self, title, show_back=True):
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1, 1),
                                    pos_hint={"x": 0, "y": 0}))
        page = BoxLayout(
            orientation="vertical",
            padding=[dp(16), dp(12), dp(16), dp(12)],
            spacing=dp(10),
            size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
        )
        root.add_widget(page)

        top_bar = BoxLayout(size_hint_y=None, height=ROW_H, spacing=dp(10))
        if show_back:
            top_bar.add_widget(self._back_btn())
        else:
            top_bar.add_widget(Widget(size_hint_x=None, width=BACK_W))
        top_bar.add_widget(Label(
            text=title, color=C_WHITE, bold=True, font_size=dp(22),
            halign="left", valign="middle",
        ))
        top_bar.add_widget(Widget(size_hint_x=None, width=BACK_W))
        page.add_widget(top_bar)

        self.add_widget(root)
        return page

    def _back_btn(self):
        btn = CalcoraButton(text="< Back", background_color=C_PANEL2,
                             size_hint=(None, None), size=(BACK_W, ROW_H))
        btn.bind(on_release=lambda *_: self._go_home())
        return btn

    def float_back_button(self):
        btn = CalcoraButton(text="< Back", background_color=C_PANEL2,
                             size_hint=(0.25, 0.07),
                             pos_hint={"x": 0.03, "top": 0.97})
        btn.bind(on_release=lambda *_: self._go_home())
        return btn

    def _go_home(self):
        self.manager.transition = SlideTransition(direction="right", duration=0.22)
        self.manager.current    = "worker_home" if SESSION.get("role") == "worker" else "home"

    def make_input(self, hint):
        return StyledInput(hint_text=hint, multiline=False,
                           size_hint_y=None, height=ROW_H)

    def on_pre_enter(self, *_):
        refresh = getattr(self, "refresh", None)
        if callable(refresh):
            refresh()


# ── Home ──────────────────────────────────────────────────────────────────────

class HomeScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_home()

    def refresh(self):
        """Rebuild home screen to reflect active store's data."""
        self.clear_widgets()
        self._build_home()

    def on_pre_enter(self, *_):
        self.refresh()

    def _build_home(self):
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1, 1),
                                    pos_hint={"x": 0, "y": 0}))

        # Decorative glow
        glow = Widget(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        with glow.canvas:
            Color(0.15, 0.47, 0.95, 0.06)
            Ellipse(pos=(dp(-60), dp(300)), size=(dp(360), dp(360)))
            Color(0.43, 0.20, 0.85, 0.05)
            Ellipse(pos=(dp(160), dp(-40)), size=(dp(280), dp(280)))
        root.add_widget(glow)

        content = BoxLayout(
            orientation="vertical",
            padding=[dp(24), dp(18), dp(24), dp(18)],
            spacing=dp(14),
            size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
        )
        root.add_widget(content)

        # Header: logo image on left + text on right
        header = BoxLayout(orientation="horizontal",
                           size_hint_y=None, height=dp(100), spacing=dp(10))

        logo = KivyImage(
            source=os.path.join(BASE_DIR, "calcora logo.png"),
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(None, None),
            size=(dp(90), dp(90)),
        )
        header.add_widget(logo)

        title_col = BoxLayout(orientation="vertical", spacing=dp(2))
        title_col.add_widget(Label(
            text="CALCORA",
            color=C_WHITE, bold=True, font_size=dp(24),
            halign="left", valign="middle",
        ))
        title_col.add_widget(Label(
            text="Smart Sales Engine",
            color=C_BLUE, font_size=dp(13), bold=True,
            halign="left", valign="middle",
        ))
        title_col.add_widget(Label(
            text="Calculate Less. Earn More.",
            color=C_GREEN, font_size=dp(12),
            halign="left", valign="middle",
        ))
        header.add_widget(title_col)
        content.add_widget(header)

        # Divider
        div = Widget(size_hint_y=None, height=dp(1))
        with div.canvas:
            Color(*C_BLUE[:3], 0.30)
            div._line = Rectangle(pos=div.pos, size=div.size)
        div.bind(pos=lambda w, v: setattr(w._line, "pos", v),
                 size=lambda w, v: setattr(w._line, "size", v))
        content.add_widget(div)

        # Business type badge — shows active store name + type
        btype = get_biz_type()
        cfg   = biz_config()
        stores_data = load_stores()
        app2 = App.get_running_app()
        if app2 and app2.active_store_id != "default":
            extra = stores_data.get("list", [])
            store_name = next((s["name"] for s in extra
                               if s["id"] == app2.active_store_id), btype)
        else:
            store_name = stores_data.get("default_name", "Main Store")

        badge_box = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        badge_pill = Label(
            text=f"  {cfg['icon']}  {store_name}  |  {btype}  ",
            color=C_WHITE, bold=True, font_size=dp(11),
            size_hint=(None, None), size=(dp(260), dp(30)),
        )
        with badge_pill.canvas.before:
            Color(*cfg["color"][:3], 0.85)
            badge_pill._bg = RoundedRectangle(
                pos=badge_pill.pos, size=badge_pill.size, radius=[dp(14)])
        badge_pill.bind(
            pos=lambda w,v: setattr(w._bg,"pos",v),
            size=lambda w,v: setattr(w._bg,"size",v))
        badge_box.add_widget(badge_pill)
        badge_box.add_widget(Widget())
        content.add_widget(badge_box)

        # Nav grid — colorful tiles per store
        nav_items = [
            ("Daily Sales",       "sales",   C_BLUE,                 False),
            ("Stock  [Owner]",    "stock",   C_PURPLE,               True),
            ("Finance  [Owner]",  "finance", C_GREEN,                True),
            ("Inventory",         "details", C_CYAN,                 False),
        ]
        grid = GridLayout(cols=2, rows=2, spacing=dp(12), size_hint_y=0.48)
        for label, screen, color, owner in nav_items:
            grid.add_widget(self._nav_tile(label, screen, color, owner))
        content.add_widget(grid)

        # Bottom row — History + Owner Dashboard
        bottom_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))
        hist_btn = CalcoraButton(text="History", background_color=C_PANEL2,
                                  size_hint=(1, 1))
        hist_btn.bind(on_release=lambda *_: self._go("history"))
        bottom_row.add_widget(hist_btn)

        # Owner Dashboard button (online)
        dash_btn = CalcoraButton(text="Dashboard", background_color=C_ORANGE,
                                  size_hint=(1, 1))
        dash_btn.bind(on_release=lambda *_: self._go("owner_dashboard"))
        bottom_row.add_widget(dash_btn)
        content.add_widget(bottom_row)

        self.add_widget(root)
        Clock.schedule_once(self._fade_in, 0.05)
        # Start notification polling and update bell
        if FB_AVAILABLE and fb and fb.is_online():
            fb.on_notification(self._on_notif_update)
            fb.start_polling(interval=30)

    def _nav_tile(self, label, screen, color, owner=False):
        fl = FloatLayout()
        with fl.canvas.before:
            # Dark panel base
            Color(*C_PANEL)
            fl._bg = RoundedRectangle(pos=fl.pos, size=fl.size, radius=[RADIUS])
            # Colored left strip
            Color(*color[:3], 0.95)
            fl._strip = RoundedRectangle(
                pos=fl.pos, size=(dp(6), 1), radius=[RADIUS, 0, 0, RADIUS])
            # Subtle colored top-right glow
            Color(*color[:3], 0.08)
            fl._glow = Ellipse(pos=fl.pos, size=(1, 1))
        def _s(w, *_):
            fl._bg.pos      = w.pos
            fl._bg.size     = w.size
            fl._strip.pos   = w.pos
            fl._strip.size  = (dp(6), w.height)
            fl._glow.pos    = (w.x + w.width*0.4, w.y + w.height*0.2)
            fl._glow.size   = (w.width*0.9, w.height*0.9)
        fl.bind(pos=_s, size=_s)

        display = label.replace("  [Owner]", "")
        lbl = Label(text=display, color=C_WHITE, bold=True,
                    halign="center", valign="middle",
                    size_hint=(1, 0.70), pos_hint={"x": 0, "top": 1},
                    font_size=dp(15))
        lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        fl.add_widget(lbl)

        if owner:
            lock_lbl = Label(
                text="Owner only",
                color=(*color[:3], 0.90), font_size=dp(10),
                halign="center", valign="middle",
                size_hint=(1, 0.28), pos_hint={"x": 0, "y": 0},
            )
            lock_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
            fl.add_widget(lock_lbl)

        btn = Button(background_normal="", background_color=(0,0,0,0),
                     background_down="",
                     size_hint=(1,1), pos_hint={"x":0,"y":0})
        btn.bind(on_release=lambda *_: self._go(screen))
        btn.bind(on_press=lambda *_: Animation(
            background_color=(*color[:3], 0.15), duration=0.08).start(btn))
        btn.bind(on_release=lambda *_: Animation(
            background_color=(0,0,0,0), duration=0.15).start(btn))
        fl.add_widget(btn)
        return fl

    def _on_notif_update(self, count):
        """Called when notification count changes."""
        pass  # Could update a badge label here

    def _fade_in(self, *_):
        for child in self.children:
            child.opacity = 0
            Animation(opacity=1, duration=0.45).start(child)

    def _go(self, screen_name):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current    = screen_name


# ── Stock ─────────────────────────────────────────────────────────────────────

class StockScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._unlocked = True
        self._do_build()

    def _build_locked(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(Label(
            text="Stock Management", color=C_WHITE, bold=True, font_size=dp(24),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.97},
        ))
        lock_box = BoxLayout(orientation="vertical", spacing=dp(16),
                             size_hint=(0.72, None), height=dp(200),
                             pos_hint={"center_x": 0.5, "center_y": 0.52})
        lock_box.add_widget(Label(
            text="[b]Stock is PIN Protected[/b]",
            markup=True, color=C_WHITE, font_size=dp(16),
            halign="center", size_hint_y=None, height=dp(30),
        ))
        unlock_btn = CalcoraButton(
            text="Enter PIN to Unlock",
            background_color=C_PURPLE,
            size_hint_y=None, height=BTN_H,
        )
        unlock_btn.bind(on_release=self._ask_pin)
        lock_box.add_widget(unlock_btn)
        if not load_pin():
            setup_btn = CalcoraButton(
                text="Set up PIN",
                background_color=C_GREEN,
                size_hint_y=None, height=BTN_H,
            )
            setup_btn.bind(on_release=self._setup_pin)
            lock_box.add_widget(setup_btn)
        root.add_widget(lock_box)
        self.add_widget(root)

    def _setup_pin(self, *_):
        pin_popup("Set a 4-digit Owner PIN",
                  on_success=lambda p: (save_pin(p), self._unlock()),
                  confirm=True)

    def _ask_pin(self, *_):
        if not load_pin():
            self._setup_pin()
            return
        pin_popup("Enter Owner PIN",
                  on_success=self._unlock,
                  on_cancel=lambda: None,
                  confirm=False)

    def _unlock(self, *_):
        self._unlocked = True
        self.clear_widgets()
        self._do_build()

    def _lock(self, *_):
        self._unlocked = False
        self._build_locked()

    def on_pre_enter(self, *_):
        self.clear_widgets()
        self._unlocked = True
        self._do_build()

    def _do_build(self):
        cfg  = biz_config()
        page = self.make_page("Stock Management", show_back=False)
        self._page_ref = page

        # Lock button row
        # Business type badge — shows store name + type
        btype = get_biz_type()
        stores_data2 = load_stores()
        app3 = App.get_running_app()
        if app3 and app3.active_store_id != "default":
            extra2 = stores_data2.get("list", [])
            sname2 = next((s["name"] for s in extra2
                           if s["id"] == app3.active_store_id), btype)
        else:
            sname2 = stores_data2.get("default_name", "Main Store")

        badge_row = BoxLayout(size_hint_y=None, height=dp(28))
        badge = Label(
            text=f"{cfg['icon']}  {sname2}  —  {btype}  ({cfg['desc']})",
            color=C_GREEN, font_size=dp(12), halign="left", valign="middle",
        )
        badge.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        badge_row.add_widget(badge)
        page.add_widget(badge_row)

        # Item name always shown
        self.item_input = self.make_input("Item name (e.g. Sugar 1kg)")
        page.add_widget(self.item_input)

        # Unit selector based on business type
        unit_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        unit_row.add_widget(Label(text="Unit:", color=C_GREY,
                                   size_hint_x=None, width=dp(44),
                                   font_size=dp(13), bold=True))
        self._sel_unit = cfg["units"][0]
        self._unit_btns = []
        unit_scroll = ScrollView(do_scroll_y=False, do_scroll_x=True)
        unit_box = BoxLayout(size_hint=(None,1), spacing=dp(6))
        unit_box.bind(minimum_width=unit_box.setter("width"))
        for u in cfg["units"]:
            is_sel = u == cfg["units"][0]
            btn = Button(
                text=u,
                background_normal="",
                background_down="",
                background_color=C_BLUE if is_sel else C_PANEL2,
                color=C_WHITE,
                bold=is_sel,
                font_size=dp(13),
                size_hint=(None, 1),
                width=dp(max(54, len(u)*10 + 20)),
            )
            with btn.canvas.before:
                btn._bc = Color(*btn.background_color)
                btn._br = RoundedRectangle(pos=btn.pos, size=btn.size,
                                            radius=[dp(8)])
            btn.bind(
                pos=lambda w,v: setattr(w._br,"pos",v),
                size=lambda w,v: setattr(w._br,"size",v),
                background_color=lambda w,v: setattr(w._bc,"rgba",v),
            )
            btn.bind(on_release=lambda b, un=u: self._pick_unit(un))
            unit_box.add_widget(btn)
            self._unit_btns.append((u, btn))
        unit_scroll.add_widget(unit_box)
        unit_row.add_widget(unit_scroll)
        page.add_widget(unit_row)

        # Quantity always shown
        self.qty_input = self.make_input("Quantity added")
        page.add_widget(self.qty_input)

        # Capital & buying price — only for types that need it
        self.capital_input = self.make_input("Total buying cost (optional)")
        self.price_input   = self.make_input("Buying price per unit")

        if cfg["needs_capital"]:
            page.add_widget(self.capital_input)
        if cfg["needs_unit_pb"]:
            page.add_widget(self.price_input)

        # Selling price — always shown
        self.sell_price_input = self.make_input("Selling price per unit")
        page.add_widget(self.sell_price_input)

        self.message = Label(color=C_GREEN, size_hint_y=None,
                             height=dp(60), halign="center", text="")
        self.message.bind(size=lambda w,*_: setattr(w,"text_size",w.size))

        actions = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(8))
        for text, color, cb in (
            ("Add Stock",   C_BLUE,  self._add_stock),
            ("Restock",     C_GREEN, self._restock),
            ("Delete",      C_ERROR, self._confirm_delete),
        ):
            btn = CalcoraButton(text=text, background_color=color)
            btn.bind(on_release=cb)
            actions.add_widget(btn)

        page.add_widget(actions)
        page.add_widget(self.message)

    def _pick_unit(self, unit):
        self._sel_unit = unit
        for u, btn in self._unit_btns:
            btn.background_color = C_BLUE if u == unit else C_PANEL2
            btn.bold = (u == unit)

    def refresh(self):
        self.clear_widgets()
        self._unlocked = True
        self._do_build()

    def _add_stock(self, *_):
        self._save(require_existing=False)

    def _restock(self, *_):
        self._save(require_existing=True)

    def _confirm_delete(self, *_):
        name = self.item_input.text.strip()
        if not name:
            self._msg("Enter an item name to delete.", error=True)
            return
        confirm_popup("Delete item",
                      f"Delete '{name}' from inventory?",
                      self._delete_item)

    def _msg(self, text, error=False):
        self.message.color   = C_ERROR if error else C_GREEN
        self.message.text    = text
        self.message.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.message)

    def _save(self, require_existing):
        app = App.get_running_app()
        cfg = biz_config()
        try:
            name       = self.item_input.text.strip()
            added_qty  = parse_number(self.qty_input.text)
            sell_price = parse_number(self.sell_price_input.text)
            if not name or added_qty <= 0 or sell_price <= 0:
                raise ValueError("basic")

            if cfg["needs_unit_pb"]:
                buying_price    = parse_number(self.price_input.text)
                entered_capital = parse_number(self.capital_input.text) \
                                  if cfg["needs_capital"] else 0
                added_capital   = (entered_capital if entered_capital > 0
                                   else added_qty * buying_price)
                if buying_price <= 0 and entered_capital <= 0:
                    raise ValueError("price")
                if buying_price <= 0:
                    buying_price = added_capital / added_qty
            else:
                # Craft/art — no buying cost
                buying_price  = 0
                added_capital = 0

        except ZeroDivisionError:
            self._msg("Invalid quantities.", error=True)
            return
        except ValueError as e:
            if "price" in str(e):
                self._msg("Enter buying price or total cost.", error=True)
            else:
                self._msg("Enter item name, quantity, and selling price.", error=True)
            return

        exists = name in app.inventory
        if require_existing and not exists:
            self._msg("Item not found. Use Add Stock first.", error=True)
            return
        if not require_existing and exists:
            self._msg("Item already exists. Use Restock instead.", error=True)
            return

        item = app.inventory.setdefault(name, {
            "quantity": 0, "capital": 0,
            "total_quantity_added": 0, "unit_pb": 0,
            "unit": "", "buying_price": 0, "sell_price": 0,
        })
        item["quantity"]             += added_qty
        item["capital"]              += added_capital
        item["total_quantity_added"] += added_qty
        item["unit_pb"]       = (item["capital"] / item["total_quantity_added"]
                                 if item["total_quantity_added"] else 0)
        item["unit"]          = self._sel_unit
        item["buying_price"]  = buying_price
        item["sell_price"]    = sell_price

        action = "restocked" if require_existing else "added"
        if cfg["needs_unit_pb"]:
            self._msg(f"{name} {action}.  Stock: {added_qty:g} {self._sel_unit}  |  "
                      f"Buy: {app.currency()} {money(buying_price)}  "
                      f"Sell: {app.currency()} {money(sell_price)}")
        else:
            self._msg(f"{name} {action}.  Stock: {added_qty:g} {self._sel_unit}  |  "
                      f"Price: {app.currency()} {money(sell_price)}")
        app.save_data()

        # Stock notifications: low stock, stock over, capital status
        store_name = ""
        try:
            with open(app.active_profile_file(), "r", encoding="utf-8") as f:
                store_name = json.load(f).get("store_name", "")
        except Exception:
            pass
        if not store_name:
            store_name = "Your Store"
        if item["quantity"] > 0:
            if item.get("capital", 0) > 0:
                send_app_notification(app.active_store_id,
                                      _format_notification_text(
                                          "Stock over", name, store_name,
                                          "(capital accumulated)"))
            else:
                send_app_notification(app.active_store_id,
                                      _format_notification_text(
                                          "Stock over", name, store_name,
                                          "(capital not accumulated)"))
        if item["quantity"] <= max(1, item["total_quantity_added"] * 0.25):
            send_app_notification(app.active_store_id,
                                  _format_notification_text(
                                      "Low stock", name, store_name))

    def _delete_item(self):
        app  = App.get_running_app()
        name = self.item_input.text.strip()
        if name in app.inventory:
            del app.inventory[name]
            self._msg(f"{name} deleted.")
            app.save_data()
        else:
            self._msg("Item not found.", error=True)



# ── Sales table row ───────────────────────────────────────────────────────────

class SalesTableRow(BoxLayout):
    def __init__(self, on_change, **kwargs):
        super().__init__(orientation="horizontal", spacing=dp(3),
                         size_hint_y=None, height=dp(44), **kwargs)
        self.on_change = on_change

        self.date_in  = self._cell(today_short(), prefill=True)
        self.item_in  = self._cell("Item")
        self.qty_in   = self._cell("Qty")
        self.price_in = self._cell("Price")
        self.total_in = self._cell("Total", readonly=True)

        for f in (self.date_in, self.item_in, self.qty_in,
                  self.price_in, self.total_in):
            self.add_widget(f)

        self.qty_in.bind(text=lambda *_: self._recalc())
        self.price_in.bind(text=lambda *_: self._recalc())

    def _cell(self, hint, readonly=False, prefill=False):
        inp = StyledInput(
            hint_text=hint,
            text=hint if prefill else "",
            readonly=readonly,
            multiline=False,
            size_hint_x=1,
            padding=[dp(6), dp(10)],
            font_size=dp(13),
        )
        if readonly:
            inp.background_color = C_PANEL
            inp.foreground_color = C_GREEN
        return inp

    def _recalc(self):
        amt = self.amount()
        self.total_in.text = money(amt) if amt else ""
        self.on_change()

    def amount(self):
        return parse_number(self.qty_in.text) * parse_number(self.price_in.text)

    def is_empty(self):
        return (not self.item_in.text.strip()
                and not self.qty_in.text.strip()
                and not self.price_in.text.strip())

    def data(self):
        return {
            "date":     self.date_in.text.strip(),
            "item":     self.item_in.text.strip(),
            "quantity": parse_number(self.qty_in.text),
            "price":    parse_number(self.price_in.text),
            "amount":   self.amount(),
        }


# ── Sales screen ──────────────────────────────────────────────────────────────

class SalesScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        page = self.make_page("Daily Sales")
        page.spacing = dp(6)
        self.rows    = []
        self.message = Label(color=C_ERROR, size_hint_y=None, height=dp(36),
                             halign="center")

        self.table = BoxLayout(orientation="vertical", spacing=dp(3),
                               size_hint_y=None)
        self.table.bind(minimum_height=self.table.setter("height"))
        self.table.add_widget(self._header())

        for _ in range(5):
            self._add_row()

        scroll = ScrollView(size_hint_y=1)
        scroll.add_widget(self.table)
        page.add_widget(scroll)

        self.total_bar = StyledInput(
            text="", readonly=True, multiline=False,
            foreground_color=C_GREEN, background_color=C_PANEL,
            size_hint_y=None, height=dp(52),
            halign="center",
            font_size=dp(16),
        )
        page.add_widget(self.total_bar)

        btn_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))
        add_btn = CalcoraButton(text="+ Add Row", background_color=C_BLUE)
        add_btn.bind(on_release=lambda *_: self._add_row())
        sub_btn = CalcoraButton(text="Submit & Calculate", background_color=C_PURPLE)
        sub_btn.bind(on_release=self._submit)
        btn_row.add_widget(add_btn)
        btn_row.add_widget(sub_btn)
        page.add_widget(btn_row)
        page.add_widget(self.message)
        self._update_total()

    def _header(self):
        hdr = BoxLayout(orientation="horizontal", spacing=dp(3),
                        size_hint_y=None, height=HDR_H)
        with hdr.canvas.before:
            Color(*C_PANEL2)
            hdr._hbg = RoundedRectangle(pos=hdr.pos, size=hdr.size, radius=[dp(8)])
        hdr.bind(pos=lambda w, v: setattr(w._hbg, "pos",  v),
                 size=lambda w, v: setattr(w._hbg, "size", v))
        for text in ("Date", "Item", "Qty", "Price", "Total"):
            hdr.add_widget(Label(text=text, color=C_GREEN, bold=True,
                                 halign="center", valign="middle"))
        return hdr

    def _add_row(self):
        row = SalesTableRow(self._update_total)
        row.opacity = 0
        self.rows.append(row)
        self.table.add_widget(row)
        Animation(opacity=1, duration=0.2).start(row)
        self._update_total()

    def _msg(self, text, error=False):
        self.message.color   = C_ERROR if error else C_GREEN
        self.message.text    = text
        self.message.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.message)

    def _submit(self, *_):
        app  = App.get_running_app()
        rows = [r.data() for r in self.rows if not r.is_empty()]
        if not rows:
            self._msg("No daily sales to archive yet.", error=True)
            return

        requested = {}
        for row in rows:
            if not row["item"] or row["quantity"] <= 0 or row["price"] <= 0:
                self._msg("Every filled row needs Item, Qty, and Price.", error=True)
                return
            requested[row["item"]] = requested.get(row["item"], 0) + row["quantity"]

        for item_name, qty in requested.items():
            if item_name not in app.inventory:
                self._msg(f"'{item_name}' is not in Stock.", error=True)
                return
            if app.inventory[item_name]["quantity"] < qty:
                self._msg(f"Not enough stock for '{item_name}'.", error=True)
                return

        for row in rows:
            si                  = app.inventory[row["item"]]
            bp                  = si.get("buying_price", si.get("unit_pb", 0))
            row["buying_price"] = bp
            row["capital"]      = row["quantity"] * bp
            row["gross_profit"] = (row["price"] - bp) * row["quantity"]
            row["tax"]          = row["gross_profit"] * VAT_RATE
            row["net_profit"]   = row["gross_profit"] - row["tax"]
            si["quantity"]     -= row["quantity"]
            app.all_sales.append(row)

        subtotal = sum(r["amount"] for r in rows)
        app.history.append({"rows": rows, "subtotal": subtotal})
        self._reset()
        self._msg("Daily sheet saved, stock deducted, and finance updated.")
        app.save_data()

        # If worker — push to Firebase so owner gets notified
        if FB_AVAILABLE and fb and fb.is_online() and SESSION.get("role") == "worker":
            store_id    = SESSION.get("store_id") or ""
            worker_name = SESSION.get("worker_name") or "Worker"
            worker_id   = SESSION.get("worker_id") or ""
            if store_id:
                def _push():
                    fb.push_sales_sheet(store_id, rows, subtotal,
                                        worker_name, worker_id)
                threading.Thread(target=_push, daemon=True).start()
                self._msg("Sales saved and owner notified!")

    def _reset(self):
        self.rows.clear()
        self.table.clear_widgets()
        self.table.add_widget(self._header())
        for _ in range(5):
            self._add_row()
        self._update_total()

    def _update_total(self):
        if not hasattr(self, "total_bar"):
            return
        total = sum(r.amount() for r in self.rows)
        self.total_bar.text = (f"  TOTAL EARNED:  UGX {money(total)}"
                               if total else "")

    def refresh(self):
        self._update_total()


# ── Inventory row ─────────────────────────────────────────────────────────────

class InventoryRow(Button):
    def __init__(self, item_name, qty_text, pct_text, on_select, **kwargs):
        super().__init__(
            text=f"  {item_name}        {qty_text}        {pct_text}",
            size_hint_y=None, height=dp(50),
            background_normal="", background_color=C_PANEL,
            background_down="",
            color=C_WHITE, halign="left", valign="middle",
            **kwargs,
        )
        self.item_name = item_name
        self.bind(on_release=lambda *_: on_select(self.item_name))

    def on_size(self, *_):
        self.text_size = self.size
        self.font_size = min(self.width * 0.048, dp(16))

    def on_press(self):
        Animation(background_color=(*C_BLUE[:3], 0.30), duration=0.08).start(self)

    def on_release(self):
        Animation(background_color=C_PANEL, duration=0.15).start(self)


# ── Item info box ─────────────────────────────────────────────────────────────

class ItemInfoBox(PanelBox):
    def __init__(self, title, value, **kwargs):
        super().__init__(orientation="vertical", padding=dp(8), spacing=dp(2),
                         **kwargs)
        self.tlbl = Label(text=title, color=C_GREEN, bold=True,
                          halign="center", valign="middle")
        self.vlbl = Label(text=value, color=C_WHITE,
                          halign="center", valign="middle")
        self.add_widget(self.tlbl)
        self.add_widget(self.vlbl)

    def on_size(self, *_):
        self.tlbl.text_size = self.tlbl.size
        self.vlbl.text_size = self.vlbl.size
        fs = min(self.width * 0.11, self.height * 0.24, dp(16))
        self.tlbl.font_size = fs
        self.vlbl.font_size = fs


class SummaryCard(PanelBox):
    """Compact summary card used in Owner Dashboard top row."""
    def __init__(self, title, value="—", **kwargs):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(4), **kwargs)
        self.tlbl = Label(text=title, color=C_GREY, bold=True,
                          halign="center", valign="middle")
        self.vlbl = Label(text=value, color=C_WHITE, bold=True,
                          halign="center", valign="middle")
        self.add_widget(self.tlbl)
        self.add_widget(self.vlbl)

    def on_size(self, *_):
        w, h = self.size
        self.tlbl.size_hint_y = None
        self.tlbl.height = dp(24)
        self.tlbl.text_size = (max(dp(60), w - dp(20)), self.tlbl.height)
        self.vlbl.text_size = (max(dp(60), w - dp(20)), max(dp(24), h - dp(42)))
        self.tlbl.font_size = min(dp(14), max(dp(12), w * 0.05))
        self.vlbl.font_size = min(dp(24), max(dp(16), w * 0.08))
        self.tlbl.valign = "middle"
        self.vlbl.valign = "middle"


# ── Details / Inventory screen ────────────────────────────────────────────────

class DetailsScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.page      = FloatLayout()
        self._debounce = None
        self.add_widget(self.page)

    def refresh(self):
        self._build_list()

    def _build_list(self):
        self.page.clear_widgets()
        self.page.add_widget(GradientBG(size_hint=(1, 1),
                                         pos_hint={"x": 0, "y": 0}))
        self.page.add_widget(self.float_back_button())
        self.page.add_widget(Label(
            text="Inventory", color=C_WHITE, bold=True, font_size=dp(26),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.93},
        ))

        self.search = StyledInput(
            hint_text="Search items...", multiline=False,
            size_hint=(0.88, 0.07),
            pos_hint={"center_x": 0.5, "top": 0.82},
        )
        self.search.bind(text=self._on_search)
        self.page.add_widget(self.search)

        self.list_box = BoxLayout(orientation="vertical", spacing=dp(3),
                                   size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll = ScrollView(size_hint=(0.92, 0.50),
                            pos_hint={"center_x": 0.5, "top": 0.73})
        scroll.add_widget(self.list_box)
        self.page.add_widget(scroll)

        rst = CalcoraButton(text="Clear Search", background_color=C_PANEL2,
                             size_hint=(0.40, 0.07),
                             pos_hint={"center_x": 0.5, "y": 0.09})
        rst.bind(on_release=self._reset_search)
        self.page.add_widget(rst)
        self._populate()

    def _on_search(self, *_):
        if self._debounce:
            self._debounce.cancel()
        self._debounce = Clock.schedule_once(lambda dt: self._populate(), 0.25)

    def _reset_search(self, *_):
        self.search.text = ""
        self._populate()

    def _populate(self):
        app   = App.get_running_app()
        self.list_box.clear_widgets()
        query = self.search.text.strip().lower()
        items = [(n, i) for n, i in app.inventory.items()
                 if not query or query in n.lower()]

        sold_by = {}
        for row in app.all_sales:
            sold_by[row["item"]] = sold_by.get(row["item"], 0) + row["quantity"]
        total_sold = sum(sold_by.values())

        if not items:
            self.list_box.add_widget(Label(
                text="No inventory items yet.",
                color=C_GREY, size_hint_y=None, height=dp(48),
            ))
            return

        for name, item in items:
            unit  = item.get("unit", "")
            qty_t = f"{item['quantity']:g}{unit}"
            pct   = (sold_by.get(name, 0) / total_sold * 100) if total_sold else 0
            r     = InventoryRow(name, qty_t, f"{pct:.0f}%", self._show_detail)
            r.opacity = 0
            self.list_box.add_widget(r)
            Animation(opacity=1, duration=0.18).start(r)

    def _show_detail(self, item_name):
        app  = App.get_running_app()
        item = app.inventory[item_name]
        data = app.item_math(item_name)
        unit = item.get("unit", "")

        self.page.clear_widgets()
        self.page.add_widget(GradientBG(size_hint=(1, 1),
                                         pos_hint={"x": 0, "y": 0}))

        back = CalcoraButton(text="< Inventory", background_color=C_PANEL2,
                              size_hint=(0.32, 0.07),
                              pos_hint={"x": 0.03, "top": 0.97})
        back.bind(on_release=lambda *_: self._build_list())
        self.page.add_widget(back)

        self.page.add_widget(Label(
            text=item_name, color=C_WHITE, bold=True, font_size=dp(24),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.93},
        ))

        boxes = [
            ("Capital",   money(item.get("capital", 0)), {"x": 0.05, "top": 0.74}),
            ("Cap. Acc.", money(data["capital"]),          {"x": 0.05, "top": 0.57}),
            ("In Stock",  f"{item['quantity']:g}{unit}",  {"center_x": 0.5, "top": 0.74}),
            ("Profit",    money(data["net_profit"]),       {"right": 0.95, "top": 0.74}),
            ("Taxes",     money(data["tax"]),              {"center_x": 0.5, "top": 0.57}),
            ("Revenue",   money(data["revenue"]),          {"right": 0.95, "top": 0.57}),
        ]
        for title, value, pos in boxes:
            box = ItemInfoBox(title, f"UGX {value}",
                              size_hint=(0.27, 0.14), pos_hint=pos)
            box.opacity = 0
            self.page.add_widget(box)
            Animation(opacity=1, duration=0.25).start(box)

        self.page.add_widget(Label(
            text=f"Sales share:  {data['percentage']:.0f}%",
            color=C_BLUE, font_size=dp(18), bold=True,
            size_hint=(0.85, 0.07),
            pos_hint={"center_x": 0.5, "center_y": 0.36},
        ))
        rec = stock_recommendation(item)
        self.page.add_widget(Label(
            text=f"Recommendation:  {rec}",
            color=C_GREEN, font_size=dp(16),
            size_hint=(0.90, 0.09),
            pos_hint={"center_x": 0.5, "center_y": 0.26},
        ))



# ── PIN helpers ───────────────────────────────────────────────────────────────

def save_pin(pin):
    app = App.get_running_app()
    pf  = app.active_pin_file() if app else PIN_FILE
    try:
        with open(pf, "w", encoding="utf-8") as f:
            json.dump({"pin": hash_pw(pin)}, f)
    except OSError:
        pass

def load_pin():
    app = App.get_running_app()
    pf  = app.active_pin_file() if app else PIN_FILE
    try:
        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f:
                return json.load(f).get("pin", "")
    except Exception:
        pass
    return ""

def check_pin(pin):
    stored = load_pin()
    return stored and hash_pw(pin) == stored


def pin_popup(title, on_success, on_cancel=None, confirm=False, worker_mode=False):
    """Show a PIN entry popup. If confirm=True, asks for PIN twice (setup)."""
    content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(20))
    with content.canvas.before:
        Color(*C_PANEL)
        content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                        radius=[dp(14)])
    content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                 size=lambda w,v: setattr(w._bg,"size",v))

    content.add_widget(Label(
        text=title, color=C_WHITE, bold=True,
        font_size=dp(16), halign="center",
        size_hint_y=None, height=dp(32),
    ))

    # PIN dots display
    dot_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(10))
    dot_row.add_widget(Widget())
    dots = []
    for _ in range(4):
        d = Label(text="○", color=C_GREY, font_size=dp(22))
        dots.append(d)
        dot_row.add_widget(d)
    dot_row.add_widget(Widget())
    content.add_widget(dot_row)

    pin_val = [""]

    def _update_dots():
        for i, d in enumerate(dots):
            d.text  = "●" if i < len(pin_val[0]) else "○"
            d.color = C_GREEN if i < len(pin_val[0]) else C_GREY

    msg = Label(text="", color=C_ERROR, font_size=dp(12),
                halign="center", size_hint_y=None, height=dp(24))
    msg.bind(size=lambda w,*_: setattr(w,"text_size",w.size))

    popup = Popup(
        title="", content=content,
        size_hint=(0.82, None), height=dp(420),
        auto_dismiss=False,
        background_color=(*C_PANEL[:3], 1),
        separator_height=0,
    )

    confirm_val = [""]

    def _press(digit):
        if len(pin_val[0]) < 4:
            pin_val[0] += digit
            _update_dots()
            if len(pin_val[0]) == 4:
                Clock.schedule_once(lambda *_: _submit(), 0.15)

    def _backspace():
        pin_val[0] = pin_val[0][:-1]
        _update_dots()

    def _submit():
        if worker_mode:
            # Just capture whatever PIN is entered — no stored PIN check
            popup.dismiss()
            on_success(pin_val[0])
        elif confirm:
            if not confirm_val[0]:
                # First entry — ask to confirm
                confirm_val[0] = pin_val[0]
                pin_val[0] = ""
                _update_dots()
                msg.text  = "Re-enter PIN to confirm"
                msg.color = C_GREEN
            else:
                if pin_val[0] == confirm_val[0]:
                    popup.dismiss()
                    on_success(pin_val[0])
                else:
                    confirm_val[0] = ""
                    pin_val[0]     = ""
                    _update_dots()
                    msg.text  = "PINs don't match. Try again."
                    msg.color = C_ERROR
        else:
            if check_pin(pin_val[0]):
                popup.dismiss()
                on_success()
            else:
                pin_val[0] = ""
                _update_dots()
                msg.text  = "Wrong PIN. Try again."
                msg.color = C_ERROR

    content.add_widget(msg)

    # Numpad
    numpad = GridLayout(cols=3, spacing=dp(8), size_hint_y=None, height=dp(220))
    for digit in ("1","2","3","4","5","6","7","8","9","","0","⌫"):
        if digit == "":
            numpad.add_widget(Widget())
        elif digit == "⌫":
            btn = CalcoraButton(text="⌫", background_color=C_PANEL2, font_size=dp(20))
            btn.bind(on_release=lambda *_: _backspace())
            numpad.add_widget(btn)
        else:
            btn = CalcoraButton(text=digit, background_color=C_PANEL2, font_size=dp(20))
            btn.bind(on_release=lambda b, d=digit: _press(d))
            numpad.add_widget(btn)
    content.add_widget(numpad)

    cancel_btn = CalcoraButton(text="Cancel", background_color=C_PANEL2,
                                size_hint_y=None, height=dp(40))
    def _cancel(*_):
        popup.dismiss()
        if on_cancel:
            on_cancel()
    cancel_btn.bind(on_release=_cancel)
    content.add_widget(cancel_btn)

    popup.open()


# ── Finance box ───────────────────────────────────────────────────────────────

class FinanceBox(PanelBox):
    def __init__(self, title, accent=None, **kwargs):
        ac = accent or C_BLUE
        super().__init__(orientation="vertical", padding=dp(8), spacing=dp(2),
                         border_color=ac, **kwargs)
        self.value_text = ""
        self.tlbl = Label(text=title, color=ac, bold=True,
                          halign="center", valign="middle",
                          size_hint_y=0.45, shorten=True, shorten_from="right")
        self.vlbl = Label(text="", color=C_WHITE, bold=True,
                          halign="center", valign="middle",
                          size_hint_y=0.55, shorten=True, shorten_from="right")
        self.add_widget(self.tlbl)
        self.add_widget(self.vlbl)
        self.tlbl.bind(size=lambda *_: self._upd())
        self.vlbl.bind(size=lambda *_: self._upd())

    def set_value(self, value):
        self.value_text = value
        self.vlbl.text  = value
        Animation(opacity=0, duration=0.1).start(self.vlbl)
        Clock.schedule_once(
            lambda *_: Animation(opacity=1, duration=0.25).start(self.vlbl), 0.1)
        self._upd()

    def on_size(self, *_):
        self._upd()

    def _upd(self):
        self.tlbl.text_size = self.tlbl.size
        self.vlbl.text_size = self.vlbl.size
        self.tlbl.font_size = max(dp(12), min(
            self.width * 0.085, self.height * 0.22, dp(18)))
        vl = max(len(self.value_text), 1)
        self.vlbl.font_size = max(dp(11), min(
            self.width / (vl * 0.60), self.height * 0.24, dp(20)))


# ── Finance screen ────────────────────────────────────────────────────────────

class FinanceScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._unlocked = False
        self._build_locked()

    def _build_locked(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(self.float_back_button())
        root.add_widget(Label(
            text="Finance", color=C_WHITE, bold=True, font_size=dp(28),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.97},
        ))
        lock_box = BoxLayout(orientation="vertical", spacing=dp(16),
                             size_hint=(0.7, None), height=dp(220),
                             pos_hint={"center_x": 0.5, "center_y": 0.50})
        lock_box.add_widget(Label(
            text="[b]Finance is PIN Protected[/b]",
            markup=True, color=C_WHITE, font_size=dp(16),
            halign="center", size_hint_y=None, height=dp(30),
        ))
        unlock_btn = CalcoraButton(
            text="Enter PIN to Unlock",
            background_color=C_BLUE,
            size_hint_y=None, height=BTN_H,
        )
        unlock_btn.bind(on_release=self._ask_pin)
        lock_box.add_widget(unlock_btn)
        if not load_pin():
            setup_btn = CalcoraButton(
                text="Set up PIN",
                background_color=C_GREEN,
                size_hint_y=None, height=BTN_H,
            )
            setup_btn.bind(on_release=self._setup_pin)
            lock_box.add_widget(setup_btn)
        root.add_widget(lock_box)
        self.add_widget(root)

    def _setup_pin(self, *_):
        pin_popup("Set a 4-digit Finance PIN",
                  on_success=lambda p: (save_pin(p), self._unlock()),
                  confirm=True)

    def _ask_pin(self, *_):
        if not load_pin():
            self._setup_pin()
            return
        pin_popup("Enter Finance PIN",
                  on_success=self._unlock,
                  on_cancel=lambda: None,
                  confirm=False)

    def _unlock(self, *_):
        self._unlocked = True
        self._build_finance()

    def _lock(self, *_):
        self._unlocked = False
        self._build_locked()

    def _build_finance(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(self.float_back_button())
        lock_btn = CalcoraButton(
            text="Lock", background_color=C_PANEL2,
            size_hint=(0.22, 0.07),
            pos_hint={"right": 0.97, "top": 0.97},
            font_size=dp(12),
        )
        lock_btn.bind(on_release=self._lock)
        root.add_widget(lock_btn)
        root.add_widget(Label(
            text="Finance", color=C_WHITE, bold=True, font_size=dp(28),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.97},
        ))
        self.revenue_box = FinanceBox("Total Revenue", accent=C_BLUE,
                                      size_hint=(0.65, 0.17),
                                      pos_hint={"center_x": 0.5, "top": 0.82})
        self.tax_box     = FinanceBox("Taxes (VAT)", accent=C_ERROR,
                                      size_hint=(0.42, 0.18),
                                      pos_hint={"x": 0.04, "center_y": 0.50})
        self.profit_box  = FinanceBox("Net Profit", accent=C_GREEN,
                                      size_hint=(0.42, 0.18),
                                      pos_hint={"right": 0.96, "center_y": 0.50})
        for box in (self.revenue_box, self.tax_box, self.profit_box):
            root.add_widget(box)
        rst = CalcoraButton(
            text="Reset All Finance Data",
            background_color=(0.65, 0.10, 0.10, 1),
            size_hint=(0.52, 0.08),
            pos_hint={"center_x": 0.5, "y": 0.10},
        )
        rst.bind(on_release=self._confirm_reset)
        root.add_widget(rst)
        chg = CalcoraButton(
            text="Change PIN", background_color=C_PANEL2,
            size_hint=(0.38, 0.07),
            pos_hint={"center_x": 0.5, "y": 0.02},
            font_size=dp(12),
        )
        chg.bind(on_release=self._setup_pin)
        root.add_widget(chg)
        self.add_widget(root)
        self.refresh()

    def on_pre_enter(self, *_):
        self._unlocked = False
        self._build_locked()

    def refresh(self):
        if not self._unlocked:
            return
        app    = App.get_running_app()
        totals = app.finance_math()
        cur    = app.currency()
        self.revenue_box.set_value(
            f"{cur} {money(totals['revenue'])}"    if totals["revenue"]    else "—")
        self.tax_box.set_value(
            f"{cur} {money(totals['tax'])}"        if totals["tax"]        else "—")
        self.profit_box.set_value(
            f"{cur} {money(totals['net_profit'])}" if totals["net_profit"] else "—")

    def _confirm_reset(self, *_):
        confirm_popup("Reset Finance",
                      "This will erase all sales and history. Continue?",
                      self._do_reset)

    def _do_reset(self):
        app = App.get_running_app()
        app.all_sales.clear()
        app.history.clear()
        app.save_data()
        self.refresh()



# ── History screen ────────────────────────────────────────────────────────────

class HistoryScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        page = self.make_page("History")
        self.hist_box = BoxLayout(orientation="vertical", spacing=dp(14),
                                   size_hint_y=None)
        self.hist_box.bind(minimum_height=self.hist_box.setter("height"))
        scroll = ScrollView()
        scroll.add_widget(self.hist_box)
        page.add_widget(scroll)

    def refresh(self):
        app = App.get_running_app()
        self.hist_box.clear_widgets()
        if not app.history:
            self.hist_box.add_widget(Label(
                text="No archived daily sheets yet.",
                color=C_GREY, size_hint_y=None, height=dp(48),
            ))
            return

        for index, entry in enumerate(reversed(app.history), start=1):
            num   = len(app.history) - index + 1
            sheet = PanelBox(orientation="vertical", spacing=dp(3),
                             size_hint_y=None, padding=dp(8))
            sheet.height = (len(entry["rows"]) + 3) * dp(42)

            sheet.add_widget(Label(
                text=f"Daily Sheet  #{num}",
                color=C_GREEN, bold=True,
                size_hint_y=None, height=dp(34), halign="left",
            ))

            hdr = BoxLayout(orientation="horizontal", spacing=dp(2),
                            size_hint_y=None, height=HDR_H)
            for txt in ("Date", "Item", "Qty", "Price", "Total"):
                hdr.add_widget(Label(text=txt, color=C_GREY, bold=True,
                                     halign="center", valign="middle"))
            sheet.add_widget(hdr)

            for row in entry["rows"]:
                tr = GridLayout(cols=5, spacing=dp(2),
                                size_hint_y=None, height=dp(40))
                for val in (row.get("date", ""), row["item"],
                            f"{row['quantity']:g}",
                            money(row["price"]), money(row["amount"])):
                    tr.add_widget(StyledInput(
                        text=val, readonly=True, multiline=False,
                        halign="center", padding=[dp(4), dp(8)],
                        font_size=dp(13), background_color=C_PANEL2,
                    ))
                sheet.add_widget(tr)

            sheet.add_widget(StyledInput(
                text=f"  TOTAL:  UGX {money(entry['subtotal'])}",
                readonly=True, multiline=False,
                foreground_color=C_GREEN, background_color=C_PANEL2,
                size_hint_y=None, height=dp(44),
                halign="center", font_size=dp(15),
            ))
            self.hist_box.add_widget(sheet)


# ── App ───────────────────────────────────────────────────────────────────────



# ── Auth helpers ──────────────────────────────────────────────────────────────

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_auth():
    if not os.path.exists(AUTH_FILE):
        return None
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_auth(data):
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ── Signup screen ─────────────────────────────────────────────────────────────


# ── Role selection screen ──────────────────────────────────────────────────────

class RoleSelectScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        card = BoxLayout(orientation="vertical", spacing=dp(20),
                         padding=[dp(30),dp(20),dp(30),dp(20)],
                         size_hint=(0.92, None),
                         pos_hint={"center_x":0.5,"center_y":0.52})
        card.bind(minimum_height=card.setter("height"))
        with card.canvas.before:
            Color(*C_PANEL)
            card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(20)])
        card.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        logo = CalcoraLogo(size_hint=(1,None), height=dp(80),
                           allow_stretch=True, keep_ratio=True)
        card.add_widget(logo)
        card.add_widget(Label(text="Who are you?", color=C_WHITE, bold=True,
                              font_size=dp(22), halign="center",
                              size_hint_y=None, height=dp(36)))
        card.add_widget(Label(text="Select your role to continue",
                              color=C_GREY, font_size=dp(13), halign="center",
                              size_hint_y=None, height=dp(24)))
        # Owner button
        ob = CalcoraButton(text="I am an Owner",
                           background_color=C_BLUE,
                           size_hint_y=None, height=dp(58), font_size=dp(17))
        ob.bind(on_release=lambda *_: self._go("login"))
        card.add_widget(ob)
        card.add_widget(Label(text="Full access  •  Analytics  •  Manage workers",
                              color=C_GREY, font_size=dp(11), halign="center",
                              size_hint_y=None, height=dp(22)))
        # Worker button
        wb = CalcoraButton(text="I am a Worker",
                           background_color=C_PURPLE,
                           size_hint_y=None, height=dp(58), font_size=dp(17))
        wb.bind(on_release=lambda *_: self._go("worker_login"))
        card.add_widget(wb)
        card.add_widget(Label(text="Sales  •  Stock  •  Inventory  •  Store code + PIN",
                              color=C_GREY, font_size=dp(11), halign="center",
                              size_hint_y=None, height=dp(22)))
        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(card)
        root.add_widget(scroll)
        self.add_widget(root)

    def _go(self, s):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current = s


# ── Google Auth Helpers ────────────────────────────────────────────────────────

def google_auth_login():
    """Placeholder for Google OAuth login. Requires google-auth-oauthlib setup."""
    return False, "Google Sign-In setup required. Contact support or try email/password login."

def google_auth_signup(email=None):
    """Placeholder for Google OAuth signup. Requires google-auth-oauthlib setup."""
    return False, "Google Sign-Up setup required. Contact support or create account manually."

# ── Owner Signup ───────────────────────────────────────────────────────────────

class SignupScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        card = BoxLayout(orientation="vertical", padding=[dp(24),dp(20),dp(24),dp(20)],
                         spacing=dp(12), size_hint=(0.93,None),
                         pos_hint={"center_x":0.5,"center_y":0.50})
        card.bind(minimum_height=card.setter("height"))
        with card.canvas.before:
            Color(*C_PANEL)
            card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(18)])
        card.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        logo = CalcoraLogo(size_hint=(1,None), height=dp(70),
                           allow_stretch=True, keep_ratio=True)
        card.add_widget(logo)
        card.add_widget(Label(text="Create Owner Account", color=C_WHITE, bold=True,
                              font_size=dp(18), halign="center",
                              size_hint_y=None, height=dp(30)))
        # Country
        COUNTRIES = [("Uganda","UGX","UG"),("Tanzania","TZS","TZ"),("Kenya","KES","KE")]
        self._countries = COUNTRIES; self._sel_country = 0
        c_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self._c_btns = []
        for i,(country,cur,code) in enumerate(COUNTRIES):
            btn = CalcoraButton(text=f"{country}\n{cur}",
                                background_color=C_BLUE if i==0 else C_PANEL2,
                                font_size=dp(11))
            btn.bind(on_release=lambda b,idx=i: self._sel_c(idx))
            c_row.add_widget(btn); self._c_btns.append(btn)
        card.add_widget(c_row)
        # Store name
        card.add_widget(Label(text="Main Store Name", color=C_GREY,
                              font_size=dp(11), halign="left",
                              size_hint_y=None, height=dp(18)))
        self.f_store_name = StyledInput(hint_text="e.g. Mama Grace Shop",
                                         multiline=False, size_hint_y=None, height=ROW_H)
        card.add_widget(self.f_store_name)
        # Business type
        card.add_widget(Label(text="Store Type", color=C_GREY,
                              font_size=dp(11), halign="left",
                              size_hint_y=None, height=dp(18)))
        self._sel_biz = list(BUSINESS_TYPES.keys())[0]; self._biz_btns = []
        biz_scroll = ScrollView(size_hint_y=None, height=dp(88),
                                do_scroll_y=False, do_scroll_x=True)
        biz_row = BoxLayout(size_hint=(None,1), spacing=dp(8))
        biz_row.bind(minimum_width=biz_row.setter("width"))
        for name,cfg in BUSINESS_TYPES.items():
            btn = CalcoraButton(text=f"{cfg['icon']}\n{name}",
                                background_color=C_BLUE if name==self._sel_biz else C_PANEL2,
                                size_hint=(None,1), width=dp(110), font_size=dp(11))
            btn.bind(on_release=lambda b,n=name: self._sel_biz_type(n))
            biz_row.add_widget(btn); self._biz_btns.append((name,btn))
        biz_scroll.add_widget(biz_row); card.add_widget(biz_scroll)
        self.biz_desc_lbl = Label(text=BUSINESS_TYPES[self._sel_biz]["desc"],
                                   color=C_GREEN, font_size=dp(11), halign="center",
                                   size_hint_y=None, height=dp(20))
        self.biz_desc_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        card.add_widget(self.biz_desc_lbl)
        # Fields
        self.f_business = StyledInput(hint_text="Owner / Business Name",
                                       multiline=False, size_hint_y=None, height=ROW_H)
        self.f_email    = StyledInput(hint_text="Email Address",
                                       multiline=False, size_hint_y=None, height=ROW_H)
        self.f_phone    = StyledInput(hint_text="Phone Number e.g. 256700123456",
                                       multiline=False, size_hint_y=None, height=ROW_H,
                                       input_filter="int")
        # Set default country code for Uganda
        self.f_phone.text = "256"
        self.f_password = StyledInput(hint_text="Password (min 6 chars)", password=True,
                                       multiline=False, size_hint_y=None, height=ROW_H)
        self.f_confirm  = StyledInput(hint_text="Confirm Password", password=True,
                                       multiline=False, size_hint_y=None, height=ROW_H)
        for f in (self.f_business,self.f_email,self.f_phone,
                  self.f_password,self.f_confirm):
            card.add_widget(f)
        self.msg = Label(text="", color=C_ERROR, font_size=dp(12),
                         halign="center", size_hint_y=None, height=dp(28))
        self.msg.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        card.add_widget(self.msg)
        sb = CalcoraButton(text="Create Account", background_color=C_BLUE,
                           size_hint_y=None, height=BTN_H)
        sb.bind(on_release=self._signup); card.add_widget(sb)
        gb = CalcoraButton(text="Sign Up with Google", background_color=C_PURPLE,
                           size_hint_y=None, height=dp(45), font_size=dp(12))
        gb.bind(on_release=self._google_signup); card.add_widget(gb)
        lb = CalcoraButton(text="Already have an account? Log In",
                           background_color=C_PANEL2, size_hint_y=None, height=dp(40))
        lb.bind(on_release=lambda *_: self._go("login")); card.add_widget(lb)
        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(card); root.add_widget(scroll); self.add_widget(root)

    # Country codes mapping
    COUNTRY_CODES = ["256", "255", "254"]  # Uganda, Tanzania, Kenya

    def _sel_c(self, idx):
        self._sel_country = idx
        for i, btn in enumerate(self._c_btns):
            btn.background_color = C_BLUE if i == idx else C_PANEL2
        # Auto-set phone country code
        code = self.COUNTRY_CODES[idx]
        current = self.f_phone.text.strip()
        # Replace existing code or set fresh
        for c in self.COUNTRY_CODES:
            if current.startswith(c):
                current = current[len(c):]
                break
        self.f_phone.text = code + current

    def _sel_biz_type(self, name):
        self._sel_biz = name
        for n,btn in self._biz_btns:
            btn.background_color = C_BLUE if n==name else C_PANEL2
        self.biz_desc_lbl.text = BUSINESS_TYPES[name]["desc"]

    def _google_signup(self, *_):
        ok, msg = google_auth_signup()
        if ok:
            self._go("home")
        else:
            self._err_msg(msg)

    def _err_msg(self, text):
        self.msg.color = C_ERROR
        self.msg.text = text
        self.msg.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.msg)

    def _signup(self, *_):
        business   = self.f_business.text.strip()
        store_name = self.f_store_name.text.strip() or business
        email      = self.f_email.text.strip()
        phone      = self.f_phone.text.strip()
        pw = self.f_password.text; pw2 = self.f_confirm.text
        country, cur, code = self._countries[self._sel_country]
        if not business: return self._err("Enter your name.")
        if not email or "@" not in email: return self._err("Enter a valid email.")
        if not phone: return self._err("Enter your phone number.")
        if len(pw) < 6: return self._err("Password must be at least 6 characters.")
        if pw != pw2: return self._err("Passwords do not match.")
        SESSION["role"] = "owner"
        if FB_AVAILABLE:
            self._err("Creating account...")
            def _do():
                ok, msg = fb.sign_up_owner(email, pw, business)
                Clock.schedule_once(lambda dt: self._finish(
                    business, store_name, email, phone, country, cur, pw), 0)
            threading.Thread(target=_do, daemon=True).start()
        else:
            self._finish(business, store_name, email, phone, country, cur, pw)

    def _finish(self, business, store_name, email, phone, country, cur, pw):
        save_auth({"business": business, "email": email, "phone": phone,
                   "password": hash_pw(pw), "country": country, "currency": cur,
                   "biz_type": self._sel_biz, "role": "owner"})
        save_stores({"active":"default","list":[],
                     "default_name": store_name,"default_biz": self._sel_biz})
        profile = {"name":business,"store_name":store_name,"phone":phone,
                   "email":email,"address":"","currency":cur,"country":country,
                   "vat":18,"photo":"","biz_type":self._sel_biz,
                   "theme":load_theme()}
        profile = _ensure_subscription_fields(profile)
        try:
            with open(PROFILE_FILE,"w",encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
        except OSError:
            pass
        # Send welcome notification and email
        welcome_message = f"Welcome to Calcora: {store_name}"
        stores_data = load_stores()
        if stores_data.get("default_online_id"):
            send_app_notification(stores_data["default_online_id"], welcome_message)
        if email:
            _send_email(email, "Welcome to Calcora",
                        f"Hello {business},\n\nWelcome to Calcora! Your store '{store_name}' is ready to use.\n\nThank you for choosing Calcora.")
        # Create store online if signed in
        if FB_AVAILABLE and fb and fb.is_online():
            def _create_online():
                ok, online_id, store_code = fb.create_store(store_name, self._sel_biz)
                if ok and online_id:
                    stores_data = load_stores()
                    stores_data["default_online_id"] = online_id
                    stores_data["default_store_code"] = store_code
                    save_stores(stores_data)
                    send_app_notification(online_id, welcome_message)
            threading.Thread(target=_create_online, daemon=True).start()
        self._go("home")

    def _err(self, text):
        self.msg.color = C_GREEN if text.startswith("Creating") else C_ERROR
        self.msg.text = text; self.msg.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.msg)

    def _go(self, s):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current = s


# ── Owner Login ────────────────────────────────────────────────────────────────

class LoginScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        card = BoxLayout(orientation="vertical",
                         padding=[dp(28),dp(28),dp(28),dp(28)], spacing=dp(16),
                         size_hint=(0.92,None),
                         pos_hint={"center_x":0.5,"center_y":0.52})
        card.bind(minimum_height=card.setter("height"))
        with card.canvas.before:
            Color(*C_PANEL)
            card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(18)])
        card.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        logo = CalcoraLogo(size_hint=(1,None), height=dp(80),
                           allow_stretch=True, keep_ratio=True)
        card.add_widget(logo)
        # Owner pill
        pill = Label(text="  Owner Login  ", color=C_WHITE, bold=True,
                     font_size=dp(13), size_hint=(None,None), size=(dp(130),dp(28)),
                     halign="center")
        with pill.canvas.before:
            Color(*C_BLUE)
            pill._bg = RoundedRectangle(pos=pill.pos, size=pill.size, radius=[dp(14)])
        pill.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        pr = BoxLayout(size_hint_y=None, height=dp(34))
        pr.add_widget(Widget()); pr.add_widget(pill); pr.add_widget(Widget())
        card.add_widget(pr)
        self.f_email    = StyledInput(hint_text="Email Address",
                                       multiline=False, size_hint_y=None, height=ROW_H)
        self.f_password = StyledInput(hint_text="Password", password=True,
                                       multiline=False, size_hint_y=None, height=ROW_H)
        card.add_widget(self.f_email); card.add_widget(self.f_password)
        self.msg = Label(text="", color=C_ERROR, font_size=dp(12),
                         halign="center", size_hint_y=None, height=dp(28))
        self.msg.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        card.add_widget(self.msg)
        lb = CalcoraButton(text="Log In as Owner", background_color=C_BLUE,
                           size_hint_y=None, height=BTN_H)
        lb.bind(on_release=self._login); card.add_widget(lb)
        gb = CalcoraButton(text="Continue with Google", background_color=C_PURPLE,
                           size_hint_y=None, height=dp(45), font_size=dp(12))
        gb.bind(on_release=self._google_login); card.add_widget(gb)
        sb = CalcoraButton(text="No account? Sign Up", background_color=C_PANEL2,
                           size_hint_y=None, height=dp(40))
        sb.bind(on_release=lambda *_: self._go("signup")); card.add_widget(sb)
        bb = CalcoraButton(text="< Back", background_color=C_PANEL2,
                           size_hint_y=None, height=dp(38))
        bb.bind(on_release=lambda *_: self._go("splash")); card.add_widget(bb)
        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(card); root.add_widget(scroll); self.add_widget(root)

    def _google_login(self, *_):
        ok, msg = google_auth_login()
        if ok:
            self._go("home")
        else:
            self._err(msg)

    def _login(self, *_):
        email = self.f_email.text.strip(); pw = self.f_password.text
        if not email or not pw:
            return self._err("Enter email and password.")
        SESSION["role"] = "owner"
        if FB_AVAILABLE:
            self._err("Logging in...")
            def _do():
                ok, msg = fb.sign_in_owner(email, pw)
                Clock.schedule_once(lambda dt: self._finish(email, pw, ok, msg), 0)
            threading.Thread(target=_do, daemon=True).start()
        else:
            self._finish(email, pw, False, "No internet")

    def _finish(self, email, pw, fb_ok, fb_msg):
        auth = load_auth()
        if not auth:
            return self._err("No account found. Please sign up first.")
        if email != auth.get("email",""):
            return self._err("Email not found.")
        if hash_pw(pw) != auth.get("password",""):
            return self._err("Incorrect password.")
        if not fb_ok:
            if fb_msg and ("network error" in fb_msg.lower() or "timed out" in fb_msg.lower() or "failed to establish" in fb_msg.lower() or "internet" in fb_msg.lower()):
                self._err("Running offline — no internet.")
                Clock.schedule_once(lambda *_: self._go("home"), 1.2)
                return
            return self._err(fb_msg or "Login failed")
        self._go("home")

    def _err(self, text):
        self.msg.color = C_GREEN if text.startswith("Logging") else C_ERROR
        self.msg.text = text; self.msg.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.msg)

    def _go(self, s):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current = s


# ── Worker Login ───────────────────────────────────────────────────────────────

class WorkerLoginScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._worker_pin = ""
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        card = BoxLayout(orientation="vertical",
                         padding=[dp(28),dp(24),dp(28),dp(24)], spacing=dp(16),
                         size_hint=(0.92,None),
                         pos_hint={"center_x":0.5,"center_y":0.52})
        card.bind(minimum_height=card.setter("height"))
        with card.canvas.before:
            Color(*C_PANEL)
            card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(18)])
        card.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        logo = CalcoraLogo(size_hint=(1,None), height=dp(70),
                           allow_stretch=True, keep_ratio=True)
        card.add_widget(logo)
        # Worker pill
        pill = Label(text="  Worker Login  ", color=C_WHITE, bold=True,
                     font_size=dp(13), size_hint=(None,None), size=(dp(140),dp(28)),
                     halign="center")
        with pill.canvas.before:
            Color(*C_PURPLE)
            pill._bg = RoundedRectangle(pos=pill.pos, size=pill.size, radius=[dp(14)])
        pill.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        pr = BoxLayout(size_hint_y=None, height=dp(34))
        pr.add_widget(Widget()); pr.add_widget(pill); pr.add_widget(Widget())
        card.add_widget(pr)
        card.add_widget(Label(
            text="Ask your owner for the Store Code and your PIN",
            color=C_GREY, font_size=dp(12), halign="center",
            size_hint_y=None, height=dp(30)))
        self.f_code = StyledInput(hint_text="Store Code (e.g. AB12CD)",
                                   multiline=False, size_hint_y=None, height=ROW_H)
        card.add_widget(self.f_code)
        # PIN entry button
        self.pin_btn = CalcoraButton(text="Tap to Enter PIN",
                                      background_color=C_PANEL2,
                                      size_hint_y=None, height=ROW_H)
        self.pin_btn.bind(on_release=self._open_pin)
        card.add_widget(self.pin_btn)
        self.msg = Label(text="", color=C_ERROR, font_size=dp(13),
                         halign="center", size_hint_y=None, height=dp(30))
        self.msg.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        card.add_widget(self.msg)
        lb = CalcoraButton(text="Log In as Worker", background_color=C_PURPLE,
                           size_hint_y=None, height=BTN_H)
        lb.bind(on_release=self._login); card.add_widget(lb)
        bb = CalcoraButton(text="< Back", background_color=C_PANEL2,
                           size_hint_y=None, height=dp(38))
        bb.bind(on_release=lambda *_: self._go("splash")); card.add_widget(bb)
        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(card); root.add_widget(scroll); self.add_widget(root)

    def _open_pin(self, *_):
        pin_popup("Enter your worker PIN",
                  on_success=self._set_pin, confirm=False, worker_mode=True)

    def _set_pin(self, pin=None):
        if pin:
            self._worker_pin = pin
            self.pin_btn.text = "PIN: " + "●" * len(pin)
            self.pin_btn.background_color = C_GREEN

    def _login(self, *_):
        code = self.f_code.text.strip().upper()
        pin  = self._worker_pin
        if not code: return self._err("Enter the Store Code.")
        if not pin:  return self._err("Enter your PIN.")
        if not FB_AVAILABLE:
            return self._err("Internet required for worker login.")
        self._err("Connecting...")
        def _do():
            ok, msg, store_info, worker = fb.worker_login(code, pin)
            def _after(dt):
                if ok:
                    SESSION.update({
                        "role":        "worker",
                        "worker_name": worker.get("name","Worker"),
                        "worker_id":   worker.get("id",""),
                        "store_id":    store_info.get("id",""),
                        "store_name":  store_info.get("name",""),
                        "store_code":  code,
                        "owner_uid":   store_info.get("owner_id",""),
                    })
                    self._go("worker_home")
                else:
                    self._err(msg)
            Clock.schedule_once(_after, 0)
        threading.Thread(target=_do, daemon=True).start()

    def _err(self, text):
        self.msg.color = C_GREEN if text == "Connecting..." else C_ERROR
        self.msg.text = text; self.msg.opacity = 0
        Animation(opacity=1, duration=0.3).start(self.msg)

    def _go(self, s):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current = s


# ── Worker Home ────────────────────────────────────────────────────────────────

class WorkerHomeScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build()

    def _build(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        content = BoxLayout(orientation="vertical",
                            padding=[dp(20),dp(16),dp(20),dp(16)],
                            spacing=dp(14), size_hint=(1,1), pos_hint={"x":0,"y":0})
        root.add_widget(content)
        # Header
        header = BoxLayout(size_hint_y=None, height=dp(80), spacing=dp(12))
        logo = KivyImage(source=os.path.join(BASE_DIR,"calcora icon.png"),
                         allow_stretch=True, keep_ratio=True,
                         size_hint=(None,None), size=(dp(60),dp(60)))
        header.add_widget(logo)
        title_col = BoxLayout(orientation="vertical")
        store_name  = SESSION.get("store_name") or "My Store"
        worker_name = SESSION.get("worker_name") or "Worker"
        title_col.add_widget(Label(text=store_name, color=C_WHITE, bold=True,
                                   font_size=dp(18), halign="left", valign="middle"))
        title_col.add_widget(Label(text=f"Welcome, {worker_name}",
                                   color=C_GREEN, font_size=dp(12),
                                   halign="left", valign="middle"))
        header.add_widget(title_col)
        logout = CalcoraButton(text="Logout", background_color=C_PANEL2,
                               size_hint=(None,None), size=(dp(70),dp(36)),
                               font_size=dp(12))
        logout.bind(on_release=self._logout)
        header.add_widget(logout)
        content.add_widget(header)
        # Divider
        div = Widget(size_hint_y=None, height=dp(1))
        with div.canvas:
            Color(*C_PURPLE[:3], 0.4)
            div._l = Rectangle(pos=div.pos, size=div.size)
        div.bind(pos=lambda w,v: setattr(w._l,"pos",v),
                 size=lambda w,v: setattr(w._l,"size",v))
        content.add_widget(div)
        # Worker pill
        pill = Label(text="  Worker Interface  ", color=C_WHITE, bold=True,
                     font_size=dp(11), size_hint=(None,None), size=(dp(160),dp(26)))
        with pill.canvas.before:
            Color(*C_PURPLE)
            pill._bg = RoundedRectangle(pos=pill.pos, size=pill.size, radius=[dp(13)])
        pill.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                  size=lambda w,v: setattr(w._bg,"size",v))
        pr = BoxLayout(size_hint_y=None, height=dp(30))
        pr.add_widget(pill); pr.add_widget(Widget())
        content.add_widget(pr)
        # Nav tiles
        nav = [("Daily Sales","sales",C_BLUE),
               ("Stock","stock",C_PURPLE),
               ("History","history",C_ORANGE)]
        grid = GridLayout(cols=1, spacing=dp(12), size_hint_y=0.62)
        for label,screen,color in nav:
            grid.add_widget(self._tile(label, screen, color))
        content.add_widget(grid)
        self.add_widget(root)

    def _tile(self, label, screen, color):
        fl = FloatLayout()
        with fl.canvas.before:
            Color(*C_PANEL)
            fl._bg = RoundedRectangle(pos=fl.pos, size=fl.size, radius=[RADIUS])
            Color(*color[:3], 0.9)
            fl._strip = RoundedRectangle(pos=fl.pos, size=(dp(5),1),
                                          radius=[RADIUS,0,0,RADIUS])
            Color(*color[:3], 0.07)
            fl._glow = Ellipse(pos=fl.pos, size=(1,1))
        def _s(w,*_):
            fl._bg.pos=w.pos; fl._bg.size=w.size
            fl._strip.pos=w.pos; fl._strip.size=(dp(5),w.height)
            fl._glow.pos=(w.x+w.width*0.35,w.y+w.height*0.15)
            fl._glow.size=(w.width*0.85,w.height*0.85)
        fl.bind(pos=_s, size=_s)
        lbl = Label(text=label, color=C_WHITE, bold=True,
                    halign="center", valign="middle",
                    size_hint=(1,1), pos_hint={"x":0,"y":0}, font_size=dp(15))
        lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        fl.add_widget(lbl)
        btn = Button(background_normal="", background_color=(0,0,0,0),
                     background_down="", size_hint=(1,1), pos_hint={"x":0,"y":0})
        btn.bind(on_release=lambda *_: self._go(screen))
        btn.bind(on_press=lambda *_: Animation(
            background_color=(*color[:3],0.15),duration=0.08).start(btn))
        btn.bind(on_release=lambda *_: Animation(
            background_color=(0,0,0,0),duration=0.15).start(btn))
        fl.add_widget(btn)
        return fl

    def _logout(self, *_):
        SESSION.update({"role":None,"worker_name":None,"worker_id":None,
                        "store_id":None,"store_name":None})
        if FB_AVAILABLE: fb.sign_out()
        self.manager.transition = SlideTransition(direction="right", duration=0.22)
        self.manager.current = "splash"

    def _go(self, screen):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current = screen

    def refresh(self):
        self._build()


# ── Owner Dashboard ────────────────────────────────────────────────────────────

class OwnerDashboardScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build()

    def _build(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(Label(text="Owner Dashboard", color=C_WHITE, bold=True,
                              font_size=dp(22), size_hint=(0.7,None), height=dp(44),
                              pos_hint={"center_x":0.5,"top":0.97}, halign="center"))
        # divider removed to avoid overlap with section labels

        # Status dot — updated after async check
        self.status_lbl = Label(text="● Connecting...",
                                color=C_GOLD, font_size=dp(12), bold=True,
                                size_hint=(None,None), size=(dp(120),dp(24)),
                                pos_hint={"right":0.97,"top":0.97})
        root.add_widget(self.status_lbl)

        scroll_content = BoxLayout(orientation="vertical",
                        padding=[dp(16),dp(80),dp(16),dp(16)],
                                    spacing=dp(14), size_hint_y=None)
        scroll_content.bind(minimum_height=scroll_content.setter("height"))

        # Summary row: quick at-a-glance cards for Revenue, Sales, Workers, Health
        summary_row = GridLayout(cols=4, spacing=dp(12), size_hint_y=None, height=dp(110))
        rev_card = SummaryCard("Revenue", "—", size_hint=(1, None), height=dp(100))
        sales_card = SummaryCard("Sales", "—", size_hint=(1, None), height=dp(100))
        workers_card = SummaryCard("Workers", "—", size_hint=(1, None), height=dp(100))
        health_card = SummaryCard("Health", "—", size_hint=(1, None), height=dp(100))
        summary_row.add_widget(rev_card)
        summary_row.add_widget(sales_card)
        summary_row.add_widget(workers_card)
        summary_row.add_widget(health_card)
        scroll_content.add_widget(summary_row)

        # Fill summary asynchronously to avoid blocking UI
        def _load_summary():
            try:
                app = App.get_running_app()
                store = self._get_online_store_id() or (app.active_store_id if app else "default")
                sales = app._get_sales_for_store(store, limit=1000) if app else []
                total = sum(float(x.get("subtotal") or x.get("amount") or 0) for x in sales)
                s_count = len(sales)
                workers = fb.get_workers(store) if FB_AVAILABLE and fb and fb.is_online() else []
                w_count = len(workers)
                # compute simple health metric (last 7 days)
                from datetime import datetime, timedelta
                week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                recent = [x for x in sales if (x and (x.get("submitted_at") or x.get("created_at") or "")[:10]) >= week_ago]
                if not recent:
                    health = 0
                else:
                    active_days = len({(x.get("submitted_at") or x.get("created_at") or "")[:10] for x in recent if (x.get("submitted_at") or x.get("created_at"))})
                    items_sold = sum(float(x.get("quantity") or 0) for x in recent)
                    days_score = active_days / 7.0
                    items_score = min(items_sold, 35) / 35.0
                    health = min(100, int((days_score * 0.5 + items_score * 0.5) * 100))
                def _upd(dt):
                    rev_card.vlbl.text = f"UGX {money(total)}"
                    sales_card.vlbl.text = f"{s_count}"
                    workers_card.vlbl.text = f"{w_count}"
                    health_card.vlbl.text = f"{health}%"
                    # subtle color hint for health
                    health_card.vlbl.color = (C_GREEN if health >= 70 else C_GOLD if health >= 40 else C_ERROR)
                Clock.schedule_once(_upd, 0)
            except Exception:
                pass
        threading.Thread(target=_load_summary, daemon=True).start()

        # Always build content — data loads async
        self._build_online(scroll_content)

        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(scroll_content)
        root.add_widget(scroll)
        self.add_widget(root)

        # Check online status async and update indicator
        def _check_online():
            online = FB_AVAILABLE and fb and fb.is_online()
            # Try refreshing token if needed
            if not online and FB_AVAILABLE and fb:
                try:
                    fb.refresh_session()
                    online = fb.is_online()
                except Exception:
                    pass
            def _upd(dt):
                if online:
                    self.status_lbl.text  = "● ONLINE"
                    self.status_lbl.color = C_GREEN
                else:
                    self.status_lbl.text  = "● OFFLINE"
                    self.status_lbl.color = C_ERROR
            Clock.schedule_once(_upd, 0)
        threading.Thread(target=_check_online, daemon=True).start()

    def _section(self, text, color=None):
        lbl = Label(text=text, color=color or C_CYAN, bold=True,
                    font_size=dp(14), halign="left",
                    size_hint_y=None, height=dp(36))
        lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        return lbl

    def _wait_for_supabase(self, seconds=5):
        """Give login/refresh a short moment before owner dashboard requests."""
        if not (FB_AVAILABLE and fb):
            return False
        end = time.time() + seconds
        while time.time() < end:
            if fb.is_online():
                return True
            try:
                fb.refresh_session()
                if fb.is_online():
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return fb.is_online()

    def _fb_error(self, fallback):
        try:
            return fb.last_error() or fallback
        except Exception:
            return fallback

    def _local_sales_for_store(self, store_id):
        app = App.get_running_app()
        if not app:
            return []
        stores_data = load_stores()
        local_online = stores_data.get("default_online_id")
        if app.active_store_id != "default" and app.active_store_id != store_id and store_id != local_online:
            return []
        sales = []
        now = datetime.now()
        current_year = now.year
        for entry in app.history:
            for row in entry.get("rows", []):
                item = dict(row)
                date_str = (item.get("date") or "").strip()
                if date_str:
                    try:
                        dt = datetime.strptime(date_str, "%d/%m")
                        item["submitted_at"] = dt.replace(year=current_year).strftime(
                            "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        item["submitted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    item["submitted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                sales.append(item)
        return sales

    def _sales_for_store(self, store_id, limit=200):
        sales = []
        if FB_AVAILABLE and fb and fb.is_online():
            sales = fb.get_sales(store_id, limit=limit) or []
        if not sales:
            sales = self._local_sales_for_store(store_id)
        return sales

    def _sale_date(self, sale):
        date_str = (sale.get("submitted_at") or sale.get("created_at") or "").strip()
        if date_str:
            return date_str[:10]
        local_date = (sale.get("date") or "").strip()
        if local_date:
            try:
                dt = datetime.strptime(local_date, "%d/%m")
                return dt.replace(year=datetime.now().year).strftime("%Y-%m-%d")
            except Exception:
                pass
        return ""

    def _ensure_default_store_online(self):
        """Create the locally-saved signup store online if Supabase has no rows yet."""
        stores_data = load_stores()
        store_name  = stores_data.get("default_name", "Main Store")
        biz_type    = stores_data.get("default_biz", get_biz_type())
        if not store_name:
            store_name = "Main Store"
        ok, store_id, store_code = fb.create_store(store_name, biz_type)
        if ok and store_id:
            stores_data["default_online_id"] = store_id
            stores_data["default_store_code"] = store_code
            save_stores(stores_data)
            return True
        return False

    def _build_online(self, box):

        # ── Notifications ──
        # Notifications header with clear-read action
        hdr_row = BoxLayout(size_hint_y=None, height=dp(34))
        hdr_row.add_widget(self._section("Notifications"))
        clear_btn = CalcoraButton(text="Clear read", background_color=C_PANEL2,
                                  size_hint=(None, None), size=(dp(96), dp(30)), font_size=dp(12))
        hdr_row.add_widget(Widget())
        hdr_row.add_widget(clear_btn)
        box.add_widget(hdr_row)

        notif_box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        notif_box.bind(minimum_height=notif_box.setter("height"))
        notif_box.add_widget(Label(text="Loading...", color=C_GREY,
                                    font_size=dp(13), size_hint_y=None, height=dp(36)))

        def _load_notifs():
            if not self._wait_for_supabase():
                Clock.schedule_once(lambda dt: (
                    notif_box.clear_widgets(),
                    notif_box.add_widget(Label(
                        text="Log in online to load notifications.",
                        color=C_GREY, font_size=dp(13),
                        size_hint_y=None, height=dp(36)))
                ), 0)
                return
            notifs = fb.get_notifications(limit=15)
            def _show(dt):
                notif_box.clear_widgets()
                if not notifs:
                    notif_box.add_widget(Label(text="No notifications yet.",
                                               color=C_GREY, font_size=dp(13),
                                               size_hint_y=None, height=dp(36)))
                    return
                for n in notifs:
                    is_read = n.get("is_read", False)
                    row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
                    with row.canvas.before:
                        Color(*C_BLUE[:3], 0.08 if is_read else 0.20)
                        row._bg = RoundedRectangle(pos=row.pos, size=row.size,
                                                    radius=[dp(8)])
                    row.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                             size=lambda w,v: setattr(w._bg,"size",v))
                    dot = Label(text="●", color=C_GREY if is_read else C_GREEN,
                                font_size=dp(10), size_hint_x=None, width=dp(20))
                    ts  = (n.get("created_at","") or "")[:16]
                    txt = Label(text=f"{n.get('message','')}\n{ts}",
                                color=C_GREY if is_read else C_WHITE,
                                font_size=dp(12), halign="left", valign="middle")
                    txt.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                    row.add_widget(dot); row.add_widget(txt)
                    # Add small delete button for read notifications
                    if is_read:
                        del_btn = CalcoraButton(text="Delete", background_color=C_ERROR,
                                                size_hint=(None,None), size=(dp(78),dp(34)), font_size=dp(11))
                        def _del(nid=n.get("id"), rb=row):
                            threading.Thread(target=lambda: (
                                fb.delete_notification(nid) if FB_AVAILABLE and fb and fb.is_online() else None,
                                Clock.schedule_once(lambda dt: _load_notifs(), 0)
                            ), daemon=True).start()
                        del_btn.bind(on_release=lambda *_: _del())
                        row.add_widget(del_btn)
                    notif_box.add_widget(row)
                    if not is_read:
                        def _mark(w, t, nid=n.get("id","")):
                            if w.collide_point(*t.pos):
                                threading.Thread(
                                    target=lambda i=nid: fb.mark_notification_read(i),
                                    daemon=True).start()
                        row.bind(on_touch_down=_mark)
                Clock.schedule_once(_show, 0)
        # Wire clear button to delete all read notifications
        def _clear_read(*_):
            if not (FB_AVAILABLE and fb and fb.is_online()):
                return
            def _do():
                fb.delete_read_notifications()
                Clock.schedule_once(lambda dt: _load_notifs(), 0)
            threading.Thread(target=_do, daemon=True).start()
        clear_btn.bind(on_release=_clear_read)
        threading.Thread(target=_load_notifs, daemon=True).start()
        box.add_widget(notif_box)
        # larger spacer to separate notifications from stores overview
        box.add_widget(Widget(size_hint_y=None, height=dp(40)))

        # ── Stores Overview ──
        box.add_widget(self._section("Stores Overview"))
        stores_box = BoxLayout(orientation="vertical", spacing=dp(14), size_hint_y=None)
        stores_box.bind(minimum_height=stores_box.setter("height"))
        stores_box.add_widget(Label(text="Loading stores...", color=C_GREY,
                                     font_size=dp(13), size_hint_y=None, height=dp(36)))

        def _load_stores():
            if not self._wait_for_supabase():
                Clock.schedule_once(lambda dt: (
                    stores_box.clear_widgets(),
                    stores_box.add_widget(Label(
                        text="Could not connect to Supabase yet.\nLog in again or check the console for the Supabase error.",
                        color=C_GREY, font_size=dp(13), halign="center",
                        size_hint_y=None, height=dp(58)))
                ), 0)
                return
            stores = fb.get_stores()
            offline_notice = False
            if not stores:
                stores_data = load_stores()
                if stores_data.get("list") or stores_data.get("default_name"):
                    offline_notice = True
                    stores = []
                    default_name = stores_data.get("default_name", "Main Store")
                    default_biz = stores_data.get("default_biz", get_biz_type())
                    default_code = stores_data.get("default_store_code", "LOCAL")
                    stores.append({
                        "id": stores_data.get("default_online_id", "default"),
                        "name": default_name,
                        "biz_type": default_biz,
                        "store_code": default_code,
                    })
                    for item in stores_data.get("list", []):
                        stores.append({
                            "id": item.get("online_id") or item.get("id") or "",
                            "name": item.get("name", "Store"),
                            "biz_type": item.get("biz_type", default_biz),
                            "store_code": item.get("store_code", "LOCAL"),
                        })
                elif not self._fb_error(""):
                    if self._ensure_default_store_online():
                        stores = fb.get_stores()
            def _show(dt):
                stores_box.clear_widgets()
                if not stores:
                    err = self._fb_error("")
                    if err:
                        stores_box.add_widget(Label(
                            text=err,
                            color=C_ERROR, font_size=dp(12), halign="center",
                            size_hint_y=None, height=dp(58)))
                        return
                    stores_box.add_widget(Label(
                        text="No stores found online.\nCreate one from Profile > My Stores.",
                        color=C_GREY, font_size=dp(13), halign="center",
                        size_hint_y=None, height=dp(50)))
                    return
                if offline_notice:
                    stores_box.add_widget(Label(
                        text="Showing cached store data while offline.",
                        color=C_GOLD, font_size=dp(12), halign="center",
                        size_hint_y=None, height=dp(26)))

                for s in stores:
                    sid = s.get("id","")
                    cfg = BUSINESS_TYPES.get(s.get("biz_type",""),
                                              BUSINESS_TYPES["Home Retail"])
                    col = cfg["color"]

                    # Card
                    card = BoxLayout(orientation="vertical", spacing=dp(8),
                                     size_hint_y=None, padding=[dp(14),dp(12),dp(14),dp(12)])
                    with card.canvas.before:
                        Color(*C_PANEL)
                        card._bg = RoundedRectangle(pos=card.pos, size=card.size,
                                                     radius=[dp(14)])
                        Color(*col[:3], 0.7)
                        card._strip = RoundedRectangle(pos=card.pos,
                                                        size=(dp(6), card.height),
                                                        radius=[dp(14),0,0,dp(14)])
                    def _csync(w, *_):
                        w._bg.pos    = w.pos; w._bg.size   = w.size
                        w._strip.pos = w.pos; w._strip.size = (dp(6), w.height)
                    card.bind(pos=_csync, size=_csync)

                    # Title row
                    top_row = BoxLayout(size_hint_y=None, height=dp(30))
                    name_lbl = Label(text="",
                                     color=C_WHITE, bold=True, font_size=dp(15),
                                     halign="left", valign="middle",
                                     shorten=True, shorten_from="right")
                    name_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                    code_lbl = Label(text=f"Code: {s.get('store_code','—')}",
                                     color=C_GREY, font_size=dp(11),
                                     halign="right", valign="middle",
                                     size_hint_x=None, width=dp(116),
                                     shorten=True, shorten_from="left")
                    code_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                    top_row.add_widget(name_lbl)
                    top_row.add_widget(code_lbl)
                    card.add_widget(top_row)

                    # Stats labels (loaded async)
                    stats_row = GridLayout(cols=3, spacing=dp(6),
                                           size_hint_y=None, height=dp(42))
                    rev_lbl = Label(text=f"{s.get('name','')}\n", color=C_GREY,
                                    font_size=dp(11), halign="center",
                                    valign="middle", shorten=True)
                    sales_lbl = Label(text="Sales\n--", color=C_GREY,
                                      font_size=dp(10), halign="center",
                                      valign="middle", shorten=True)
                    worker_count_lbl = Label(text="Workers\n--", color=C_GREY,
                                             font_size=dp(10), halign="center",
                                             valign="middle", shorten=True)
                    for lbl in (rev_lbl, sales_lbl, worker_count_lbl):
                        lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                        stats_row.add_widget(lbl)
                    card.add_widget(stats_row)

                    # Health bar row
                    health_row = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(8))
                    h_title = Label(text="Health:", color=C_GREY, font_size=dp(11),
                                    size_hint_x=None, width=dp(52), valign="middle")
                    h_bar   = Widget(size_hint_y=None, height=dp(12))
                    h_pct   = Label(text="—", color=C_WHITE, font_size=dp(11),
                                    size_hint_x=None, width=dp(40),
                                    halign="right", valign="middle")
                    health_row.add_widget(h_title)
                    health_row.add_widget(h_bar)
                    health_row.add_widget(h_pct)
                    card.add_widget(health_row)

                    # Last-week summary label
                    last_week_lbl = Label(text="", color=C_GREY, font_size=dp(10),
                                           size_hint_y=None, height=dp(18),
                                           halign="left", valign="middle")
                    last_week_lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
                    card.add_widget(last_week_lbl)

                    # Workers label
                    workers_lbl = Label(text="Workers: loading...", color=C_GREY,
                                        font_size=dp(12), halign="left",
                                        valign="middle", size_hint_y=None,
                                        height=dp(34), shorten=True,
                                        shorten_from="right")
                    workers_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                    card.add_widget(workers_lbl)

                    # Button row
                    btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
                    mw_btn = CalcoraButton(text="+ Add / Manage Workers",
                                           background_color=C_BLUE,
                                           size_hint=(0.50,1), font_size=dp(11))
                    mw_btn.bind(on_release=lambda b, store=s, wlbl=workers_lbl:
                                self._manage_workers(store, wlbl))
                    vs_btn = CalcoraButton(text="Sales",
                                           background_color=C_PANEL2,
                                           size_hint=(0.25,1), font_size=dp(11))
                    vs_btn.bind(on_release=lambda b, store_id2=sid:
                                self._view_sales(store_id2))
                    del_btn = CalcoraButton(text="Delete",
                                            background_color=C_ERROR,
                                            size_hint=(0.25,1), font_size=dp(11))
                    del_btn.bind(on_release=lambda b, store=s, card2=card:
                                 self._confirm_delete_store(store, card2, stores_box))
                    btn_row.add_widget(mw_btn)
                    btn_row.add_widget(vs_btn)
                    btn_row.add_widget(del_btn)
                    card.add_widget(btn_row)

                    card.height = dp(196)
                    stores_box.add_widget(card)

                    # Load stats async
                    def _stats(store_id, store_name, revenue_l, sales_l, worker_l, hb, hp, wl, lw_lbl):
                        from datetime import datetime, timedelta
                        sales   = self._sales_for_store(store_id, limit=200)
                        workers = fb.get_workers(store_id) if FB_AVAILABLE and fb and fb.is_online() else []
                        total   = sum(float(x.get("subtotal") or x.get("amount") or 0) for x in sales)
                        s_count = len(sales)
                        w_count = len(workers)
                        wnames  = (", ".join(w.get("name","?") for w in workers)
                                   if workers else "None yet")
                        week_ago = (datetime.now() - timedelta(days=7)
                                    ).strftime("%Y-%m-%d")
                        recent = [x for x in sales if self._sale_date(x) >= week_ago]
                        if not recent:
                            health = 0
                        else:
                            active_days = len({self._sale_date(x) for x in recent if self._sale_date(x)})
                            items_sold = sum(float(x.get("quantity") or 0) for x in recent)
                            days_score = active_days / 7.0
                            items_score = min(items_sold, 35) / 35.0
                            health = min(100, int((days_score * 0.5 + items_score * 0.5) * 100))
                        bar_col  = (C_GREEN if health >= 70
                                    else C_GOLD if health >= 40 else C_ERROR)
                        def _draw_bar(*_):
                            hb.canvas.clear()
                            with hb.canvas:
                                Color(*C_PANEL2)
                                RoundedRectangle(pos=hb.pos, size=hb.size, radius=[dp(4)])
                                Color(*bar_col[:3], 1)
                                RoundedRectangle(
                                    pos=hb.pos,
                                    size=(hb.width * health / 100, hb.height),
                                    radius=[dp(4)])
                        def _upd(dt):
                            revenue_l.text = f"{store_name}"
                            sales_l.text = f"Sales\n{s_count}"
                            worker_l.text = f"Workers\n{w_count}"
                            for lbl in (revenue_l, sales_l, worker_l):
                                lbl.color = C_WHITE
                            hp.text  = f"{health}%"
                            hp.color = bar_col
                            wl.text  = f"Workers: {wnames}"
                            # Compute last-week and previous-week totals for display
                            try:
                                week_end = datetime.now().date()
                                week_start = week_end - timedelta(days=6)
                                prev_start = week_start - timedelta(days=7)
                                prev_end = week_start - timedelta(days=1)
                                def _in_range(s, start, end):
                                    d = self._sale_date(s)
                                    if not d:
                                        return False
                                    try:
                                        sd = datetime.fromisoformat(d).date()
                                    except Exception:
                                        try:
                                            sd = datetime.strptime(d, "%Y-%m-%d").date()
                                        except Exception:
                                            return False
                                    return start <= sd <= end
                                cur_week = [s for s in sales if _in_range(s, week_start, week_end)]
                                prev_week = [s for s in sales if _in_range(s, prev_start, prev_end)]
                                cur_total = sum(float(x.get("subtotal") or x.get("amount") or 0) for x in cur_week)
                                prev_total = sum(float(x.get("subtotal") or x.get("amount") or 0) for x in prev_week)
                                change_pct = ((cur_total - prev_total) / prev_total * 100.0) if prev_total > 0 else (100.0 if cur_total > 0 else 0.0)
                            except Exception:
                                cur_total = prev_total = change_pct = 0

                            # Display last-week summary
                            try:
                                lw_lbl.text = f"Last wk: {money(prev_total)}  Change: {change_pct:+.0f}%"
                                lw_lbl.color = C_GREY
                            except Exception:
                                pass

                            # Adjusted health notification (cap +/-15 points)
                            from health_utils import compute_base_health, compute_change_pct, adjust_health
                            try:
                                base_h = compute_base_health(cur_week)
                                pct = compute_change_pct(cur_total, prev_total)
                                adj_h = adjust_health(base_h, pct, cap_points=15)
                            except Exception:
                                adj_h = health
                            if adj_h < 15:
                                send_app_notification(store_id,
                                                      _format_notification_text("Business unhealthy needs attention", "", store_name))
                            perf = ("Low" if adj_h < 40 else
                                    "Fair" if adj_h < 70 else
                                    "Good" if adj_h < 90 else
                                    "High")
                            send_app_notification(store_id, f"Weekly performance {perf}: {store_name}")
                            hb.unbind(pos=_draw_bar, size=_draw_bar)
                            hb.bind(pos=_draw_bar, size=_draw_bar)
                            _draw_bar()
                        Clock.schedule_once(_upd, 0)
                    threading.Thread(
                        target=lambda i=sid, n=s.get("name", "Your Store"),
                                       rl=rev_lbl, sal=sales_lbl,
                                       wc=worker_count_lbl, hb=h_bar,
                                       hp=h_pct, wl=workers_lbl, lw=last_week_lbl:
                            _stats(i, n, rl, sal, wc, hb, hp, wl, lw),
                        daemon=True).start()

            Clock.schedule_once(_show, 0)
        threading.Thread(target=_load_stores, daemon=True).start()
        box.add_widget(stores_box)

    def _view_sales(self, store_id):
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(14))
        with content.canvas.before:
            Color(*C_PANEL)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                            radius=[dp(14)])
        content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))
        popup = Popup(title="Recent Sales", content=content,
                      size_hint=(0.95,0.85),
                      background_color=(*C_PANEL[:3],1), title_color=C_GREEN)
        loading = Label(text="Loading sales...", color=C_GREY,
                        size_hint_y=None, height=dp(40))
        content.add_widget(loading)
        sales_box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        sales_box.bind(minimum_height=sales_box.setter("height"))
        sv = ScrollView()
        sv.add_widget(sales_box)
        content.add_widget(sv)
        close = CalcoraButton(text="Close", background_color=C_PANEL2,
                               size_hint_y=None, height=dp(44))
        close.bind(on_release=popup.dismiss)
        content.add_widget(close)
        def _load():
            sales = []
            if self._wait_for_supabase() and FB_AVAILABLE and fb and fb.is_online():
                sales = fb.get_sales(store_id, limit=30) or []
            if not sales:
                app = App.get_running_app()
                if app:
                    sales = self._local_sales_for_store(store_id)
            def _show(dt):
                content.remove_widget(loading)
                if not sales:
                    err = self._fb_error("")
                    if err:
                        sales_box.add_widget(Label(text=err,
                                                   color=C_ERROR, font_size=dp(12),
                                                   halign="center",
                                                   size_hint_y=None, height=dp(54)))
                        return
                    sales_box.add_widget(Label(text="No sales submitted yet.",
                                               color=C_GREY, font_size=dp(13),
                                               size_hint_y=None, height=dp(40)))
                    return
                for s in sales:
                    row = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))
                    with row.canvas.before:
                        Color(*C_PANEL2)
                        row._bg = RoundedRectangle(pos=row.pos, size=row.size,
                                                    radius=[dp(8)])
                    row.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                             size=lambda w,v: setattr(w._bg,"size",v))
                    ts  = ((s.get("submitted_at") or s.get("created_at") or s.get("date") or "")[:16])
                    cur = app_currency()
                    subtotal = float(s.get("subtotal") or s.get("amount") or 0)
                    worker_name = s.get('worker_name') or s.get('item') or 'Sale'
                    txt = Label(
                        text=f"{worker_name}  —  "
                             f"{cur} {subtotal:,.0f}\n{ts}",
                        color=C_WHITE, font_size=dp(12),
                        halign="left", valign="middle",
                        shorten=True, shorten_from="right")
                    txt.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
                    row.add_widget(txt)
                    sales_box.add_widget(row)
            Clock.schedule_once(_show, 0)
        threading.Thread(target=_load, daemon=True).start()
        popup.open()

    def _manage_workers(self, store, workers_lbl=None):
        store_id   = store.get("id","") if isinstance(store, dict) else store
        store_name = store.get("name","Store") if isinstance(store, dict) else "Store"

        content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(16))
        with content.canvas.before:
            Color(*C_PANEL)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                            radius=[dp(12)])
        content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))
        popup = Popup(title=f"Workers — {store_name}", content=content,
                      size_hint=(0.93, 0.90),
                      background_color=(*C_PANEL[:3],1), title_color=C_GREEN)

        # Add section
        content.add_widget(Label(text="Add New Worker", color=C_GREEN, bold=True,
                                  font_size=dp(14), size_hint_y=None, height=dp(28)))
        name_inp = StyledInput(hint_text="Worker Name (e.g. John Doe)",
                                multiline=False, size_hint_y=None, height=ROW_H)
        content.add_widget(name_inp)

        worker_pin_holder = [""]
        pin_btn = CalcoraButton(text="Tap to Set Worker PIN",
                                 background_color=C_PANEL2,
                                 size_hint_y=None, height=ROW_H, font_size=dp(13))
        def _open_pin(*_):
            pin_popup("Set 4-digit PIN for this worker",
                      on_success=lambda p: (
                          worker_pin_holder.__setitem__(0, p),
                          setattr(pin_btn, "text", "PIN set  " + "●"*4),
                          setattr(pin_btn, "background_color", C_GREEN)),
                      confirm=True)
        pin_btn.bind(on_release=_open_pin)
        content.add_widget(pin_btn)

        add_msg = Label(text="", color=C_GREEN, font_size=dp(12),
                        halign="center", size_hint_y=None, height=dp(26))
        add_msg.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        content.add_widget(add_msg)

        workers_list = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        workers_list.bind(minimum_height=workers_list.setter("height"))

        def _load_w():
            if not self._wait_for_supabase():
                Clock.schedule_once(lambda dt: (
                    workers_list.clear_widgets(),
                    workers_list.add_widget(Label(
                        text="Could not connect to Supabase.",
                        color=C_ERROR, font_size=dp(12),
                        size_hint_y=None, height=dp(34)))
                ), 0)
                return
            workers = fb.get_workers(store_id)
            def _show(dt):
                workers_list.clear_widgets()
                if not workers:
                    workers_list.add_widget(Label(
                        text="No workers yet — add one above.",
                        color=C_GREY, font_size=dp(12),
                        size_hint_y=None, height=dp(34)))
                    return
                for w in workers:
                    wrow = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
                    with wrow.canvas.before:
                        Color(*C_PANEL2)
                        wrow._bg = RoundedRectangle(pos=wrow.pos, size=wrow.size,
                                                     radius=[dp(8)])
                    wrow.bind(pos=lambda wi,v: setattr(wi._bg,"pos",v),
                              size=lambda wi,v: setattr(wi._bg,"size",v))
                    wlbl2 = Label(text=f"  {w.get('name','?')}",
                                  color=C_WHITE, font_size=dp(13),
                                  halign="left", valign="middle")
                    wlbl2.bind(size=lambda wi,*_: setattr(wi,"text_size",wi.size))
                    del_btn = CalcoraButton(text="Remove", background_color=C_ERROR,
                                            size_hint=(None,1), width=dp(84),
                                            font_size=dp(12))
                    def _del(b, wid=w.get("id",""), wname=w.get("name","")):
                        def _do():
                            ok = fb.remove_worker(wid)
                            def _done(dt):
                                add_msg.color = C_GREEN if ok else C_ERROR
                                add_msg.text  = (f"'{wname}' removed." if ok
                                                 else "Failed to remove.")
                                _load_w()
                            Clock.schedule_once(_done, 0)
                        threading.Thread(target=_do, daemon=True).start()
                    del_btn.bind(on_release=_del)
                    wrow.add_widget(wlbl2); wrow.add_widget(del_btn)
                    workers_list.add_widget(wrow)
                if workers_lbl:
                    wnames = ", ".join(w.get("name","?") for w in workers)
                    workers_lbl.text = f"Workers: {wnames}"
            Clock.schedule_once(_show, 0)
        threading.Thread(target=_load_w, daemon=True).start()

        def _add(*_):
            name = name_inp.text.strip()
            pin  = worker_pin_holder[0]
            if not name:
                add_msg.color = C_ERROR
                add_msg.text  = "Enter the worker's name."
                return
            if len(pin) < 4:
                add_msg.color = C_ERROR
                add_msg.text  = "Please set a 4-digit PIN first."
                return
            add_msg.color = C_GREEN
            add_msg.text  = "Adding worker..."
            def _do():
                ok, wid = fb.add_worker(store_id, name, pin)
                def _done(dt):
                    if ok:
                        add_msg.color = C_GREEN
                        add_msg.text  = f"'{name}' added successfully!"
                        name_inp.text = ""
                        worker_pin_holder[0] = ""
                        pin_btn.text = "Tap to Set Worker PIN"
                        pin_btn.background_color = C_PANEL2
                        _load_w()
                    else:
                        add_msg.color = C_ERROR
                        add_msg.text  = self._fb_error("Failed to add. Check connection.")
                Clock.schedule_once(_done, 0)
            threading.Thread(target=_do, daemon=True).start()

        add_btn = CalcoraButton(text="Add Worker", background_color=C_BLUE,
                                 size_hint_y=None, height=BTN_H)
        add_btn.bind(on_release=_add)
        content.add_widget(add_btn)

        content.add_widget(Label(text="Current Workers", color=C_GREEN, bold=True,
                                  font_size=dp(13), size_hint_y=None, height=dp(26)))
        wscroll = ScrollView(size_hint_y=None, height=dp(190))
        wscroll.add_widget(workers_list)
        content.add_widget(wscroll)

        close_btn = CalcoraButton(text="Done", background_color=C_PANEL2,
                                   size_hint_y=None, height=dp(44))
        close_btn.bind(on_release=popup.dismiss)
        content.add_widget(close_btn)
        popup.open()

    def _confirm_delete_store(self, store, card, stores_box):
        store_id   = store.get("id","")
        store_name = store.get("name","Store")
        confirm_popup(
            "Delete Store",
            f"Delete '{store_name}' and all its workers and sales? This cannot be undone.",
            lambda: self._do_delete_store(store_id, store_name, card, stores_box),
        )

    def _do_delete_store(self, store_id, store_name, card, stores_box):
        def _do():
            ok = fb.delete_store(store_id)
            def _done(dt):
                if ok:
                    stores_box.remove_widget(card)
                    # Also remove from local stores file
                    data = load_stores()
                    data["list"] = [s for s in data.get("list",[])
                                    if s.get("id") != store_id]
                    save_stores(data)
                else:
                    confirm_popup("Error", self._fb_error("Failed to delete store. Try again."), lambda: None)
            Clock.schedule_once(_done, 0)
        threading.Thread(target=_do, daemon=True).start()

    def on_pre_enter(self, *_):
        Clock.schedule_once(lambda *_: self._build(), 0.2)

    def refresh(self):
        self._build()

class BottomNav(BoxLayout):
    """Fixed bottom bar with Home and Profile buttons."""
    def __init__(self, screen_manager, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)
        self.sm = screen_manager
        with self.canvas.before:
            Color(*C_PANEL)
            self._bg = Rectangle(pos=self.pos, size=self.size)
            Color(*C_BLUE[:3], 0.25)
            self._top = Line(points=[self.x, self.y+self.height,
                                     self.x+self.width, self.y+self.height],
                             width=1)
        self.bind(pos=self._sync, size=self._sync)

        for label, target in (("Home", "home"), ("Profile", "profile")):
            btn = self._tab(label, target)
            self.add_widget(btn)

    def _sync(self, *_):
        self._bg.pos  = self.pos
        self._bg.size = self.size
        self._top.points = [self.x, self.y + self.height,
                            self.x + self.width, self.y + self.height]

    def _tab(self, label, target):
        btn = CalcoraButton(
            text=label,
            background_color=C_PANEL,
            font_size=dp(14),
            bold=True,
        )
        btn._target = target
        btn.bind(on_release=lambda b, t=target: self._go(t))
        return btn

    def _icon(self, label):
        return "Home" if label == "Home" else "Profile"

    def _go(self, target):
        if target == "home" and SESSION.get("role") == "worker":
            target = "worker_home"
        self.sm.transition = SlideTransition(
            direction="left" if target == "profile" else "right",
            duration=0.20)
        self.sm.current = target
        self._refresh_colors()

    def _refresh_colors(self):
        current = self.sm.current
        for btn in self.children:
            if hasattr(btn, "_target"):
                active = btn._target == current or (
                    btn._target == "home" and current == "worker_home")
                btn.background_color = C_BLUE if active else C_PANEL

    def _update_tab_color(self, fl, target):
        pass


# ── Profile screen ────────────────────────────────────────────────────────────

class ProfileScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._unlocked = False
        self._build_locked()

    def _build_locked(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(Label(
            text="Profile", color=C_WHITE, bold=True, font_size=dp(26),
            size_hint=(1, None), height=dp(50),
            pos_hint={"center_x": 0.5, "top": 0.97},
        ))
        lock_box = BoxLayout(orientation="vertical", spacing=dp(16),
                             size_hint=(0.72, None), height=dp(200),
                             pos_hint={"center_x": 0.5, "center_y": 0.52})
        lock_box.add_widget(Label(
            text="[b]Profile is PIN Protected[/b]",
            markup=True, color=C_WHITE, font_size=dp(16),
            halign="center", size_hint_y=None, height=dp(30),
        ))
        unlock_btn = CalcoraButton(
            text="Enter PIN to Unlock",
            background_color=C_BLUE,
            size_hint_y=None, height=BTN_H,
        )
        unlock_btn.bind(on_release=self._ask_pin)
        lock_box.add_widget(unlock_btn)
        if not load_pin():
            setup_btn = CalcoraButton(
                text="Set up PIN",
                background_color=C_GREEN,
                size_hint_y=None, height=BTN_H,
            )
            setup_btn.bind(on_release=self._setup_pin)
            lock_box.add_widget(setup_btn)
        root.add_widget(lock_box)
        self.add_widget(root)

    def _setup_pin(self, *_):
        pin_popup("Set a 4-digit Owner PIN",
                  on_success=lambda p: (save_pin(p), self._unlock()),
                  confirm=True)

    def _ask_pin(self, *_):
        if not load_pin():
            self._setup_pin()
            return
        pin_popup("Enter Owner PIN",
                  on_success=self._unlock,
                  on_cancel=lambda: None,
                  confirm=False)

    def _unlock(self, *_):
        self._unlocked = True
        self._build()

    def on_pre_enter(self, *_):
        self._unlocked = False
        self._build_locked()

    def _build(self):
        self.clear_widgets()
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))

        # Lock button top-right
        lock_btn = CalcoraButton(
            text="Lock", background_color=C_PANEL2,
            size_hint=(0.20, 0.06), font_size=dp(12),
            pos_hint={"right": 0.97, "top": 0.97},
        )
        lock_btn.bind(on_release=lambda *_: (
            setattr(self, "_unlocked", False) or self._build_locked()))
        root.add_widget(lock_btn)

        scroll_content = BoxLayout(
            orientation="vertical",
            padding=[dp(20), dp(50), dp(20), dp(16)],
            spacing=dp(14),
            size_hint_y=None,
        )
        scroll_content.bind(minimum_height=scroll_content.setter("height"))

        # ── Avatar / photo ──
        avatar_box = BoxLayout(orientation="vertical",
                               size_hint_y=None, height=dp(160),
                               spacing=dp(8))

        # Photo or initials circle
        self._photo_path = ""
        self.avatar_img = KivyImage(
            size_hint=(None, None), size=(dp(88), dp(88)),
            allow_stretch=True, keep_ratio=True,
        )
        self.avatar_circle = Widget(
            size_hint=(None, None), size=(dp(88), dp(88)))
        self._draw_avatar(self.avatar_circle)

        avatar_stack = FloatLayout(size_hint_y=None, height=dp(96))
        self.avatar_circle.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        self.avatar_img.pos_hint    = {"center_x": 0.5, "center_y": 0.5}
        avatar_stack.add_widget(self.avatar_circle)
        avatar_stack.add_widget(self.avatar_img)

        # Camera/upload button overlay
        upload_btn = CalcoraButton(
            text="+ Photo",
            background_color=(*C_BLUE[:3], 0.85),
            size_hint=(None, None), size=(dp(70), dp(28)),
            pos_hint={"center_x": 0.5, "y": 0.0},
            font_size=dp(11),
        )
        upload_btn.bind(on_release=self._pick_photo)
        avatar_stack.add_widget(upload_btn)
        avatar_box.add_widget(avatar_stack)

        self.name_lbl = Label(
            text="Business Name", color=C_WHITE, bold=True,
            font_size=dp(20), halign="center", size_hint_y=None, height=dp(32),
        )
        self.name_lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        avatar_box.add_widget(self.name_lbl)
        scroll_content.add_widget(avatar_box)

        # ── Divider ──
        scroll_content.add_widget(self._divider())

        # ── Editable fields ──
        scroll_content.add_widget(self._section_label("Business Info"))

        self.f_name     = self._field("Business / Owner Name", "")
        self.f_phone    = self._field("Phone Number", "")
        self.f_email    = self._field("Email Address", "")
        self.f_address  = self._field("Business Address", "")

        for f in (self.f_name, self.f_phone, self.f_email, self.f_address):
            scroll_content.add_widget(f)

        scroll_content.add_widget(self._divider())
        scroll_content.add_widget(self._section_label("Business Type"))

        self._prof_sel_biz  = get_biz_type()
        self._prof_biz_btns = []
        biz_scroll = ScrollView(size_hint_y=None, height=dp(90),
                                do_scroll_y=False, do_scroll_x=True)
        biz_row = BoxLayout(size_hint=(None,1), spacing=dp(8))
        biz_row.bind(minimum_width=biz_row.setter("width"))
        for name, cfg in BUSINESS_TYPES.items():
            btn = CalcoraButton(
                text=f"{cfg['icon']}\n{name}",
                background_color=C_BLUE if name==self._prof_sel_biz else C_PANEL2,
                size_hint=(None,1), width=dp(110), font_size=dp(11),
            )
            btn.bind(on_release=lambda b, n=name: self._prof_sel_biz_type(n))
            biz_row.add_widget(btn)
            self._prof_biz_btns.append((name, btn))
        biz_scroll.add_widget(biz_row)
        scroll_content.add_widget(biz_scroll)

        self.prof_biz_desc = Label(
            text=BUSINESS_TYPES[self._prof_sel_biz]["desc"],
            color=C_GREEN, font_size=dp(11), halign="center",
            size_hint_y=None, height=dp(22),
        )
        self.prof_biz_desc.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        scroll_content.add_widget(self.prof_biz_desc)

        scroll_content.add_widget(self._divider())
        scroll_content.add_widget(self._section_label("Country & Currency"))

        # Country selector (linked to currency)
        COUNTRIES = [
            ("Uganda",   "UGX", "UG"),
            ("Tanzania", "TZS", "TZ"),
            ("Kenya",    "KES", "KE"),
        ]
        self._country_data  = COUNTRIES
        self._sel_country   = 0   # index into COUNTRIES

        country_row = BoxLayout(size_hint_y=None, height=ROW_H, spacing=dp(8))
        self._country_btns = []
        for i, (country, cur, code) in enumerate(COUNTRIES):
            btn = CalcoraButton(
                text=f"{country}\n{cur}",
                background_color=C_BLUE if i == 0 else C_PANEL2,
                font_size=dp(12),
            )
            btn.bind(on_release=lambda b, idx=i: self._select_country(idx))
            country_row.add_widget(btn)
            self._country_btns.append(btn)
        scroll_content.add_widget(country_row)

        # Read-only currency display
        self.currency_lbl = Label(
            text="Selected: UGX  (Uganda)",
            color=C_GREEN, font_size=dp(13),
            halign="center", size_hint_y=None, height=dp(28),
        )
        self.currency_lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        scroll_content.add_widget(self.currency_lbl)

        scroll_content.add_widget(self._divider())
        scroll_content.add_widget(self._section_label("Theme"))

        self._theme_mode = load_theme()
        theme_row = BoxLayout(size_hint_y=None, height=ROW_H, spacing=dp(10))
        self.dark_btn = CalcoraButton(
            text="Dark",
            background_color=C_BLUE if self._theme_mode != "light" else C_PANEL2,
        )
        self.light_btn = CalcoraButton(
            text="Light",
            background_color=C_BLUE if self._theme_mode == "light" else C_PANEL2,
        )
        self.dark_btn.bind(on_release=lambda *_: self._select_theme("dark"))
        self.light_btn.bind(on_release=lambda *_: self._select_theme("light"))
        theme_row.add_widget(self.dark_btn)
        theme_row.add_widget(self.light_btn)
        scroll_content.add_widget(theme_row)

        scroll_content.add_widget(self._divider())
        scroll_content.add_widget(self._section_label("Tax / VAT Settings"))

        # VAT rate input
        vat_row = BoxLayout(size_hint_y=None, height=ROW_H, spacing=dp(10))
        vat_row.add_widget(Label(
            text="VAT Rate %:", color=C_WHITE, font_size=dp(14),
            halign="left", valign="middle", size_hint_x=0.4,
        ))
        self.f_vat = StyledInput(
            hint_text="e.g. 18", text="18",
            multiline=False, input_filter="float",
            size_hint_x=0.6,
        )
        vat_row.add_widget(self.f_vat)
        scroll_content.add_widget(vat_row)

        # VAT description label
        self.vat_lbl = Label(
            text="18% of gross profit will be deducted as tax",
            color=C_GREY, font_size=dp(12),
            halign="center", size_hint_y=None, height=dp(26),
        )
        self.vat_lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        self.f_vat.bind(text=self._update_vat_label)
        scroll_content.add_widget(self.vat_lbl)

        scroll_content.add_widget(self._divider())
        scroll_content.add_widget(self._section_label("Business Summary"))

        # summary cards — auto height
        self.cards_grid = GridLayout(cols=2, spacing=dp(10),
                                     size_hint_y=None, height=dp(200),
                                     row_default_height=dp(90),
                                     row_force_default=True)
        scroll_content.add_widget(self.cards_grid)

        scroll_content.add_widget(self._divider())

        # ── Store Switcher ──
        scroll_content.add_widget(self._section_label("My Stores"))

        self._stores_box = BoxLayout(orientation="vertical", spacing=dp(8),
                                      size_hint_y=None, height=dp(10))
        self._stores_box.bind(minimum_height=self._stores_box.setter("height"))
        scroll_content.add_widget(self._stores_box)

        add_store_btn = CalcoraButton(
            text="+ Add New Store",
            background_color=C_PANEL2,
            size_hint_y=None, height=dp(42),
            font_size=dp(13),
        )
        add_store_btn.bind(on_release=self._add_store_popup)
        scroll_content.add_widget(add_store_btn)

        scroll_content.add_widget(self._divider())

        # ── Save button ──
        save_btn = CalcoraButton(
            text="Save Profile",
            background_color=C_BLUE,
            size_hint_y=None, height=BTN_H,
        )
        save_btn.bind(on_release=self._save_profile)
        scroll_content.add_widget(save_btn)

        # ── Help link ──
        help_btn = CalcoraButton(
            text="Help & User Guide",
            background_color=C_PANEL2,
            size_hint_y=None, height=dp(44),
            font_size=dp(13),
        )
        help_btn.bind(on_release=lambda *_: self._go_help())
        scroll_content.add_widget(help_btn)

        # padding at bottom for nav bar
        scroll_content.add_widget(Widget(size_hint_y=None, height=dp(20)))

        scroll = ScrollView(size_hint=(1,1), pos_hint={"x":0,"y":0})
        scroll.add_widget(scroll_content)
        root.add_widget(scroll)

        self.add_widget(root)
        self._refresh_stores_list()
        self._load_profile()
        # populate summary immediately
        Clock.schedule_once(lambda *_: self._refresh_summary(), 0.1)

    def _go_help(self):
        self.manager.transition = SlideTransition(direction="left", duration=0.22)
        self.manager.current    = "help"

    def _refresh_stores_list(self):
        if not hasattr(self, "_stores_box"):
            return
        app        = App.get_running_app()
        stores_data = load_stores()
        extra_list  = stores_data.get("list", [])
        def_name    = stores_data.get("default_name", "Main Store")
        def_biz     = stores_data.get("default_biz", get_biz_type())

        self._stores_box.clear_widgets()
        all_stores = [{"id": "default", "name": def_name, "biz_type": def_biz}] \
                     + extra_list
        for s in all_stores:
            is_active = s["id"] == app.active_store_id
            row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
            with row.canvas.before:
                col = BUSINESS_TYPES.get(s.get("biz_type",""),{}).get("color", C_PANEL)
                Color(*col[:3], 0.12 if not is_active else 0.25)
                row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(10)])
            row.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))

            icon = BUSINESS_TYPES.get(s.get("biz_type",""),{}).get("icon","🏪")
            lbl  = Label(
                text=f"{'► ' if is_active else '   '}{icon}  {s['name']}",
                color=C_GREEN if is_active else C_WHITE,
                font_size=dp(13), halign="left", valign="middle",
                bold=is_active,
            )
            lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
            row.add_widget(lbl)

            if not is_active:
                sw_btn = CalcoraButton(
                    text="Switch",
                    background_color=C_BLUE,
                    size_hint=(None,1), width=dp(80), font_size=dp(12),
                )
                sw_btn.bind(on_release=lambda b,sid=s["id"],sname=s["name"]:
                            self._confirm_switch(sid, sname))
                row.add_widget(sw_btn)
            else:
                active_lbl = Label(
                    text="ACTIVE", color=C_GREEN, font_size=dp(11), bold=True,
                    size_hint=(None,1), width=dp(60),
                )
                row.add_widget(active_lbl)

            self._stores_box.add_widget(row)
        self._stores_box.height = len(all_stores) * dp(52)

    def _confirm_switch(self, store_id, store_name):
        pin_popup(
            f"Enter PIN to switch to\n{store_name}",
            on_success=lambda: self._do_switch(store_id),
            on_cancel=lambda: None,
            confirm=False,
        )

    def _do_switch(self, store_id):
        app = App.get_running_app()
        app.switch_store(store_id)
        self._refresh_stores_list()
        self._flash(f"Switched to store successfully!")

    def _add_store_popup(self, *_):
        content = BoxLayout(orientation="vertical", spacing=dp(14), padding=dp(20))
        with content.canvas.before:
            Color(*C_PANEL)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                            radius=[dp(14)])
        content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))

        content.add_widget(Label(text="Add New Store", color=C_WHITE, bold=True,
                                  font_size=dp(16), halign="center",
                                  size_hint_y=None, height=dp(30)))
        name_inp = StyledInput(hint_text="Store name", multiline=False,
                                size_hint_y=None, height=ROW_H)
        content.add_widget(name_inp)

        # Business type for new store
        sel_biz = [list(BUSINESS_TYPES.keys())[0]]
        biz_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        biz_btns = []
        for name in BUSINESS_TYPES:
            btn = CalcoraButton(
                text=name, font_size=dp(10),
                background_color=C_BLUE if name == sel_biz[0] else C_PANEL2,
                size_hint=(None, 1), width=dp(100),
            )
            def _pick(b, n=name):
                sel_biz[0] = n
                for bb in biz_btns:
                    bb.background_color = C_BLUE if bb.text == n else C_PANEL2
            btn.bind(on_release=_pick)
            biz_row.add_widget(btn)
            biz_btns.append(btn)
        biz_scroll = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(50))
        biz_scroll.add_widget(biz_row)
        content.add_widget(biz_scroll)

        popup = Popup(title="", content=content, size_hint=(0.90, None),
                      height=dp(300), auto_dismiss=True,
                      background_color=(*C_PANEL[:3], 1), separator_height=0)
        btn_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))

        def _add(*_):
            sname = name_inp.text.strip()
            if not sname:
                return
            import uuid
            sid         = str(uuid.uuid4())[:8]
            stores_data = load_stores()
            new_store = {"id": sid, "name": sname, "biz_type": sel_biz[0]}
            stores_data.setdefault("list", []).append(new_store)
            save_stores(stores_data)
            popup.dismiss()
            self._refresh_stores_list()
            self._flash(f"Store '{sname}' added!")
            # Also create on Supabase if online
            if FB_AVAILABLE and fb and fb.is_online():
                def _create_online():
                    ok, online_id, store_code = fb.create_store(sname, sel_biz[0])
                    if ok and online_id:
                        data = load_stores()
                        for item in data.get("list", []):
                            if item.get("id") == sid:
                                item["online_id"] = online_id
                                item["store_code"] = store_code
                                break
                        save_stores(data)
                threading.Thread(target=_create_online, daemon=True).start()

        add_btn = CalcoraButton(text="Add Store", background_color=C_BLUE)
        add_btn.bind(on_release=_add)
        can_btn = CalcoraButton(text="Cancel", background_color=C_PANEL2)
        can_btn.bind(on_release=popup.dismiss)
        btn_row.add_widget(add_btn)
        btn_row.add_widget(can_btn)
        content.add_widget(btn_row)
        popup.open()

    def _prof_sel_biz_type(self, name):
        self._prof_sel_biz = name
        for n, btn in self._prof_biz_btns:
            btn.background_color = C_BLUE if n == name else C_PANEL2
        self.prof_biz_desc.text = BUSINESS_TYPES[name]["desc"]

    def _select_country(self, idx):
        self._sel_country = idx
        country, cur, code = self._country_data[idx]
        for i, btn in enumerate(self._country_btns):
            btn.background_color = C_BLUE if i == idx else C_PANEL2
        self.currency_lbl.text = f"Selected: {cur}  ({country})"

    def _select_theme(self, mode):
        self._theme_mode = mode
        self.dark_btn.background_color = C_BLUE if mode == "dark" else C_PANEL2
        self.light_btn.background_color = C_BLUE if mode == "light" else C_PANEL2

    def _update_vat_label(self, *_):
        try:
            v = float(self.f_vat.text or "0")
            self.vat_lbl.text = f"{v:.1f}% of gross profit will be deducted as tax"
        except ValueError:
            self.vat_lbl.text = "Enter a valid VAT %"

    def _draw_avatar(self, w):
        w.canvas.clear()
        with w.canvas:
            Color(*C_BLUE)
            Ellipse(pos=w.pos, size=w.size)

    def _pick_photo(self, *_):
        """Ask permission then open photo chooser."""
        content = BoxLayout(orientation="vertical", spacing=dp(16), padding=dp(24))
        with content.canvas.before:
            Color(*C_PANEL)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                            radius=[dp(14)])
        content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))

        content.add_widget(Label(
            text="Access Photos",
            color=C_WHITE, bold=True, font_size=dp(18),
            halign="center", size_hint_y=None, height=dp(32),
        ))
        content.add_widget(Label(
            text="Calcora would like to access your photos\nto set your profile picture.",
            color=C_GREY, font_size=dp(13),
            halign="center", size_hint_y=None, height=dp(52),
        ))

        popup = Popup(
            title="", content=content,
            size_hint=(0.85, None), height=dp(260),
            auto_dismiss=True,
            background_color=(*C_PANEL[:3], 1),
            separator_height=0,
        )

        btn_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))

        def _allow(*_):
            popup.dismiss()
            Clock.schedule_once(lambda *_: self._open_chooser(), 0.2)

        allow_btn = CalcoraButton(text="Allow Access", background_color=C_BLUE)
        allow_btn.bind(on_release=_allow)
        deny_btn  = CalcoraButton(text="Don't Allow",  background_color=C_PANEL2)
        deny_btn.bind(on_release=popup.dismiss)
        btn_row.add_widget(deny_btn)
        btn_row.add_widget(allow_btn)
        content.add_widget(btn_row)
        popup.open()

    def _open_chooser(self):
        """Open file chooser after permission granted."""
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        with content.canvas.before:
            Color(*C_PANEL)
            content._bg = RoundedRectangle(pos=content.pos, size=content.size,
                                            radius=[dp(12)])
        content.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))

        # Try Pictures folder first, then home
        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
        start_path = pictures if os.path.exists(pictures) else os.path.expanduser("~")

        fc = FileChooserListView(
            filters=["*.png","*.jpg","*.jpeg","*.bmp","*.gif","*.webp"],
            path=start_path,
        )
        content.add_widget(fc)

        btn_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=dp(10))
        popup = Popup(
            title="Select Profile Photo",
            content=content,
            size_hint=(0.95, 0.88),
            background_color=(*C_PANEL[:3], 1),
            title_color=C_GREEN,
        )

        def _select(*_):
            if fc.selection:
                self._set_photo(fc.selection[0])
            popup.dismiss()

        sel_btn = CalcoraButton(text="Select", background_color=C_BLUE)
        sel_btn.bind(on_release=_select)
        can_btn = CalcoraButton(text="Cancel", background_color=C_PANEL2)
        can_btn.bind(on_release=popup.dismiss)
        btn_row.add_widget(sel_btn)
        btn_row.add_widget(can_btn)
        content.add_widget(btn_row)
        popup.open()

    def _set_photo(self, path):
        if path and os.path.exists(path):
            self._photo_path      = path
            self.avatar_img.source= path
            self.avatar_img.reload()
            self.avatar_circle.opacity = 0   # hide blue circle when photo set

    def _divider(self):
        d = Widget(size_hint_y=None, height=dp(1))
        with d.canvas:
            Color(*C_BLUE[:3], 0.25)
            d._r = Rectangle(pos=d.pos, size=d.size)
        d.bind(pos=lambda w, v: setattr(w._r, "pos",  v),
               size=lambda w, v: setattr(w._r, "size", v))
        return d

    def _section_label(self, text):
        lbl = Label(text=text, color=C_GREEN, bold=True,
                    font_size=dp(13), halign="left", valign="middle",
                    size_hint_y=None, height=dp(28))
        lbl.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        return lbl

    def _field(self, hint, default):
        inp = StyledInput(
            hint_text=hint, text=default,
            multiline=False, size_hint_y=None, height=ROW_H,
        )
        return inp

    def _summary_card(self, title, value, color):
        box = PanelBox(orientation="vertical", padding=dp(10),
                       spacing=dp(4), border_color=color)
        t = Label(text=title, color=color, bold=True,
                  halign="center", valign="middle",
                  font_size=dp(12))
        t.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        v = Label(text=value, color=C_WHITE, bold=True,
                  halign="center", valign="middle",
                  font_size=dp(15))
        v.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        box.add_widget(t)
        box.add_widget(v)
        return box

    def refresh(self):
        if not self._unlocked:
            self._build_locked()
            return
        self._load_profile()
        self._refresh_summary()
        self._refresh_stores_list()

    def _load_profile(self):
        app = App.get_running_app()
        pf  = app.active_profile_file() if app else PROFILE_FILE
        if not os.path.exists(pf):
            auth = load_auth() or {}
            if auth:
                self.f_name.text  = auth.get("business", "")
                self.f_phone.text = auth.get("phone", "")
                self.f_email.text = auth.get("email", "")
                self.name_lbl.text = auth.get("business", "Business Name") or "Business Name"
                saved_biz = auth.get("biz_type", "Home Retail")
                if saved_biz in BUSINESS_TYPES:
                    self._prof_sel_biz_type(saved_biz)
                saved_cur = auth.get("currency", "UGX")
                for i, (country, cur, code) in enumerate(self._country_data):
                    if cur == saved_cur:
                        self._select_country(i)
                        break
                self._select_theme(auth.get("theme", load_theme()))
            return
        try:
            with open(pf, "r", encoding="utf-8") as f:
                p = json.load(f)
            self.f_name.text    = p.get("name",    "")
            self.f_phone.text   = p.get("phone",   "")
            self.f_email.text   = p.get("email",   "")
            self.f_address.text = p.get("address", "")
            self.f_vat.text     = str(p.get("vat", "18"))
            self.name_lbl.text  = p.get("name", "Business Name") or "Business Name"
            # restore biz_type
            saved_biz = p.get("biz_type", "Home Retail")
            if saved_biz in BUSINESS_TYPES:
                self._prof_sel_biz_type(saved_biz)
            # restore country selection
            saved_cur = p.get("currency", "UGX")
            for i, (country, cur, code) in enumerate(self._country_data):
                if cur == saved_cur:
                    self._select_country(i)
                    break
            self._select_theme(p.get("theme", load_theme()))
            # restore photo
            photo = p.get("photo", "")
            if photo and os.path.exists(photo):
                self._set_photo(photo)
        except (json.JSONDecodeError, OSError):
            pass

    def _save_profile(self, *_):
        country, cur, code = self._country_data[self._sel_country]
        try:
            vat_val = float(self.f_vat.text or "18")
        except ValueError:
            vat_val = 18.0
        p = {
            "name":     self.f_name.text.strip(),
            "phone":    self.f_phone.text.strip(),
            "email":    self.f_email.text.strip(),
            "address":  self.f_address.text.strip(),
            "currency": cur,
            "country":  country,
            "vat":      vat_val,
            "photo":    self._photo_path,
            "biz_type": self._prof_sel_biz,
            "theme":    self._theme_mode,
        }
        try:
            app = App.get_running_app()
            pf  = app.active_profile_file() if app else PROFILE_FILE
            existing = {}
            if os.path.exists(pf):
                try:
                    with open(pf, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except Exception:
                    existing = {}
            if existing.get("subscription_expires"):
                p["subscription_expires"] = existing["subscription_expires"]
            if existing.get("subscription_status"):
                p["subscription_status"] = existing["subscription_status"]
            with open(pf, "w", encoding="utf-8") as f:
                json.dump(p, f, indent=2)
        except OSError:
            pass
        self.name_lbl.text = p["name"] or "Business Name"
        apply_theme(self._theme_mode)
        self._refresh_summary()
        # flash confirmation
        self._flash("Profile saved!")

    def _flash(self, text):
        msg = Label(text=text, color=C_GREEN, font_size=dp(14),
                    size_hint_y=None, height=dp(30), halign="center")
        msg.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        msg.opacity = 0
        # add to scroll content (first child of scroll, which is first child of root)
        try:
            self.children[0].children[0].children[0].add_widget(msg)
            Animation(opacity=1, duration=0.3).start(msg)
            Clock.schedule_once(
                lambda *_: Animation(opacity=0, duration=0.5).start(msg), 1.5)
        except Exception:
            pass

    def _refresh_summary(self):
        self.cards_grid.clear_widgets()
        app = App.get_running_app()
        totals = app.finance_math()
        cur    = app.currency()
        cards = [
            ("Total Revenue",  f"{cur} {money(totals['revenue'])}",    C_BLUE),
            ("Net Profit",     f"{cur} {money(totals['net_profit'])}", C_GREEN),
            ("Tax Paid",       f"{cur} {money(totals['tax'])}",        C_ERROR),
            ("Items in Stock", str(len(app.inventory)),                 C_PURPLE),
        ]
        for title, value, color in cards:
            self.cards_grid.add_widget(
                self._summary_card(title, value, color))



# ── Splash / loading screen ───────────────────────────────────────────────────


# ── Help screen ───────────────────────────────────────────────────────────────

HELP_SECTIONS = [
    ("Getting Started", [
        ("Sign Up", "Open the app and tap 'Sign Up'. Choose your country, business type, fill in your business name, email, phone and a password. Your business type controls which fields appear throughout the app."),
        ("Log In", "If you already have an account, tap 'Log In' and enter your email and password. You can also use 'Continue with Google'."),
        ("Set Owner PIN", "The first time you open Stock, Finance or Profile, you will be asked to set a 4-digit PIN. This PIN protects owner-only screens from staff access."),
    ]),
    ("Daily Sales", [
        ("Recording a Sale", "From the home screen tap 'Daily Sales'. Each row has: Date, Item name, Quantity, Price per unit, and Total (auto-calculated). Fill in as many rows as needed."),
        ("Adding More Rows", "Tap '+ Add Row' to add more sale lines. The TOTAL EARNED bar at the bottom updates live as you type."),
        ("Submitting Sales", "When done, tap 'Submit & Calculate'. The app checks that every item is in your stock, deducts the quantities, calculates profit, tax and net profit, then saves to History."),
        ("Errors", "If an item is not in stock or has insufficient quantity, a red error message appears. Add the item to stock first."),
    ]),
    ("Stock Management", [
        ("Adding Stock", "Tap 'Stock' from home (enter your PIN). Fill in: Item name, select the unit (kg, pcs, etc.), quantity, buying price, and selling price. Tap 'Add Stock'."),
        ("Restocking", "For items already in inventory, enter the name and new quantities then tap 'Restock'. The system calculates the running average buying price automatically."),
        ("Craft Sellers", "If your business type is Craft & Art, the buying price fields are hidden — only the selling price is needed since you make the items yourself."),
        ("Deleting Items", "Enter the item name and tap 'Delete'. You will be asked to confirm before the item is removed from inventory."),
    ]),
    ("Finance", [
        ("Viewing Finances", "Tap 'Finance' and enter your PIN. You will see: Total Revenue, Taxes (VAT), and Net Profit — all calculated from your submitted sales."),
        ("VAT / Tax Rate", "Go to Profile > Tax/VAT Settings to set your VAT percentage. The default is 18%. The system applies: Tax = (Revenue - Cost) x VAT%."),
        ("Reset Finance", "The red 'Reset All Finance Data' button clears all sales history. This cannot be undone — use with caution."),
        ("Locking", "Tap 'Lock' to re-lock the finance screen without leaving."),
    ]),
    ("Inventory", [
        ("Viewing Items", "Tap 'Inventory' from home to see all stocked items, their quantities, and their sales share percentage."),
        ("Item Details", "Tap any item to see: Capital invested, Accumulated capital, In-stock quantity, Net Profit, Taxes, Revenue, Sales share, and a restocking recommendation."),
        ("Search", "Use the search bar at the top to filter items by name. Tap 'Clear Search' to reset."),
    ]),
    ("History", [
        ("Daily Sheets", "Tap 'History' to see all archived daily sales sheets, newest first. Each sheet shows the date, items sold, quantities, prices and total earned."),
    ]),
    ("Profile & Settings", [
        ("Business Info", "In Profile you can update your business name, phone, email and address."),
        ("Business Type", "Change your business type here. This updates which fields appear in Stock and adapts the app to your business."),
        ("Country & Currency", "Select Uganda (UGX), Tanzania (TZS) or Kenya (KES). The currency is shown on all amounts throughout the app."),
        ("Profile Photo", "Tap '+ Photo' to set a profile picture. The app will ask permission to access your photos first."),
        ("Multiple Stores", "In Profile, scroll to 'My Stores'. Tap '+ Add New Store' to create a second store. Tap 'Switch' next to any store (PIN required) to switch. Each store has completely separate inventory, sales, finance and profile data."),
    ]),
    ("Tips & Tricks", [
        ("Quick PIN", "The same PIN protects Stock, Finance and Profile. Change it anytime from Finance > Change PIN."),
        ("Google Sign-In", "On Android, 'Continue with Google' uses your Google account for quick secure login without remembering a password."),
        ("Offline First", "Calcora works fully offline. All data is saved on your device. No internet needed for daily operations."),
        ("Backup", "Your data files (calcora_data.json, calcora_profile.json) are in the app folder. Copy them to back up your data."),
    ]),
]


def helpbot_response(question):
    if not question or not question.strip():
        return "Ask me anything about using Calcora, such as sales, stock, finance, history, or profile settings."
    q = question.lower()
    if any(word in q for word in ["sale", "record", "submit", "daily"]):
        return "To record a sale, open Daily Sales, add rows for each item, enter quantity and unit price, then tap 'Submit & Calculate'. If an item is not in stock, add it first in Stock."
    if any(word in q for word in ["stock", "inventory", "restock", "item"]):
        return "Go to Stock, enter the item name, quantity, buying price and selling price, then tap Add Stock. For existing items, use Restock to update quantities."
    if any(word in q for word in ["finance", "profit", "tax", "vat"]):
        return "Open Finance with your PIN to see revenue, tax and net profit. Update the VAT rate in Profile > Tax/VAT Settings if needed."
    if any(word in q for word in ["profile", "settings", "business", "currency", "country"]):
        return "In Profile you can update business name, contact details, currency, and business type. This controls which fields appear in Stock and helps keep reports accurate."
    if any(word in q for word in ["history", "past", "sheet", "sales history"]):
        return "Tap History to view past daily sales sheets. Each entry shows sold items, quantities and totals. Use this to review what your business sold over time."
    if any(word in q for word in ["help", "guide", "ask", "chat"]):
        return "Type your question and press Ask. I can guide you through using Daily Sales, Stock, Finance, History, Profile and more."
    if any(word in q for word in ["signup", "sign up", "account"]):
        return "Tap Sign Up to create a new account. Fill in your business details, email, phone and password, then tap Submit."
    if any(word in q for word in ["login", "log in", "sign in"]):
        return "Use the Login screen with your email and password. If you're on Android, you can also use Continue with Google."
    return "I’m here to help with Calcora. Try a question like 'How do I add stock?', 'How do I record a sale?', or 'How do I check profit?'."


class HelpScreen(CalcoraScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build()

    def _build(self):
        root = FloatLayout()
        root.add_widget(GradientBG(size_hint=(1,1), pos_hint={"x":0,"y":0}))
        root.add_widget(self.float_back_button())

        root.add_widget(Label(
            text="Help & User Guide",
            color=C_WHITE, bold=True, font_size=dp(22),
            size_hint=(0.7, None), height=dp(44),
            pos_hint={"center_x": 0.5, "top": 0.97},
            halign="center",
        ))

        content = BoxLayout(
            orientation="vertical",
            padding=[dp(16), dp(10), dp(16), dp(16)],
            spacing=dp(12),
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        for section_title, items in HELP_SECTIONS:
            # Section header
            hdr = BoxLayout(size_hint_y=None, height=dp(38))
            with hdr.canvas.before:
                Color(*C_BLUE[:3], 0.18)
                hdr._bg = RoundedRectangle(pos=hdr.pos, size=hdr.size,
                                            radius=[dp(10)])
            hdr.bind(pos=lambda w,v: setattr(w._bg,"pos",v),
                     size=lambda w,v: setattr(w._bg,"size",v))
            hdr_lbl = Label(
                text=section_title, color=C_BLUE, bold=True,
                font_size=dp(15), halign="left", valign="middle",
                padding=[dp(12), 0],
            )
            hdr_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
            hdr.add_widget(hdr_lbl)
            content.add_widget(hdr)

            for topic, body in items:
                # Topic card
                card = PanelBox(
                    orientation="vertical",
                    padding=[dp(14), dp(10), dp(14), dp(10)],
                    spacing=dp(4),
                    size_hint_y=None,
                )
                topic_lbl = Label(
                    text=topic, color=C_GREEN, bold=True,
                    font_size=dp(13), halign="left", valign="middle",
                    size_hint_y=None, height=dp(24),
                )
                topic_lbl.bind(size=lambda w,*_: setattr(w,"text_size",w.size))

                body_lbl = Label(
                    text=body, color=C_WHITE, font_size=dp(12),
                    halign="left", valign="top",
                    text_size=(None, None),
                    size_hint_y=None,
                )
                def _update_body(w, *_):
                    w.text_size = (w.width, None)
                    w.height    = w.texture_size[1] + dp(8)
                body_lbl.bind(size=_update_body, width=_update_body)

                card.add_widget(topic_lbl)
                card.add_widget(body_lbl)

                # Auto height
                def _card_height(c, *_):
                    c.height = sum(ch.height for ch in c.children) + dp(24)
                card.bind(children=_card_height)
                card.height = dp(80)

                content.add_widget(card)

        # Chatbot assistant section
        assistant_hdr = Label(
            text="Chat with Calcora Assistant",
            color=C_CYAN, bold=True, font_size=dp(16),
            size_hint_y=None, height=dp(32), halign="left",
            valign="middle",
        )
        assistant_hdr.bind(size=lambda w,*_: setattr(w,"text_size",w.size))
        content.add_widget(assistant_hdr)

        self.chat_box = BoxLayout(orientation="vertical", spacing=dp(8),
                                  size_hint_y=None)
        self.chat_box.bind(minimum_height=self.chat_box.setter("height"))
        self._add_chat_bubble("Hi! I’m Calcora Assistant. Ask me how to use the app.", False)

        chat_panel = PanelBox(orientation="vertical",
                               padding=[dp(12), dp(12), dp(12), dp(12)],
                               spacing=dp(8), size_hint_y=None)
        chat_panel.add_widget(self.chat_box)
        chat_panel.height = dp(220)
        content.add_widget(chat_panel)

        input_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        self.chat_input = StyledInput(hint_text="Type your question here...",
                                      multiline=False)
        ask_btn = CalcoraButton(text="Ask", background_color=C_GREEN,
                                 size_hint=(None, 1), width=dp(90))
        ask_btn.bind(on_release=lambda *_: self._send_chat_question())
        input_row.add_widget(self.chat_input)
        input_row.add_widget(ask_btn)
        content.add_widget(input_row)

        scroll = ScrollView(
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
        )
        inner = BoxLayout(size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))
        inner.add_widget(Widget(size_hint_y=None, height=dp(54)))
        inner.add_widget(content)
        scroll.add_widget(inner)
        root.add_widget(scroll)
        self.add_widget(root)

    def _add_chat_bubble(self, text, from_user=True):
        bubble = PanelBox(
            orientation="vertical",
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(4),
            size_hint_y=None,
            bg_color=C_PANEL2 if from_user else C_PANEL,
            border_color=C_BLUE if from_user else C_GREEN,
        )
        label = Label(
            text=text,
            color=C_WHITE,
            font_size=dp(13),
            halign="left",
            valign="top",
            text_size=(None, None),
            size_hint_y=None,
        )
        def _resize(w, *_):
            w.text_size = (w.width, None)
            w.height = w.texture_size[1] + dp(10)
            bubble.height = w.height + dp(20)
        label.bind(size=_resize, width=_resize)
        bubble.add_widget(label)
        self.chat_box.add_widget(bubble)
        return bubble

    def _send_chat_question(self):
        question = self.chat_input.text.strip()
        if not question:
            return
        self._add_chat_bubble(question, from_user=True)
        self.chat_input.text = ""
        answer = helpbot_response(question)
        Clock.schedule_once(lambda dt: self._add_chat_bubble(answer, from_user=False), 0)


# ── Splash screen ─────────────────────────────────────────────────────────────

class SplashScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()

        bg = KivyImage(
            source=os.path.join(BASE_DIR, "calcora load image.png"),
            allow_stretch=True,
            keep_ratio=False,
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
        )
        root.add_widget(bg)

        shade = Widget(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        with shade.canvas.before:
            Color(0, 0, 0, 0.42)
            shade._bg = Rectangle(pos=shade.pos, size=shade.size)
        shade.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                   size=lambda w, v: setattr(w._bg, "size", v))
        root.add_widget(shade)

        content = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(26), dp(26), dp(26), dp(30)],
            size_hint=(1, None),
            height=dp(290),
            pos_hint={"x": 0, "y": 0},
        )
        content.add_widget(Label(
            text="CALCORA",
            color=(1, 1, 1, 1), bold=True, font_size=dp(34),
            halign="center", size_hint_y=None, height=dp(48),
        ))
        content.add_widget(Label(
            text="Calculate Less. Earn More.",
            color=C_GREEN, bold=True, font_size=dp(14),
            halign="center", size_hint_y=None, height=dp(28),
        ))
        owner_btn = CalcoraButton(text="Login as Owner", background_color=C_BLUE,
                                  size_hint_y=None, height=BTN_H)
        worker_btn = CalcoraButton(text="Login as Worker", background_color=C_PURPLE,
                                   size_hint_y=None, height=BTN_H)
        signup_btn = CalcoraButton(text="New here? Sign Up", background_color=C_GREEN,
                                   size_hint_y=None, height=BTN_H)
        owner_btn.bind(on_release=lambda *_: self._go("login"))
        worker_btn.bind(on_release=lambda *_: self._go("worker_login"))
        signup_btn.bind(on_release=lambda *_: self._go("signup"))
        content.add_widget(owner_btn)
        content.add_widget(worker_btn)
        content.add_widget(signup_btn)
        root.add_widget(content)

        self.add_widget(root)

    def _go(self, screen):
        self.manager.transition = SlideTransition(direction="left", duration=0.25)
        self.manager.current = screen


class CalcoraApp(App):
    title   = "Calcora"
    kv_file = ""          # prevent auto-loading calcora.kv

    @property
    def icon(self):
        return os.path.join(BASE_DIR, "calcora icon.png")

    def build(self):
        apply_theme(load_theme())
        Window.clearcolor = C_BG
        self.active_store_id = "default"
        self.inventory = {}
        self.all_sales = []
        self.history   = []
        self._load_data()

        self.sm = ScreenManager()
        self.sm.transition = SlideTransition(duration=0.22)
        for widget, name in (
            (SplashScreen,         "splash"),
            (RoleSelectScreen,     "role_select"),
            (SignupScreen,         "signup"),
            (LoginScreen,          "login"),
            (WorkerLoginScreen,    "worker_login"),
            (WorkerHomeScreen,     "worker_home"),
            (OwnerDashboardScreen, "owner_dashboard"),
            (HomeScreen,           "home"),
            (SalesScreen,          "sales"),
            (StockScreen,          "stock"),
            (FinanceScreen,        "finance"),
            (DetailsScreen,        "details"),
            (HistoryScreen,        "history"),
            (ProfileScreen,        "profile"),
            (HelpScreen,           "help"),
        ):
            self.sm.add_widget(widget(name=name))

        self.sm.current = "splash"

        root = BoxLayout(orientation="vertical")
        root.add_widget(self.sm)

        self.bottom_nav = BottomNav(self.sm, size_hint_y=None, height=dp(60))
        root.add_widget(self.bottom_nav)

        AUTH_SCREENS = ("splash","role_select","signup","login",
                        "worker_login","worker_home")

        def _on_screen_change(*_):
            cur    = self.sm.current
            hidden = cur in AUTH_SCREENS
            self.bottom_nav.opacity = 0 if hidden else 1
            self.bottom_nav.height  = dp(0) if hidden else dp(60)
            self.bottom_nav._refresh_colors()

        self.sm.bind(current=lambda *_: _on_screen_change())
        _on_screen_change()

        # Start Firebase notification polling for owner
        if FB_AVAILABLE and fb.is_online():
            fb.start_polling(interval=30)

        return root

    def active_data_file(self):
        if self.active_store_id == "default":
            return DATA_FILE
        return store_data_file(self.active_store_id)

    def active_profile_file(self):
        if self.active_store_id == "default":
            return PROFILE_FILE
        return store_profile_file(self.active_store_id)

    def active_pin_file(self):
        if self.active_store_id == "default":
            return PIN_FILE
        return store_pin_file(self.active_store_id)

    def switch_store(self, store_id):
        """Save current store, load new store, refresh all screens."""
        self.save_data()
        self.active_store_id = store_id
        # Update active in stores file
        data = load_stores()
        data["active"] = store_id
        save_stores(data)
        # Load new store data
        self.inventory = {}
        self.all_sales = []
        self.history   = []
        self._load_data()
        for sname in ("home","sales","stock","finance","details","history","profile"):
            try:
                s = self.sm.get_screen(sname)
                if hasattr(s, "refresh"):
                    s.refresh()
            except Exception:
                pass

    def _load_data(self):
        f = self.active_data_file()
        if not os.path.exists(f):
            return
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            self.inventory = data.get("inventory", {})
            self.all_sales = data.get("all_sales", [])
            self.history   = data.get("history",   [])
        except (json.JSONDecodeError, OSError):
            pass

    def save_data(self):
        try:
            with open(self.active_data_file(), "w", encoding="utf-8") as f:
                json.dump({
                    "inventory": self.inventory,
                    "all_sales": self.all_sales,
                    "history":   self.history,
                }, f, indent=2)
        except OSError:
            pass

    def _get_sales_for_store(self, store_id, limit=1000):
        """App-level sales getter with Supabase then local history fallback."""
        sales = []
        if FB_AVAILABLE and fb and fb.is_online():
            try:
                sales = fb.get_sales(store_id, limit=limit) or []
            except Exception:
                sales = []
        if not sales:
            # build from local history
            now = datetime.now()
            current_year = now.year
            for entry in self.history:
                for row in entry.get("rows", []):
                    item = dict(row)
                    date_str = (item.get("date") or "").strip()
                    if date_str:
                        try:
                            dt = datetime.strptime(date_str, "%d/%m")
                            item["submitted_at"] = dt.replace(year=current_year).strftime(
                                "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            item["submitted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        item["submitted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    sales.append(item)
        return sales

    def _sale_date(self, sale):
        """Return ISO date string YYYY-MM-DD for a sale dict (app-level)."""
        date_str = (sale.get("submitted_at") or sale.get("created_at") or "").strip()
        if date_str:
            return date_str[:10]
        local_date = (sale.get("date") or "").strip()
        if local_date:
            try:
                dt = datetime.strptime(local_date, "%d/%m")
                return dt.replace(year=datetime.now().year).strftime("%Y-%m-%d")
            except Exception:
                pass
        return ""


    def on_start(self):
        # Set window/taskbar icon — must be called after window is ready
        try:
            icon_path = os.path.join(BASE_DIR, "calcora icon.png")
            if os.path.exists(icon_path):
                self.icon = icon_path
                Window.set_icon(icon_path)
        except Exception:
            pass
        self._check_subscription_notifications()
        # Schedule daily check which will trigger the weekly health check
        try:
            Clock.schedule_interval(lambda dt: self._weekly_health_check(), 24 * 3600)
            # Run once at start to catch today's trigger
            Clock.schedule_once(lambda dt: self._weekly_health_check(), 1)
        except Exception:
            pass

    def _check_subscription_notifications(self):
        pf = self.active_profile_file()
        if not os.path.exists(pf):
            return
        try:
            with open(pf, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            return
        profile = _ensure_subscription_fields(profile)
        expiry = profile.get("subscription_expires")
        try:
            expires_at = datetime.fromisoformat(expiry).date()
        except Exception:
            try:
                expires_at = datetime.strptime(expiry, "%Y-%m-%d").date()
            except Exception:
                return
        store_name = profile.get("store_name") or profile.get("name") or "Your Business"
        days_left = (expires_at - datetime.now().date()).days
        if days_left < 0:
            profile["subscription_status"] = "expired"
            send_app_notification(self.active_store_id,
                                  f"Subscription expired: {store_name}")
        elif days_left <= 7:
            send_app_notification(self.active_store_id,
                                  f"Subscription expiring soon ({days_left} days): {store_name}")
        try:
            with open(pf, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
        except OSError:
            pass

    def _get_online_store_id(self):
        """Return the Supabase/online store id for the active store if present."""
        stores = load_stores()
        if self.active_store_id == "default":
            return stores.get("default_online_id") or "default"
        for it in stores.get("list", []):
            if it.get("id") == self.active_store_id:
                return it.get("online_id") or it.get("id")
        return self.active_store_id

    def _weekly_health_check(self):
        """Compute weekly sales, compare to previous week, adjust health, and send notifications.
        Runs when today's weekday matches the signup weekday and at least 7 days
        have passed since the last weekly report.
        """
        try:
            pf = self.active_profile_file()
            if not os.path.exists(pf):
                return
            with open(pf, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            return

        profile = _ensure_subscription_fields(profile)
        signup_day = profile.get("signup_weekday")
        if signup_day is None:
            # If no signup weekday stored, set it now from signup_date or today
            try:
                sd = profile.get("signup_date")
                if sd:
                    signup_day = datetime.fromisoformat(sd).weekday()
                else:
                    signup_day = datetime.now().weekday()
            except Exception:
                signup_day = datetime.now().weekday()
            profile["signup_weekday"] = signup_day

        today = datetime.now().date()
        if today.weekday() != int(signup_day):
            return

        # Only run if last report was more than 6 days ago
        last_reported = profile.get("last_week_reported")
        if last_reported:
            try:
                last_dt = datetime.fromisoformat(last_reported).date()
                if (today - last_dt).days < 7:
                    return
            except Exception:
                pass

        # Determine target store id (online id preferred)
        target_store = self._get_online_store_id() or self.active_store_id

        # Compute week range: last 7 days ending yesterday
        week_end = datetime.now().date() - timedelta(days=1)
        week_start = week_end - timedelta(days=6)

        sales = self._get_sales_for_store(target_store, limit=1000) or []
        def _in_range(s):
            d = self._sale_date(s)
            if not d:
                return False
            try:
                sd = datetime.fromisoformat(d).date()
            except Exception:
                try:
                    sd = datetime.strptime(d, "%Y-%m-%d").date()
                except Exception:
                    return False
            return week_start <= sd <= week_end

        weekly_sales = [s for s in sales if _in_range(s)]
        current_total = sum(float(x.get("subtotal") or x.get("amount") or 0) for x in weekly_sales)

        previous_total = float(profile.get("last_week_total") or 0)
        # percent change calculation
        if previous_total <= 0:
            change_pct = 100.0 if current_total > 0 else 0.0
        else:
            change_pct = ((current_total - previous_total) / previous_total) * 100.0

        # Compute base health using same logic as dashboard (active days + items sold)
        if not weekly_sales:
            base_health = 0
        else:
            active_days = len({self._sale_date(x) for x in weekly_sales if self._sale_date(x)})
            items_sold = sum(float(x.get("quantity") or 0) for x in weekly_sales)
            days_score = active_days / 7.0
            items_score = min(items_sold, 35) / 35.0
            base_health = min(100, int((days_score * 0.5 + items_score * 0.5) * 100))

        # Adjust health by percent change (increase or decrease)
        adjusted_health = int(max(0, min(100, base_health + change_pct)))

        store_name = profile.get("store_name") or profile.get("name") or "Your Business"

        # Send performance notification with change and new health
        if change_pct > 0:
            msg = f"Weekly sales up {change_pct:.0f}% vs last week — Health {adjusted_health}%: {store_name}"
        elif change_pct < 0:
            msg = f"Weekly sales down {abs(change_pct):.0f}% vs last week — Health {adjusted_health}%: {store_name}"
        else:
            msg = f"Weekly sales unchanged — Health {adjusted_health}%: {store_name}"

        send_app_notification(target_store, msg)

        # Also send unhealthy alert if adjusted health is very low
        if adjusted_health < 15:
            send_app_notification(target_store,
                                  _format_notification_text("Business unhealthy needs attention", "", store_name))

        # Persist new weekly totals
        profile["last_week_total"] = current_total
        profile["last_week_reported"] = today.isoformat()
        try:
            with open(pf, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2)
        except OSError:
            pass

    def on_stop(self):
        self.save_data()

    def item_math(self, item_name):
        rows       = [r for r in self.all_sales if r["item"] == item_name]
        total_sold = sum(r["quantity"] for r in self.all_sales)
        units_sold = sum(r["quantity"] for r in rows)
        revenue    = sum(r.get("amount", 0) for r in rows)
        capital    = sum(r.get("buying_price", 0) * r.get("quantity", 0) for r in rows)
        gross      = revenue - capital
        tax        = gross * self.vat_rate()
        net_profit = gross - tax
        return {
            "revenue":    revenue,
            "capital":    capital,
            "tax":        tax,
            "net_profit": net_profit,
            "percentage": (units_sold / total_sold * 100) if total_sold else 0,
        }

    def finance_math(self):
        revenue = sum(r.get("amount", 0) for r in self.all_sales)
        capital = sum(r.get("buying_price", 0) * r.get("quantity", 0)
                      for r in self.all_sales)
        gross      = revenue - capital
        tax        = gross * self.vat_rate()
        net_profit = gross - tax
        return {"revenue": revenue, "tax": tax, "net_profit": net_profit}

    def vat_rate(self):
        """Read VAT % from saved profile, fallback to 18%."""
        try:
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    p = json.load(f)
                return float(p.get("vat", 18)) / 100
        except Exception:
            pass
        return VAT_RATE

    def currency(self):
        """Read currency symbol from saved profile, fallback to UGX."""
        try:
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    p = json.load(f)
                return p.get("currency", "UGX")
        except Exception:
            pass
        return "UGX"


if __name__ == "__main__":
    CalcoraApp().run()
