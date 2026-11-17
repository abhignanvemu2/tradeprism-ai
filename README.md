# TradePrism AI

A standalone market-research workspace with a Next.js frontend, Python analysis API, background ingestion/training worker, real-provider adapters, and a forward paper-scenario journal.

**Status: v0.1 research implementation. The full project brief is not yet complete. Do not deploy this as a commercial trading-advice service.** No genuine trained model or market-performance report is bundled: provider access was unavailable in the build environment. The code can train and save an actual model once sufficient genuine historical data is ingested. It never substitutes demonstration prices, recommendations, probabilities or returns.

## Run on Windows with Docker Desktop

Install Git and Docker Desktop with Linux containers enabled. Run these in **Command Prompt**:

```bat
git clone https://github.com/abhignanvemu2/tradeprism-ai.git
cd tradeprism-ai
copy .env.example .env
notepad .env
```

Set `TRADEPRISM_USERS` to a JSON object mapping your username to a random private access key. Replace `POSTGRES_PASSWORD` with a random database password; use URL-safe characters because Compose embeds it in a connection URL. Generate independent random values with Python if installed:

```bat
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Never reuse the example placeholder or commit the real `.env`. Then:

```bat
docker compose up --build -d
docker compose logs -f worker
```

Open **http://localhost:3000** and enter the access key you configured. The frontend stores it only in page memory; reloading locks the workspace. PostgreSQL and model artifacts persist in named Docker volumes. The database and API are not published to the host; the web port binds to loopback only.

The Compose configuration is supplied but could not be run in the build environment. The Python API tests and Next.js production build were run successfully.

## First genuine-data workflow

1. Choose `BTC-USD`, `1h`, then **Fetch history**. Keep the worker running. The public Coinbase Exchange endpoint must be reachable from your machine; public access still has provider terms and regional/network limitations.
2. Inspect the background job. An HTTP 403 or other provider error remains an error; the chart will stay empty. A successful fetch stores up to approximately 1,800 completed candles, with source and fetch timestamps.
3. Enable periodic polling if desired. It enqueues history refreshes every 60 seconds **while the page remains open**. This is completed-candle polling, not a live tick feed.
4. Click **Train research model**. Training requires at least 300 filled examples and at least 30 examples of both outcomes in each purged partition. Having 1,800 bars does not guarantee enough qualifying examples. If necessary, ingest more genuine history using the CLI below.
5. Review the saved artifact metadata and evaluation in **Models**. A conditional research probability is not a validated actionable recommendation, a win rate, or the probability of your edited trade.
6. Use manual drawing tools and enter your own entry, stop and target. Tick size and lot size come from provider metadata. Enter your account currency and a conversion assumption where needed. Calculate and save the plan, or create a forward paper scenario.
7. Fetch subsequent data to advance the paper scenario. Only completed bars opening after creation are used. One concurrent paper scenario per user is supported; terminal events are recorded without editing the original plan.

No real order-placement endpoint exists.

## Provider configuration

| Market | Adapter | Required configuration | Current limitation |
|---|---|---|---|
| AXISBANK, HDFCBANK, ICICIBANK | Kite Connect | `KITE_API_KEY`, current `KITE_ACCESS_TOKEN`, account/data entitlement | Historical charting implemented; equity model training deliberately blocked until corporate-action reconciliation is implemented. |
| BTC-USD, ETH-USD | Coinbase Exchange | Public market-data endpoint access | Historical REST polling; no streaming/order-book integration yet. Build environment returned HTTP 403. |
| EUR_USD | OANDA v20 | `OANDA_TOKEN`, `OANDA_ACCOUNT_ID`; `OANDA_ENV=practice` or `live` | Midpoint candles, provider tick volume; no executable bid/ask spread model. Account and jurisdiction availability must be checked with OANDA. |
| Explanations | OpenAI-compatible chat endpoint | `LLM_CHAT_URL`, `LLM_API_KEY`, `LLM_MODEL` | Server-side structured evidence and JSON response validation. Requires a separately configured service; it is not the predictive model. |

Keep credentials server-side in `.env`. Never put them into `NEXT_PUBLIC_*` variables. Do not paste broker access tokens into GitHub issues or chat. No credentials were included in this repository.

## Local development without Docker

Requires Python 3.12 and Node 24. Commands below are for Windows Command Prompt. Use three terminals from the repository directory. In terminals 1 and 2, set **the same** `TRADEPRISM_USERS` mapping and provider variables; local storage defaults to `backend/data/` using SQLite.

Terminal 1:

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set TRADEPRISM_USERS={"bib":"YOUR_RANDOM_ACCESS_KEY_AT_LEAST_24_CHARS"}
python -m uvicorn tradeprism.api:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bat
cd backend
.venv\Scripts\activate
set TRADEPRISM_USERS={"bib":"YOUR_RANDOM_ACCESS_KEY_AT_LEAST_24_CHARS"}
python -m tradeprism.worker
```

