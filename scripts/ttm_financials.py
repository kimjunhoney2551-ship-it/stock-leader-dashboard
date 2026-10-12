"""SEC reported facts: contiguous TTM vs year-ago TTM; never replace missing with FY."""
import json,os,urllib.request,time,threading,subprocess
from pathlib import Path
from datetime import date,timedelta,datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1]
TODAY=date.today().isoformat()
UA='StockLeaderDashboard/1.0 github.com/kimjunhoney2551-ship-it/stock-leader-dashboard'
lock=threading.Lock();last_request=0
def get(url):
    global last_request
    with lock:
        time.sleep(max(0,.16-(time.monotonic()-last_request)));last_request=time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA}),timeout=45) as r:return json.load(r)
def day(s):return date.fromisoformat(s)
def evidence(f,tag):return {k:f[k] for k in ['start','end','val','filed','accn','form'] if k in f}|{'tag':tag}
def facts(tax,tag):
    vals=tax.get(tag,{}).get('units',{}).get('USD',[]);unique={}
    for f in sorted(vals,key=lambda x:x.get('filed','')):
        if f.get('filed','9999')>TODAY or f.get('end','9999')>TODAY:continue
        if f.get('form') not in ['10-Q','10-Q/A','10-K','10-K/A','20-F','20-F/A','40-F','6-K']:continue
        unique[(f.get('start'),f['end'])]=f
    return list(unique.values())
def intervals(tax,tag):
    vals=[f for f in facts(tax,tag) if f.get('start') and 50<=(day(f['end'])-day(f['start'])).days<=380]
    edges={}
    for f in vals:
        edges[(f['start'],(day(f['end'])+timedelta(days=1)).isoformat())]=(f['val'],[evidence(f,tag)])
    # Derive standalone quarters from cumulative YTD/FY of exactly the same fiscal start.
    groups={}
    for f in vals:groups.setdefault(f['start'],[]).append(f)
    for group in groups.values():
        for a in group:
            for b in group:
                delta=(day(b['end'])-day(a['end'])).days
                if 50<=delta<=300:
                    key=((day(a['end'])+timedelta(days=1)).isoformat(),(day(b['end'])+timedelta(days=1)).isoformat())
                    if key not in edges:edges[key]=(b['val']-a['val'],[dict(evidence(b,tag),coefficient=1),dict(evidence(a,tag),coefficient=-1)])
    return edges
def total(edges,start,end):
    stop=(day(end)+timedelta(days=1)).isoformat();memo={}
    def visit(s):
        if s==stop:return (0,[],0)
        if s in memo:return memo[s]
        choices=[]
        for (a,b),(v,e) in edges.items():
            if a==s and s<b<=stop:
                tail=visit(b)
                if tail:choices.append((v+tail[0],e+tail[1],tail[2]+1))
        memo[s]=min(choices,key=lambda x:(x[2],len(x[1]))) if choices else None
        return memo[s]
    return visit(start)
TAGS={'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet','RevenueFromContractWithCustomerIncludingAssessedTax'],
      'gross_profit':['GrossProfit'],'cost':['CostOfRevenue','CostOfGoodsAndServicesSold','CostOfGoodsSold'],
      'sga':['SellingGeneralAndAdministrativeExpense'],'operating_income':['OperatingIncomeLoss']}
