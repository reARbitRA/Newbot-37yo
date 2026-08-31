#!/usr/bin/env python3
"""NovaCore — لایه‌ی سرویس platform-agnostic.

همه‌ی منطق محصول (چت، سهمیه، پرداخت) اینجاست — بدون هیچ وابستگی به تلگرام.
آداپتورها (bot.py تلگرام، api_server.py برای Mini App / وب / موبایل)
فقط transport هستند و به این کلاس delegate می‌کنند.

    from core import NovaCore
    core = NovaCore()
    core.chat("telegram", 12345, "username", "سلام")
"""
import time, sqlite3
import config, db

class NovaCore:
    def __init__(self, system_prompt: str | None = None):
        db.init()
        if system_prompt:
            config.AI_SYSTEM_PROMPT = system_prompt
        self._ensure_accounts()
        from router import get_router
        self.router = get_router(config.AI_SYSTEM_PROMPT)

    # ── multi-platform account mapping ──
    def _ensure_accounts(self):
        c = db.conn()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS core_accounts(
            platform TEXT NOT NULL,
            ext_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(platform, ext_id)
        );""")
        c.commit()

    def _uid(self, platform: str, ext_id, username: str = "") -> int:
        ext = str(ext_id)
        c = db.conn()
        r = c.execute("SELECT user_id FROM core_accounts WHERE platform=? AND ext_id=?",
                      (platform, ext)).fetchone()
        if r:
            if username:
                db.upsert_user(r["user_id"], username)
            return r["user_id"]
        # آیدی پلتفرم‌محور: telegram→همون عدد، بقیه→autoincrement از کاربران جدید
        if platform == "telegram":
            uid = int(ext)
        else:
            uid = int(time.time() * 1000) % (1 << 31)
            while db.get_user(uid):
                uid += 1
        db.upsert_user(uid, username)
        c.execute("INSERT OR REPLACE INTO core_accounts(platform, ext_id, user_id) VALUES(?,?,?)",
                  (platform, ext, uid))
        c.commit()
        return uid

    # ── API اصلی ──
    def chat(self, platform: str, ext_id, username: str, text: str) -> dict:
        uid = self._uid(platform, ext_id, username)
        ok, note = db.check_and_consume(uid)
        if not ok:
            return {"ok": False, "reply": None, "note": note, "user_id": uid}
        db.add_message(uid, "user", text)
        answer = self.router.chat(db.get_history(uid))
        db.add_message(uid, "assistant", answer)
        return {"ok": True, "reply": answer, "note": note, "user_id": uid}

    def status(self, platform: str, ext_id) -> dict:
        uid = self._uid(platform, ext_id)
        u = db._rollover_daily(db.get_user(uid))
        plan = db.effective_plan(u)
        days = max(0, int((u["plan_expires"] - time.time()) // 86400)) + 1
        return {"user_id": uid, "plan": plan,
                "balance_messages": u["balance_messages"],
                "daily_used": u["daily_used"],
                "subscription_days_left": days if plan == "monthly" else 0}

    def checkout(self, platform: str, ext_id, plan_key: str) -> dict:
        uid = self._uid(platform, ext_id)
        if plan_key == "monthly":
            base, kind, credit = config.MONTHLY_PRICE_CENTS, "monthly", 0
        elif plan_key.startswith("pack"):
            cents = int(plan_key[4:])
            if cents not in config.PAYG_PACKS:
                raise ValueError("pack ناشناخته")
            base, kind, credit = cents, "pack", config.PAYG_PACKS[cents]
        else:
            raise ValueError("plan_key نامعتبر (monthly | pack100|300|500)")
        p = db.create_payment(uid, kind, base, credit)
        return {"payment_id": p["id"], "amount_usdt": p["expected_cents"] / 100.0,
                "network": "TRC20", "address": config.DEPOSIT_ADDRESS,
                "expires_in": config.PAYMENT_WINDOW}

    def poll_payments(self) -> int:
        return len(__import__("tron_watcher").poll_once())

    def stats(self) -> dict:
        return db.stats()
