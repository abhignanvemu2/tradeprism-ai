"""Our deterministic explanation engine. Not an LLM or free-form chatbot."""
from datetime import datetime,timezone

def explain_evidence(a,question=''):
    lines=[f"{a['symbol']} · {a['timeframe']} · {a['state']}."]
    stamp=a.get('data_timestamp')
    if stamp:lines.append(f"Source: {a['source']}. Last candle opened at {datetime.fromtimestamp(stamp,timezone.utc).isoformat()}.")
    indicators=a.get('indicators',{})
    if indicators:
        lines.append(f"Trend: {a.get('trend','unavailable')}, based on EMA 20 versus EMA 50; this alone does not predict a profitable trade.")
        for field,label in [('rsi','RSI'),('atr','ATR'),('support','20-bar low'),('resistance','20-bar high')]:
            if indicators.get(field) is not None:lines.append(f'{label}: {indicators[field]:.4f}.')
    prediction=a.get('prediction',{})
    if prediction.get('probability') is not None:
        lines.append(f"Research probability: {prediction['probability']:.1%}. Target: {prediction['target']} This is not a manual-plan probability or guaranteed win rate.")
    else:lines.append('No supported predictive probability is available.')
    lines.append(f"Decision: {a['decision']}.")
    lines.extend(a.get('reasons',[]))
    lines.append('This engine explains the calculated evidence only. Free-form questions, news claims and a custom LLM are not supported.')
    return {'engine':'deterministic-local-v1','label':'Local calculation-based explanation — not an LLM','summary':'\n\n'.join(lines),'generated_at':a['generated_at'],'evidence':{k:v for k,v in a.items() if k not in ('candles','overlays')}}
