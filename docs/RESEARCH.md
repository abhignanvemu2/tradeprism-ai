> **v0.2 update:** See the root README for current setup. Indian stocks now use Upstox; local explanations replace the LLM endpoint. Windows startup and root .env loading are implemented. Intraday equity research training is permitted with session/gap and discontinuity guards, but corporate-action reconciliation remains unverified. Upstox authentication, real-data training and browser interactions still need end-to-end verification. Older v0.1 descriptions below are retained as historical scope context.

# Research protocol v1

This is a research protocol implemented in `quant.py` and `ml.py`, not evidence of actual market performance.

## Defined target

Long-only 20-bar breakout. At completed bar `t`, entry is the 20-bar highest high plus one provider tick. Stop is 1.5 ATR below entry, target 3 ATR above entry. Values are tick-rounded. The stop entry is valid only on bar `t+1`: if that bar opens above entry or never reaches entry, mark unfilled and exclude it from the conditional-outcome classifier.

For filled examples, success means target before stop within the next 12 bars. If neither barrier is touched, expire at the last close; the classification label is failure, while P&L uses the actual exit close. If both barriers occur in one candle, stop wins. On later bars an adverse gap fills at the open beyond the stop. On the entry bar, a stop touch counts conservatively at the stop even though intrabar ordering is unknown.

## Features and costs

Forward-only returns, rolling volatility, RSI, EMA distance, ATR fraction, relative volume and distance to the rolling high. No centered windows or future candles. Feature schema is stored with the artifact. Volume means the selected provider's volume; the UI labels forex update counts.

Research evaluation assumes 15 bps per side inclusive of a fee/slippage allowance, applied to actual entry and exit notionals. It does not claim to reproduce real spread histories, financing, borrow costs, queue position or market impact. Predictions describe the barrier event, not the probability of a net profit after arbitrary user changes.

## Evaluation boundaries

Chronological 55/15/15/15 split: training, model selection, calibration, final holdout. Each partition excludes examples whose full label horizon crosses its right boundary. Selection compares logistic regression with gradient-boosted trees using Brier score. Sigmoid calibration uses a separate partition. Fixed 0.60 probability threshold is selected before final-test evaluation.

Final performance removes overlapping positions and reports denominator, net win rate, Wilson 95% interval, average win/loss, expectancy, profit factor (undefined when no losses), drawdown, expiry count and a full-notional research equity curve. This is not a risk-sized account curve or forward paper performance. Probability calibration bins use all final filled examples; strategy metrics use threshold-selected, non-overlapping examples.

The same raw-data/strategy/tick hash reuses its saved model/report instead of rerunning the final test. Different dataset hashes may still contain overlapping test dates; no new independence claim is made. Walk-forward validation and a durable holdout-governance registry are not implemented. Multiple testing and survivorship limitations remain.

## Inference and paper scenarios

Inference uses the saved transformations/model/calibrator. It is always labeled research. There is no threshold-based actionable BUY/SELL release. The API's default is NO TRADE; WATCH indicates available fresh research only.

Practice replay disables predictive inference and only computes features from candles up to the replay timestamp. It never presents retrospectively trained outputs as unbiased historical predictions.

User scenarios have their own immutable records and no inherited model probability. They are stop-entry scenarios valid on the first full bar opening after submission. They are separate from the next-bar research strategy because live timing is not yet reconciled. A gap beyond entry cancels. Forward fills advance when new real completed bars are ingested; no open-page polling means no automatic new ingestion in this version. Missing bars and incomplete exchange calendars limit simulation reliability; these results are not broker execution simulations.

## No 70% claim

Above-70% accuracy is only an eventual research objective. No percentage is prefilled in the app. No real-market model was trained in the build environment; only an isolated synthetic test validates the mechanics of training and serialization. Those test artifacts are never shipped or loaded by the application.
