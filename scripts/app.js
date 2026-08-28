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
  mcSummaryLocal: 'data/monte-carlo-current.json',
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
  cacheVersion: 'uk-v0931-20260827-constituency-explorer-scenario-builder',
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
  con:{name:'Conservative',short:'Con',color:'#2f8fff'},
  ref:{name:'Reform UK',short:'Ref',color:'#24c7c9'},
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
const URL_PARAMS = new URLSearchParams(location.search);
const OFFLINE = URL_PARAMS.get('offline') === '1';
const MC_BUILD_MODE = OFFLINE || URL_PARAMS.get('social_card_build') === '1' || URL_PARAMS.get('mc_build') === '1';

const state = {
  polls:[], pollSource:'', average:null, latestAverage:null, pollAverageView:'weighted', pollTrendRange:180, pollTrendFocus:null,
  constituencies:[], constituencyIndex:new Map(), byId:new Map(), geometry:null, ni:null,
  modelParams:null, mrpLite:null, precomputedMc:null, subnational:[], territorialBaseline:null, geographicTargets:null,
  mapPaths:new Map(), selectedPath:null,
  central:null, mc:null, representative:null, customScenario:null, scenarioHemicycleActive:false, selectedSeat:null, mapMode:'central', mapLayout:'geo', coalition:new Set(), explorerPage:1, explorerPageSize:25, explorerMatchingIds:null, pollPage:1, pollPageSize:25, hemiFocus:null,
};

const MAP_BASE_VIEW={x:0,y:0,w:640,h:760};
const mapZoomState={
  base:{...MAP_BASE_VIEW},view:{...MAP_BASE_VIEW},maxZoom:9,panning:false,pointerId:null,
  startX:0,startY:0,startView:null,moved:false,suppressClick:false
};

const $ = sel => document.querySelector(sel);
const $$ = sel => Array.from(document.querySelectorAll(sel));
const fmt1 = n => Number.isFinite(n) ? n.toLocaleString('it-IT',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—';
const fmt0 = n => Number.isFinite(n) ? String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g,'.') : '—';
const pctFmt = n => Number.isFinite(n) ? `${fmt1(n)}%` : '—';
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const sleepFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve()));

function setStatus(text, kind='loading') {
  const textEl=$('#statusText'),dot=$('#statusDot');
  if(textEl)textEl.textContent=text;
  if(dot)dot.className=`dot ${kind}`;
  const wrap=textEl?.closest?.('.status');
  if(wrap){wrap.classList.remove('is-loading','is-ok','is-error');wrap.classList.add(`is-${kind}`);}
}
function showError(text) {
  const el = $('#errorBox'); el.textContent = text; el.style.display = 'block';
}
function clearError(){ $('#errorBox').style.display='none'; }

// v0.9.49 — explicit user-view context. Frontend only.
function pollFiltersActive(){
  return ['pollSearch','pollPollster','pollArea'].some(id=>String($(`#${id}`)?.value||'').trim()!=='');
}
function activeScenarioSections(){
  if(!state.customScenario)return [];
  const out=[];
  if(state.scenarioHemicycleActive)out.push('Emiciclo');
  if(state.mapMode==='custom')out.push('Mappa');
  if($('#regionalSource')?.value==='custom')out.push('Regioni');
  if($('#seatSource')?.value==='custom')out.push('Collegi');
  return out;
}
function pollFilterLabel(id,value){
  if(id==='pollSearch')return `Sondaggi: ${value}`;
  if(id==='pollPollster')return `Istituto: ${value}`;
  if(id==='pollArea')return `Area sondaggi: ${value}`;
  return value;
}
function activeViewContext(){
  const seatIds=['seatSearch','seatCountry','seatRegion','seatWinner','seatWinner2024','seatStatus'];
  const pollIds=['pollSearch','pollPollster','pollArea'];
  const seatFilters=seatIds.map(id=>({kind:'seat',id,value:String($(`#${id}`)?.value||'').trim()})).filter(x=>x.value);
  const pollFilters=pollIds.map(id=>({kind:'poll',id,value:String($(`#${id}`)?.value||'').trim()})).filter(x=>x.value);
  const scenarioSections=activeScenarioSections();
  return {seatFilters,pollFilters,scenarioSections,scenario:scenarioSections.length>0,filtered:seatFilters.length>0||pollFilters.length>0};
}
function syncViewContextBar(){
  const root=$('#viewStateBar');if(!root)return;
  const ctx=activeViewContext();
  if(!ctx.scenario&&!ctx.filtered){
    root.hidden=true;root.classList.remove('is-active','is-filtered','is-scenario','is-mixed','below-desktop-sticky');document.body.classList.remove('has-active-view');syncMobileNowcastVisibility();return;
  }
  document.body.classList.add('has-active-view');root.hidden=false;
  root.classList.toggle('is-filtered',ctx.filtered&&!ctx.scenario);root.classList.toggle('is-scenario',ctx.scenario&&!ctx.filtered);root.classList.toggle('is-mixed',ctx.scenario&&ctx.filtered);root.classList.add('is-active');
  const title=$('#viewStateTitle'),detail=$('#viewStateDetail'),kicker=$('#viewStateKicker'),chips=$('#viewStateChips');
  if(kicker)kicker.textContent=ctx.scenario?'Vista alternativa':'Vista parziale';
  if(title)title.textContent=ctx.scenario&&ctx.filtered?'Scenario personalizzato + filtri':ctx.scenario?'Scenario personalizzato':'Vista filtrata';
  const parts=['Non è il nowcast completo'];
  if(ctx.scenario)parts.push(`scenario utente: ${ctx.scenarioSections.join(', ')}`);
  if(ctx.seatFilters.length){const n=state.explorerMatchingIds?.size;parts.push(Number.isFinite(n)?`${fmt0(n)} di 650 collegi`:`collegi filtrati`);}
  if(ctx.pollFilters.length&&state.polls?.length){let n=null;try{n=pollTableFiltered().length;}catch(_){}parts.push(Number.isFinite(n)?`${fmt0(n)} sondaggi visibili`:'sondaggi filtrati');}
  if(detail)detail.textContent=parts.join(' · ');
  const html=[];
  if(ctx.scenario)html.push(`<button type="button" class="view-state-chip scenario" data-view-clear-scenario title="Disattiva lo scenario nelle viste, mantenendolo disponibile nel builder"><span>Scenario · ${escapeHtml(ctx.scenarioSections.join(' + '))}</span><b aria-hidden="true">×</b></button>`);
  for(const x of ctx.seatFilters)html.push(`<button type="button" class="view-state-chip" data-view-clear-filter="${x.id}" data-view-filter-kind="seat" title="Rimuovi questo filtro"><span>${escapeHtml(mapFilterLabel(x.id,x.value))}</span><b aria-hidden="true">×</b></button>`);
  for(const x of ctx.pollFilters)html.push(`<button type="button" class="view-state-chip" data-view-clear-filter="${x.id}" data-view-filter-kind="poll" title="Rimuovi questo filtro"><span>${escapeHtml(pollFilterLabel(x.id,x.value))}</span><b aria-hidden="true">×</b></button>`);
  if(chips)chips.innerHTML=html.join('');
  const desktopSticky=$('#desktopNowcastSticky');root.classList.toggle('below-desktop-sticky',!!desktopSticky?.classList.contains('is-visible'));
  $('#mobileNowcastSticky')?.classList.remove('is-visible');
}
function clearSeatFiltersRaw(){
  for(const id of ['seatSearch','seatCountry','seatRegion','seatWinner','seatWinner2024','seatStatus']){const el=$(`#${id}`);if(el)el.value='';}
  const sort=$('#seatSort');if(sort)sort.value='uncertainty';
}
function clearPollFiltersRaw(){for(const id of ['pollSearch','pollPollster','pollArea']){const el=$(`#${id}`);if(el)el.value='';}}
function renderNowcastSeatProjection(){
  const totals=state.mc?.medians||state.central?.totals;if(!totals)return;
  renderSeats(totals,state.mc?.intervals||null);
  if(state.mc){
    $('#projectionTitle').textContent='Scenario rappresentativo Monte Carlo';
    $('#projectionSubtitle').textContent='Mediane di 50.000 simulazioni; intervallo centrale 80% tra parentesi. La mappa viene ricomposta per aderire il più possibile alle mediane dei seggi.';
  }else{
    $('#projectionTitle').textContent='Scenario alla media dei sondaggi';
    $('#projectionSubtitle').textContent='Proiezione centrale del nowcast; la distribuzione probabilistica sarà disponibile al termine del Monte Carlo.';
  }
}
function renderCustomSeatProjection(){
  if(!state.customScenario?.totals)return;
  renderSeats(state.customScenario.totals,null);
  $('#projectionTitle').textContent='Scenario personalizzato';
  $('#projectionSubtitle').textContent='Emiciclo e distribuzione dei seggi mostrano lo scenario deterministico costruito dall’utente. Intervalli e probabilità restano quelli del nowcast di produzione.';
}
function deactivateCustomScenarioViews(){
  const seatSource=$('#seatSource');if(seatSource)seatSource.value='live';
  const regional=$('#regionalSource');if(regional)regional.value='live';
  if(state.mapMode==='custom')state.mapMode=state.mc?.seatProb?'representative':'central';
  state.scenarioHemicycleActive=false;renderNowcastSeatProjection();
  state.explorerPage=1;applyMapColors();renderMarginals();renderRegionalDashboard();syncViewContextBar();
}
function activateCustomScenarioViews(){
  if(!state.customScenario)return;
  const seatSource=$('#seatSource');if(seatSource){const o=seatSource.querySelector('option[value="custom"]');if(o)o.disabled=false;seatSource.value='custom';}
  const regional=$('#regionalSource');if(regional){const o=regional.querySelector('option[value="custom"]');if(o)o.disabled=false;regional.value='custom';}
  state.scenarioHemicycleActive=true;renderCustomSeatProjection();
  state.mapMode='custom';state.explorerPage=1;applyMapColors();renderMarginals();renderRegionalDashboard();syncViewContextBar();
}
function returnToFullNowcast(){
  clearSeatFiltersRaw();clearPollFiltersRaw();state.pollPage=1;state.explorerPage=1;
  if(state.customScenario)resetCustomScenario();else deactivateCustomScenarioViews();
  renderPolls();renderMarginals();renderRegionalDashboard();applyMapColors();syncViewContextBar();
}
function bindViewContextBar(){
  const root=$('#viewStateBar');if(!root||root.dataset.bound==='1')return;root.dataset.bound='1';
  root.addEventListener('click',e=>{
    const clearScenario=e.target.closest?.('[data-view-clear-scenario]');if(clearScenario){deactivateCustomScenarioViews();return;}
    const btn=e.target.closest?.('[data-view-clear-filter]');if(!btn)return;const el=$(`#${btn.dataset.viewClearFilter}`);if(el)el.value='';
    if(btn.dataset.viewFilterKind==='poll'){state.pollPage=1;renderPolls();}else{state.explorerPage=1;renderMarginals();}
    syncViewContextBar();
  });
  $('#returnFullNowcastBtn')?.addEventListener('click',returnToFullNowcast);
}

function setRefreshReview(kind,title,detail='',changes=null){
  const box=$('#refreshReview'),head=$('#refreshReviewTitle'),copy=$('#refreshReviewDetail');
  if(!box)return;
  box.hidden=false;
  box.className=`refresh-review is-${kind}`;
  box.setAttribute('aria-live',(kind==='changed'||kind==='error')?'assertive':'polite');
  if(head)head.textContent=title;
  if(copy)copy.textContent=detail;
  renderRefreshReviewChanges(changes);
}
function normalizePollText(value){
  return String(value??'').normalize('NFKD').toLowerCase().replace(/\[[^\]]*\]/g,'').replace(/\s+/g,' ').trim();
}
function normalizePollArea(value){
  const x=normalizePollText(value);
  if(x==='gb'||x.includes('great britain'))return 'gb';
  if(x==='uk'||x.includes('united kingdom'))return 'uk';
  if(x.includes('scotland'))return 'scotland';
  if(x.includes('wales'))return 'wales';
  return x;
}
function pollIdentityKey(p){
  // Stable identity intentionally excludes sample size and vote shares: those are
  // model inputs that may be corrected for the same published poll.
  return [p?.date||'',normalizePollText(p?.pollster),normalizePollArea(p?.area)].join('|');
}
function pollVoteSignature(p){
  return ['lab','con','ref','ld','green','snp','pc','rb','other'].map(k=>{
    const n=Number(p?.[k]);return Number.isFinite(n)?n.toFixed(2):'';
  }).join('|');
}
function pollModelSignature(p){
  return `${Math.round(Number(p?.sample)||0)}|${pollVoteSignature(p)}`;
}
function groupPollsByIdentity(rows){
  const grouped=new Map();
  for(const row of rows||[]){const key=pollIdentityKey(row);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(row);}
  return grouped;
}
function reviewPollingChanges(current,live){
  const all=[...(current||[]),...(live||[])].filter(x=>x?.date).map(x=>x.date).sort();
  const latest=all.at(-1)||'';
  const d=latest?new Date(`${latest}T12:00:00Z`):new Date();d.setUTCDate(d.getUTCDate()-21);
  const cutoff=d.toISOString().slice(0,10);
  const currentRecent=(current||[]).filter(x=>(x?.date||'')>=cutoff),liveRecent=(live||[]).filter(x=>(x?.date||'')>=cutoff);
  const oldGroups=groupPollsByIdentity(currentRecent),newGroups=groupPollsByIdentity(liveRecent),keys=new Set([...oldGroups.keys(),...newGroups.keys()]);
  const added=[],corrected=[],removed=[];
  for(const key of keys){
    const oldRows=[...(oldGroups.get(key)||[])],newRows=[...(newGroups.get(key)||[])];
    // First remove exact model-equivalent matches. This prevents harmless source
    // formatting/client/reference changes from looking like new polls.
    for(let i=newRows.length-1;i>=0;i--){
      const sig=pollModelSignature(newRows[i]),j=oldRows.findIndex(row=>pollModelSignature(row)===sig);
      if(j>=0){newRows.splice(i,1);oldRows.splice(j,1);}
    }
    // Remaining rows under the same date+pollster+area are corrections, not new polls.
    const paired=Math.min(oldRows.length,newRows.length);
    for(let i=0;i<paired;i++)corrected.push(newRows[i]);
    if(newRows.length>paired)added.push(...newRows.slice(paired));
    if(oldRows.length>paired)removed.push(...oldRows.slice(paired));
  }
  const byDate=(a,b)=>(b?.date||'').localeCompare(a?.date||'')||normalizePollText(a?.pollster).localeCompare(normalizePollText(b?.pollster));
  added.sort(byDate);corrected.sort(byDate);removed.sort(byDate);
  return {changed:!!(added.length||corrected.length||removed.length),added,corrected,removed};
}
function pollReviewDescription(p){
  if(!p)return 'Fonte nazionale controllata.';
  const normArea=normalizePollArea(p.area),area=normArea==='gb'?'GB':normArea==='uk'?'UK':regionalDisplayName(p.area||'');
  const bits=[p.pollster||'Istituto non indicato',p.date?formatDate(p.date):null,area||null,Number(p.sample)>0?`n=${fmt0(Number(p.sample))}`:null].filter(Boolean);
  return bits.join(' · ');
}
function pollReviewCountLabel(n,singular,plural){return `${n} ${n===1?singular:plural}`;}
function renderRefreshReviewChanges(review){
  const details=$('#refreshReviewChanges'),summary=$('#refreshReviewChangesSummary'),body=$('#refreshReviewChangesBody');
  if(!details||!summary||!body)return;
  const groups=review?[['added','Nuovi',review.added||[]],['corrected','Corretti',review.corrected||[]],['removed','Rimossi',review.removed||[]]]:[];
  const total=groups.reduce((n,g)=>n+g[2].length,0);
  if(!total){details.hidden=true;details.open=false;body.innerHTML='';return;}
  const labels=[];
  if(review.added?.length)labels.push(pollReviewCountLabel(review.added.length,'nuovo','nuovi'));
  if(review.corrected?.length)labels.push(pollReviewCountLabel(review.corrected.length,'corretto','corretti'));
  if(review.removed?.length)labels.push(pollReviewCountLabel(review.removed.length,'rimosso','rimossi'));
  summary.textContent=`Dettaglio rilevazioni · ${labels.join(' · ')}`;
  body.innerHTML=groups.filter(([, ,rows])=>rows.length).map(([kind,label,rows])=>`<section class="refresh-review-group is-${kind}"><strong>${label}</strong>${rows.map(row=>`<div class="refresh-review-row"><span>${escapeHtml(pollReviewDescription(row))}</span></div>`).join('')}</section>`).join('');
  details.hidden=false;
  details.open=total<=4;
}
function validateLivePollSnapshot(live){
  const suspicious=(live||[]).filter(p=>Number(p?.sample)>0&&Number(p.sample)<100);
  if(suspicious.length){throw new Error(`Verifica annullata: campione non plausibile letto dalla fonte (${pollReviewDescription(suspicious[0])}). Nessun Monte Carlo è stato avviato.`);}
  const badPollster=(live||[]).find(p=>/\[\d+\]\s*$/.test(String(p?.pollster||'')));
  if(badPollster)throw new Error('Verifica annullata: la fonte contiene riferimenti bibliografici non ripuliti. Nessun Monte Carlo è stato avviato.');
}
async function fetchLiveNationalPolls(){
  if(OFFLINE)throw new Error('Verifica in tempo reale non disponibile in modalità offline.');
  const j=await fetchJson(`${CONFIG.wikiApi}&_=${Date.now()}`,14000),html=j?.parse?.text?.['*'];
  if(!html)throw new Error('La fonte MediaWiki non ha restituito dati utilizzabili.');
  const polls=parseWikipediaPolls(html);
  if(polls.length<20)throw new Error('La fonte live ha restituito troppo pochi sondaggi per una verifica sicura.');
  return polls;
}

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
function cleanWikiCellText(cell){
  if(!cell)return '';
  const clone=cell.cloneNode(true);
  clone.querySelectorAll('sup.reference,.reference,.mw-ref,.mw-reference-text,style,script').forEach(el=>el.remove());
  return clone.textContent.replace(/\[[0-9]+\]/g,'').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
}
function parsePollSample(text){
  const clean=String(text??'').replace(/\[[^\]]*\]/g,'').replace(/\u00a0/g,' ').trim();
  const m=clean.match(/\b\d{1,3}(?:[.,\s]\d{3})+\b|\b\d{3,6}\b/);
  return m?Number(m[0].replace(/\D/g,'')):0;
}
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
    const heads=Array.from(rows[0].querySelectorAll('th,td')).map(x=>cleanWikiCellText(x).toLowerCase());
    const idx={};
    heads.forEach((h,i)=>{
      if(h.includes('date')&&h.includes('conduct'))idx.date=i; else if(h==='pollster')idx.pollster=i; else if(h==='client')idx.client=i;
      else if(h==='area')idx.area=i; else if(h.includes('sample'))idx.sample=i; else if(h==='lab')idx.lab=i; else if(h==='con')idx.con=i;
      else if(h==='ref')idx.ref=i; else if(h==='ld')idx.ld=i; else if(h==='grn')idx.green=i; else if(h==='snp')idx.snp=i; else if(h==='pc')idx.pc=i;
      else if(h==='rb')idx.rb=i; else if(h.startsWith('other'))idx.other=i;
    });
    if(['date','pollster','area','lab','con','ref','ld','green'].some(k=>idx[k]==null))continue;
    for(const tr of rows.slice(1)){
      const cells=Array.from(tr.querySelectorAll(':scope > th,:scope > td')).map(cleanWikiCellText);
      if(cells.length<=Math.max(...Object.values(idx)))continue;
      const date=parseEndDate(cells[idx.date],year); if(!date)continue;
      const pollster=cells[idx.pollster]; if(!pollster||/election|by-election/i.test(pollster))continue;
      const rec={date,fieldwork:cells[idx.date],pollster,client:idx.client!=null?cells[idx.client]:'',area:String(cells[idx.area]).toUpperCase(),sample:idx.sample!=null?parsePollSample(cells[idx.sample]):0};
      for(const p of ['lab','con','ref','ld','green','snp','pc','rb','other']) rec[p]=idx[p]!=null?parsePercent(cells[idx[p]]):null;
      const key=[date,normalizePollText(pollster),normalizePollArea(rec.area),normalizePollText(rec.client),rec.sample,pollVoteSignature(rec)].join('|'); if(seen.has(key))continue; seen.add(key); out.push(rec);
    }
  }
  return out.sort((a,b)=>b.date.localeCompare(a.date));
}

