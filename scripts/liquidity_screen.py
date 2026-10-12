#!/usr/bin/env python3
"""Two-stage price collection: fast 10-day USD turnover first; long history
only for stocks with USD >=5m average daily value.

Works with Yahoo OHLCV, and does not fabricate cap or beta. A ticker for which
the short history cannot be verified remains unclassified/pending.
"""
from __future__ import annotations
from datetime import date,timedelta
import os
import time

import pandas as pd
import yfinance as yf

from price_cache import load,to_frame,from_frame,update_frame,persist

LIQUIDITY_MIN_USD=5_000_000
HISTORY_BARS_REQUIRED=270
SAFE_MIN_DAYS=30

def as_of_frame(frame, market_date):
    if frame is None or frame.empty:
        return None
    out=frame.loc[frame.index<=pd.Timestamp(market_date)]
    return out if not out.empty else None

def average_traded_dollars(frame, asof, min_days=SAFE_MIN_DAYS):
    """Only accept an unbroken latest-market-session sample as verified."""
    frame=as_of_frame(frame,asof)
    if frame is None or len(frame)<min_days:
        return None
    if frame.index[-1].date()!=asof:
        return None
    recent=frame.iloc[-min_days:]
    try:
        prices=pd.to_numeric(recent["Close"],errors="coerce")
        volume=pd.to_numeric(recent["Volume"],errors="coerce")
        if prices.isna().any() or volume.isna().any() or (prices<=0).any() or (volume<0).any():
            return None
        return float((prices*volume).mean())
    except (KeyError,ValueError,TypeError):
        return None

def normalize_fetched(frame,asof):
    if frame is None or frame.empty:
        return None
    frame=frame.copy()
    frame.index=pd.to_datetime(frame.index,utc=True).tz_convert(None).normalize()
    frame=as_of_frame(frame,asof)
    return frame

def daily_refresh(tickers, market_date, warnings, extract_symbol):
    """Return (full_history_by_ticker, current_turnover_by_ticker, metadata).

    Only verified turnover passers are eligible for first-time 575-day backfill.
    Cached 270+session passers need short OHLCV refresh only.
    """
    saved=load()
    frames={t:to_frame(saved.get(t)) for t in tickers}
    batch=max(8,min(80,int(os.getenv("YF_BATCH_SIZE","65"))))
    pause=max(0.0,float(os.getenv("BATCH_PAUSE_SEC","0.2")))
    stop=(market_date+timedelta(days=1)).isoformat()
    calls=0
    error_count=0

    def update_chunks(symbols, start,stage):
        nonlocal calls,error_count
        for pos in range(0,len(symbols),batch):
            chunk=symbols[pos:pos+batch]
            forms=[x.replace(".","-") for x in chunk]
            try:
                raw=yf.download(tickers=" ".join(forms),start=start,end=stop,interval="1d",
                    group_by="ticker",auto_adjust=True,progress=False,threads=False,timeout=40)
                for orig,alias in zip(chunk,forms):
                    fresh=normalize_fetched(extract_symbol(raw,alias),market_date)
                    if fresh is not None:
                        frames[orig]=update_frame(frames.get(orig),fresh)
            except Exception as exc:
                error_count+=1
                if len(warnings)<40:
                    warnings.append(f"{stage} batch {pos}: {type(exc).__name__}")
            calls+=1
            if calls%10==0 or pos+batch>=len(symbols):
                print(stage,"finished",min(pos+batch,len(symbols)),"/",len(symbols),
                      "http calls",calls,flush=True)
            time.sleep(pause)

    # Fetch <=35 calendar-day light history for the entire universe. On later
    # days, cached stocks request <=12 calendar days and missing stocks retry.
    has_cache=[t for t in tickers if frames.get(t) is not None and len(frames[t])>=30]
    have=set(has_cache)
    no_cache=[t for t in tickers if t not in have]
    update_chunks(has_cache,(market_date-timedelta(days=12)).isoformat(),"recent")
    update_chunks(no_cache,(market_date-timedelta(days=55)).isoformat(),"liquidity_probe")

    ref=as_of_frame(frames.get("SPY"),market_date)
    if ref is None:
        raise RuntimeError("SPY short history unavailable; cannot verify market session for liquidity screen")
    session=ref.index[-1].date()
    liquidity={}
    shortlist=[]
    missing=[]
    excluded=[]
    for t in tickers:
        if t in ("SPY","KRW=X"):
            shortlist.append(t)
            continue
        amount=average_traded_dollars(frames.get(t),session)
        if amount is None:
            missing.append(t)
        else:
            liquidity[t]=round(amount,2)
            if amount>=LIQUIDITY_MIN_USD:
                shortlist.append(t)
            else:
                excluded.append(t)

    # Download >1 year OHLCV only for liquid stocks without sufficient cache.
    def incomplete(t):
        hist=as_of_frame(frames.get(t),market_date)
        return hist is None or len(hist)<HISTORY_BARS_REQUIRED
    bootstrap=[t for t in shortlist if incomplete(t)]
    update_chunks(bootstrap,(market_date-timedelta(days=575)).isoformat(),"long_backfill")

    # Keep older price bars for all formerly tracked symbols; do not fake a
    # new quote when a provider fails or an issuer is inactive.
    packed={t:from_frame(fr) for t,fr in frames.items() if fr is not None and len(fr)}
    persist(packed)
    full={t:as_of_frame(frames.get(t),market_date) for t in shortlist
          if frames.get(t) is not None and len(as_of_frame(frames.get(t),market_date))>=61}
    meta={
        "screen_method":"30-session close × volume daily mean; latest SPY market session verified",
        "screen_reference_session":session.isoformat(),
        "screen_min_avg_value_usd":LIQUIDITY_MIN_USD,
        "screen_total":sum(1 for t in tickers if t not in ("SPY","KRW=X")),
        "screen_turnover_verified":len(shortlist)-sum(x in shortlist for x in ("SPY","KRW=X"))+len(excluded),
        "screen_liquidity_pass":len(shortlist)-sum(x in shortlist for x in ("SPY","KRW=X")),
        "screen_liquidity_reject":len(excluded),
        "screen_liquidity_pending":len(missing),
        "screen_long_backfill":len(bootstrap),
        "screen_requests":calls,
        "screen_failed_batches":error_count,
        "screen_long_history_available":len(full)-sum(x in full for x in ("SPY","KRW=X")),
    }
    print("PREFILTER",meta,flush=True)
    return full,liquidity,meta