def normalize(doc):
    tax=doc.get('facts',{}).get('us-gaap',{});revfacts=[f for tag in TAGS['revenue'] for f in facts(tax,tag) if f.get('start')]
    if not revfacts:return {'error':'No standard US-GAAP revenue duration facts; issuer-specific or IFRS extraction required'}
    end=max(f['end'] for f in revfacts)
    # Select matching fiscal endpoints, supporting 52/53-week reporting calendars.
    ends=sorted(set(f['end'] for f in revfacts))
    def prev(e):
        options=[x for x in ends if 350<=(day(e)-day(x)).days<=380]
        return min(options,key=lambda x:abs((day(e)-day(x)).days-365)) if options else None
    prevend=prev(end);oldend=prev(prevend) if prevend else None
    if not oldend:return {'error':'Missing year-ago fiscal endpoints','ttm_end':end}
    periods=[((day(prevend)+timedelta(days=1)).isoformat(),end),((day(oldend)+timedelta(days=1)).isoformat(),prevend)]
    out={'ttm_end':end,'previous_ttm_end':prevend,'ttm_start':periods[0][0],'previous_ttm_start':periods[1][0],'financial_basis':'TTM_YOY','raw_ttm':{},'evidence':{},'entity_name':doc.get('entityName'),'cik':doc.get('cik')}
    # No silent fallback to older complete quarters when latest quarter lacks an input.
    for key,tags in TAGS.items():
        for tag in tags:
            ed=intervals(tax,tag);pair=[total(ed,*p) for p in periods]
            if all(p is not None for p in pair):
                out['raw_ttm'][key]=[p[0] for p in pair];out['evidence'][key]=[p[1] for p in pair];break
    # SG&A may be reported as separate selling/marketing and general/admin lines.
    if 'sga' not in out['raw_ttm']:
        ga=[total(intervals(tax,'GeneralAndAdministrativeExpense'),*p) for p in periods]
        for tag in ['SellingAndMarketingExpense','SellingExpense']:
            sales=[total(intervals(tax,tag),*p) for p in periods]
            if all(x is not None for x in ga+sales):
                out['raw_ttm']['sga']=[ga[i][0]+sales[i][0] for i in [0,1]]
                out['evidence']['sga']=[ga[i][1]+sales[i][1] for i in [0,1]]
                out['sga_method']='GeneralAndAdministrativeExpense + '+tag
                break
    raw=out['raw_ttm'];rev=raw.get('revenue')
    if 'gross_profit' not in raw and rev and 'cost' in raw:
        raw['gross_profit']=[r-c for r,c in zip(rev,raw['cost'])];out['gross_profit_method']='reported revenue minus reported cost of revenue/goods and services; no operating-expense proxy'
    if rev and min(rev)>0:
        out['revenue_growth_pct']=(rev[0]/rev[1]-1)*100
        if 'gross_profit' in raw:out['gpm_delta_pp']=100*(raw['gross_profit'][0]/rev[0]-raw['gross_profit'][1]/rev[1])
        if 'sga' in raw and min(raw['sga'])>=0:out['sga_ratio_delta_pp']=100*(raw['sga'][0]/rev[0]-raw['sga'][1]/rev[1])
        assets={f['end']:f for f in facts(tax,'Assets') if not f.get('start')}
        if all(e in assets for e in [end,prevend,oldend]):
            a=[assets[e]['val'] for e in [end,prevend,oldend]]
            if min(a)>0:
                raw['assets']=a;out['evidence']['assets']=[evidence(assets[e],'Assets') for e in [end,prevend,oldend]]
                out['asset_turnover_delta']=rev[0]/((a[0]+a[1])/2)-rev[1]/((a[1]+a[2])/2)
    if 'operating_income' in raw and raw['operating_income'][1]!=0:
        a,b=raw['operating_income'];out['op_income_growth_pct']=100*(a-b)/abs(b)
    out['f_inputs_complete']=all(k in out for k in ['revenue_growth_pct','gpm_delta_pp','sga_ratio_delta_pp','asset_turnover_delta'])
    out['stale']= (day(TODAY)-day(end)).days>220
    if out['stale']:out['error']='Latest standard revenue facts older than 220 days; not verified latest TTM'
    return out
def fetch(t,cik):
    url=f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json'
    cache=ROOT/'cache/ttm_source_work'/TODAY;cache.mkdir(parents=True,exist_ok=True);fp=cache/(str(cik)+'.json')
    doc=json.loads(fp.read_text()) if fp.exists() else get(url)
    if not fp.exists():fp.write_text(json.dumps(doc,separators=(',',':')))
    row=normalize(doc);row.update(source=url,fetched_at_utc=datetime.now(timezone.utc).isoformat());return t,row
