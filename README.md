# 🤖 NovaMind Bot — بات تلگرامی AI با پرداخت USDT (TRC20)

بات دستیار هوش مصنوعی با مدل آزاد (freemium)، اشتراک ماهانه و شارژ pay-as-you-go، پرداخت با USDT روی شبکه TRON.

## ✨ امکانات
- 💬 چت AI با حافظه (تاریخچه اخیر هر کاربر)
- 🆓 پلن رایگان: پیام محدود روزانه
- 💎 اشتراک ماهانه (۳۰ روزه)
- ⚡ شارژ اعتباری (pay-as-you-go)
- 💰 پرداخت USDT-TRC20 با تأیید خودکار (TronGrid)
- 🛠 پنل ادمین داخل تلگرام

## 🚀 راه‌اندازی

### ۱. پیش‌نیازها
```bash
pip install -r requirements.txt
```

### ۲. تنظیمات
فایل `config.py` رو باز کن و این‌ها رو پر کن:

| کلید | توضیح |
|---|---|
| `BOT_TOKEN` | توکن بات از [@BotFather](https://t.me/BotFather) |
| `ADMIN_IDS` | آیدی عددی تلگرام خودت (از [@userinfobot](https://t.me/userinfobot) بگیر) |
| `DEPOSIT_ADDRESS` | آدرس ولت TRON تو (آدرس Receive از Trust Wallet — شبکه TRC20) |
| `AI_BASE_URL` | مثلاً `https://openrouter.ai/api/v1` یا `https://api.deepseek.com/v1` |
| `AI_API_KEY` | کلید API خودت (OpenRouter / DeepSeek / هر سرویس سازگار) |
| `AI_MODEL` | مثلاً `deepseek/deepseek-chat-v3-0324` یا `deepseek-chat` |

### ۳. اجرا
```bash
python bot.py
```

روی اندروید (Pydroid 3) هم اجرا می‌شه — همون مسیر `/storage/emulated/0/...`.

## 💰 جریان پرداخت
1. کاربر `/buy` می‌زنه → پلن انتخاب می‌کنه
2. بات یک **مبلغ دقیق و یکتا** می‌سازه (مثلاً `4.87 USDT` به‌جای `4.00`) و آدرس ولت رو نشون می‌ده
3. کاربر از Trust Wallet دقیقاً همون مبلغ رو TRC20 می‌فرسته
4. `tron_watcher.py` هر ۶۰ ثانیه تراکنش‌های ورودی رو از TronGrid چک می‌کنه
5. مبلغ تطبیق خورد → حساب کاربر خودکار شارژ می‌شه ✅

> ⚠️ مبلغ رو **دقیقاً** همون عدد اعشاری بفرسته — اعشار، شناسه‌ی پرداخته.

## 📋 پلن‌ها (پیش‌فرض — توی config قابل تغییر)
| پلن | قیمت | چی می‌ده |
|---|---|---|
| رایگان | 0 | ۱۰ پیام/روز |
| ماهانه | 4.00 USDT | ۳۰۰ پیام/روز × ۳۰ روز |
| شارژ 1 | 1.00 USDT | ۵۰ پیام اعتباری |
| شارژ 3 | 3.00 USDT | ۱۷۰ پیام |
| شارژ 5 | 5.00 USDT | ۳۰۰ پیام |

## 🛠 دستورات ادمین
```
/admin          — آمار کلی
/admin user <id> — وضعیت یک کاربر
/admin grant <id> <usdt> — شارژ دستی
/admin pending   — پرداخت‌های در انتظار
```

## 📁 ساختار
```
bot.py           — روتر اصلی و هندلرها
config.py        — تنظیمات
db.py            — دیتابیس SQLite
ai.py            — اتصال به AI (OpenAI-compatible)
tron_watcher.py  — دیده‌بان پرداخت TRC20
admin.py         — دستورات ادمین
```

---

## 🧠 REDAEYE Fusion Router v2 (`fusion_router.py`)

طبقه‌بندی خودکار پرامپت → سه استراتژی:
- **simple → direct**: سریع‌ترین مدل سبک
- **medium → cascade**: مدل ارزان اول؛ اگر جواب ضعیف/امتناعی بود → خودکار به مدل قوی (FrugalGPT-style)
- **complex → fusion**: ۳ مدل قوی موازی پاسخ می‌دهند + یک مدل ترکیب‌کننده بهترین جواب را می‌سازد (Mixture-of-Agents)

بعلاوه: کش معنایی (TTL ۶h)، امتیاز تأخیر EWMA (روتر به سمت پروایدر سریع‌تر می‌لغزد)، سقف روزانه هر پروایدر، circuit breaker، و دفتر هزینه به قیمت لیست (برای روز کلید پولی).

کاربر هیچ‌وقت زیرساخت را نمی‌بیند — فقط جواب.

**کلیدها** (env): `GROQ_API_KEY` `CEREBRAS_API_KEY` `DEEPSEEK_API_KEY` `OPENROUTER_API_KEY` `MISTRAL_API_KEY` `SILICONFLOW_API_KEY` `ZAI_API_KEY` `SAMBANOVA_API_KEY` — با یک کلید هم کار می‌کند.

تست: `PYTHONPATH=. python3 tests/test_fusion.py` (۸ تست)
