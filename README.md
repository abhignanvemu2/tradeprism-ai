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

## Guided workflow

1. Select AXISBANK and **15m**.
2. **Fetch history** to inspect genuine completed candles.
3. **Prepare training data + train** downloads up to 10,000 bars and runs local training/evaluation. This may take time and may still return insufficient evidence.
4. Review **Models** for measured results, dates, sample counts, costs and limitations.
5. **Explain calculated evidence** works locally without any LLM service. It is our deterministic explanation engine, not a language model or general chatbot.
6. Use your own plan and forward paper scenarios. No real orders are placed.

## What changed in v0.2

- Upstox read-only V3 history/intraday adapter for AXISBANK, HDFCBANK and ICICIBANK; master-derived identifiers, paise-to-INR ticks, bounded history windows, incomplete-candle exclusion.
- Indian stocks are the default UI/scanner universe. Legacy crypto/forex adapters remain internal for compatibility but are not required.
- Local `.env` loading and Windows setup/start scripts; SQLite by default.
- Local calculation-based explanations; `/explain` no longer calls any external LLM endpoint.
- Research training for Indian stocks at 1m/5m/15m. Outcome labels cannot cross a session or missing interval; large discontinuities are rejected for review. No claim that these guards fully reconcile corporate actions.
- Combined download/train background job, with honest failures and no demonstration data.

## Limits — read before use

This is research software, not the completed production platform. Upstox integration cannot be verified end-to-end until you configure a valid token. REST completed-candle polling is **not** tick-by-tick streaming. Live WebSockets, exchange holiday validation, full corporate-action reconciliation, walk-forward validation and production safeguards remain unfinished. The local explanation engine is not an LLM; a custom LLM is a separate future project.

Indian-stock training is now permitted for **research only**, with the guards above. Its results must not be treated as validated trading recommendations. 1h/daily equity training is blocked because the initial 12-bar intraday strategy must finish within one session. There is no guaranteed accuracy and no trained Indian-stock artifact bundled.

If old stored candles came from Kite, do not mix them with Upstox: use a new `DATA_DIR` for both services. Existing historical records are never rewritten. Default local storage remains `backend/data`.

Training requires sufficient examples of both outcomes in separate chronological partitions. A failed minimum-evidence check is not an installation error. The test suite uses isolated synthetic fixtures only; the running app never does.

## Checks

```bat
cd backend
.venv\Scripts\python -m pytest -q
cd ..\frontend
npm run build
```

Official integration references: [Upstox instruments](https://upstox.com/developer/api-documentation/instruments/), [V3 history](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/), [V3 intraday](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/), [read-only token](https://upstox.com/developer/api-documentation/analytics-token/).

The `docs/` files retain the detailed original research protocol and scope tracker; their v0.2 notes supersede older v0.1 integration descriptions. Optional Docker files remain for users who prefer containers, but are not necessary for this workflow. Lightweight Charts attribution remains enabled.
