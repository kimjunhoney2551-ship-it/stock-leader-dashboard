#!/usr/bin/env python3
"""Latest *disclosed* institutional holdings, separate from stock-price as-of dates.

Data: Yahoo Finance top institutional holders. This is a sampled subset, NOT all
institutions. Never substitute the institution-held LEVEL for the quarter-over-
quarter CHANGE used by the five-point COMP smart-money component.
"""
from __future__ import annotations
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, date, timezone
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"docs"/"data"
CACHE=DATA/"institutional.json"
LATEST=DATA/"latest.json"
HISTORICAL=DATA/"snapshots"/"2026-10-09.json"
SOURCE="Yahoo Finance institutional_holders (top-holder matched sample, NOT all 13F filings)"

def numeric(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError,OverflowError):
        return None

def quarter(s):
    d=date.fromisoformat(s)
    return f"{d.year}Q{(d.month-1)//3+1}"

def normalize_holders(frame,now=None):
    """One latest-per-manager disclosure; split into report-date quarters."""
    if not isinstance(frame,pd.DataFrame) or frame.empty:
        return {}
    columns={str(x).strip().lower().replace(" ","").replace("_",""):x for x in frame.columns}
    holder_col=columns.get("holder")
    shares_col=columns.get("shares")
    date_col=columns.get("datereported")
    if not all(x is not None for x in (holder_col,shares_col,date_col)):
        return {}
    today=now or datetime.now(timezone.utc).date()
    groups={}
    for _,r in frame.iterrows():
        holder=re.sub(r"\s+"," ",str(r[holder_col]).strip().lower())
        shares=numeric(r[shares_col])
        moment=pd.to_datetime(r[date_col],errors="coerce",utc=True)
        if not holder or holder in ("nan","none") or shares is None or shares<=0 or pd.isna(moment):
            continue
        reported=moment.date()
        if reported>today or (today-reported).days>550:
            continue
        key=quarter(reported.isoformat())
        slot=groups.setdefault(key,{})
        old=slot.get(holder)
        if old is None or old["date"]<reported.isoformat():
            slot[holder]={"date":reported.isoformat(),"shares":int(shares)}
    result={}
    for q,members in groups.items():
        if len(members)<4:
            continue
        reported=max(x["date"] for x in members.values())
        result[q]={"report_asof":reported,"holders":{name:x["shares"] for name,x in members.items()}}
    return result

def matched_change(history):
    """Use matched managers from two distinct quarters to avoid survivorship bias."""
    periods=sorted(history.keys(),reverse=True)
    if len(periods)<2:
        return {}
    curr=history[periods[0]]
    prev=history[periods[1]]
    try:
        gap=(date.fromisoformat(curr["report_asof"])-date.fromisoformat(prev["report_asof"])).days
    except (ValueError,KeyError):
        return {}
    if gap<45 or gap>220:
        return {}
    newer=curr.get("holders",{})
    older=prev.get("holders",{})
    common=set(newer)&set(older)
    # Avoid a distorted comparison when only one or two returning holders remain.
    if len(common)<4 or len(common)/max(1,min(len(newer),len(older)))<0.6:
        return {}
    before=sum(older[x] for x in common)
    after=sum(newer[x] for x in common)
    if before<=0:
        return {}
    value=100*(after/before-1)
    if not math.isfinite(value):
        return {}
    return {
        "inst_change_pct":round(value,4),
        "inst_change_asof":curr["report_asof"],
        "inst_change_prev_asof":prev["report_asof"],
        "inst_change_sample_holders":len(common),
        "inst_change_method":"matched_top_institutions_proxy",
        "inst_change_source":SOURCE,
    }

def update_ticker(previous, raw, timestamp):
    """Keep good historical snapshots even when the current provider request fails."""
    periods=normalize_holders(raw)
    if not periods:
        return previous,False
    entry=dict(previous or {})
    history=dict(entry.get("history") or {})
    for p,data in periods.items():
        old=history.get(p)
        # Keep most recent observation for a reporting quarter.
        if old is None or data["report_asof"]>=old.get("report_asof",""):
            history[p]=data
    history={key:history[key] for key in sorted(history,reverse=True)[:4]}
    top=history[sorted(history,reverse=True)[0]]
    entry.update({
        "history":history,
        "inst_holder_report_asof":top["report_asof"],
        "inst_holder_fetched_at_utc":timestamp,
        "inst_holder_sample_count":len(top["holders"]),
        "inst_holder_sample_shares":sum(top["holders"].values()),
        "inst_holder_source":SOURCE,
    })
    change=matched_change(history)
    for key in ("inst_change_pct","inst_change_asof","inst_change_prev_asof",
                "inst_change_sample_holders","inst_change_method","inst_change_source"):
        entry.pop(key,None)
    entry.update(change)
    return entry,True

