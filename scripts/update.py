#!/usr/bin/env python3
"""US exchange-listed equity snapshot; supports an explicitly date-pinned historical run.
This collector cannot by itself validate institutional 13D/13G, historical shares, or full COMP.
"""
import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# Institution disclosures are fetched separately, may be newer than historical prices.
from ownership import load_cache, enrich_row
from price_cache import load as load_price_cache, to_frame, from_frame, update_frame, persist as persist_price_cache

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"docs"/"data"
UNIVERSE=ROOT/"config"/"universe.csv"
BASE_URL="https://www.nasdaqtrader.com/dynamic/symdir/"
REGEX=re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,13}$")
NON_STOCK=re.compile(
    r"\b(?:ETF|ETN|ETP|exchange.traded|warrants?|rights to|subscription rights?|"
    r"preferred|preference shares?|depositary shares representing preferred|"
    r"senior notes?|subordinated notes?|notes due|debentures?|bonds? due|"
    r"closed.end funds?|mutual funds?|units? (?:consisting|each consisting|comprising))\b",re.I)
SECTORS={"Technology":"정보기술","Communication Services":"커뮤니케이션",
"Consumer Cyclical":"경기소비재","Consumer Defensive":"필수소비재","Energy":"에너지",
"Financial Services":"금융","Healthcare":"헬스케어","Industrials":"산업재",
"Basic Materials":"소재","Real Estate":"부동산","Utilities":"유틸리티"}
LOOKBACK={"ret_1w":5,"ret_1m":21,"ret_3m":63,"ret_4w":20,
"ret_12w":60,"ret_25w":125,"ret_52w":252}

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None

def directory(name):
    err=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(BASE_URL+name,headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=45) as response:
                data=response.read(5000000)
            s=data.decode("utf-8-sig",errors="replace")
            if "File Creation Time:" not in s or "<html" in s[:500].lower():
                raise ValueError("Nasdaq Trader response not a complete symbol directory")
            return s
        except Exception as ex:
            err=ex
            time.sleep(1+attempt*2)
    raise RuntimeError("Cannot download "+name+": "+str(err))

def discover():
    output={}
    for source in ("nasdaqlisted.txt","otherlisted.txt"):
        rows=list(csv.DictReader(io.StringIO(directory(source)),delimiter="|"))
        count=0
        for r in rows:
            if r.get("Test Issue")!="N" or r.get("ETF","N")=="Y":
                continue
            name=(r.get("Security Name") or "").strip()
            if not name or NON_STOCK.search(name):
                continue
            if source=="nasdaqlisted.txt":
                sym=(r.get("Symbol") or "").upper().strip()
                exchange="NASDAQ"
            else:
                code=(r.get("Exchange") or "").strip()
                if code not in {"A","N","P","Z","V"}:
                    continue
                n=(r.get("NASDAQ Symbol") or "").upper().strip()
                alt=(r.get("ACT Symbol") or "").upper().strip()
                sym=n if REGEX.fullmatch(n) else alt
                exchange={"A":"AMEX","N":"NYSE","P":"NYSE ARCA","Z":"CBOE BZX","V":"IEX"}[code]
            if not REGEX.fullmatch(sym):
                continue
            output.setdefault(sym,{"ticker":sym,"name":name,"exchange":exchange})
            count+=1
        if count<1000:
            raise RuntimeError("Unexpectedly small Nasdaq directory "+source+": "+str(count))
    found=sorted(output.values(),key=lambda r:r["ticker"])
    if len(found)<3000:
        raise RuntimeError("Incomplete universe: "+str(len(found)))
    return found

def symbol_frame(data, ticker):
    if data is None or data.empty:
        return None
    if isinstance(data.columns,pd.MultiIndex):
        a=set(map(str,data.columns.get_level_values(0)))
        b=set(map(str,data.columns.get_level_values(1)))
        if ticker in a:
            out=data[ticker].copy()
        elif ticker in b:
            out=data.xs(ticker,axis=1,level=1).copy()
        else:
            return None
    else:
        out=data.copy()
    return out if {"Close","High","Low","Volume"}.issubset(out.columns) else None

