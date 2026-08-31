#!/usr/bin/env python3
"""دیده‌بان پرداخت TRC20 — تراکنش‌های ورودی USDT رو با TronGrid چک می‌کنه.

روش: آخرین تراکنش‌های قرارداد USDT رو می‌گیریم و ورودی‌های به آدرس ما رو
با پرداخت‌های pending (مبلغ یکتا) تطبیق می‌دیم. بدون کلید هم کار می‌کنه.
"""
import json, time, threading, urllib.request, urllib.error
import config, db

def _get(url: str) -> dict:
    headers = {"accept": "application/json"}
    if config.TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def _fetch_incoming(limit: int = 50) -> list[dict]:
    """آخرین transfer های TRC20 ورودی به آدرس ما — از اندپوینت پارس‌شده‌ی TronGrid."""
    url = (f"{config.TRONGRID_URL}/v1/accounts/{config.DEPOSIT_ADDRESS}"
           f"/transactions/trc20?limit={limit}&only_confirmed=true"
           f"&contract_address={config.USDT_CONTRACT}")
    try:
        data = _get(url)
    except Exception:
        return []
    out = []
    for t in data.get("data", []):
        try:
            if t.get("type") != "Transfer" or t.get("to") != config.DEPOSIT_ADDRESS:
                continue
            if t.get("token_information", {}).get("address") != config.USDT_CONTRACT:
                continue
            raw = int(t["value"])               # ۶ اعشار USDT
            out.append({
                "txid": t["transaction_id"],
                "to": t["to"],
                "cents": raw // 10_000,         # raw(6dp) → سنت(2dp)
                "ts": t.get("block_timestamp", 0) / 1000.0,
            })
        except (KeyError, ValueError):
            continue
    return out

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def _b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    s = ""
    while n > 0:
        n, r = divmod(n, 58)
        s = _BASE58_ALPHABET[r] + s
    # بایت‌های صفر ابتدایی → '1'
    for b in raw:
        if b == 0:
            s = "1" + s
        else:
            break
    return s

def _hex_to_base58check(hex_addr: str) -> str:
    raw = bytes.fromhex(hex_addr)
    # sha256 دوبار (استاندارد TRON) — از hashlib
    import hashlib
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return _b58encode(raw + checksum)

def poll_once() -> list[dict]:
    """یک دور چک؛ پرداخت‌های تطبیق‌خورده رو برمی‌گردونه."""
    db.expire_stale()
    matched = []
    if config.DEPOSIT_ADDRESS.startswith("YOUR_"):
        return matched  # هنوز تنظیم نشده
    for t in _fetch_incoming():
        if t["to"] != config.DEPOSIT_ADDRESS:
            continue
        p = db.match_payment(t["cents"], t["txid"])
        if p:
            db.apply_payment(p["user_id"], p["kind"], p["credit_messages"] or 0)
            matched.append(p)
    return matched

def start_loop(notify_cb=None):
    """حلقه‌ی پس‌زمینه. notify_cb(payment_dict) بعد از هر شارژ موفق صدا زده می‌شه."""
    def _loop():
        seen_txids = set()
        while True:
            try:
                for p in poll_once():
                    if p.get("txid") and p["txid"] not in seen_txids:
                        seen_txids.add(p["txid"])
                        if notify_cb:
                            try:
                                notify_cb(p)
                            except Exception:
                                pass
            except Exception:
                pass  # شبکه قطع؟ دور بعدی
            time.sleep(config.POLL_INTERVAL)
    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    return th