OWNERSHIP_FIELDS=(
    "inst_holder_report_asof","inst_holder_fetched_at_utc","inst_holder_sample_count",
    "inst_holder_sample_shares","inst_holder_source",
    "inst_change_pct","inst_change_asof","inst_change_prev_asof",
    "inst_change_sample_holders","inst_change_method","inst_change_source"
)

def enrich_row(row,cache):
    entry=cache.get(row.get("ticker"))
    if not isinstance(entry,dict):
        return row
    # User-supplied file data are separate; this function is only called on
    # machine-produced JSON rows. Institution score is filled only when matched.
    for key in OWNERSHIP_FIELDS:
        if key in entry:
            row[key]=entry[key]
        elif key in row and row.get("inst_change_method")=="matched_top_institutions_proxy":
            row.pop(key,None)
    return row

def load_cache():
    try:
        d=json.loads(CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d,dict) and isinstance(d.get("tickers"),dict) else {"version":1,"cursor":0,"tickers":{}}
    except (ValueError,OSError):
        return {"version":1,"cursor":0,"tickers":{}}

def inject_file(path,cache):
    if not path.exists():
        return False
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return False
    rows=obj.get("rows",[])
    if not rows:
        return False
    for row in rows:
        enrich_row(row,cache)
    count=sum(1 for r in rows if r.get("inst_holder_report_asof"))
    changes=sum(1 for r in rows if numeric(r.get("inst_change_pct")) is not None)
    obj["institution_latest_disclosure_count"]=count
    obj["institution_comparable_change_count"]=changes
    obj["institution_data_policy"]="Latest fetched quarterly top-manager report even when price_asof=2026-10-09. Institution CHANGE is a matched-holder proxy; no value is imputed."
    obj["institution_data_source"]=SOURCE
    # JS checks generated_at_utc to detect whether a remote refresh is new.
    obj["generated_at_utc"]=datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    return True

def collect(cache,priorities=None):
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("yfinance is required") from e
    universe_file=ROOT/"config"/"universe.csv"
    if not universe_file.exists():
        print("No universe.csv yet; ownership collection waits for price universe",flush=True)
        return cache
    import csv
    with universe_file.open(encoding="utf-8-sig",newline="") as fh:
        all_symbols=sorted(set(row["ticker"].strip().upper() for row in csv.DictReader(fh) if row.get("ticker")))
    if not all_symbols:
        return cache
    cap=max(1,min(500,int(os.getenv("OWNERSHIP_PER_RUN","120"))))
    cursor=int(cache.get("cursor") or 0)%len(all_symbols)
    batch=(all_symbols+all_symbols)[cursor:cursor+cap]
    priority=priorities or os.getenv("OWNERSHIP_PRIORITY_TICKERS","").split(",")
    # Optional high-priority symbols are included in this run, but the cursor
    # progresses through every listed ticker irrespective of their priority.
    special=[s.strip().upper() for s in priority if s.strip().upper() in all_symbols]
    batch=list(dict.fromkeys(special+batch))
    fetched=0
    failures=0
    stamp=datetime.now(timezone.utc).isoformat()
    started=time.monotonic()
    for tick in batch:
        if time.monotonic()-started>float(os.getenv("OWNERSHIP_MAX_SECONDS","900")):
            print("Time budget reached, stopping safely.",flush=True)
            break
        try:
            df=yf.Ticker(tick.replace(".","-")).get_institutional_holders()
            entry,valid=update_ticker(cache["tickers"].get(tick),df,stamp)
            if valid:
                cache["tickers"][tick]=entry
                fetched+=1
            else:
                failures+=1
        except Exception as e:
            failures+=1
            if failures<=10:
                print(tick,type(e).__name__,str(e)[:150],flush=True)
        time.sleep(max(0.0,float(os.getenv("OWNERSHIP_PAUSE_SEC","0.35"))))
    # Move by every attempted position in the rotating slice; no permanent A-first bias.
    cache["cursor"]=(cursor+min(cap,len(all_symbols)))%len(all_symbols)
    cache["last_attempt_utc"]=datetime.now(timezone.utc).isoformat()
    cache["last_batch_symbols"]=len(batch)
    cache["last_batch_success"]=fetched
    cache["last_batch_missing_or_failed"]=failures
    print(f"Ownership sample: {fetched} valid of {len(batch)}, cached {len(cache['tickers'])}/{len(all_symbols)}",flush=True)
    return cache

def main():
    cache=load_cache()
    cache=collect(cache)
    DATA.mkdir(parents=True,exist_ok=True)
    CACHE.write_text(json.dumps(cache,ensure_ascii=False,allow_nan=False,separators=(",",":"))+"\n",encoding="utf-8")
    for dest in (LATEST,HISTORICAL):
        if inject_file(dest,cache["tickers"]):
            print("Enriched",dest,flush=True)
    print("Finished; incomplete institutional change is left unscored.",flush=True)

if __name__=="__main__":
    main()
