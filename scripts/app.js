(() => {
'use strict';

const CONFIG = {
  pollsLocal: 'data/polls.json',
  pollsFallback: 'data/polls-fallback.json',
  constituencyLocal: 'data/constituencies-2024.json',
  geometryDisplayLocal: 'data/constituencies-map.geojson',
  geometryLocal: 'data/constituencies-2024.geojson',
  modelParamsLocal: 'data/model-params.json',
  mrpLiteLocal: 'data/mrp-lite-live.json',
  subnationalLocal: 'data/subnational-polls.json',
  territorialBaselineLocal: 'data/territorial-baseline.json',
  niLocal: 'data/ni-2024.json',
  commonsCandidateCsv: 'https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv',
  wikiApi: 'https://en.wikipedia.org/w/api.php?action=parse&page=Opinion_polling_for_the_next_United_Kingdom_general_election&prop=text&format=json&origin=*',
  onsGeo: 'https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson',
  halfLifeDays: 7,
  modelLookbackDays: 100,
  subnationalHalfLifeDays: 28,
  subnationalLookbackDays: 210,
  mcSims: 50000,
  mcBatch: 1000,
  majority: 326,
  gbSeats: 632,
  niSeats: 18,
  cacheVersion: 'uk-v091-20260826-mrp-parser-fix',
  swingLambda: 0.82,
  nationalSigma: {lab:1.35,con:1.35,ref:1.35,ld:0.95,green:0.95,snp:0.50,pc:0.30,rb:0.65,other:0.70},
  regionNoise: 0.035,
  localNoise: 0.055,
  niSwingLambda: 0.55,
  niNationalNoise: 0.050,
  niLocalNoise: 0.100,
};

const PARTY_ORDER = ['lab','con','ref','ld','green','snp','pc','rb','other'];
// RB is shown in polling, but is deliberately excluded from the constituency
// seat conversion until we have a defensible candidate/geographic baseline.
const SEAT_MODEL_PARTIES = PARTY_ORDER.filter(p=>p!=='rb');
const PARTY = {
  lab:{name:'Labour',short:'Lab',color:'#e4003b'},
  con:{name:'Conservative',short:'Con',color:'#0087dc'},
  ref:{name:'Reform UK',short:'Ref',color:'#12b6cf'},
  ld:{name:'Liberal Democrats',short:'LD',color:'#faa61a'},
  green:{name:'Green',short:'Green',color:'#6ab023'},
  snp:{name:'SNP',short:'SNP',color:'#f6e642',text:'#111'},
  pc:{name:'Plaid Cymru',short:'PC',color:'#005b54'},
  rb:{name:'Restore Britain',short:'RB',color:'#8752cc'},
  other:{name:'Altri',short:'Altri',color:'#7c8491'},
  sf:{name:'Sinn Féin',short:'SF',color:'#008c4a',abstentionist:true},
  dup:{name:'Democratic Unionist Party',short:'DUP',color:'#8f3f2f'},
  alliance:{name:'Alliance Party',short:'Alliance',color:'#c49300',text:'#111'},
  sdlp:{name:'SDLP',short:'SDLP',color:'#5f8f32'},
  uup:{name:'Ulster Unionist Party',short:'UUP',color:'#596fb3'},
  tuv:{name:'Traditional Unionist Voice',short:'TUV',color:'#263a5e'},
  aontu:{name:'Aontú',short:'Aontú',color:'#8d4a83'},
  pbp:{name:'People Before Profit',short:'PBP',color:'#a51f4b'},
  ni_green:{name:'Green Party NI',short:'Green NI',color:'#79a86b'},
  ind:{name:'Independent',short:'Ind',color:'#b6beca'},
  ni_other:{name:'Altri NI',short:'Altri NI',color:'#505866'},
};
const NI_ORDER=['sf','dup','alliance','sdlp','uup','tuv','aontu','pbp','ni_green','ind','ni_other'];
const SEAT_ORDER=['lab','con','ref','ld','green','snp','pc','rb','sf','dup','alliance','sdlp','uup','tuv','aontu','pbp','ni_green','ind','ni_other','other'];

const BASE_GB = {lab:34.6,con:24.4,ref:14.7,ld:12.6,green:6.6,snp:2.6,pc:0.7,rb:0,other:3.8};
const MONTHS = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
const OFFLINE = new URLSearchParams(location.search).get('offline') === '1';

const state = {
  polls:[], pollSource:'', average:null, latestAverage:null,
  constituencies:[], constituencyIndex:new Map(), byId:new Map(), geometry:null, ni:null,
  modelParams:null, mrpLite:null, subnational:[], territorialBaseline:null, geographicTargets:null,
  mapPaths:new Map(), selectedPath:null,
  central:null, mc:null, selectedSeat:null, mapMode:'central', coalition:new Set(),
};

const $ = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));
const fmt1 = n => Number.isFinite(n) ? n.toLocaleString('it-IT',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
const fmt0 = n => Number.isFinite(n) ? Math.round(n).toLocaleString('it-IT') : '—';
const pctFmt = n => Number.isFinite(n) ? `${fmt1(n)}%` : '—';
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const sleepFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve()));

function setStatus(text, kind='loading') {
  $('#statusText').textContent = text;
  $('#statusDot').className = `dot ${kind}`;
}
function showError(text) {
  const el = $('#errorBox'); el.textContent = text; el.style.display = 'block';
}
function clearError(){ $('#errorBox').style.display='none'; }

