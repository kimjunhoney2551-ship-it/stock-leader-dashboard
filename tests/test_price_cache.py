import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import price_cache


def make_frame(start="2025-01-01",n=280,base=10.0):
    dates=pd.bdate_range(start,periods=n)
    return pd.DataFrame({
        "Close":[base+i*0.01 for i in range(n)],
        "High":[base+i*0.01+0.2 for i in range(n)],
        "Low":[base+i*0.01-0.2 for i in range(n)],
        "Volume":[100000+i for i in range(n)]
    },index=dates)


class CacheTests(unittest.TestCase):
    def test_keep_285_daily_observations(self):
        original=make_frame(n=360)
        saved=price_cache.from_frame(original)
        self.assertEqual(len(saved),285)
        restored=price_cache.to_frame(saved)
        self.assertEqual(len(restored),285)
        self.assertEqual(restored.index[-1],original.index[-1])
        self.assertAlmostEqual(restored.Close.iloc[-1],original.Close.iloc[-1])

    def test_delta_overrides_overlapping_market_days(self):
        original=make_frame(n=270)
        recent=make_frame(start=str(original.index[-7].date()),n=8,base=90)
        combined=price_cache.update_frame(original,recent)
        self.assertEqual(len(combined),271)
        self.assertEqual(float(combined.loc[recent.index[-8],"Close"]),90)
        self.assertEqual(combined.index[-1],recent.index[-1])

    def test_compressed_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(price_cache,"CACHE_DIR",Path(folder)):
                bars=price_cache.from_frame(make_frame(n=285))
                self.assertEqual(price_cache.persist({"AAPL":bars,"ZBRA":bars}),2)
                got=price_cache.load()
                self.assertEqual(set(got),{"AAPL","ZBRA"})
                self.assertEqual(len(got["AAPL"]),285)
                self.assertTrue(Path(folder,"A.json.gz").exists())

    def test_no_fake_data_created(self):
        self.assertIsNone(price_cache.to_frame([]))
        self.assertEqual(price_cache.from_frame(None),[])


if __name__=="__main__":
    unittest.main()
