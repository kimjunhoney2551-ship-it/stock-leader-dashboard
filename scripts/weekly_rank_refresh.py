"""User-approved: trailing 12 weekly percentile mean minus population SD."""
import json,os,subprocess,gzip,time
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def main():
    env=dict(os.environ,EXPORT_INPUTS='/tmp/score-inputs.json')
    subprocess.run(['node','scripts/export_scores.cjs'],cwd=ROOT,env=env,check=True)
    doc=json.loads(Path('/tmp/score-inputs.json').read_text());asof=doc['market_session'];fx=doc['fx_krw_usd']
    rows=[r for r in doc['rows'] if r.get('price_asof')==asof and (r.get('market_cap_usd') or 0)*fx>=5e11 and (r.get('avg_value_usd') or 0)>=5e6 and r.get('beta') is not None and r['beta']<=2]
    ticks=[r['ticker'] for r in rows];dates=pd.date_range(end=asof,periods=64,freq='W-FRI');start=(dates[0]-pd.Timedelta(days=7)).date().isoformat();end=(pd.Timestamp(asof)+pd.Timedelta(days=1)).date().isoformat()
    cache=ROOT/'cache/weekly_rank_prices.json.gz';stored={}
    if cache.exists():
        with gzip.open(cache,'rt') as f: stored=json.load(f)
    series={};errors=[]
    for t in ticks:
        if stored.get('asof')==asof and t in stored.get('closes',{}): series[t]=stored['closes'][t]
    todo=[t for t in ticks if t not in series]
    for offset in range(0,len(todo),75):
        batch=todo[offset:offset+75];mapping={t:t.replace('.','-') for t in batch}
        import yfinance as yf
        bars=yf.download(list(mapping.values()),start=start,end=end,auto_adjust=True,threads=6,progress=False,group_by='ticker',timeout=25)
        for t,sym in mapping.items():
            try:
                frame=bars[sym] if isinstance(bars.columns,pd.MultiIndex) else bars
                close=frame['Close'].dropna();close.index=pd.to_datetime(close.index).tz_localize(None)
                weekly=close.resample('W-FRI').last().reindex(dates)
                series[t]=[None if pd.isna(x) else float(x) for x in weekly]
            except Exception as e:errors.append({'ticker':t,'error':str(e)[:100]})
        print('History',min(offset+75,len(todo)),'/',len(todo),flush=True)
        time.sleep(.3)
    with gzip.open(cache,'wt') as f:json.dump({'asof':asof,'dates':[str(d.date()) for d in dates],'closes':series,'source':'Yahoo Finance adjusted closes via yfinance; Friday week-ending last actual trading close'},f,separators=(',',':'))
    frame=pd.DataFrame(series,index=dates);out={t:{'components':{}} for t in ticks};coverage={}
    for horizon,weight in [(4,8),(12,12),(25,12),(52,8)]:
        rets=frame/frame.shift(horizon)-1
        # SPY-relative return subtracts the same benchmark from every name, leaving each weekly rank unchanged.
        last=rets.tail(12);n=last.notna().sum(axis=1);ranks=last.rank(axis=1,method='average').sub(1).div(n.sub(1),axis=0)
        coverage[str(horizon)]={str(d.date()):int(n.loc[d]) for d in last.index}
        for t in ticks:
            vals=ranks[t].dropna() if t in ranks else pd.Series(dtype=float)
            if len(vals)!=12:continue
            avg=float(vals.mean());sd=float(vals.std(ddof=0));factor=max(0,min(1,avg-sd))
            out[t]['components'][str(horizon)]={'score':weight*factor,'weight':weight,'mean_percentile':avg,'population_sd':sd,'weekly_percentiles':[float(v) for v in vals],'observations':12}
    for t,r in out.items():
        r['complete']=len(r['components'])==4
        r['score']=sum(c['score'] for c in r['components'].values()) if r['complete'] else None
    result={'market_session':asof,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'universe_count':len(ticks),'coverage':coverage,'dates':[str(d.date()) for d in dates[-12:]],'method':'Each horizon uses last 12 Friday week-ending return percentiles, midrank ties, on current base-filter universe. Points = weight * clip(mean - population SD,0,1). SPY subtraction leaves cross-sectional rank unchanged. Universe frozen at current filters; not point-in-time backtest. IPOs without all 12 observations stay missing.','rows':out,'errors':errors}
    (ROOT/'docs/data/weekly_ranks.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({'rank_complete':sum(r['complete'] for r in out.values()),'base':len(ticks),'errors':errors}),flush=True)
if __name__=='__main__':main()
