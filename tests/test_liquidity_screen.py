import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import liquidity_screen


def bars(start="2026-09-01", end="2026-10-09", daily_close=10, daily_volume=1_000_000):
    ind=pd.bdate_range(start,end)
    return pd.DataFrame({"Close":[float(daily_close)]*len(ind),
                         "High":[daily_close*1.01]*len(ind),
                         "Low":[daily_close*.99]*len(ind),
                         "Volume":[daily_volume]*len(ind)},index=ind)


def market_symbol_frame(data,sym):
    return data[sym] if isinstance(data.columns,pd.MultiIndex) and sym in data.columns.get_level_values(0) else None


class TestLiquidityPrefilter(unittest.TestCase):
    def test_10_day_average_usd_and_session(self):
        frame=bars(daily_close=20,daily_volume=250000)
        self.assertEqual(liquidity_screen.average_traded_dollars(frame,date(2026,10,9)),5_000_000)
        self.assertIsNone(liquidity_screen.average_traded_dollars(frame,date(2026,10,12)))
        self.assertIsNone(liquidity_screen.average_traded_dollars(frame.iloc[-7:],date(2026,10,9)))

    def test_fast_screen_only_backfills_passers(self):
        recent={
            "SPY":bars(daily_close=500,daily_volume=100000),
            "LIQD":bars(daily_close=25,daily_volume=400000),
            "ILLIQ":bars(daily_close=1,daily_volume=80000),
        }
        long_index=pd.bdate_range(end="2026-10-09",periods=280)
        def long_df(x):
            return pd.DataFrame({"Close":[x]*len(long_index),"High":[x*1.01]*len(long_index),
                                 "Low":[x*.99]*len(long_index),"Volume":[1_000_000]*len(long_index)},index=long_index)
        requests=[]
        def mock_download(*,tickers,start,end,**kwargs):
            symbols=tickers.split()
            requests.append((symbols,start,end))
            result={}
            for sym in symbols:
                result[sym]=long_df(25 if sym=="LIQD" else 500) if start.startswith("2025") else recent[sym]
            return pd.concat(result,axis=1)
        with patch.object(liquidity_screen,"load",return_value={}),\
             patch.object(liquidity_screen,"persist",return_value=3),\
             patch.object(liquidity_screen.yf,"download",side_effect=mock_download),\
             patch.object(liquidity_screen.time,"sleep",return_value=None):
            full,liquidity,meta=liquidity_screen.daily_refresh(
                ["SPY","LIQD","ILLIQ"],date(2026,10,9),[],market_symbol_frame)
        self.assertEqual(meta["screen_liquidity_pass"],1)
        self.assertEqual(meta["screen_liquidity_reject"],1)
        self.assertEqual(meta["screen_liquidity_pending"],0)
        self.assertEqual(meta["screen_long_backfill"],2) # SPY + LIQD
        self.assertNotIn("ILLIQ",full)
        self.assertIn("LIQD",full)
        self.assertEqual(liquidity["ILLIQ"],80000)
        self.assertTrue(all("ILLIQ" not in t for t,begin,_ in requests if begin.startswith("2025")))


if __name__=="__main__":
    unittest.main()
