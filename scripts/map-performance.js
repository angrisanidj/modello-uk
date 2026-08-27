(() => {
  'use strict';

  const SVG_NS='http://www.w3.org/2000/svg';
  const map=document.getElementById('ukMap');
  const wrap=document.getElementById('mapWrap');
  if(!map||!wrap)return;

  let hoverPath=null,tooltip=null,lastTarget=null;
  function ensureUi(){
    if(!hoverPath){
      hoverPath=document.createElementNS(SVG_NS,'path');
      hoverPath.setAttribute('class','map-hover-overlay');
      hoverPath.setAttribute('aria-hidden','true');
      hoverPath.style.display='none';
    }
    if(hoverPath.parentNode!==map)map.appendChild(hoverPath);
    if(!tooltip){
      tooltip=document.createElement('div');
      tooltip.className='map-fast-tooltip';
      tooltip.setAttribute('role','tooltip');
      tooltip.hidden=true;
      wrap.appendChild(tooltip);
    }
  }

  function positionTooltip(event){
    const rect=wrap.getBoundingClientRect();
    const x=event.clientX-rect.left+12;
    const y=event.clientY-rect.top+12;
    tooltip.style.transform=`translate3d(${Math.max(8,x)}px,${Math.max(8,y)}px,0)`;
  }
  function enter(target,event){
    if(!target||target===lastTarget)return;
    ensureUi();
    lastTarget=target;
    hoverPath.setAttribute('d',target.getAttribute('d')||'');
    hoverPath.style.display='';
    tooltip.textContent=target.dataset.mapName||target.dataset.id||'';
    tooltip.hidden=!tooltip.textContent;
    if(!tooltip.hidden)positionTooltip(event);
  }
  function clear(){
    lastTarget=null;
    if(hoverPath){hoverPath.style.display='none';hoverPath.removeAttribute('d');}
    if(tooltip)tooltip.hidden=true;
  }
  map.addEventListener('pointerover',event=>{
    const target=event.target instanceof Element?event.target.closest('path.constituency'):null;
    if(target&&map.contains(target))enter(target,event);
  },{passive:true});

  map.addEventListener('pointerleave',clear,{passive:true});
  map.addEventListener('maprendered',()=>{
    lastTarget=null;
    ensureUi();
    map.appendChild(hoverPath);
  });

  ensureUi();
})();
