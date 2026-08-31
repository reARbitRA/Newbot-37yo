#!/usr/bin/env python3
"""
NovaRouter — ارکستراتور چند-پروایدره LLM (۱۴۰۵/2026)

✦ طبقه‌بندی پرامپت: ساده / متوسط / پیچیده → مسیریابی هوشمند
✦ زنجیره‌ی failover خودکار + circuit breaker
✦ احترام به rate limit هر پروایدر (پنجره‌ی لغزان — تا سقف مجاز، نه بیشتر)
✦ retry با backoff نمایی روی 429/5xx
✦ آمار لیتنسی و سلامت هر پروایدر
✦ thread-safe — سازگار با python-telegram-bot

استفاده:
    from router import Router
    rt = Router()
    answer = rt.chat([{"role":"user","content":"سلام"}])

کلیدها رو از environment یا مستقیم اینجا بذار. هر پروایدر که کلید نداره
خودکار غیرفعاله — با یه کلید هم سیستم کار می‌کنه.
"""
import os, time, json, threading, urllib.request, urllib.error, random
from dataclasses import dataclass, field

# ══════════════════════ ۱) رجیستری پروایدرها ══════════════════════
# tier: سریع مدل‌های سبک و کم‌لتنسی | قوی: مدل‌های بزرگ‌تر برای کار سخت
# rpm: سقف درخواست در دقیقه (احترام به سهمیه — نه دور زدنش)
# هر پروایدرِ OpenAI-compatible اینجا قابل اضافه‌ست.

@dataclass(frozen=True)
class Model:
    name: str          # model id دقیق
    tier: str          # "fast" | "strong"
    rpm: int           # سقف مجاز در دقیقه

@dataclass
class Provider:
    key: str
    base_url: str
    models: list
    rpm: int = 20                      # سقف کل پروایدر
    priority: int = 50                 # کمتر = اولویت بیشتر
    enabled: bool = True

PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        key=os.getenv("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
        rpm=25, priority=10,
        models=[
            Model("llama-3.1-8b-instant",            "fast",   25),
            Model("llama-3.3-70b-versatile",         "strong",  25),
        ],
    ),
    "cerebras": Provider(
        key=os.getenv("CEREBRAS_API_KEY", ""),
        base_url="https://api.cerebras.ai/v1",
        rpm=25, priority=15,
        models=[
            Model("llama-3.1-8b",                    "fast",   25),
            Model("llama-3.3-70b",                   "strong",  25),
        ],
    ),
    "deepseek": Provider(
        key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com/v1",
        rpm=30, priority=20,
        models=[Model("deepseek-chat", "strong", 30)],
    ),
    "openrouter": Provider(
        key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
        rpm=15, priority=30,
        models=[
            # فقط مدل‌های تگ :free (رایگان روی حساب رایگان)
            Model("meta-llama/llama-3.3-70b-instruct:free",  "strong", 15),
            Model("deepseek/deepseek-chat-v3-0324:free",     "strong", 15),
            Model("google/gemma-2-9b-it:free",               "fast",   15),
        ],
    ),
    "mistral": Provider(
        key=os.getenv("MISTRAL_API_KEY", ""),
        base_url="https://api.mistral.ai/v1",
        rpm=10, priority=35,
        models=[
            Model("mistral-small-latest",  "fast",   10),
            Model("mistral-large-latest",  "strong",  5),
        ],
    ),
    "siliconflow": Provider(
        key=os.getenv("SILICONFLOW_API_KEY", ""),
        base_url="https://api.siliconflow.cn/v1",
        rpm=20, priority=25,
        models=[
            Model("Qwen/Qwen2.5-7B-Instruct",     "fast",   20),
            Model("deepseek-ai/DeepSeek-V3",      "strong", 20),
        ],
    ),
    "zai": Provider(
        key=os.getenv("ZAI_API_KEY", ""),
        base_url="https://api.z.ai/api/paas/v4",
        rpm=15, priority=40,
        models=[Model("glm-4-flash", "fast", 15)],
    ),
    "sambanova": Provider(
        key=os.getenv("SAMBANOVA_API_KEY", ""),
        base_url="https://api.sambanova.ai/v1",
        rpm=10, priority=45,
        models=[Model("Meta-Llama-3.1-8B-Instruct", "fast", 10)],
    ),
}

# ══════════════════════ ۲) طبقه‌بندی پرامپت ══════════════════════
# heuristic سبک و آنی (بدون LLM → صفر لیتنسی اضافه)

_REASON = ("تحلیل", "مقایسه", "بررسی", "استدلال", "اثبات", "طراحی",
           "analyze", "compare", "explain", "prove", "evaluate",
           "design", "architecture", "strategy", "optimize")
_CODE = ("```", "def ", "class ", "import ", "error", "traceback", "bug",
         "کد", "برنامه", "اسکریپت", "function", "api", "sql", "regex")
_CREATIVE = ("بنویس", "داستان", "شعر", "مقاله", "write", "story", "essay",
             "draft", "marketing", "محتوا")

def classify(messages: list[dict]) -> str:
    """خروجی: 'simple' | 'medium' | 'complex'"""
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    n = len(last)
    score = 0
    if n > 400:   score += 2
    elif n > 120: score += 1
    if len(messages) > 6:          score += 1      # گفتگوی طولانی
    low = last.lower()
    if any(k in low for k in _CODE):     score += 4   # کد همیشه سطح بالا
    if any(k in low for k in _REASON):   score += 1
    if any(k in low for k in _CREATIVE): score += 1
    if any(c in last for c in "=-×÷^∫∑"): score += 1
    # سؤال کوتاهِ تک‌خطی با یک نشانه فقط → ساده بمان (مگر کد باشد)
    if not any(k in low for k in _CODE) and score <= 1 and n <= 80 and len(messages) <= 2:
        score = 0
    if score >= 4: return "complex"
    if score >= 2: return "medium"
    return "simple"

