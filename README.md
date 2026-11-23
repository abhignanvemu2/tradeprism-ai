# TradePrism AI — Indian-stock local research

## Update and run on Windows (no Docker)

Install Python 3.12 and Node.js 24. In CMD, from your existing project folder:

```bat
git pull origin main
setup.bat
```

If you already have `.env`, keep it. Add this line with your own read-only Upstox token:

```env
UPSTOX_ACCESS_TOKEN=YOUR_UPSTOX_ANALYTICS_TOKEN
```

Keep your existing `TRADEPRISM_USERS` key. Kite, OANDA and LLM variables are no longer needed for the Indian-stock workflow. No PostgreSQL password is needed locally.

```bat
start.bat
```

If `.env` does not exist, the launcher creates it with a random app login key. Add the Upstox token and restart. Open http://localhost:3000 and enter the app key from `.env`. Keep the launcher window open; Ctrl+C stops its services. Never commit `.env` or share either token.

## Current terminal (v0.5)

- **Exactly 100 selected stocks**, defined in `backend/tradeprism/scope.py`; NSE listings only. No automatic expansion, BSE duplicate listings, crypto or forex research. Your `BSE` ticker is the company listed on NSE, not all BSE-exchange stocks.
- **Only 5m and 15m** collection, model fitting, chart selection and forecasts. Other jobs are cancelled at startup; old candles/models/evidence remain archived on disk. Old 1m/hourly/daily models cannot issue new forecasts.
- Confirmed renames: **ZOMATO → ETERNAL**, **LTIM → LTM**. The user-facing labels remain ZOMATO/LTIM; current provider names are shown. If a requested listing cannot be matched (including an unresolved demerger), it remains one of the 100 rows with an unavailable label; no guessed replacement or market data is supplied.
- Sidebar navigation, a mobile hamburger drawer with keyboard handling, readable tables, and a quieter terminal layout. Scanner and the old sidebar paper-research slogan are removed. The Three.js market-breadth view is available in a collapsed section.
- Clicking a stock opens `/stocks/<symbol>`, containing only that stock's chart, daily summary and forecast history. Workspace search and per-user Favorites remain available. Favorites persist in SQLite; out-of-scope favorites remain stored but are hidden from the active universe.
- **Forecasts default to today's issue date in Asia/Kolkata**, including an empty table before the first forecast of the day. Date ranges retrieve older records with complete pagination, position and timeframe filters. The default date rolls over automatically at IST midnight. Summary cards have their own session-date selector.
- Daily cards count long setups, short setups, successful/failed net outcomes, not-entered setups, open trades, waiting entries and missing/revised data. Counts include all recorded research forecasts, not just the qualified subset. Long/short counts describe issued setups, including ones that never entered. Breakeven is separate.

## Entry and outcome protocol

New model version: `bidirectional-breakout-v4-window3-partitioned`.

Both **long breakouts above 20-bar resistance** and **short breakdowns below 20-bar support** are learned. The local model includes direction and support/resistance distances; inference evaluates both directions. Stops are 1.5 ATR away, targets 3 ATR away, before costs. Separate long/short selected-holdout statistics are recorded. Model probability is the estimated chance of a target hit conditional on a simulated entry, not an observed win rate or guaranteed return.

A forecast is frozen before entry can occur. Following one waiting bar, its entry is eligible during the next **three candles**, within a maximum **12-candle outcome window**, capped at the 15:30 IST session close. A gap through entry uses the candle opening price (less favorable than the planned entry); a gap already beyond the target is unfilled. Stops take precedence when a candle touches both barriers and sequence is unknown. Later stop gaps use the adverse opening price. These exact rules also produce the historical training labels.

Each direction can have one unresolved forecast per stock/timeframe. Long and short research setups may coexist: they are independent scenarios, not a funded portfolio or an instruction to hold both positions.

The ledger distinguishes:

| State | Meaning |
|---|---|
| Waiting for entry | Entry window has not ended and fill is not confirmed |
| Entered / open | A completed candle confirms entry; no exit yet |
| Target / stop hit | Completed candles confirm a terminal result |
| Time expired | Closed at the time/session boundary with actual candle-close return |
| Not entered | Entry window ended without a valid entry, or opening gap exceeded target |
| Awaiting candle data | Required candles are missing; automatic backfill will retry |
| Unverifiable / revised | Evidence is still missing after the grace period or provider history changed |

