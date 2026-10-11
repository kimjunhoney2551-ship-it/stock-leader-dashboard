const fs=require("fs"),vm=require("vm"),assert=require("assert");
for(const f of ["docs/index.html","docs/2026-10-09.html"]){
 const html=fs.readFileSync(f,"utf8");
 const matches=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
 assert(matches.length>=1,"No inline script found for "+f);
 for(const [i,m] of matches.entries()){
  new vm.Script(m[1],{filename:f+"#"+i});
 }
 assert(html.includes("addTradingViewLatest"),"Missing TradingView merger "+f);
 assert(html.includes("data/tradingview_latest.json"),"Missing connected TV JSON fetch "+f);
 assert(html.includes("tvCount"),"Missing TV status display "+f);
 console.log("Validated syntax and merged source wiring:",f);
}