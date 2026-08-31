#!/usr/bin/env python3
"""دیتابیس SQLite — کاربران، پرداخت‌ها، پیام‌ها."""
import sqlite3, time, threading, os
import config

_local = threading.local()

def conn() -> sqlite3.Connection:
    if not hasattr(_local, "c") or _local.c is None:
        _local.c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _local.c.row_factory = sqlite3.Row
        _local.c.execute("PRAGMA journal_mode=WAL")
    return _local.c

def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        joined_at REAL,
        plan TEXT DEFAULT 'free',              -- free | monthly | credit
        plan_expires REAL DEFAULT 0,
        balance_messages INTEGER DEFAULT 0,    -- برای pay-as-you-go
        daily_used INTEGER DEFAULT 0,
        daily_date TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        expected_cents INTEGER,                -- مبلغ دقیق منتظر (سنت)
        kind TEXT,                             -- monthly | pack
        credit_messages INTEGER,
        status TEXT DEFAULT 'pending',         -- pending | paid | expired
        created_at REAL,
        expires_at REAL,
        txid TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        content TEXT,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status, expected_cents);
    CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id, id);
    """)
    c.commit()

# ─────────────── کاربران ───────────────

def today() -> str:
    return time.strftime("%Y-%m-%d")

def upsert_user(uid: int, username: str):
    c = conn()
    r = c.execute("SELECT user_id, username FROM users WHERE user_id=?", (uid,)).fetchone()
    if r is None:
        c.execute("INSERT INTO users(user_id, username, joined_at, daily_date) VALUES(?,?,?,?)",
                  (uid, username, time.time(), today()))
        c.commit()
    elif username and username != r["username"]:
        c.execute("UPDATE users SET username=? WHERE user_id=?", (username, uid))
        c.commit()

def get_user(uid: int):
    r = conn().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    return dict(r) if r else None

def _rollover_daily(u: dict) -> dict:
    """ریست سهمیه روزانه اگر تاریخ عوض شده."""
    if u["daily_date"] != today():
        conn().execute("UPDATE users SET daily_used=0, daily_date=? WHERE user_id=?",
                       (today(), u["user_id"]))
        conn().commit()
        u["daily_used"] = 0
        u["daily_date"] = today()
    return u

def effective_plan(u: dict) -> str:
    """پلن فعال (اشتراک منقضی‌شده → free)."""
    if u["plan"] == "monthly" and u["plan_expires"] < time.time():
        conn().execute("UPDATE users SET plan='free' WHERE user_id=?", (u["user_id"],))
        conn().commit()
        return "free"
    return u["plan"]

def check_and_consume(uid: int) -> tuple[bool, str]:
    """یک پیام کم کن. خروجی: (مجاز؟, پیام وضعیت)"""
    u = get_user(uid)
    if u is None:
        return False, "اول /start بزن."
    u = _rollover_daily(u)
    plan = effective_plan(u)

    if plan == "monthly":
        limit = config.MONTHLY_DAILY_MESSAGES
        if u["daily_used"] >= limit:
            return False, f"سهمیه امروز ({limit} پیام) تموم شد. فردا ادامه بده 💤"
        conn().execute("UPDATE users SET daily_used=daily_used+1 WHERE user_id=?", (uid,))
        conn().commit()
        return True, f"💎 {limit - u['daily_used'] - 1} پیام امروز باقی مانده"

    if plan == "credit" and u["balance_messages"] > 0:
        conn().execute("UPDATE users SET balance_messages=balance_messages-1 WHERE user_id=?", (uid,))
        conn().commit()
        return True, f"⚡ {u['balance_messages'] - 1} پیام اعتباری باقی مانده"

    # free
    if u["daily_used"] >= config.FREE_DAILY_MESSAGES:
        return False, ("سهمیه رایگان امروز ({n} پیام) تموم شد 🆓\n"
                       "برای ادامه /buy بزن و اشتراک بگیر یا شارژ کن.").format(n=config.FREE_DAILY_MESSAGES)
    conn().execute("UPDATE users SET daily_used=daily_used+1 WHERE user_id=?", (uid,))
    conn().commit()
    return True, f"🆓 {config.FREE_DAILY_MESSAGES - u['daily_used'] - 1} پیام رایگان امروز"

def apply_payment(uid: int, kind: str, credit_messages: int):
    c = conn()
    if kind == "monthly":
        now = time.time()
        u = get_user(uid)
        base = u["plan_expires"] if u["plan"] == "monthly" and u["plan_expires"] > now else now
        c.execute("""UPDATE users SET plan='monthly', plan_expires=?,
                     balance_messages=0, daily_used=0 WHERE user_id=?""",
                  (base + config.MONTHLY_DAYS * 86400, uid))
    else:
        c.execute("""UPDATE users SET plan='credit',
                     balance_messages=balance_messages+? WHERE user_id=?""",
                  (credit_messages, uid))
    c.commit()

# ─────────────── پرداخت‌ها ───────────────

def create_payment(uid: int, kind: str, base_cents: int, credit_messages: int) -> dict:
    """مبلغ یکتا با سنت رندوم بساز (مثلاً 4.00 → 4.37)."""
    import random
    c = conn()
    for _ in range(50):
        cents = base_cents + random.randint(5, 99)
        dup = c.execute("""SELECT id FROM payments WHERE status='pending'
                           AND expected_cents=?""", (cents,)).fetchone()
        if dup is None:
            now = time.time()
            cur = c.execute("""INSERT INTO payments(user_id, expected_cents, kind,
                    credit_messages, status, created_at, expires_at)
                    VALUES(?,?,?,?, 'pending', ?, ?)""",
                    (uid, cents, kind, credit_messages, now, now + config.PAYMENT_WINDOW))
            c.commit()
            return {"id": cur.lastrowid, "expected_cents": cents}
    raise RuntimeError("نمی‌تونم مبلغ یکتا بسازم")

def match_payment(cents: int, txid: str) -> dict | None:
    """تراکنش ورودی رو به پرداخت pending تطبیق بده."""
    c = conn()
    r = c.execute("""SELECT * FROM payments WHERE status='pending'
                     AND expected_cents=? AND expires_at > ?""",
                  (cents, time.time())).fetchone()
    if r is None:
        return None
    c.execute("UPDATE payments SET status='paid', txid=? WHERE id=?", (txid, r["id"]))
    c.commit()
    d = dict(r); d["status"] = "paid"
    return d

def expire_stale():
    c = conn()
    c.execute("""UPDATE payments SET status='expired'
                 WHERE status='pending' AND expires_at < ?""", (time.time(),))
    c.commit()

def pending_list() -> list[dict]:
    rows = conn().execute("""SELECT * FROM payments WHERE status='pending'
                             ORDER BY created_at DESC LIMIT 20""").fetchall()
    return [dict(r) for r in rows]

# ─────────────── تاریخچه چت ───────────────

def add_message(uid: int, role: str, content: str):
    c = conn()
    c.execute("INSERT INTO messages(user_id, role, content, created_at) VALUES(?,?,?,?)",
              (uid, role, content[:8000], time.time()))
    c.commit()
    # فقط N پیام اخیر نگه‌دار
    keep = config.HISTORY_TURNS * 2 + 4
    c.execute("""DELETE FROM messages WHERE user_id=? AND id NOT IN
                 (SELECT id FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?)""",
              (uid, uid, keep))
    c.commit()

def get_history(uid: int) -> list[dict]:
    rows = conn().execute("""SELECT role, content FROM messages WHERE user_id=?
                             ORDER BY id ASC""", (uid,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows][-config.HISTORY_TURNS * 2:]

# ─────────────── آمار ───────────────

def stats() -> dict:
    c = conn()
    total = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    today_active = c.execute(
        "SELECT COUNT(DISTINCT user_id) n FROM messages WHERE created_at > ?",
        (time.time() - 86400,)).fetchone()["n"]
    monthly = c.execute(
        "SELECT COUNT(*) n FROM users WHERE plan='monthly' AND plan_expires > ?",
        (time.time(),)).fetchone()["n"]
    revenue = c.execute(
        "SELECT COALESCE(SUM(expected_cents),0) s FROM payments WHERE status='paid'").fetchone()["s"]
    return {"users": total, "active_24h": today_active, "monthly_subs": monthly,
            "revenue_usdt": revenue / 100.0}
