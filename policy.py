#!/usr/bin/env python3
"""Policy — پنل کنترل صاحب پروژه.

مالک تصمیم می‌گیرد: کدام پروایدر روشنه، سقفش چنده، پولی یا مجانی،
و هر سطح پرامپت با کدام استراتژی جواب بگیرد. بدون ری‌استارت (hot-reload).

فایل: policy.json — قابل ویرایش دستی یا با دستورات ادمین در بات.
"""
import os, json, threading, time

POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.json")

DEFAULTS = {
    "strategies": {"simple": "direct", "medium": "cascade", "complex": "fusion"},
    "providers": {
        "groq":        {"enabled": True, "billing": "free", "daily_cap": 1400},
        "cerebras":    {"enabled": True, "billing": "free", "daily_cap": 900},
        "deepseek":    {"enabled": True, "billing": "free", "daily_cap": 800},
        "openrouter":  {"enabled": True, "billing": "free", "daily_cap": 45},
        "mistral":     {"enabled": True, "billing": "free", "daily_cap": 200},
        "siliconflow": {"enabled": True, "billing": "free", "daily_cap": 600},
        "zai":         {"enabled": True, "billing": "free", "daily_cap": 300},
        "sambanova":   {"enabled": True, "billing": "free", "daily_cap": 200}
    },
    "allow_paid": False,
    "fusion_n": 3
}

_lock = threading.RLock()
_cache = {"mtime": None, "data": None}

def _load() -> dict:
    with _lock:
        try:
            mtime = os.path.getmtime(POLICY_PATH)
        except OSError:
            with open(POLICY_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
            _cache["mtime"] = None
            _cache["data"] = dict(DEFAULTS)
            return _cache["data"]
        if _cache["data"] is None or mtime != _cache["mtime"]:
            with open(POLICY_PATH, encoding="utf-8") as f:
                data = json.load(f)
            _cache["mtime"], _cache["data"] = mtime, data
        return _cache["data"]

def _save(data: dict):
    with _lock:
        with open(POLICY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _cache["mtime"] = None          # force reload
        _load()

# ─────────────── خواندن ───────────────

def strategy_for(level: str) -> str:
    return _load()["strategies"].get(level, "direct")

def provider_gate(pid: str) -> tuple[bool, int | None]:
    """(اجازه؟, سقف روزانه مؤثر — None یعنی از رجیستری)"""
    p = _load()
    cfg = p["providers"].get(pid)
    if cfg is None:
        return True, None                       # پروایدر ناشناخته → رفتار پیش‌فرض رجیستری
    if not cfg.get("enabled", True):
        return False, None
    if cfg.get("billing") == "paid" and not p.get("allow_paid", False):
        return False, None                      # پولی، ولی پولی مجاز نیست
    cap = cfg.get("daily_cap")
    return True, (int(cap) if cap is not None else None)

def allow_paid() -> bool:
    return _load().get("allow_paid", False)

def fusion_n() -> int:
    return int(_load().get("fusion_n", 3))

def snapshot() -> dict:
    return json.loads(json.dumps(_load()))      # deep copy برای نمایش

# ─────────────── نوشتن (دستورات مالک) ───────────────

def set_provider(pid: str, **kw):
    """kw: enabled=True/False | billing='free'/'paid' | daily_cap=int"""
    if pid not in DEFAULTS["providers"]:
        raise ValueError(f"پروایدر ناشناخته: {pid} (موجود: {', '.join(DEFAULTS['providers'])})")
    d = _load()
    cfg = d["providers"].setdefault(pid, {"enabled": True, "billing": "free", "daily_cap": 999})
    if "enabled" in kw:
        cfg["enabled"] = bool(kw["enabled"])
    if "billing" in kw:
        if kw["billing"] not in ("free", "paid"):
            raise ValueError("billing باید free یا paid باشد")
        cfg["billing"] = kw["billing"]
    if "daily_cap" in kw:
        cfg["daily_cap"] = max(0, int(kw["daily_cap"]))
    _save(d)

def set_strategy(level: str, strat: str):
    if level not in ("simple", "medium", "complex"):
        raise ValueError("سطح باید simple | medium | complex باشد")
    if strat not in ("direct", "cascade", "fusion"):
        raise ValueError("استراتژی باید direct | cascade | fusion باشد")
    d = _load()
    d["strategies"][level] = strat
    _save(d)

def set_allow_paid(flag: bool):
    d = _load()
    d["allow_paid"] = bool(flag)
    _save(d)

def set_fusion_n(n: int):
    if not 2 <= int(n) <= 5:
        raise ValueError("fusion_n باید بین ۲ تا ۵ باشد")
    d = _load()
    d["fusion_n"] = int(n)
    _save(d)

def reset():
    _save(json.loads(json.dumps(DEFAULTS)))