Terminal 3:

```bat
cd frontend
npm ci
npm run dev
```

Local development does not automatically load `.env`; either use Compose or set server variables in the terminals. On macOS/Linux use `source .venv/bin/activate` and `export` instead of Windows commands. To use PostgreSQL locally set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE` in both backend processes. Set `DATA_DIR` to the same persistent absolute directory for API and worker.

To ingest a larger research dataset, stop the worker temporarily and run from the backend directory with the same environment:

```bat
python -m tradeprism.cli ingest BTC-USD --timeframe 1h --count 5000
python -m tradeprism.cli train BTC-USD --timeframe 1h
```

## Implemented

- Source-tagged OHLCV ingestion, instrument metadata, deduplication, invalid-candle rejection, bounded retries and rate-limit backoff.
- Conservative historical-revision rejection instead of silently changing old research inputs.
- Authentication, owner-isolated plans/drawings/history, API request limiting, and audit events.
- Forward-only indicators and features, fixed breakout targets, logistic regression / gradient-boosted tree comparison, calibration and persisted model artifacts.
- Chronological train / selection / calibration / final-test partitions, purged label horizons, cost-aware sequential-trade statistics and uncertainty intervals.
- Candlestick, line, bar and area views; zoom/pan, crosshair, volume, EMA overlays, manual drawings, saved anchors, undo/redo, and drag-editable scenario levels.
- Real cached-universe scanner with explicit availability counts. No misleading cross-market opportunity rankings.
- Practice replay with future bars hidden and predictive inference disabled.
- Append-only signal snapshots and paper events, with database-level update/delete prevention.
- Tests and GitHub Actions build/test workflow.

## Important remaining work

The [acceptance checklist](docs/ACCEPTANCE.md) is the authoritative scope tracker. In particular:

- AXISBANK, forex and crypto live connections have **not** been verified with user credentials/reachable feeds.
- No real-market trained model, saved production artifact or empirical win-rate claim exists yet.
- Actionable AI signals are deliberately disabled pending executable-spread checks, time alignment, walk-forward validation and corporate-action/calendar handling.
- Advanced drawing/indicator configuration, synchronized multi-chart layouts, event/news integrations, independent alert workers, portfolio controls and production operations are incomplete.
- Single worker and simple database-backed job queue; no Redis distribution or multi-worker recovery guarantees.
- No public deployment was performed. Managed preview could not launch Next.js due to incompatible injected CLI flags, so browser layout and drawing interactions remain unverified.

## Checks

```bat
cd backend
python -m pytest -q
cd ..\frontend
npm ci
npm run build
```

Build-session results: **24 backend tests passed**; **Next.js production build and TypeScript checks passed**. Test prices and model examples are synthetic **only inside isolated tests** and never populate the application database or shipped model directory. Test artifacts live in temporary directories.

## Operating costs and deployment

Code itself does not purchase a service. Kite data entitlement, OANDA account access, LLM usage, hosting and managed database charges are external. Current quotations and redistribution rights must be confirmed with each provider; no cost or license is assumed from the existence of an API. See [provider/capability matrix](docs/CAPABILITIES.md).

For local backup, stop ingestion and back up PostgreSQL plus the research/model volume together. For SQLite, stop both processes and copy the entire data directory. Never deserialize untrusted joblib/pickle files. Before public deployment add TLS, managed identity/revocation, durable queue controls, migration tooling, backups with restore tests, monitoring, and the missing execution/data-quality checks. Commercial advice/execution requires a jurisdiction-specific review; this repository does not establish compliance.

## Project map

```text
frontend/             Next.js workspace and same-origin API proxy
backend/tradeprism/   API, data adapters, quant, ML, storage, worker
backend/tests/        Isolated calculations, leakage, lifecycle and failure tests
docs/                 Architecture, capabilities, acceptance and research protocol
compose.yaml          Local PostgreSQL + API + worker + web
```

Third-party charting: TradingView Lightweight Charts, Apache-2.0. Its visible attribution is enabled. TradePrism is not TradingView Advanced Charts and does not include an Advanced Charts license or imply affiliation.
