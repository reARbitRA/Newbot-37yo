#!/usr/bin/env python3
"""
REDAEYE Router v2 — Fusion Engine
سطح‌بندی هوشمند + Cascade (FrugalGPT-style) + Fusion (Mixture-of-Agents)
+ Semantic Cache + Latency Scoring (EWMA) + Budget Planner + Cost Ledger

استراتژی‌ها:
  direct   — یک مدل بهترین‌انتخاب (simple)
  cascade  — مدل ارزان → بررسی کیفیت → در صورت نیاز مدل قوی (medium)
  fusion   — N پیشنهاددهنده‌ی موازی + ترکیب‌کننده (complex)

کاربر هیچ‌وقت نمی‌بیند پشت صحنه چه مدلی جواب داده — فقط جواب می‌بیند.
"""
import os, re, json, time, hashlib, threading, urllib.request, urllib.error
import policy
import concurrent.futures
from dataclasses import dataclass

# ══════════════ ۱) رجیستری ══════════════

@dataclass(frozen=True)
class ModelSpec:
    name: str
    tier: str            # fast | strong
    rpm: int
    price_in: float      # $/1M tokens (لیست‌پرایس — برای ledger)
    price_out: float
    caps: tuple = ()     # ("vision","long")

@dataclass
class ProviderSpec:
    key: str
    base_url: str
    daily_cap: int       # سقف درخواست در روز (احترام به سهمیه)
    priority: int
    models: list

def _p(key_env, url, daily, prio, models):
    return ProviderSpec(os.getenv(key_env, ""), url, daily, prio, models)

REGISTRY: dict[str, ProviderSpec] = {
    "groq": _p("GROQ_API_KEY", "https://api.groq.com/openai/v1", 1400, 10, [
        ModelSpec("llama-3.1-8b-instant",     "fast",   25, 0.05, 0.08),
        ModelSpec("llama-3.3-70b-versatile",  "strong", 25, 0.59, 0.79),
    ]),
    "cerebras": _p("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1", 900, 15, [
        ModelSpec("llama-3.1-8b",   "fast",   25, 0.10, 0.30),
        ModelSpec("llama-3.3-70b",  "strong", 25, 0.85, 1.20),
    ]),
    "deepseek": _p("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", 800, 20, [
        ModelSpec("deepseek-chat", "strong", 30, 0.27, 1.10),
    ]),
    "openrouter": _p("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", 45, 30, [
        ModelSpec("meta-llama/llama-3.3-70b-instruct:free", "strong", 15, 0.0, 0.0),
        ModelSpec("google/gemma-2-9b-it:free",             "fast",   15, 0.0, 0.0),
    ]),
    "mistral": _p("MISTRAL_API_KEY", "https://api.mistral.ai/v1", 200, 35, [
        ModelSpec("mistral-small-latest", "fast",   10, 0.20, 0.60),
        ModelSpec("mistral-large-latest", "strong",  5, 2.00, 6.00),
    ]),
    "siliconflow": _p("SILICONFLOW_API_KEY", "https://api.siliconflow.cn/v1", 600, 25, [
        ModelSpec("Qwen/Qwen2.5-7B-Instruct", "fast",   20, 0.0, 0.0),
        ModelSpec("deepseek-ai/DeepSeek-V3",  "strong", 20, 0.27, 1.10),
    ]),
    "zai": _p("ZAI_API_KEY", "https://api.z.ai/api/paas/v4", 300, 40, [
        ModelSpec("glm-4-flash", "fast", 15, 0.0, 0.0),
    ]),
    "sambanova": _p("SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1", 200, 45, [
        ModelSpec("Meta-Llama-3.1-8B-Instruct", "fast", 10, 0.0, 0.0),
    ]),
}

# ══════════════ ۲) سطح‌بندی پرامپت ══════════════

_REASON = ("تحلیل", "مقایسه", "بررسی", "استدلال", "اثبات", "طراحی", "بهینه",
           "analyze", "compare", "prove", "evaluate", "design", "architect", "optimize", "step-by-step")