async function fetchJson(url, timeout=15000) {
  const ctrl = new AbortController(); const t=setTimeout(()=>ctrl.abort(),timeout);
  try {
    const r=await fetch(url,{cache:'no-store',signal:ctrl.signal});
    if(!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return await r.json();
  } finally { clearTimeout(t); }
}
async function fetchText(url, timeout=18000) {
  const ctrl=new AbortController(); const t=setTimeout(()=>ctrl.abort(),timeout);
  try { const r=await fetch(url,{cache:'no-store',signal:ctrl.signal}); if(!r.ok) throw new Error(`${r.status}`); return await r.text(); }
  finally { clearTimeout(t); }
}

function parsePercent(text){ const m=String(text??'').replace(',','.').match(/-?\d+(?:\.\d+)?/); return m?Number(m[0]):null; }
function parseEndDate(text, year){
  const matches=[...String(text).replace(/—|−/g,'–').matchAll(/(\d{1,2})\s+([A-Za-z]{3,9})/g)];
  let day,mon;
  if(matches.length){ const m=matches[matches.length-1]; day=Number(m[1]); mon=MONTHS[m[2].slice(0,3).toLowerCase()]; }
  else { const m=String(text).match(/(?:\d{1,2}\s*[–-]\s*)?(\d{1,2})\s+([A-Za-z]{3,9})/); if(!m)return null; day=Number(m[1]); mon=MONTHS[m[2].slice(0,3).toLowerCase()]; }
  if(mon==null)return null; const d=new Date(Date.UTC(year,mon,day)); return Number.isNaN(+d)?null:d.toISOString().slice(0,10);
}

function parseWikipediaPolls(html){
  const doc=new DOMParser().parseFromString(html,'text/html');
  let inNational=false, year=null; const out=[], seen=new Set();
  for(const el of doc.querySelectorAll('h2,h3,h4,table')){
    if(/^H[234]$/.test(el.tagName)){
      const title=el.textContent.replace(/\[edit\]/gi,'').trim();
      if(title.includes('National poll results')){ inNational=true; continue; }
      if(inNational && el.tagName==='H2' && !title.includes('National poll results')) inNational=false;
      if(inNational && /^20\d{2}$/.test(title)) year=Number(title);
      continue;
    }
    if(!inNational || !year) continue;
    const rows=Array.from(el.querySelectorAll('tr')); if(!rows.length)continue;
    const heads=Array.from(rows[0].querySelectorAll('th,td')).map(x=>x.textContent.replace(/\s+/g,' ').trim().toLowerCase());
    const idx={};
    heads.forEach((h,i)=>{
      if(h.includes('date')&&h.includes('conduct'))idx.date=i; else if(h==='pollster')idx.pollster=i; else if(h==='client')idx.client=i;
      else if(h==='area')idx.area=i; else if(h.includes('sample'))idx.sample=i; else if(h==='lab')idx.lab=i; else if(h==='con')idx.con=i;
      else if(h==='ref')idx.ref=i; else if(h==='ld')idx.ld=i; else if(h==='grn')idx.green=i; else if(h==='snp')idx.snp=i; else if(h==='pc')idx.pc=i;
      else if(h==='rb')idx.rb=i; else if(h.startsWith('other'))idx.other=i;
    });
    if(['date','pollster','area','lab','con','ref','ld','green'].some(k=>idx[k]==null))continue;
    for(const tr of rows.slice(1)){
      const cells=Array.from(tr.querySelectorAll(':scope > th,:scope > td')).map(x=>x.textContent.replace(/\s+/g,' ').trim());
      if(cells.length<=Math.max(...Object.values(idx)))continue;
      const date=parseEndDate(cells[idx.date],year); if(!date)continue;
      const pollster=cells[idx.pollster]; if(!pollster||/election|by-election/i.test(pollster))continue;
      const rec={date,fieldwork:cells[idx.date],pollster,client:idx.client!=null?cells[idx.client]:'',area:String(cells[idx.area]).toUpperCase(),sample:Math.round(parsePercent(cells[idx.sample])||0)};
      for(const p of ['lab','con','ref','ld','green','snp','pc','rb','other']) rec[p]=idx[p]!=null?parsePercent(cells[idx[p]]):null;
      const key=[date,pollster,rec.sample,rec.lab,rec.con,rec.ref].join('|'); if(seen.has(key))continue; seen.add(key); out.push(rec);
    }
  }
  return out.sort((a,b)=>b.date.localeCompare(a.date));
}

async function loadPolls(){
  try { const j=await fetchJson(CONFIG.pollsLocal,5000); if(j?.polls?.length>=20){state.pollSource='snapshot automatico';return j.polls;} } catch(_){ }
  if(!OFFLINE) try { const j=await fetchJson(CONFIG.wikiApi,12000); const polls=parseWikipediaPolls(j.parse.text['*']); if(polls.length>=20){state.pollSource='MediaWiki live';return polls;} } catch(_){ }
  const f=await fetchJson(CONFIG.pollsFallback,5000); state.pollSource='snapshot di sicurezza'; return f.polls||[];
}

function parseCsv(text){
  const rows=[]; let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(quoted){ if(c==='"'&&text[i+1]==='"'){cell+='"';i++;} else if(c==='"')quoted=false; else cell+=c; }
    else if(c==='"')quoted=true; else if(c===','){row.push(cell);cell='';} else if(c==='\n'){row.push(cell.replace(/\r$/,''));rows.push(row);row=[];cell='';} else cell+=c;
  }
  if(cell||row.length){row.push(cell);rows.push(row);} if(!rows.length)return [];
  const h=rows.shift(); return rows.filter(r=>r.some(Boolean)).map(r=>Object.fromEntries(h.map((k,i)=>[k,r[i]??''])));
}
function mapCandidateParty(row){
  const a=String(row['Party abbreviation']||'').toLowerCase().trim(), n=String(row['Party name']||'').toLowerCase().trim();
  if(a==='lab'||n.includes('labour'))return 'lab'; if(a==='con'||n.includes('conservative'))return 'con'; if(a==='ld'||n.includes('liberal democrat'))return 'ld';
  if(a==='ruk'||a==='ref'||n.includes('reform uk'))return 'ref'; if(a==='green'||n==='green party'||n.includes('scottish green'))return 'green';
  if(a==='snp'||n.includes('scottish national'))return 'snp'; if(a==='pc'||n.includes('plaid cymru'))return 'pc'; return 'other';
}
function constituenciesFromCandidateCsv(text){
  const rows=parseCsv(text), grouped=new Map();
  for(const r of rows){
    const id=(r['ONS ID']||'').trim(); if(!id)continue;
    if(!grouped.has(id))grouped.set(id,{id,name:(r['Constituency name']||'').trim(),region:(r['Region name']||'').trim(),country:(r['Country name']||'').trim(),shares:{},candidates:[]});
    const x=grouped.get(id), party=mapCandidateParty(r), votes=Math.round(parsePercent(r.Votes)||0);
    let reportedShare=parsePercent(r.Share);
    if(Number.isFinite(reportedShare)&&Math.abs(reportedShare)<=1.000001)reportedShare*=100;
    x.candidates.push({party,party_name:r['Party name']||'',candidate:`${r['Candidate first name']||''} ${r['Candidate surname']||''}`.trim(),votes,reportedShare});
  }
  return [...grouped.values()].map(x=>{
    const totalVotes=x.candidates.reduce((s,c)=>s+c.votes,0);
    if(totalVotes<=0)throw new Error(`Nessun voto valido per ${x.name}`);
    x.shares={};
    for(const c of x.candidates){
      c.share=c.votes/totalVotes*100;
      if(Number.isFinite(c.reportedShare)&&Math.abs(c.reportedShare-c.share)>.25)throw new Error(`Quota voto incoerente per ${x.name}`);
      delete c.reportedShare;
      x.shares[c.party]=(x.shares[c.party]||0)+c.share;
    }
    x.valid_votes=totalVotes;
    const shareTotal=Object.values(x.shares).reduce((a,b)=>a+b,0);
    if(Math.abs(shareTotal-100)>.5)throw new Error(`Quote voto non sommano a 100 per ${x.name}`);
    x.candidates.sort((a,b)=>b.votes-a.votes);
    x.winner2024=x.candidates[0]?.party||'other';x.winner2024_name=x.candidates[0]?.party_name||'';x.winner2024_candidate=x.candidates[0]?.candidate||'';x.majority2024=(x.candidates[0]?.votes||0)-(x.candidates[1]?.votes||0);x.top_candidates_2024=x.candidates.slice(0,4);delete x.candidates;return x;
  });
}
async function loadConstituencies(){
  try { const j=await fetchJson(CONFIG.constituencyLocal,7000); if(j?.constituencies?.length===650)return j.constituencies; } catch(_){ }
  if(!OFFLINE) try { const t=await fetchText(CONFIG.commonsCandidateCsv,18000); const c=constituenciesFromCandidateCsv(t); if(c.length===650)return c; } catch(_){ }
  return [];
}
async function loadGeometry(){
  try { const j=await fetchJson(CONFIG.geometryDisplayLocal,5000); if(j?.features?.length>=650)return j; } catch(_){ }
  try { const j=await fetchJson(CONFIG.geometryLocal,8000); if(j?.features?.length>=650)return j; } catch(_){ }
  if(!OFFLINE) try { const j=await fetchJson(CONFIG.onsGeo,18000); if(j?.features?.length>=650)return j; } catch(_){ }
  return null;
}
async function loadModelParams(){
  try{
    const j=await fetchJson(CONFIG.modelParamsLocal,5000);
    return j?.approved ? j : null;
  }catch(_){ return null; }
}
async function loadSubnationalPolls(){
  try{
    const j=await fetchJson(CONFIG.subnationalLocal,5000);
    return Array.isArray(j?.polls)?j.polls:[];
  }catch(_){ return []; }
}
async function loadTerritorialBaseline(){
  try{
    const j=await fetchJson(CONFIG.territorialBaselineLocal,5000);
    return j?.groups?.GB?j:null;
  }catch(_){ return null; }
}
function lambdaFor(p){
  const v=state.modelParams?.lambdas?.[p];
  return Number.isFinite(v)?v:CONFIG.swingLambda;
}
function refMissingPrior(){
  const v=state.modelParams?.ref_missing_prior;
  return Number.isFinite(v)?v:0;
}
function regionBetaFor(zone,p){
  const v=state.modelParams?.regional_beta?.[zone]?.[p];
  return Number.isFinite(v)?v:1;
}
function zoneForSeat(seat){
  if(/scotland/i.test(seat.country||''))return 'Scotland';
  if(/wales/i.test(seat.country||''))return 'Wales';
  if(/england/i.test(seat.country||''))return seat.region||'England';
  return seat.country||'Other';
}
function allowedInZone(p,zone){
  if(p==='rb')return false;
  if(p==='snp')return zone==='Scotland';
  if(p==='pc')return zone==='Wales';
  return true;
}
function baseGroup(zone){
  return state.territorialBaseline?.groups?.[zone]||null;
}

