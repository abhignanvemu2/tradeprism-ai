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

## Searchable stocks, complete tables and 3D overview

The Dashboard replaces the daily-results table with the **Stocks** table. Search matches symbols and company names across the complete discovered universe. Server-side sorting happens before pagination: highest recorded paper win rate is the default, with price, gainers/losers, symbol and resolved-count sorting available. Select the timeframe, result period and minimum sample count. Stocks with no resolved forecasts have no win rate; small samples are marked explicitly. This is observed paper performance, not a new prediction or proof of trading profitability.

The stock table and separate **Background** module refresh every five seconds. First/previous/next/last buttons, a page-number input and page sizes up to 200 make every matching record accessible. Forecast history also uses pagination instead of the latest-100 display cutoff; background jobs are no longer limited to the latest five/30 in the UI. Live sorting can move rows between pages as prices or results change; use symbol sorting for easier browsing.

The Three.js overview shows the counts of rising, falling, unchanged and unavailable stocks for the entire filtered result, including records outside the current page. It uses stored provider prices against previous close, not invented chart values. Reduced-motion preferences and a pause control are supported. Rendering stops in hidden/offscreen views and resources are released on navigation; numeric counts remain available without WebGL.

## Automatic dashboard and prospective results (v0.4)

Once `start.bat` is running with a working Upstox token, **Dashboard** refreshes automatically. You do not have to click Fetch or Train for each stock. Opening a chart gives it collection priority; the discovered NSE/BSE universe keeps progressing in the background.

- The collection queue now covers **1m, 5m, 15m, 1h and daily** charts. Automatic model fitting covers **1m, 5m and 15m**. Hourly/daily swing models, additional strategy families, derivatives and all possible chart styles are not implemented.
- Ranked candidates must have a fresh compatible model, at least 30 selected holdout trades, positive holdout mean net return after assumed costs, a Brier score better than the simple baseline, and probability at least the model's threshold. If none qualify, the dashboard says so. Passing these research gates is not production/live-trading validation.
- Automatic prospective forecasts freeze the model version, probability, entry, stop, target and timestamp **before** the entry window. They use a one-bar waiting period after the observed candle, then a stop entry in the next full bar, with a 12-bar outcome horizon inside the same session. The training labels use exactly this timing. The version change triggers automatic retraining; old-model inference is blocked.
- The system records forecasts even when they fail the candidate quality gate, to expose poor results rather than hide them. The dashboard identifies the qualifying subset separately. Forecasts never place real orders.
- Daily and previous-calendar-week results use **recorded forward paper outcomes**, with IST outcome dates, positive-net-return wins, target-hit rate, losses, pending forecasts, unfilled entries and unverifiable outcomes. Net win rate is not the same quantity as estimated target-hit probability. Fixed 15 bps per side are an assumption, not a verified broker charge schedule.
- No past live wins are invented on installation. Results accumulate from deployment onward. Existing historical holdout results remain in Models and must not be passed off as prospective results. Daily returns are per-forecast averages, not portfolio profit; correlated stocks/timeframes are not independent samples.
- Missing expected candles or revisions invalidate a pending forecast's measurement rather than fabricate an outcome. Changed historical data can still require explicit reconciliation; fully unattended operation cannot safely conceal unresolved data conflicts.
- Every stock/timeframe takes provider requests, CPU and storage. Whole-market backfill can take days. The 5,000-key rotating price stream and slower candle/retraining queues are **not simultaneous tick-level analysis of every chart**. Unsupported stock groups, insufficient evidence and stale coverage remain visible. The app cannot guarantee a win percentage or a profitable “best trade.”

Windows setup now reuses `backend/.venv`, checks backend dependencies, waits for API health before starting the website and reports which process exited. Data defaults to `backend/data` regardless of the terminal's working directory. Run setup only after stopping old app processes.

## Continuous monitoring and automatic training (v0.3)

In PowerShell, stop the old launcher with Ctrl+C, then:

```powershell
git pull origin main
.\setup.bat
.\start.bat
```

Keep your existing `.env`; no extra paid account or AI API key is required. Automatic research defaults to enabled. Set `CONTINUOUS_RESEARCH=0` and restart to disable its collector and live-feed processes. Only one launcher should run against a database.

