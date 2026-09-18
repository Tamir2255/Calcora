"""
Calcora Supabase Sync Module
Pure REST API — only needs 'requests' library.
pip install requests
"""
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

# ── Config ────────────────────────────────────────────────────────────────────

SUPABASE_URL = "https://hcnjxdidapkkyrbxxtdy.supabase.co"
ANON_KEY     = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imhjbmp4ZGlkYXBra3lyYnh4dGR5Iiw"
    "icm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0MjE1OTgsImV4cCI6MjA5NDk5NzU5OH0."
    "WYHNUWW8KxCwHgw0XvPey-AtnfokR8nPD2ttjjeku9w"
)
REST_URL = f"{SUPABASE_URL}/rest/v1"
AUTH_URL = f"{SUPABASE_URL}/auth/v1"

# ── State ─────────────────────────────────────────────────────────────────────

_access_token   = None
_refresh_token  = None
_user_id        = None
_is_online      = False
_role           = None
_poll_callbacks = []
_poll_running   = False
_last_error     = ""
TIMEOUT         = 10
MAX_RETRIES     = 2

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

def _headers():
    """Always use the token if available, otherwise anon key."""
    token = _access_token if _access_token else ANON_KEY
    return {
        "apikey":        ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }

def _set_error(text):
    global _last_error
    _last_error = text or ""

def last_error():
    return _last_error

def _parse_auth(data):
    """Extract token and user from Supabase auth response (handles both formats)."""
    global _access_token, _refresh_token, _user_id, _is_online
    # Format 1: {access_token, user: {id}}
    if "access_token" in data:
        _access_token  = data["access_token"]
        _refresh_token = data.get("refresh_token", "")
        user = data.get("user") or data.get("User") or {}
        _user_id  = user.get("id") or data.get("user_id","")
        _is_online = True
        return True
    # Format 2: session nested
    if "session" in data and data["session"]:
        s = data["session"]
        _access_token  = s.get("access_token","")
        _refresh_token = s.get("refresh_token","")
        user = data.get("user") or s.get("user") or {}
        _user_id  = user.get("id","")
        _is_online = bool(_access_token)
        return bool(_access_token)
    return False