def bars_asof(frame, asof):
    if frame is None or frame.empty:
        return None
    frame=frame.copy()
    idx=pd.to_datetime(frame.index,utc=True).tz_convert(None).normalize()
    frame.index=idx
    frame=frame.loc[frame.index<=pd.Timestamp(asof)]
    return frame if len(frame)>60 else None

def stats(frame):
    if frame is None:
        return {}
    data=frame[["Close","High","Low","Volume"]].apply(pd.to_numeric,errors="coerce")
    data=data.dropna(subset=["Close","Volume"])
    data=data[(data.Close>0)&(data.Volume>=0)]
    if len(data)<61:
        return {}
    c=data.Close
    hi=data.High
    lo=data.Low
    v=data.Volume
    val=num(c.iloc[-1])
    if val is None:
        return {}
    out={"close_usd":val,"price_asof":data.index[-1].date().isoformat()}
    for key,n in LOOKBACK.items():
        if len(c)>n and c.iloc[-n-1]>0:
            out[key]=round(100*(val/c.iloc[-n-1]-1),6)
    if len(hi)>=252:
        maximum=num(hi.iloc[-252:].max())
        if maximum and maximum>0:
            out["high52_gap_pct"]=round(100*(val/maximum-1),5)
    dollars=c*v
    if len(dollars)>=60 and dollars.iloc[-60:].notna().all():
        d10=num(dollars.iloc[-10:].mean())
        d60=num(dollars.iloc[-60:].mean())
        out["avg_value_usd"]=round(d10,2) if d10 is not None else None
        if d10 is not None and d60 and d60>0:
            out["rvol10_60"]=round(d10/d60,7)
    if len(data)>=20:
        spread=(hi-lo).replace(0,np.nan)
        multiplier=((2*c-hi-lo)/spread).fillna(0).iloc[-20:]
        total=num(v.iloc[-20:].sum())
        if total and total>0:
            out["cmf20"]=round(float((multiplier*v.iloc[-20:]).sum())/total,8)
    return {k:x for k,x in out.items() if x is not None}

def beta_asof(equity, benchmark):
    if equity is None or benchmark is None:
        return None
    a=pd.to_numeric(equity["Close"],errors="coerce").pct_change(fill_method=None)
    b=pd.to_numeric(benchmark["Close"],errors="coerce").pct_change(fill_method=None)
    d=pd.concat([a,b],axis=1,join="inner").dropna().tail(252)
    if len(d)<126:
        return None
    variation=float(d.iloc[:,1].var())
    if not variation>0:
        return None
    value=num(d.iloc[:,0].cov(d.iloc[:,1])/variation)
    return round(value,6) if value is not None else None

