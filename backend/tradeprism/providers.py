"""Only provider-returned observations enter the application database."""
import csv
import io
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
import numpy as np

SECONDS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '1d': 86400}
REGISTRY = {
    'AXISBANK': {'provider': 'upstox', 'venue': 'NSE', 'asset': 'equity', 'currency': 'INR', 'zone': 'Asia/Kolkata'},
    'HDFCBANK': {'provider': 'upstox', 'venue': 'NSE', 'asset': 'equity', 'currency': 'INR', 'zone': 'Asia/Kolkata'},
    'ICICIBANK': {'provider': 'upstox', 'venue': 'NSE', 'asset': 'equity', 'currency': 'INR', 'zone': 'Asia/Kolkata'},
    'BTC-USD': {'provider': 'coinbase', 'venue': 'Coinbase Exchange', 'asset': 'crypto spot', 'currency': 'USD', 'zone': 'UTC'},
    'ETH-USD': {'provider': 'coinbase', 'venue': 'Coinbase Exchange', 'asset': 'crypto spot', 'currency': 'USD', 'zone': 'UTC'},
    'EUR_USD': {'provider': 'oanda', 'venue': 'OANDA', 'asset': 'forex', 'currency': 'USD', 'zone': 'America/New_York'},
}

class DataUnavailable(ValueError):
    pass

def request(url, headers=None, params=None, raw=False):
    for attempt in range(3):
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                r = client.get(url, headers=headers, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            if r.status_code != 200:
                raise DataUnavailable(f'Provider returned HTTP {r.status_code}; check access, entitlement and connectivity.')
            return r.text if raw else r.json()
        except (httpx.RequestError, ValueError) as e:
            if isinstance(e, DataUnavailable):
                raise
            if attempt == 2:
                raise DataUnavailable('Provider connection or response failed; no substitute data used.') from e
            time.sleep(2 ** attempt)

def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()

def timestamp(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()

def validate(rows, end):
    result = {}
    for row in rows:
        t, o, h, l, c, v = map(float, row)
        if not np.isfinite([t, o, h, l, c, v]).all() or min(o, h, l, c) <= 0 or v < 0 or l > min(o, c) or h < max(o, c) or l > h:
            raise DataUnavailable('Invalid OHLCV data; ingestion rejected.')
        if t >= end:
            continue
        if t in result and result[t] != [t, o, h, l, c, v]:
            raise DataUnavailable('Conflicting duplicate candles; ingestion rejected.')
        result[t] = [t, o, h, l, c, v]
    return sorted(result.values())

def fetch(symbol, tf, count=1800):
    if symbol not in REGISTRY or tf not in SECONDS:
        raise DataUnavailable('Unsupported instrument or timeframe')
    meta = dict(REGISTRY[symbol])
    step = SECONDS[tf]
    end = int(time.time() // step * step)
    rows = []
    if meta['provider'] == 'upstox':
        from .upstox import fetch_upstox
        return fetch_upstox(symbol, tf, count, request, validate)
    if meta['provider'] == 'coinbase':
        root = 'https://api.exchange.coinbase.com'
        product = request(f'{root}/products/{symbol}')
        meta.update(tick=float(product['quote_increment']), lot=float(product['base_increment']), volume_type='venue base-asset volume', adjustment='unadjusted spot', short_allowed=False)
        cursor = end
        for _ in range((count + 279) // 280):
            start = cursor - step * 280
            data = request(f'{root}/products/{symbol}/candles', params={'granularity': step, 'start': iso(start), 'end': iso(cursor)})
            rows.extend([r[0], r[3], r[2], r[1], r[4], r[5]] for r in data if start <= r[0] < cursor)
            cursor = start
            time.sleep(.35)
    elif meta['provider'] == 'kite':
        key, token = os.getenv('KITE_API_KEY'), os.getenv('KITE_ACCESS_TOKEN')
        if not key or not token:
            raise DataUnavailable('Kite API key and current access token required for NSE data.')
        headers = {'X-Kite-Version': '3', 'Authorization': f'token {key}:{token}'}
        instruments = csv.DictReader(io.StringIO(request('https://api.kite.trade/instruments/NSE', headers, raw=True)))
        found = next((x for x in instruments if x['tradingsymbol'] == symbol and x['instrument_type'] == 'EQ'), None)
        if not found:
            raise DataUnavailable('Instrument is absent from the current NSE registry.')
        meta.update(tick=float(found['tick_size']), lot=float(found['lot_size']), provider_id=found['instrument_token'], volume_type='exchange traded volume', adjustment='provider history; corporate-action consistency unverified', short_allowed=False)
        interval = {'1m': 'minute', '5m': '5minute', '15m': '15minute', '1h': '60minute', '1d': 'day'}[tf]
        # Small chunks obey historical window limits; overlap is deduplicated.
        days = min(5000, max(30, int(count * step / 22500 * 1.5))) if tf != '1d' else min(5000, count * 2)
        cursor = time.time()
        start = cursor - days * 86400
        while cursor > start:
            left = max(start, cursor - (100 if tf == '1d' else 30) * 86400)
            fmt = lambda t: datetime.fromtimestamp(t, ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')
            data = request(f"https://api.kite.trade/instruments/historical/{found['instrument_token']}/{interval}", headers, {'from': fmt(left), 'to': fmt(cursor)})
            rows.extend([timestamp(r[0]), *r[1:6]] for r in data['data']['candles'])
            cursor = left - 1
            time.sleep(.4)
        # Daily session candles are not UTC-midnight candles. Exclude today's bar.
        if tf == '1d':
            end = datetime.now(ZoneInfo('Asia/Kolkata')).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        else:
            end = time.time() - step
    else:
        token, account = os.getenv('OANDA_TOKEN'), os.getenv('OANDA_ACCOUNT_ID')
        if not token or not account:
            raise DataUnavailable('OANDA token and account ID required for forex data.')
        mode = os.getenv('OANDA_ENV', 'practice')
        if mode not in ('practice', 'live'):
            raise DataUnavailable('OANDA_ENV must be practice or live')
        root = 'https://api-fxpractice.oanda.com' if mode == 'practice' else 'https://api-fxtrade.oanda.com'
        headers = {'Authorization': f'Bearer {token}'}
        inst = request(f'{root}/v3/accounts/{account}/instruments', headers, {'instruments': symbol})['instruments'][0]
        meta.update(tick=10 ** -int(inst['displayPrecision']), lot=10 ** -int(inst['tradeUnitsPrecision']), volume_type='provider price-update count (tick volume)', adjustment='midpoint prices', short_allowed=True, environment=mode)
        data = request(f'{root}/v3/accounts/{account}/instruments/{symbol}/candles', headers, {'count': min(count, 5000), 'granularity': {'1m':'M1','5m':'M5','15m':'M15','1h':'H1','1d':'D'}[tf], 'price':'M'})
        rows = [[timestamp(x['time']), *[float(x['mid'][k]) for k in ('o','h','l','c')], x['volume']] for x in data['candles'] if x['complete']]
        end = time.time()
    rows = validate(rows, end)[-count:]
    if not rows:
        raise DataUnavailable('Provider returned no completed candles.')
    meta.update(symbol=symbol, timeframe=tf, source=meta['provider'], fetched_at=time.time(), first=rows[0][0], last=rows[-1][0], count=len(rows), delay='not independently verified; completed historical bars only')
    # Continuous-market gaps are observable. Session-aware equity/FX gap checks are pending.
    meta['missing_intervals'] = sum(max(0, round((b[0]-a[0])/step)-1) for a,b in zip(rows,rows[1:])) if meta['provider']=='coinbase' else None
    return rows, meta
