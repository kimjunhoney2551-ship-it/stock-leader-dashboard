"""Collect SEC-derived tracked-holder comparisons; no missing-value imputation."""
import json, urllib.request, time, concurrent.futures
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/data/ownership_verified.json'
def get(path):
    req=urllib.request.Request('https://tradefilings.com/api/v1/'+path,headers={'User-Agent':'StockResearchDashboard/1.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=60) as r: return json.load(r)
        except Exception:
            if attempt==2: raise
            time.sleep(2+attempt*3)
def collect(t):
    result={'ticker':t,'source_url':'https://tradefilings.com/stock/'+t,'fetched_at_utc':datetime.now(timezone.utc).isoformat()}
    try:
        h=get('stock/'+t+'/ownership'); result['provider_meta']=h['meta']
        periods=sorted({r['period'] for r in h['data'] if r.get('period')})
        if len(periods)>=2:
            prev,cur=periods[-2:]
            gap=(datetime.fromisoformat(cur)-datetime.fromisoformat(prev)).days
            if not 80<=gap<=100: raise ValueError('Latest available periods are not consecutive quarters')
            a=get('stock/'+t+'/holders?period='+prev)['data']; b=get('stock/'+t+'/holders?period='+cur)['data']
            def by_cik(rows):
                out={}
                for r in rows:
                    if r.get('cik') and isinstance(r.get('shares'),(int,float)) and r['shares']>0:
                        if str(r['cik']) in out: raise ValueError('Duplicate CIK requires share-class review')
                        out[str(r['cik'])]=r
                return out
            aa,bb=by_cik(a),by_cik(b); common=sorted(aa.keys()&bb.keys()); pairs=[]
            for cik in common:
                pairs.append({'cik':cik,'name':bb[cik]['name'],'previous':{k:aa[cik].get(k) for k in ['shares','filed','source_url']},'current':{k:bb[cik].get(k) for k in ['shares','filed','source_url']}})
            ps=sum(aa[k]['shares'] for k in common); cs=sum(bb[k]['shares'] for k in common)
            coverage=len(common)/min(len(aa),len(bb)) if aa and bb else 0
            result.update(previous_period=prev,current_period=cur,matched_holders=pairs,previous_shares=ps,current_shares=cs,matched_coverage=coverage,previous_holder_count=len(aa),current_holder_count=len(bb))
            # Broad sample, same positive holders in both periods. New/exited holders excluded.
            if len(common)>=4 and coverage>=0.6 and ps>0:
                result.update(inst_change_pct=(cs/ps-1)*100,inst_change_asof=cur,inst_change_prev_asof=prev,inst_change_sample_holders=len(common),inst_change_method='matched_tracked_institutions',inst_change_source=result['source_url'])
        result['filings_13dg']=get('13dg?ticker='+t+'&limit=100')['data']
    except Exception as e: result['error']=str(e)
    return result
if __name__=='__main__':
    rows=json.loads((ROOT/'docs/data/screen_results.json').read_text())['rows']
    targets=[r['ticker'] for r in sorted(rows,key=lambda r:r.get('f_score')!=4)]
    doc=json.loads(OUT.read_text()) if OUT.exists() else {'tickers':{}}
    today=datetime.now(timezone.utc).date().isoformat()
    todo=[t for t in targets if doc['tickers'].get(t,{}).get('fetched_at_utc','')[:10]!=today or doc['tickers'].get(t,{}).get('error')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for r in pool.map(collect,todo):
            doc['tickers'][r['ticker']]=r
            doc['queried_at_utc']=datetime.now(timezone.utc).isoformat()
            doc['method']='Change in summed shares of identical CIK holders with positive holdings in both latest available quarters; excludes new/exited holders and untracked managers. Not total market institutional ownership. 13D/G search results are evidence only; no automatic event scoring without defined lookback.'
            doc['attribution']='Source: U.S. SEC EDGAR filings, compiled by TradeFilings (https://tradefilings.com). Research and information only — not investment advice. 13F data is reported up to 45 days after quarter end and shows only reportable U.S. long positions; totals are reported 13F values, not AUM. Records may be revised. https://tradefilings.com/api/terms'
            OUT.write_text(json.dumps(doc,ensure_ascii=False,separators=(',',':'))+'\n')
            print(r['ticker'],r.get('inst_change_pct'),len(r.get('filings_13dg',[])),r.get('error',''),flush=True)
