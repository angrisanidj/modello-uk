(() => {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const map = document.getElementById('ukMap');
  const wrap = document.getElementById('mapWrap');
  if (!map || !wrap) return;

  let hoverPath = null;
  let lastTarget = null;
  let tooltip = null;
  let raf = 0;
  let pendingPointer = null;

  function ensureLayers() {
    if (!hoverPath) {
      hoverPath = document.createElementNS(SVG_NS, 'path');
      hoverPath.setAttribute('class', 'map-hover-overlay');
      hoverPath.setAttribute('aria-hidden', 'true');
      hoverPath.style.display = 'none';
      map.appendChild(hoverPath);
    } else if (hoverPath.parentNode === map && map.lastElementChild !== hoverPath) {
      map.appendChild(hoverPath);
    }

    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.className = 'map-fast-tooltip';
      tooltip.setAttribute('role', 'tooltip');
      tooltip.hidden = true;
      wrap.appendChild(tooltip);
    }
  }

  function preparePaths() {
    ensureLayers();
    const paths = map.querySelectorAll('path.constituency');
    for (const path of paths) {
      const title = path.querySelector('title');
      if (title) {
        path.dataset.mapName = title.textContent || path.dataset.id || '';
        title.remove();
      } else if (!path.dataset.mapName) {
        path.dataset.mapName = path.dataset.id || '';
      }
    }
  }

  function hideHover() {
    lastTarget = null;
    if (hoverPath) {
      hoverPath.style.display = 'none';
      hoverPath.removeAttribute('d');
    }
    if (tooltip) tooltip.hidden = true;
  }

  function scheduleTooltip(clientX, clientY) {
    pendingPointer = {clientX, clientY};
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      if (!tooltip || !pendingPointer || tooltip.hidden) return;
      const rect = wrap.getBoundingClientRect();
      const x = pendingPointer.clientX - rect.left + 12;
      const y = pendingPointer.clientY - rect.top + 12;
      const maxX = Math.max(8, rect.width - tooltip.offsetWidth - 8);
      const maxY = Math.max(8, rect.height - tooltip.offsetHeight - 8);
      tooltip.style.transform = `translate3d(${Math.min(x, maxX)}px,${Math.min(y, maxY)}px,0)`;
    });
  }

  map.addEventListener('pointermove', (event) => {
    const target = event.target instanceof Element
      ? event.target.closest('path.constituency')
      : null;

    if (!target || !map.contains(target)) {
      hideHover();
      return;
    }

    ensureLayers();

    if (target !== lastTarget) {
      lastTarget = target;
      hoverPath.setAttribute('d', target.getAttribute('d') || '');
      hoverPath.style.display = '';
      tooltip.textContent = target.dataset.mapName || target.dataset.id || '';
      tooltip.hidden = !tooltip.textContent;
    }
    scheduleTooltip(event.clientX, event.clientY);
  }, {passive: true});

  map.addEventListener('pointerleave', hideHover, {passive: true});

  // app.js builds the SVG asynchronously. Observe only child-list mutations;
  // when the map is rebuilt, cache names once and recreate the single overlay.
  const observer = new MutationObserver((mutations) => {
    let relevant = false;
    for (const mutation of mutations) {
      if (mutation.type === 'childList') {
        relevant = true;
        break;
      }
    }
    if (!relevant) return;
    requestAnimationFrame(preparePaths);
  });

  observer.observe(map, {childList: true});
  preparePaths();
})();