def main():
    subprocess.run(['node','scripts/export_scores.cjs'],cwd=ROOT,env=dict(os.environ,EXPORT_INPUTS='/tmp/ttm-inputs.json'),check=True)
    inp=json.loads(Path('/tmp/ttm-inputs.json').read_text());fx=inp['fx_krw_usd']
    target=[r['ticker'] for r in inp['rows'] if r.get('price_asof')==inp['market_session'] and (r.get('market_cap_usd') or 0)*fx>=5e11 and (r.get('avg_value_usd') or 0)>=5e6 and r.get('beta') is not None and r['beta']<=2]
    if os.getenv('TTM_TICKERS'):target=os.environ['TTM_TICKERS'].split(',')
    priority={r['ticker']:i for i,r in enumerate(json.loads((ROOT/'docs/data/screen_results.json').read_text()).get('rows',[]))}
    target.sort(key=lambda t:priority.get(t,100000))
    mapping_path=ROOT/'cache/sec_tickers.json'
    mapping=json.loads(mapping_path.read_text()) if mapping_path.exists() else get('https://www.sec.gov/files/company_tickers.json')
    mapping_path.write_text(json.dumps(mapping,separators=(',',':'))+'\n')
    by={v['ticker'].replace('-','.'):v['cik_str'] for v in mapping.values()}
    dest=ROOT/'docs/data/financial_ttm.json';doc=json.loads(dest.read_text()) if dest.exists() else {'rows':{}};errors=[]
    original_target_count=len(target)
    target=[t for t in target if doc['rows'].get(t,{}).get('fetched_at_utc','')[:10]!=TODAY] if os.getenv('TTM_REUSE_TODAY') else target
    # Avoid thousands of denied requests on hosted runners; retain sourced cache with a visible refresh error.
    first=next((t for t in target if t.replace('-','.') in by),None)
    if first:
        try:
            t,r=fetch(first,by[first.replace('-','.')]);doc['rows'][t]=r
        except (urllib.error.HTTPError,urllib.error.URLError) as e:
            if getattr(e,'code',None) in [403,429] or '403' in str(e) or '429' in str(e):
                doc['refresh_error']='SEC API access unavailable from this runner: HTTP '+str(e)
                doc['refresh_attempted_at_utc']=datetime.now(timezone.utc).isoformat()
                dest.write_text(json.dumps(doc,separators=(',',':'))+'\n')
                print(doc['refresh_error'],flush=True)
                return
            errors.append({'ticker':first,'error':str(e)})
    doc.pop('refresh_error',None)
    with ThreadPoolExecutor(max_workers=int(os.getenv('TTM_WORKERS','4'))) as pool:
        jobs={pool.submit(fetch,t,by[t.replace('-','.')]):t for t in target if t.replace('-','.') in by}
        for n,f in enumerate(as_completed(jobs),1):
            t=jobs[f]
            try:t,r=f.result();doc['rows'][t]=r
            except Exception as e:errors.append({'ticker':t,'error':str(e)[:200]})
            if n%50==0:
                doc.update(refresh_status='in_progress',processed_count=n,requested_count=original_target_count,errors=errors,queried_at_utc=datetime.now(timezone.utc).isoformat())
                tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(doc,separators=(',',':'))+'\n');tmp.replace(dest)
                print('SEC TTM',n,'/',len(jobs),'errors',len(errors),flush=True)
    doc.update(refresh_status='partial' if errors else 'complete',queried_at_utc=datetime.now(timezone.utc).isoformat(),requested_count=original_target_count,errors=errors,unmapped=[t for t in target if t.replace('-','.') not in by],method='All four F tests: latest contiguous TTM vs matching year-ago TTM; assets average period opening and closing. No FY fallback, missing not zero. SEC standard concepts only; facts with accession numbers retained. Latest filings may be newer than price date.')
    dest.write_text(json.dumps(doc,separators=(',',':'))+'\n');print('TTM complete',sum(r.get('f_inputs_complete',False) and not r.get('stale',False) for r in doc['rows'].values()),'requested',len(target),'errors',len(errors),flush=True)
if __name__=='__main__':main()