- The collector discovers the provider's current **NSE and BSE equity-segment** instrument masters, filtering supported stock groups (BSE does not use NSE's `EQ` type) daily. BSE symbols use `BSE_` to distinguish exchange listings. This is not a point-in-time historical universe and does not cover all security types or guarantee every listed/suspended stock is present.
- A separate TLS-verified Upstox V3 **LTPC WebSocket** process receives real prices. The UI reads the latest persisted prices every 5 seconds (scanner: 15 seconds). Trade timestamps and stale states remain visible; a connected socket alone does not prove fresh trades.
- Standard LTPC capacity is **5,000 instrument keys**. Larger universes rotate subscriptions every 5 minutes; overflow instruments are **not streamed simultaneously**. The coverage panel shows the requested subscription count and overflow, not a claim that every instrument sent ticks.
- The collector downloads up to 10,000 completed intraday bars per newly discovered symbol/timeframe, then refreshes existing histories. Initial download of thousands of histories can take many hours or days and substantial disk space. Provider pacing, network speed and laptop capacity determine the actual delay. Existing charts and initial downloads alternate to avoid starving either queue.
- Training runs automatically in a separate serial worker, with at most 20 pending jobs. At least 12 newly stored completed candles must arrive after the previous attempt before another automatic attempt; elapsed weekends do not count as bars. Labels use only observed completed outcomes; this is **automatic batch retraining, not online learning from every tick**. The same failed dataset is not endlessly retried.
- A live last-trade price is distinct from a current chart or model. Price-only ticks never fabricate volume or replace verified OHLCV. Charts and model inference update after REST history collection; **full-market chart analysis is not simultaneous or guaranteed real time**.
- Open **Dashboard** for recorded forecasts and daily/weekly results, or **Scanner** to search and page through stocks. Open **Models** to inspect research results. Manual fetch/prepare remains available for selected stocks and other supported timeframes.
- Nonstandard stock groups (including trade-to-trade/SME groups) remain visible, but the current intraday strategy refuses training until their settlement/session rules are supported.
- Research models remain non-actionable, including automatically trained models. Automatic training does not guarantee improvement; no deployment-quality model promotion or performance guarantee is claimed. Keep the terminal open; closing the browser does not stop collection/training.

The generated Protobuf decoder comes from the [official Upstox V3 schema](https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto). The app uses its own TLS-verified socket, reconnects with backoff, and does not log temporary authorized feed URLs. REST requests share conservative local pacing of one request per 1.1 seconds across collector and worker. Other apps sharing the same Upstox account also consume the provider's quota.

## What changed in v0.2

- Upstox read-only V3 history/intraday adapter for AXISBANK, HDFCBANK and ICICIBANK; master-derived identifiers, paise-to-INR ticks, bounded history windows, incomplete-candle exclusion.
- Indian stocks are the default UI/scanner universe. Legacy crypto/forex adapters remain internal for compatibility but are not required.
- Local `.env` loading and Windows setup/start scripts; SQLite by default.
- Local calculation-based explanations; `/explain` no longer calls any external LLM endpoint.
- Research training for Indian stocks at 1m/5m/15m. Outcome labels cannot cross a session or missing interval; large discontinuities are rejected for review. No claim that these guards fully reconcile corporate actions.
- Combined download/train background job, with honest failures and no demonstration data.

## Limits — read before use

This is research software, not the completed production platform. Upstox integration cannot be verified end-to-end until you configure a valid token. Live price streaming is implemented but requires verification with your token; authenticated streaming could not be tested in the development environment. Completed-candle chart collection remains REST-based and can lag. Exchange holiday validation, full corporate-action reconciliation, walk-forward validation and production safeguards remain unfinished. The local explanation engine is not an LLM; a custom LLM is a separate future project.

Indian-stock training is now permitted for **research only**, with the guards above. Its results must not be treated as validated trading recommendations. 1h/daily equity training is blocked because the initial 12-bar intraday strategy must finish within one session. There is no guaranteed accuracy and no trained Indian-stock artifact bundled.

If old stored candles came from Kite, do not mix them with Upstox: use a new `DATA_DIR` for all services. Ordinary ingestion never rewrites historical candles. If provider corrections conflict, use **Reconcile history + retrain**: changed values are archived in immutable `data_revision` records before updating the current candle dataset. Old model artifacts remain preserved and inference from models predating the reconciliation is blocked. Reconciliation requires the provider response to cover the entire stored date range; it does not independently verify corporate actions. Large discontinuities still block training. Default local storage remains `backend/data`.

Training requires sufficient examples of both outcomes in separate chronological partitions. A failed minimum-evidence check is not an installation error. The test suite uses isolated synthetic fixtures only; the running app never does.

## Checks

```bat
cd backend
.venv\Scripts\python -m pytest -q
cd ..\frontend
npm run build
```

Official integration references: [Upstox instruments](https://upstox.com/developer/api-documentation/instruments/), [V3 history](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/), [V3 intraday](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/), [read-only token](https://upstox.com/developer/api-documentation/analytics-token/).

The `docs/` files retain the detailed original research protocol and scope tracker; this v0.4 README supersedes older integration and coverage descriptions. Optional Docker files remain for users who prefer containers, but are not necessary for this workflow. Lightweight Charts attribution remains enabled.

Feed limits: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
REST quotas: https://upstox.com/developer/api-documentation/rate-limiting/
