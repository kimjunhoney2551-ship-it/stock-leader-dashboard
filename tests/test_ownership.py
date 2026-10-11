import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from ownership import normalize_holders,update_ticker,matched_change,enrich_row

class InstitutionalTests(unittest.TestCase):
    def setUp(self):
        self.report=pd.DataFrame([
            {"Holder":n,"Shares":s,"Date Reported":"2026-03-31"}
            for n,s in [("Alpha",100),("Beta",200),("Gamma",300),("Delta",400),("Epsilon",500)]
        ]+[
            {"Holder":n,"Shares":s,"Date Reported":"2026-06-30"}
            for n,s in [("Alpha",110),("Beta",220),("Gamma",330),("Delta",440),("Epsilon",550)]
        ])

    def test_latest_disclosure_is_separate_from_market_price(self):
        entry,ok=update_ticker(None,self.report,"2026-10-11T00:01:00+00:00")
        self.assertTrue(ok)
        self.assertEqual(entry["inst_holder_report_asof"],"2026-06-30")
        self.assertEqual(entry["inst_change_prev_asof"],"2026-03-31")
        self.assertAlmostEqual(entry["inst_change_pct"],10)
        self.assertEqual(entry["inst_change_sample_holders"],5)
        row=enrich_row({"ticker":"TEST","price_asof":"2026-10-09"},{"TEST":entry})
        self.assertEqual(row["price_asof"],"2026-10-09")
        self.assertEqual(row["inst_change_asof"],"2026-06-30")

    def test_latest_only_does_not_impute_change_or_zero(self):
        only=self.report[self.report["Date Reported"]=="2026-06-30"].copy()
        entry,ok=update_ticker(None,only,"2026-10-11T00:01:00+00:00")
        self.assertTrue(ok)
        self.assertNotIn("inst_change_pct",entry)
        self.assertNotIn("inst_change_method",entry)

    def test_insufficient_common_holder_does_not_score(self):
        entry,ok=update_ticker(None,self.report,"2026-10-11T00:01:00+00:00")
        entry["history"]["2026Q1"]["holders"]={"Other":123456}
        self.assertEqual(matched_change(entry["history"]),{})

    def test_bad_and_future_date_ignored(self):
        data=self.report.copy()
        data.loc[:,"Date Reported"]="2027-01-01"
        self.assertEqual(normalize_holders(data),{})

    def test_autoscore_removed_when_new_evidence_incomplete(self):
        old={"ticker":"T","inst_change_method":"matched_top_institutions_proxy",
             "inst_change_pct":8,"inst_change_asof":"2026-03-31"}
        entry={"inst_holder_report_asof":"2026-06-30","inst_holder_sample_count":9}
        updated=enrich_row(old,{"T":entry})
        self.assertIsNone(updated.get("inst_change_pct"))
        self.assertIsNone(updated.get("inst_change_asof"))
        self.assertEqual(updated["inst_holder_sample_count"],9)

    def test_empty_provider_keeps_good_cache(self):
        old={"inst_holder_report_asof":"2026-06-30"}
        cached,success=update_ticker(old,None,"2026-10-11T00:01:00+00:00")
        self.assertFalse(success)
        self.assertEqual(cached,old)

if __name__=="__main__":
    unittest.main()