def fetch_history(symbols,asof,warnings):
    """First run: backfill. Later runs: fetch only last 18 calendar days.

    We retain >252 daily closes/highs/volumes for all observed tickers, so
    historical momentum, rolling highs, beta and CMF remain valid without
    repeatedly downloading over a year of history on every run.
    """
    stored=load_price_cache()
    results={}
    now_stored={}
    jobs={"cached":[],"incremental":[],"bootstrap":[]}
    for sym in symbols:
        prev=to_frame(stored.get(sym))
        if prev is not None and len(prev)>0:
            now_stored[sym]=prev
        last=prev.index[-1].date() if prev is not None and len(prev)>0 else None
        # Reuse a complete cache when generating a past historical snapshot.
        if last is not None and last>=asof and len(prev.loc[prev.index<=pd.Timestamp(asof)])>=61:
            jobs["cached"].append(sym)
            results[sym]=bars_asof(prev,asof)
        elif last is not None and len(prev)>=5 and last>=asof-timedelta(days=14):
            jobs["incremental"].append(sym)
        else:
            jobs["bootstrap"].append(sym)
    print("Price cache:",
          "reused",len(jobs["cached"]),"incremental",len(jobs["incremental"]),
          "backfill",len(jobs["bootstrap"]),flush=True)
    stop=(asof+timedelta(days=1)).isoformat()
    batch=max(5,min(65,int(os.getenv("YF_BATCH_SIZE","35"))))
    pause=float(os.getenv("BATCH_PAUSE_SEC","0.35"))
    done=0
    for mode in ("incremental","bootstrap"):
        list_symbols=jobs[mode]
        start=(asof-timedelta(days=18 if mode=="incremental" else 575)).isoformat()
        for pos in range(0,len(list_symbols),batch):
            chunk=list_symbols[pos:pos+batch]
            forms=[x.replace(".","-") for x in chunk]
            try:
                raw=yf.download(tickers=" ".join(forms),start=start,end=stop,interval="1d",
                    group_by="ticker",auto_adjust=True,progress=False,threads=False,timeout=40)
                for original,alias in zip(chunk,forms):
                    fetched=symbol_frame(raw,alias)
                    # Even a failed provider query leaves older cached data intact.
                    if fetched is not None and not fetched.empty:
                        fetched=fetched.copy()
                        fetched.index=pd.to_datetime(fetched.index,utc=True).tz_convert(None).normalize()
                        now_stored[original]=update_frame(now_stored.get(original),fetched)
                    frame=bars_asof(now_stored.get(original),asof)
                    if frame is not None:
                        results[original]=frame
            except Exception as ex:
                if len(warnings)<40:
                    warnings.append("price "+mode+" batch "+str(pos)+" failed: "+type(ex).__name__)
                for original in chunk:
                    frame=bars_asof(now_stored.get(original),asof)
                    if frame is not None:
                        results[original]=frame
            done+=len(chunk)
            print("Price cache sync",mode,done,"/",len(symbols),
                  "valid frames",len(results),flush=True)
            time.sleep(pause)
    # Keep a fully validated, bounded 285-session cache; save even for symbols
    # missing today's quote so subsequent dates can retry only missing deltas.
    packed={ticker:from_frame(frame) for ticker,frame in now_stored.items()
            if frame is not None and len(frame)>0}
    cached_count=persist_price_cache(packed)
    print("Price cache saved",cached_count,"symbols",flush=True)
    return results


