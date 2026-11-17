from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import math
import numpy as np
import pandas as pd

FEATURES = ['return1','return5','return20','volatility','rsi','ema_distance','atr_fraction','volume_ratio','breakout_distance']
HORIZON = 12
VERSION = 'long-breakout-v2-session-purged'

def features(frame):
    d = frame.copy()
    c = d.close
    d['return1'] = c.pct_change()
    d['return5'] = c.pct_change(5)
    d['return20'] = c.pct_change(20)
    d['volatility'] = d.return1.rolling(20).std()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    down = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d['rsi'] = (100 - 100 / (1 + up / down.replace(0, np.nan))).where(down != 0, 100).where((up+down) != 0, 50)
    d['ema20'] = c.ewm(span=20, adjust=False, min_periods=20).mean()
    d['ema50'] = c.ewm(span=50, adjust=False, min_periods=50).mean()
    d['ema_distance'] = c / d.ema20 - 1
    tr = pd.concat([d.high-d.low, (d.high-c.shift()).abs(), (d.low-c.shift()).abs()], axis=1).max(axis=1)
    d['atr'] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    d['atr_fraction'] = d.atr/c
    d['volume_ratio'] = d.volume / d.volume.rolling(20).mean().replace(0,np.nan)
    d['resistance'] = d.high.rolling(20).max()
    d['support'] = d.low.rolling(20).min()
    d['breakout_distance'] = d.resistance/c - 1
    d['sma20'] = c.rolling(20).mean()
    d['bb_upper'] = d.sma20 + 2*c.rolling(20).std()
    d['bb_lower'] = d.sma20 - 2*c.rolling(20).std()
    d['macd'] = c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean()
    return d.replace([np.inf,-np.inf],np.nan)

def rounded(v, tick):
    return float((Decimal(str(v))/Decimal(str(tick))).quantize(Decimal('1'),rounding=ROUND_HALF_UP)*Decimal(str(tick)))

def plan(row, tick):
    entry = rounded(row.resistance + tick, tick)
    return {'direction':'LONG','entry':entry,'stop':rounded(entry-1.5*row.atr,tick),'target':rounded(entry+3*row.atr,tick)}

def outcome(bars, p, cost_bps=15):
    """Stop entry valid for first bar only. Gap above entry => unfilled.

    Conservatively count a stop touched on entry bar even if sequencing is unknown.
    Expiry is a non-success label, with its actual marked-to-market P&L.
    """
    first = bars.iloc[0]
    if first.open > p['entry'] or first.high < p['entry']:
        return None
    for offset, (_, b) in enumerate(bars.iterrows()):
        if b.low <= p['stop']:
            price = min(p['stop'], b.open) if offset else p['stop']
            event = 'stop'
        elif b.high >= p['target']:
            price, event = p['target'], 'target'
        elif offset == len(bars)-1:
            price, event = b.close, 'expired'
        else:
            continue
        net = (price-p['entry'])/p['entry'] - cost_bps/10000 * (1+price/p['entry'])
        return {'label':int(event=='target'), 'event':event, 'net_return':float(net), 'bars':offset+1,'exit':float(price)}

def dataset(d, tick):
    examples, unfilled = [], 0
    for i in range(50,len(d)-HORIZON):
        row = d.iloc[i]
        if 'session' in d.columns:
            window=d.iloc[i:i+1+HORIZON]
            if window.session.nunique()!=1 or (window.time.diff().dropna()!=d.attrs.get('step')).any():
                continue
        if row[FEATURES].isna().any() or row.atr <= 0:
            continue
        p = plan(row,tick)
        if p['stop']<=0 or not p['stop']<p['entry']<p['target']:
            continue
        out = outcome(d.iloc[i+1:i+1+HORIZON],p)
        if out is None:
            unfilled += 1
            continue
        examples.append({'index':i,'time':float(row.time), 'label_end':i+HORIZON, 'x':row[FEATURES].to_numpy(dtype=float), **out})
    return examples, unfilled

def risk(entry, stop, target, direction, equity, risk_pct, tick, lot, cost_bps=15, fx=1, multiplier=1):
    numbers = [entry,stop,target,equity,risk_pct,tick,lot,cost_bps,fx,multiplier]
    if not all(math.isfinite(x) for x in numbers) or min(entry,stop,target,equity,tick,lot,fx,multiplier)<=0 or not 0<risk_pct<=3 or not 0<=cost_bps<=1000:
        raise ValueError('Use positive finite inputs, risk above 0 and at most 3%, and costs from 0–1000 bps per side.')
    if direction not in ('LONG','SHORT'):
        raise ValueError('Direction must be LONG or SHORT')
    entry,stop,target = (rounded(x,tick) for x in (entry,stop,target))
    sign = 1 if direction=='LONG' else -1
    loss, gain = sign*(entry-stop),sign*(target-entry)
    if min(loss,gain)<=0:
        raise ValueError('LONG requires stop < entry < target; SHORT requires target < entry < stop, after tick rounding.')
    budget = equity*risk_pct/100
    loss_unit = (loss+(entry+stop)*cost_bps/10000)*multiplier*fx
    gain_unit = (gain-(entry+target)*cost_bps/10000)*multiplier*fx
    # No leverage: cap notional including entry fees at account equity.
    units = min(budget/loss_unit,equity/(entry*(1+cost_bps/10000)*multiplier*fx))
    size = float((Decimal(str(units))/Decimal(str(lot))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(lot)))
    return {'label':'User scenario', 'direction':direction,'entry':entry,'stop':stop,'target':target,'quantity':size,'risk_budget':budget,'estimated_loss':size*loss_unit,'estimated_profit':size*gain_unit,'account_risk_pct':size*loss_unit/equity*100,'price_gain_pct':gain/entry*100,'price_loss_pct':loss/entry*100,'reward_risk':gain/loss,'net_reward_risk':gain_unit/loss_unit,'cost_bps_per_side':cost_bps,'fx':fx,'multiplier':multiplier,'probability':None,'assumptions':'No leverage. Fixed cost/slippage allowance per side. Gaps can exceed planned loss.'}
