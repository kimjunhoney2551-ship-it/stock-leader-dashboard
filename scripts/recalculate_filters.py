"""30 trading-session dollar volume and 252 daily-return beta, from saved bars."""
import gzip,json,statistics
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
def main():
    doc=json.loads((ROOT/'docs/data/latest.json').read_text());asof=doc['market_session'];bars={}
    for p in (ROOT/'cache/prices').glob('*.json.gz'):
        with gzip.open(p,'rt') as f:bars.update(json.load(f)['symbols'])
    def clean(t):return [r for r in bars.get(t,[]) if r[0]<=asof and r[1]>0]
    def returns(rows):return {b[0]:b[1]/a[1]-1 for a,b in zip(rows,rows[1:])}
    bench=returns(clean('SPY'));out={}
    for row in doc['rows']:
        t=row['ticker'];rows=clean(t);r={'avg_value_usd':None,'beta':None,'filter_price_asof':asof}
        if rows and rows[-1][0]==asof:
            if len(rows)>=30:r['avg_value_usd']=sum(x[1]*x[4] for x in rows[-30:])/30
            rets=returns(rows);dates=sorted(set(rets)&set(bench))[-252:]
            if len(dates)==252:
                a=[rets[d] for d in dates];b=[bench[d] for d in dates];var=statistics.variance(b)
                if var>0:r['beta']=statistics.covariance(a,b)/var
            r['beta_observations']=len(dates)
        out[t]=r
    result={'market_session':asof,'generated_at_utc':datetime.now(timezone.utc).isoformat(),'market_cap_min_krw':500000000000,'method':'30 trading sessions mean close*volume; beta covariance of 252 daily returns / SPY variance. Full 252 observations required. Cached Yahoo adjusted OHLCV. Missing stays null.','rows':out}
    (ROOT/'docs/data/filter_inputs.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print('30-day volume',sum(r['avg_value_usd'] is not None for r in out.values()),'1y beta',sum(r['beta'] is not None for r in out.values()))
if __name__=='__main__':main()
