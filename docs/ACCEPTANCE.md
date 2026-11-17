# Acceptance status

The original full-platform acceptance criteria are **not met** by v0.1. This file distinguishes implemented code from actually verified integrations.

| Requirement | Status | Evidence / blocker |
|---|---|---|
| Genuine AXISBANK history/latest data | Adapter implemented, unverified | Missing Kite credentials/entitlement. No successful fetch performed. |
| Genuine crypto/forex feeds | Adapters implemented, unverified | Coinbase request returned HTTP 403; OANDA account credentials absent. |
| Distinguish live/delayed/stale | Partial | Historical completed bars and stale state shown. No live stream or verified delay/session calendar. |
| Real model trained/saved/evaluated/inferred | Pipeline implemented; real-data execution blocked | Test-only training/artifact/inference succeeds with isolated fixtures. No real-market artifact or report. |
| Reproducible levels and risk | Implemented / unit tested | ATR breakout plans and deterministic tick/lot/cost/FX sizing. Research-only levels; FX is a user assumption. |
| Unsupported probability claims absent | Implemented | Empty until a model exists; research target documented; edited user scenarios have null probability. |
| Manual chart tools/persistent drawings | Partial / build checked | Core tools and server persistence; browser interactions unverified and advanced capabilities pending. |
| Inspectable independent AI overlays | Not complete | Independent user-scenario lines; full AI zone/pattern annotations absent. |
| Manual risk recalculation | Implemented / math tested | Number edits or line drags trigger recalculation; browser dragging not verified. |
| Scanner real coverage | Implemented | Six configured instruments; data availability counts; actionable ranking deliberately absent. |
| Paper trades follow genuine updates | Code implemented / isolated lifecycle tests pass | No real feed was available to verify the forward loop. |
| Immutable historic signals | Implemented / database tested | Append-only records plus update/delete triggers. |
| Reports include losses/costs | Pipeline implemented / tests pass | No real market performance report exists yet. |
| Honest missing-service states | Implemented / tested | Auth/provider/model/LLM errors never manufacture output. |
| No user-facing dummy data | Implemented | Synthetic data limited to test files and temporary test databases/artifacts. |
| No unsupported 70% claim | Implemented | No asserted win rate; conditional estimates require actual model artifacts. |
| Multi-timeframe/sector/context analysis | Not complete | Single selected timeframe only; no bank index / broad-market integration. |
| Walk-forward, drift, event filters | Not complete | Single chronological purged holdout; age-based expiry only. |
| Portfolio and production operations | Not complete | One concurrent paper scenario; no portfolio-level correlated risk/daily-loss engine, migrations, Redis queue or tested disaster recovery. |

## Verification performed

- Python compilation and 24 backend tests passed.
- Next.js production build, including TypeScript checks, passed.
- GitHub Actions workflow supplied; remote CI status must be checked separately.
- Browser QA unavailable: the managed preview launcher injected Vite-style options that Next.js rejected (`--host`, `--strictPort`). No workaround server or fabricated screenshot was used.
- Docker/PostgreSQL deployment was not exercised in this environment; SQLite isolated tests verify the storage logic and immutable trigger behavior.

## Essential external inputs

1. A reachable authorized crypto market-data endpoint for the first real training run.
2. Kite API credentials and current NSE history entitlement for AXISBANK.
3. OANDA account/token if the forex adapter is wanted.
4. A configured compatible LLM endpoint/key/model for explanatory chat.

Configure credentials privately in the local server environment. Do not commit them. These inputs enable integration validation; they do not by themselves complete the remaining engineering work above.
