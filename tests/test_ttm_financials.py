import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ttm_financials import intervals,total,normalize
class TTMTests(unittest.TestCase):
    def test_ytd_difference_and_contiguous_ttm(self):
        def f(s,e,v):return {'start':s,'end':e,'val':v,'filed':'2026-08-01','form':'10-Q','accn':'test'}
        tax={'Revenues':{'units':{'USD':[f('2025-01-01','2025-06-30',40),f('2025-01-01','2025-09-30',70),f('2025-01-01','2025-12-31',110),f('2026-01-01','2026-06-30',60)]}}}
        result=total(intervals(tax,'Revenues'),'2025-07-01','2026-06-30')
        self.assertEqual(result[0],130)
        self.assertIsNone(total(intervals(tax,'Revenues'),'2024-07-01','2025-06-30'))
    def test_latest_missing_never_backfilled_with_annual_score(self):
        tax={'Revenues':{'units':{'USD':[{'start':'2026-01-01','end':'2026-06-30','val':10,'filed':'2026-08-01','form':'10-Q'}]}}}
        result=normalize({'facts':{'us-gaap':tax}})
        self.assertIn('error',result)
        self.assertNotIn('sga_ratio_delta_pp',result)
if __name__=='__main__':unittest.main()
