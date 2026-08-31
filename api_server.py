#!/usr/bin/env python3
"""NovaMind REST API — در برای Telegram Mini App / وب / موبایل.

استاندارد و بدون وابستگی (فقط stdlib). اجرا:
    python3 api_server.py            → http://0.0.0.0:8080

End-points:
    GET  /health                     → سلامت سرویس
    POST /api/chat                   → {"platform","ext_id","text"} → جواب AI
    GET  /api/status?platform=&ext_id=
    POST /api/checkout               → {"plan":"monthly"|"pack100"|...}
    POST /api/payments/poll          → بررسی دستی پرداخت‌ها
    POST /api/miniapp/auth           → اعتبارسنجی initData تلگرام (HMAC)
    GET  /                           → Mini App placeholder

امنیت: env NOVA_API_TOKEN ست کنی، همه‌ی /api/* به Bearer نیاز پیدا می‌کنند.
CORS: * روی /api/* (برای Mini App لازم است).
"""
import os, json, hmac, hashlib, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import config

API_TOKEN = os.getenv("NOVA_API_TOKEN", "")
PORT = int(os.getenv("NOVA_PORT", "8080"))

core = None  # lazy

def get_core():
    global core
    if core is None:
        from core import NovaCore
        core = NovaCore()
    return core

def verify_init_data(init_data: str, bot_token: str) -> tuple[bool, str]:
    """اعتبارسنجی رسمی Telegram Mini App initData (HMAC-SHA256)."""
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        return False, ""
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, received_hash), pairs.get("user", "")

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        if not API_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_OPTIONS(self):
        self._json(204, {})

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "service": "novamind-api"})
        if self.path.startswith("/api/status"):
            if not self._authed():
                return self._json(401, {"error": "unauthorized"})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                s = get_core().status(q["platform"][0], q["ext_id"][0])
                return self._json(200, s)
            except KeyError:
                return self._json(400, {"error": "platform & ext_id required"})
        if self.path == "/":
            html = ("<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>NovaMind Mini App</title></head><body style='font-family:system-ui;"
                    "background:#0b0f19;color:#dfe7f3;display:grid;place-items:center;height:100vh'>"
                    "<div style='text-align:center'><h1>🤖 NovaMind</h1>"
                    "<p>Mini App shell — API ready at <code>/api/chat</code></p></div></body></html>")
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        try:
            data = self._body()
            c = get_core()
            if self.path == "/api/chat":
                r = c.chat(data.get("platform", "web"), data.get("ext_id"),
                           data.get("username", ""), data.get("text", ""))
                return self._json(200, r)
            if self.path == "/api/checkout":
                return self._json(200, c.checkout(
                    data.get("platform", "web"), data.get("ext_id"),
                    data.get("plan", "monthly")))
            if self.path == "/api/payments/poll":
                return self._json(200, {"matched": c.poll_payments()})
            if self.path == "/api/miniapp/auth":
                ok, user = verify_init_data(data.get("init_data", ""), config.BOT_TOKEN)
                return self._json(200, {"valid": ok})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        self._json(404, {"error": "not found"})

    def log_message(self, *a):
        pass  # لاگ خام NGINX-style لازم نیست

if __name__ == "__main__":
    print(f"🚀 NovaMind API → http://0.0.0.0:{PORT}  (token-auth: {'ON' if API_TOKEN else 'OFF'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