_CODE = ("```", "def ", "class ", "import ", "traceback", "function", "sql", "regex",
         "کد", "برنامه بنویس", "دیباگ", "باگ", "error در")
_CREATIVE = ("داستان", "شعر", "مقاله", "بنویس", "محتوا", "story", "essay", "draft", "script")

def classify(messages: list[dict]) -> str:
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    n, low = len(last), last.lower()
    total_ctx = sum(len(m["content"]) for m in messages)
    score = 0
    if n > 400: score += 2
    elif n > 120: score += 1
    if total_ctx > 2500: score += 1
    if len(messages) > 6: score += 1
    if any(k in low for k in _CODE): score += 4
    if any(k in low for k in _REASON): score += 1
    if any(k in low for k in _CREATIVE): score += 1
    if any(c in last for c in "=-×÷^∑"): score += 1
    if score <= 1 and n <= 80: return "simple"
    if score >= 4: return "complex"
    return "medium"

# ══════════════ ۳) زیرساخت ══════════════

class SlidingWindow:
    def __init__(self):
        self._lk = threading.Lock(); self._w: dict[str, list] = {}
    def allow(self, pid, rpm):
        now = time.time()
        with self._lk:
            w = self._w.setdefault(pid, [])
            w[:] = [t for t in w if t > now - 60]
            if len(w) >= rpm: return False
            w.append(now); return True

class DailyBudget:
    """سقف روزانه به ازای پروایدر — رول‌اوور نیمه‌شب."""
    def __init__(self):
        self._lk = threading.Lock(); self._d: dict[str, int] = {}; self._day = ""
    def allow(self, pid, cap):
        day = time.strftime("%Y%m%d")
        with self._lk:
            if day != self._day: self._d.clear(); self._day = day
            return self._d.get(pid, 0) < cap
    def bump(self, pid):
        with self._lk: self._d[pid] = self._d.get(pid, 0) + 1
    def left(self, pid, cap):
        with self._lk: return cap - self._d.get(pid, 0)

class Breaker:
    def __init__(self, threshold=3, cool=60):
        self._lk = threading.Lock(); self._s: dict = {}; self.th, self.cool = threshold, cool
    def ok(self, pid):
        with self._lk:
            s = self._s.get(pid); return not (s and s[1] > time.time())
    def record(self, pid, good):
        with self._lk:
            f, u = self._s.get(pid, (0, 0))
            self._s[pid] = (0, 0) if good else ((f + 1, time.time() + self.cool) if f + 1 >= self.th else (f + 1, u))

class LatencyEWMA:
    """امتیاز تأخیر — روتر به سمت پروایدرهای سریع‌تر می‌لغزد."""
    def __init__(self, alpha=0.3):
        self._lk = threading.Lock(); self._m: dict[str, float] = {}; self.a = alpha
    def update(self, pid, dt):
        with self._lk:
            old = self._m.get(pid, dt)
            self._m[pid] = self.a * dt + (1 - self.a) * old
    def get(self, pid):
        with self._lk: return self._m.get(pid, 1.5)

class SemanticCache:
    """کش نرمال‌شده (exact-normalized) با TTL."""
    def __init__(self, ttl=21600, max_entries=5000):
        self._lk = threading.Lock(); self._m: dict = {}
        self.ttl, self.maxn = ttl, max_entries
    @staticmethod
    def _key(messages):
        norm = re.sub(r"\s+", " ", " ".join(m["role"][0] + m["content"] for m in messages)).strip().lower()
        return hashlib.sha256(norm.encode()).hexdigest()
    def get(self, messages):
        k = self._key(messages)
        with self._lk:
            hit = self._m.get(k)
            if hit and time.time() - hit[1] < self.ttl: return hit[0]
            self._m.pop(k, None); return None
    def put(self, messages, answer):
        k = self._key(messages)
        with self._lk:
            if len(self._m) >= self.maxn:
                oldest = min(self._m, key=lambda x: self._m[x][1])
                self._m.pop(oldest)
            self._m[k] = (answer, time.time())

