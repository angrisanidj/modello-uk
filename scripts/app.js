(() => {
'use strict';

const CONFIG = {
  pollsLocal: 'data/polls.json',
  pollsFallback: 'data/polls-fallback.json',
  constituencyLocal: 'data/constituencies-2024.json',
  geometryLocal: 'data/constituencies-2024.geojson',
  niLocal: 'data/ni-2024.json',
  commonsCandidateCsv: 'https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv',
  wikiApi: 'https://en.wikipedia.org/w/api.php?action=parse&page=Opinion_polling_for_the_next_United_Kingdom_general_election&prop=text&format=json&origin=*',
  onsGeo: 'https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC/FeatureServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson',
  halfLifeDays: 7,
  modelLookbackDays: 100,
  mcSims: 50000,
  mcBatch: 1000,
  majority: 326,
  gbSeats: 632,
  niSeats: 18,
  cacheVersion: 'uk-v01-20260826',
  swingLambda: 0.82,
  nationalSigma: {lab:1.35,con:1.35,ref:1.35,ld:0.95,green:0.95,snp:0.50,pc:0.30,rb:0.65,other:0.70},
  regionNoise: 0.035,
  localNoise: 0.055,
};

const PARTY_ORDER = ['lab','con','ref','ld','green','snp','pc','rb','other'];
const PARTY = {
  lab:{name:'Labour',short:'Lab',color:'#e4003b'},
  con:{name:'Conservative',short:'Con',color:'#0087dc'},
  ref:{name:'Reform UK',short:'Ref',color:'#12b6cf'},
  ld:{name:'Liberal Democrats',short:'LD',color:'#faa61a'},
  green:{name:'Green',short:'Green',color:'#6ab023'},
  snp:{name:'SNP',short:'SNP',color:'#f6e642',text:'#111'},
  pc:{name:'Plaid Cymru',short:'PC',color:'#005b54'},
  rb:{name:'Restore Britain',short:'RB',color:'#8752cc'},
  other:{name:'Altri / NI',short:'Altri',color:'#7c8491'},
};

const BASE_GB = {lab:34.6,con:24.4,ref:14.7,ld:12.6,green:6.6,snp:2.6,pc:0.7,rb:0.15,other:3.8};
const MONTHS = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
const OFFLINE = new URLSearchParams(location.search).get('offline') === '1';

const state = {
  polls:[], pollSource:'', average:null, latestAverage:null,
  constituencies:[], byId:new Map(), geometry:null, ni:null,
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
    const x=grouped.get(id), party=mapCandidateParty(r), share=parsePercent(r.Share)||0, votes=Math.round(parsePercent(r.Votes)||0);
    x.shares[party]=(x.shares[party]||0)+share; x.candidates.push({party,party_name:r['Party name']||'',candidate:`${r['Candidate first name']||''} ${r['Candidate surname']||''}`.trim(),votes,share});
  }
  return [...grouped.values()].map(x=>{x.candidates.sort((a,b)=>b.votes-a.votes);x.winner2024=x.candidates[0]?.party||'other';x.winner2024_name=x.candidates[0]?.party_name||'';x.winner2024_candidate=x.candidates[0]?.candidate||'';x.majority2024=(x.candidates[0]?.votes||0)-(x.candidates[1]?.votes||0);x.top_candidates_2024=x.candidates.slice(0,4);delete x.candidates;return x;});
}
async function loadConstituencies(){
  try { const j=await fetchJson(CONFIG.constituencyLocal,7000); if(j?.constituencies?.length===650)return j.constituencies; } catch(_){ }
  if(!OFFLINE) try { const t=await fetchText(CONFIG.commonsCandidateCsv,18000); const c=constituenciesFromCandidateCsv(t); if(c.length===650)return c; } catch(_){ }
  return [];
}
async function loadGeometry(){
  try { const j=await fetchJson(CONFIG.geometryLocal,8000); if(j?.features?.length>=650)return j; } catch(_){ }
  if(!OFFLINE) try { const j=await fetchJson(CONFIG.onsGeo,18000); if(j?.features?.length>=650)return j; } catch(_){ }
  return null;
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

function partyAllowed(p, seat){ if(p==='snp')return /scotland/i.test(seat.country); if(p==='pc')return /wales/i.test(seat.country); return true; }
function normalizeTargets(avg){
  const x={}; let total=0; for(const p of PARTY_ORDER){ x[p]=Math.max(0.05,avg[p]||0); total+=x[p]; }
  for(const p of PARTY_ORDER)x[p]=x[p]/total*100; return x;
}
function projectedShares(seat,target){
  const raw={}; let sum=0;
  for(const p of PARTY_ORDER){
    if(!partyAllowed(p,seat)){raw[p]=0;continue;}
    let base=seat.shares?.[p]||0;
    if(p==='rb')base=Math.max(base,.12); else if(['lab','con','ref','ld','green'].includes(p))base=Math.max(base,.18); else base=Math.max(base,.03);
    const natBase=BASE_GB[p]||.2, ratio=Math.max(.08,target[p]/natBase);
    const lambda=p==='rb'?.50:CONFIG.swingLambda;
    raw[p]=base*Math.pow(ratio,lambda); sum+=raw[p];
  }
  if(sum<=0)return raw; for(const p of PARTY_ORDER)raw[p]=raw[p]/sum*100; return raw;
}
function buildCentral(){
  const target=normalizeTargets(state.average.values), seats=[]; const totals=Object.fromEntries(PARTY_ORDER.map(p=>[p,0]));
  for(const c of state.constituencies){
    if(/northern ireland/i.test(c.country))continue;
    const shares=projectedShares(c,target); const winner=PARTY_ORDER.reduce((best,p)=>shares[p]>(shares[best]??-1)?p:best,PARTY_ORDER[0]); totals[winner]++; seats.push({...c,projected:shares,centralWinner:winner});
  }
  totals.other+=CONFIG.niSeats;
  state.central={target,seats,totals}; state.byId=new Map(seats.map(s=>[s.id,s]));
  return state.central;
}

function hashString(str){ let h=2166136261>>>0; for(let i=0;i<str.length;i++){h^=str.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0; }
function mulberry32(a){return function(){let t=a+=0x6D2B79F5;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return ((t^t>>>14)>>>0)/4294967296;};}
function logistic(rng){const u=clamp(rng(),1e-7,1-1e-7);return Math.log(u/(1-u))/Math.PI*Math.sqrt(3);}
function normalApprox(rng){return (rng()+rng()+rng()+rng()+rng()+rng()-3)*Math.SQRT2;}
function fingerprint(){ const p=state.polls.slice(0,40).map(x=>`${x.date}|${x.pollster}|${x.lab}|${x.con}|${x.ref}|${x.ld}|${x.green}|${x.rb}`).join(';'); return `${CONFIG.cacheVersion}:${hashString(p+'|'+state.constituencies.length)}`; }
function mcCacheKey(){return `focusamerica:${fingerprint()}`;}
function saveMcCache(summary){ try{localStorage.setItem(mcCacheKey(),JSON.stringify(summary));}catch(_){ } }
function loadMcCache(){ try{const x=JSON.parse(localStorage.getItem(mcCacheKey())||'null');if(x?.sims===CONFIG.mcSims&&x?.medians)return x;}catch(_){ }return null; }

function prepareSeatModel(){
  const seats=state.central.seats, target=state.central.target;
  const regions=[...new Set(seats.map(s=>s.region||s.country||'Other'))]; const regionIndex=new Map(regions.map((r,i)=>[r,i]));
  const models=seats.map(s=>{
    const candidates=PARTY_ORDER.filter(p=>partyAllowed(p,s)).map(p=>{
      let base=s.shares?.[p]||0; if(p==='rb')base=Math.max(base,.12); else if(['lab','con','ref','ld','green'].includes(p))base=Math.max(base,.18); else base=Math.max(base,.03);
      const nat=BASE_GB[p]||.2, lambda=p==='rb'?.50:CONFIG.swingLambda;
      return {p,baseLog:Math.log(base),lambda,nat,central:s.projected[p]||0};
    }).sort((a,b)=>b.central-a.central).slice(0,5);
    return {id:s.id,region:regionIndex.get(s.region||s.country||'Other'),candidates};
  });
  return {models,regions,target};
}

async function runMonteCarlo(force=false){
  if(!state.central?.seats?.length)return;
  if(!force){const cached=loadMcCache();if(cached){state.mc=cached;renderMc();applyMapColors();return;}}
  const {models,regions,target}=prepareSeatModel(), P=PARTY_ORDER.length, N=CONFIG.mcSims, nSeats=models.length;
  const partyIndex=new Map(PARTY_ORDER.map((p,i)=>[p,i]));
  const dists=PARTY_ORDER.map(()=>new Uint16Array(N)); const wins=new Uint32Array(nSeats*P); const rng=mulberry32(hashString(fingerprint()));
  let hung=0, labMaj=0,conMaj=0,refMaj=0; const largestCounts=Object.fromEntries(PARTY_ORDER.map(p=>[p,0]));
  $('#mcStatus').textContent='Calcolo in corso'; $('#mcProgress').value=0;
  for(let start=0;start<N;start+=CONFIG.mcBatch){
    const end=Math.min(N,start+CONFIG.mcBatch);
    for(let sim=start;sim<end;sim++){
      const drawn={}; let sum=0;
      for(const p of PARTY_ORDER){const sigma=CONFIG.nationalSigma[p]||.8;drawn[p]=Math.max(.05,target[p]+normalApprox(rng)*sigma);sum+=drawn[p];}
      for(const p of PARTY_ORDER)drawn[p]=drawn[p]/sum*100;
      const natShift={}; for(const p of PARTY_ORDER)natShift[p]=(p==='rb'?.50:CONFIG.swingLambda)*Math.log(Math.max(.05,drawn[p])/(BASE_GB[p]||.2));
      const regNoise=Array.from({length:regions.length},()=>Object.fromEntries(PARTY_ORDER.map(p=>[p,logistic(rng)*CONFIG.regionNoise])));
      const counts=new Uint16Array(P);
      for(let si=0;si<nSeats;si++){
        const m=models[si]; let bestP='other',bestScore=-Infinity;
        for(const cand of m.candidates){const score=cand.baseLog+natShift[cand.p]+regNoise[m.region][cand.p]+logistic(rng)*CONFIG.localNoise;if(score>bestScore){bestScore=score;bestP=cand.p;}}
        const pi=partyIndex.get(bestP);counts[pi]++;wins[si*P+pi]++;
      }
      counts[partyIndex.get('other')]+=CONFIG.niSeats;
      let largest='lab',largestN=-1;
      for(let pi=0;pi<P;pi++){dists[pi][sim]=counts[pi];if(counts[pi]>largestN){largestN=counts[pi];largest=PARTY_ORDER[pi];}}
      largestCounts[largest]++;
      const lm=counts[partyIndex.get('lab')]>=CONFIG.majority, cm=counts[partyIndex.get('con')]>=CONFIG.majority, rm=counts[partyIndex.get('ref')]>=CONFIG.majority;
      if(lm)labMaj++;if(cm)conMaj++;if(rm)refMaj++;if(!lm&&!cm&&!rm)hung++;
    }
    $('#mcProgress').value=end; $('#mcCount').textContent=`${fmt0(end)} / ${fmt0(N)}`; await sleepFrame();
  }
  const medians={}, intervals={}, distPlain={};
  for(let pi=0;pi<P;pi++){
    const p=PARTY_ORDER[pi], arr=Array.from(dists[pi]).sort((a,b)=>a-b); medians[p]=quantileSorted(arr,.5); intervals[p]=[quantileSorted(arr,.1),quantileSorted(arr,.9)]; distPlain[p]=Array.from(dists[pi]);
  }
  const seatProb={}; for(let si=0;si<nSeats;si++){const obj={};for(let pi=0;pi<P;pi++)obj[PARTY_ORDER[pi]]=wins[si*P+pi]/N;seatProb[models[si].id]=obj;}
  const summary={sims:N,medians,intervals,labMaj:labMaj/N,conMaj:conMaj/N,refMaj:refMaj/N,hung:hung/N,largest:Object.fromEntries(PARTY_ORDER.map(p=>[p,largestCounts[p]/N])),seatProb,dist:distPlain,fingerprint:fingerprint()};
  state.mc=summary; saveMcCache(summary); $('#mcStatus').textContent='Completato'; renderMc(); applyMapColors();
}
function quantileSorted(arr,q){const i=Math.floor((arr.length-1)*q);return arr[i];}

function renderCentral(){
  const totals=state.central.totals; $('#projectionTitle').textContent='Proiezione centrale provvisoria'; $('#projectionSubtitle').textContent='Conversione territoriale 2024 → oggi, prima della calibrazione completa del backtest.';
  renderSeats(totals,null); $('#kpiLargest').textContent=PARTY[Object.entries(totals).sort((a,b)=>b[1]-a[1])[0][0]].short; $('#kpiLargestMeta').textContent='proiezione centrale';
}
function renderMc(){
  const m=state.mc;if(!m)return; renderSeats(m.medians,m.intervals); $('#projectionTitle').textContent='Distribuzione dei seggi';$('#projectionSubtitle').textContent='Mediana delle 50.000 simulazioni; intervallo centrale 80% tra parentesi.';
  $('#probLabMaj').textContent=pctFmt(m.labMaj*100);$('#probConMaj').textContent=pctFmt(m.conMaj*100);$('#probRefMaj').textContent=pctFmt(m.refMaj*100);$('#probHung').textContent=pctFmt(m.hung*100);
  const largest=Object.entries(m.largest).sort((a,b)=>b[1]-a[1])[0];$('#kpiLargest').textContent=PARTY[largest[0]].short;$('#kpiLargestMeta').textContent=`${pctFmt(largest[1]*100)} di essere il primo partito`;
  const maj=Math.max(m.labMaj,m.conMaj,m.refMaj);$('#kpiMajority').textContent=pctFmt(maj*100);const who=m.labMaj===maj?'Labour':m.conMaj===maj?'Conservative':'Reform';$('#kpiMajorityMeta').textContent=`${who} · soglia 326`;
  $('#mcStatus').textContent='Completato';$('#mcCount').textContent=`${fmt0(m.sims)} / ${fmt0(m.sims)}`;$('#mcProgress').value=m.sims; updateCoalition();
}
function renderSeats(totals,intervals){
  const sum=PARTY_ORDER.reduce((s,p)=>s+(totals[p]||0),0)||650; $('#seatStrip').innerHTML=PARTY_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<span style="width:${(totals[p]/sum)*100}%;background:${PARTY[p].color}" title="${PARTY[p].name}: ${fmt0(totals[p])}"></span>`).join('');
  $('#seatTable').innerHTML=PARTY_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<div class="seat-row"><div class="left"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</div><strong>${fmt0(totals[p])}${intervals?.[p]?` <small>${fmt0(intervals[p][0])}–${fmt0(intervals[p][1])}</small>`:''}</strong></div>`).join('');
  renderHemicycle(totals);
}
function hemicyclePoints(){
  const pts=[]; for(let row=0;row<18;row++){const r=63+row*9.6,cap=Math.max(8,Math.round(Math.PI*r/11));for(let j=0;j<cap;j++){const t=Math.PI-(j/(cap-1))*Math.PI;pts.push({x:310+r*Math.cos(t),y:297-r*Math.sin(t),r});}}
  pts.sort((a,b)=>a.x-b.x||b.r-a.r); if(pts.length>650){const remove=pts.length-650;const keep=[];for(let i=0;i<pts.length;i++){if(Math.floor((i+1)*remove/pts.length)!==Math.floor(i*remove/pts.length))continue;keep.push(pts[i]);}return keep.slice(0,650);}return pts.slice(0,650);
}
const hemiPts=hemicyclePoints();
function renderHemicycle(totals){
  const seats=[];for(const p of PARTY_ORDER){for(let i=0;i<Math.round(totals[p]||0);i++)seats.push(p);}while(seats.length<650)seats.push('other');if(seats.length>650)seats.length=650;
  $('#hemicycle').innerHTML=hemiPts.map((pt,i)=>`<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="3.7" fill="${PARTY[seats[i]||'other'].color}" opacity=".96"><title>${PARTY[seats[i]||'other'].name}</title></circle>`).join('');
}

function geometryCode(props){return props.PCON24CD||props.PCON24CDH||props.PCONCD||props.GSS_CODE||props.code||props.id||'';}
function geometryName(props){return props.PCON24NM||props.PCONNM||props.NAME||props.name||'';}
function eachCoord(geom,fn){if(!geom)return;if(geom.type==='Polygon'){for(const ring of geom.coordinates)for(const c of ring)fn(c);}else if(geom.type==='MultiPolygon'){for(const poly of geom.coordinates)for(const ring of poly)for(const c of ring)fn(c);}}
function pathForGeometry(geom,project){
  if(!geom)return''; const polyPath=poly=>poly.map(ring=>ring.map((c,i)=>`${i?'L':'M'}${project(c)[0].toFixed(2)},${project(c)[1].toFixed(2)}`).join(' ')+' Z').join(' ');
  return geom.type==='Polygon'?polyPath(geom.coordinates):geom.type==='MultiPolygon'?geom.coordinates.map(polyPath).join(' '):'';
}
function renderMap(){
  if(!state.geometry?.features?.length){$('#mapEmpty').style.display='grid';$('#mapMeta').textContent='Geometrie non disponibili: esegui la build dati.';return;}
  const features=state.geometry.features; let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const f of features)eachCoord(f.geometry,c=>{minX=Math.min(minX,c[0]);maxX=Math.max(maxX,c[0]);minY=Math.min(minY,c[1]);maxY=Math.max(maxY,c[1]);});
  const pad=24,W=640,H=760,s=Math.min((W-2*pad)/(maxX-minX),(H-2*pad)/(maxY-minY));const project=c=>[pad+(c[0]-minX)*s,H-pad-(c[1]-minY)*s];
  $('#ukMap').innerHTML=features.map(f=>{const id=geometryCode(f.properties||{}), name=geometryName(f.properties||{}), seat=state.byId.get(id);const fill=seat?PARTY[seat.centralWinner]?.color:partyColorFrom2024(id);return `<path class="constituency" data-id="${escapeHtml(id)}" d="${pathForGeometry(f.geometry,project)}" fill="${fill||'#414957'}"><title>${escapeHtml(seat?.name||name||id)}</title></path>`;}).join('');
  $('#mapEmpty').style.display='none'; $('#mapMeta').textContent=`${features.length} geometrie ONS · BGC 20 m`;
  $$('#ukMap .constituency').forEach(el=>el.addEventListener('click',()=>selectSeat(el.dataset.id)));
  applyMapColors();
}
function partyColorFrom2024(id){const c=state.constituencies.find(x=>x.id===id);return PARTY[c?.winner2024||'other'].color;}
function selectSeat(id){state.selectedSeat=id;$$('#ukMap .constituency').forEach(x=>x.classList.toggle('selected',x.dataset.id===id));renderDetail(id);}
function renderDetail(id){
  const seat=state.byId.get(id)||state.constituencies.find(x=>x.id===id);if(!seat)return;$('#detailName').textContent=seat.name;$('#detailRegion').textContent=[seat.region,seat.country].filter(Boolean).join(' · ');
  const proj=seat.projected||{},prob=state.mc?.seatProb?.[id];const rows=PARTY_ORDER.filter(p=>(proj[p]||0)>.15).sort((a,b)=>(proj[b]||0)-(proj[a]||0)).slice(0,6);
  $('#detailBody').innerHTML=`<div class="detail-stat"><span>Vincitore 2024</span><strong>${escapeHtml(seat.winner2024_name||PARTY[seat.winner2024]?.name||'Altro')}</strong></div><div class="detail-stat"><span>Proiezione centrale</span><strong>${PARTY[seat.centralWinner||seat.winner2024]?.name||'—'}</strong></div><div class="detail-score">${rows.map(p=>`<div><span>${PARTY[p].short}</span><span class="mini-track"><i style="width:${clamp((proj[p]||0)*2,0,100)}%;background:${PARTY[p].color}"></i></span><strong>${prob?pctFmt(prob[p]*100):pctFmt(proj[p]||0)}</strong></div>`).join('')}</div><p class="small-note">${prob?'Valori a destra = probabilità di vittoria Monte Carlo.':'Valori a destra = quota centrale stimata; probabilità disponibili dopo il Monte Carlo.'}</p>`;
}
function applyMapColors(){
  if(!$('#ukMap'))return; for(const el of $$('#ukMap .constituency')){const id=el.dataset.id,seat=state.byId.get(id);if(!seat)continue;if(state.mapMode==='central'||!state.mc?.seatProb?.[id])el.setAttribute('fill',PARTY[seat.centralWinner].color);else{const probs=state.mc.seatProb[id],best=Object.entries(probs).sort((a,b)=>b[1]-a[1])[0];el.setAttribute('fill',mixWithDark(PARTY[best[0]].color,best[1]));}}
  if(state.selectedSeat)renderDetail(state.selectedSeat);
}
function mixWithDark(hex,prob){const h=hex.replace('#','');const r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);const k=.35+.65*clamp(prob,0,1);return `rgb(${Math.round(r*k)},${Math.round(g*k)},${Math.round(b*k)})`;}

