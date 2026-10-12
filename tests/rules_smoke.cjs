// Node-only browser-emulation smoke test for the public rules dashboard.
// Uses latest real published snapshot; no fabricated passers or third-party requests.
const fs=require("fs");
const vm=require("vm");
const assert=require("assert");
const html=fs.readFileSync("docs/rules.html","utf8");
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert(scripts.length===1,"Expected one standalone dashboard script");
new vm.Script(scripts[0][1],{filename:"rules.js"});
const snapshot=JSON.parse(fs.readFileSync("docs/data/latest.json","utf8"));
const tv=JSON.parse(fs.readFileSync("docs/data/tradingview_latest.json","utf8"));
assert(tv.rows&&tv.completed===true,"TradingView snapshot not complete");
const fy=JSON.parse(fs.readFileSync("docs/data/tradingview_financial_history_priority.json","utf8"));
assert(Object.keys(fy.rows).length>=16,"FY historical finance samples missing");

assert(Array.isArray(snapshot.rows),"Invalid market snapshot");
const financials=JSON.parse(fs.readFileSync("docs/data/financial_latest.json","utf8"));
const institutions=JSON.parse(fs.readFileSync("docs/data/institutional.json","utf8"));
const ids={};
const get=(id)=>ids[id]||(ids[id]={
  id,value:id==="filter"?"complete":id==="sort"?"lower":"",
  textContent:"",innerHTML:"",disabled:false,
  listeners:{},addEventListener(kind,fn){this.listeners[kind]=fn;}
});
const ctx={
 document:{getElementById:get},
 fetch:async(url)=>{const p='docs/'+String(url).split('?')[0].replace(/^\.\//,'');return {ok:fs.existsSync(p),json:async()=>JSON.parse(fs.readFileSync(p,'utf8'))};},
 __onScoresReady({items}){for(const x of items){if(x.status==='pass'){assert(x.missing===0&&x.f===4&&x.low>=80&&x.r.weekly_rank.complete,'Invalid confirmed passer');assert(x.r.financial_basis==='TTM_YOY'&&x.r.market_cap_usd*1342.989990234375>=5e11,'Wrong financial basis or market cap');}if(x.missing===0)assert(Math.abs(x.low-x.up)<1e-8,'Exact score has inconsistent bounds');}},
 setTimeout,
 Blob,URL,
 console
};
vm.runInNewContext(scripts[0][1],ctx,{timeout:15000});
setTimeout(()=>{
  try{
    assert(get("notice").innerHTML.includes("종가 기준"),"missing asof");
    assert(get("total").textContent!=="—","universe not loaded");
    assert(get("priced").textContent!=="—","coverage not loaded");
    const official=Number(get("official").textContent.replace(/,/g,""));
    assert(Number.isFinite(official),"missing official count");
    assert(get("validation").innerHTML.includes("시가총액 수집"),"coverage detail missing");
    assert(get("validation").innerHTML.includes("TV 자료"),"TV overlay not connected");
    assert(get("validation").innerHTML.includes("FY 매출"),"FY YoY comparison not connected");
    get("filter").value="all"; get("filter").listeners.change();
    get("search").value="NTAP";
    get("search").listeners.input();
    assert(get("table").innerHTML.includes("NTAP"),"Priority ticker not rendered");

    get("search").value="";
    get("search").listeners.input();
    get("filter").value="all";
    get("filter").listeners.change();
    assert(get("table").innerHTML.includes("<tr>"),"table failed to render");
    get("filter").value="watch";
    get("filter").listeners.change();
    assert(get("table").innerHTML.length>50,"watchlist did not render");
    console.log("Dashboard validated:",{
      market_session:snapshot.market_session,universe:snapshot.universe_count,
      quoted:snapshot.price_updated_count,
      official:official,
      prelim:get("watch").textContent,
      tradingview_count:tv.stats?.requested||Object.keys(tv.rows).length,
      market_cap_count:(get("validation").innerHTML.match(/시가총액 수집.*?<strong>(.*?)<\/strong>/)||[])[1]
    });
  }catch(e){console.error(e);process.exitCode=1;}
},400);
