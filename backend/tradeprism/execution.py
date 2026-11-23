"""Shared candle-based simulation for training and prospective confirmation."""
ENTRY_BARS=3

def evaluate(bars,plan,entry_time,end_time,step,stamp,cost_bps=15,legacy=False):
    long=plan.get('direction','LONG')=='LONG'; sign=1 if long else -1
    deadline=min(end_time,entry_time+step*(1 if legacy else ENTRY_BARS))
    fill=None; entered_at=None; evidence=[]; expected=entry_time
    def state(event,**extra):
        result={'event':event,'entered':fill is not None,'fill_price':fill,'entered_at':entered_at,
                'entry_deadline':deadline,'checked_through':expected,'candles':evidence,**extra}
        if 'exit' in extra:
            result['net_return']=sign*(extra['exit']-fill)/fill-cost_bps/10000*(1+extra['exit']/fill)
        return result
    for c in bars:
        if c['time']+step>stamp: break
        if abs(c['time']-expected)>.1:
            return state('awaiting_data',reason='Waiting for missing candle/backfill',missing_time=expected)
        evidence.append(c); t=c['time']; expected=t+step
        first_fill=False
        if fill is None:
            if t>=deadline:return state('unfilled',event_time=deadline,reason='Entry was not reached during its entry window')
            gap=c['open']>plan['entry'] if long else c['open']<plan['entry']
            crossed=c['high']>=plan['entry'] if long else c['low']<=plan['entry']
            if legacy and (gap or not crossed):return state('unfilled',event_time=expected,reason='Legacy one-bar entry rule; gap entries excluded')
            if crossed:
                price=max(c['open'],plan['entry']) if long else min(c['open'],plan['entry'])
                beyond=price>=plan['target'] if long else price<=plan['target']
                if beyond:return state('unfilled',event_time=expected,reason='Opening gap was already beyond the target')
                fill=price; entered_at=t; first_fill=True
            elif expected>=deadline:return state('unfilled',event_time=expected,reason='Entry was not reached during its entry window')
            else:continue
        stop=c['low']<=plan['stop'] if long else c['high']>=plan['stop']
        target=c['high']>=plan['target'] if long else c['low']<=plan['target']
        if stop:
            price=plan['stop'] if first_fill else (min(c['open'],plan['stop']) if long else max(c['open'],plan['stop']))
            return state('stop',exit=price,event_time=expected,ambiguous=bool(target),reason='Conservative stop-first rule if candle sequencing is unknown')
        if target:return state('target',exit=plan['target'],event_time=expected)
        if expected>=end_time:return state('expired',exit=c['close'],event_time=expected)
    if stamp>=expected+step+30 and expected<end_time:
        return state('awaiting_data',reason='Waiting for a completed provider candle',missing_time=expected)
    return state('open' if fill is not None else 'waiting_entry')

TERMINAL={'target','stop','expired','unfilled','data_gap','invalidated'}