function renderCoalitionButtons(){
  const ps=['lab','con','ref','ld','green','snp','pc','rb'];$('#coalitionButtons').innerHTML=ps.map(p=>`<button data-party="${p}"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</button>`).join('');
  $$('#coalitionButtons button').forEach(b=>b.addEventListener('click',()=>{const p=b.dataset.party;state.coalition.has(p)?state.coalition.delete(p):state.coalition.add(p);b.classList.toggle('selected',state.coalition.has(p));updateCoalition();}));
}
function updateCoalition(){
  const totals=state.mc?.medians||state.central?.totals||{};const seats=[...state.coalition].reduce((s,p)=>s+(totals[p]||0),0);$('#coalSeats').textContent=fmt0(seats);$('#coalDistance').textContent=seats>=CONFIG.majority?`+${fmt0(seats-CONFIG.majority)}`:`−${fmt0(CONFIG.majority-seats)}`;
  if(!state.mc?.dist||!state.coalition.size){$('#coalProb').textContent=state.coalition.size?'—':'—';return;}let yes=0;for(let i=0;i<state.mc.sims;i++){let s=0;for(const p of state.coalition)s+=state.mc.dist[p]?.[i]||0;if(s>=CONFIG.majority)yes++;}$('#coalProb').textContent=pctFmt(yes/state.mc.sims*100);
}