function calculateAverage(polls){
  const now=new Date(); const sums=Object.fromEntries(PARTY_ORDER.map(p=>[p,0])), den=Object.fromEntries(PARTY_ORDER.map(p=>[p,0])); let effective=0;
  for(const poll of polls){
    const d=new Date(`${poll.date}T12:00:00Z`), age=Math.max(0,(now-d)/86400000); if(age>CONFIG.modelLookbackDays)continue;
    const temporal=Math.pow(0.5,age/CONFIG.halfLifeDays); const sample=clamp(Math.sqrt(Math.max(500,poll.sample||2000)/2000),.75,1.25); const area=poll.area==='UK'?.97:1;
    const w=temporal*sample*area; if(w>.04)effective++;
    for(const p of PARTY_ORDER){ const v=poll[p]; if(Number.isFinite(v)){sums[p]+=w*v;den[p]+=w;} }
  }
  const avg={}; for(const p of PARTY_ORDER)avg[p]=den[p]?sums[p]/den[p]:0;
  // Do not force a strict 100 here: some pollsters do not separately report national parties.
  return {values:avg,effective};
}
function latestPollAverage(polls,n=6){
  const slice=polls.slice(0,n), out={}; for(const p of PARTY_ORDER){const vals=slice.map(x=>x[p]).filter(Number.isFinite);out[p]=vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:0;}return out;
}
function normalizeForZone(values,zone){
  const out={};let total=0;
  for(const p of PARTY_ORDER){
    if(!allowedInZone(p,zone)){out[p]=0;continue;}
    const v=Math.max(0,Number(values?.[p])||0);
    out[p]=v;total+=v;
  }
  if(total<=0)return out;
  for(const p of PARTY_ORDER)out[p]=out[p]/total*100;
  return out;
}
function subnationalAverage(country){
  const now=new Date(),sums=Object.fromEntries(PARTY_ORDER.map(p=>[p,0])),den=Object.fromEntries(PARTY_ORDER.map(p=>[p,0]));
  let effectiveWeight=0,used=0;
  for(const poll of state.subnational){
    if(poll.country!==country)continue;
    const d=new Date(`${poll.date}T12:00:00Z`),age=Math.max(0,(now-d)/86400000);
    if(age>CONFIG.subnationalLookbackDays)continue;
    const temporal=Math.pow(.5,age/CONFIG.subnationalHalfLifeDays);
    const sample=clamp(Math.sqrt(Math.max(400,poll.sample||1000)/1000),.70,1.30);
    const w=temporal*sample;
    if(w<.025)continue;
    effectiveWeight+=w;used++;
    for(const p of PARTY_ORDER){
      const v=poll[p];
      if(Number.isFinite(v)){sums[p]+=w*v;den[p]+=w;}
    }
  }
  const values={};
  for(const p of PARTY_ORDER)values[p]=den[p]?sums[p]/den[p]:null;
  return {values,used,effectiveWeight};
}
function nationalImpliedTarget(zone,gbTarget){
  const base=baseGroup(zone)?.shares||BASE_GB,raw={};
  for(const p of PARTY_ORDER){
    if(!allowedInZone(p,zone)){raw[p]=0;continue;}
    const b=Math.max(.05,Number(base[p])||.05);
    const gbBase=Math.max(.05,Number(BASE_GB[p])||.05);
    raw[p]=b*Math.pow(Math.max(.08,(gbTarget[p]||.05)/gbBase),regionBetaFor(zone,p));
  }
  return normalizeForZone(raw,zone);
}
function blendCountryPoll(country,gbTarget){
  const prior=nationalImpliedTarget(country,gbTarget);
  const poll=subnationalAverage(country);
  if(poll.used<1||poll.effectiveWeight<.08)return {target:prior,source:'GB swing',weight:0,used:0};
  const observed=normalizeForZone(
    Object.fromEntries(PARTY_ORDER.map(p=>[p,Number.isFinite(poll.values[p])?poll.values[p]:prior[p]])),
    country
  );
  // Sparse country polls are useful but should not fully override the GB signal.
  const alpha=clamp(poll.effectiveWeight/(poll.effectiveWeight+1.6),0,.82);
  const mixed={};
  for(const p of PARTY_ORDER)mixed[p]=(1-alpha)*prior[p]+alpha*observed[p];
  return {target:normalizeForZone(mixed,country),source:'polling subnazionale',weight:alpha,used:poll.used};
}
function buildGeographicTargets(gbTarget){
  const groups=state.territorialBaseline?.groups;
  if(!groups?.GB)return {targets:{GB:gbTarget},baselines:{GB:BASE_GB},meta:{}};

  const scot=blendCountryPoll('Scotland',gbTarget);
  const wales=blendCountryPoll('Wales',gbTarget);
  const weights=state.territorialBaseline.country_vote_weights||{};
  const wE=Number(weights.England)||.84,wS=Number(weights.Scotland)||.08,wW=Number(weights.Wales)||.05;

  const engRaw={};
  for(const p of PARTY_ORDER){
    if(!allowedInZone(p,'England')){engRaw[p]=0;continue;}
    const residual=((gbTarget[p]||0)-wS*(scot.target[p]||0)-wW*(wales.target[p]||0))/Math.max(.01,wE);
    engRaw[p]=Math.max(.02,residual);
  }
  const england=normalizeForZone(engRaw,'England');

  const targets={GB:gbTarget,England:england,Scotland:scot.target,Wales:wales.target};
  const baselines={GB:groups.GB.shares,England:groups.England?.shares||BASE_GB,Scotland:groups.Scotland?.shares||BASE_GB,Wales:groups.Wales?.shares||BASE_GB};

  for(const region of state.territorialBaseline.english_regions||[]){
    const rb=groups[region]?.shares;
    if(!rb)continue;
    const raw={};
    for(const p of PARTY_ORDER){
      if(!allowedInZone(p,region)){raw[p]=0;continue;}
      const b=Math.max(.05,Number(rb[p])||.05);
      const eb=Math.max(.05,Number(baselines.England[p])||.05);
      const et=Math.max(.05,Number(england[p])||.05);
      raw[p]=b*Math.pow(Math.max(.08,et/eb),regionBetaFor(region,p));
    }
    targets[region]=normalizeForZone(raw,region);
    baselines[region]=rb;
  }

  return {
    targets,baselines,
    meta:{
      Scotland:{source:scot.source,polls:scot.used,blend:scot.weight},
      Wales:{source:wales.source,polls:wales.used,blend:wales.weight},
      regionalModel:state.modelParams?'validated':'uniform England fallback'
    }
  };
}


function mrpLiteActive(){
  const m=state.mrpLite;
  return m?.version==='uk-v091-mrp-lite-live'
    && m?.model_type==='constituency-residual-ml-v1'
    && m?.status==='ok'
    && m?.approved===true
    && Number(m?.holdout_accuracy)>=.80
    && Array.isArray(m?.seats)
    && m.seats.length===632;
}
function buildMrpLiteCentral(target,geo){
  const lookup=new Map(state.mrpLite.seats.map(s=>[String(s.id),s]));
  const totals=Object.fromEntries(SEAT_ORDER.map(p=>[p,0]));
  const seats=[];
  for(const c of state.constituencies){
    if(/northern ireland/i.test(c.country||''))continue;
    const m=lookup.get(String(c.id));
    if(!m)throw new Error(`MRP-lite: manca il collegio ${c.id}`);
    const projected={};
    for(const p of PARTY_ORDER)projected[p]=Number(m.projected?.[p])||0;
    const winner=SEAT_MODEL_PARTIES.filter(p=>partyAllowed(p,c))
      .reduce((best,p)=>projected[p]>(projected[best]??-1)?p:best,'other');
    totals[winner]=(totals[winner]||0)+1;
    seats.push({...c,projected,centralWinner:winner,modelZone:zoneForSeat(c),mrpLite:true});
  }
  const niCentral=buildNiCentral();
  for(const [p,n] of Object.entries(niCentral.totals||{}))totals[p]=(totals[p]||0)+n;
  seats.push(...niCentral.seats);
  if(!niCentral.seats.length)totals.other+=CONFIG.niSeats;
  const central={target,geographic:geo,seats,totals,ni:niCentral.meta,mrpLite:{
    holdoutAccuracy:Number(state.mrpLite.holdout_accuracy)||0,
    holdoutSeatError:Number(state.mrpLite.holdout_seat_abs_error)||0,
    selectedSpec:state.mrpLite.selected_spec?.name||state.mrpLite.selected_spec||'ML'
  }};
  state.geographicTargets=geo;
  state.central=central;
  state.byId=new Map(seats.map(s=>[s.id,s]));
  return central;
}