async function loadPolls(){
  try { const j=await fetchJson(CONFIG.pollsLocal,5000); if(j?.polls?.length>=20){state.pollSource='archivio automatico';return j.polls;} } catch(_){ }
  if(!OFFLINE) try { const j=await fetchJson(CONFIG.wikiApi,12000); const polls=parseWikipediaPolls(j.parse.text['*']); if(polls.length>=20){state.pollSource='MediaWiki in tempo reale';return polls;} } catch(_){ }
  const f=await fetchJson(CONFIG.pollsFallback,5000); state.pollSource='archivio di sicurezza'; return f.polls||[];
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
function historicalAverageAt(polls,asOf){
  const now=asOf instanceof Date?asOf:new Date(asOf);const sums=Object.fromEntries(PARTY_ORDER.map(p=>[p,0])),den=Object.fromEntries(PARTY_ORDER.map(p=>[p,0]));let effective=0;
  for(const poll of polls){
    const d=new Date(`${poll.date}T12:00:00Z`),age=(now-d)/86400000;if(!Number.isFinite(age)||age<0||age>CONFIG.modelLookbackDays)continue;
    const temporal=Math.pow(0.5,age/CONFIG.halfLifeDays),sample=clamp(Math.sqrt(Math.max(500,poll.sample||2000)/2000),.75,1.25),area=poll.area==='UK'?.97:1,w=temporal*sample*area;
    if(w>.04)effective++;
    for(const p of PARTY_ORDER){const v=poll[p];if(Number.isFinite(v)){sums[p]+=w*v;den[p]+=w;}}
  }
  const values={};for(const p of PARTY_ORDER)values[p]=den[p]?sums[p]/den[p]:0;
  return {values,effective};
}
function dateIsoUTC(d){return new Date(d).toISOString().slice(0,10);}
function addDaysUTC(d,days){const x=new Date(d);x.setUTCDate(x.getUTCDate()+days);return x;}
function pollTrendSeries(days=180){
  if(!state.polls.length)return [];
  const latestDate=new Date(`${state.polls[0].date}T12:00:00Z`);const oldestDate=new Date(`${state.polls[state.polls.length-1].date}T12:00:00Z`);
  const requested=days==='all'?Math.ceil((latestDate-oldestDate)/86400000):Number(days)||180;
  const start=new Date(Math.max(oldestDate.getTime(),addDaysUTC(latestDate,-requested).getTime()));
  const span=Math.max(1,Math.ceil((latestDate-start)/86400000)),step=span>540?4:span>260?2:1,out=[];
  for(let d=new Date(start);d<=latestDate;d=addDaysUTC(d,step)){const avg=historicalAverageAt(state.polls,d);if(avg.effective>0)out.push({date:dateIsoUTC(d),...avg});}
  if(!out.length||out[out.length-1].date!==dateIsoUTC(latestDate)){const avg=historicalAverageAt(state.polls,latestDate);if(avg.effective>0)out.push({date:dateIsoUTC(latestDate),...avg});}
  return out;
}
function historicalDelta(days,p){
  if(!state.polls.length)return null;const latest=new Date(`${state.polls[0].date}T12:00:00Z`),past=addDaysUTC(latest,-days),old=historicalAverageAt(state.polls,past).values[p],now=state.average?.values?.[p];
  return Number.isFinite(now)&&Number.isFinite(old)&&old>0?now-old:null;
}
function signedPp(v){if(!Number.isFinite(v))return '—';const sign=v>0?'+':'';return `${sign}${fmt1(v)} p.p.`;}
function renderPollTrend(){
  const svg=$('#pollTrendSvg'),empty=$('#pollTrendEmpty'),legend=$('#pollTrendLegend'),move=$('#pollMoveGrid'),stats=$('#pollActivityStats'),pollsters=$('#pollsterActivity'),tooltip=$('#pollTrendTooltip');if(!svg||!legend||!move||!stats||!pollsters)return;
  const series=pollTrendSeries(state.pollTrendRange),parties=['lab','con','ref','ld','green'],focus=state.pollTrendFocus&&parties.includes(state.pollTrendFocus)?state.pollTrendFocus:null;
  if(series.length<2){svg.innerHTML='';empty.style.display='grid';legend.innerHTML='';if(tooltip)tooltip.hidden=true;return;}empty.style.display='none';
  const mobileTrend=window.matchMedia?.('(max-width:760px)')?.matches===true;
  const W=860,H=mobileTrend?440:360,pad={l:46,r:18,t:18,b:mobileTrend?48:42};svg.setAttribute('viewBox',`0 0 ${W} ${H}`);const vals=series.flatMap(x=>parties.map(p=>x.values[p]).filter(Number.isFinite));let lo=Math.floor((Math.min(...vals)-2)/5)*5,hi=Math.ceil((Math.max(...vals)+2)/5)*5;lo=Math.max(0,lo);if(hi-lo<20)hi=lo+20;
  const x=i=>pad.l+(W-pad.l-pad.r)*(i/(series.length-1)),y=v=>pad.t+(H-pad.t-pad.b)*(1-(v-lo)/(hi-lo));const grid=[];
  for(let v=lo;v<=hi+.001;v+=5){const yy=y(v);grid.push(`<line x1="${pad.l}" x2="${W-pad.r}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" class="poll-trend-gridline"/><text x="${pad.l-9}" y="${(yy+4).toFixed(1)}" class="poll-trend-axis" text-anchor="end">${fmt0(v)}%</text>`);}
  const tickCount=4;for(let i=0;i<=tickCount;i++){const idx=Math.round((series.length-1)*i/tickCount),xx=x(idx);grid.push(`<text x="${xx.toFixed(1)}" y="${H-13}" class="poll-trend-axis poll-trend-date" text-anchor="middle">${new Date(`${series[idx].date}T12:00:00Z`).toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit',year:'2-digit',timeZone:'UTC'})}</text>`);}
  const lines=parties.map(p=>{const pts=series.map((d,i)=>`${x(i).toFixed(1)},${y(d.values[p]).toFixed(1)}`).join(' '),last=series[series.length-1],cls=focus?(focus===p?'is-focused':'is-dimmed'):'';return `<polyline points="${pts}" fill="none" stroke="${PARTY[p].color}" stroke-width="${focus===p?4:3}" stroke-linecap="round" stroke-linejoin="round" class="poll-trend-line ${cls}" data-trend-party="${p}" tabindex="0"><title>${PARTY[p].name}</title></polyline><circle cx="${x(series.length-1).toFixed(1)}" cy="${y(last.values[p]).toFixed(1)}" r="${focus===p?5.2:4.2}" fill="${PARTY[p].color}" class="poll-trend-end ${cls}" data-trend-party="${p}"><title>${PARTY[p].name}: ${pctFmt(last.values[p])}</title></circle>`;}).join('');
  svg.innerHTML=`<g>${grid.join('')}</g><line x1="${pad.l}" x2="${W-pad.r}" y1="${H-pad.b}" y2="${H-pad.b}" class="poll-trend-baseline"/><line class="poll-trend-crosshair" x1="${pad.l}" x2="${pad.l}" y1="${pad.t}" y2="${H-pad.b}" hidden/>${lines}`;
  legend.innerHTML=parties.map(p=>`<button type="button" class="poll-trend-legend-btn ${focus===p?'active':focus?'muted':''}" data-trend-party="${p}" aria-pressed="${focus===p?'true':'false'}"><i style="background:${PARTY[p].color}"></i><strong>${PARTY[p].short}</strong><b>${pctFmt(state.average.values[p])}</b></button>`).join('');
  const selectParty=p=>{state.pollTrendFocus=state.pollTrendFocus===p?null:p;renderPollTrend();};
  legend.querySelectorAll('[data-trend-party]').forEach(el=>el.addEventListener('click',()=>selectParty(el.dataset.trendParty)));
  svg.onclick=e=>{const el=e.target.closest?.('[data-trend-party]');if(el)selectParty(el.dataset.trendParty);};
  svg.onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&e.target?.dataset?.trendParty){e.preventDefault();selectParty(e.target.dataset.trendParty);}};
  svg.onpointermove=e=>{if(!tooltip)return;const rect=svg.getBoundingClientRect(),wrap=svg.parentElement.getBoundingClientRect(),sx=(e.clientX-rect.left)/Math.max(1,rect.width)*W,raw=(sx-pad.l)/(W-pad.l-pad.r),idx=Math.round(clamp(raw,0,1)*(series.length-1)),d=series[idx],shown=focus?[focus]:parties,cross=svg.querySelector('.poll-trend-crosshair'),cx=x(idx);if(cross){cross.hidden=false;cross.setAttribute('x1',cx.toFixed(1));cross.setAttribute('x2',cx.toFixed(1));}tooltip.innerHTML=`<strong>${formatDate(d.date)}</strong>${shown.map(p=>`<span><i style="background:${PARTY[p].color}"></i>${PARTY[p].short}<b>${pctFmt(d.values[p])}</b></span>`).join('')}`;tooltip.hidden=false;const left=clamp(e.clientX-wrap.left+14,8,Math.max(8,wrap.width-188)),top=clamp(e.clientY-wrap.top-18,8,Math.max(8,wrap.height-140));tooltip.style.left=`${left}px`;tooltip.style.top=`${top}px`;};
  svg.onpointerleave=()=>{if(tooltip)tooltip.hidden=true;const cross=svg.querySelector('.poll-trend-crosshair');if(cross)cross.hidden=true;};
  const first=series[0],last=series[series.length-1];$('#pollTrendMeta').textContent=`${formatDate(first.date)} → ${formatDate(last.date)} · ${series.length} punti · stessa ponderazione della media corrente`;
  move.innerHTML=parties.map(p=>{const d7=historicalDelta(7,p),d30=historicalDelta(30,p),cls=v=>!Number.isFinite(v)?'flat':v>.05?'up':v<-.05?'down':'flat';return `<div class="poll-move-row"><span><i class="party-dot" style="background:${PARTY[p].color}"></i><strong>${PARTY[p].short}</strong></span><b>${pctFmt(state.average.values[p])}</b><em class="${cls(d7)}">7g ${signedPp(d7)}</em><em class="${cls(d30)}">30g ${signedPp(d30)}</em></div>`;}).join('');
  const latest=new Date(`${state.polls[0].date}T12:00:00Z`),cut7=addDaysUTC(latest,-7),cut30=addDaysUTC(latest,-30),recent7=state.polls.filter(p=>new Date(`${p.date}T12:00:00Z`)>=cut7),recent30=state.polls.filter(p=>new Date(`${p.date}T12:00:00Z`)>=cut30),uniq=new Set(recent30.map(p=>p.pollster).filter(Boolean)),sample30=recent30.reduce((n,p)=>n+(Number(p.sample)||0),0);
  stats.innerHTML=`<div class="poll-activity-stat"><span>Sondaggi · 7 giorni</span><strong>${fmt0(recent7.length)}</strong></div><div class="poll-activity-stat"><span>Sondaggi · 30 giorni</span><strong>${fmt0(recent30.length)}</strong></div><div class="poll-activity-stat"><span>Istituti · 30 giorni</span><strong>${fmt0(uniq.size)}</strong></div><div class="poll-activity-stat"><span>Campione cumulato</span><strong>${fmt0(sample30)}</strong></div>`;
  const counts=new Map();for(const p of recent30){const name=p.pollster||'Non indicato';counts.set(name,(counts.get(name)||0)+1);}const ranking=[...counts.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'en-GB')).slice(0,6),max=Math.max(1,...ranking.map(x=>x[1]));
  pollsters.innerHTML=ranking.length?ranking.map(([name,n])=>`<div class="pollster-row"><span title="${escapeHtml(name)}">${escapeHtml(name)}</span><div><i style="width:${(n/max*100).toFixed(1)}%"></i></div><strong>${n}</strong></div>`).join(''):'<div class="empty-small">Nessuna rilevazione negli ultimi 30 giorni.</div>';$('#pollsterActivityMeta').textContent=`${recent30.length} rilevazioni`;
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
  const productionV0929=m?.version==='uk-v0929-precision-weighted-mrp-live'
    && m?.model_type==='precision-weighted-contemporary-mrp-geography-v1'
    && m?.approved_for_live===true
    && m?.applied_to_production===true
    && m?.provider_topline_used===false
    && Number(m?.validation_2019_correct_winners)>=609
    && Number(m?.provider_stack_cv_2024_correct_winners)>=584;
  const legacyV0910=m?.version==='uk-v0910-incumbent-routing-live'
    && m?.model_type==='constituency-residual-incumbent-routing-v5'
    && Number(m?.holdout_accuracy)>=.80;
  return m?.status==='ok'
    && m?.approved===true
    && (productionV0929||legacyV0910)
    && Array.isArray(m?.seats)
    && m.seats.length===632;
}
function shadowDiagnosticsReady(){
  const m=state.mrpLite;
  return m?.status==='ok' && m?.shadow_only===true && m?.approved===false;
}
function precisionMrpProductionActive(){
  const m=state.mrpLite;
  return mrpLiteActive()
    && m?.version==='uk-v0929-precision-weighted-mrp-live'
    && m?.model_type==='precision-weighted-contemporary-mrp-geography-v1';
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
    const eligible=SEAT_MODEL_PARTIES.filter(p=>partyAllowed(p,c)&&(p!=='other'||m.otherEligible===true));
    const computed=eligible.reduce((best,p)=>projected[p]>(projected[best]??-1)?p:best,eligible[0]||'other');
    const winner=(m.centralWinner&&eligible.includes(m.centralWinner))?m.centralWinner:computed;
    totals[winner]=(totals[winner]||0)+1;
    seats.push({...c,projected,centralWinner:winner,otherEligible:m.otherEligible===true,contestability:m.contestability||null,modelZone:zoneForSeat(c),mrpLite:true});
  }
  const niCentral=buildNiCentral();
  for(const [p,n] of Object.entries(niCentral.totals||{}))totals[p]=(totals[p]||0)+n;
  seats.push(...niCentral.seats);
  if(!niCentral.seats.length)totals.other+=CONFIG.niSeats;
  const central={target,geographic:geo,seats,totals,ni:niCentral.meta,mrpLite:{
    holdoutAccuracy:Number(state.mrpLite.holdout_accuracy)||0,
    holdoutSeatError:Number(state.mrpLite.holdout_seat_abs_error)||0,
    validation2019Accuracy:Number(state.mrpLite.validation_2019_accuracy)||0,
    providerStackCv2024Accuracy:Number(state.mrpLite.provider_stack_cv_2024_accuracy)||0,
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
function productionModelLabel(){
  const diagnostic=shadowDiagnosticsReady()?' · ricerca shadow attiva':'';
  if(precisionMrpProductionActive()){
    const cv=Number(state.mrpLite.provider_stack_cv_2024_accuracy);
    const hist=Number(state.mrpLite.validation_2019_accuracy);
    return `MRP stack 2026 · CV regionale 2024 ${(cv*100).toFixed(1)}% · validazione 2019 ${(hist*100).toFixed(1)}%`;
  }
  if(mrpLiteActive())return `MRP-lite + incumbent routing · benchmark 2024 ${(Number(state.mrpLite.holdout_accuracy)*100).toFixed(1)}%${diagnostic}`;
  if(partialRakeModelActive())return `Raking parziale validato (α=${partialRakeStrength().toFixed(2)}) 2024 → oggi${diagnostic}`;
  if(transferModelActive())return `Modello trasferimenti 2024 → oggi${diagnostic}`;
  return `Fallback prudente 2024 → oggi: swing regolarizzato${diagnostic}`;
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

const GENERAL_ELECTION_2024='2024-07-04';
const mobileDenseList=()=>window.matchMedia?.('(max-width:760px)')?.matches===true;
function explorerPageSize(){return mobileDenseList()?10:state.explorerPageSize;}
function pollPageSize(){return mobileDenseList()?10:state.pollPageSize;}
function postElectionPolls(){return [...state.polls].filter(p=>String(p.date||'')>=GENERAL_ELECTION_2024).sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))||String(b.fieldwork||'').localeCompare(String(a.fieldwork||'')));}
function populatePollTableFilters(){
  const base=postElectionPolls(),fill=(id,values,label)=>{const el=$(id);if(!el)return;const cur=el.value;el.innerHTML=`<option value="">${label}</option>`+values.map(v=>`<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');if(values.includes(cur))el.value=cur;};
  fill('#pollPollster',[...new Set(base.map(p=>p.pollster).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'en-GB')),'Tutti');fill('#pollArea',[...new Set(base.map(p=>p.area).filter(Boolean))].sort(),'Tutte');
}
function pollTableFiltered(){
  const q=($('#pollSearch')?.value||'').trim().toLowerCase(),pollster=$('#pollPollster')?.value||'',area=$('#pollArea')?.value||'';
  return postElectionPolls().filter(p=>{if(pollster&&p.pollster!==pollster)return false;if(area&&p.area!==area)return false;if(q&&!`${p.pollster||''} ${p.client||''}`.toLowerCase().includes(q))return false;return true;});
}
function renderPolls(){
  const latestView=state.pollAverageView==='latest',a=latestView?state.latestAverage:state.average.values; const ordered=PARTY_ORDER.map(p=>[p,a[p]]).sort((x,y)=>y[1]-x[1]);
  $('#voteBars').innerHTML=ordered.map(([p,v])=>`<div class="vote-row"><div class="party-label"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</div><div class="bar-track"><div class="bar-fill" style="background:${PARTY[p].color};width:${clamp(v/35*100,0,100)}%"></div></div><div class="vote-val">${pctFmt(v)}</div></div>`).join('');
  const leader=ordered[0], second=ordered[1]; $('#kpiLeader').textContent=PARTY[leader[0]].short; $('#kpiLeaderMeta').textContent=`${pctFmt(leader[1])} · +${fmt1(leader[1]-second[1])} su ${PARTY[second[0]].short}`;
  $('#pollAverageMeta').textContent=latestView?'Media aritmetica semplice delle 6 rilevazioni più recenti · solo confronto':`${state.average.effective} rilevazioni con peso significativo · emivita ${CONFIG.halfLifeDays} giorni`;
  const modeNote=$('#pollAverageModeNote');if(modeNote)modeNote.innerHTML=latestView?'<strong>Ultimi 6 sondaggi:</strong> media aritmetica semplice delle sei rilevazioni più recenti. Serve per confrontare il segnale più immediato con la media del modello e non alimenta il nowcast.':`<strong>Media ponderata:</strong> usa le rilevazioni fino a ${CONFIG.modelLookbackDays} giorni, dando più peso a quelle recenti e tenendo conto della numerosità del campione. È il dato che alimenta il nowcast.`;
  const latest=state.polls[0]; if(latest){$('#kpiLastPoll').textContent=formatDate(latest.date);$('#kpiLastPollMeta').textContent=`${latest.pollster} · ${latest.area} · n=${fmt0(latest.sample)}`;}
  $('#dataBadge').textContent=`Sondaggi: ${state.pollSource}`;updateEditorialMeta();populatePollTableFilters();
  const filtered=pollTableFiltered(),pageSize=pollPageSize(),pages=Math.max(1,Math.ceil(filtered.length/pageSize));state.pollPage=clamp(state.pollPage||1,1,pages);const start=(state.pollPage-1)*pageSize,visible=filtered.slice(start,start+pageSize);
  const rows=visible.map(p=>`<tr><td>${escapeHtml(p.fieldwork||formatDate(p.date))}</td><td><strong>${escapeHtml(p.pollster)}</strong></td><td>${escapeHtml(p.client||'—')}</td><td>${escapeHtml(p.area)}</td><td>${fmt0(p.sample)}</td>${['lab','con','ref','ld','green','snp','pc','rb'].map(k=>`<td>${Number.isFinite(p[k])?fmt1(p[k]):'—'}</td>`).join('')}</tr>`).join('');
  $('#pollTableBody').innerHTML=rows||'<tr><td colspan="13"><div class="empty-small">Nessuna rilevazione corrisponde ai filtri.</div></td></tr>';
  const pollMobile=$('#pollMobileList');if(pollMobile)pollMobile.innerHTML=visible.length?visible.map(p=>{const vals=['lab','con','ref','ld','green','snp','pc','rb'].filter(k=>Number.isFinite(p[k]));return `<article class="poll-mobile-card"><div class="poll-mobile-head"><div><strong>${escapeHtml(p.pollster||'Istituto non indicato')}</strong><span>${escapeHtml(p.fieldwork||formatDate(p.date))}</span></div><b>${escapeHtml(p.area||'—')}</b></div><div class="poll-mobile-meta"><span>${escapeHtml(p.client||'Senza committente indicato')}</span><span>Campione <strong>${fmt0(p.sample)}</strong></span></div><div class="poll-mobile-values">${vals.map(k=>`<span style="--party:${PARTY[k]?.color||PARTY.other.color}"><i></i><b>${PARTY[k]?.short||k}</b><strong>${fmt1(p[k])}</strong></span>`).join('')}</div></article>`;}).join(''):'<div class="empty-small mobile-empty">Nessuna rilevazione corrisponde ai filtri.</div>';
  const count=$('#pollTableCount');if(count)count.textContent=`${fmt0(filtered.length)} rilevazioni`;
  const meta=$('#pollTableMeta');if(meta)meta.textContent=filtered.length?`Pagina ${state.pollPage} di ${pages} · record ${fmt0(start+1)}–${fmt0(start+visible.length)} · dalle elezioni generali del 4 luglio 2024.`:'Nessuna rilevazione filtrata.';
  renderPagination($('#pollPagination'),pages,state.pollPage,p=>{state.pollPage=p;renderPolls();document.querySelector('.poll-browser-card')?.scrollIntoView({behavior:'smooth',block:'start'});});
  syncViewContextBar();
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
const stableModelTokenCache=new WeakMap();
function stableModelToken(obj,fallback){
  if(!obj||typeof obj!=='object')return fallback;
  if(stableModelTokenCache.has(obj))return stableModelTokenCache.get(obj);
  const raw=JSON.stringify(obj,(key,value)=>/^(generated_at|updated_at|timestamp|build_time)$/i.test(key)?undefined:value);
  const token=String(hashString(raw||fallback));stableModelTokenCache.set(obj,token);return token;
}
function fingerprint(){
  const p=state.polls.slice(0,40)
    .map(x=>`${x.date}|${x.pollster}|${x.lab}|${x.con}|${x.ref}|${x.ld}|${x.green}|${x.rb}`)
    .join(';');
  const sp=state.subnational.slice(0,24)
    .map(x=>`${x.country}|${x.date}|${x.pollster}|${x.lab}|${x.con}|${x.ref}|${x.snp}|${x.pc}`)
    .join(';');
  const ni=stableModelToken(state.ni,'ni-fallback');
  const mrp=stableModelToken(state.mrpLite,'mrp-fallback');
  const cal=state.modelParams
    ? `${state.modelParams.version||'model'}:${state.modelParams.model_type||''}:${state.modelParams.rake_strength??''}`
    : 'fallback';
  return `${CONFIG.cacheVersion}:${hashString(p+'|'+sp+'|'+state.constituencies.length+'|'+cal+'|'+ni+'|'+mrp)}`;
}
function simulationSeedKey(){
  // Preserve the v0.9.43 Monte Carlo seed inputs whenever a new simulation is
  // genuinely required. Caching uses the stable content fingerprint above,
  // while the statistical draw sequence remains unchanged from the baseline.
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
function mcCacheKey(){return `danieleangrisani:ukmodel:${fingerprint()}`;}
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

let publishedMcRefreshTimer=null,publishedMcRefreshAttempts=0;
function applyMonteCarloSummary(summary){
  state.mc=summary;saveMcCache(summary);renderMc();setMonteCarloPending(false);applyMapColors();return summary;
}
function waitForPublishedMonteCarlo(fp){
  if(publishedMcRefreshTimer)return;
  publishedMcRefreshAttempts=0;
  const poll=async()=>{
    publishedMcRefreshTimer=null;publishedMcRefreshAttempts++;
    try{
      const fresh=await fetchJson(`${CONFIG.mcSummaryLocal}?v=${Date.now()}`,5000);
      if(fresh?.fingerprint===fp&&Number(fresh.sims)===CONFIG.mcSims){state.precomputedMc=fresh;applyMonteCarloSummary(fresh);$('#mcStatus').textContent='Completato';return;}
    }catch(_){}
    if(publishedMcRefreshAttempts<24)publishedMcRefreshTimer=setTimeout(poll,7500);
  };
  publishedMcRefreshTimer=setTimeout(poll,5000);
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
    const candidates=SEAT_MODEL_PARTIES.filter(p=>partyAllowed(p,s)&&(p!=='other'||!s.mrpLite||s.otherEligible===true)).map(p=>{
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

let mcRunPromise=null,mcRunFingerprint=null;
async function runMonteCarlo({allowClientBuild=false}={}){
  if(!state.central?.seats?.length)return;
  const fp=fingerprint();
  if(state.mc?.fingerprint===fp)return state.mc;
  const precomputed=state.precomputedMc;
  if(precomputed?.fingerprint===fp&&Number(precomputed.sims)===CONFIG.mcSims)return applyMonteCarloSummary(precomputed);
  const cached=loadMcCache();
  if(cached?.fingerprint===fp)return applyMonteCarloSummary(cached);
  // Public browsers never launch a duplicate 50k run. The single authoritative
  // calculation is performed by the post-update social-card workflow and then
  // persisted to data/monte-carlo-current.json. While that short build is in
  // progress, the page polls for the published summary instead of recomputing it.
  if(!MC_BUILD_MODE&&!allowClientBuild){setMonteCarloPending(true);$('#mcStatus').textContent='Aggiornamento Monte Carlo in corso';waitForPublishedMonteCarlo(fp);return null;}
  if(mcRunPromise&&mcRunFingerprint===fp)return mcRunPromise;
  mcRunFingerprint=fp;
  mcRunPromise=(async()=>{
  setMonteCarloPending(true);
  const {models,regions,target}=prepareSeatModel(),P=SEAT_ORDER.length,N=CONFIG.mcSims,nSeats=models.length;
  const partyIndex=new Map(SEAT_ORDER.map((p,i)=>[p,i])),dists=SEAT_ORDER.map(()=>new Uint16Array(N)),wins=new Uint32Array(nSeats*P),rng=mulberry32(hashString(simulationSeedKey()));
  let hung=0,labMaj=0,conMaj=0,refMaj=0,labWorkMaj=0,conWorkMaj=0,refWorkMaj=0;
  const workThresholds=new Uint16Array(N),largestCounts=Object.fromEntries(SEAT_ORDER.map(p=>[p,0]));
  $('#mcStatus').textContent='50 blocchi asincroni da 1.000';$('#mcProgress').value=0;const centreAlreadyTransformed=mrpLiteActive()||partialRakeModelActive()||transferModelActive();
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
  const summary={sims:N,medians,intervals,labMaj:labMaj/N,conMaj:conMaj/N,refMaj:refMaj/N,labWorkMaj:labWorkMaj/N,conWorkMaj:conWorkMaj/N,refWorkMaj:refWorkMaj/N,workingThreshold:quantileSorted(workArr,.5),hung:hung/N,largest:Object.fromEntries(SEAT_ORDER.map(p=>[p,largestCounts[p]/N])),seatProb,dist:distPlain,fingerprint:fp};
  state.mc=summary;
  saveMcCache(summary);
  $('#mcStatus').textContent='Completato';
  renderMc();
  setMonteCarloPending(false);
  applyMapColors();
  return summary;
  })();
  try{return await mcRunPromise;}finally{mcRunPromise=null;mcRunFingerprint=null;}
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

  if(pending&&(state.mapMode==='prob'||state.mapMode==='representative')){state.mapMode='central';applyMapColors();}
  updateMapModeButtons();
}

function renderUncertaintyDashboard(){
  const partyGrid=$('#uncertaintyPartyGrid'),leaderGrid=$('#uncertaintyLeaderGrid'),stats=$('#battlefieldStats'),list=$('#battlefieldList'),regionNote=$('#battlefieldRegionNote');
  if(!partyGrid&&!leaderGrid&&!stats&&!list)return;
  const m=state.mc;
  if(!m){
    if(partyGrid)partyGrid.innerHTML='<div class="empty-small">In attesa del Monte Carlo.</div>';
    if(leaderGrid)leaderGrid.innerHTML='<div class="empty-small">Calcolo in corso…</div>';
    if(stats)stats.innerHTML='<div class="empty-small">In attesa delle probabilità di collegio.</div>';
    if(list)list.innerHTML='';
    if(regionNote)regionNote.textContent='—';
    return;
  }

  const ranges=SEAT_ORDER.map(p=>({
    p,median:Number(m.medians?.[p]||0),
    low:Number(m.intervals?.[p]?.[0]||0),high:Number(m.intervals?.[p]?.[1]||0),
    leader:Number(m.largest?.[p]||0)
  })).filter(x=>PARTY[x.p]&&x.p!=='other'&&x.p!=='ni_other'&&(x.median>=1||x.high>=2||x.leader>=.001)).sort((a,b)=>b.median-a.median||b.high-a.high);
  const maxHigh=Math.max(1,...ranges.map(x=>x.high));
  if(partyGrid){
    partyGrid.innerHTML=ranges.map(x=>{
      const left=clamp(x.low/maxHigh*100,0,100),right=clamp(x.high/maxHigh*100,0,100),med=clamp(x.median/maxHigh*100,0,100),width=Math.max(.7,right-left);
      return `<button type="button" class="uncertainty-party" data-uncertainty-party="${x.p}" style="--party:${PARTY[x.p].color}" title="Filtra i collegi con ${escapeHtml(PARTY[x.p].name)} vincitore nello scenario corrente"><div class="uncertainty-party-top"><span><i class="party-dot" style="background:${PARTY[x.p].color}"></i><strong>${escapeHtml(PARTY[x.p].name)}</strong></span><b>${fmt0(x.median)}</b></div><div class="uncertainty-range-track" aria-label="${escapeHtml(PARTY[x.p].name)}: mediana ${fmt0(x.median)}, intervallo 80% ${fmt0(x.low)}-${fmt0(x.high)}"><i class="uncertainty-range" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></i><i class="uncertainty-median" style="left:${med.toFixed(2)}%"></i></div><div class="uncertainty-party-meta"><span>80%: <strong>${fmt0(x.low)}–${fmt0(x.high)}</strong></span><span>Ampiezza: ${fmt0(x.high-x.low)}</span></div><span class="uncertainty-action">Apri i collegi →</span></button>`;
    }).join('')||'<div class="empty-small">Intervalli non disponibili.</div>';
    partyGrid.querySelectorAll('[data-uncertainty-party]').forEach(btn=>btn.addEventListener('click',()=>filterExplorerByWinner(btn.dataset.uncertaintyParty)));
  }

  if(leaderGrid){
    const leaders=Object.entries(m.largest||{}).filter(([p])=>PARTY[p]&&p!=='other'&&p!=='ni_other').map(([p,v])=>({p,v:Number(v)||0})).sort((a,b)=>b.v-a.v).filter((x,i)=>x.v>=.001||i<3).slice(0,7);
    leaderGrid.innerHTML=leaders.map(x=>`<div class="uncertainty-leader-row"><span><i class="party-dot" style="background:${PARTY[x.p].color}"></i>${escapeHtml(PARTY[x.p].name)}</span><div class="uncertainty-leader-meter"><i style="width:${clamp(x.v*100,0,100).toFixed(2)}%;background:${PARTY[x.p].color}"></i></div><strong>${pctFmt(x.v*100)}</strong></div>`).join('')||'<div class="empty-small">Probabilità non disponibili.</div>';
  }

  const seats=(state.central?.seats||[]).map(seat=>{
    const prob=m.seatProb?.[seat.id];
    const best=prob?Object.entries(prob).filter(([p])=>PARTY[p]).sort((a,b)=>b[1]-a[1])[0]:null;
    return best?{seat,p:best[0],prob:Number(best[1])}:null;
  }).filter(Boolean);
  const buckets={tossup:0,uncertain:0,competitive:0,safe:0};
  for(const x of seats){if(x.prob<.55)buckets.tossup++;else if(x.prob<.65)buckets.uncertain++;else if(x.prob<.80)buckets.competitive++;else buckets.safe++;}
  if(stats){
    stats.innerHTML=[
      ['Testa a testa','<55%',buckets.tossup,'tossup'],
      ['Incerti','55–65%',buckets.uncertain,'uncertain'],
      ['Competitivi','65–80%',buckets.competitive,'competitive'],
      ['Solidi','≥80%',buckets.safe,'safe']
    ].map(([label,range,n,cls])=>`<div class="battlefield-stat ${cls}"><span>${label}<small>${range} · prob. favorito</small></span><strong>${fmt0(n)}</strong></div>`).join('');
  }

  const regionCounts=new Map();
  for(const x of seats.filter(x=>x.prob<.65)){const area=regionLabelForSeat(x.seat)||x.seat.country||'Altro';regionCounts.set(area,(regionCounts.get(area)||0)+1);}
  const topRegion=[...regionCounts.entries()].sort((a,b)=>b[1]-a[1])[0];
  if(regionNote)regionNote.textContent=topRegion?`${regionalDisplayName(topRegion[0])}: ${fmt0(topRegion[1])} sotto il 65%`:'Nessun collegio sotto il 65%';

  if(list){
    const mostUncertain=seats.sort((a,b)=>a.prob-b.prob||String(a.seat.name).localeCompare(String(b.seat.name),'en-GB')).slice(0,8);
    list.innerHTML=mostUncertain.map(x=>`<button type="button" class="battlefield-seat" data-battlefield-seat="${escapeHtml(x.seat.id)}"><span class="battlefield-seat-name"><strong>${escapeHtml(x.seat.name||x.seat.id)}</strong><small>${escapeHtml(regionalDisplayName(regionLabelForSeat(x.seat)||x.seat.country||''))}</small></span><span class="battlefield-seat-party"><i class="party-dot" style="background:${PARTY[x.p].color}"></i>${escapeHtml(PARTY[x.p].short)}</span><b>${pctFmt(x.prob*100)}</b></button>`).join('')||'<div class="empty-small">Probabilità di collegio non disponibili.</div>';
    list.querySelectorAll('[data-battlefield-seat]').forEach(btn=>btn.addEventListener('click',()=>{const id=btn.dataset.battlefieldSeat;if(!id)return;selectSeat(id);document.querySelector('#territorio')?.scrollIntoView({behavior:'smooth',block:'start'});}));
  }
}

function renderCentral(){
  const totals=state.central.totals;
  $('#projectionTitle').textContent='Scenario alla media dei sondaggi';
  const sm=state.geographicTargets?.meta?.Scotland,wm=state.geographicTargets?.meta?.Wales;
  const sub=[sm?.polls?`Scozia: ${sm.polls} sondaggi`:null,wm?.polls?`Galles: ${wm.polls} sondaggi`:null].filter(Boolean).join(' · ');
  $('#projectionSubtitle').textContent=`Struttura geografica validata${sub?` · ${sub}`:''}${state.central?.ni?.signalWeight?` · Irlanda del Nord: segnale Assemblea ×${state.central.ni.signalWeight.toFixed(2)}`:' · Irlanda del Nord: base 2024'} · Il Monte Carlo sta costruendo la distribuzione probabilistica e lo scenario territoriale rappresentativo.`;
  if(state.scenarioHemicycleActive&&state.customScenario)renderCustomSeatProjection();else renderSeats(totals,null);
  $('#kpiLargest').textContent=PARTY[Object.entries(totals).sort((a,b)=>b[1]-a[1])[0][0]]?.short||'—';
  $('#kpiLargestMeta').textContent='scenario centrale provvisorio';
  renderOutcomeDashboard();
  renderMarginals();
  renderRegionalDashboard();
  renderMapSummary();
  renderMinimalCoalitions();
  renderUncertaintyDashboard();
  updateMobileNowcastSticky();
}
function renderMc(){
  const m=state.mc;if(!m)return;
  state.representative=buildRepresentativeScenario(m);
  if(state.scenarioHemicycleActive&&state.customScenario)renderCustomSeatProjection();
  else{
    renderSeats(m.medians,m.intervals);
    $('#projectionTitle').textContent='Scenario rappresentativo Monte Carlo';
    $('#projectionSubtitle').textContent='Mediane di 50.000 simulazioni; intervallo centrale 80% tra parentesi. La mappa viene ricomposta per aderire il più possibile alle mediane dei seggi.';
  }
  $('#probLabMaj').textContent=pctFmt(m.labMaj*100);$('#probConMaj').textContent=pctFmt(m.conMaj*100);$('#probRefMaj').textContent=pctFmt(m.refMaj*100);$('#probHung').textContent=pctFmt(m.hung*100);
  if($('#probLabWorkMaj'))$('#probLabWorkMaj').textContent=pctFmt((m.labWorkMaj||0)*100);if($('#probConWorkMaj'))$('#probConWorkMaj').textContent=pctFmt((m.conWorkMaj||0)*100);if($('#probRefWorkMaj'))$('#probRefWorkMaj').textContent=pctFmt((m.refWorkMaj||0)*100);if($('#workingThreshold'))$('#workingThreshold').textContent=fmt0(m.workingThreshold||326);
  const largest=Object.entries(m.largest).sort((a,b)=>b[1]-a[1])[0];$('#kpiLargest').textContent=PARTY[largest[0]]?.short||largest[0];$('#kpiLargestMeta').textContent=`${pctFmt(largest[1]*100)} di essere il primo partito`;
  const maj=Math.max(m.labMaj,m.conMaj,m.refMaj);$('#kpiMajority').textContent=pctFmt(maj*100);const who=m.labMaj===maj?'Labour':m.conMaj===maj?'Conservative':'Reform';$('#kpiMajorityMeta').textContent=`${who} · 326 assoluta · ~${fmt0(m.workingThreshold||326)} operativa`;
  $('#mcStatus').textContent='Completato';$('#mcCount').textContent=`${fmt0(m.sims)} / ${fmt0(m.sims)}`;$('#mcProgress').value=m.sims;
  if(state.mapMode==='central')state.mapMode='representative';
  updateMapModeButtons();
  applyMapColors();
  renderOutcomeDashboard();
  renderMarginals();
  renderRegionalDashboard();
  renderMapSummary();
  updateCoalition();
  renderMinimalCoalitions();
  renderUncertaintyDashboard();
  updateMobileNowcastSticky();
}
function renderSeats(totals,intervals){
  const sum=SEAT_ORDER.reduce((acc,p)=>acc+(totals[p]||0),0)||650;
  $('#seatStrip').innerHTML=SEAT_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<span data-hemi-party="${p}" role="button" tabindex="0" aria-label="Evidenzia ${PARTY[p].name}" aria-pressed="${state.hemiFocus===p?'true':'false'}" class="${state.hemiFocus===p?'active':state.hemiFocus?'muted':''}" style="width:${(totals[p]/sum)*100}%;background:${PARTY[p].color}" title="${PARTY[p].name}: ${fmt0(totals[p])}"></span>`).join('');
  $('#seatTable').innerHTML=SEAT_ORDER.filter(p=>(totals[p]||0)>0).map(p=>`<div class="seat-row hemi-legend-row ${state.hemiFocus===p?'active':state.hemiFocus?'muted':''}" data-hemi-party="${p}" role="button" tabindex="0" aria-pressed="${state.hemiFocus===p?'true':'false'}" title="Clicca per evidenziare ${PARTY[p].name} nell’emiciclo"><div class="left"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</div><strong>${fmt0(totals[p])}${intervals?.[p]?` <small>${fmt0(intervals[p][0])}–${fmt0(intervals[p][1])}</small>`:''}</strong></div>`).join('');
  renderHemicycle(totals);
  const activate=p=>{state.hemiFocus=state.hemiFocus===p?null:p;renderSeats(totals,intervals);};
  [...$('#seatTable').querySelectorAll('[data-hemi-party]'),...$('#seatStrip').querySelectorAll('[data-hemi-party]')].forEach(el=>{el.addEventListener('click',()=>activate(el.dataset.hemiParty));el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate(el.dataset.hemiParty);}});});
}
function hemicyclePoints(){
  const rows=18,ideals=[];
  for(let row=0;row<rows;row++){const r=63+row*9.6;ideals.push({row,r,ideal:Math.max(8,Math.PI*r/11)});}
  const scale=650/ideals.reduce((acc,x)=>acc+x.ideal,0),caps=ideals.map(x=>Math.max(8,Math.floor(x.ideal*scale)));
  let missing=650-caps.reduce((a,b)=>a+b,0);
  const order=ideals.map((x,i)=>({i,frac:x.ideal*scale-Math.floor(x.ideal*scale)})).sort((a,b)=>b.frac-a.frac);
  for(let k=0;k<missing;k++)caps[order[k%order.length].i]++;
  const pts=[];
  for(let row=0;row<rows;row++){const r=ideals[row].r,cap=caps[row];for(let j=0;j<cap;j++){const t=Math.PI-(j/(cap-1))*Math.PI;pts.push({x:310+r*Math.cos(t),y:297-r*Math.sin(t),r});}}
  pts.sort((a,b)=>a.x-b.x||b.r-a.r);return pts;
}
const hemiPts=hemicyclePoints();
function renderHemicycle(totals){
  const seats=[];for(const p of SEAT_ORDER){for(let i=0;i<Math.round(totals[p]||0);i++)seats.push(p);}while(seats.length<650)seats.push('other');if(seats.length>650)seats.length=650;
  $('#hemicycle').innerHTML=hemiPts.map((pt,i)=>{const p=seats[i]||'other',focus=state.hemiFocus,cls=focus?(p===focus?'hemi-focus':'hemi-dim'):'';return `<circle class="hemi-seat ${cls}" data-party="${p}" cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="3.7" fill="${PARTY[p].color}" opacity="${focus?(p===focus?1:.13):.96}"><title>${PARTY[p].name}</title></circle>`;}).join('');
}