function bindUi(){
  $('#refreshBtn').addEventListener('click',()=>init(true));
  $('#mapCentralBtn').addEventListener('click',()=>{state.mapMode='central';$('#mapCentralBtn').classList.add('active');$('#mapProbBtn').classList.remove('active');applyMapColors();});
  $('#mapProbBtn').addEventListener('click',()=>{state.mapMode='prob';$('#mapProbBtn').classList.add('active');$('#mapCentralBtn').classList.remove('active');applyMapColors();});
  $$('[data-window]').forEach(btn=>btn.addEventListener('click',()=>{ $$('[data-window]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');const use=btn.dataset.window==='latest'?state.latestAverage:state.average.values;const old=state.average.values;state.average.values=use;renderPolls();state.average.values=old;}));
}

async function init(force=false){
  clearError();setStatus('Caricamento dati…','loading');$('#refreshBtn').disabled=true;
  try{
    if(force){try{localStorage.removeItem(mcCacheKey());}catch(_){ }}
    const [polls,constituencies,geometry,ni]=await Promise.all([loadPolls(),loadConstituencies(),loadGeometry(),fetchJson(CONFIG.niLocal,5000).catch(()=>null)]);
    state.polls=polls;state.average=calculateAverage(polls);state.latestAverage=latestPollAverage(polls);state.constituencies=constituencies;state.geometry=geometry;state.ni=ni;renderPolls();renderCoalitionButtons();
    if(constituencies.length===650){buildCentral();renderCentral();renderMap();setStatus('Dati aggiornati · simulazione pronta','ok');$('#footerBuild').textContent=`Baseline: 650 collegi · sondaggi: ${state.pollSource}`;await runMonteCarlo(force);}else{
      setStatus('Sondaggi caricati · manca la baseline territoriale','error');showError('La dashboard nazionale è attiva, ma i 650 risultati di collegio non sono ancora nello snapshot locale e il browser non è riuscito a recuperarli direttamente. Esegui la GitHub Action “Update UK election data”: genererà automaticamente baseline e geometrie.');renderMap();
    }
  }catch(err){console.error(err);setStatus('Errore di caricamento','error');showError(`Errore: ${err.message||err}`);}finally{$('#refreshBtn').disabled=false;}
}

bindUi();init(false);
})();