function partialRakeModelActive(){
  return state.modelParams?.model_type==='partial-raked-v1'
    && state.modelParams?.approved===true
    && Number.isFinite(Number(state.modelParams?.rake_strength));
}
function partialRakeStrength(){
  return clamp(Number(state.modelParams?.rake_strength)||0,0,1);
}
function weightedNationalRows(items){
  const totals=Object.fromEntries(SEAT_MODEL_PARTIES.map(p=>[p,0]));
  let den=0;
  for(const item of items){
    const w=Math.max(1,Number(item.seat.valid_votes)||1);den+=w;
    for(const p of SEAT_MODEL_PARTIES)totals[p]+=w*(item.shares[p]||0)/100;
  }
  if(den>0)for(const p of SEAT_MODEL_PARTIES)totals[p]=totals[p]/den*100;
  return totals;
}
function targetForRaking(gbTarget){
  const out={};let total=0;
  for(const p of SEAT_MODEL_PARTIES){
    const v=Math.max(.0001,Number(gbTarget?.[p])||0);out[p]=v;total+=v;
  }
  if(total>0)for(const p of SEAT_MODEL_PARTIES)out[p]=out[p]/total*100;
  return out;
}
function fullRakeItems(items,target,iterations=40){
  const out=items.map(item=>({seat:item.seat,shares:{...item.shares}}));
  for(let iter=0;iter<iterations;iter++){
    const current=weightedNationalRows(out);let maxErr=0;const mult={};
    for(const p of SEAT_MODEL_PARTIES){
      maxErr=Math.max(maxErr,Math.abs((current[p]||0)-(target[p]||0)));
      mult[p]=clamp((target[p]||0)/Math.max(.01,current[p]||0),.40,2.50);
    }
    if(maxErr<.02)break;
    for(const item of out){
      const raw={};
      for(const p of SEAT_MODEL_PARTIES)raw[p]=partyAllowed(p,item.seat)?(item.shares[p]||0)*mult[p]:0;
      item.shares=normalizeSeatRow(raw,item.seat);
    }
  }
  return out;
}
function applyPartialRaking(items,gbTarget){
  const alpha=partialRakeStrength();
  if(alpha<=0)return items;
  const target=targetForRaking(gbTarget),full=fullRakeItems(items,target,Number(state.modelParams?.rake_iterations)||40);
  return items.map((item,i)=>{
    const raw={};
    for(const p of SEAT_MODEL_PARTIES)raw[p]=(1-alpha)*(item.shares[p]||0)+alpha*(full[i].shares[p]||0);
    return {seat:item.seat,shares:normalizeSeatRow(raw,item.seat)};
  });
}
function transferModelActive(){
  return state.modelParams?.model_type==='transfer-raked-v1'
    && state.modelParams?.approved===true
    && state.modelParams?.transfer_coefficients;
}
function transferCountryForSeat(seat){
  if(/scotland/i.test(seat.country||''))return 'Scotland';
  if(/wales/i.test(seat.country||''))return 'Wales';
  return 'England';
}
function modelTargetWithoutRB(values,zone){
  const out={};let total=0;
  for(const p of SEAT_MODEL_PARTIES){
    if(!allowedInZone(p,zone)){out[p]=0;continue;}
    const v=Math.max(.0001,Number(values?.[p])||0);
    out[p]=v;total+=v;
  }
  if(total<=0)return out;
  for(const p of SEAT_MODEL_PARTIES)out[p]=(out[p]||0)/total*100;
  return out;
}
function normalizeSeatRow(raw,seat){
  const out={};let total=0;
  for(const p of SEAT_MODEL_PARTIES){
    if(!partyAllowed(p,seat)){out[p]=0;continue;}
    const v=Math.max(.0001,Number(raw?.[p])||0);
    out[p]=v;total+=v;
  }
  for(const p of PARTY_ORDER){
    if(p==='rb'){out[p]=0;continue;}
    if(out[p]==null)out[p]=0;
  }
  if(total<=0){out.other=100;return out;}
  for(const p of SEAT_MODEL_PARTIES)out[p]=(out[p]||0)/total*100;
  return out;
}
function weightedTargetFromRows(items){
  const totals=Object.fromEntries(SEAT_MODEL_PARTIES.map(p=>[p,0]));
  let den=0;
  for(const item of items){
    const w=Math.max(1,Number(item.seat.valid_votes)||1);den+=w;
    for(const p of SEAT_MODEL_PARTIES)totals[p]+=w*(item.shares[p]||0)/100;
  }
  if(den<=0)return totals;
  for(const p of SEAT_MODEL_PARTIES)totals[p]=totals[p]/den*100;
  return totals;
}
function rakeTransferRows(items,target,iterations=28){
  for(let iter=0;iter<iterations;iter++){
    const current=weightedTargetFromRows(items);
    let maxErr=0;const mult={};
    for(const p of SEAT_MODEL_PARTIES){
      const desired=Number(target[p])||0;
      maxErr=Math.max(maxErr,Math.abs((current[p]||0)-desired));
      mult[p]=clamp(desired/Math.max(.01,current[p]||0),.45,2.20);
    }
    if(maxErr<.02)break;
    for(const item of items){
      const raw={};
      for(const p of SEAT_MODEL_PARTIES)raw[p]=partyAllowed(p,item.seat)?(item.shares[p]||0)*mult[p]:0;
      item.shares=normalizeSeatRow(raw,item.seat);
    }
  }
  return items;
}
function transferFeatureVector(seat,baseNat,targetNat){
  const sources=state.modelParams?.transfer_feature_parties||['lab','con','ref','ld','green','snp','pc'];
  return sources.map(p=>{
    const nationalMove=((targetNat[p]||0)-(baseNat[p]||0))/10;
    const localExposure=((seat.shares?.[p]||0)-(baseNat[p]||0))/20;
    return nationalMove*localExposure;
  });
}
function transferProjectGroup(seats,targetRaw,baseRaw){
  if(!seats.length)return [];
  const zone=transferCountryForSeat(seats[0]);
  const target=modelTargetWithoutRB(targetRaw,zone);
  const base=modelTargetWithoutRB(baseRaw,zone);
  const items=seats.map(seat=>{
    const raw={};
    for(const p of SEAT_MODEL_PARTIES){
      if(!partyAllowed(p,seat)){raw[p]=0;continue;}
      let b=seat.shares?.[p]||0;
      const floor=['lab','con','ref','ld','green'].includes(p)?.18:.03;
      b=Math.max(b,floor);
      raw[p]=b*Math.pow(Math.max(.08,(target[p]||.01)/Math.max(.01,base[p]||.01)),CONFIG.swingLambda);
    }
    return {seat,shares:normalizeSeatRow(raw,seat)};
  });
  rakeTransferRows(items,target,Number(state.modelParams?.rake_iterations)||36);

  const coeff=state.modelParams?.transfer_coefficients||{};
  const sources=state.modelParams?.transfer_feature_parties||['lab','con','ref','ld','green','snp','pc'];
  for(const item of items){
    const features=transferFeatureVector(item.seat,base,target);
    const raw={...item.shares};
    for(const p of SEAT_MODEL_PARTIES){
      if(!partyAllowed(p,item.seat)){raw[p]=0;continue;}
      let correction=0;
      const row=coeff[p]||{};
      for(let i=0;i<sources.length;i++)correction+=(Number(row[sources[i]])||0)*(features[i]||0);
      raw[p]=Math.max(.0001,(raw[p]||0)+correction);
    }
    item.shares=normalizeSeatRow(raw,item.seat);
  }
  return rakeTransferRows(items,target,Number(state.modelParams?.rake_iterations)||36);
}
function buildTransferCentral(target,geo){
  const gbSeats=state.constituencies.filter(c=>!/northern ireland/i.test(c.country||''));
  const groups=new Map([['England',[]],['Scotland',[]],['Wales',[]]]);
  for(const c of gbSeats)groups.get(transferCountryForSeat(c)).push(c);

  const seats=[];const totals=Object.fromEntries(PARTY_ORDER.map(p=>[p,0]));
  for(const country of ['England','Scotland','Wales']){
    const group=groups.get(country)||[];
    const zoneTarget=geo.targets[country]||target;
    const zoneBase=geo.baselines[country]||BASE_GB;
    for(const item of transferProjectGroup(group,zoneTarget,zoneBase)){
      const shares=item.shares;
      const winner=SEAT_MODEL_PARTIES
        .filter(p=>partyAllowed(p,item.seat))
        .reduce((best,p)=>shares[p]>(shares[best]??-1)?p:best,'other');
      totals[winner]++;
      seats.push({...item.seat,projected:shares,centralWinner:winner,modelZone:item.seat.region||country});
    }
  }
  totals.other+=CONFIG.niSeats;
  return {target,geographic:geo,seats,totals};
}