def run():
    explicit=os.getenv("ASOF_DATE","").strip()
    if explicit:
        requested=date.fromisoformat(explicit)
        if requested>datetime.now(timezone.utc).date():
            raise ValueError("Future market dates are not permitted")
    else:
        requested=datetime.now(timezone.utc).date()
    historical=bool(explicit)
    directory_rows=discover()
    tickers=[r["ticker"] for r in directory_rows]
    warnings=[]
    limit=int(os.getenv("PRICE_LIMIT","0"))
    observed=tickers if limit<=0 else tickers[:limit]
    price=fetch_history(list(dict.fromkeys(observed+["SPY","KRW=X"])),requested,warnings)
    benchmark=price.get("SPY")
    bench=stats(benchmark)
    session=bench.get("price_asof")
    if not session:
        raise RuntimeError("Cannot verify SPY market session")
    if historical and session!=explicit:
        raise RuntimeError("Pinned close requested "+explicit+" but actual SPY session "+session)
    institutional_cache=load_cache().get('tickers',{})
    outrows=[]
    current=0
    for n,r in enumerate(directory_rows):
        d={"ticker":r["ticker"],"name":r["name"],"exchange":r["exchange"]}
        frame=price.get(r["ticker"])
        st=stats(frame)
        if st and st.get("price_asof")==session:
            d.update(st)
            d["_auto_price_fields"]=[k for k in st if k not in {"price_asof"}]
            d["price_is_current"]=True
            beta=beta_asof(frame,benchmark)
            if beta is not None:
                d["beta"]=beta
            current+=1
        else:
            d["price_is_current"]=False
            d["_auto_price_fields"]=[]
        enrich_row(d,institutional_cache)
        outrows.append(d)
    if current<20:
        raise RuntimeError("Only "+str(current)+" symbols downloaded; aborting incomplete update")
    # Fundamentals are NOT queried in historical mode: today's .info is not point-in-time 2026-10-09.
    metadata_updated=0
    if not historical:
        count=max(0,min(50,int(os.getenv("INFO_PER_RUN","25"))))
        for entry in sorted(outrows,key=lambda x:x["ticker"])[:count]:
            try:
                info=yf.Ticker(entry["ticker"].replace(".","-")).info
                if not isinstance(info,dict):
                    continue
                for key,source in (("market_cap_usd","marketCap"),("forward_pe","forwardPE")):
                    val=num(info.get(source))
                    if val is not None and (key!="market_cap_usd" or val>0):
                        entry[key]=val
                roe=num(info.get("returnOnEquity"))
                if roe is not None:
                    entry["roe_pct"]=100*roe
                sector=info.get("sector")
                if isinstance(sector,str) and sector in SECTORS:
                    entry["sector"]=SECTORS[sector]
                entry["info_asof"]=datetime.now(timezone.utc).date().isoformat()
                metadata_updated+=1
            except Exception as exc:
                if len(warnings)<40:
                    warnings.append("info "+entry["ticker"]+" "+type(exc).__name__)
            time.sleep(0.15)
    mapping={"spy1w":"ret_1w","spy1m":"ret_1m","spy3m":"ret_3m",
       "spy4w":"ret_4w","spy12w":"ret_12w","spy25w":"ret_25w","spy52w":"ret_52w"}
    fx=stats(price.get("KRW=X")).get("close_usd")
    coverage=round(current/len(tickers)*100,2)
    payload={
      "schema_version":1,"generated_at_utc":datetime.now(timezone.utc).isoformat(),
      "market_session":session,"requested_asof":explicit or "LATEST","historical_snapshot":historical,
      "source":"Nasdaq Trader + Yahoo Finance (yfinance, unofficial price history)",
      "universe_scope":"US_LISTED_COMMON_STOCK_AND_ADR",
      "universe_source":"Nasdaq Trader CURRENT symbol directory (NOT point-in-time asof historical)",
      "universe_asof_utc":datetime.now(timezone.utc).date().isoformat(),
      "rank_completeness":"incomplete","current_price_coverage_pct":coverage,
      "current_price_coverage_complete":current==len(tickers),
      "price_updated_count":current,"universe_count":len(tickers),
      "info_updated_count":metadata_updated,"fx_krw_usd":fx,
      "institution_latest_disclosure_count":sum(bool(r.get("inst_holder_report_asof")) for r in outrows),
      "institution_comparable_change_count":sum(r.get("inst_change_pct") is not None for r in outrows),
      "institution_data_policy":"Latest available Yahoo top-institution disclosures, report date separated from price session; changes only for matched top holders across reporting quarters.",
      "sp500_returns":{k:bench[v] for k,v in mapping.items() if v in bench},
      "rows":outrows,"warnings":warnings,
      "notice":"As-of date is for price history only. Universe directory is present-day, not historical. Historic cap/shares/F-score unavailable; current institutional disclosures are an explicitly latest-data, non-point-in-time exception. Sampled holder changes are NOT full institutional ownership changes; no complete COMP can be claimed."
    }
    DATA.mkdir(parents=True,exist_ok=True)
    UNIVERSE.parent.mkdir(parents=True,exist_ok=True)
    with UNIVERSE.open("w",newline="",encoding="utf-8") as fh:
        writer=csv.DictWriter(fh,fieldnames=["ticker","name","exchange"])
        writer.writeheader()
        writer.writerows(directory_rows)
    text=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n"
    if explicit:
        archive=DATA/"snapshots"/(session+".json")
        archive.parent.mkdir(parents=True,exist_ok=True)
        archive.write_text(text,encoding="utf-8")
        # first historical run populates latest, until next daily refresh.
        current_latest=DATA/"latest.json"
        try:
            existing=json.loads(current_latest.read_text(encoding="utf-8"))
        except Exception:
            existing={}
        if not existing.get("price_updated_count"):
            current_latest.write_text(text,encoding="utf-8")
    else:
        (DATA/"latest.json").write_text(text,encoding="utf-8")
    print(json.dumps({"market_session":session,"symbols":len(tickers),"priced":current,
                      "coverage_pct":coverage,"historical":historical},ensure_ascii=False))
if __name__=="__main__":
    try:
        run()
    except Exception as exc:
        print("UPDATE FAILED:",type(exc).__name__,exc,file=sys.stderr)
        sys.exit(1)