Live LTPC ticks produce separate, persisted **entry/target/stop observations**. All received samples in a flush are considered, so a touch isn't lost just because the latest price retreats. These observations are provisional: a feed can miss ticks, and a last-price feed is not an execution feed. They do not fabricate confirmed wins. Completed REST candles confirm outcomes; candle ambiguity is explicitly conservative. Ticks received before entry publication/window or stale/out-of-order ticks cannot backdate entry.

An independent outcome-refresh thread collects missing history for unresolved forecasts while bootstrap collection/model training continue. Every successful candle ingestion also resolves forecasts. The UI refreshes every five seconds; confirmations depend on candle completion, provider availability and shared REST pacing. No exact tick-by-tick execution claim is made.

**Existing forecasts keep their original timing rules and immutable final outcomes.** A previous one-bar/gap-excluded forecast is not rewritten into a win using today's strategy. Its evidence explains the legacy rule. Pending old forecasts still receive outcome checks. Historical trained artifacts are retained, but old-strategy inference is blocked; automatic training switches to the new version.

## Training and corporate-action boundaries

Only the selected stocks and two intervals are trained. Training is queued and bounded, after new completed outcomes arrive, not on every price tick. First-time downloads and fitting take time; minimum evidence requirements remain in place (300 filled examples, with sufficient examples and both labels in each purged chronological partition).

A price discontinuity greater than 20% **partitions the dataset**. Rolling indicators reset at the boundary and each segment has its own warm-up; labels cannot span the boundary or missing intervals/session boundaries. Ratios near common split/bonus factors are flagged for inspection, not treated as proof of a corporate action. Genuine crashes and data errors can also cause gaps. Historical OHLC prices are not automatically multiplied by an inferred ratio. Valid sub-periods remain eligible for training if there is sufficient evidence.

Provider revisions to an already stored candle remain a different issue. Ordinary ingestion does not rewrite research evidence. Use **Reconcile history + retrain** to archive old values before accepting provider corrections; complete coverage of the stored range is required. Models trained before the revision cannot produce new inference. Full corporate-action and exchange-calendar verification remains unfinished.

## Local data and concurrency

Data defaults to `backend/data/tradeprism.db` (SQLite); trained artifacts are under `backend/data/models`. `DATA_DIR` / `DATABASE_URL` can override this. SQLite uses **WAL**, a **30-second busy timeout** on every connection and short serialized read/write transactions for competing writers. Network requests and model fitting occur outside database write transactions. WAL reduces contention; it does not make SQLite a multi-writer database. Run only one launcher.

Stop the app before backing up the complete `backend/data` folder; include SQLite sidecar files if present. Do not delete the database to fix a failed training job. The upgrade creates new progress/observation tables automatically and preserves old trade evidence.

Windows tests explicitly dispose of SQLAlchemy connections before temporary-directory cleanup. Tests use isolated synthetic fixtures only, never the application database or shipped market data.

## Verification and limits

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
cd ..\frontend
npm run build
```

The local model uses scikit-learn; explanations are deterministic calculations, not an external LLM. No live orders are placed. Short scenarios do not validate borrowing, settlement, broker eligibility or execution availability. Net paper returns assume 15 basis points per side, not verified broker charges. A positive test/paper win rate does not establish profitability or future accuracy. Simultaneous scenarios are correlated and their returns must not be summed as portfolio returns.

Authenticated Upstox streaming needs your local token and cannot be verified without it. Price observations can arrive promptly while REST confirmations lag. The terminal honestly reports stale/missing data. No model, demonstration prices or fabricated wins ship with the app.

References: [Upstox instruments](https://upstox.com/developer/api-documentation/instruments/), [V3 history](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/), [V3 intraday](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/), [analytics token](https://upstox.com/developer/api-documentation/analytics-token/), [NSE ZOMATO rename](https://nsearchives.nseindia.com/content/circulars/CML67420.pdf), [NSE LTIM rename](https://nsearchives.nseindia.com/content/circulars/CML72948.pdf).

This README supersedes older strategy/coverage documents under `docs/`. Lightweight Charts attribution remains enabled.