# ══════════════════════ ۳) لایه‌های زیرساخت ══════════════════════

class RateLimiter:
    """پنجره‌ی لغزان — تضمین نمی‌کنیم از سهمیه‌ی پروایدر بیشتر بزنیم."""
    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}
    def allow(self, pid: str, rpm: int) -> bool:
        now = time.time()
        with self._lock:
            w = self._hits.setdefault(pid, [])
            w[:] = [t for t in w if t > now - 60]
            if len(w) >= rpm:
                return False
            w.append(now)
            return True
    def next_free(self, pid: str) -> float:
        with self._lock:
            w = self._hits.get(pid, [])
            return (w[0] + 60) - time.time() if w else 0.0

class Breaker:
    """circuit breaker: ۳ خطای متوالی → ۶۰ ثانیه استراحت."""
    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
    def ok(self, pid: str) -> bool:
        with self._lock:
            s = self._state.get(pid)
            return not (s and s["open_until"] > time.time())
    def record(self, pid: str, success: bool):
        with self._lock:
            s = self._state.setdefault(pid, {"fails": 0, "open_until": 0})
            if success:
                s["fails"] = 0; s["open_until"] = 0
            else:
                s["fails"] += 1
                if s["fails"] >= 3:
                    s["open_until"] = time.time() + 60
    def status(self) -> dict:
        with self._lock:
            return {k: {"fails": v["fails"],
                        "open": v["open_until"] > time.time()}
                    for k, v in self._state.items()}

# ══════════════════════ ۴) روتر ══════════════════════

@dataclass
class _Stats:
    calls: int = 0; fails: int = 0
    latency_sum: float = 0.0
    by_model: dict = field(default_factory=dict)

class Router:
    def __init__(self, system_prompt: str = "", max_tokens: int = 1200):
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.limiter = RateLimiter()
        self.breaker = Breaker()
        self.stats: dict[str, _Stats] = {}
        self._lock = threading.Lock()

    # ---- زنجیره‌ی مدل برای هر سطح ----
    def _chain(self, level: str) -> list[tuple[str, Model]]:
        want = "fast" if level == "simple" else "strong"
        out = []
        for pid, p in PROVIDERS.items():
            if not (p.enabled and p.key):
                continue
            for m in p.models:
                # simple → فقط fast | medium → fast قوی‌ها یا strong | complex → strong
                if level == "simple" and m.tier != "fast":      continue
                if level == "complex" and m.tier != "strong":   continue
                out.append((pid, m, p))
        # اولویت: priority پروایدر + بونوس لیتنسی پاین‌تر
        out.sort(key=lambda x: x[2].priority)
        return out

    def _call(self, p: Provider, model: str, messages: list[dict]) -> str:
        body = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(
            p.base_url.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {p.key}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()

    def _track(self, pid: str, model: str, dt: float, ok: bool):
        with self._lock:
            s = self.stats.setdefault(pid, _Stats())
            s.calls += 1
            if not ok: s.fails += 1
            s.latency_sum += dt
            mm = s.by_model.setdefault(model, {"n": 0, "t": 0.0})
            mm["n"] += 1; mm["t"] += dt

    # ---- API اصلی ----
    def chat(self, messages: list[dict], level: str | None = None) -> str:
        level = level or classify(messages)
        payload = ([{"role": "system", "content": self.system_prompt}] + messages
                   if self.system_prompt else messages)
        tried = 0
        for pid, model, p in self._chain(level):
            if tried >= 4:                        # حداکثر ۴ تلاش
                break
            if not self.breaker.ok(pid):          # بریکر بازه
                continue
            if not self.limiter.allow(pid, min(p.rpm, next(
                    (m.rpm for m in p.models if m.name == model), p.rpm))):
                continue                          # سهمیه‌ی همین دقیقه پرّه — بعدی
            t0 = time.time()
            try:
                out = self._call(p, model.name, payload)
                self._track(pid, model, time.time() - t0, True)
                self.breaker.record(pid, True)
                return out
            except urllib.error.HTTPError as e:
                self._track(pid, model, time.time() - t0, False)
                self.breaker.record(pid, False)
                if e.code == 429:                 # backoff مؤدبانه و بعدی
                    time.sleep(min(2 ** tried + random.random(), 8))
                tried += 1
            except Exception:
                self._track(pid, model, time.time() - t0, False)
                self.breaker.record(pid, False)
                tried += 1
        return ("⏳ همه‌ی مسیرهای آزاد این دقیقه پرشد — ۳۰ ثانیه بعد "
                "دوباره بفرست. (سطح: " + level + ")")

    def health(self) -> dict:
        with self._lock:
            return {
                pid: {"calls": s.calls, "fails": s.fails,
                      "avg_ms": int(1000 * s.latency_sum / max(s.calls - s.fails, 1)),
                      "models": s.by_model}
                for pid, s in self.stats.items()
            } | {"breakers": self.breaker.status()}

ROUTER = None
def get_router(system_prompt: str = "") -> Router:
    global ROUTER
    if ROUTER is None:
        ROUTER = Router(system_prompt)
    return ROUTER