class Ledger:
    """دفتر هزینه به قیمت لیست — آماده‌ی روزی که کلید پولی وصل شود."""
    def __init__(self, path="ledger.jsonl"):
        self.path = path; self._lk = threading.Lock()
        self.totals = {"requests": 0, "list_cost_usd": 0.0, "cache_hits": 0}
    def log(self, **kw):
        kw["ts"] = time.time()
        with self._lk:
            self.totals["requests"] += 1
            self.totals["list_cost_usd"] += kw.get("cost", 0.0)
            if kw.get("cache"): self.totals["cache_hits"] += 1
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(kw, ensure_ascii=False) + "\n")

# ══════════════ ۴) تشخیص کیفیت برای Cascade ══════════════

_BAD = ("i can't", "i cannot", "i'm sorry", "as an ai", "i'm unable",
        "نمی‌توانم", "نمیتونم", "متأسفم", "ببخشید ولی", "قادر نیستم", "من یک هوش مصنوعی")

def looks_bad(answer: str, prompt_len: int) -> bool:
    if not answer or len(answer.strip()) < max(12, prompt_len // 40): return True
    low = answer.lower()
    return any(b in low for b in _BAD)

# ══════════════ ۵) روتر ══════════════

class FusionRouter:
    def __init__(self, system_prompt="", cache_on=True, ledger_path="ledger.jsonl"):
        self.sys = system_prompt
        self.win, self.day, self.brk = SlidingWindow(), DailyBudget(), Breaker()
        self.lat = LatencyEWMA()
        self.cache = SemanticCache() if cache_on else None
        self.ledger = Ledger(ledger_path)
        self._call = self._http_call          # قابل‌موك در تست

    # ---- انتخاب کاندیدها ----
    def _available(self, tier):
        out = []
        for pid, p in REGISTRY.items():
            if not p.key: continue
            ok, cap = policy.provider_gate(pid)          # پنل مالک: enabled/billing/cap
            if not ok: continue
            eff_cap = cap if cap is not None else p.daily_cap
            for m in p.models:
                if m.tier != tier: continue
                if not (self.brk.ok(pid) and self.day.allow(pid, eff_cap)): continue
                out.append((pid, m, p))
        # اولویت ثابت + جریمه‌ی تأخیر تجربی (ثانیه × ۱۰)
        out.sort(key=lambda x: x[2].priority + self.lat.get(x[0]) * 10)
        return out

    def _pick(self, tier):
        for pid, m, p in self._available(tier):
            if self.win.allow(pid, min(m.rpm, p.priority * 3 + 20)):
                return pid, m, p
        # هرچی شد یه fast پیدا کن
        for pid, m, p in self._available("fast"):
            if self.win.allow(pid, m.rpm):
                return pid, m, p
        return None

    # ---- تماس پایه ----
    def _http_call(self, pid, model_name, messages, max_tokens=900):
        p = REGISTRY[pid]
        body = json.dumps({"model": model_name, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.7}).encode()
        req = urllib.request.Request(p.base_url.rstrip("/") + "/chat/completions",
            data=body, headers={"Content-Type": "application/json",
                                "Authorization": f"Bearer {p.key}"}, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode())
        dt = time.time() - t0
        usage = d.get("usage", {})
        return d["choices"][0]["message"]["content"].strip(), dt, usage

    def _safe_call(self, pid, m, messages, max_tokens=900):
        t0 = time.time()
        try:
            text, dt, usage = self._call(pid, m.name, messages, max_tokens)
            self.day.bump(pid); self.lat.update(pid, dt); self.brk.record(pid, True)
            tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            if not tin: tin = sum(len(x["content"]) for x in messages) // 4; tout = len(text) // 4
            cost = tin / 1e6 * m.price_in + tout / 1e6 * m.price_out
            self.ledger.log(provider=pid, model=m.name, strategy="call",
                            tokens_in=tin, tokens_out=tout, cost=round(cost, 6), ms=int(dt * 1000))
            return text
        except Exception:
            self.brk.record(pid, False); self.lat.update(pid, time.time() - t0)
            return None

    # ---- استراتژی‌ها ----
    def _direct(self, messages, tier):
        c = self._pick(tier)
        return self._safe_call(c[0], c[1], messages) if c else None

    def _cascade(self, messages):
        """ارزان اول؛ اگه خروجی بد/کوتاه/امتناعی بود → قوی (همان پروایدر یا بعدی)."""
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        cheap = self._pick("fast")
        if not cheap: return self._direct(messages, "strong")
        ans = self._safe_call(*cheap, messages)
        if ans and not looks_bad(ans, len(last_user)):
            return ans
        # escalate: اولین مدل قویِ «متفاوت» (پروایدر دیگر، یا مدل قوی همان پروایدر)
        for pid, m, p in self._available("strong"):
            if (pid, m.name) == (cheap[0], cheap[1].name):
                continue
            if not self.win.allow(pid, m.rpm):
                continue
            better = self._safe_call(pid, m, messages)
            if better and not looks_bad(better, len(last_user)):
                return better
        return ans

    def _fusion(self, messages, n=None):
        """N پیشنهاددهنده‌ی موازی + ترکیب‌کننده‌ی قوی (Mixture-of-Agents)."""
        n = n or 3
        cands = self._available("strong")[:n]
        if len(cands) < 2:
            return self._direct(messages, "strong")
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(self._safe_call, pid, m, messages) for pid, m, _ in cands]
            answers = [f.result() for f in futs]
        answers = [a for a in answers if a]
        if not answers:
            return None
        if len(answers) == 1:
            return answers[0]
        synth_prompt = messages + [{
            "role": "user",
            "content": "Three candidate answers follow. Merge them into ONE best final answer: "
                       "keep what's correct and complete, drop errors and repetition. "
                       "Reply with the final answer only.\n\n"
                       + "\n---\n".join(f"[Candidate {i+1}]\n{a}" for i, a in enumerate(answers))
        }]
        final = self._direct(synth_prompt, "strong")
        return final or max(answers, key=len)

    # ---- API اصلی ----
    def chat(self, messages: list[dict], level: str | None = None) -> str:
        level = level or classify(messages)
        payload = ([{"role": "system", "content": self.sys}] + messages) if self.sys else messages
        if self.cache:
            hit = self.cache.get(payload)
            if hit:
                self.ledger.log(strategy="cache", cache=True, cost=0.0)
                return hit
        strat = policy.strategy_for(level)            # پنل مالک: استراتژی هر سطح
        if strat == "cascade":
            out = self._cascade(payload)
        elif strat == "fusion":
            out = self._fusion(payload, n=policy.fusion_n())
        else:
            tier = "fast" if level == "simple" else "strong"
            out = self._direct(payload, tier)
        if out is None:
            # آخرین شانس: هر پروایدرِ زنده
            for tier in ("fast", "strong"):
                c = self._pick(tier)
                if c:
                    out = self._safe_call(c[0], c[1], payload)
                    if out: break
        if out is None:
            return "⏳ همه‌ی مسیرها این لحظه پرست — چند ثانیه بعد دوباره بفرست."
        if self.cache: self.cache.put(payload, out)
        return out

    # ---- پنل ----
    def health(self):
        rows = {}
        for pid, p in REGISTRY.items():
            if p.key:
                rows[pid] = {"daily_left": self.day.left(pid, p.daily_cap),
                             "breaker_ok": self.brk.ok(pid),
                             "ewma_s": round(self.lat.get(pid), 2)}
        return {"providers": rows, "ledger": self.ledger.totals,
                "policy": {"strategies": policy.snapshot()["strategies"],
                           "allow_paid": policy.allow_paid()}}
