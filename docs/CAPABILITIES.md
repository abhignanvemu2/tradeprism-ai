> **v0.2 update:** See the root README for current setup. Indian stocks now use Upstox; local explanations replace the LLM endpoint. Windows startup and root .env loading are implemented. Intraday equity research training is permitted with session/gap and discontinuity guards, but corporate-action reconciliation remains unverified. Upstox authentication, real-data training and browser interactions still need end-to-end verification. Older v0.1 descriptions below are retained as historical scope context.

# Provider and chart capability matrix

Official documentation consulted during implementation, 17 November 2026. Provider documentation establishes interface behavior; it does not establish that a user's account has access or redistribution permission.

## Providers

| Provider | Implemented use | Limits / provenance | Access and commercial caveats |
|---|---|---|---|
| [Kite history](https://kite.trade/docs/connect/v3/historical/) and [registry](https://kite.trade/docs/connect/v3/market-quotes/) | NSE current instrument lookup, OHLCV backfill in chunks | Provider-supported intervals only; token/tick/lot read from current master; daily/open-session handling remains conservative | API key, current access token and history entitlement required. Current pricing and exchange redistribution permission must be confirmed. |
| [Coinbase Exchange candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles) | BTC-USD/ETH-USD completed candles; product tick and quantity increments | Requests capped at 280 buckets below documented per-request limit; bounded retries; venue volume; missing intervals reported | [Public market-data API](https://docs.cdp.coinbase.com/exchange/introduction/welcome) is subject to provider market-data terms. Public does not imply unrestricted redistribution. Build environment received HTTP 403. |
| [OANDA account candles](https://developer.oanda.com/rest-live-v20/pricing-ep/) | EUR_USD midpoint candles with account metadata | Maximum 5,000 per request; current adapter does not paginate larger requests; price-update count is not global volume | Token/account required; practice by default. User/account jurisdiction and pricing are not verified. |

No international-equity adapter, corporate-action feed, economic calendar, news feed or tick streaming is implemented. No service subscriptions were purchased. Cost estimates would be speculative until the chosen account plans and deployment size are known.

## Charting choice

Use [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/) for licensed chart rendering with independent provider acquisition. Its [plugin interface](https://tradingview.github.io/lightweight-charts/docs/plugins/intro) allows custom overlays, but it does not automatically provide a complete drawing/workspace application. Attribution remains visible. [Advanced Charts](https://www.tradingview.com/charting-library-docs/latest/) is a different product with separate access/licensing; it is not bundled.

| Requested feature | Native support used | Custom work implemented | Remaining limitation / external access |
|---|---|---|---|
| Candles, line, bars, area | Lightweight Charts series | Type selector | None at basic rendering level; browser QA pending. |
| Pan, zoom, crosshair | Chart/time/price scale APIs | OHLC hover labels, fit button | Browser gesture verification pending. |
| Volume, indicators | Histogram and line series | EMA 20/50 toggle, provider volume labels | Separate indicator panes, configurable periods/styles, instances and presets remain. |
| Manual drawings | Coordinate conversion only | SVG trendline/ray, horizontal/vertical, rectangle, Fibonacci, note, measurement | Drawings use candle-aligned anchors; no full object inspector or free-space anchors. |
| Parallel channel | None | Two parallel lines rendered | Second-line offset is screen-space only; not a complete price-anchored channel tool. |
| Edit, lock, hide, delete | None | Endpoint dragging and selected-object controls | Whole-object dragging and note text editing remain. |
| Undo/redo, persistence | None | Bounded undo/redo; server autosave per owner/instrument | Single workspace per instrument; no layout collection/version conflict resolution. |
| Scenario entry/SL/TP | None | Independent draggable levels and deterministic server recalculation | Long/short position box visuals and multi-target exits remain. |
| AI layer | None | Research/manual modes and structured evidence panel | Current scenario overlay is explicitly user-created; inspectable AI pattern/zone annotations remain. |
| Replay | None | Historical endpoint cutoff, slider and next bar | Practice only; inference disabled; no unbiased historical-model replay. |
| Fullscreen | Browser API | Fullscreen chart container | Needs browser verification. |
| Multi-chart sync | None | Not implemented | Requires custom layout, linking and persistence. |
| Mobile | Responsive CSS | Wrapping controls and single-column workspace | Drawer tool UX and touch interaction QA remain. |

See [acceptance status](ACCEPTANCE.md) before treating this build as feature-complete.
