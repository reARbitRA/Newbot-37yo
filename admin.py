#!/usr/bin/env python3
"""دستورات ادمین — فقط برای ADMIN_IDS."""
import time
import config, db, policy

def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS

def handle_admin(text: str, reply) -> bool:
    """خروجی True یعنی پیام مصرف شد. reply(text, markdown=False) برای جواب."""
    parts = text.split()
    cmd = parts[1] if len(parts) > 1 else ""

    if cmd == "" or cmd == "stats":
        s = db.stats()
        reply(
            "📊 <b>آمار NovaMind</b>\n"
            f"• کاربران: {s['users']}\n"
            f"• فعال ۲۴س: {s['active_24h']}\n"
            f"• اشتراک فعال: {s['monthly_subs']}\n"
            f"• درآمد کل: {s['revenue_usdt']:.2f} USDT",
            markdown=True,
        )
        return True

    if cmd == "user" and len(parts) >= 3:
        try:
            uid = int(parts[2])
        except ValueError:
            reply("آیدی عددی بده."); return True
        u = db.get_user(uid)
        if not u:
            reply("کاربر پیدا نشد."); return True
        u = db._rollover_daily(u)
        plan = db.effective_plan(u)
        bal = u["balance_messages"]
        exp = time.strftime("%Y-%m-%d", time.localtime(u["plan_expires"])) if plan == "monthly" else "-"
        reply(
            f"👤 <code>{uid}</code>  @{u.get('username') or '-'}\n"
            f"پلن: <b>{plan}</b>\n"
            f"اعتبار اعشاری: {bal} پیام | اشتراک تا: {exp}\n"
            f"امروز: {u['daily_used']} پیام",
            markdown=True,
        )
        return True

    if cmd == "grant" and len(parts) >= 4:
        try:
            uid, usdt = int(parts[2]), float(parts[3])
        except ValueError:
            reply("فرمت: /admin grant <id> <usdt>"); return True
        db.upsert_user(uid, "manual")
        msgs = int(usdt * 100 / config.PER_MESSAGE_COST_CENTS)
        db.apply_payment(uid, "pack", msgs)
        reply(f"✅ {uid} شارژ شد با ~{msgs} پیام ({usdt} USDT).")
        return True

    if cmd == "policy":
        snap = policy.snapshot()
        provs = "\n".join(
            f"{'✅' if c['enabled'] else '⛔'} {pid}: {c['billing']}, cap={c['daily_cap']}"
            for pid, c in snap["providers"].items())
        reply(
            "🎛 <b>پنل کنترل مالک</b>\n\n"
            f"استراتژی‌ها: <code>{snap['strategies']}</code>\n"
            f"پولی مجاز: <b>{'بله' if snap['allow_paid'] else 'خیر'}</b> | fusion_n={snap['fusion_n']}\n\n"
            f"<b>پروایدرها:</b>\n{provs}\n\n"
            "دستورها: /admin provider &lt;نام&gt; on|off|free|paid|cap=N\n"
            "/admin strategy &lt;simple|medium|complex&gt; &lt;direct|cascade|fusion&gt;\n"
            "/admin paid on|off · /admin fusionn 2-5 · /admin policyreset",
            markdown=True,
        )
        return True

    if cmd == "provider" and len(parts) >= 4:
        pid = parts[2].lower()
        kw = {}
        for arg in parts[3:]:
            if arg in ("on", "off"): kw["enabled"] = arg == "on"
            elif arg in ("free", "paid"): kw["billing"] = arg
            elif arg.startswith("cap="): kw["daily_cap"] = arg[4:]
        try:
            policy.set_provider(pid, **kw)
            reply(f"🎛 {pid} آپدیت شد: {kw}")
        except ValueError as e:
            reply(f"⚠️ {e}")
        return True

    if cmd == "strategy" and len(parts) >= 4:
        try:
            policy.set_strategy(parts[2], parts[3])
            reply(f"🎛 سطح {parts[2]} → استراتژی {parts[3]} (بدون ری‌استارت)")
        except ValueError as e:
            reply(f"⚠️ {e}")
        return True

    if cmd == "paid" and len(parts) >= 3:
        policy.set_allow_paid(parts[2] == "on")
        reply(f"🎛 مدل‌های پولی: {'فعال ✅' if parts[2]=='on' else 'غیرفعال ⛔'}")
        return True

    if cmd == "fusionn" and len(parts) >= 3:
        try:
            policy.set_fusion_n(parts[2])
            reply(f"🎛 تعداد مدل‌های fusion = {parts[2]}")
        except ValueError as e:
            reply(f"⚠️ {e}")
        return True

    if cmd == "policyreset":
        policy.reset()
        reply("🎛 پالیسی به پیش‌فرض برگشت.")
        return True

    if cmd == "pending":
        rows = db.pending_list()
        if not rows:
            reply("پرداخت pending ای نیست."); return True
        lines = [
            f"• #{r['id']} | {r['expected_cents']/100:.2f} USDT | {r['kind']} | "
            f"user {r['user_id']} | {int(r['expires_at']-time.time())}s"
            for r in rows
        ]
        reply("⏳ <b>در انتظار:</b>\n" + "\n".join(lines), markdown=True)
        return True

    reply(
        "🛠 <b>دستورات:</b>\n"
        "/admin policy — پنل کنترل مدل‌ها\n"
        "/admin stats — آمار\n"
        "/admin user &lt;id&gt;\n"
        "/admin grant &lt;id&gt; &lt;usdt&gt;\n"
        "/admin pending",
        markdown=True,
    )
    return True
