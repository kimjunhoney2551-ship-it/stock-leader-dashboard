"""Latest annual financial comparisons, separate from historical price dates."""
import json, math, os
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/data/financial_latest.json'

def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):
        return None

def normalize(income,balance):
    years=sorted(income.columns,reverse=True)
    if len(years)<2:return {}
    current,previous=years[:2]
    if not 300<=(current-previous).days<=430:return {}
    def read(frame,key,period):
        if key not in frame.index or period not in frame.columns:return None
        return number(frame.loc[key,period])
    out={'financial_period_current':str(current.date()),'financial_period_previous':str(previous.date())}
    rev=[read(income,'Total Revenue',d) for d in (current,previous)]
    gp=[read(income,'Gross Profit',d) for d in (current,previous)]
    sga=[read(income,'Selling General And Administration',d) for d in (current,previous)]
    op=[read(income,'Operating Income',d) for d in (current,previous)]
    if all(v is not None and v>0 for v in rev):
        out['revenue_growth_pct']=100*(rev[0]/rev[1]-1)
        if all(v is not None for v in gp):out['gpm_delta_pp']=100*(gp[0]/rev[0]-gp[1]/rev[1])
        if all(v is not None and v>=0 for v in sga):out['sga_ratio_delta_pp']=100*(sga[0]/rev[0]-sga[1]/rev[1])
        # Annual turnover uses average opening/closing assets for BOTH years.
        earlier=sorted([d for d in balance.columns if 300<=(previous-d).days<=430],reverse=True)
        if earlier:
            assets=[read(balance,'Total Assets',d) for d in (current,previous,earlier[0])]
            if all(v is not None and v>0 for v in assets):
                out['asset_turnover_delta']=rev[0]/((assets[0]+assets[1])/2)-rev[1]/((assets[1]+assets[2])/2)
    if all(v is not None for v in op) and op[1]!=0:
        out['op_income_growth_pct']=100*(op[0]-op[1])/abs(op[1])
    ni=read(income,'Net Income Common Stockholders',current)
    if ni is None:ni=read(income,'Net Income',current)
    eq=[read(balance,'Common Stock Equity',d) for d in (current,previous)]
    if any(v is None for v in eq):eq=[read(balance,'Stockholders Equity',d) for d in (current,previous)]
    if ni is not None and all(v is not None for v in eq) and sum(eq)!=0:
        out['roe_fallback_pct']=ni/(sum(eq)/2)*100
        out['roe_fallback_inputs']={'net_income':ni,'equity_current':eq[0],'equity_previous':eq[1]}
    out['raw_annual']={'revenue':rev,'gross_profit':gp,'sga':sga,'operating_income':op}
    return out

def fetch(ticker):
    stock=yf.Ticker(ticker.replace('.','-'))
    row=normalize(stock.income_stmt,stock.balance_sheet)
    if not row:return ticker,None,'No comparable consecutive annual statements'
    row.update(source='Yahoo Finance annual income statement and balance sheet via yfinance',fetched_at_utc=datetime.now(timezone.utc).isoformat())
    return ticker,row,None

def main():
    targets=json.loads((ROOT/'config/financial_targets.json').read_text())
    try:payload=json.loads(DEST.read_text())
    except (FileNotFoundError,ValueError):payload={'rows':{}}
    errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(fetch,t):t for t in targets}
        for index,future in enumerate(as_completed(jobs),1):
            try:
                ticker,row,error=future.result()
                if row:payload['rows'][ticker]=row
                else:errors.append({'ticker':ticker,'error':error})
            except Exception as error:errors.append({'ticker':jobs[future],'error':str(error)[:150]})
            if index%20==0:print(f'Processed {index}/{len(targets)}; usable {len(payload["rows"])}',flush=True)
    payload.update(queried_at_utc=datetime.now(timezone.utc).isoformat(),requested_count=len(targets),errors=errors,
        period_policy='Latest two consecutive annual income statements and three balance sheets; dates may be later than price date. No missing value is scored as zero.')
    DEST.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
    print(json.dumps({'rows':len(payload['rows']),'errors':len(errors),'f_complete':sum(all(k in r for k in ['revenue_growth_pct','gpm_delta_pp','sga_ratio_delta_pp','asset_turnover_delta']) for r in payload['rows'].values())}),flush=True)

if __name__=='__main__':main()
