"""Additional equity research guards; no claim of corporate-action verification."""
import pandas as pd
from .providers import SECONDS

def research_frame(frame,meta,tf):
    if meta['asset']!='equity':return frame
    if meta.get('stock_group') and meta['stock_group'] not in ('EQ','A','B','X'):
        raise ValueError('This stock group requires settlement/session review; the current intraday training strategy is not enabled for it. Prices and charts remain available.')
    if tf not in ('5m','15m'):
        raise ValueError('Indian-stock research currently supports 5m or 15m only, with outcomes inside one session.')
    d=frame.copy()
    if d.empty:raise ValueError('Download genuine history first.')
    # A large discontinuity is not proof of a split. Partition every such boundary,
    # reset rolling features there, and never label a trade across it.
    ratios=d.open/d.close.shift()
    breaks=(ratios-1).abs().gt(.20)
    d['segment']=breaks.cumsum()
    d.attrs['discontinuities']=[{'time':float(d.iloc[i].time),'ratio':float(ratios.iloc[i]),
        'possible_split_or_bonus':bool(any(abs(ratios.iloc[i]-r)<.025 for r in (.5,1/3,.25,.2,.1,2,3,4,5,10)))}
        for i in range(len(d)) if breaks.iloc[i]]
    local=pd.to_datetime(d.time,unit='s',utc=True).dt.tz_convert('Asia/Kolkata')
    minutes=local.dt.hour*60+local.dt.minute
    if ((minutes<555)|(minutes>=930)).any():
        raise ValueError('Nonstandard session candles require review before training.')
    d['session']=local.dt.strftime('%Y-%m-%d')
    d.attrs['step']=SECONDS[tf]
    return d