function geometryCode(props){return props.PCON24CD||props.PCON24CDH||props.PCONCD||props.GSS_CODE||props.code||props.id||'';}
function geometryName(props){return props.PCON24NM||props.PCONNM||props.NAME||props.name||'';}
function eachCoord(geom,fn){if(!geom)return;if(geom.type==='Polygon'){for(const ring of geom.coordinates)for(const c of ring)fn(c);}else if(geom.type==='MultiPolygon'){for(const poly of geom.coordinates)for(const ring of poly)for(const c of ring)fn(c);}}
function pathForGeometry(geom,project){
  if(!geom)return''; const polyPath=poly=>poly.map(ring=>ring.map((c,i)=>`${i?'L':'M'}${project(c)[0].toFixed(1)},${project(c)[1].toFixed(1)}`).join(' ')+' Z').join(' ');
  return geom.type==='Polygon'?polyPath(geom.coordinates):geom.type==='MultiPolygon'?geom.coordinates.map(polyPath).join(' '):'';
}
function geometryProjectedCenter(geom,project){
  let x1=Infinity,y1=Infinity,x2=-Infinity,y2=-Infinity,n=0;
  eachCoord(geom,c=>{const p=project(c);if(!Number.isFinite(p[0])||!Number.isFinite(p[1]))return;x1=Math.min(x1,p[0]);y1=Math.min(y1,p[1]);x2=Math.max(x2,p[0]);y2=Math.max(y2,p[1]);n++;});
  return n?{x:(x1+x2)/2,y:(y1+y2)/2}:{x:320,y:380};
}
function hexagonPath(cx,cy,r){
  const pts=[];for(let i=0;i<6;i++){const a=(Math.PI/180)*(60*i-30);pts.push([cx+r*Math.cos(a),cy+r*Math.sin(a)]);}
  return pts.map((pt,i)=>`${i?'L':'M'}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ')+' Z';
}
let hexLayoutCache=null;
function buildHexAssignments(features,project,W=640,H=760){
  // Collision-free hex cartogram.  We first create a geography-preserving
  // target for every constituency, then snap those targets to a single shared
  // pointy-top hex lattice.  A lattice cell can be owned by one seat only, so
  // overlaps are impossible by construction.  Sparse/coastal seats are placed
  // first; dense urban seats are allowed to expand into nearby free cells.
  if(hexLayoutCache?.features===features&&hexLayoutCache.W===W&&hexLayoutCache.H===H)return hexLayoutCache.assignments;
  const pad=18,r=7.25,gap=1.08;
  const rows=features.map(f=>{
    const id=geometryCode(f.properties||{}),name=geometryName(f.properties||{}),c=geometryProjectedCenter(f.geometry,project),seat=state.byId.get(id);
    return {f,id,name,country:seat?.country||'',ax:c.x,ay:c.y,x:c.x,y:c.y,density:0};
  }).filter(x=>x.id&&Number.isFinite(x.x)&&Number.isFinite(x.y));

  // Local density is used only to decide placement priority: rural/coastal
  // seats keep their geographic anchor, while cities absorb the schematic
  // expansion needed to give every constituency equal visual area.
  const densityRadius2=32*32;
  for(let i=0;i<rows.length;i++){
    let d=0;
    for(let j=0;j<rows.length;j++){
      if(i===j)continue;
      const dx=rows[i].ax-rows[j].ax,dy=rows[i].ay-rows[j].ay;
      if(dx*dx+dy*dy<=densityRadius2)d++;
    }
    rows[i].density=d;
  }

  // Produce a gentle, geography-preserving target before the strict grid snap.
  // This does not draw the hexes: it merely tells the discrete assignment where
  // a dense cluster would ideally expand.
  const targetMin=r*2.12,targetMin2=targetMin*targetMin;
  const deterministicVector=(a,b)=>{
    let h=2166136261;const text=`${a}|${b}`;
    for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}
    const angle=((h>>>0)%3600)/3600*Math.PI*2;return [Math.cos(angle),Math.sin(angle)];
  };
  const bucketSize=targetMin*1.2;
  for(let iter=0;iter<72;iter++){
    const buckets=new Map(),fx=new Float64Array(rows.length),fy=new Float64Array(rows.length);
    for(let i=0;i<rows.length;i++){
      const p=rows[i],gx=Math.floor(p.x/bucketSize),gy=Math.floor(p.y/bucketSize),key=`${gx},${gy}`;
      if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(i);
    }
    for(let i=0;i<rows.length;i++){
      const a=rows[i],gx=Math.floor(a.x/bucketSize),gy=Math.floor(a.y/bucketSize);
      for(let ox=-1;ox<=1;ox++)for(let oy=-1;oy<=1;oy++){
        const bucket=buckets.get(`${gx+ox},${gy+oy}`);if(!bucket)continue;
        for(const j of bucket){
          if(j<=i)continue;const b=rows[j];let dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy;if(d2>=targetMin2)continue;
          let d=Math.sqrt(d2);if(d<.001){const v=deterministicVector(a.id,b.id);dx=v[0];dy=v[1];d=1;}
          const push=(targetMin-d)*.42,ux=dx/d,uy=dy/d;
          fx[i]-=ux*push;fy[i]-=uy*push;fx[j]+=ux*push;fy[j]+=uy*push;
        }
      }
    }
    for(let i=0;i<rows.length;i++){
      const p=rows[i];
      const spring=.086/(1+p.density*.06);
      fx[i]+=(p.ax-p.x)*spring;fy[i]+=(p.ay-p.y)*spring;
      const mag=Math.hypot(fx[i],fy[i]),maxStep=2.3,k=mag>maxStep?maxStep/mag:1;
      p.x=clamp(p.x+fx[i]*k,pad+r,W-pad-r);
      p.y=clamp(p.y+fy[i]*k,pad+r,H-pad-r);
    }
  }

  // Pointy-top axial hex grid.  The extra gap leaves a thin dark/silhouette
  // channel between neighbouring cells and makes collisions impossible.
  const stepX=Math.sqrt(3)*r*gap,stepY=1.5*r*gap;
  const cells=[];
  let rowIndex=0;
  for(let y=pad+r;y<=H-pad-r+.001;y+=stepY,rowIndex++){
    const offset=(rowIndex&1)?stepX/2:0;
    let colIndex=0;
    for(let x=pad+r+offset;x<=W-pad-r+.001;x+=stepX,colIndex++){
      cells.push({x,y,row:rowIndex,col:colIndex,key:`${rowIndex}:${colIndex}`});
    }
  }

  const cost=(p,c)=>{
    const tx=c.x-p.x,ty=c.y-p.y,ax=c.x-p.ax,ay=c.y-p.ay;
    // The relaxed target handles dense-city expansion; the original centroid
    // remains a secondary anchor so the coastline and national outline survive.
    return tx*tx+ty*ty+.24*(ax*ax+ay*ay);
  };
  const occupied=new Map(),placement=new Map();
  const priority=[...rows].sort((a,b)=>a.density-b.density||Math.hypot(b.ax-W/2,b.ay-H/2)-Math.hypot(a.ax-W/2,a.ay-H/2)||a.id.localeCompare(b.id));
  for(const p of priority){
    let best=null,bestCost=Infinity;
    for(const c of cells){
      if(occupied.has(c.key))continue;
      const v=cost(p,c);if(v<bestCost){bestCost=v;best=c;}
    }
    if(!best)continue;
    occupied.set(best.key,p);placement.set(p.id,best);
  }

  // Small deterministic local optimisation.  Seats may move into an empty
  // neighbouring grid cell or swap with a neighbour only when the total anchor
  // error decreases.  Because every move remains on the same lattice, the
  // no-overlap guarantee is preserved throughout.
  const byRC=new Map(cells.map(c=>[`${c.row}:${c.col}`,c]));
  const neighbourCells=c=>{
    const even=(c.row&1)===0;
    const offsets=even?[[0,-1],[0,1],[-1,-1],[-1,0],[1,-1],[1,0]]:[[0,-1],[0,1],[-1,0],[-1,1],[1,0],[1,1]];
    return offsets.map(([dr,dc])=>byRC.get(`${c.row+dr}:${c.col+dc}`)).filter(Boolean);
  };
  const rowById=new Map(rows.map(p=>[p.id,p]));
  for(let pass=0;pass<5;pass++){
    let changed=false;
    for(const p of priority){
      const cur=placement.get(p.id);if(!cur)continue;
      let bestMove=null,bestGain=0;
      for(const next of neighbourCells(cur)){
        const other=occupied.get(next.key);
        if(!other){
          const gain=cost(p,cur)-cost(p,next);
          if(gain>bestGain+.01){bestGain=gain;bestMove={next,other:null};}
        }else if(other!==p){
          const q=rowById.get(other.id);if(!q)continue;
          const gain=(cost(p,cur)+cost(q,next))-(cost(p,next)+cost(q,cur));
          if(gain>bestGain+.01){bestGain=gain;bestMove={next,other:q};}
        }
      }
      if(!bestMove)continue;
      occupied.delete(cur.key);
      if(bestMove.other){
        placement.set(bestMove.other.id,cur);occupied.set(cur.key,bestMove.other);
      }
      placement.set(p.id,bestMove.next);occupied.set(bestMove.next.key,p);changed=true;
    }
    if(!changed)break;
  }

  const assigned=new Map();
  for(const p of rows){const c=placement.get(p.id);if(c)assigned.set(p.id,{x:c.x,y:c.y,r,name:p.name});}
  hexLayoutCache={features,W,H,assignments:assigned};
  return assigned;
}
function updateMapLayoutButtons(){
  $('#mapGeoLayoutBtn')?.classList.toggle('active',state.mapLayout!=='hex');
  $('#mapHexLayoutBtn')?.classList.toggle('active',state.mapLayout==='hex');
  const wrap=$('#mapWrap');if(wrap)wrap.classList.toggle('is-hex-layout',state.mapLayout==='hex');
}
function renderMap(){
  const map=$('#ukMap');
  if(!state.geometry?.features?.length){$('#mapEmpty').style.display='grid';$('#mapMeta').textContent='Geometrie non disponibili: esegui l’aggiornamento dei dati.';return;}
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
  if(state.mapLayout==='hex'){
    const hexes=buildHexAssignments(features,project,W,H);
    const silhouette=features.map(f=>pathForGeometry(f.geometry,project)).join(' ');
    map.innerHTML=`<path class="hex-uk-silhouette" d="${silhouette}" fill-rule="evenodd" aria-hidden="true"></path>`+features.map(f=>{
      const id=geometryCode(f.properties||{}),name=geometryName(f.properties||{}),seat=state.byId.get(id),hex=hexes.get(id);if(!hex)return'';
      const fill=seat?PARTY[seat.centralWinner]?.color:partyColorFrom2024(id),label=seat?.name||name||id;
      return `<path class="constituency constituency-hex" data-id="${escapeHtml(id)}" data-map-name="${escapeHtml(label)}" d="${hexagonPath(hex.x,hex.y,hex.r)}" fill="${fill||'#414957'}"></path>`;
    }).join('');
  }else{
    map.innerHTML=features.map(f=>{
      const id=geometryCode(f.properties||{}),name=geometryName(f.properties||{}),seat=state.byId.get(id);
      const fill=seat?PARTY[seat.centralWinner]?.color:partyColorFrom2024(id);
      const label=seat?.name||name||id;
      return `<path class="constituency" data-id="${escapeHtml(id)}" data-map-name="${escapeHtml(label)}" d="${pathForGeometry(f.geometry,project)}" fill="${fill||'#414957'}"></path>`;
    }).join('');
  }
  state.mapPaths=new Map(Array.from(map.querySelectorAll('path.constituency')).map(el=>[el.dataset.id,el]));
  state.selectedPath=state.selectedSeat?state.mapPaths.get(state.selectedSeat)||null:null;if(state.selectedPath)state.selectedPath.classList.add('selected');
  resetMapZoom();
  $('#mapEmpty').style.display='none';
  const reduced=state.geometry?.meta?.vertices_after;
  $('#mapMeta').textContent=state.mapLayout==='hex'?`${features.length} esagoni · 1 esagono = 1 collegio · griglia senza sovrapposizioni`:(reduced?`${features.length} collegi · geometria web ottimizzata`:`${features.length} geometrie ONS · BGC 20 m`);
  updateMapLayoutButtons();
  applyMapColors();
  renderMarginals();
  map.dispatchEvent(new CustomEvent('maprendered'));
}
function mapViewClamp(view){
  const b=mapZoomState.base,minW=b.w/mapZoomState.maxZoom,minH=b.h/mapZoomState.maxZoom;
  let w=clamp(Number(view.w)||b.w,minW,b.w),h=w*b.h/b.w;
  if(h>b.h){h=b.h;w=h*b.w/b.h;}
  let x=Number(view.x)||0,y=Number(view.y)||0;
  x=clamp(x,b.x,b.x+b.w-w);y=clamp(y,b.y,b.y+b.h-h);
  return {x,y,w,h};
}
function applyMapView(){
  const map=$('#ukMap');if(!map)return;const v=mapViewClamp(mapZoomState.view);mapZoomState.view=v;
  map.setAttribute('viewBox',`${v.x.toFixed(3)} ${v.y.toFixed(3)} ${v.w.toFixed(3)} ${v.h.toFixed(3)}`);
  const zoom=mapZoomState.base.w/v.w,level=$('#mapZoomLevel');if(level)level.textContent=`${Math.round(zoom*100)}%`;
  const wrap=$('#mapWrap');if(wrap){wrap.classList.toggle('is-map-pannable',zoom>1.001);wrap.classList.toggle('is-map-panning',mapZoomState.panning);}
}
function resetMapZoom(){mapZoomState.view={...mapZoomState.base};mapZoomState.panning=false;mapZoomState.pointerId=null;mapZoomState.moved=false;applyMapView();}
function mapPointFromClient(clientX,clientY){
  const map=$('#ukMap'),r=map?.getBoundingClientRect();if(!r||!r.width||!r.height)return null;const v=mapZoomState.view;
  return {x:v.x+(clientX-r.left)/r.width*v.w,y:v.y+(clientY-r.top)/r.height*v.h};
}
function zoomMapAt(factor,clientX=null,clientY=null){
  const v=mapZoomState.view,b=mapZoomState.base,oldZoom=b.w/v.w,newZoom=clamp(oldZoom*factor,1,mapZoomState.maxZoom),newW=b.w/newZoom,newH=b.h/newZoom;
  let anchor={x:v.x+v.w/2,y:v.y+v.h/2};if(clientX!=null&&clientY!=null){const pt=mapPointFromClient(clientX,clientY);if(pt)anchor=pt;}
  const rx=(anchor.x-v.x)/v.w,ry=(anchor.y-v.y)/v.h;mapZoomState.view=mapViewClamp({x:anchor.x-rx*newW,y:anchor.y-ry*newH,w:newW,h:newH});applyMapView();
}
function bboxForIds(ids){
  if(!state.mapPaths?.size)return null;let x1=Infinity,y1=Infinity,x2=-Infinity,y2=-Infinity,n=0;
  for(const id of ids||[]){const el=state.mapPaths.get(id);if(!el)continue;let b;try{b=el.getBBox();}catch(_){continue;}if(!b||!Number.isFinite(b.x))continue;x1=Math.min(x1,b.x);y1=Math.min(y1,b.y);x2=Math.max(x2,b.x+b.width);y2=Math.max(y2,b.y+b.height);n++;}
  return n?{x:x1,y:y1,w:Math.max(.1,x2-x1),h:Math.max(.1,y2-y1),n}:null;
}
function fitMapBBox(box,padding=.18,maxZoom=7){
  if(!box){resetMapZoom();return;}const b=mapZoomState.base,aspect=b.w/b.h,cx=box.x+box.w/2,cy=box.y+box.h/2;
  let w=Math.max(box.w*(1+padding*2),box.h*aspect*(1+padding*2));w=clamp(w,b.w/maxZoom,b.w);let h=w/aspect;
  mapZoomState.view=mapViewClamp({x:cx-w/2,y:cy-h/2,w,h});applyMapView();
}
function fitFilteredSeats(){
  const ids=state.explorerMatchingIds&&state.explorerMatchingIds.size?state.explorerMatchingIds:new Set(state.mapPaths.keys());
  if(ids.size>=state.mapPaths.size){resetMapZoom();return;}fitMapBBox(bboxForIds(ids),.12,7);
}
function fitSelectedSeat(){if(!state.selectedSeat)return;fitMapBBox(bboxForIds([state.selectedSeat]),.55,7);}
function initMapNavigation(){
  const map=$('#ukMap'),wrap=$('#mapWrap');if(!map||!wrap||map.dataset.navReady==='1')return;map.dataset.navReady='1';
  wrap.querySelectorAll('[data-mapzoom]').forEach(btn=>btn.addEventListener('click',()=>{const a=btn.dataset.mapzoom;if(a==='in')zoomMapAt(1.55);else if(a==='out')zoomMapAt(1/1.55);else if(a==='filtered')fitFilteredSeats();else if(a==='clearfilters'){resetSeatFilters();resetMapZoom();}else resetMapZoom();}));
  map.addEventListener('wheel',ev=>{if(!state.mapPaths?.size)return;ev.preventDefault();zoomMapAt(ev.deltaY<0?1.22:1/1.22,ev.clientX,ev.clientY);},{passive:false});
  map.addEventListener('pointerdown',ev=>{const z=mapZoomState.base.w/mapZoomState.view.w;if(z<=1.001)return;if(ev.pointerType==='mouse'&&ev.button!==0)return;mapZoomState.panning=true;mapZoomState.pointerId=ev.pointerId;mapZoomState.startX=ev.clientX;mapZoomState.startY=ev.clientY;mapZoomState.startView={...mapZoomState.view};mapZoomState.moved=false;map.setPointerCapture?.(ev.pointerId);applyMapView();});
  map.addEventListener('pointermove',ev=>{if(!mapZoomState.panning||ev.pointerId!==mapZoomState.pointerId)return;const r=map.getBoundingClientRect();if(!r.width||!r.height)return;const dx=(ev.clientX-mapZoomState.startX)/r.width*mapZoomState.startView.w,dy=(ev.clientY-mapZoomState.startY)/r.height*mapZoomState.startView.h;if(Math.hypot(ev.clientX-mapZoomState.startX,ev.clientY-mapZoomState.startY)>4)mapZoomState.moved=true;mapZoomState.view=mapViewClamp({...mapZoomState.startView,x:mapZoomState.startView.x-dx,y:mapZoomState.startView.y-dy});applyMapView();});
  const stop=ev=>{if(!mapZoomState.panning||ev.pointerId!==mapZoomState.pointerId)return;if(mapZoomState.moved)mapZoomState.suppressClick=true;mapZoomState.panning=false;mapZoomState.pointerId=null;try{map.releasePointerCapture?.(ev.pointerId);}catch(_){}applyMapView();};map.addEventListener('pointerup',stop);map.addEventListener('pointercancel',stop);
}
function partyColorFrom2024(id){const c=state.byId.get(id)||state.constituencyIndex.get(id);return PARTY[c?.winner2024||'other']?.color||PARTY.other.color;}
function selectSeat(id){
  state.selectedSeat=id;
  if(state.selectedPath)state.selectedPath.classList.remove('selected');
  state.selectedPath=state.mapPaths.get(id)||null;
  if(state.selectedPath)state.selectedPath.classList.add('selected');
  const zb=$('#detailZoomBtn'),cb=$('#detailCopyBtn'),pb=$('#detailPngBtn'),sb=$('#detailShareBtn');if(zb)zb.disabled=!state.selectedPath;if(cb)cb.disabled=false;if(pb)pb.disabled=false;if(sb)sb.disabled=false;
  renderDetail(id);
}
function margin2024(seat){return seatMarginFromShares(seat,seat?.shares||{});}
function probabilityLabel(p){if(p==null)return 'Monte Carlo in corso';if(p<.55)return 'Testa a testa';if(p<.65)return 'Incerto';if(p<.80)return 'Competitivo';return 'Solido';}
function copySeatDeepLink(){
  if(!state.selectedSeat)return;const url=new URL(location.href);url.searchParams.set('seat',state.selectedSeat);url.hash='territorio';const text=url.toString();
  const btn=$('#detailCopyBtn'),done=()=>{if(!btn)return;const old=btn.textContent;btn.textContent='Link copiato';setTimeout(()=>btn.textContent=old,1400);};
  if(navigator.clipboard?.writeText)navigator.clipboard.writeText(text).then(done).catch(()=>fallbackCopy(text,done));else fallbackCopy(text,done);
}
function fallbackCopy(text,done){const ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done?.();}catch(_){}ta.remove();}
function restoreSeatDeepLink(){const id=new URLSearchParams(location.search).get('seat');if(!id||!state.byId.has(id))return;selectSeat(id);setTimeout(()=>fitSelectedSeat(),0);}
function renderDetail(id){
  const seat=state.byId.get(id)||state.constituencies.find(x=>x.id===id);if(!seat)return;$('#detailName').textContent=seat.name;$('#detailRegion').textContent=[seat.region,seat.country,seat.id].filter(Boolean).map((v,i)=>i<2?regionalDisplayName(v):v).join(' · ');
  const customActive=state.mapMode==='custom'&&state.customScenario?.sharesById?.[id],proj=customActive?state.customScenario.sharesById[id]:(seat.projected||{}),liveProj=seat.projected||{},prob=state.mc?.seatProb?.[id]||null;
  const cm=seatMarginFromShares(seat,proj),liveCm=seatMarginFromShares(seat,liveProj),prev=margin2024(seat);const scenarioWinner=customActive?state.customScenario.assignment[id]:(state.representative?.assignment?.[id]||seat.centralWinner||seat.winner2024),centralWinner=seat.centralWinner||seat.winner2024;
  const scenarioLabel=customActive?'Scenario utente':(state.representative?'Scenario rappresentativo':'Proiezione centrale');const bestProb=prob?Math.max(...Object.values(prob)):null;const probWinner=prob?Object.entries(prob).sort((a,b)=>b[1]-a[1])[0]?.[0]:null;const changed=scenarioWinner!==(seat.winner2024||'other');
  const shareRows=Object.keys(proj).filter(p=>PARTY[p]&&(proj[p]||0)>.15).sort((a,b)=>(proj[b]||0)-(proj[a]||0)).slice(0,6);
  const probRows=prob?Object.entries(prob).filter(([p,v])=>PARTY[p]&&v>.003).sort((a,b)=>b[1]-a[1]).slice(0,5):[];
  const candidate=seat.winner2024_candidate?` · ${escapeHtml(seat.winner2024_candidate)}`:'';const majorityVotes=Number(seat.majority2024)||0,validVotes=Number(seat.valid_votes)||0;
  const scenarioBadge=`<span class="seat-status-badge ${changed?'gain':'hold'}">${changed?'Cambio':'Conferma'} vs 2024</span>${bestProb!=null?`<span class="seat-status-badge risk">${probabilityLabel(bestProb)} · ${pctFmt(bestProb*100)}</span>`:''}`;
  const scenarioNote=customActive?'Scenario personalizzato: quote deterministiche. Le probabilità sotto restano quelle del nowcast corrente.':state.representative&&scenarioWinner!==centralWinner?'Lo scenario territoriale rappresentativo rialloca questo collegio rispetto al centro deterministico per aderire alle mediane nazionali.':'Il vincitore rappresentativo coincide con il centro deterministico in questo collegio.';
  $('#detailBody').innerHTML=`<div class="detail-badges">${scenarioBadge}</div><div class="detail-stat"><span>Vincitore 2024</span><strong>${escapeHtml(seat.winner2024_name||PARTY[seat.winner2024]?.name||'Altro')}${candidate}</strong></div><div class="detail-stat"><span>Margine 2024</span><strong>${fmt1(prev.margin)} p.p.${majorityVotes?` · ${fmt0(majorityVotes)} voti`:''}</strong></div><div class="detail-stat"><span>${scenarioLabel}</span><strong>${PARTY[scenarioWinner]?.name||'—'}</strong></div><div class="detail-stat"><span>Margine ${customActive?'scenario':'centrale'}</span><strong>${fmt1(customActive?cm.margin:liveCm.margin)} p.p. · ${PARTY[(customActive?cm:liveCm).runner]?.short||'—'} secondo</strong></div>${customActive?`<div class="detail-stat"><span>Nowcast corrente</span><strong>${PARTY[centralWinner]?.name||'—'} · ${fmt1(liveCm.margin)} p.p.</strong></div>`:''}${validVotes?`<div class="detail-stat"><span>Voti validi 2024</span><strong>${fmt0(validVotes)}</strong></div>`:''}<div class="detail-section-title">Quote ${customActive?'scenario':'centrali'}</div><div class="detail-score share-mode">${shareRows.map(p=>`<div><span>${PARTY[p].short}</span><span class="mini-track"><i style="width:${clamp((proj[p]||0)*2,0,100)}%;background:${PARTY[p].color}"></i></span><strong>${pctFmt(proj[p]||0)}</strong></div>`).join('')}</div><div class="detail-section-title">Probabilità di vittoria nel nowcast</div>${probRows.length?`<div class="detail-score probability-mode">${probRows.map(([p,v])=>`<div><span>${PARTY[p].short}</span><span class="mini-track"><i style="width:${clamp(v*100,0,100)}%;background:${PARTY[p].color}"></i></span><strong>${pctFmt(v*100)}</strong></div>`).join('')}</div>`:'<div class="detail-pending">Disponibile al termine delle 50.000 simulazioni.</div>'}<p class="small-note">${scenarioNote}${seat.isNorthernIreland?' NI: candidature 2024 mantenute; segnale dell’Assemblea usato solo come segnale debole.':''}</p>`;
}

function mapWinnerForSeat(seat){
  if(!seat)return'other';
  if(state.mapMode==='custom'&&state.customScenario?.assignment?.[seat.id])return state.customScenario.assignment[seat.id];
  if(state.mapMode==='representative'&&state.representative?.assignment?.[seat.id])return state.representative.assignment[seat.id];
  if(state.mapMode==='prob'&&state.mc?.seatProb?.[seat.id])return Object.entries(state.mc.seatProb[seat.id]).sort((a,b)=>b[1]-a[1])[0]?.[0]||seat.centralWinner||'other';
  if(state.mapMode==='margin')return centralSeatMargin(seat).winner;
  return seat.centralWinner||seat.winner2024||'other';
}
function mapColorForSeat(seat){
  const winner=mapWinnerForSeat(seat),base=PARTY[winner]?.color||PARTY.other.color;
  if(state.mapMode==='margin'){const cm=centralSeatMargin(seat);return mixWithDark(base,clamp(cm.margin/16,.08,1));}
  if(state.mapMode==='prob'&&state.mc?.seatProb?.[seat.id]){const p=Math.max(...Object.values(state.mc.seatProb[seat.id]||{}));return mixWithDark(base,p);}
  return base;
}
function renderMapLegend(){
  const partyEl=$('#mapPartyLegend'),intensityEl=$('#mapIntensityLegend');if(!partyEl||!intensityEl||!state.central?.seats?.length)return;
  const counts=new Map();for(const seat of state.central.seats){const p=mapWinnerForSeat(seat);counts.set(p,(counts.get(p)||0)+1);}
  const visible=[...counts.entries()].filter(([,n])=>n>0).sort((a,b)=>b[1]-a[1]||String(a[0]).localeCompare(String(b[0]))).slice(0,14);
  partyEl.innerHTML=`<span class="map-legend-label">Partiti</span>${visible.map(([p,n])=>`<span class="map-party-key" title="${escapeHtml(PARTY[p]?.name||p)} · ${fmt0(n)} collegi"><i style="background:${PARTY[p]?.color||PARTY.other.color}"></i><b>${escapeHtml(PARTY[p]?.short||p)}</b><small>${fmt0(n)}</small></span>`).join('')}`;
  if(state.mapMode==='margin')intensityEl.innerHTML='<strong>Intensità:</strong><span>vantaggio ridotto</span><i class="map-intensity-ramp"></i><span>vantaggio ampio (16+ p.p.)</span>';
  else if(state.mapMode==='prob')intensityEl.innerHTML='<strong>Intensità:</strong><span>vittoria incerta</span><i class="map-intensity-ramp"></i><span>vittoria più probabile</span>';
  else intensityEl.innerHTML='<strong>Legenda:</strong><span>il colore indica il partito assegnatario del collegio nella vista selezionata.</span>';
}
function applyMapColors(){
  if(!state.mapPaths?.size)return;
  for(const [id,el] of state.mapPaths){const seat=state.byId.get(id);if(!seat)continue;el.setAttribute('fill',mapColorForSeat(seat));}
  updateMapModeButtons();renderMapSummary();renderMapLegend();applyExplorerMapFilter();
  if(state.selectedSeat)renderDetail(state.selectedSeat);
  syncViewContextBar();
}
function mixWithDark(hex,prob){const h=hex.replace('#','');const r=parseInt(h.slice(0,2),16),g=parseInt(h.slice(2,4),16),b=parseInt(h.slice(4,6),16);const k=.35+.65*clamp(prob,0,1);return `rgb(${Math.round(r*k)},${Math.round(g*k)},${Math.round(b*k)})`;}


function centralSeatMargin(seat){
  const rows=Object.entries(seat?.projected||{})
    .filter(([p,v])=>PARTY[p]&&Number.isFinite(Number(v))&&Number(v)>.001)
    .sort((a,b)=>Number(b[1])-Number(a[1]));
  const first=rows[0]||[seat?.centralWinner||'other',0],second=rows[1]||['other',0];
  return {winner:first[0],runner:second[0],margin:Math.max(0,Number(first[1])-Number(second[1])),winnerShare:Number(first[1])||0,runnerShare:Number(second[1])||0};
}
function representativeTargets(medians){
  const raw=SEAT_ORDER.map(p=>({p,v:Math.max(0,Number(medians?.[p])||0)}));
  const sum=raw.reduce((a,x)=>a+x.v,0)||650;
  const scaled=raw.map(x=>({...x,x:x.v/sum*650}));
  const out=Object.fromEntries(scaled.map(x=>[x.p,Math.floor(x.x)]));
  let left=650-Object.values(out).reduce((a,b)=>a+b,0);
  scaled.sort((a,b)=>(b.x-Math.floor(b.x))-(a.x-Math.floor(a.x)));
  for(let i=0;i<left;i++)out[scaled[i%scaled.length].p]++;
  return out;
}
function buildRepresentativeScenario(m){
  if(!state.central?.seats?.length||!m?.seatProb)return null;
  const target=representativeTargets(m.medians),assign={},counts=Object.fromEntries(SEAT_ORDER.map(p=>[p,0]));
  for(const seat of state.central.seats){
    const probs=m.seatProb?.[seat.id]||{};
    const ranked=Object.entries(probs).filter(([p,v])=>PARTY[p]&&Number(v)>0).sort((a,b)=>b[1]-a[1]);
    const winner=ranked[0]?.[0]||seat.centralWinner||seat.winner2024||'other';assign[seat.id]=winner;counts[winner]=(counts[winner]||0)+1;
  }
  const eps=1e-9,maxMoves=5000;let moves=0;
  while(moves<maxMoves){
    const over=SEAT_ORDER.filter(p=>(counts[p]||0)>(target[p]||0));
    const under=SEAT_ORDER.filter(p=>(counts[p]||0)<(target[p]||0));
    if(!over.length||!under.length)break;
    let best=null;
    for(const seat of state.central.seats){
      const from=assign[seat.id];if(!over.includes(from))continue;
      const probs=m.seatProb?.[seat.id]||{},pFrom=Math.max(eps,Number(probs[from])||eps);
      for(const to of under){
        const pTo=Number(probs[to])||0;if(pTo<=0)continue;
        const loss=Math.log(pFrom)-Math.log(Math.max(eps,pTo));
        if(!best||loss<best.loss)best={id:seat.id,from,to,loss};
      }
    }
    if(!best)break;
    assign[best.id]=best.to;counts[best.from]--;counts[best.to]++;moves++;
  }
  const mismatch=SEAT_ORDER.reduce((s,p)=>s+Math.abs((counts[p]||0)-(target[p]||0)),0);
  const centralChanged=state.central.seats.reduce((n,seat)=>n+(assign[seat.id]!==seat.centralWinner?1:0),0);
  return {assignment:assign,counts,target,mismatch,moves,centralChanged};
}
function updateMapModeButtons(){
  const ids={central:'#mapCentralBtn',representative:'#mapCentralBtn',margin:'#mapMarginBtn',prob:'#mapProbBtn',custom:'#mapUserBtn'};
  $$('#mapModeControls button').forEach(b=>b.classList.remove('active'));
  const selector=ids[state.mapMode]||'#mapCentralBtn';$(selector)?.classList.add('active');
  const central=$('#mapCentralBtn');if(central)central.textContent=state.mc?.seatProb?'Scenario':'Proiezione';
}
function renderMapSummary(){
  const el=$('#mapSummary');if(!el||!state.central?.seats?.length)return;
  const seats=state.central.seats,rep=state.representative?.assignment;
  const winnerFor=seat=>{if(state.mapMode==='custom'&&state.customScenario?.assignment?.[seat.id])return state.customScenario.assignment[seat.id];if(state.mapMode==='representative'&&rep?.[seat.id])return rep[seat.id];if(state.mapMode==='prob'&&state.mc?.seatProb?.[seat.id])return Object.entries(state.mc.seatProb[seat.id]).sort((a,b)=>b[1]-a[1])[0]?.[0]||seat.centralWinner;return seat.centralWinner;};
  const changes=seats.reduce((n,s)=>n+(winnerFor(s)!==(s.winner2024||'other')?1:0),0);
  const tight=seats.filter(s=>centralSeatMargin(s).margin<5).length;
  const uncertain=state.mc?.seatProb?seats.filter(s=>Math.max(...Object.values(state.mc.seatProb[s.id]||{other:1}))<.65).length:null;
  const mode=state.mapMode==='custom'?'Scenario utente':state.mapMode==='prob'?'Probabilità di vittoria':state.mapMode==='margin'?'Margine centrale':state.mapMode==='representative'?'Scenario rappresentativo':'Scenario alla media';
  const repNote=state.mapMode==='representative'&&state.representative?`<span class="map-summary-chip"><strong>${state.representative.centralChanged}</strong> collegi riallocati per aderire alle mediane</span>`:state.mapMode==='custom'&&state.customScenario?`<span class="map-summary-chip"><strong>${state.customScenario.changedFromLive}</strong> vincitori diversi dal nowcast corrente</span>`:'';
  const filterNote=$('#seatFilterMap')?.checked&&state.explorerMatchingIds&&state.explorerMatchingIds.size<seats.length?`<span class="map-summary-chip accent"><strong>${state.explorerMatchingIds.size}</strong> collegi evidenziati dai filtri</span>`:'';
  el.innerHTML=`<span class="map-summary-chip accent"><strong>${mode}</strong></span><span class="map-summary-chip"><strong>${changes}</strong> cambi di vincitore vs 2024</span><span class="map-summary-chip"><strong>${tight}</strong> collegi entro 5 p.p.</span>${uncertain==null?'':`<span class="map-summary-chip"><strong>${uncertain}</strong> con max P(vittoria) &lt;65%</span>`}${repNote}${filterNote}`;
}
function liveScenarioWinner(seat){
  return state.representative?.assignment?.[seat.id]||seat.centralWinner||seat.winner2024||'other';
}
function explorerSource(){
  const source=$('#seatSource')?.value||'live';
  return source==='custom'&&state.customScenario?'custom':'live';
}
function scenarioWinnerForSeat(seat,source=explorerSource()){
  if(source==='custom'&&state.customScenario?.assignment?.[seat.id])return state.customScenario.assignment[seat.id];
  return liveScenarioWinner(seat);
}
function scenarioSharesForSeat(seat,source=explorerSource()){
  if(source==='custom'&&state.customScenario?.sharesById?.[seat.id])return state.customScenario.sharesById[seat.id];
  return seat.projected||{};
}
function seatMarginFromShares(seat,shares){
  const rows=Object.entries(shares||{}).filter(([p,v])=>PARTY[p]&&Number.isFinite(Number(v))&&Number(v)>.001).sort((a,b)=>Number(b[1])-Number(a[1]));
  const first=rows[0]||[seat?.centralWinner||'other',0],second=rows[1]||['other',0];
  return {winner:first[0],runner:second[0],margin:Math.max(0,Number(first[1])-Number(second[1])),winnerShare:Number(first[1])||0,runnerShare:Number(second[1])||0};
}
function scenarioModelParties(){return ['lab','con','ref','ld','green','snp','pc','other'];}
function scenarioBaseTarget(){
  const src=state.central?.target||{};const ps=scenarioModelParties();let total=ps.reduce((s,p)=>s+Math.max(0,Number(src[p])||0),0)||1;
  return Object.fromEntries(ps.map(p=>[p,Math.max(0,Number(src[p])||0)/total*100]));
}
function normalizeScenarioTarget(raw){
  const ps=scenarioModelParties();let total=ps.reduce((s,p)=>s+Math.max(0,Number(raw[p])||0),0);
  if(total<=0)return Object.fromEntries(ps.map(p=>[p,0]));
  return Object.fromEntries(ps.map(p=>[p,Math.max(0,Number(raw[p])||0)/total*100]));
}
function scenarioInputValues(){
  const out={};for(const p of scenarioModelParties())out[p]=Math.max(0,Number($(`#scenario-${p}`)?.value)||0);return out;
}
function updateScenarioTotal(){
  const total=Object.values(scenarioInputValues()).reduce((a,b)=>a+b,0);const el=$('#scenarioTotal');if(el){el.textContent=pctFmt(total);el.classList.toggle('bad-total',Math.abs(total-100)>.051);}return total;
}
function renderScenarioInputs(reset=false){
  const el=$('#scenarioInputs');if(!el||!state.central)return;const base=scenarioBaseTarget();
  if(reset||!el.children.length)el.innerHTML=scenarioModelParties().map(p=>`<label class="scenario-input"><span><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</span><span class="scenario-number"><input id="scenario-${p}" data-scenario-party="${p}" type="number" min="0" max="100" step="0.1" value="${(base[p]||0).toFixed(1)}"><b>%</b></span></label>`).join('');
  $$('[data-scenario-party]').forEach(input=>input.addEventListener('input',updateScenarioTotal));updateScenarioTotal();
}
function normalizeScenarioInputs(){
  const norm=normalizeScenarioTarget(scenarioInputValues());for(const p of scenarioModelParties()){const el=$(`#scenario-${p}`);if(el)el.value=(norm[p]||0).toFixed(1);}updateScenarioTotal();
}
function buildCustomScenario(rawTarget){
  if(!state.central?.seats?.length)return null;const target=normalizeScenarioTarget(rawTarget),base=scenarioBaseTarget();
  const assignment={},sharesById={},totals=Object.fromEntries(SEAT_ORDER.map(p=>[p,0]));
  for(const seat of state.central.seats){
    if(seat.isNorthernIreland){const w=seat.centralWinner||seat.winner2024||'ni_other';assignment[seat.id]=w;sharesById[seat.id]={...(seat.projected||{})};totals[w]=(totals[w]||0)+1;continue;}
    const raw={};let sum=0;
    for(const p of scenarioModelParties()){
      if(!partyAllowed(p,seat)||(p==='other'&&seat.mrpLite&&seat.otherEligible!==true)){raw[p]=0;continue;}
      const live=Math.max(.0001,Number(seat.projected?.[p])||0),bn=Math.max(.05,Number(base[p])||.05);
      const relative=live/bn;raw[p]=Math.max(.000001,(target[p]||0)*relative);sum+=raw[p];
    }
    const shares={};for(const p of scenarioModelParties())shares[p]=sum>0?raw[p]/sum*100:0;
    const allowed=scenarioModelParties().filter(p=>partyAllowed(p,seat)&&!(p==='other'&&seat.mrpLite&&seat.otherEligible!==true));const winner=allowed.reduce((best,p)=>(shares[p]||0)>(shares[best]??-1)?p:best,allowed[0]||'other');
    assignment[seat.id]=winner;sharesById[seat.id]=shares;totals[winner]=(totals[winner]||0)+1;
  }
  const liveAssign=Object.fromEntries(state.central.seats.map(s=>[s.id,liveScenarioWinner(s)]));
  const changedFromLive=state.central.seats.reduce((n,s)=>n+(assignment[s.id]!==liveAssign[s.id]?1:0),0);
  return {target,assignment,sharesById,totals,changedFromLive,createdAt:new Date().toISOString()};
}
function renderCustomScenario(){
  const s=state.customScenario,table=$('#scenarioSeatTable'),strip=$('#scenarioSeatStrip');if(!table||!strip)return;
  if(!s){table.innerHTML='<div class="empty-small">Calcola uno scenario per vedere la distribuzione dei seggi.</div>';strip.innerHTML='';$('#scenarioChanges').textContent='—';return;}
  const sum=SEAT_ORDER.reduce((a,p)=>a+(s.totals[p]||0),0)||650;
  strip.innerHTML=SEAT_ORDER.filter(p=>(s.totals[p]||0)>0).map(p=>`<span style="width:${(s.totals[p]/sum)*100}%;background:${PARTY[p]?.color||PARTY.other.color}" title="${PARTY[p]?.name||p}: ${fmt0(s.totals[p])}"></span>`).join('');
  table.innerHTML=SEAT_ORDER.filter(p=>(s.totals[p]||0)>0).map(p=>{const live=state.mc?.medians?.[p]??state.central?.totals?.[p]??0,d=(s.totals[p]||0)-live;return `<div class="seat-row"><div class="left"><i class="party-dot" style="background:${PARTY[p]?.color||PARTY.other.color}"></i>${PARTY[p]?.short||p}</div><strong>${fmt0(s.totals[p])} <small class="scenario-delta ${d>0?'up':d<0?'down':''}">${d===0?'=':(d>0?'+':'')+fmt0(d)}</small></strong></div>`;}).join('');
  $('#scenarioChanges').textContent=`${fmt0(s.changedFromLive)} collegi cambiano vincitore rispetto al nowcast corrente`;
  $('#scenarioMapBtn').disabled=false;$('#mapUserBtn').disabled=false;$('#mapUserBtn').setAttribute('aria-disabled','false');const src=$('#seatSource');if(src){const o=src.querySelector('option[value="custom"]');if(o)o.disabled=false;}
}
function runCustomScenario(){
  const originalTotal=updateScenarioTotal(),raw=scenarioInputValues();state.customScenario=buildCustomScenario(raw);renderCustomScenario();
  state.scenarioHemicycleActive=true;renderCustomSeatProjection();renderRegionalDashboard();syncViewContextBar();
  const msg=$('#scenarioMessage');if(msg)msg.textContent=`Scenario calcolato su ${fmt0(Object.values(state.customScenario?.totals||{}).reduce((a,b)=>a+b,0))} seggi. ${Math.abs(originalTotal-100)>.051?`Gli input (${pctFmt(originalTotal)}) sono stati normalizzati automaticamente a 100%. `:''}L’emiciclo mostra già lo scenario personalizzato; mappa, regioni e collegi restano sul nowcast finché non premi «Attiva scenario nelle viste». Le probabilità Monte Carlo restano quelle del nowcast corrente.`;
  state.explorerPage=1;renderMarginals();
}
function resetCustomScenario(){
  state.scenarioHemicycleActive=false;state.customScenario=null;renderScenarioInputs(true);renderCustomScenario();renderNowcastSeatProjection();const src=$('#seatSource');if(src){src.value='live';const o=src.querySelector('option[value="custom"]');if(o)o.disabled=true;}
  const mb=$('#mapUserBtn');if(mb){mb.disabled=true;mb.setAttribute('aria-disabled','true');}if(state.mapMode==='custom')state.mapMode=state.mc?.seatProb?'representative':'central';applyMapColors();state.explorerPage=1;renderMarginals();
  const reg=$('#regionalSource');if(reg)reg.value='live';renderRegionalDashboard();
  const msg=$('#scenarioMessage');if(msg)msg.textContent='Scenario ripristinato. Emiciclo, mappa, regioni e collegi sono tornati al nowcast completo; il Monte Carlo di produzione non è stato modificato.';syncViewContextBar();
}
let scenarioThresholdRunToken=0,scenarioThresholdResult=null;
function scenarioTargetAtPartyShare(party,share,base=scenarioBaseTarget()){
  const parties=scenarioModelParties();share=clamp(Number(share)||0,.1,99.5);const otherTotal=parties.filter(p=>p!==party).reduce((n,p)=>n+Math.max(0,Number(base[p])||0),0),remaining=100-share,out={};
  for(const p of parties){if(p===party){out[p]=share;continue;}out[p]=otherTotal>0?remaining*(Math.max(0,Number(base[p])||0)/otherTotal):remaining/(parties.length-1);}
  return out;
}
function scenarioDeterministicSeatsAtShare(party,share,targetSeats,base){
  const scenario=buildCustomScenario(scenarioTargetAtPartyShare(party,share,base));return {seats:Number(scenario?.totals?.[party]||0),scenario,targetSeats};
}
function scenarioThresholdDeterministicBracket(party,targetSeats,base){
  let low=.1,high=85;
  if(scenarioDeterministicSeatsAtShare(party,high,targetSeats,base).seats<targetSeats)return null;
  for(let i=0;i<12;i++){const mid=(low+high)/2;if(scenarioDeterministicSeatsAtShare(party,mid,targetSeats,base).seats>=targetSeats)high=mid;else low=mid;}
  const guess=Math.ceil(high*10)/10;return {low:Math.max(.1,guess-4),high:Math.min(90,guess+4),guess};
}
function prepareScenarioMedianModel(rawTarget){
  const scenario=buildCustomScenario(rawTarget);if(!scenario)return null;const target=scenario.target,seats=state.central.seats,regions=[...new Set(seats.map(s=>s.isNorthernIreland?'Northern Ireland':(s.modelZone||s.region||s.country||'Other')))],regionIndex=new Map(regions.map((r,i)=>[r,i]));
  const models=seats.map(s=>{
    const zone=s.isNorthernIreland?'Northern Ireland':(s.modelZone||s.region||s.country||'Other');
    if(s.isNorthernIreland){
      const candidates=NI_ORDER.filter(p=>(s.projected?.[p]||0)>.001).map(p=>({p,baseLog:Math.log(Math.max(.03,s.projected[p]||.03)),central:s.projected[p]||0})).sort((a,b)=>b.central-a.central);
      return {id:s.id,region:regionIndex.get(zone),candidates,ni:true};
    }
    const shares=scenario.sharesById?.[s.id]||s.projected||{};
    const candidates=scenarioModelParties().filter(p=>partyAllowed(p,s)&&(p!=='other'||!s.mrpLite||s.otherEligible===true)).map(p=>({p,baseLog:Math.log(Math.max(.03,Number(shares[p])||.03)),central:Number(shares[p])||0})).sort((a,b)=>b.central-a.central).slice(0,5);
    return {id:s.id,region:regionIndex.get(zone),candidates,ni:false};
  });
  return {models,regions,target,scenario};
}
async function scenarioMedianSimulation(rawTarget,focusParty,sims,{seedTag='threshold',onProgress=null,runToken=null}={}){
  const prepared=prepareScenarioMedianModel(rawTarget);if(!prepared)throw new Error('Scenario non disponibile');
  const {models,regions,target}=prepared,N=Math.max(1000,Math.round(Number(sims)||1000)),drawParties=scenarioModelParties(),counts=new Uint16Array(N),rng=mulberry32(hashString(`${simulationSeedKey()}|scenario-majority|${focusParty}|${seedTag}`));
  for(let start=0;start<N;start+=CONFIG.mcBatch){
    if(runToken!=null&&runToken!==scenarioThresholdRunToken)throw new DOMException('Calcolo sostituito','AbortError');
    const end=Math.min(N,start+CONFIG.mcBatch);
    for(let sim=start;sim<end;sim++){
      const drawn={};let sum=0;
      for(const p of drawParties){const sigma=CONFIG.nationalSigma[p]||.8;drawn[p]=Math.max(.05,(target[p]||.05)+normalApprox(rng)*sigma);sum+=drawn[p];}
      for(const p of drawParties)drawn[p]=drawn[p]/sum*100;
      const natShift={};for(const p of drawParties)natShift[p]=CONFIG.swingLambda*Math.log(Math.max(.05,drawn[p])/Math.max(.05,target[p]||.05));
      const regNoise=Array.from({length:regions.length},()=>Object.fromEntries(drawParties.map(p=>[p,logistic(rng)*CONFIG.regionNoise]))),niPartyNoise=Object.fromEntries(NI_ORDER.map(p=>[p,logistic(rng)*CONFIG.niNationalNoise]));
      let focusSeats=0;
      for(const model of models){
        let bestP=model.ni?'ni_other':'other',bestScore=-Infinity;
        for(const cand of model.candidates){const score=model.ni?cand.baseLog+niPartyNoise[cand.p]+logistic(rng)*CONFIG.niLocalNoise:cand.baseLog+(natShift[cand.p]||0)+(regNoise[model.region]?.[cand.p]||0)+logistic(rng)*CONFIG.localNoise;if(score>bestScore){bestScore=score;bestP=cand.p;}}
        if(bestP===focusParty)focusSeats++;
      }
      counts[sim]=focusSeats;
    }
    onProgress?.(end,N);await sleepFrame();
  }
  const sorted=Array.from(counts).sort((a,b)=>a-b);return {sims:N,median:quantileSorted(sorted,.5),interval:[quantileSorted(sorted,.1),quantileSorted(sorted,.9)],counts};
}
function setScenarioMajorityBusy(busy,text='',progress=0){
  const box=$('#scenarioMajorityProgress'),label=box?.querySelector('span'),bar=box?.querySelector('progress');
  if(box){box.hidden=!busy;if(label&&text)label.textContent=text;if(bar)bar.value=clamp(progress,0,100);}
  $('#scenarioMajorityRun')?.toggleAttribute('disabled',busy);$$('[data-majority-party]').forEach(b=>b.disabled=busy);$('#scenarioMajorityParty')?.toggleAttribute('disabled',busy);$('#scenarioMajoritySeats')?.toggleAttribute('disabled',busy);
}
function renderScenarioMajorityResult(result){
  const el=$('#scenarioMajorityResult');if(!el)return;scenarioThresholdResult=result;
  if(!result){el.hidden=true;el.innerHTML='';return;}
  const {party,targetSeats,share,baseShare,summary,target}=result,delta=share-baseShare,prob=Array.from(summary.counts||[]).reduce((n,v)=>n+(v>=targetSeats?1:0),0)/Math.max(1,summary.sims||1);
  el.hidden=false;el.innerHTML=`<div class="scenario-majority-result-main"><span><i style="background:${PARTY[party].color}"></i>${escapeHtml(PARTY[party].name)}</span><strong>${pctFmt(share)}</strong><small>${delta>=0?'+':''}${fmt1(delta)} p.p. rispetto alla base dello scenario</small></div><div class="scenario-majority-result-metrics"><span>Mediana <strong>${fmt0(summary.median)} seggi</strong></span><span>Intervallo 80% <strong>${fmt0(summary.interval[0])}–${fmt0(summary.interval[1])}</strong></span><span>Prob. ≥ ${fmt0(targetSeats)} <strong>${pctFmt(prob*100)}</strong></span><span>Conferma <strong>${fmt0(summary.sims)} simulazioni</strong></span></div><div class="scenario-majority-result-actions"><button type="button" class="primary" data-apply-majority-scenario>Applica allo scenario</button><span>Quota indicativa minima a passi di 0,1 p.p.; gli altri partiti modellati mantengono i rapporti relativi della base corrente. Restore Britain resta esclusa dalla conversione.</span></div>`;
  el.querySelector('[data-apply-majority-scenario]')?.addEventListener('click',()=>{for(const p of scenarioModelParties()){const input=$(`#scenario-${p}`);if(input)input.value=(target[p]||0).toFixed(1);}updateScenarioTotal();runCustomScenario();document.querySelector('.scenario-builder-card')?.scrollIntoView({behavior:'smooth',block:'start'});});
}
async function runScenarioMajoritySearch(partyOverride=null){
  if(!state.central?.seats?.length)return;const party=partyOverride||$('#scenarioMajorityParty')?.value||'lab',targetSeats=clamp(Math.round(Number($('#scenarioMajoritySeats')?.value)||326),1,632),base=scenarioBaseTarget(),baseShare=Number(base[party])||0;
  if(!['lab','ref','con'].includes(party))return;const runToken=++scenarioThresholdRunToken;renderScenarioMajorityResult(null);setScenarioMajorityBusy(true,`Cerco la zona di ${PARTY[party].name}…`,2);
  try{
    const bracket=scenarioThresholdDeterministicBracket(party,targetSeats,base);if(!bracket)throw new Error(`${PARTY[party].name} non raggiunge ${fmt0(targetSeats)} seggi nell’intervallo esplorato.`);
    let low=bracket.low,high=bracket.high;const probeSims=3000,iterations=7;
    for(let i=0;i<iterations;i++){
      const mid=Math.round(((low+high)/2)*10)/10,target=scenarioTargetAtPartyShare(party,mid,base),phaseBase=5+i*(38/iterations);
      const probe=await scenarioMedianSimulation(target,party,probeSims,{seedTag:`${party}|${targetSeats}|common`,runToken,onProgress:(done,total)=>setScenarioMajorityBusy(true,`Ricerca ${i+1}/${iterations} · ${PARTY[party].short} ${fmt1(mid)}% · ${fmt0(done)}/${fmt0(total)}`,phaseBase+(done/total)*(38/iterations))});
      if(probe.median>=targetSeats)high=mid;else low=mid+.1;
      if(high-low<=.11)break;
    }
    let share=Math.ceil(high*10)/10,summary=null,target=null;
    for(let attempt=0;attempt<3;attempt++){
      target=scenarioTargetAtPartyShare(party,share,base);summary=await scenarioMedianSimulation(target,party,CONFIG.mcSims,{seedTag:`${party}|${targetSeats}|common`,runToken,onProgress:(done,total)=>setScenarioMajorityBusy(true,`Conferma finale · ${PARTY[party].short} ${fmt1(share)}% · ${fmt0(done)}/${fmt0(total)}`,45+(done/total)*54)});
      if(summary.median>=targetSeats)break;share=Math.round((share+.2)*10)/10;
    }
    if(!summary||summary.median<targetSeats)throw new Error(`La soglia non è stata confermata entro ${fmt1(share)}%.`);
    renderScenarioMajorityResult({party,targetSeats,share,baseShare,summary,target});setScenarioMajorityBusy(false,'',100);
  }catch(err){setScenarioMajorityBusy(false);if(err?.name==='AbortError')return;const el=$('#scenarioMajorityResult');if(el){el.hidden=false;el.innerHTML=`<div class="scenario-majority-error"><strong>Calcolo non completato</strong><span>${escapeHtml(err?.message||String(err))}</span></div>`;}}
}

function populateSeatExplorerFilters(){
  if(!state.central?.seats?.length)return;const seats=state.central.seats;
  const fill=(sel,vals,label,display=v=>v)=>{const el=$(sel);if(!el)return;const current=el.value;el.innerHTML=`<option value="">${label}</option>`+vals.map(v=>`<option value="${escapeHtml(v)}">${escapeHtml(display(v))}</option>`).join('');if(vals.includes(current))el.value=current;};
  const countries=[...new Set(seats.map(s=>s.country).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'it'));
  const selectedCountry=$('#seatCountry')?.value||'';const regions=[...new Set(seats.filter(s=>!selectedCountry||s.country===selectedCountry).map(s=>s.region).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'it'));
  fill('#seatCountry',countries,'Tutti',regionalDisplayName);fill('#seatRegion',regions,'Tutte',regionalDisplayName);
  const parties=[...new Set(seats.flatMap(s=>[s.winner2024,liveScenarioWinner(s),state.customScenario?.assignment?.[s.id]]).filter(p=>PARTY[p]))].sort((a,b)=>(PARTY[a]?.name||a).localeCompare(PARTY[b]?.name||b,'it'));
  const partyOpts=parties.map(p=>`<option value="${p}">${escapeHtml(PARTY[p]?.name||p)}</option>`).join('');
  for(const sel of ['#seatWinner','#seatWinner2024']){const el=$(sel);if(!el)continue;const current=el.value;el.innerHTML='<option value="">Tutti</option>'+partyOpts;if(parties.includes(current))el.value=current;}
}
function renderPagination(el,totalPages,current,onPage){
  if(!el)return;totalPages=Math.max(1,totalPages);current=clamp(current,1,totalPages);const parts=[];
  parts.push(`<button type="button" class="page-nav" data-page="${Math.max(1,current-1)}" ${current===1?'disabled':''} aria-label="Pagina precedente">‹</button>`);
  const compact=window.matchMedia?.('(max-width:760px)')?.matches;
  const wanted=[];
  if(!compact||totalPages<=9){for(let p=1;p<=totalPages;p++)wanted.push(p);}else{
    const keep=new Set([1,totalPages,current-2,current-1,current,current+1,current+2].filter(p=>p>=1&&p<=totalPages));wanted.push(...[...keep].sort((a,b)=>a-b));
  }
  let prev=0;
  for(const p of wanted){if(prev&&p-prev>1)parts.push('<span class="page-gap" aria-hidden="true">…</span>');parts.push(`<button type="button" class="page-num ${p===current?'active':''}" data-page="${p}" ${p===current?'aria-current="page"':''}>${p}</button>`);prev=p;}
  parts.push(`<button type="button" class="page-nav" data-page="${Math.min(totalPages,current+1)}" ${current===totalPages?'disabled':''} aria-label="Pagina successiva">›</button>`);
  el.innerHTML=parts.join('');el.querySelectorAll('[data-page]').forEach(btn=>btn.addEventListener('click',()=>{if(btn.disabled)return;onPage(Number(btn.dataset.page)||1);}));
}
function filterExplorerByWinner(p){
  resetSeatFilters();populateSeatExplorerFilters();const sel=$('#seatWinner');if(sel){if(!sel.querySelector(`option[value="${CSS.escape(p)}"]`)){const o=document.createElement('option');o.value=p;o.textContent=PARTY[p]?.name||p;sel.appendChild(o);}sel.value=p;}state.explorerPage=1;renderMarginals();document.querySelector('#collegi')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function seatExplorerItem(seat,source){
  const shares=scenarioSharesForSeat(seat,source),cm=seatMarginFromShares(seat,shares),projected=scenarioWinnerForSeat(seat,source),probs=state.mc?.seatProb?.[seat.id]||null,bestProb=probs?Math.max(...Object.values(probs)):null;
  return {seat,shares,cm,projected,bestProb,changed:projected!==(seat.winner2024||'other')};
}
function explorerFilterValues(){return {q:($('#seatSearch')?.value||'').trim().toLowerCase(),country:$('#seatCountry')?.value||'',region:$('#seatRegion')?.value||'',winner:$('#seatWinner')?.value||'',winner2024:$('#seatWinner2024')?.value||'',status:$('#seatStatus')?.value||'',sort:$('#seatSort')?.value||'uncertainty',source:explorerSource()};}
function itemPassesExplorer(x,f){
  const s=x.seat,name=`${s.name||''} ${s.region||''} ${s.country||''}`.toLowerCase();if(f.q&&!name.includes(f.q))return false;if(f.country&&s.country!==f.country)return false;if(f.region&&s.region!==f.region)return false;if(f.winner&&x.projected!==f.winner)return false;if(f.winner2024&&(s.winner2024||'other')!==f.winner2024)return false;
  if(f.status==='changed'&&!x.changed)return false;if(f.status==='held'&&x.changed)return false;if(f.status==='margin25'&&!(x.cm.margin<2.5))return false;if(f.status==='margin5'&&!(x.cm.margin<5))return false;if(f.status==='tossup55'&&!(x.bestProb!=null&&x.bestProb<.55))return false;if(f.status==='uncertain65'&&!(x.bestProb!=null&&x.bestProb<.65))return false;if(f.status==='safe80'&&!(x.bestProb!=null&&x.bestProb>=.80))return false;return true;
}
function sortExplorerItems(items,f){
  const uncertainty=v=>v.bestProb==null?2:v.bestProb;return items.sort((a,b)=>{
    if(f.sort==='margin')return a.cm.margin-b.cm.margin||a.seat.name.localeCompare(b.seat.name,'it');
    if(f.sort==='change')return Number(b.changed)-Number(a.changed)||a.cm.margin-b.cm.margin;
    if(f.sort==='name')return a.seat.name.localeCompare(b.seat.name,'it');
    if(f.sort==='winner')return (PARTY[a.projected]?.name||a.projected).localeCompare(PARTY[b.projected]?.name||b.projected,'it')||a.seat.name.localeCompare(b.seat.name,'it');
    return uncertainty(a)-uncertainty(b)||a.cm.margin-b.cm.margin;
  });
}
function explorerFiltersActive(){
  return ['seatSearch','seatCountry','seatRegion','seatWinner','seatWinner2024','seatStatus'].some(id=>String($(`#${id}`)?.value||'').trim()!=='');
}
function mapFilterLabel(id,value){
  if(!value)return '';
  if(id==='seatSearch')return `Ricerca: ${value}`;
  if(id==='seatCountry')return `Paese: ${regionalDisplayName(value)}`;
  if(id==='seatRegion')return `Regione: ${regionalDisplayName(value)}`;
  if(id==='seatWinner')return `Scenario: ${PARTY[value]?.short||value}`;
  if(id==='seatWinner2024')return `2024: ${PARTY[value]?.short||value}`;
  if(id==='seatStatus'){const labels={changed:'Cambio di seggio',held:'Seggio confermato',margin25:'Margine < 2,5 p.p.',margin5:'Margine < 5 p.p.',tossup55:'Favorito < 55%',uncertain65:'Favorito < 65%',safe80:'Favorito ≥ 80%'};return labels[value]||value;}
  return value;
}
function renderMapFilterChips(){
  const wrap=$('#mapActiveFilters');if(!wrap)return;
  const ids=['seatSearch','seatCountry','seatRegion','seatWinner','seatWinner2024','seatStatus'];
  const active=ids.map(id=>({id,value:String($(`#${id}`)?.value||'').trim()})).filter(x=>x.value);
  if(!active.length){wrap.hidden=true;wrap.innerHTML='';return;}
  wrap.hidden=false;
  wrap.innerHTML=`<span class="map-active-filters-label">Filtri attivi</span><div class="map-filter-chip-list">${active.map(x=>`<button type="button" class="map-filter-chip" data-clear-seat-filter="${x.id}" title="Rimuovi ${escapeHtml(mapFilterLabel(x.id,x.value))}"><span>${escapeHtml(mapFilterLabel(x.id,x.value))}</span><b aria-hidden="true">×</b></button>`).join('')}</div>${active.length>1?'<button type="button" class="map-filter-clear-all" data-clear-all-seat-filters>Rimuovi tutti</button>':''}`;
  wrap.querySelectorAll('[data-clear-seat-filter]').forEach(btn=>btn.addEventListener('click',()=>{const el=$(`#${btn.dataset.clearSeatFilter}`);if(el)el.value='';state.explorerPage=1;renderMarginals();}));
  wrap.querySelector('[data-clear-all-seat-filters]')?.addEventListener('click',resetSeatFilters);
}
function applyExplorerMapFilter(){
  renderMapFilterChips();
  if(!state.mapPaths?.size)return;const enabled=$('#seatFilterMap')?.checked!==false,ids=state.explorerMatchingIds,active=enabled&&explorerFiltersActive()&&!!ids&&ids.size<state.mapPaths.size;
  for(const [id,el] of state.mapPaths){const match=!enabled||!ids||ids.has(id);el.classList.toggle('filtered-out',!match);}
  const fit=$('[data-mapzoom="filtered"]');if(fit){const n=ids?.size||state.mapPaths.size;fit.disabled=!active;fit.classList.toggle('is-active',active);fit.textContent=active?`Filtrati (${n})`:'Filtrati';}
  const clear=$('[data-mapzoom="clearfilters"]');if(clear){clear.hidden=!active;clear.disabled=!active;}
}
function resetSeatFilters(){
  clearSeatFiltersRaw();const src=$('#seatSource');if(src)src.value='live';state.explorerPage=1;renderMarginals();syncViewContextBar();
}
function applySeatPreset(kind){
  resetSeatFilters();if(kind==='uncertain'){$('#seatStatus').value='uncertain65';$('#seatSort').value='uncertainty';}else if(kind==='changed'){$('#seatStatus').value='changed';$('#seatSort').value='margin';}else if(kind==='marginal'){$('#seatStatus').value='margin5';$('#seatSort').value='margin';}state.explorerPage=1;renderMarginals();
}
function renderMarginals(){
  const body=$('#marginalTableBody'),meta=$('#marginalMeta');if(!body||!state.central?.seats?.length)return;populateSeatExplorerFilters();
  const f=explorerFilterValues(),all=state.central.seats.map(seat=>seatExplorerItem(seat,f.source)),filtered=sortExplorerItems(all.filter(x=>itemPassesExplorer(x,f)),f);
  state.explorerMatchingIds=new Set(filtered.map(x=>x.seat.id));applyExplorerMapFilter();
  const pageSize=explorerPageSize(),pages=Math.max(1,Math.ceil(filtered.length/pageSize));state.explorerPage=clamp(state.explorerPage||1,1,pages);const start=(state.explorerPage-1)*pageSize,visible=filtered.slice(start,start+pageSize);
  const count=$('#seatExplorerCount');if(count)count.textContent=`${fmt0(filtered.length)} di ${fmt0(all.length)} collegi`;
  if(meta)meta.textContent=f.source==='custom'?'Filtri applicati allo scenario utente; le probabilità indicate restano quelle del Monte Carlo corrente.':'Cerca, filtra e ordina ogni collegio del nowcast corrente; l’incertezza è quella delle 50.000 simulazioni.';
  body.innerHTML=visible.length?visible.map(x=>{const prev=x.seat.winner2024||'other';return `<tr data-marginal-seat="${escapeHtml(x.seat.id)}"><td><strong>${escapeHtml(x.seat.name)}</strong><small>${escapeHtml(x.seat.id||'')}</small></td><td>${escapeHtml([x.seat.region,x.seat.country].filter(Boolean).map(regionalDisplayName).join(' · ')||'—')}</td><td><span class="party-pill"><i style="background:${PARTY[prev]?.color||PARTY.other.color}"></i>${PARTY[prev]?.short||'Altro'}</span></td><td><span class="party-pill ${x.changed?'changed':''}"><i style="background:${PARTY[x.projected]?.color||PARTY.other.color}"></i>${PARTY[x.projected]?.short||'Altro'}</span></td><td>${fmt1(x.cm.margin)} p.p.</td><td>${x.bestProb==null?'—':pctFmt(x.bestProb*100)}</td></tr>`;}).join(''):'<tr><td colspan="6"><div class="empty-small">Nessun collegio corrisponde ai filtri selezionati.</div></td></tr>';
  const seatMobile=$('#seatMobileList');if(seatMobile)seatMobile.innerHTML=visible.length?visible.map(x=>{const prev=x.seat.winner2024||'other',area=[x.seat.region,x.seat.country].filter(Boolean).map(regionalDisplayName).join(' · ')||'—';return `<button type="button" class="seat-mobile-card" data-marginal-seat="${escapeHtml(x.seat.id)}"><span class="seat-mobile-title"><strong>${escapeHtml(x.seat.name)}</strong><small>${escapeHtml(area)}</small></span><span class="seat-mobile-route"><span class="party-pill"><i style="background:${PARTY[prev]?.color||PARTY.other.color}"></i>${PARTY[prev]?.short||'Altro'} <small>2024</small></span><b>→</b><span class="party-pill ${x.changed?'changed':''}"><i style="background:${PARTY[x.projected]?.color||PARTY.other.color}"></i>${PARTY[x.projected]?.short||'Altro'} <small>scenario</small></span></span><span class="seat-mobile-stats"><span>Margine <strong>${fmt1(x.cm.margin)} p.p.</strong></span><span>Prob. favorito <strong>${x.bestProb==null?'—':pctFmt(x.bestProb*100)}</strong></span></span></button>`;}).join(''):'<div class="empty-small mobile-empty">Nessun collegio corrisponde ai filtri selezionati.</div>';
  document.querySelector('.explorer-card')?.querySelectorAll('[data-marginal-seat]').forEach(el=>el.addEventListener('click',()=>{selectSeat(el.dataset.marginalSeat);document.querySelector('#territorio')?.scrollIntoView({behavior:'smooth',block:'start'});setTimeout(()=>fitSelectedSeat(),420);}));
  renderPagination($('#seatPagination'),pages,state.explorerPage,p=>{state.explorerPage=p;renderMarginals();document.querySelector('.explorer-table')?.scrollIntoView({behavior:'smooth',block:'center'});});
  const note=$('#seatExplorerNote');if(note)note.textContent=state.mc?.seatProb?`${f.source==='custom'?'Scenario utente · ':''}Probabilità del favorito = Monte Carlo corrente. Clic su una riga → dettaglio mappa.`:'Il Monte Carlo è ancora in corso: i filtri probabilistici saranno disponibili al termine.';
  const footer=$('#seatExplorerFooter');if(footer)footer.textContent=filtered.length?`Pagina ${state.explorerPage} di ${pages} · collegi ${fmt0(start+1)}–${fmt0(start+visible.length)} su ${fmt0(filtered.length)} filtrati.`:'Nessun collegio filtrato.';
  syncViewContextBar();
}


function regionalSource(){const el=$('#regionalSource');return el?.value==='custom'&&state.customScenario?'custom':'live';}
function regionalWinner(seat,source=regionalSource()){
  if(source==='custom'&&state.customScenario?.assignment?.[seat.id])return state.customScenario.assignment[seat.id];
  return liveScenarioWinner(seat);
}
function regionLabelForSeat(seat){
  const c=(seat.country||'').trim();
  if(/scotland/i.test(c))return 'Scotland';
  if(/wales/i.test(c))return 'Wales';
  if(/northern ireland/i.test(c))return 'Northern Ireland';
  return (seat.region||'England').trim()||'England';
}
const REGION_LABEL_IT={
  'England':'Inghilterra','Scotland':'Scozia','Wales':'Galles','Northern Ireland':'Irlanda del Nord',
  'North East':'Nord-Est','North West':'Nord-Ovest','Yorkshire and The Humber':'Yorkshire e Humber',
  'East Midlands':'Midlands orientali','West Midlands':'Midlands occidentali','East of England':'Est dell’Inghilterra',
  'London':'Londra','South East':'Sud-Est','South West':'Sud-Ovest'
};
function regionalDisplayName(name){return REGION_LABEL_IT[name]||name;}
function regionalPartySet(){return ['lab','con','ref','ld','green','snp','pc','sf','dup','alliance','other'];}
function bestLiveProbability(seat){
  const prob=state.mc?.seatProb?.[seat.id];if(!prob)return null;
  const best=Object.entries(prob).filter(([p])=>PARTY[p]).sort((a,b)=>b[1]-a[1])[0];return best?best[1]:null;
}
function buildRegionalSnapshot(source=regionalSource()){
  if(!state.central?.seats?.length)return {areas:[],countries:[],net:[],flows:[]};
  const groups=new Map(),countries=new Map(),prevTotals={},curTotals={},flowMap=new Map();
  const add=(map,key,seat,winner,prev)=>{if(!map.has(key))map.set(key,{name:key,total:0,current:{},previous:{},changes:0,uncertain:0});const g=map.get(key);g.total++;g.current[winner]=(g.current[winner]||0)+1;g.previous[prev]=(g.previous[prev]||0)+1;if(winner!==prev)g.changes++;const pr=bestLiveProbability(seat);if(pr!=null&&pr<.65)g.uncertain++;};
  for(const seat of state.central.seats){
    const winner=regionalWinner(seat,source),prev=seat.winner2024||'other',area=regionLabelForSeat(seat),country=(seat.country||'').trim()||'United Kingdom';
    add(groups,area,seat,winner,prev);add(countries,country,seat,winner,prev);prevTotals[prev]=(prevTotals[prev]||0)+1;curTotals[winner]=(curTotals[winner]||0)+1;
    if(winner!==prev){const k=`${prev}>${winner}`;flowMap.set(k,(flowMap.get(k)||0)+1);}
  }
  const areaOrder=['North East','North West','Yorkshire and The Humber','East Midlands','West Midlands','East of England','London','South East','South West','Scotland','Wales','Northern Ireland'];
  const decorate=g=>{const rank=Object.entries(g.current).sort((a,b)=>b[1]-a[1]);return {...g,leader:rank[0]?.[0]||'other',leaderSeats:rank[0]?.[1]||0};};
  const areas=[...groups.values()].map(decorate).sort((a,b)=>{const ai=areaOrder.indexOf(a.name),bi=areaOrder.indexOf(b.name);if(ai>=0||bi>=0)return (ai<0?999:ai)-(bi<0?999:bi);return a.name.localeCompare(b.name,'en-GB');});
  const countryOrder=['England','Scotland','Wales','Northern Ireland'];
  const countryRows=[...countries.values()].map(decorate).sort((a,b)=>(countryOrder.indexOf(a.name)<0?999:countryOrder.indexOf(a.name))-(countryOrder.indexOf(b.name)<0?999:countryOrder.indexOf(b.name)));
  const parties=[...new Set([...Object.keys(prevTotals),...Object.keys(curTotals)])].filter(p=>PARTY[p]);
  const net=parties.map(p=>({p,previous:prevTotals[p]||0,current:curTotals[p]||0,delta:(curTotals[p]||0)-(prevTotals[p]||0)})).filter(x=>x.previous||x.current).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)||b.current-a.current);
  const flows=[...flowMap.entries()].map(([k,count])=>{const [from,to]=k.split('>');return {from,to,count};}).sort((a,b)=>b.count-a.count||a.from.localeCompare(b.from));
  return {areas,countries:countryRows,net,flows};
}
function setExplorerArea(area){
  resetSeatFilters();const c=$('#seatCountry'),r=$('#seatRegion');
  if(area==='Scotland'||area==='Wales'||area==='Northern Ireland'){if(c)c.value=area;}else{if(c)c.value='England';if(r)r.value=area;}
  state.explorerPage=1;renderMarginals();document.querySelector('#collegi')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function setExplorerFlow(from,to){
  resetSeatFilters();const a=$('#seatWinner2024'),b=$('#seatWinner');if(a)a.value=from;if(b)b.value=to;const s=$('#seatStatus');if(s)s.value='changed';state.explorerPage=1;renderMarginals();document.querySelector('#collegi')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function renderRegionalDashboard(){
  const table=$('#regionalTableBody'),summary=$('#countrySummary'),netEl=$('#partyNetGrid'),flowEl=$('#seatFlowList');if(!table||!summary||!netEl||!flowEl||!state.central?.seats?.length)return;
  const source=regionalSource(),snap=buildRegionalSnapshot(source),mainCols=['lab','con','ref','ld','snp','pc'];
  const customOpt=$('#regionalSource option[value="custom"]');if(customOpt)customOpt.disabled=!state.customScenario;
  summary.innerHTML=snap.countries.map(g=>`<button class="country-card" type="button" data-region-shortcut="${escapeHtml(g.name)}"><span class="country-name">${escapeHtml(regionalDisplayName(g.name))}</span><strong><i style="background:${PARTY[g.leader]?.color||PARTY.other.color}"></i>${PARTY[g.leader]?.short||g.leader}</strong><small>${fmt0(g.leaderSeats)} / ${fmt0(g.total)} seggi · ${fmt0(g.changes)} cambi${state.mc?.seatProb?` · ${fmt0(g.uncertain)} incerti`:''}</small></button>`).join('');
  table.innerHTML=snap.areas.map(g=>`<tr data-region-shortcut="${escapeHtml(g.name)}"><td><strong>${escapeHtml(regionalDisplayName(g.name))}</strong></td><td>${fmt0(g.total)}</td><td><span class="party-pill"><i style="background:${PARTY[g.leader]?.color||PARTY.other.color}"></i>${PARTY[g.leader]?.short||g.leader} ${fmt0(g.leaderSeats)}</span></td>${mainCols.map(p=>`<td>${fmt0(g.current[p]||0)}</td>`).join('')}<td>${fmt0(g.changes)}</td><td>${state.mc?.seatProb?fmt0(g.uncertain):'—'}</td></tr>`).join('');
  const regionalMobile=$('#regionalMobileList');if(regionalMobile)regionalMobile.innerHTML=snap.areas.map(g=>`<button type="button" class="regional-mobile-card" data-region-shortcut="${escapeHtml(g.name)}"><span class="regional-mobile-head"><strong>${escapeHtml(regionalDisplayName(g.name))}</strong><b><i style="background:${PARTY[g.leader]?.color||PARTY.other.color}"></i>${PARTY[g.leader]?.short||g.leader} ${fmt0(g.leaderSeats)}</b></span><span class="regional-mobile-meta"><span>${fmt0(g.total)} seggi</span><span>${fmt0(g.changes)} cambi</span><span>${state.mc?.seatProb?`${fmt0(g.uncertain)} incerti`:'incertezza in calcolo'}</span></span><span class="regional-mobile-parties">${mainCols.filter(p=>(g.current[p]||0)>0).map(p=>`<span style="--party:${PARTY[p]?.color||PARTY.other.color}"><i></i>${PARTY[p]?.short||p} <strong>${fmt0(g.current[p]||0)}</strong></span>`).join('')}</span></button>`).join('');
  netEl.innerHTML=snap.net.slice(0,10).map(x=>`<div class="party-net-row"><span><i style="background:${PARTY[x.p]?.color||PARTY.other.color}"></i>${PARTY[x.p]?.short||x.p}</span><b>${fmt0(x.current)}</b><strong class="${x.delta>0?'net-up':x.delta<0?'net-down':'net-flat'}">${x.delta>0?'+':''}${fmt0(x.delta)}</strong><small>da ${fmt0(x.previous)}</small></div>`).join('');
  flowEl.innerHTML=snap.flows.length?snap.flows.slice(0,12).map(x=>`<button type="button" class="seat-flow-row" data-flow-from="${escapeHtml(x.from)}" data-flow-to="${escapeHtml(x.to)}"><span><i style="background:${PARTY[x.from]?.color||PARTY.other.color}"></i>${PARTY[x.from]?.short||x.from}<b>→</b><i style="background:${PARTY[x.to]?.color||PARTY.other.color}"></i>${PARTY[x.to]?.short||x.to}</span><strong>${fmt0(x.count)}</strong></button>`).join(''):'<div class="empty-small">Nessun cambio di vincitore nello scenario selezionato.</div>';
  const meta=$('#regionalMeta');if(meta)meta.textContent=source==='custom'?'Scenario utente deterministico; le colonne “incerti” restano riferite al Monte Carlo corrente.':state.representative?'Scenario territoriale rappresentativo coerente con le mediane Monte Carlo.':'Proiezione centrale provvisoria; passerà allo scenario rappresentativo al termine delle simulazioni.';
  summary.querySelectorAll('[data-region-shortcut]').forEach(el=>el.addEventListener('click',()=>setExplorerArea(el.dataset.regionShortcut)));
  table.querySelectorAll('[data-region-shortcut]').forEach(el=>el.addEventListener('click',()=>setExplorerArea(el.dataset.regionShortcut)));
  regionalMobile?.querySelectorAll('[data-region-shortcut]').forEach(el=>el.addEventListener('click',()=>setExplorerArea(el.dataset.regionShortcut)));
  flowEl.querySelectorAll('[data-flow-from]').forEach(el=>el.addEventListener('click',()=>setExplorerFlow(el.dataset.flowFrom,el.dataset.flowTo)));
  syncViewContextBar();
}
function csvEscape(v){const s=String(v??'');return /[",\r\n]/.test(s)?`"${s.replaceAll('"','""')}"`:s;}
function explorerItemsForExport(filtered=true){
  const source=explorerSource(),all=state.central?.seats?.map(seat=>seatExplorerItem(seat,source))||[];if(!filtered)return all;const f=explorerFilterValues();return sortExplorerItems(all.filter(x=>itemPassesExplorer(x,f)),f);
}
// v0.9.34.1 — complete 650-seat CSV export, including Northern Ireland party columns.
function seatCsvRows(filtered=true){
  const source=explorerSource(),items=explorerItemsForExport(filtered),shareParties=[...scenarioModelParties(),...NI_ORDER];
  const marginHeader=source==='custom'?'margine_scenario_utente_pp':'margine_centrale_pp';
  const header=['ons_id','collegio','paese','regione','vincitore_2024','vincitore_scenario','cambio',marginHeader,'favorito_mc','prob_favorito_mc',...shareParties.map(p=>`quota_${p}`),...shareParties.map(p=>`prob_${p}`)];
  const rows=[header];
  for(const x of items){
    const seat=x.seat,shares=scenarioSharesForSeat(seat,source),prob=state.mc?.seatProb?.[seat.id]||{},best=Object.entries(prob).filter(([p])=>PARTY[p]).sort((a,b)=>b[1]-a[1])[0];
    const isNI=!!seat.isNorthernIreland||/northern ireland/i.test(`${seat.country||''} ${seat.modelZone||''}`);
    const shareCell=p=>{
      const niParty=NI_ORDER.includes(p);
      if(isNI!==niParty)return '';
      return Number(shares[p]||0).toFixed(4);
    };
    const probCell=p=>{
      const niParty=NI_ORDER.includes(p);
      if(isNI!==niParty||prob[p]==null)return '';
      return Number(prob[p]).toFixed(6);
    };
    rows.push([seat.id,seat.name,seat.country,seat.region,seat.winner2024||(isNI?'ni_other':'other'),x.projected,x.changed?'1':'0',Number(x.cm.margin).toFixed(3),best?.[0]||'',best?Number(best[1]).toFixed(6):'',...shareParties.map(shareCell),...shareParties.map(probCell)]);
  }
  return rows;
}
function downloadSeatCsv(filtered=true){
  if(!state.central?.seats?.length)return;const rows=seatCsvRows(filtered),csv='\ufeff'+rows.map(r=>r.map(csvEscape).join(',')).join('\r\n');downloadBlob(new Blob([csv],{type:'text/csv;charset=utf-8'}),`uk_collegi_${filtered?'filtrati':'650'}_${exportDateStamp()}.csv`);
}

function renderOutcomeDashboard(){
  const headline=$('#outcomeHeadline'),sub=$('#outcomeSub'),grid=$('#largestPartyGrid');if(!headline||!sub||!grid)return;
  const totals=state.mc?.medians||state.central?.totals||{},rankedSeats=Object.entries(totals).filter(([p])=>PARTY[p]).sort((a,b)=>b[1]-a[1]);
  if(!state.mc){
    const [p,n]=rankedSeats[0]||['other',0];headline.textContent=`${PARTY[p]?.name||p} è il primo partito nello scenario centrale`;sub.textContent=n>=CONFIG.majority?`Lo scenario centrale supera quota ${CONFIG.majority}. Il Monte Carlo sta misurando quanto è robusta questa maggioranza.`:`Nessun partito raggiunge ${CONFIG.majority} seggi nello scenario centrale. Il Monte Carlo sta misurando il rischio di Parlamento senza maggioranza.`;
    grid.innerHTML=rankedSeats.slice(0,3).map(([k,seats])=>`<div class="outcome-party"><span><i style="background:${PARTY[k].color}"></i>${PARTY[k].name}</span><strong>${fmt0(seats)}</strong><small>seggi centrali</small></div>`).join('');return;
  }
  const m=state.mc,maj=[['lab',m.labMaj],['con',m.conMaj],['ref',m.refMaj]].sort((a,b)=>b[1]-a[1]),largest=Object.entries(m.largest||{}).sort((a,b)=>b[1]-a[1]);
  if(m.hung>=Math.max(...maj.map(x=>x[1])))headline.textContent='Parlamento senza maggioranza è l’esito complessivo più probabile';else headline.textContent=`${PARTY[maj[0][0]].name}: maggioranza assoluta è l’esito singolo più probabile`;
  sub.textContent=`Parlamento senza maggioranza ${pctFmt(m.hung*100)} · soglia assoluta ${CONFIG.majority} · soglia operativa mediana ~${fmt0(m.workingThreshold||326)}.`;
  grid.innerHTML=largest.slice(0,3).map(([k,pr])=>`<div class="outcome-party"><span><i style="background:${PARTY[k]?.color||PARTY.other.color}"></i>${PARTY[k]?.name||k}</span><strong>${pctFmt(pr*100)}</strong><small>probabilità di essere primo partito · mediana ${fmt0(m.medians?.[k]||0)}</small></div>`).join('');
}
function coalitionProbability(parties){
  if(!state.mc?.dist||!parties?.length)return null;let yes=0;
  for(let i=0;i<state.mc.sims;i++){let s=0;for(const p of parties)s+=state.mc.dist[p]?.[i]||0;const sf=state.mc.dist.sf?.[i]||0,t=Math.floor((650-sf)/2)+1;if(s>=t)yes++;}
  return yes/state.mc.sims;
}
function renderMinimalCoalitions(){
  const el=$('#coalitionOptions');if(!el)return;const totals=state.mc?.medians||state.central?.totals||{},threshold=state.mc?.workingThreshold||state.central?.ni?.workingThreshold||CONFIG.majority;
  const ps=['lab','con','ref','ld','green','snp','pc'].filter(p=>(totals[p]||0)>0),opts=[];
  const maxMask=1<<ps.length;
  for(let mask=1;mask<maxMask;mask++){
    const combo=ps.filter((_,i)=>mask&(1<<i));if(combo.length<2||combo.length>4)continue;const seats=combo.reduce((s,p)=>s+(totals[p]||0),0);if(seats<threshold)continue;
    const minimal=combo.every(p=>seats-(totals[p]||0)<threshold);if(!minimal)continue;opts.push({combo,seats,surplus:seats-threshold});
  }
  opts.sort((a,b)=>a.combo.length-b.combo.length||a.surplus-b.surplus).splice(8);
  if(!opts.length){el.innerHTML='<div class="empty-small">Nessuna combinazione minima vincente trovata con i partiti principali.</div>';return;}
  el.innerHTML=opts.map(o=>{const pr=coalitionProbability(o.combo);return `<button class="coalition-option" data-coalition="${o.combo.join(',')}"><span>${o.combo.map(p=>`<i title="${PARTY[p].name}" style="background:${PARTY[p].color}"></i>`).join('')}</span><strong>${o.combo.map(p=>PARTY[p].short).join(' + ')}</strong><small>${fmt0(o.seats)} seggi · +${fmt0(o.surplus)}${pr==null?'':` · P≥soglia ${pctFmt(pr*100)}`}</small></button>`;}).join('');
  el.querySelectorAll('button[data-coalition]').forEach(b=>b.addEventListener('click',()=>{
    state.coalition=new Set(b.dataset.coalition.split(',').filter(Boolean));
    $$('#coalitionButtons button').forEach(btn=>btn.classList.toggle('selected',state.coalition.has(btn.dataset.party)));updateCoalition();
  }));
}

function renderCoalitionButtons(){
  const ps=['lab','con','ref','ld','green','snp','pc','rb','dup','alliance','sdlp','uup','tuv'];$('#coalitionButtons').innerHTML=ps.map(p=>`<button data-party="${p}"><i class="party-dot" style="background:${PARTY[p].color}"></i>${PARTY[p].short}</button>`).join('');
  $$('#coalitionButtons button').forEach(b=>b.addEventListener('click',()=>{const p=b.dataset.party;state.coalition.has(p)?state.coalition.delete(p):state.coalition.add(p);b.classList.toggle('selected',state.coalition.has(p));updateCoalition();}));
}
function updateCoalition(){
  const totals=state.mc?.medians||state.central?.totals||{};const seats=[...state.coalition].reduce((s,p)=>s+(totals[p]||0),0);const threshold=state.mc?.workingThreshold||state.central?.ni?.workingThreshold||CONFIG.majority;$('#coalSeats').textContent=fmt0(seats);$('#coalDistance').textContent=seats>=threshold?`+${fmt0(seats-threshold)}`:`−${fmt0(threshold-seats)}`;
  if(!state.mc?.dist||!state.coalition.size){$('#coalProb').textContent='—';return;}let yes=0;for(let i=0;i<state.mc.sims;i++){let s=0;for(const p of state.coalition)s+=state.mc.dist[p]?.[i]||0;const sf=state.mc.dist.sf?.[i]||0;const t=Math.floor((650-sf)/2)+1;if(s>=t)yes++;}$('#coalProb').textContent=pctFmt(yes/state.mc.sims*100);
}


// v0.9.33 — client-side graphic exports and social sharing. Statistical model untouched.
function currentSiteUrl(){const u=new URL(location.href);u.searchParams.delete('seat');u.hash='';return u.toString();}
function selectedSeatUrl(id=state.selectedSeat){const u=new URL(currentSiteUrl());if(id)u.searchParams.set('seat',id);u.hash='territorio';return u.toString();}
function canvasBlob(canvas){return new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('PNG non generato')),'image/png'));}
function downloadBlob(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},250);}
function exportDateStamp(){const d=state.polls?.[0]?.date||new Date().toISOString().slice(0,10);return String(d).slice(0,10);}
function roundRect(ctx,x,y,w,h,r,fill,stroke=null,lw=1){ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=lw;ctx.stroke();}}
function cardText(ctx,s,x,y,font,color='#f3f6fb',align='left'){ctx.font=font;ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='alphabetic';ctx.fillText(String(s),x,y);}
function wrapCardText(ctx,s,x,y,maxW,lineH,font,color='#aeb8c7',maxLines=3){ctx.font=font;ctx.fillStyle=color;ctx.textAlign='left';const words=String(s).split(/\s+/);let line='',lines=[];for(const word of words){const t=line?`${line} ${word}`:word;if(ctx.measureText(t).width>maxW&&line){lines.push(line);line=word;}else line=t;}if(line)lines.push(line);lines.slice(0,maxLines).forEach((ln,i)=>ctx.fillText(ln,x,y+i*lineH));}
function drawUkFlagMark(ctx,x,y,w=42,h=28){ctx.save();roundRect(ctx,x,y,w,h,5,'#17365d');ctx.strokeStyle='#fff';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w,y+h);ctx.moveTo(x+w,y);ctx.lineTo(x,y+h);ctx.stroke();ctx.strokeStyle='#c8102e';ctx.lineWidth=2.2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w,y+h);ctx.moveTo(x+w,y);ctx.lineTo(x,y+h);ctx.stroke();ctx.fillStyle='#fff';ctx.fillRect(x+w*.40,y,w*.20,h);ctx.fillRect(x,y+h*.36,w,h*.28);ctx.fillStyle='#c8102e';ctx.fillRect(x+w*.445,y,w*.11,h);ctx.fillRect(x,y+h*.425,w,h*.15);ctx.restore();}
function projectedTotalsForCard(){return state.mc?.medians||state.central?.totals||null;}
function cardPartyRows(){const totals=projectedTotalsForCard()||{};return SEAT_ORDER.filter(p=>PARTY[p]&&(totals[p]||0)>0).map(p=>({p,seats:totals[p]||0})).sort((a,b)=>b.seats-a.seats).slice(0,8);}
function cardPollRows(){const a=state.average?.values||{};return PARTY_ORDER.filter(p=>PARTY[p]&&Number.isFinite(a[p])).map(p=>({p,v:a[p]})).sort((x,y)=>y.v-x.v).slice(0,5);}
function drawCardHemicycle(ctx,totals,box){const seats=[];for(const p of SEAT_ORDER){for(let i=0;i<Math.round(totals[p]||0);i++)seats.push(p);}while(seats.length<650)seats.push('other');if(seats.length>650)seats.length=650;const minX=Math.min(...hemiPts.map(p=>p.x)),maxX=Math.max(...hemiPts.map(p=>p.x)),minY=Math.min(...hemiPts.map(p=>p.y)),maxY=Math.max(...hemiPts.map(p=>p.y)),sx=box.w/(maxX-minX),sy=box.h/(maxY-minY),s=Math.min(sx,sy),ox=box.x+(box.w-(maxX-minX)*s)/2,oy=box.y+(box.h-(maxY-minY)*s)/2;hemiPts.forEach((pt,i)=>{ctx.fillStyle=PARTY[seats[i]||'other']?.color||PARTY.other.color;ctx.beginPath();ctx.arc(ox+(pt.x-minX)*s,oy+(pt.y-minY)*s,Math.max(2.1,3.2*s),0,Math.PI*2);ctx.fill();});}
async function buildModelCardCanvas(format='landscape'){
  const totals=projectedTotalsForCard();if(!totals)throw new Error('Proiezione non ancora disponibile');const ig=format==='instagram',W=ig?1080:1200,H=ig?1350:630,c=document.createElement('canvas');c.width=W;c.height=H;const ctx=c.getContext('2d');ctx.fillStyle='#0a0f17';ctx.fillRect(0,0,W,H);const grad=ctx.createLinearGradient(0,0,W,H);grad.addColorStop(0,'rgba(28,56,91,.66)');grad.addColorStop(.55,'rgba(14,22,34,.1)');grad.addColorStop(1,'rgba(116,24,46,.22)');ctx.fillStyle=grad;ctx.fillRect(0,0,W,H);
  if(!ig){roundRect(ctx,24,24,W-48,H-48,28,'rgba(17,24,35,.96)','#344255',1.3);drawUkFlagMark(ctx,55,50,46,30);cardText(ctx,'DANIELE ANGRISANI · MODELLO ELETTORALE',116,73,'800 15px system-ui','#8ea0b7');cardText(ctx,'Elezioni nel Regno Unito',55,132,'900 42px system-ui','#f7f9fc');cardText(ctx,state.mc?'Scenario rappresentativo Monte Carlo':'Scenario centrale',55,166,'600 19px system-ui','#98a8bc');roundRect(ctx,55,192,690,337,22,'#0e151f','#2c3a4c',1);drawCardHemicycle(ctx,totals,{x:85,y:216,w:630,h:272});cardText(ctx,'326',400,512,'900 24px system-ui','#f5f7fb','center');cardText(ctx,'maggioranza assoluta',400,533,'600 12px system-ui','#8594a8','center');const rows=cardPartyRows().slice(0,6);rows.forEach((r,i)=>{const y=202+i*49;roundRect(ctx,785,y,354,40,10,'#121b27','#293747',1);ctx.fillStyle=PARTY[r.p].color;ctx.fillRect(785,y,6,40);cardText(ctx,PARTY[r.p].name,806,y+26,'750 16px system-ui','#eef3f9');cardText(ctx,fmt0(r.seats),1120,y+27,'900 19px system-ui',PARTY[r.p].color,'right');});const top=Object.entries(state.mc?.largest||{}).sort((a,b)=>b[1]-a[1])[0];roundRect(ctx,785,504,354,46,11,'#182334','#33445a',1);cardText(ctx,top?`${PARTY[top[0]]?.short||top[0]} primo partito ${pctFmt(top[1]*100)}`:'Nowcast in aggiornamento',806,533,'800 15px system-ui','#dce6f2');const polls=cardPollRows().slice(0,5);let px=55;polls.forEach((r,i)=>{cardText(ctx,PARTY[r.p].short,px,582,'700 13px system-ui',PARTY[r.p].color);cardText(ctx,pctFmt(r.v),px+42,582,'900 15px system-ui','#f0f4fa');px+=132;});cardText(ctx,`Ultimo sondaggio ${formatDate(state.polls?.[0]?.date||exportDateStamp())}`,1138,582,'600 12px system-ui','#7f8ea2','right');}
  else {roundRect(ctx,24,24,W-48,H-48,32,'rgba(17,24,35,.97)','#344255',1.4);drawUkFlagMark(ctx,54,54,52,34);cardText(ctx,'DANIELE ANGRISANI · MODELLO ELETTORALE',122,80,'800 17px system-ui','#8ea0b7');cardText(ctx,'Elezioni nel Regno Unito',W/2,154,'900 43px system-ui','#f7f9fc','center');cardText(ctx,state.mc?'Nowcast probabilistico · 50.000 simulazioni':'Scenario centrale',W/2,194,'600 20px system-ui','#98a8bc','center');roundRect(ctx,54,230,W-108,525,24,'#0e151f','#2c3a4c',1);drawCardHemicycle(ctx,totals,{x:95,y:270,w:890,h:390});cardText(ctx,'326 · maggioranza assoluta',W/2,716,'800 18px system-ui','#9baabd','center');const rows=cardPartyRows().slice(0,6),gap=12,cw=(W-108-gap*2)/3;rows.forEach((r,i)=>{const col=i%3,row=Math.floor(i/3),x=54+col*(cw+gap),y=790+row*150;roundRect(ctx,x,y,cw,132,18,'#121b27','#2d3b4d',1);ctx.fillStyle=PARTY[r.p].color;ctx.beginPath();ctx.arc(x+35,y+35,12,0,Math.PI*2);ctx.fill();cardText(ctx,PARTY[r.p].short,x+58,y+41,'800 18px system-ui',PARTY[r.p].color);cardText(ctx,fmt0(r.seats),x+cw/2,y+101,'900 38px system-ui','#f5f8fc','center');});const polls=cardPollRows().slice(0,5);roundRect(ctx,54,1110,W-108,145,19,'#101824','#2d3b4d',1);cardText(ctx,'Media sondaggi',80,1150,'800 18px system-ui','#9eadc0');const cell=(W-160)/5;polls.forEach((r,i)=>{const x=80+i*cell+cell/2;cardText(ctx,PARTY[r.p].short,x,1193,'750 16px system-ui',PARTY[r.p].color,'center');cardText(ctx,pctFmt(r.v),x,1232,'900 25px system-ui','#f5f8fc','center');});cardText(ctx,`Ultimo sondaggio ${formatDate(state.polls?.[0]?.date||exportDateStamp())}`,W/2,1297,'600 14px system-ui','#8090a4','center');}
  return c;
}
function modelShareText(){const totals=projectedTotalsForCard()||{},lead=Object.entries(totals).filter(([p])=>PARTY[p]).sort((a,b)=>b[1]-a[1])[0]||['other',0],hung=state.mc?.hung;const line1=`Elezioni UK: ${PARTY[lead[0]]?.name||lead[0]} primo partito con ${fmt0(lead[1])} seggi nello scenario ${state.mc?'Monte Carlo':'centrale'}.`;const line2=state.mc?`Parlamento senza maggioranza ${pctFmt(hung*100)} · 50.000 simulazioni · probabilità collegio per collegio.`:'Modello indipendente di Daniele Angrisani: sondaggi, seggi e collegi aggiornati.';return `${line1}\n${line2}`;}
function socialCardVersionToken(){
  const latest=state.polls?.[0]?.date||'nodate',avg=state.average?.values||{},totals=projectedTotalsForCard()||{};
  const values=[...PARTY_ORDER.map(p=>Number(avg[p]||0).toFixed(2)),...SEAT_ORDER.map(p=>String(Math.round(Number(totals[p]||0)))),Number(state.mc?.hung||0).toFixed(5)].join('|');
  return `${String(latest).replaceAll('-','')}-${hashString(values).toString(16)}`;
}
function socialShareTarget(kind){
  const map={x:'share-x.html',threads:'share-threads.html',facebook:'share-facebook.html',linkedin:'share-linkedin.html',telegram:'share-telegram.html',whatsapp:'share-whatsapp.html'};
  if(!map[kind])return currentSiteUrl();const u=new URL(map[kind],location.href);u.searchParams.set('v',socialCardVersionToken());u.searchParams.set('src',kind);return u.href;
}
function socialCardReady(){return !!(state.average?.values&&state.central?.seats?.length===650&&state.mc?.sims===CONFIG.mcSims&&projectedTotalsForCard());}
window.socialCardReady=socialCardReady;
window.socialCardVersionToken=socialCardVersionToken;
window.socialCardDataUrl=async(format='landscape')=>(await buildModelCardCanvas(format)).toDataURL('image/png');
window.ukMonteCarloSummary=()=>state.mc?JSON.parse(JSON.stringify(state.mc)):null;
async function downloadModelCard(format='landscape'){const c=await buildModelCardCanvas(format),b=await canvasBlob(c);downloadBlob(b,`uk_nowcast_${format==='instagram'?'instagram_4x5':'social_16x9'}_${exportDateStamp()}.png`);return b;}
async function shareModelCard(format='landscape',trigger=null){const c=await buildModelCardCanvas(format),b=await canvasBlob(c),file=new File([b],`uk_nowcast_${format==='instagram'?'instagram_4x5':'social_16x9'}_${exportDateStamp()}.png`,{type:'image/png'}),text=modelShareText(),url=currentSiteUrl();if(navigator.share&&navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:'Elezioni nel Regno Unito — Nowcast',text:`${text}\n\n${url}`});return true;}downloadBlob(b,file.name);try{await navigator.clipboard?.writeText(`${text}\n\n${url}`);}catch(_){}if(trigger)flashButton(trigger,'PNG + testo copiato');return false;}
function flashButton(btn,label='Fatto ✓'){if(!btn)return;const oldHtml=btn.innerHTML,oldTitle=btn.title,oldAria=btn.getAttribute('aria-label');if(btn.classList.contains('share-btn')){btn.classList.add('copied');btn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';btn.title='Copiato';btn.setAttribute('aria-label','Copiato');}else{btn.textContent=label;}setTimeout(()=>{btn.innerHTML=oldHtml;btn.classList.remove('copied');btn.title=oldTitle;if(oldAria)btn.setAttribute('aria-label',oldAria);else btn.removeAttribute('aria-label');},1600);}
function shareUrl(kind,url,text){const u=encodeURIComponent(url),t=encodeURIComponent(text);if(kind==='x')return `https://x.com/intent/post?text=${encodeURIComponent(text+' '+url)}`;if(kind==='threads')return `https://www.threads.net/intent/post?text=${encodeURIComponent(text+'\n\n'+url)}`;if(kind==='facebook')return `https://www.facebook.com/sharer/sharer.php?u=${u}`;if(kind==='linkedin')return `https://www.linkedin.com/sharing/share-offsite/?url=${u}`;if(kind==='telegram')return `https://t.me/share/url?url=${u}&text=${t}`;if(kind==='whatsapp')return `https://api.whatsapp.com/send?text=${encodeURIComponent(text+'\n\n'+url)}`;return null;}
async function openModelShare(kind,btn){const url=currentSiteUrl(),text=modelShareText();if(kind==='copy'){const copy=`${text}\n\n${url}`;if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(copy).catch(()=>fallbackCopy(copy));else fallbackCopy(copy);flashButton(btn,'Copiato ✓');return;}if(kind==='instagram'){await shareModelCard('instagram',btn);return;}if(kind==='native'){if(navigator.share){await navigator.share({title:'Elezioni nel Regno Unito — Nowcast',text,url});return;}const copy=`${text}\n\n${url}`;fallbackCopy(copy,()=>flashButton(btn,'Copiato ✓'));return;}const sharePage=socialShareTarget(kind),target=shareUrl(kind,sharePage,text);if(target)window.open(target,'_blank','noopener,noreferrer');}
function seatExportData(id=state.selectedSeat){const seat=state.byId.get(id);if(!seat)return null;const live=seat.projected||{},cm=seatMarginFromShares(seat,live),prob=state.mc?.seatProb?.[id]||null,bestProb=prob?Object.entries(prob).sort((a,b)=>b[1]-a[1])[0]:null,rep=state.representative?.assignment?.[id]||seat.centralWinner||seat.winner2024;return {seat,live,cm,prob,bestProb,rep};}
async function buildSeatCardCanvas(id=state.selectedSeat){const d=seatExportData(id);if(!d)throw new Error('Seleziona prima un collegio');const {seat,live,cm,prob,bestProb,rep}=d,W=1200,H=630,c=document.createElement('canvas');c.width=W;c.height=H;const ctx=c.getContext('2d');ctx.fillStyle='#0a0f17';ctx.fillRect(0,0,W,H);const grad=ctx.createLinearGradient(0,0,W,H);grad.addColorStop(0,'rgba(24,55,90,.72)');grad.addColorStop(1,'rgba(91,22,44,.25)');ctx.fillStyle=grad;ctx.fillRect(0,0,W,H);roundRect(ctx,24,24,W-48,H-48,28,'rgba(17,24,35,.97)','#344255',1.3);drawUkFlagMark(ctx,54,50,46,30);cardText(ctx,'DANIELE ANGRISANI · NOWCAST DEL COLLEGIO',114,73,'800 15px system-ui','#8ea0b7');cardText(ctx,seat.name,54,132,seat.name.length>34?'900 34px system-ui':'900 42px system-ui','#f7f9fc');cardText(ctx,[seat.region,seat.country,seat.id].filter(Boolean).map((v,i)=>i<2?regionalDisplayName(v):v).join(' · '),54,163,'600 16px system-ui','#91a1b5');const changed=rep!==(seat.winner2024||'other');roundRect(ctx,54,194,520,102,18,'#101925','#2e3c4e',1);cardText(ctx,'Scenario rappresentativo',78,226,'700 14px system-ui','#8e9db0');ctx.fillStyle=PARTY[rep]?.color||PARTY.other.color;ctx.beginPath();ctx.arc(84,262,12,0,Math.PI*2);ctx.fill();cardText(ctx,PARTY[rep]?.name||rep,108,270,'900 28px system-ui','#f5f8fc');cardText(ctx,`${changed?'Cambio':'Conferma'} vs 2024 · margine centrale ${fmt1(cm.margin)} p.p.`,78,322,'650 15px system-ui',changed?'#ffb6c5':'#9dd9b2');const prev=seat.winner2024||'other';roundRect(ctx,54,350,520,102,18,'#101925','#2e3c4e',1);cardText(ctx,'Risultato 2024',78,382,'700 14px system-ui','#8e9db0');cardText(ctx,PARTY[prev]?.name||seat.winner2024_name||prev,78,421,'850 24px system-ui',PARTY[prev]?.color||'#d7dce5');cardText(ctx,seat.winner2024_candidate||'',78,445,'600 13px system-ui','#8e9db0');const shareRows=Object.entries(live).filter(([p,v])=>PARTY[p]&&v>.2).sort((a,b)=>b[1]-a[1]).slice(0,5);shareRows.forEach(([p,v],i)=>{const y=198+i*56,x=625;cardText(ctx,PARTY[p].short,x,y+20,'800 15px system-ui',PARTY[p].color);roundRect(ctx,x+62,y+7,360,14,7,'#263243');roundRect(ctx,x+62,y+7,Math.max(5,360*clamp(v/50,0,1)),14,7,PARTY[p].color);cardText(ctx,pctFmt(v),1074,y+21,'900 16px system-ui','#f0f4fa','right');});roundRect(ctx,625,493,449,58,14,'#121d2b','#35475d',1);const probText=bestProb?`${PARTY[bestProb[0]]?.short||bestProb[0]} ${pctFmt(bestProb[1]*100)} di vittoria · ${probabilityLabel(bestProb[1])}`:'Monte Carlo in corso';cardText(ctx,probText,649,529,'800 17px system-ui','#dce6f3');cardText(ctx,`Ultimo sondaggio ${formatDate(state.polls?.[0]?.date||exportDateStamp())}`,54,578,'600 12px system-ui','#8090a4');cardText(ctx,'angrisanidj.github.io/modello-uk/',1145,578,'600 12px system-ui','#8090a4','right');return c;}
function seatShareText(id=state.selectedSeat){const d=seatExportData(id);if(!d)return'';const p=d.bestProb,prob=p?` · P vittoria ${PARTY[p[0]]?.short||p[0]} ${pctFmt(p[1]*100)}`:'';return `${d.seat.name}: ${PARTY[d.rep]?.name||d.rep} nello scenario rappresentativo, margine centrale ${fmt1(d.cm.margin)} p.p.${prob}.\nNowcast UK · Daniele Angrisani.`;}
async function downloadSeatCard(){if(!state.selectedSeat)return;const c=await buildSeatCardCanvas(),b=await canvasBlob(c);downloadBlob(b,`uk_collegio_${state.selectedSeat}_${exportDateStamp()}.png`);}
async function shareSeatCard(btn=null){if(!state.selectedSeat)return;const c=await buildSeatCardCanvas(),b=await canvasBlob(c),file=new File([b],`uk_collegio_${state.selectedSeat}_${exportDateStamp()}.png`,{type:'image/png'}),text=seatShareText(),url=selectedSeatUrl();if(navigator.share&&navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:`${state.byId.get(state.selectedSeat)?.name||'Collegio'} — Nowcast UK`,text:`${text}\n\n${url}`});return;}downloadBlob(b,file.name);const copy=`${text}\n\n${url}`;if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(copy).catch(()=>fallbackCopy(copy));else fallbackCopy(copy);flashButton(btn,'PNG + testo copiato');}


