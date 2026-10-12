"""Confirmed 2026-10-12 policy: 90-calendar-day qualifying positive 13D/G events."""
import json
from pathlib import Path
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1]
def score(entry,asof):
    if not isinstance(entry.get('filings_13dg'),list):return {'score':None,'reason':'filing search unavailable'}
    floor=(datetime.fromisoformat(asof)-timedelta(days=90)).date().isoformat();groups={};evidence=[]
    for f in entry['filings_13dg']:
        if f.get('filed','9999')<=asof and not f.get('superseded_by'):
            groups.setdefault(str(f.get('filer_cik') or f.get('filer')),[]).append(f)
    for events in groups.values():
        events.sort(key=lambda f:(f['filed'],f['accession']),reverse=True);f=events[0]
        if f['filed']<floor:continue
        form=f.get('form','').upper();shares=f.get('shares');pct=f.get('pct_owned');qual=False;reason='increase not confirmed'
        if '/A' not in form and form in ['SC 13D','SC 13G'] and ((shares or 0)>0 or (pct or 0)>0):
            qual=pct is None or pct>=5;reason='initial beneficial ownership report' if qual else 'initial report below 5%'
        elif '/A' in form and len(events)>1:
            prev=events[1];ps=prev.get('shares');pp=prev.get('pct_owned')
            # Require a real share increase; a percentage increase caused solely by buybacks does not qualify.
            qual=shares is not None and ps is not None and shares>ps and (pct is None or pp is None or pct>=pp) and (pct is None or pct>=5)
            reason='amendment: confirmed share increase' if qual else 'amendment: no confirmed increase or below 5%'
        points=(3 if '13D' in form else 2) if qual else 0
        evidence.append({'accession':f['accession'],'filed':f['filed'],'form':form,'filer':f.get('filer'),'score':points,'reason':reason,'source_url':f['source_url']})
    return {'score':max([e['score'] for e in evidence],default=0),'asof':asof,'window_start':floor,'evidence':evidence,'reason':'Latest filing per filer controls; zero means no qualifying verified positive event in searched records, not proof that no SEC filing exists.'}
def main():
    doc=json.loads((ROOT/'docs/data/ownership_verified.json').read_text());asof=datetime.now(timezone.utc).date().isoformat()
    out={'asof':asof,'window_days':90,'method':'Maximum 13D=3 / 13G=2; latest filing per filer must be initial positive >=5% where known, or confirmed share-increase amendment. Decreases and unverifiable amendments do not qualify. Successful empty search scores 0; unavailable search stays null.','rows':{t:score(e,asof) for t,e in doc['tickers'].items()}}
    (ROOT/'docs/data/filing_scores.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
    print('13DG score complete',sum(r['score'] is not None for r in out['rows'].values()),'positive',sum((r['score'] or 0)>0 for r in out['rows'].values()))
if __name__=='__main__':main()