function renderPolls(){
  const a=state.average.values; const ordered=PARTY_ORDER.map(p=>[p,a[p]]).sort((x,y)=>y[1]-x[1]);
  $('#voteBars').innerHTML=ordered.map(([p,v])=>`<div class="vote-row"><div class="party-label"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</div><div class="bar-track"><div class="bar-fill" style="background:${PARTY[p].color};width:${clamp(v/35*100,0,100)}%"></div></div><div class="vote-val">${pctFmt(v)}</div></div>`).join('');
  const leader=ordered[0], second=ordered[1]; $('#kpiLeader').textContent=PARTY[leader[0]].short; $('#kpiLeaderMeta').textContent=`${pctFmt(leader[1])} · +${fmt1(leader[1]-second[1])} su ${PARTY[second[0]].short}`;
  $('#pollAverageMeta').textContent=`${state.average.effective} rilevazioni con peso significativo · half-life ${CONFIG.halfLifeDays} giorni`;
  const latest=state.polls[0]; if(latest){$('#kpiLastPoll').textContent=formatDate(latest.date);$('#kpiLastPollMeta').textContent=`${latest.pollster} · ${latest.area} · n=${fmt0(latest.sample)}`;}
  $('#dataBadge').textContent=`Sondaggi: ${state.pollSource}`;
  const rows=state.polls.slice(0,24).map(p=>`<tr><td>${escapeHtml(p.fieldwork||formatDate(p.date))}</td><td>${escapeHtml(p.pollster)}</td><td>${escapeHtml(p.area)}</td><td>${fmt0(p.sample)}</td>${['lab','con','ref','ld','green','snp','pc','rb'].map(k=>`<td>${Number.isFinite(p[k])?fmt1(p[k]):'—'}</td>`).join('')}</tr>`).join('');
  $('#pollTableBody').innerHTML=rows;
}
function formatDate(iso){ try{return new Date(`${iso}T12:00:00Z`).toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit',year:'numeric'});}catch(_){return iso;} }
function escapeHtml(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function partyAllowed(p, seat){ return allowedInZone(p,zoneForSeat(seat)); }
function normalizeTargets(avg){
  const x={}; let total=0; for(const p of PARTY_ORDER){ x[p]=Math.max(0.05,avg[p]||0); total+=x[p]; }
  for(const p of PARTY_ORDER)x[p]=x[p]/total*100; return x;
}
function projectedShares(seat,target,geoBase){
  const raw={}; let sum=0; const zone=zoneForSeat(seat);
  for(const p of PARTY_ORDER){
    if(!partyAllowed(p,seat)){raw[p]=0;continue;}
    let base=seat.shares?.[p]||0;
    const natBase=Math.max(.05,Number(geoBase?.[p])||Number(BASE_GB[p])||.2);
    if(p==='ref' && base<.18 && refMissingPrior()>0) base=Math.max(base,natBase*refMissingPrior());
    if(['lab','con','ref','ld','green'].includes(p))base=Math.max(base,.18); else base=Math.max(base,.03);
    const ratio=Math.max(.08,(target[p]||.05)/natBase);
    raw[p]=base*Math.pow(ratio,lambdaFor(p)); sum+=raw[p];
  }
  if(sum<=0)return raw; for(const p of PARTY_ORDER)raw[p]=raw[p]/sum*100; return raw;
}
function niModuleReady(){
  return state.ni?.meta?.version==='uk-v08-ni-constituency'&&Array.isArray(state.ni?.constituencies)&&state.ni.constituencies.length===18;
}
function niNormalize(raw){
  const out={};let total=0;for(const p of NI_ORDER){const v=Math.max(.0001,Number(raw?.[p])||0);out[p]=v;total+=v;}
  if(total<=0)return out;for(const p of NI_ORDER)out[p]=out[p]/total*100;return out;
}
function buildNiCentral(){
  if(!niModuleReady())return {seats:[],totals:{other:CONFIG.niSeats},meta:{mode:'fixed fallback',signalWeight:0,workingThreshold:322}};
  const base=state.ni.national_2024||{},target=state.ni.target_shares||base,seats=[],totals=Object.fromEntries(NI_ORDER.map(p=>[p,0]));
  for(const seat of state.ni.constituencies){
    const eligible=(seat.eligible_parties||Object.keys(seat.shares||{})).filter(p=>NI_ORDER.includes(p)),raw={};
    for(const p of NI_ORDER){
      if(!eligible.includes(p)){raw[p]=0;continue;}
      const local=Math.max(.05,Number(seat.shares?.[p])||.05),bn=Math.max(.05,Number(base[p])||.05),tn=Math.max(.05,Number(target[p])||.05);
      raw[p]=local*Math.pow(Math.max(.12,tn/bn),CONFIG.niSwingLambda);
    }
    const projected=niNormalize(raw),winner=eligible.reduce((best,p)=>(projected[p]||0)>(projected[best]??-1)?p:best,eligible[0]||'ni_other');
    totals[winner]=(totals[winner]||0)+1;seats.push({...seat,projected,centralWinner:winner,modelZone:'Northern Ireland',isNorthernIreland:true});
  }
  const sfSeats=totals.sf||0;
  return {seats,totals,meta:{mode:state.ni.meta?.mode||'NI module',signalWeight:Number(state.ni.meta?.signal_weight)||0,sfSeats,workingThreshold:Math.floor((650-sfSeats)/2)+1}};
}

function buildCentral(){
  const target=normalizeTargets(state.average.values),geo=buildGeographicTargets(target),initial=[];
  if(mrpLiteActive())return buildMrpLiteCentral(target,geo);
  for(const c of state.constituencies){
    if(/northern ireland/i.test(c.country||''))continue;
    const zone=zoneForSeat(c),zoneTarget=geo.targets[zone]||geo.targets.England||target,zoneBase=geo.baselines[zone]||geo.baselines.England||BASE_GB;
    initial.push({seat:c,shares:projectedShares(c,zoneTarget,zoneBase),zone});
  }
  let items=initial;
  if(partialRakeModelActive())items=applyPartialRaking(initial,target);
  else if(transferModelActive()){const legacy=buildTransferCentral(target,geo);state.geographicTargets=geo;state.central=legacy;state.byId=new Map(legacy.seats.map(s=>[s.id,s]));return legacy;}
  const totals=Object.fromEntries(SEAT_ORDER.map(p=>[p,0])),seats=[];
  for(let i=0;i<items.length;i++){
    const item=items[i],c=item.seat,shares=item.shares,zone=initial[i]?.zone||zoneForSeat(c);
    const winner=SEAT_MODEL_PARTIES.filter(p=>partyAllowed(p,c)).reduce((best,p)=>shares[p]>(shares[best]??-1)?p:best,'other');
    totals[winner]++;seats.push({...c,projected:shares,centralWinner:winner,modelZone:zone});
  }
  const niCentral=buildNiCentral();for(const [p,n] of Object.entries(niCentral.totals||{}))totals[p]=(totals[p]||0)+n;
  seats.push(...niCentral.seats);if(!niCentral.seats.length)totals.other+=CONFIG.niSeats;
  const central={target,geographic:geo,seats,totals,ni:niCentral.meta};state.geographicTargets=geo;state.central=central;state.byId=new Map(seats.map(s=>[s.id,s]));return central;
}

function hashString(str){
  let h=2166136261>>>0;
  for(let i=0;i<str.length;i++){
    h^=str.charCodeAt(i);
    h=Math.imul(h,16777619);
  }
  return h>>>0;
}
function mulberry32(a){
  return function(){
    let t=a+=0x6D2B79F5;
    t=Math.imul(t^t>>>15,t|1);
    t^=t+Math.imul(t^t>>>7,t|61);
    return ((t^t>>>14)>>>0)/4294967296;
  };
}
function logistic(rng){
  const u=clamp(rng(),1e-7,1-1e-7);
  return Math.log(u/(1-u))/Math.PI*Math.sqrt(3);
}
function normalApprox(rng){
  return (rng()+rng()+rng()+rng()+rng()+rng()-3)*Math.SQRT2;
}
function fingerprint(){
  const p=state.polls.slice(0,40)
    .map(x=>`${x.date}|${x.pollster}|${x.lab}|${x.con}|${x.ref}|${x.ld}|${x.green}|${x.rb}`)
    .join(';');
  const sp=state.subnational.slice(0,24)
    .map(x=>`${x.country}|${x.date}|${x.pollster}|${x.lab}|${x.con}|${x.ref}|${x.snp}|${x.pc}`)
    .join(';');
  const ni=state.ni?.meta?.generated_at||state.ni?.meta?.version||'ni-fallback';
  const mrp=state.mrpLite?.generated_at||state.mrpLite?.version||'mrp-fallback';
  const cal=state.modelParams
    ? `${state.modelParams.version||'model'}:${state.modelParams.model_type||''}:${state.modelParams.rake_strength??''}`
    : 'fallback';
  return `${CONFIG.cacheVersion}:${hashString(p+'|'+sp+'|'+state.constituencies.length+'|'+cal+'|'+ni+'|'+mrp)}`;
}
function mcCacheKey(){return `focusamerica:${fingerprint()}`;}
function saveMcCache(summary){
  try{localStorage.setItem(mcCacheKey(),JSON.stringify(summary));}catch(_){}
}
function loadMcCache(){
  try{
    const x=JSON.parse(localStorage.getItem(mcCacheKey())||'null');
    if(x?.sims===CONFIG.mcSims&&x?.medians)return x;
  }catch(_){}
  return null;
}

function prepareSeatModel(){
  const seats=state.central.seats,target=state.central.target,geo=state.central.geographic;
  const regions=[...new Set(seats.map(s=>s.isNorthernIreland?'Northern Ireland':(s.modelZone||s.region||s.country||'Other')))],regionIndex=new Map(regions.map((r,i)=>[r,i]));
  const centreAlreadyTransformed=mrpLiteActive()||partialRakeModelActive()||transferModelActive();
  const models=seats.map(s=>{
    const zone=s.isNorthernIreland?'Northern Ireland':(s.modelZone||zoneForSeat(s));
    if(s.isNorthernIreland){
      const candidates=NI_ORDER.filter(p=>(s.projected?.[p]||0)>.001).map(p=>({p,baseLog:Math.log(Math.max(.03,s.projected[p]||.03)),centralShift:0,central:s.projected[p]||0})).sort((a,b)=>b.central-a.central);
      return {id:s.id,region:regionIndex.get(zone),candidates,ni:true};
    }
    const zoneTarget=geo.targets[zone]||target,zoneBase=geo.baselines[zone]||BASE_GB;
    const candidates=SEAT_MODEL_PARTIES.filter(p=>partyAllowed(p,s)).map(p=>{
      if(centreAlreadyTransformed){const central=Math.max(.03,s.projected?.[p]||.03);return {p,baseLog:Math.log(central),centralShift:0,central};}
      let base=s.shares?.[p]||0;const nat=Math.max(.05,Number(zoneBase[p])||Number(BASE_GB[p])||.2);
      if(p==='ref'&&base<.18&&refMissingPrior()>0)base=Math.max(base,nat*refMissingPrior());
      if(['lab','con','ref','ld','green'].includes(p))base=Math.max(base,.18);else base=Math.max(base,.03);
      const lambda=lambdaFor(p),ratio=Math.max(.08,(zoneTarget[p]||.05)/nat);return {p,baseLog:Math.log(base),centralShift:lambda*Math.log(ratio),central:s.projected[p]||0};
    }).sort((a,b)=>b.central-a.central).slice(0,5);
    return {id:s.id,region:regionIndex.get(zone),candidates,ni:false};
  });
  return {models,regions,target};
}

async function runMonteCarlo(force=false){
  if(!state.central?.seats?.length)return;
  setMonteCarloPending(true);
  if(!force){
    const cached=loadMcCache();
    if(cached){
      state.mc=cached;
      renderMc();
      setMonteCarloPending(false);
      applyMapColors();
      return;
    }
  }
  const {models,regions,target}=prepareSeatModel(),P=SEAT_ORDER.length,N=CONFIG.mcSims,nSeats=models.length;
  const partyIndex=new Map(SEAT_ORDER.map((p,i)=>[p,i])),dists=SEAT_ORDER.map(()=>new Uint16Array(N)),wins=new Uint32Array(nSeats*P),rng=mulberry32(hashString(fingerprint()));
  let hung=0,labMaj=0,conMaj=0,refMaj=0,labWorkMaj=0,conWorkMaj=0,refWorkMaj=0;
  const workThresholds=new Uint16Array(N),largestCounts=Object.fromEntries(SEAT_ORDER.map(p=>[p,0]));
  $('#mcStatus').textContent='Calcolo in corso';$('#mcProgress').value=0;const centreAlreadyTransformed=mrpLiteActive()||partialRakeModelActive()||transferModelActive();
  for(let start=0;start<N;start+=CONFIG.mcBatch){
    const end=Math.min(N,start+CONFIG.mcBatch);
    for(let sim=start;sim<end;sim++){
      const drawn={};let sum=0;
      for(const p of PARTY_ORDER){const sigma=CONFIG.nationalSigma[p]||.8;drawn[p]=Math.max(.05,target[p]+normalApprox(rng)*sigma);sum+=drawn[p];}
      for(const p of PARTY_ORDER)drawn[p]=drawn[p]/sum*100;
      const natShift={};for(const p of PARTY_ORDER){const elastic=centreAlreadyTransformed?CONFIG.swingLambda:lambdaFor(p);natShift[p]=elastic*Math.log(Math.max(.05,drawn[p])/Math.max(.05,target[p]||.05));}
      const regNoise=Array.from({length:regions.length},()=>Object.fromEntries(PARTY_ORDER.map(p=>[p,logistic(rng)*CONFIG.regionNoise])));
      const niPartyNoise=Object.fromEntries(NI_ORDER.map(p=>[p,logistic(rng)*CONFIG.niNationalNoise])),counts=new Uint16Array(P);
      for(let si=0;si<nSeats;si++){
        const model=models[si];let bestP=model.ni?'ni_other':'other',bestScore=-Infinity;
        for(const cand of model.candidates){
          const score=model.ni?cand.baseLog+niPartyNoise[cand.p]+logistic(rng)*CONFIG.niLocalNoise:cand.baseLog+cand.centralShift+natShift[cand.p]+regNoise[model.region][cand.p]+logistic(rng)*CONFIG.localNoise;
          if(score>bestScore){bestScore=score;bestP=cand.p;}
        }
        const pi=partyIndex.get(bestP);if(pi==null)continue;counts[pi]++;wins[si*P+pi]++;
      }
      const sf=counts[partyIndex.get('sf')]||0,threshold=Math.floor((650-sf)/2)+1;workThresholds[sim]=threshold;
      let largest='lab',largestN=-1;for(let pi=0;pi<P;pi++){dists[pi][sim]=counts[pi];if(counts[pi]>largestN){largestN=counts[pi];largest=SEAT_ORDER[pi];}}largestCounts[largest]++;
      const lab=counts[partyIndex.get('lab')]||0,con=counts[partyIndex.get('con')]||0,ref=counts[partyIndex.get('ref')]||0,lm=lab>=CONFIG.majority,cm=con>=CONFIG.majority,rm=ref>=CONFIG.majority;
      if(lm)labMaj++;if(cm)conMaj++;if(rm)refMaj++;if(!lm&&!cm&&!rm)hung++;if(lab>=threshold)labWorkMaj++;if(con>=threshold)conWorkMaj++;if(ref>=threshold)refWorkMaj++;
    }
    $('#mcProgress').value=end;$('#mcCount').textContent=`${fmt0(end)} / ${fmt0(N)}`;await sleepFrame();
  }
  const medians={},intervals={},distPlain={};
  for(let pi=0;pi<P;pi++){const p=SEAT_ORDER[pi],arr=Array.from(dists[pi]).sort((a,b)=>a-b);medians[p]=quantileSorted(arr,.5);intervals[p]=[quantileSorted(arr,.1),quantileSorted(arr,.9)];distPlain[p]=Array.from(dists[pi]);}
  const seatProb={};for(let si=0;si<nSeats;si++){const obj={};for(let pi=0;pi<P;pi++)obj[SEAT_ORDER[pi]]=wins[si*P+pi]/N;seatProb[models[si].id]=obj;}
  const workArr=Array.from(workThresholds).sort((a,b)=>a-b);
  const summary={sims:N,medians,intervals,labMaj:labMaj/N,conMaj:conMaj/N,refMaj:refMaj/N,labWorkMaj:labWorkMaj/N,conWorkMaj:conWorkMaj/N,refWorkMaj:refWorkMaj/N,workingThreshold:quantileSorted(workArr,.5),hung:hung/N,largest:Object.fromEntries(SEAT_ORDER.map(p=>[p,largestCounts[p]/N])),seatProb,dist:distPlain,fingerprint:fingerprint()};
  state.mc=summary;
  saveMcCache(summary);
  $('#mcStatus').textContent='Completato';
  renderMc();
  setMonteCarloPending(false);
  applyMapColors();
}

function quantileSorted(arr,q){
  const i=Math.floor((arr.length-1)*q);
  return arr[i];
}

function setMonteCarloPending(pending){
  const probBtn=$('#mapProbBtn');
  if(probBtn){
    probBtn.disabled=!!pending;
    probBtn.setAttribute('aria-disabled',pending?'true':'false');
    probBtn.title=pending?'Disponibile al termine delle 50.000 simulazioni':'Colora i collegi in base alla probabilità di vittoria';
  }
  const badge=$('#mcBadge');
  if(badge)badge.textContent=pending?'50.000 simulazioni · in corso':'50.000 simulazioni · completate';

  if(pending&&state.mapMode==='prob'){
    state.mapMode='central';
    $('#mapCentralBtn')?.classList.add('active');
    $('#mapProbBtn')?.classList.remove('active');
    applyMapColors();
  }
}

function renderCentral(){
  const totals=state.central.totals;
  $('#projectionTitle').textContent='Proiezione centrale · provvisoria';
  const sm=state.geographicTargets?.meta?.Scotland,wm=state.geographicTargets?.meta?.Wales;
  const sub=[sm?.polls?`Scozia: ${sm.polls} poll`:null,wm?.polls?`Galles: ${wm.polls} poll`:null].filter(Boolean).join(' · ');
  $('#projectionSubtitle').textContent=`${mrpLiteActive()?`MRP-lite constituency-level · holdout 2024 ${(state.central.mrpLite.holdoutAccuracy*100).toFixed(1)}% · ${state.central.mrpLite.selectedSpec}`:partialRakeModelActive()?`Raking parziale validato (α=${partialRakeStrength().toFixed(2)}) 2024 → oggi`:transferModelActive()?'Modello trasferimenti 2024 → oggi':'Fallback prudente 2024 → oggi: swing regolarizzato'}${sub?` · ${sub}`:''}${state.central?.ni?.signalWeight?` · NI: tracker Assembly ×${state.central.ni.signalWeight.toFixed(2)}`:' · NI: baseline 2024'} · Monte Carlo in corso: emiciclo e mappa mostrano il centro deterministico fino al completamento.`;
  renderSeats(totals,null);
  $('#kpiLargest').textContent=PARTY[Object.entries(totals).sort((a,b)=>b[1]-a[1])[0][0]]?.short||'—';
  $('#kpiLargestMeta').textContent='proiezione centrale provvisoria';
}
function renderMc(){
  const m=state.mc;if(!m)return; renderSeats(m.medians,m.intervals); $('#projectionTitle').textContent='Distribuzione dei seggi';$('#projectionSubtitle').textContent='Risultato Monte Carlo completato: mediana delle 50.000 simulazioni; intervallo centrale 80% tra parentesi.';
  $('#probLabMaj').textContent=pctFmt(m.labMaj*100);$('#probConMaj').textContent=pctFmt(m.conMaj*100);$('#probRefMaj').textContent=pctFmt(m.refMaj*100);$('#probHung').textContent=pctFmt(m.hung*100);
  if($('#probLabWorkMaj'))$('#probLabWorkMaj').textContent=pctFmt((m.labWorkMaj||0)*100);if($('#probConWorkMaj'))$('#probConWorkMaj').textContent=pctFmt((m.conWorkMaj||0)*100);if($('#probRefWorkMaj'))$('#probRefWorkMaj').textContent=pctFmt((m.refWorkMaj||0)*100);if($('#workingThreshold'))$('#workingThreshold').textContent=fmt0(m.workingThreshold||326);
  const largest=Object.entries(m.largest).sort((a,b)=>b[1]-a[1])[0];$('#kpiLargest').textContent=PARTY[largest[0]]?.short||largest[0];$('#kpiLargestMeta').textContent=`${pctFmt(largest[1]*100)} di essere il primo partito`;
  const maj=Math.max(m.labMaj,m.conMaj,m.refMaj);$('#kpiMajority').textContent=pctFmt(maj*100);const who=m.labMaj===maj?'Labour':m.conMaj===maj?'Conservative':'Reform';$('#kpiMajorityMeta').textContent=`${who} · 326 assoluta · ~${fmt0(m.workingThreshold||326)} operativa`;
  $('#mcStatus').textContent='Completato';$('#mcCount').textContent=`${fmt0(m.sims)} / ${fmt0(m.sims)}`;$('#mcProgress').value=m.sims; updateCoalition();
}
function renderSeats(totals,intervals){
  const sum=SEAT_ORDER.reduce((s,p)=>s+(totals[p]||0),0)||650; $('#seatStrip').innerHTML=SEAT_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<span style="width:${(totals[p]/sum)*100}%;background:${PARTY[p].color}" title="${PARTY[p].name}: ${fmt0(totals[p])}"></span>`).join('');
  $('#seatTable').innerHTML=SEAT_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<div class="seat-row"><div class="left"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</div><strong>${fmt0(totals[p])}${intervals?.[p]?` <small>${fmt0(intervals[p][0])}–${fmt0(intervals[p][1])}</small>`:''}</strong></div>`).join('');
  renderHemicycle(totals);
}
function hemicyclePoints(){
  const pts=[]; for(let row=0;row<18;row++){const r=63+row*9.6,cap=Math.max(8,Math.round(Math.PI*r/11));for(let j=0;j<cap;j++){const t=Math.PI-(j/(cap-1))*Math.PI;pts.push({x:310+r*Math.cos(t),y:297-r*Math.sin(t),r});}}
  pts.sort((a,b)=>a.x-b.x||b.r-a.r); if(pts.length>650){const remove=pts.length-650;const keep=[];for(let i=0;i<pts.length;i++){if(Math.floor((i+1)*remove/pts.length)!==Math.floor(i*remove/pts.length))continue;keep.push(pts[i]);}return keep.slice(0,650);}return pts.slice(0,650);
}
const hemiPts=hemicyclePoints();
function renderHemicycle(totals){
  const seats=[];for(const p of SEAT_ORDER){for(let i=0;i<Math.round(totals[p]||0);i++)seats.push(p);}while(seats.length<650)seats.push('other');if(seats.length>650)seats.length=650;
  $('#hemicycle').innerHTML=hemiPts.map((pt,i)=>`<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="3.7" fill="${PARTY[seats[i]||'other'].color}" opacity=".96"><title>${PARTY[seats[i]||'other'].name}</title></circle>`).join('');
}

function geometryCode(props){return props.PCON24CD||props.PCON24CDH||props.PCONCD||props.GSS_CODE||props.code||props.id||'';}
function geometryName(props){return props.PCON24NM||props.PCONNM||props.NAME||props.name||'';}
function eachCoord(geom,fn){if(!geom)return;if(geom.type==='Polygon'){for(const ring of geom.coordinates)for(const c of ring)fn(c);}else if(geom.type==='MultiPolygon'){for(const poly of geom.coordinates)for(const ring of poly)for(const c of ring)fn(c);}}
function pathForGeometry(geom,project){
  if(!geom)return''; const polyPath=poly=>poly.map(ring=>ring.map((c,i)=>`${i?'L':'M'}${project(c)[0].toFixed(1)},${project(c)[1].toFixed(1)}`).join(' ')+' Z').join(' ');
  return geom.type==='Polygon'?polyPath(geom.coordinates):geom.type==='MultiPolygon'?geom.coordinates.map(polyPath).join(' '):'';
}
function renderMap(){
  const map=$('#ukMap');
  if(!state.geometry?.features?.length){$('#mapEmpty').style.display='grid';$('#mapMeta').textContent='Geometrie non disponibili: esegui la build dati.';return;}
  // Web Mercator for display only. The previous renderer treated one degree
  // of longitude as the same physical distance as one degree of latitude; at
  // UK latitudes that makes Britain look much too wide / vertically squashed.
  // Projection is computed only while the SVG paths are built, so hover cost
  // remains unchanged.
  const features=state.geometry.features;
  const RAD=Math.PI/180;
  const mercator=c=>{
    const lon=Number(c[0])*RAD;
    const lat=clamp(Number(c[1]),-85,85)*RAD;
    return [lon,Math.log(Math.tan(Math.PI/4+lat/2))];
  };
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const f of features)eachCoord(f.geometry,c=>{
    const p=mercator(c);
    minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);
    minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);
  });
  const pad=24,W=640,H=760,s=Math.min((W-2*pad)/(maxX-minX),(H-2*pad)/(maxY-minY));
  const project=c=>{const p=mercator(c);return [pad+(p[0]-minX)*s,H-pad-(p[1]-minY)*s];};
  map.innerHTML=features.map(f=>{
    const id=geometryCode(f.properties||{}),name=geometryName(f.properties||{}),seat=state.byId.get(id);
    const fill=seat?PARTY[seat.centralWinner]?.color:partyColorFrom2024(id);
    const label=seat?.name||name||id;
    return `<path class="constituency" data-id="${escapeHtml(id)}" data-map-name="${escapeHtml(label)}" d="${pathForGeometry(f.geometry,project)}" fill="${fill||'#414957'}"></path>`;
  }).join('');
  state.mapPaths=new Map(Array.from(map.querySelectorAll('path.constituency')).map(el=>[el.dataset.id,el]));
  $('#mapEmpty').style.display='none';
  const reduced=state.geometry?.meta?.vertices_after;
  $('#mapMeta').textContent=reduced?`${features.length} collegi · geometria web ottimizzata`:`${features.length} geometrie ONS · BGC 20 m`;
  applyMapColors();
  map.dispatchEvent(new CustomEvent('maprendered'));
}
function partyColorFrom2024(id){const c=state.byId.get(id)||state.constituencyIndex.get(id);return PARTY[c?.winner2024||'other']?.color||PARTY.other.color;}
function selectSeat(id){
  state.selectedSeat=id;
  if(state.selectedPath)state.selectedPath.classList.remove('selected');
  state.selectedPath=state.mapPaths.get(id)||null;
  if(state.selectedPath)state.selectedPath.classList.add('selected');
  renderDetail(id);
}
function renderDetail(id){
  const seat=state.byId.get(id)||state.constituencies.find(x=>x.id===id);if(!seat)return;$('#detailName').textContent=seat.name;$('#detailRegion').textContent=[seat.region,seat.country].filter(Boolean).join(' · ');
  const proj=seat.projected||{},prob=state.mc?.seatProb?.[id];const rows=Object.keys(proj).filter(p=>PARTY[p]&&(proj[p]||0)>.15).sort((a,b)=>(proj[b]||0)-(proj[a]||0)).slice(0,7);const niNote=seat.isNorthernIreland?' NI: candidature 2024 mantenute; tracker Assembly usato solo come segnale debole.':'';
  $('#detailBody').innerHTML=`<div class="detail-stat"><span>Vincitore 2024</span><strong>${escapeHtml(seat.winner2024_name||PARTY[seat.winner2024]?.name||'Altro')}</strong></div><div class="detail-stat"><span>Proiezione centrale</span><strong>${PARTY[seat.centralWinner||seat.winner2024]?.name||'—'}</strong></div><div class="detail-score">${rows.map(p=>`<div><span>${PARTY[p].short}</span><span class="mini-track"><i style="width:${clamp((proj[p]||0)*2,0,100)}%;background:${PARTY[p].color}"></i></span><strong>${prob?pctFmt((prob[p]||0)*100):pctFmt(proj[p]||0)}</strong></div>`).join('')}</div><p class="small-note">${prob?'Valori a destra = probabilità di vittoria Monte Carlo.':'Valori a destra = quota centrale stimata; probabilità disponibili dopo il Monte Carlo.'}${niNote}</p>`;
}
function applyMapColors(){
  if(!state.mapPaths?.size)return;
  for(const [id,el] of state.mapPaths){
    const seat=state.byId.get(id);if(!seat)continue;
    if(state.mapMode==='central'||!state.mc?.seatProb?.[id])el.setAttribute('fill',PARTY[seat.centralWinner].color);
    else{const probs=state.mc.seatProb[id],best=Object.entries(probs).sort((a,b)=>b[1]-a[1])[0];el.setAttribute('fill',mixWithDark(PARTY[best[0]].color,best[1]));}
  }
  if(state.selectedSeat)renderDetail(state.selectedSeat);
}
function mixWithDark(hex,prob){const h=hex.replace('#','');const r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);const k=.35+.65*clamp(prob,0,1);return `rgb(${Math.round(r*k)},${Math.round(g*k)},${Math.round(b*k)})`;}

