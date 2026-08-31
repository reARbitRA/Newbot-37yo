# NovaMind — Architecture & Expansion Roadmap

## 1. Layer Map (today)

```
┌─────────────────────────┐   ┌──────────────────────────┐
│  bot.py (Telegram)      │   │  api_server.py (REST)    │
│  transport only         │   │  Mini App / web / mobile │
└───────────┬─────────────┘   └────────────┬─────────────┘
            │                              │
            └──────────┬───────────────────┘
                       ▼
            ┌─────────────────────┐
            │  core.py (NovaCore) │  ← platform-agnostic service
            │  chat · quota ·     │
            │  billing · accounts │
            └─────────┬───────────┘
        ┌─────────────┼──────────────┐
        ▼             ▼              ▼
   db.py (SQLite)  router.py    tron_watcher.py
   state           AI providers  TRC20 payments
```

**Rule enforced by the layering:** no business logic above `core.py`. Transports translate, core decides. That single rule is what makes every platform below cheap.

## 2. Platform Roadmap

| Stage | Platform | What it takes | Status |
|---|---|---|---|
| 0 | Telegram bot | — | ✅ shipped & tested |
| 1 | **Telegram Mini App** | `api_server.py` (done) + static webapp calling `/api/*`; initData HMAC verified (done); add session tokens | API ready; UI next |
| 2 | Standalone web app | same REST API + auth (NOVA_API_TOKEN or per-user JWT) | API ready |
| 3 | Mobile app | same REST API | API ready |
| 4 | Discord / other chats | new adapter ≈ 150 lines (transport only), reuses core 100% | pattern proven |

## 3. Mini App session flow (Stage 1)

1. Mini App opens → Telegram injects `initData`
2. POST `/api/miniapp/auth {init_data}` → server verifies HMAC (`verify_init_data`, tested)
3. Server returns short-lived session token (next milestone: `sessions` table + TTL)
4. All `/api/*` calls carry the session — same `NovaCore` methods as the bot

## 4. Scaling path (when needed, not before)

| Bottleneck | Swap | Interface isolation |
|---|---|---|
| SQLite → Postgres | new `db.py` backend (same functions) | all callers use `db.*` functions only |
| In-memory rate limiter → Redis | new `RateLimiter` class | `router.py` uses `.allow()/.next_free()` |
| Single process → workers | stateless `api_server` + shared DB | already stateless per-request |
| TRC20 polling → webhooks/integrators | replace `tron_watcher` internals | `poll_once()` contract |

## 5. Deployment (Iran-safe architecture)

```
[You in Iran] ──Telegram──▶ [Bot on VPS outside Iran] ──▶ AI APIs / TronGrid
```
Host the bot on any cheap VPS or free tier (Render/Railway/Fly). No VPN logic in code — the architecture *is* the answer: server talks to servers directly; you only talk to Telegram.

## 6. Conventions

- Money is always integer **cents** (never floats) — DB, payments, router.
- All user-facing errors are Persian, actionable, never raw exceptions.
- Tests: stdlib `unittest`, no network, deterministic — run before every deploy.
- Every module imports `config` for tunables; no magic numbers inline.
