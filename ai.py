#!/usr/bin/env python3
"""AI client — REDAEYE Fusion Router v2 (cascade + fusion + cache)."""
import os, importlib
import config

_engines = {}

def _engine():
    """اولویت: fusion_router (اگر کلیدهای روتر ست شده) → تک‌پروایدر مستقیم."""
    if "fusion" not in _engines:
        _KEYS = ("GROQ_API_KEY","CEREBRAS_API_KEY","DEEPSEEK_API_KEY","OPENROUTER_API_KEY",
                 "MISTRAL_API_KEY","SILICONFLOW_API_KEY","ZAI_API_KEY","SAMBANOVA_API_KEY")
        try:
            import fusion_router
            from fusion_router import FusionRouter
            if not any(p.key for p in fusion_router.REGISTRY.values()) and any(os.getenv(k) for k in _KEYS):
                importlib.reload(fusion_router)   # کلید بعد از import ست شده — رجیستری تازه
            if any(p.key for p in fusion_router.REGISTRY.values()):
                _engines["fusion"] = FusionRouter(config.AI_SYSTEM_PROMPT)
                return _engines["fusion"]
        except Exception:
            pass
        _engines["fusion"] = None
    return _engines["fusion"]

def chat(messages: list[dict]) -> str:
    eng = _engine()
    if eng is not None:
        return eng.chat(messages)
    # fallback قدیمی: مستقیم با AI_BASE_URL/AI_API_KEY
    import urllib.request, json, urllib.error
    body = json.dumps({
        "model": config.AI_MODEL,
        "messages": [{"role": "system", "content": config.AI_SYSTEM_PROMPT}] + messages,
        "max_tokens": 1200, "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        config.AI_BASE_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.AI_API_KEY}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code == 401: return "⚠️ کلید AI نامعتبره."
        if e.code == 429: return "⏳ ظرفیت پرقه؛ یک دقیقه بعد امتحان کن."
        if e.code == 402: return "⚠️ اعتبار حساب AI تمام شده."
        return f"⚠️ خطای سرویس AI ({e.code})."
    except Exception as e:
        return f"⚠️ خطا در اتصال: {type(e).__name__}."

def health() -> dict:
    eng = _engine()
    return eng.health() if eng else {"mode": "single-provider"}
