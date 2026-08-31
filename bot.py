#!/usr/bin/env python3
"""NovaMind — بات تلگرامی AI با پرداخت USDT-TRC20.

اجرا:  python3 bot.py
نیاز:  python-telegram-bot (v21+)  →  pip install python-telegram-bot
"""
import logging, threading, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

import config, db, ai, admin
import tron_watcher

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("nova")

# ─────────────── کمکی‌ها ───────────────

def fmt_usdt(cents: int) -> str:
    return f"{cents/100:.2f}"

def keyboard_main():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💎 اشتراک ماهانه", callback_data="buy_monthly"),
    ], [
        InlineKeyboardButton("⚡ شارژ 1$", callback_data="buy_pack_100"),
        InlineKeyboardButton("⚡ شارژ 3$", callback_data="buy_pack_300"),
        InlineKeyboardButton("⚡ شارژ 5$", callback_data="buy_pack_500"),
    ]])

def status_line(uid: int) -> str:
    u = db.get_user(uid)
    if not u:
        return ""
    u = db._rollover_daily(u)
    plan = db.effective_plan(u)
    if plan == "monthly":
        days = int((u["plan_expires"] - time.time()) // 86400) + 1
        return f"💎 اشتراک فعال ({days} روز مانده) | امروز: {u['daily_used']}/{config.MONTHLY_DAILY_MESSAGES}"
    if plan == "credit":
        return f"⚡ اعتبار: {u['balance_messages']} پیام"
    return f"🆓 رایگان | امروز: {u['daily_used']}/{config.FREE_DAILY_MESSAGES}"

# ─────────────── هندلرها ───────────────

async def cmd_start(update: Update, ctx):
    u = update.effective_user
    db.upsert_user(u.id, u.username or "")
    await update.message.reply_text(
        "👋 سلام <b>{name}</b>!\n\n"
        "من <b>NovaMind</b> هستم — دستیار هوش مصنوعی‌ت.\n\n"
        f"🆓 روزانه <b>{config.FREE_DAILY_MESSAGES} پیام رایگان</b> داری.\n"
        "برای بیشتر، اشتراک بگیر یا شارژ کن ⬇️".format(name=u.first_name),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard_main(),
    )

async def cmd_buy(update: Update, ctx):
    packs = "\n".join(
        f"• ⚡ {k/100:.0f}$ → <b>{v} پیام</b>"
        for k, v in sorted(config.PAYG_PACKS.items()))
    await update.message.reply_text(
        "💳 <b>پلن‌ها:</b>\n\n"
        f"💎 اشتراک ماهانه — <b>{fmt_usdt(config.MONTHLY_PRICE_CENTS)} USDT</b>\n"
        f"({config.MONTHLY_DAILY_MESSAGES} پیام/روز × {config.MONTHLY_DAYS} روز)\n\n"
        f"{packs}\n\n"
        "پرداخت با <b>USDT (TRC20)</b> — انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard_main(),
    )

async def cmd_status(update: Update, ctx):
    await update.message.reply_text(status_line(update.effective_user.id))

async def on_button(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data  # buy_monthly | buy_pack_100 ...

    if data == "buy_monthly":
        base, kind, credit = config.MONTHLY_PRICE_CENTS, "monthly", 0
    else:
        cents = int(data.split("_")[2])
        base, kind, credit = cents, "pack", config.PAYG_PACKS[cents]

    p = db.create_payment(uid, kind, base, credit)
    amount = fmt_usdt(p["expected_cents"])

    pay_text = (
        "💰 <b>پرداخت با USDT (TRC20)</b>\n\n"
        f"مبلغ دقیق: <code>{amount}</code> USDT\n"
        f"به آدرس:\n<code>{config.DEPOSIT_ADDRESS}</code>\n\n"
        "⚠️ <b>مهم:</b>\n"
        "۱. شبکه رو حتماً <b>TRC20</b> انتخاب کن\n"
        f"۲. دقیقاً همین عدد <code>{amount}</code> رو بفرست (این عدد شناسه‌ی پرداخت توئه — اعشارش رو دستکاری نکن)\n"
        f"۳. مهلت: {config.PAYMENT_WINDOW//60} دقیقه\n\n"
        "✅ بعد از تأیید شبکه (حدود ۱-۲ دقیقه) حسابت خودکار فعال می‌شه."
    )
    await q.message.reply_text(pay_text, parse_mode=ParseMode.HTML)

async def on_message(update: Update, ctx):
    msg = update.message
    if not msg or not msg.text:
        return
    uid = update.effective_user.id
    text = msg.text.strip()

    if text.startswith("/admin"):
        if admin.is_admin(uid):
            await admin.handle_admin(
                text, lambda r, markdown=False: ctx.application.create_task(
                    msg.reply_text(r, parse_mode=ParseMode.HTML if markdown else None)))
        else:
            await msg.reply_text("⛔ فقط ادمین.")
        return
    if text.startswith("/"):
        return  # دستورهای دیگه

    db.upsert_user(uid, update.effective_user.username or "")
    ok, note = db.check_and_consume(uid)
    if not ok:
        await msg.reply_text(note, reply_markup=keyboard_main())
        return

    await ctx.bot.send_chat_action(uid, "typing")
    db.add_message(uid, "user", text)
    history = db.get_history(uid)
    answer = ai.chat(history)
    db.add_message(uid, "assistant", answer)

    # جواب بلند → چند تکه
    for i in range(0, len(answer), 4000):
        await msg.reply_text(answer[i:i+4000])
    if note:
        await msg.reply_text(note, disable_notification=True)

# ─────────────── اطلاع شارژ ───────────────

def make_payment_notifier(app_ref):
    def notify(p: dict):
        uid, cents = p["user_id"], p["expected_cents"]
        what = ("💎 اشتراک ماهانه فعال شد!" if p["kind"] == "monthly"
                else f"⚡ {p['credit_messages']} پیام اعتباری اضافه شد!")
        try:
            app_ref.create_task(app_ref.bot.send_message(
                uid, f"✅ پرداخت {fmt_usdt(cents)} USDT تأیید شد!\n{what}"))
        except Exception:
            pass
    return notify

# ─────────────── اجرا ───────────────

def main():
    db.init()
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_button, pattern="^buy_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    tron_watcher.start_loop(notify_cb=make_payment_notifier(app))
    log.info("NovaMind bot started. Watcher running.")
    print("🤖 NovaMind running… Ctrl+C برای خروج")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