// v0.9.39 — professional editorial masthead metadata. UI only.
function formatModelTimestamp(raw){
  if(!raw)return '—';
  const d=new Date(raw);if(Number.isNaN(d.getTime()))return String(raw);
  return d.toLocaleString('it-IT',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
}
function updateEditorialMeta(){
  const latest=$('#metaLatestPoll');if(latest)latest.textContent=state.polls?.[0]?.date?formatDate(state.polls[0].date):'—';
  const updated=$('#metaModelUpdated');if(updated){const raw=state.mrpLite?.generated_at||state.ni?.meta?.generated_at||state.territorialBaseline?.generated_at;updated.textContent=raw?formatModelTimestamp(raw):'dati correnti';}
}

// v0.9.38 — Germany-parity editorial utilities. Frontend only: no statistical inputs or simulations change.
let mobileNowcastLastScrollY=window.scrollY,mobileNowcastHideTimer=null;
function updateMobileNowcastSticky(){
  const root=$('#mobileNowcastSticky');if(!root)return;
  const totals=state.mc?.medians||state.central?.totals||{};
  const leaders=Object.entries(totals).filter(([p,n])=>PARTY[p]&&p!=='other'&&p!=='ni_other'&&Number(n)>0).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,2);
  [[1,leaders[0]],[2,leaders[1]]].forEach(([slot,row])=>{
    const p=row?.[0],n=row?.[1],dot=$(`#mobileParty${slot}Dot`),name=$(`#mobileParty${slot}Name`),seats=$(`#mobileParty${slot}Seats`),wrap=dot?.closest('.mobile-nowcast-party');
    const partyColor=p&&PARTY[p]?PARTY[p].color:'#657286';
    if(dot)dot.style.background=partyColor;
    if(wrap)wrap.style.setProperty('--sticky-party',partyColor);
    if(name)name.textContent=p&&PARTY[p]?PARTY[p].short:'—';
    if(seats)seats.textContent=Number.isFinite(Number(n))?fmt0(Number(n)):'—';
  });
  updateEditorialMeta();
  syncMobileNowcastVisibility();
  updateDesktopNowcastSticky();
}
function syncMobileNowcastVisibility(){
  const root=$('#mobileNowcastSticky'),hero=document.querySelector('.hero');if(!root||!hero)return;
  if(document.body.classList.contains('has-active-view')){root.classList.remove('is-visible');return;}
  const y=Math.max(0,window.scrollY||0),threshold=hero.offsetTop+Math.max(96,hero.offsetHeight*.72),mobile=window.matchMedia?.('(max-width:760px)')?.matches!==false;
  if(!mobile||y<=threshold){root.classList.remove('is-visible');if(mobileNowcastHideTimer){clearTimeout(mobileNowcastHideTimer);mobileNowcastHideTimer=null;}mobileNowcastLastScrollY=y;return;}
  const delta=y-mobileNowcastLastScrollY;
  if(delta<=-6){root.classList.add('is-visible');if(mobileNowcastHideTimer)clearTimeout(mobileNowcastHideTimer);mobileNowcastHideTimer=setTimeout(()=>{root.classList.remove('is-visible');mobileNowcastHideTimer=null;},1500);}
  else if(delta>=6){root.classList.remove('is-visible');if(mobileNowcastHideTimer){clearTimeout(mobileNowcastHideTimer);mobileNowcastHideTimer=null;}}
  mobileNowcastLastScrollY=y;
}
function updateDesktopNowcastSticky(){
  const root=$('#desktopNowcastSticky');if(!root)return;const totals=state.mc?.medians||state.central?.totals||{},leaders=Object.entries(totals).filter(([p,n])=>PARTY[p]&&p!=='other'&&p!=='ni_other'&&Number(n)>0).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,2);
  [[1,leaders[0]],[2,leaders[1]]].forEach(([slot,row])=>{const p=row?.[0],n=row?.[1],dot=$(`#desktopParty${slot}Dot`),name=$(`#desktopParty${slot}Name`),seats=$(`#desktopParty${slot}Seats`);if(dot)dot.style.background=p&&PARTY[p]?PARTY[p].color:'#657286';if(name)name.textContent=p&&PARTY[p]?PARTY[p].short:'—';if(seats)seats.textContent=Number.isFinite(Number(n))?fmt0(Number(n)):'—';});
  syncDesktopNowcastVisibility();
}
function syncDesktopNowcastVisibility(){
  const root=$('#desktopNowcastSticky'),hero=document.querySelector('.hero');if(!root||!hero)return;const desktop=window.matchMedia?.('(min-width:761px)')?.matches!==false,threshold=hero.offsetTop+hero.offsetHeight+10,visible=desktop&&(window.scrollY||0)>threshold;root.classList.toggle('is-visible',visible);$('#viewStateBar')?.classList.toggle('below-desktop-sticky',visible&&document.body.classList.contains('has-active-view'));
}
function initDesktopNowcastSticky(){
  $$('[data-desktop-jump]').forEach(btn=>btn.addEventListener('click',()=>{const dest=btn.dataset.desktopJump;if(dest==='top'){window.scrollTo({top:0,behavior:'smooth'});return;}document.getElementById(dest)?.scrollIntoView({behavior:'smooth',block:'start'});}));updateDesktopNowcastSticky();
}
function graphicDimensions(ratio){return ratio==='5:2'?{w:1500,h:600}:{w:1600,h:900};}
function graphicFilename(kind,ratio='16:9'){const names={projection:'proiezione_seggi',map:'mappa_collegi',trend:'andamento_sondaggi'};return `uk_${names[kind]||kind}_${ratio.replace(':','x')}_${exportDateStamp()}.png`;}
function inlineSvgClone(svg){
  const clone=svg.cloneNode(true);clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
  const src=[svg,...svg.querySelectorAll('*')],dst=[clone,...clone.querySelectorAll('*')];
  const props=['fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','opacity','font-size','font-family','font-weight','text-anchor','dominant-baseline','display','visibility'];
  src.forEach((node,i)=>{const copy=dst[i];if(!copy)return;let cs;try{cs=getComputedStyle(node);}catch(_){cs=null;}if(!cs)return;for(const p of props){const v=cs.getPropertyValue(p);if(v)copy.style.setProperty(p,v);}});
  return clone;
}
function svgImageForExport(svg,{cleanTrend=false}={}){
  if(!svg)throw new Error('Grafica non disponibile');
  const clone=inlineSvgClone(svg);
  if(cleanTrend){
    clone.querySelectorAll('.poll-trend-crosshair').forEach(el=>el.remove());
    clone.querySelectorAll('[data-export-transient]').forEach(el=>el.remove());
  }
  const xml=new XMLSerializer().serializeToString(clone),blob=new Blob([xml],{type:'image/svg+xml;charset=utf-8'}),url=URL.createObjectURL(blob);
  return new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>{URL.revokeObjectURL(url);resolve(img)};img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('Impossibile preparare la grafica SVG'))};img.src=url;});
}
function drawContainedImage(ctx,img,x,y,w,h){
  const iw=img.naturalWidth||img.width||1,ih=img.naturalHeight||img.height||1,s=Math.min(w/iw,h/ih),dw=iw*s,dh=ih*s;
  ctx.drawImage(img,x+(w-dw)/2,y+(h-dh)/2,dw,dh);
}
function moduleGraphicSubtitle(kind){
  if(kind==='projection')return state.mc?'Mediane e intervallo centrale 80% · 50.000 simulazioni':'Scenario centrale · Monte Carlo in preparazione';
  if(kind==='map'){const lab={central:'Proiezione centrale',representative:'Scenario rappresentativo',margin:'Margine centrale',prob:'Probabilità di vittoria',custom:'Scenario utente'},layout=state.mapLayout==='hex'?'cartogramma a esagoni':'mappa geografica';return `${lab[state.mapMode]||'Mappa dei collegi'} · ${layout} · 650 collegi`;}
  if(kind==='trend'){const r=state.pollTrendRange==='all'?'tutto l’archivio':`${state.pollTrendRange||180} giorni`;return `Media storica del modello · ${r} · emivita 7 giorni`;}
  return 'Nowcast UK';
}
function trendExportRecap(){
  const parties=['lab','ref','con','green','ld'],values=state.average?.values||{},valid=parties.filter(p=>Number.isFinite(values[p]));
  const leader=valid.slice().sort((a,b)=>values[b]-values[a])[0]||null;
  return {date:state.polls?.[0]?.date||null,leader,rows:valid.map(p=>({p,value:values[p],delta30:historicalDelta(30,p)}))};
}
function drawTrendExportRecap(ctx,x,y,w,h){
  const recap=trendExportRecap();if(!recap.rows.length)return;
  const headerH=22,gap=10,rows=recap.rows,chipY=y+headerH+4,chipH=Math.max(42,h-headerH-4),chipW=(w-gap*(rows.length-1))/rows.length;
  cardText(ctx,`MEDIA CORRENTE${recap.date?` · ${formatDate(recap.date)}`:''}`,x,y+14,'800 12px system-ui','#90a3ba');
  rows.forEach((row,i)=>{
    const px=x+i*(chipW+gap),isLeader=row.p===recap.leader,party=PARTY[row.p];
    roundRect(ctx,px,chipY,chipW,chipH,13,isLeader?'rgba(255,255,255,.075)':'rgba(10,17,26,.72)',isLeader?party.color:'#28394d',isLeader?2:1);
    ctx.fillStyle=party.color;ctx.beginPath();ctx.arc(px+17,chipY+chipH/2,6.5,0,Math.PI*2);ctx.fill();
    cardText(ctx,party.short,px+31,chipY+21,'800 13px system-ui','#dce5f0');
    cardText(ctx,pctFmt(row.value),px+31,chipY+41,'900 19px system-ui','#f6f9fd');
    const delta=Number.isFinite(row.delta30)?`30g ${signedPp(row.delta30)}`:'30g —';
    cardText(ctx,delta,px+chipW-12,chipY+40,'650 10px system-ui','#8fa0b4','right');
    if(isLeader)cardText(ctx,'IN TESTA',px+chipW-12,chipY+18,'900 9px system-ui',party.color,'right');
  });
}
async function buildModuleGraphicCanvas(kind,ratio='16:9'){
  const {w:W,h:H}=graphicDimensions(ratio),c=document.createElement('canvas');c.width=W;c.height=H;const ctx=c.getContext('2d');
  ctx.fillStyle='#080d14';ctx.fillRect(0,0,W,H);const grad=ctx.createLinearGradient(0,0,W,H);grad.addColorStop(0,'rgba(25,58,96,.72)');grad.addColorStop(1,'rgba(98,22,47,.24)');ctx.fillStyle=grad;ctx.fillRect(0,0,W,H);
  const pad=ratio==='5:2'?34:44;roundRect(ctx,pad,pad,W-pad*2,H-pad*2,26,'rgba(16,23,34,.97)','#354357',1.4);drawUkFlagMark(ctx,pad+28,pad+24,48,31);
  const title={projection:'Proiezione della House of Commons',map:'Mappa dei 650 collegi',trend:'Andamento dei sondaggi'}[kind]||'Nowcast UK';
  cardText(ctx,'DANIELE ANGRISANI · MODELLO ELETTORALE',pad+94,pad+48,'800 16px system-ui','#8fa2b9');
  cardText(ctx,title,pad+28,pad+104,ratio==='5:2'?'900 31px system-ui':'900 38px system-ui','#f5f8fc');
  cardText(ctx,moduleGraphicSubtitle(kind),pad+28,pad+134,'600 15px system-ui','#93a3b7');
  const contentY=pad+158,contentH=H-contentY-pad-48,contentX=pad+28,contentW=W-pad*2-56;
  roundRect(ctx,contentX,contentY,contentW,contentH,20,'#0d151f','#2e3d50',1);
  if(kind==='projection'){
    const totals=projectedTotalsForCard();if(!totals)throw new Error('Proiezione non ancora disponibile');
    const rows=cardPartyRows().slice(0,6),sideW=Math.min(430,contentW*.32),hemiW=contentW-sideW-28;
    drawCardHemicycle(ctx,totals,{x:contentX+25,y:contentY+25,w:hemiW-50,h:contentH-50});
    const rx=contentX+hemiW+12,rowH=Math.max(48,(contentH-38)/Math.max(1,rows.length));
    rows.forEach((r,i)=>{const y=contentY+20+i*rowH;ctx.fillStyle=PARTY[r.p].color;ctx.beginPath();ctx.arc(rx+13,y+18,8,0,Math.PI*2);ctx.fill();cardText(ctx,PARTY[r.p].short,rx+32,y+23,'800 15px system-ui',PARTY[r.p].color);cardText(ctx,fmt0(r.seats),contentX+contentW-24,y+25,'900 24px system-ui','#f5f8fc','right');if(state.mc?.intervals?.[r.p])cardText(ctx,`${fmt0(state.mc.intervals[r.p][0])}–${fmt0(state.mc.intervals[r.p][1])}`,contentX+contentW-24,y+43,'650 11px system-ui','#8191a6','right');});
  }else{
    const svg=kind==='map'?$('#ukMap'):$('#pollTrendSvg');if(!svg||!svg.childNodes.length)throw new Error('Grafica non ancora disponibile');
    const img=await svgImageForExport(svg,{cleanTrend:kind==='trend'});
    if(kind==='trend'){
      const recapH=ratio==='5:2'?76:92,chartH=Math.max(120,contentH-recapH-34);
      drawContainedImage(ctx,img,contentX+24,contentY+18,contentW-48,chartH);
      ctx.strokeStyle='#26384c';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(contentX+24,contentY+24+chartH);ctx.lineTo(contentX+contentW-24,contentY+24+chartH);ctx.stroke();
      drawTrendExportRecap(ctx,contentX+24,contentY+32+chartH,contentW-48,recapH);
    }else drawContainedImage(ctx,img,contentX+24,contentY+20,contentW-48,contentH-40);
  }
  cardText(ctx,`Ultimo sondaggio ${formatDate(state.polls?.[0]?.date||exportDateStamp())}`,pad+28,H-pad-16,'600 12px system-ui','#7e8da1');
  cardText(ctx,'angrisanidj.github.io/modello-uk/',W-pad-28,H-pad-16,'600 12px system-ui','#7e8da1','right');
  return c;
}
async function exportModuleGraphic(kind,ratio='16:9'){const c=await buildModuleGraphicCanvas(kind,ratio),b=await canvasBlob(c);downloadBlob(b,graphicFilename(kind,ratio));return b;}
async function shareModuleGraphic(kind,ratio='16:9',btn=null){
  const c=await buildModuleGraphicCanvas(kind,ratio),b=await canvasBlob(c),file=new File([b],graphicFilename(kind,ratio),{type:'image/png'}),url=currentSiteUrl(),text=`Nowcast UK · ${moduleGraphicSubtitle(kind)}.`;
  if(navigator.share&&navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:'Elezioni nel Regno Unito — Nowcast',text:`${text}\n\n${url}`});return true;}
  downloadBlob(b,file.name);try{await navigator.clipboard?.writeText(`${text}\n\n${url}`);}catch(_){}
  if(btn)flashButton(btn,'PNG + link ✓');return false;
}
function graphicRatioForButton(btn){return btn.closest('[data-graphic-panel]')?.querySelector('[data-export-ratio]')?.value||'16:9';}
function initModuleGraphicExports(){
  $$('[data-export-graphic]').forEach(btn=>btn.addEventListener('click',async()=>{const old=btn.textContent,ratio=graphicRatioForButton(btn);btn.disabled=true;btn.textContent='Esporto…';try{await exportModuleGraphic(btn.dataset.exportGraphic,ratio)}catch(err){console.error(err);alert(err.message||'Esportazione non riuscita')}finally{btn.disabled=false;btn.textContent=old;}}));
  $$('[data-share-graphic]').forEach(btn=>btn.addEventListener('click',async()=>{const old=btn.textContent,ratio=graphicRatioForButton(btn);btn.disabled=true;btn.textContent='Condivido…';try{await shareModuleGraphic(btn.dataset.shareGraphic,ratio,btn)}catch(err){if(err?.name!=='AbortError'){console.error(err);alert(err.message||'Condivisione non riuscita')}}finally{btn.disabled=false;btn.textContent=old;}}));
}
function buildCurrentSnapshot(){
  const m=state.mc||{},totals=m.medians||state.central?.totals||{};
  return {
    schema:'modello-uk-snapshot-v1',
    generated_at:new Date().toISOString(),
    latest_poll_date:state.polls?.[0]?.date||null,
    poll_source:state.pollSource||null,
    poll_average:Object.fromEntries(PARTY_ORDER.filter(p=>Number.isFinite(state.average?.values?.[p])).map(p=>[p,Number(state.average.values[p].toFixed(4))])),
    projection:{
      seats:Object.fromEntries(SEAT_ORDER.filter(p=>Number.isFinite(Number(totals[p]))).map(p=>[p,Number(totals[p])])),
      interval_80:m.intervals||null,
      largest_party_probability:m.largest||null,
      majority_probability:{lab:m.labMaj??null,con:m.conMaj??null,ref:m.refMaj??null},
      hung_parliament_probability:m.hung??null,
      working_majority_threshold:m.workingThreshold||state.central?.ni?.workingThreshold||CONFIG.majority,
      simulations:m.sims||0
    },
    representative_assignment:state.representative?.assignment||null
  };
}
function downloadSnapshotJson(){
  const blob=new Blob([JSON.stringify(buildCurrentSnapshot(),null,2)],{type:'application/json;charset=utf-8'});
  downloadBlob(blob,`uk_snapshot_${exportDateStamp()}.json`);
}

