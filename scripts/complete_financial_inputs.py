"""Expand annual comparisons to the entire base-filter universe, with accounting-derived fallbacks."""
import os,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
import yfinance as yf
from financial_refresh import normalize,number
ROOT=Path(__file__).resolve().parents[1]
def fetch(t):
    stock=yf.Ticker(t.replace('.','-'));inc=stock.income_stmt;bal=stock.balance_sheet
    row=normalize(inc,bal)
    if not row:return t,None
    years=sorted(inc.columns,reverse=True);cur,prev=years[:2]
    def read(df,key,d):
        return number(df.loc[key,d]) if key in df.index and d in df.columns else None
    op=[]
    for d in [cur,prev]:
        x=read(inc,'Operating Income',d)
        if x is None:
            rev,expense=read(inc,'Total Revenue',d),read(inc,'Operating Expense',d)
            if rev is not None and expense is not None:x=rev-expense
        op.append(x)
    if all(x is not None for x in op) and op[1]!=0:
        row['op_income_growth_pct']=(op[0]-op[1])/abs(op[1])*100
        row['op_income_growth_method']='(current - previous) / abs(previous); operating income, or reported revenue minus operating expense'
    ni=read(inc,'Net Income Common Stockholders',cur)
    if ni is None:ni=read(inc,'Net Income',cur)
    eq=[read(bal,'Common Stock Equity',d) for d in [cur,prev]]
    if any(x is None for x in eq):eq=[read(bal,'Stockholders Equity',d) for d in [cur,prev]]
    if ni is not None and all(x is not None for x in eq) and sum(eq)!=0:
        row['roe_fallback_pct']=ni/(sum(eq)/2)*100
        row['roe_fallback_inputs']={'net_income':ni,'equity_current':eq[0],'equity_previous':eq[1]}
    row.update(source='Yahoo Finance annual income statement and balance sheet via yfinance',fetched_at_utc=datetime.now(timezone.utc).isoformat())
    return t,row
if __name__=='__main__':
    subprocess.run(['node','scripts/export_scores.cjs'],cwd=ROOT,env=dict(os.environ,EXPORT_INPUTS='/tmp/score-inputs.json'),check=True)
    inp=json.loads(Path('/tmp/score-inputs.json').read_text());fx=inp['fx_krw_usd']
    targets=[r['ticker'] for r in inp['rows'] if r.get('price_asof')==inp['market_session'] and (r.get('market_cap_usd') or 0)*fx>=5e11 and (r.get('avg_value_usd') or 0)>=5e6 and r.get('beta') is not None and r['beta']<=2]
    path=ROOT/'docs/data/financial_latest.json';doc=json.loads(path.read_text());errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch,t):t for t in targets}
        for n,f in enumerate(as_completed(jobs),1):
            try:
                t,r=f.result()
                if r:doc['rows'][t]=r
                else:errors.append({'ticker':t,'error':'No consecutive annual statements'})
            except Exception as e:errors.append({'ticker':jobs[f],'error':str(e)[:120]})
            if n%100==0:print('Financials',n,'/',len(targets),flush=True)
    doc.update(queried_at_utc=datetime.now(timezone.utc).isoformat(),requested_count=len(targets),errors=errors)
    path.write_text(json.dumps(doc,separators=(',',':'))+'\n')
    print('Financial rows',len(doc['rows']),'errors',len(errors),flush=True)