function renderCoalitionButtons(){
  const ps=['lab','con','ref','ld','green','snp','pc','rb','dup','alliance','sdlp','uup','tuv'];$('#coalitionButtons').innerHTML=ps.map(p=>`<button data-party="${p}"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</button>`).join('');
  $$('#coalitionButtons button').forEach(b=>b.addEventListener('click',()=>{const p=b.dataset.party;state.coalition.has(p)?state.coalition.delete(p):state.coalition.add(p);b.classList.toggle('selected',state.coalition.has(p));updateCoalition();}));
}
function updateCoalition(){
  const totals=state.mc?.medians||state.central?.totals||{};const seats=[...state.coalition].reduce((s,p)=>s+(totals[p]||0),0);const threshold=state.mc?.workingThreshold||state.central?.ni?.workingThreshold||CONFIG.majority;$('#coalSeats').textContent=fmt0(seats);$('#coalDistance').textContent=seats>=threshold?`+${fmt0(seats-threshold)}`:`−${fmt0(threshold-seats)}`;
  if(!state.mc?.dist||!state.coalition.size){$('#coalProb').textContent='—';return;}let yes=0;for(let i=0;i<state.mc.sims;i++){let s=0;for(const p of state.coalition)s+=state.mc.dist[p]?.[i]||0;const sf=state.mc.dist.sf?.[i]||0;const t=Math.floor((650-sf)/2)+1;if(s>=t)yes++;}$('#coalProb').textContent=pctFmt(yes/state.mc.sims*100);
}

