#!/usr/bin/env python3
"""Persistent, compressed daily OHLCV bars for incremental US equity updates.

Data is split into single-character bucket files to avoid very large Git blobs.
Only numerical OHLCV and dates are persisted; there are no credentials or holdings.
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
CACHE_DIR=ROOT/"cache"/"prices"
FIELDS=("Close","High","Low","Volume")
MAX_BARS=285

def shard(ticker):
    first=ticker[0].upper() if ticker else "_"
    return first if first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" else "_"

def to_frame(rows):
    if not rows:
        return None
    try:
        df=pd.DataFrame(rows,columns=["Date",*FIELDS])
        df["Date"]=pd.to_datetime(df["Date"],format="%Y-%m-%d",errors="raise")
        df=df.set_index("Date").sort_index()
        for field in FIELDS:
            df[field]=pd.to_numeric(df[field],errors="coerce")
        df=df.dropna(subset=["Close","High","Low","Volume"])
        return df.loc[(df.Close>0)&(df.High>0)&(df.Low>0)&(df.Volume>=0)] if not df.empty else None
    except (ValueError,TypeError,KeyError):
        return None

def from_frame(frame):
    if frame is None or len(frame)==0:
        return []
    d=frame.sort_index().loc[:,list(FIELDS)].tail(MAX_BARS)
    entries=[]
    for dt,x in d.iterrows():
        numbers=[float(x[k]) for k in FIELDS]
        if all(math.isfinite(v) for v in numbers):
            entries.append([pd.Timestamp(dt).strftime("%Y-%m-%d"),*numbers])
    return entries

def load():
    result={}
    if not CACHE_DIR.exists():
        return result
    for p in CACHE_DIR.glob("*.json.gz"):
        try:
            with gzip.open(p,"rt",encoding="utf-8") as f:
                data=json.load(f)
            if data.get("schema_version")!=1:
                continue
            for ticker,rows in data.get("symbols",{}).items():
                if isinstance(rows,list):
                    result[ticker]=rows
        except (OSError,ValueError,KeyError,EOFError) as exc:
            print("Invalid cached price shard",p.name,type(exc).__name__,flush=True)
    return result

def update_frame(existing,addition):
    """Latest provider bars override overlapping dates; preserve earlier valid bars."""
    if addition is None or len(addition)==0:
        return existing
    if existing is None or len(existing)==0:
        merged=addition.copy()
    else:
        merged=pd.concat([existing,addition])
        merged=merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged.tail(MAX_BARS)

def persist(rows_by_symbol):
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    groups={}
    for ticker,rows in rows_by_symbol.items():
        if rows:
            groups.setdefault(shard(ticker),{})[ticker]=rows[-MAX_BARS:]
    for bucket,data in groups.items():
        p=CACHE_DIR/(bucket+".json.gz")
        temp=p.with_suffix(".json.gz.tmp")
        obj={"schema_version":1,"symbols":dict(sorted(data.items()))}
        content=json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(",",":"),sort_keys=True).encode("utf-8")
        # gzip mtime=0 ensures deterministic output bytes for unchanged data.
        with temp.open("wb") as fh:
            with gzip.GzipFile(fileobj=fh,mode="wb",mtime=0,filename="") as gz:
                gz.write(content)
        temp.replace(p)
    return sum(len(x) for x in groups.values())
