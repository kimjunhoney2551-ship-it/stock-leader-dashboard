// Run the exact published dashboard calculator against saved source data.
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'docs/rules.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const ids={};
const context={
 document:{getElementById:id=>ids[id]||(ids[id]={value:id==='filter'?'complete':id==='sort'?'lower':'',addEventListener(){}})},
 fetch:async url=>{const p=path.join(root,'docs',String(url).split('?')[0]);return {ok:fs.existsSync(p),json:async()=>JSON.parse(fs.readFileSync(p,'utf8'))};},
 console,setTimeout,
 __onScoresReady({data,items}){
   if(process.env.EXPORT_INPUTS)fs.writeFileSync(process.env.EXPORT_INPUTS,JSON.stringify({market_session:data.market_session,fx_krw_usd:data.fx_krw_usd,rows:data.rows}));
   const counts={};for(const x of items)counts[x.status]=(counts[x.status]||0)+1;
   const chosen=items.filter(x=>x.baseReady&&(x.missing===0||['watch','pass','shadow'].includes(x.status))).sort((a,b)=>b.low-a.low);
   const rows=chosen.map(x=>({ticker:x.r.ticker,name:x.r.name,sector:x.r.sector,market_cap_krw:x.r.market_cap_usd*data.fx_krw_usd,
     status:x.status,comp_score:x.missing===0?x.low:null,comp_lower:x.low,comp_upper:x.up,f_score:x.f,f_known:x.fKnown,f_lower:x.fKnownScore,f_upper:x.fKnownScore+4-x.fKnown,
     composite:x.composite,rs1m:x.rs1,rs3m:x.rs3,beta:x.r.beta,financial_period:x.r.fy_comparison_period,financial_basis:x.r.financial_basis,financial_source:x.r.fy_comparison_source,revenue_growth_pct:x.r.revenue_growth_pct,gpm_delta_pp:x.r.gpm_delta_pp,sga_ratio_delta_pp:x.r.sga_ratio_delta_pp,asset_turnover_delta:x.r.asset_turnover_delta,
     institution_report:x.r.inst_holder_report_asof||null,institution_comparison:x.r.inst_change_prev_asof||null,institution_change_pct:x.r.inst_change_pct??null,institution_matched_holders:x.r.inst_change_sample_holders??null,institution_source:x.r.inst_change_source||null,filings_13dg:x.r.ownership_evidence?.filings_13dg||[],
     missing_comp:x.missing,components:x.components}));
   const out={price_asof:data.market_session,generated_at_utc:new Date().toISOString(),method:'Approved 12 weekly rank mean minus population SD; 90-day verified positive 13D/G events. Price date and latest disclosures differ. Financial percentiles use available base-universe inputs. Missing inputs stay bounded.',
     base_count:items.filter(x=>x.baseReady).length,base_f_complete:items.filter(x=>x.baseReady&&x.f!==null).length,base_operating_income_complete:items.filter(x=>x.baseReady&&Number.isFinite(x.r.op_income_growth_pct)).length,counts,comp_complete:items.filter(x=>x.baseReady&&x.missing===0).length,both_complete:items.filter(x=>x.baseReady&&x.missing===0&&x.f!==null).length,f_complete:items.filter(x=>x.f!==null).length,f4_candidates:items.filter(x=>x.f===4&&['watch','pass','shadow'].includes(x.status)).length,rows};
   fs.writeFileSync(path.join(root,'docs/data/screen_results.json'),JSON.stringify(out,null,2)+'\n');
   const columns=['ticker','name','sector','market_cap_krw','status','comp_score','comp_lower','comp_upper','f_score','f_lower','f_upper','composite','rs1m','rs3m','beta','financial_period','financial_basis','financial_source','revenue_growth_pct','gpm_delta_pp','sga_ratio_delta_pp','asset_turnover_delta','institution_report','institution_comparison','institution_change_pct','institution_matched_holders','institution_source','missing_comp'];
   const esc=v=>v==null?'':'"'+String(v).replace(/"/g,'""')+'"';
   fs.writeFileSync(path.join(root,'docs/data/screen_results.csv'),'\ufeff'+[columns,...rows.map(r=>columns.map(c=>r[c]))].map(r=>r.map(esc).join(',')).join('\r\n'));
   console.log(JSON.stringify({counts,comp_complete:items.filter(x=>x.baseReady&&x.missing===0).length,both_complete:items.filter(x=>x.baseReady&&x.missing===0&&x.f!==null).length,f_complete:out.f_complete,f4_candidates:out.f4_candidates,top:rows.slice(0,12).map(r=>({ticker:r.ticker,comp_lower:r.comp_lower,comp_upper:r.comp_upper,f:r.f_score,composite:r.composite}))}));
 }
};
vm.runInNewContext(script,context,{timeout:15000});