function bindUi(){
  $('#refreshBtn').addEventListener('click',()=>init(true));
  $('#ukMap').addEventListener('click',event=>{
    const path=event.target instanceof Element?event.target.closest('path.constituency'):null;
    if(path&&$('#ukMap').contains(path))selectSeat(path.dataset.id);
  });
  $('#mapCentralBtn').addEventListener('click',()=>{state.mapMode='central';$('#mapCentralBtn').classList.add('active');$('#mapProbBtn').classList.remove('active');applyMapColors();});
  $('#mapProbBtn').addEventListener('click',()=>{
    if(!state.mc)return;
    state.mapMode='prob';
    $('#mapProbBtn').classList.add('active');
    $('#mapCentralBtn').classList.remove('active');
    applyMapColors();
  });
  $$('[data-window]').forEach(btn=>btn.addEventListener('click',()=>{ $$('[data-window]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const use=btn.dataset.window==='latest'?state.latestAverage:state.average.values;const old=state.average.values;state.average.values=use;renderPolls();state.average.values=old;}));
}

async function init(force=false){
  clearError();
  state.mc=null;
  state.mapMode='central';
  $('#mapCentralBtn')?.classList.add('active');
  $('#mapProbBtn')?.classList.remove('active');
  setMonteCarloPending(true);
  setStatus('Caricamento dati…','loading');
  $('#refreshBtn').disabled=true;
  try{
    if(force){try{localStorage.removeItem(mcCacheKey());}catch(_){ }}
    const [polls,constituencies,geometry,ni,modelParams,mrpLite,subnational,territorialBaseline]=await Promise.all([
      loadPolls(),loadConstituencies(),loadGeometry(),fetchJson(CONFIG.niLocal,5000).catch(()=>null),
      loadModelParams(),fetchJson(CONFIG.mrpLiteLocal,8000).catch(()=>null),loadSubnationalPolls(),loadTerritorialBaseline()
    ]);
    state.polls=polls;state.average=calculateAverage(polls);state.latestAverage=latestPollAverage(polls);
    state.constituencies=constituencies;state.constituencyIndex=new Map(constituencies.map(c=>[c.id,c]));
    state.geometry=geometry;state.ni=ni;state.modelParams=modelParams;state.mrpLite=mrpLite;state.subnational=subnational;state.territorialBaseline=territorialBaseline;
    renderPolls();renderCoalitionButtons();
    if(constituencies.length===650){buildCentral();renderCentral();renderMap();setStatus('Dati aggiornati · simulazione pronta','ok');$('#footerBuild').textContent=`Baseline: 650 collegi · sondaggi: ${state.pollSource} · seat model: ${mrpLiteActive()?`MRP-lite ${(Number(state.mrpLite.holdout_accuracy)*100).toFixed(1)}% holdout`:(partialRakeModelActive()?`raking α=${partialRakeStrength().toFixed(2)}`:'fallback prudente')} · poll subnazionali: ${state.subnational.length} · NI: ${niModuleReady()?'18 collegi simulati':'fallback fisso'}`;await runMonteCarlo(force);}else{
      setStatus('Sondaggi caricati · manca la baseline territoriale','error');showError('La dashboard nazionale è attiva, ma i 650 risultati di collegio non sono ancora nello snapshot locale e il browser non è riuscito a recuperarli direttamente. Esegui la GitHub Action “Update UK election data”: genererà automaticamente baseline e geometrie.');renderMap();
    }
  }catch(err){console.error(err);setStatus('Errore di caricamento','error');showError(`Errore: ${err.message||err}`);}finally{$('#refreshBtn').disabled=false;}
}

bindUi();init(false);
})();
