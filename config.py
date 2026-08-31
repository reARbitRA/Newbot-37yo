#!/usr/bin/env python3
"""تنظیمات بات — همه رو اینجا پر کن."""

import os

# ═══════════════ تلگرام ═══════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# آیدی عددی ادمین‌ها (از @userinfobot بگیر)
ADMIN_IDS = [123456789]

# ═══════════════ پرداخت TRON ═══════════════
# آدرس ولت TRC20 خودت (Receive address از Trust Wallet)
DEPOSIT_ADDRESS = "YOUR_TRON_ADDRESS_HERE"
# ⚠️ آدرس رسمی قرارداد USDT روی TRON — تأییدشده از TronScan API (Tether USD / tether.to)
# قبل از استقرار حتماً یک‌بار خودت هم روی tronscan.org چک کن.
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# TronGrid — بدون کلید هم کار می‌کنه (rate پایین). کلید رایگان: trongrid.io
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")
TRONGRID_URL = "https://api.trongrid.io"
POLL_INTERVAL = 60          # ثانیه بین هر چک
PAYMENT_WINDOW = 3600       # مهلت پرداخت: ۱ ساعت

# ═══════════════ پلن‌ها ═══════════════
FREE_DAILY_MESSAGES = 10
MONTHLY_PRICE_CENTS = 400      # 4.00 USDT
MONTHLY_DAILY_MESSAGES = 300
MONTHLY_DAYS = 30

# شارژ اعتباری: {سنت}: تعداد پیام
PAYG_PACKS = {100: 50, 300: 170, 500: 300}

# هزینه هر پیام برای شارژی‌ها (به سنت USDT)
PER_MESSAGE_COST_CENTS = 2

# ═══════════════ AI ═══════════════
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "YOUR_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "deepseek/deepseek-chat-v3-0324")
AI_SYSTEM_PROMPT = (
    "You are NovaMind, a helpful AI assistant inside a Telegram bot. "
    "Be concise, friendly, and useful. Respond in the user's language "
    "(Persian or English). Use plain text; Telegram markdown is ok sparingly."
)

# ═══════════════ دیتابیس ═══════════════
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nova.db")
HISTORY_TURNS = 8  # چند پیام اخیر به‌عنوان context