def _get(table, params=None, retries=MAX_RETRIES):
    if not REQUESTS_OK:
        _set_error("Install requests: pip install requests")
        return None
    try:
        r = requests.get(
            f"{REST_URL}/{table}",
            headers=_headers(),
            params=params,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            _set_error("")
            return r.json()
        if r.status_code in (408, 429, 500, 502, 503, 504) and retries > 1:
            time.sleep(0.5)
            return _get(table, params=params, retries=retries-1)
        _set_error(f"GET {table} failed: {r.status_code} {r.text[:160]}")
        print(f"[Supabase GET {table}] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        if retries > 1:
            time.sleep(0.5)
            return _get(table, params=params, retries=retries-1)
        _set_error(f"GET {table} error: {e}")
        print(f"[Supabase GET error] {e}")
    return None

def _post(table, data, retries=MAX_RETRIES):
    if not REQUESTS_OK:
        _set_error("Install requests: pip install requests")
        return None
    try:
        r = requests.post(
            f"{REST_URL}/{table}",
            headers=_headers(),
            json=data,
            timeout=TIMEOUT,
        )
        if r.status_code in (200, 201):
            _set_error("")
            return r.json()
        if r.status_code in (408, 429, 500, 502, 503, 504) and retries > 1:
            time.sleep(0.5)
            return _post(table, data, retries=retries-1)
        _set_error(f"POST {table} failed: {r.status_code} {r.text[:160]}")
        print(f"[Supabase POST {table}] {r.status_code}: {r.text[:200]}")
    except Exception as e:
        if retries > 1:
            time.sleep(0.5)
            return _post(table, data, retries=retries-1)
        _set_error(f"POST {table} error: {e}")
        print(f"[Supabase POST error] {e}")
    return None

def _patch(table, params, data, retries=MAX_RETRIES):
    if not REQUESTS_OK:
        _set_error("Install requests: pip install requests")
        return False
    try:
        r = requests.patch(
            f"{REST_URL}/{table}",
            headers=_headers(),
            params=params,
            json=data,
            timeout=TIMEOUT,
        )
        ok = r.status_code in (200, 204)
        if not ok and r.status_code in (408, 429, 500, 502, 503, 504) and retries > 1:
            time.sleep(0.5)
            return _patch(table, params, data, retries=retries-1)
        _set_error("" if ok else f"PATCH {table} failed: {r.status_code} {r.text[:160]}")
        return ok
    except Exception as e:
        if retries > 1:
            time.sleep(0.5)
            return _patch(table, params, data, retries=retries-1)
        _set_error(f"PATCH {table} error: {e}")
        return False

def _delete(table, params, retries=MAX_RETRIES):
    if not REQUESTS_OK:
        _set_error("Install requests: pip install requests")
        return False
    try:
        r = requests.delete(
            f"{REST_URL}/{table}",
            headers=_headers(),
            params=params,
            timeout=TIMEOUT,
        )
        ok = r.status_code in (200, 204)
        if not ok and r.status_code in (408, 429, 500, 502, 503, 504) and retries > 1:
            time.sleep(0.5)
            return _delete(table, params, retries=retries-1)
        _set_error("" if ok else f"DELETE {table} failed: {r.status_code} {r.text[:160]}")
        return ok
    except Exception as e:
        if retries > 1:
            time.sleep(0.5)
            return _delete(table, params, retries=retries-1)
        _set_error(f"DELETE {table} error: {e}")
        return False

# ── Public helpers ────────────────────────────────────────────────────────────

def is_online():
    return _is_online and bool(_access_token)

def current_uid():
    return _user_id

def current_role():
    return _role

def sign_out():
    global _access_token, _refresh_token, _user_id, _is_online, _role
    _access_token = _refresh_token = _user_id = _role = None
    _is_online = False

# ── Auth ──────────────────────────────────────────────────────────────────────

def sign_up_owner(email, password, business_name):
    if not REQUESTS_OK:
        return False, "Install requests: pip install requests"
    try:
        r = requests.post(
            f"{AUTH_URL}/signup",
            headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        data = r.json()
        print(f"[signup] status={r.status_code} keys={list(data.keys())}")
        if r.status_code not in (200, 201):
            msg = (data.get("error_description")
                   or data.get("msg")
                   or data.get("message", "Sign up failed"))
            return False, msg

        global _access_token, _refresh_token, _user_id, _is_online, _role

        # Case 1: Full session returned (email confirmation disabled)
        if "access_token" in data:
            _parse_auth(data)
            _role = "owner"
            return True, "Account created"

        # Case 2: Only user returned (email confirmation enabled)
        # Auto sign in immediately after signup
        if "id" in data or ("user" in data and data["user"]):
            user_id = data.get("id") or (data.get("user") or {}).get("id","")
            if user_id:
                _user_id = user_id
            # Now sign in to get the token
            r2 = requests.post(
                f"{AUTH_URL}/token?grant_type=password",
                headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
                json={"email": email, "password": password},
                timeout=TIMEOUT,
            )
            if r2.status_code == 200:
                _parse_auth(r2.json())
                _role = "owner"
                print(f"[signup→signin] uid={_user_id} online={_is_online}")
                return True, "Account created"
            else:
                # Account created but can't sign in yet
                # (email confirmation may be required)
                _is_online = False
                return True, "Account created — check email to confirm, then log in"

        return False, "Unexpected response from server"
    except Exception as e:
        return False, f"Network error: {e}"


def sign_in_owner(email, password):
    if not REQUESTS_OK:
        return False, "Install requests: pip install requests"
    try:
        r = requests.post(
            f"{AUTH_URL}/token?grant_type=password",
            headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        data = r.json()
        print(f"[signin] status={r.status_code} keys={list(data.keys())}")
        if r.status_code != 200:
            msg = (data.get("error_description")
                   or data.get("msg")
                   or data.get("message","Login failed"))
            return False, msg
        if not _parse_auth(data):
            return False, "Could not parse auth response"
        global _role
        _role = "owner"
        print(f"[signin] uid={_user_id} online={_is_online}")
        return True, "Logged in"
    except Exception as e:
        return False, f"Network error: {e}"


def refresh_session():
    global _is_online
    if not _refresh_token:
        return False
    try:
        r = requests.post(
            f"{AUTH_URL}/token?grant_type=refresh_token",
            headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
            json={"refresh_token": _refresh_token},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return _parse_auth(r.json())
    except Exception:
        pass
    _is_online = False
    return False

# ── Stores ────────────────────────────────────────────────────────────────────

def create_store(store_name, biz_type):
    store_code = str(uuid.uuid4())[:6].upper()
    data = {
        "owner_id":   _user_id,
        "name":       store_name,
        "biz_type":   biz_type,
        "store_code": store_code,
    }
    result = _post("stores", data)
    if result:
        store = result[0] if isinstance(result, list) else result
        return True, store.get("id"), store_code
    return False, None, None

def get_stores():
    if not _user_id:
        _set_error("Not signed in yet.")
        return []
    result = _get("stores", {"owner_id": f"eq.{_user_id}", "order": "created_at.asc"})
    return result or []

def delete_store(store_id):
    """Delete a store and all its workers from Supabase."""
    # Delete workers first
    _delete("workers", {"store_id": f"eq.{store_id}"})
    # Delete sales
    _delete("sales", {"store_id": f"eq.{store_id}"})
    # Delete notifications
    _delete("notifications", {"store_id": f"eq.{store_id}"})
    # Delete store
    return _delete("stores", {"id": f"eq.{store_id}"})

def get_store_by_code(store_code):
    result = _get("stores", {"store_code": f"eq.{store_code.upper()}"})
    if result:
        return result[0]
    return None

# ── Workers ───────────────────────────────────────────────────────────────────

def add_worker(store_id, worker_name, worker_pin):
    data = {
        "store_id": store_id,
        "name":     worker_name,
        "pin_hash": _hash(worker_pin),
    }
    result = _post("workers", data)
    if result:
        w = result[0] if isinstance(result, list) else result
        return True, w.get("id")
    return False, None

def get_workers(store_id):
    result = _get("workers", {"store_id": f"eq.{store_id}", "order": "created_at.asc"})
    return result or []

def remove_worker(worker_id):
    return _delete("workers", {"id": f"eq.{worker_id}"})

def worker_login(store_code, worker_pin):
    """Worker logs in with store code + PIN — no Supabase Auth needed."""
    try:
        store = get_store_by_code(store_code)
        if not store:
            return False, "Store code not found.", None, None

        store_id = store["id"]
        r = requests.get(
            f"{REST_URL}/workers",
            headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
            params={"store_id": f"eq.{store_id}"},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return False, "Could not fetch workers.", None, None

        workers = r.json()
        if not workers:
            return False, "No workers registered for this store.", None, None

        pin_hash = _hash(worker_pin)
        for w in workers:
            if w.get("pin_hash") == pin_hash:
                global _user_id, _role, _is_online, _access_token
                _user_id      = store.get("owner_id", "")
                _role         = "worker"
                _is_online    = True
                # Use anon key for worker (no auth token)
                _access_token = ANON_KEY
                return True, "Logged in", store, w

        return False, "Wrong PIN. Try again.", None, None
    except Exception as e:
        return False, f"Error: {e}", None, None

# ── Sales ─────────────────────────────────────────────────────────────────────

def push_sales_sheet(store_id, rows, subtotal, worker_name, worker_id):
    sale_data = {
        "store_id":      store_id,
        "worker_name":   worker_name,
        "worker_id":     str(worker_id) if worker_id else None,
        "rows":          json.dumps(rows),
        "subtotal":      float(subtotal),
        "submitted_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_read":       False,
    }
    result = _post("sales", sale_data)
    if not result:
        return False

    # Get store name for notification
    store_result = _get("stores", {"id": f"eq.{store_id}"})
    store_name   = store_result[0].get("name","") if store_result else ""
    owner_id     = store_result[0].get("owner_id","") if store_result else _user_id
    item_names   = [str(r.get("item","?")).strip() for r in rows if r.get("item")]
    if len(item_names) > 3:
        item_list = ", ".join(item_names[:3]) + f" +{len(item_names)-3} more"
    else:
        item_list = ", ".join(item_names)

    notif_data = {
        "owner_id":    owner_id,
        "store_id":    store_id,
        "message":     (f"{worker_name} submitted sales ({item_list}) for {store_name}"
                         if item_list else
                         f"{worker_name} submitted sales for {store_name}"),
        "worker_name": worker_name,
        "subtotal":    float(subtotal),
        "is_read":     False,
    }
    _post("notifications", notif_data)
    return True


def push_notification(store_id, message, worker_name=None, subtotal=0, owner_id=None):
    if not owner_id and store_id:
        store_result = _get("stores", {"id": f"eq.{store_id}"})
        owner_id = store_result[0].get("owner_id","") if store_result else _user_id

    if not owner_id:
        owner_id = _user_id

    notif_data = {
        "owner_id":    owner_id,
        "store_id":    store_id,
        "message":     message,
        "worker_name": worker_name or "",
        "subtotal":    float(subtotal or 0),
        "is_read":     False,
    }
    return _post("notifications", notif_data)

def get_sales(store_id, limit=50):
    result = _get("sales", {
        "store_id": f"eq.{store_id}",
        "order":    "submitted_at.desc",
        "limit":    str(limit),
    })
    if result:
        for row in result:
            if isinstance(row.get("rows"), str):
                try:
                    row["rows"] = json.loads(row["rows"])
                except Exception:
                    pass
    return result or []

# ── Notifications ─────────────────────────────────────────────────────────────

def get_notifications(limit=30):
    if not _user_id:
        _set_error("Not signed in yet.")
        return []
    result = _get("notifications", {
        "owner_id": f"eq.{_user_id}",
        "order":    "created_at.desc",
        "limit":    str(limit),
    })
    return result or []

def get_unread_count():
    result = _get("notifications", {
        "owner_id": f"eq.{_user_id}",
        "is_read":  "eq.false",
    })
    return len(result) if result else 0

def mark_notification_read(notif_id):
    return _patch("notifications", {"id": f"eq.{notif_id}"}, {"is_read": True})

def mark_all_read():
    return _patch("notifications",
                  {"owner_id": f"eq.{_user_id}", "is_read": "eq.false"},
                  {"is_read": True})


def delete_notification(notif_id):
    """Delete a single notification by id."""
    return _delete("notifications", {"id": f"eq.{notif_id}"})


def delete_read_notifications():
    """Delete all read notifications for the current owner."""
    if not _user_id:
        _set_error("Not signed in yet.")
        return False
    return _delete("notifications", {"owner_id": f"eq.{_user_id}", "is_read": "eq.true"})

# ── Polling ───────────────────────────────────────────────────────────────────

def on_notification(callback):
    if callback not in _poll_callbacks:
        _poll_callbacks.append(callback)

def start_polling(interval=30):
    global _poll_running
    if _poll_running:
        return
    _poll_running = True
    def _loop():
        while _poll_running:
            if is_online() and _role == "owner":
                try:
                    count = get_unread_count()
                    for cb in _poll_callbacks:
                        cb(count)
                except Exception:
                    pass
            time.sleep(interval)
    threading.Thread(target=_loop, daemon=True).start()

def stop_polling():
    global _poll_running
    _poll_running = False
