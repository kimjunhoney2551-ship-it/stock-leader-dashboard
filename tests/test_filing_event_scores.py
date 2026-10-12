import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from filing_event_scores import score

def event(form,date,shares,pct=6,acc='1'):
    return dict(form=form,filed=date,shares=shares,pct_owned=pct,accession=acc,filer_cik=1,filer='Example',source_url='https://www.sec.gov/Archives/example')
class FilingScores(unittest.TestCase):
    def test_later_reduction_cancels_earlier_initial_credit(self):
        events=[event('SC 13D','2026-09-01',100),event('SC 13D/A','2026-09-20',90,5.4,'2')]
        self.assertEqual(score({'filings_13dg':events},'2026-10-12')['score'],0)
    def test_verified_increase_gets_credit(self):
        events=[event('SC 13G','2026-06-01',100),event('SC 13G/A','2026-09-20',120,7.2,'2')]
        self.assertEqual(score({'filings_13dg':events},'2026-10-12')['score'],2)
    def test_empty_search_differs_from_failed_search(self):
        self.assertEqual(score({'filings_13dg':[]},'2026-10-12')['score'],0)
        self.assertIsNone(score({},'2026-10-12')['score'])
    def test_future_and_old_events_excluded(self):
        events=[event('SC 13D','2026-01-01',100),event('SC 13D','2026-10-13',150,8,'2')]
        self.assertEqual(score({'filings_13dg':events},'2026-10-12')['score'],0)
if __name__=='__main__':unittest.main()