function initMobilePanelToggles(){
  const mq=window.matchMedia?.('(max-width:760px)');
  $$('[data-mobile-toggle]').forEach(btn=>{
    const panel=$(`#${btn.dataset.mobileToggle}`);if(!panel)return;
    const label=btn.querySelector('strong');
    const setCollapsed=collapsed=>{panel.classList.toggle('mobile-collapsed',collapsed);btn.setAttribute('aria-expanded',String(!collapsed));if(label)label.textContent=collapsed?'Mostra':'Nascondi';};
    setCollapsed(!!mq?.matches);
    btn.addEventListener('click',()=>setCollapsed(!panel.classList.contains('mobile-collapsed')));
    mq?.addEventListener?.('change',ev=>setCollapsed(!!ev.matches));
  });
}

function bindUi(){
  initMobilePanelToggles();
  initDesktopNowcastSticky();
  bindViewContextBar();
  $('#refreshBtn').addEventListener('click',refreshDataManually);
  $('#downloadSnapshotJsonBtn')?.addEventListener('click',downloadSnapshotJson);
  initModuleGraphicExports();
  window.addEventListener('scroll',()=>{syncMobileNowcastVisibility();syncDesktopNowcastVisibility();},{passive:true});
  window.addEventListener('resize',()=>{syncMobileNowcastVisibility();syncDesktopNowcastVisibility();if(state.central?.seats?.length)renderMarginals();if(state.polls?.length){renderPolls();renderPollTrend();}});
  initMapNavigation();
  $('#detailZoomBtn')?.addEventListener('click',fitSelectedSeat);
  $('#detailCopyBtn')?.addEventListener('click',copySeatDeepLink);
  $('#detailPngBtn')?.addEventListener('click',()=>downloadSeatCard().catch(err=>{console.error(err);alert(err.message||'Impossibile generare la card del collegio');}));
  $('#detailShareBtn')?.addEventListener('click',ev=>shareSeatCard(ev.currentTarget).catch(err=>{if(err?.name!=='AbortError'){console.error(err);alert(err.message||'Condivisione non disponibile');}}));
  $('#downloadSocialCardBtn')?.addEventListener('click',()=>downloadModelCard('landscape').catch(err=>{console.error(err);alert(err.message||'Card non disponibile');}));
  $('#downloadInstagramCardBtn')?.addEventListener('click',()=>downloadModelCard('instagram').catch(err=>{console.error(err);alert(err.message||'Card non disponibile');}));
  $('#shareSocialCardBtn')?.addEventListener('click',ev=>shareModelCard('landscape',ev.currentTarget).catch(err=>{if(err?.name!=='AbortError'){console.error(err);alert(err.message||'Condivisione non disponibile');}}));
  $$('[data-share]').forEach(btn=>btn.addEventListener('click',()=>openModelShare(btn.dataset.share,btn).catch(err=>{if(err?.name!=='AbortError'){console.error(err);alert(err.message||'Condivisione non disponibile');}})));
  $('#ukMap').addEventListener('click',event=>{
    if(mapZoomState.suppressClick){mapZoomState.suppressClick=false;return;}
    const path=event.target instanceof Element?event.target.closest('path.constituency'):null;
    if(path&&$('#ukMap').contains(path))selectSeat(path.dataset.id);
  });
  $('#mapGeoLayoutBtn')?.addEventListener('click',()=>{if(state.mapLayout==='geo')return;state.mapLayout='geo';renderMap();});
  $('#mapHexLayoutBtn')?.addEventListener('click',()=>{if(state.mapLayout==='hex')return;state.mapLayout='hex';renderMap();});
  $('#mapCentralBtn').addEventListener('click',()=>{state.mapMode=state.mc?.seatProb?'representative':'central';applyMapColors();});
  $('#mapMarginBtn')?.addEventListener('click',()=>{state.mapMode='margin';applyMapColors();});
  $('#mapProbBtn').addEventListener('click',()=>{if(!state.mc)return;state.mapMode='prob';applyMapColors();});
  $('#mapUserBtn')?.addEventListener('click',()=>{if(!state.customScenario)return;state.mapMode='custom';applyMapColors();});
  for(const id of ['seatSearch','seatCountry','seatRegion','seatWinner','seatWinner2024','seatStatus','seatSort','seatSource']){const el=$(`#${id}`);el?.addEventListener(id==='seatSearch'?'input':'change',()=>{state.explorerPage=1;renderMarginals();});}
  for(const id of ['pollSearch','pollPollster','pollArea']){const el=$(`#${id}`);el?.addEventListener(id==='pollSearch'?'input':'change',()=>{state.pollPage=1;renderPolls();});}
  $('#pollResetFilters')?.addEventListener('click',()=>{clearPollFiltersRaw();state.pollPage=1;renderPolls();syncViewContextBar();});
  $('#seatFilterMap')?.addEventListener('change',()=>{applyExplorerMapFilter();renderMapSummary();});
  $('#seatResetFilters')?.addEventListener('click',resetSeatFilters);
  $('#seatExportFiltered')?.addEventListener('click',()=>downloadSeatCsv(true));
  $('#seatExportAll')?.addEventListener('click',()=>downloadSeatCsv(false));
  $('#regionalSource')?.addEventListener('change',()=>{renderRegionalDashboard();syncViewContextBar();});
  $$('[data-seat-preset]').forEach(b=>b.addEventListener('click',()=>applySeatPreset(b.dataset.seatPreset)));
  $('#scenarioNormalizeBtn')?.addEventListener('click',normalizeScenarioInputs);
  $('#scenarioRunBtn')?.addEventListener('click',runCustomScenario);
  $('#scenarioResetBtn')?.addEventListener('click',resetCustomScenario);
  $('#scenarioMapBtn')?.addEventListener('click',()=>{if(!state.customScenario)return;activateCustomScenarioViews();document.querySelector('#territorio')?.scrollIntoView({behavior:'smooth',block:'start'});});
  $('#scenarioMajorityRun')?.addEventListener('click',()=>runScenarioMajoritySearch());
  $$('[data-majority-party]').forEach(btn=>btn.addEventListener('click',()=>{const select=$('#scenarioMajorityParty');if(select)select.value=btn.dataset.majorityParty;const seats=$('#scenarioMajoritySeats');if(seats)seats.value='326';runScenarioMajoritySearch(btn.dataset.majorityParty);}));
  $$('[data-window]').forEach(btn=>btn.addEventListener('click',()=>{ $$('[data-window]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.pollAverageView=btn.dataset.window==='latest'?'latest':'weighted';renderPolls();}));
  $$('[data-poll-trend-range]').forEach(btn=>btn.addEventListener('click',()=>{const raw=btn.dataset.pollTrendRange;state.pollTrendRange=raw==='all'?'all':Number(raw)||180;$$('[data-poll-trend-range]').forEach(x=>x.classList.toggle('active',x===btn));renderPollTrend();}));
}

async function refreshDataManually(){
  const btn=$('#refreshBtn');
  if(!state.polls?.length){await init(true);return;}
  clearError();
  btn.disabled=true;
  const oldLabel=btn.textContent;
  btn.textContent='Verifica…';
  setStatus('Controllo nuovi sondaggi…','loading');
  setRefreshReview('checking','Verifica aggiornamenti in corso','Confronto la fonte nazionale in tempo reale con i sondaggi già caricati.');
  try{
    const live=await fetchLiveNationalPolls();
    validateLivePollSnapshot(live);
    const review=reviewPollingChanges(state.polls,live);
    if(!review.changed){
      const latest=live[0]||state.polls[0];
      setStatus('Nessun nuovo sondaggio · modello invariato','ok');
      setRefreshReview('unchanged','Nessuna variazione nei sondaggi',`${pollReviewDescription(latest)} · Monte Carlo non ricalcolato · review automatica ogni 3 ore.`);
      return;
    }

    const changedRow=review.added[0]||review.corrected[0]||review.removed[0]||live[0];
    const labels=[];
    if(review.added.length)labels.push(pollReviewCountLabel(review.added.length,'nuovo sondaggio','nuovi sondaggi'));
    if(review.corrected.length)labels.push(pollReviewCountLabel(review.corrected.length,'sondaggio corretto','sondaggi corretti'));
    if(review.removed.length)labels.push(pollReviewCountLabel(review.removed.length,'sondaggio rimosso','sondaggi rimossi'));
    const title=labels.join(' · ');
    state.polls=live;
    state.pollSource='MediaWiki in tempo reale · verifica manuale';
    state.average=calculateAverage(live);
    state.latestAverage=latestPollAverage(live);
    state.mc=null;state.precomputedMc=null;state.representative=null;state.customScenario=null;state.scenarioHemicycleActive=false;
    state.explorerPage=1;state.pollPage=1;state.mapMode='central';
    if(publishedMcRefreshTimer){clearTimeout(publishedMcRefreshTimer);publishedMcRefreshTimer=null;publishedMcRefreshAttempts=0;}
    renderPolls();renderPollTrend();renderCoalitionButtons();
    if(state.constituencies.length!==650)throw new Error('I 650 collegi non sono disponibili per ricalcolare il modello.');
    buildCentral();renderScenarioInputs(true);renderCustomScenario();renderCentral();renderMap();restoreSeatDeepLink();
    setStatus('Nuovi dati trovati · Monte Carlo in avvio','loading');
    setRefreshReview('changed',title,`Variazioni confermate nella fonte · Monte Carlo: 50.000 simulazioni in avvio.`,review);
    const fp=fingerprint(),cached=loadMcCache(),alreadyAvailable=cached?.fingerprint===fp;
    await runMonteCarlo({allowClientBuild:true});
    setStatus('Dati aggiornati · Monte Carlo completato','ok');
    setRefreshReview('done',`${title} · Monte Carlo completato`,alreadyAvailable?`Risultato già disponibile per queste rilevazioni.`:`50.000 simulazioni completate; l'aggiornamento automatico renderà persistenti dati e card.`,review);
    $('#footerBuild').textContent=`Dati: 650 collegi · sondaggi: ${state.pollSource} · rilevazioni subnazionali: ${state.subnational.length} · Irlanda del Nord: ${niModuleReady()?'18 collegi simulati':'base fissa'}`;
  }catch(err){
    console.error(err);
    setStatus('Verifica aggiornamenti non riuscita','error');
    setRefreshReview('error','Impossibile verificare nuovi sondaggi',err.message||String(err));
  }finally{
    btn.disabled=false;btn.textContent=oldLabel;
  }
}

async function init(force=false){
  clearError();
  state.mc=null;
  state.representative=null;
  state.customScenario=null;
  state.scenarioHemicycleActive=false;
  state.explorerPage=1;state.explorerMatchingIds=null;state.pollPage=1;
  state.mapMode='central';
  document.body.classList.remove('has-active-view');const viewBar=$('#viewStateBar');if(viewBar){viewBar.hidden=true;viewBar.classList.remove('is-active','is-filtered','is-scenario','is-mixed','below-desktop-sticky');}
  updateMapModeButtons();
  setMonteCarloPending(true);
  updateMobileNowcastSticky();
  setStatus('Caricamento dati…','loading');
  $('#refreshBtn').disabled=true;
  try{
    const [polls,constituencies,geometry,ni,modelParams,mrpLite,precomputedMc,subnational,territorialBaseline]=await Promise.all([
      loadPolls(),loadConstituencies(),loadGeometry(),fetchJson(CONFIG.niLocal,5000).catch(()=>null),
      loadModelParams(),fetchJson(CONFIG.mrpLiteLocal,8000).catch(()=>null),fetchJson(CONFIG.mcSummaryLocal,5000).catch(()=>null),loadSubnationalPolls(),loadTerritorialBaseline()
    ]);
    state.polls=polls;state.average=calculateAverage(polls);state.latestAverage=latestPollAverage(polls);
    state.constituencies=constituencies;state.constituencyIndex=new Map(constituencies.map(c=>[c.id,c]));
    state.geometry=geometry;state.ni=ni;state.modelParams=modelParams;state.mrpLite=mrpLite;state.precomputedMc=precomputedMc;state.subnational=subnational;state.territorialBaseline=territorialBaseline;
    renderPolls();renderPollTrend();renderCoalitionButtons();
    if(constituencies.length===650){buildCentral();renderScenarioInputs(true);renderCustomScenario();renderCentral();renderMap();restoreSeatDeepLink();setStatus('Dati aggiornati · simulazione pronta','ok');$('#footerBuild').textContent=`Dati: 650 collegi · sondaggi: ${state.pollSource} · rilevazioni subnazionali: ${state.subnational.length} · Irlanda del Nord: ${niModuleReady()?'18 collegi simulati':'base fissa'}`;await runMonteCarlo();}else{
      setStatus('Sondaggi caricati · manca la base territoriale','error');showError('La dashboard nazionale è attiva, ma i 650 risultati di collegio non sono ancora nello archivio locale e il browser non è riuscito a recuperarli direttamente. Esegui la GitHub Action “Update UK election data”: genererà automaticamente baseline e geometrie.');renderMap();
    }
  }catch(err){console.error(err);setStatus('Errore di caricamento','error');showError(`Errore: ${err.message||err}`);}finally{$('#refreshBtn').disabled=false;}
}

bindUi();init(false);
})();
