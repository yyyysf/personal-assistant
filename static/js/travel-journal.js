(function () {
  'use strict';

  var dialog = null;
  var state = { year: null, book: null, closing: false };
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealObserver = null;
  var YEAR_KEY = 'travel:journal-year';

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function refreshScrawl() {
    if (!window.scrawl) return;
    try {
      window.scrawl.initSpiral();
      window.scrawl.initStickers();
    } catch (err) {
      /* 装饰失败不影响业务 */
    }
  }

  /* ---------- 全局导航抽屉（仅旅游页存在） ---------- */
  function setNavOpen(open) {
    document.body.classList.toggle('nav-open', open);
    var button = qs('#travel-nav-toggle');
    if (button) {
      button.classList.toggle('is-open', open);
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      button.setAttribute('aria-label', open ? '收起导航' : '展开导航');
      var glyph = qs('.travel-nav-glyph', button);
      if (glyph) glyph.textContent = open ? '✕' : '☰';
    }
    var scrim = qs('#travel-nav-scrim');
    if (scrim) scrim.hidden = !open;
  }

  /* ---------- 滚动渐显 ---------- */
  function observeReveals(root) {
    if (!root) return;
    var items = qsa('.journey-sticker, .journal-polaroid, .journal-sticky-note, .journal-fragment', root);
    if (reduced || !('IntersectionObserver' in window)) {
      items.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }
    if (!revealObserver) {
      revealObserver = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-visible');
              revealObserver.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.1, rootMargin: '0px 0px -24px 0px' }
      );
    }
    items.forEach(function (el) {
      if (el.classList.contains('is-visible')) return;
      revealObserver.observe(el);
    });
  }

  /* ---------- 年份翻页 ---------- */
  function rootEl() {
    return document.getElementById('journey-list');
  }

  function spreadFor(key) {
    return qs('[data-journal-spread="' + key + '"]', rootEl());
  }

  function storedYear() {
    try {
      return window.localStorage.getItem(YEAR_KEY);
    } catch (err) {
      return null;
    }
  }

  function rememberYear(key) {
    try {
      window.localStorage.setItem(YEAR_KEY, key);
    } catch (err) {
      /* 隐私模式下忽略 */
    }
  }

  function preferredYear() {
    var root = rootEl();
    if (!root) return null;
    var candidates = [state.year, storedYear(), root.dataset.journalDefaultYear];
    for (var i = 0; i < candidates.length; i += 1) {
      var key = candidates[i];
      if (key && spreadFor(key)) return key;
    }
    var firstSpread = qs('[data-journal-spread]', root);
    return firstSpread ? firstSpread.dataset.journalSpread : null;
  }

  function activateYear(key, animate) {
    var root = rootEl();
    if (!root || !key) return;
    var target = spreadFor(key);
    if (!target) return;
    state.year = key;
    qsa('[data-journal-year]', document).forEach(function (tab) {
      var on = tab.dataset.journalYear === key;
      tab.classList.toggle('is-active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    qsa('[data-journal-spread]', root).forEach(function (spread) {
      var on = spread === target;
      spread.hidden = !on;
      spread.classList.toggle('is-active', on);
      if (!on) spread.classList.remove('is-entering');
    });
    if (animate && !reduced) {
      target.classList.remove('is-entering');
      void target.offsetWidth;
      target.classList.add('is-entering');
    }
    observeReveals(target);
    setupJourneyPager(target);
    refreshScrawl();
  }

  function initSpreads() {
    if (!rootEl()) return;
    activateYear(preferredYear(), false);
  }

  /* ---------- 右页旅程卡片：一屏之内翻页 ---------- */
  var pagerResizeTimer = null;
  var PAGER_TOP_ROOM = 12;

  function journeyList(spread) {
    return qs('.journey-sticker-list', spread);
  }

  function pagerStarts(spread) {
    var raw = spread.dataset.journalPageStarts;
    if (!raw) return [];
    return raw.split(',').map(function (value) { return Number(value) || 0; });
  }

  function pageForTarget(target) {
    var track = target.closest ? target.closest('.journal-pager-track') : null;
    if (!track) return null;
    var spread = track.closest('[data-journal-spread]');
    var starts = spread ? pagerStarts(spread) : [];
    if (starts.length < 2) return null;
    var offset = target.offsetTop;
    var page = 0;
    for (var i = 0; i < starts.length; i += 1) {
      if (offset >= starts[i] - 1) page = i;
    }
    return { spread: spread, page: page };
  }

  function resetPager(spread) {
    var list = journeyList(spread);
    if (!list) return;
    var track = qs('.journal-pager-track', list);
    if (track) {
      qsa('.journey-sticker', track).forEach(function (card) {
        list.appendChild(card);
      });
      track.parentNode.removeChild(track);
    }
    list.classList.remove('journal-paged');
    delete spread.dataset.journalPageStarts;
    delete spread.dataset.journalPage;
    spread.classList.remove('has-pages');
  }

  function applyPager(spread, starts, index) {
    var list = journeyList(spread);
    var track = list ? qs('.journal-pager-track', list) : null;
    if (!track || !starts.length) return;
    var total = starts.length;
    var page = Math.max(0, Math.min(index, total - 1));
    track.style.transform = 'translateY(' + (PAGER_TOP_ROOM - starts[page]) + 'px)';
    spread.dataset.journalPage = String(page);
    spread.classList.toggle('has-pages', total > 1);

    var pager = qs('[data-journal-pager]', spread);
    if (pager) pager.hidden = total <= 1;
    var edges = qs('[data-journal-flip-edges]', spread);
    if (edges) edges.hidden = total <= 1;
    var now = qs('[data-journal-page-now]', spread);
    var totalEl = qs('[data-journal-page-total]', spread);
    if (now) now.textContent = String(page + 1);
    if (totalEl) totalEl.textContent = String(total);
    qsa('[data-journal-page-prev]', spread).forEach(function (btn) {
      btn.disabled = page <= 0;
    });
    qsa('[data-journal-page-next]', spread).forEach(function (btn) {
      btn.disabled = page >= total - 1;
    });
  }

  function flipJourneyPage(spread, delta) {
    if (!spread) return;
    var starts = pagerStarts(spread);
    if (starts.length < 2) return;
    var current = parseInt(spread.dataset.journalPage || '0', 10) || 0;
    var next = current + delta;
    if (next < 0 || next >= starts.length) return;
    applyPager(spread, starts, next);
  }

  function setupJourneyPager(spread) {
    if (!spread) return;
    var list = journeyList(spread);
    if (!list) return;
    var previous = parseInt(spread.dataset.journalPage || '0', 10) || 0;
    resetPager(spread);
    if (spread.hidden) return;
    var cards = qsa('.journey-sticker', list);
    if (!cards.length) return;

    var track = document.createElement('div');
    track.className = 'journal-pager-track';
    var listStyle = window.getComputedStyle(list);
    if (listStyle.gap && listStyle.gap !== 'normal') {
      track.style.gap = listStyle.gap;
    }
    cards.forEach(function (card) {
      card.classList.add('is-visible');
      track.appendChild(card);
    });
    list.appendChild(track);
    list.classList.add('journal-paged');

    /* 翻页条先占位，量出的高度才是分页后的真实可视高度 */
    var pager = qs('[data-journal-pager]', spread);
    if (pager) pager.hidden = false;

    var pageHeight = list.clientHeight -
      (parseFloat(listStyle.paddingTop) || 0) -
      (parseFloat(listStyle.paddingBottom) || 0);
    var available = pageHeight - PAGER_TOP_ROOM;
    var starts = [0];
    var pageFirstCards = [cards[0]];
    if (available > 24) {
      var pageTop = 0;
      cards.forEach(function (card, i) {
        if (i === 0) return;
        var bottom = card.offsetTop + card.offsetHeight;
        if (bottom - pageTop > available + 1) {
          pageTop = card.offsetTop;
          starts.push(pageTop);
          pageFirstCards.push(card);
        }
      });
    }

    /* 每页末尾补齐留白：翻页后下一页不会从页脚探出半张卡片 */
    if (starts.length > 1) {
      var shift = 0;
      for (var p = 1; p < starts.length; p += 1) {
        var natural = starts[p] + shift;
        var gap = pageHeight - (natural - starts[p - 1]);
        if (gap > 0) {
          var spacer = document.createElement('div');
          spacer.className = 'journal-pager-spacer';
          spacer.style.height = gap + 'px';
          spacer.setAttribute('aria-hidden', 'true');
          track.insertBefore(spacer, pageFirstCards[p]);
          shift += gap;
          starts[p] = natural + gap;
        } else {
          starts[p] = natural;
        }
      }
    }
    spread.dataset.journalPageStarts = starts.join(',');
    applyPager(spread, starts, previous);
  }

  function refreshActivePager() {
    var root = rootEl();
    if (!root) return;
    var active = qs('.journal-spread.is-active', root);
    if (active) setupJourneyPager(active);
  }

  /* ---------- 旅程手记卡片（单张纸页，不做书本翻页） ---------- */
  function buildBook(root) {
    if (!root || root.dataset.bookReady) return;
    root.dataset.bookReady = '1';
    root.classList.add('is-static');
  }

  function openJourney(url, title) {
    if (!dialog) dialog = document.getElementById('app-modal');
    if (!dialog) return;
    state.closing = false;
    dialog.classList.add('is-journey-book');
    if (window.AppModal) window.AppModal.open(url, title || '旅程手账');
  }

  function finishClose() {
    var book = state.book;
    state.book = null;
    state.closing = false;
    if (book && book.flip && typeof book.flip.destroy === 'function') {
      try {
        book.flip.destroy();
      } catch (err) {
        /* 忽略销毁异常 */
      }
    }
    if (dialog) {
      dialog.classList.remove('is-journey-book');
      if (dialog.open) dialog.close();
    }
  }

  function requestClose() {
    if (state.closing) return;
    var book = state.book;
    if (!book || !book.flip || reduced) {
      finishClose();
      return;
    }
    state.closing = true;
    try {
      book.flip.flip(0);
    } catch (err) {
      finishClose();
      return;
    }
    window.setTimeout(finishClose, 760);
  }

  /* ---------- 手账小装饰：贴纸提示 / 定位 / 拖动 ---------- */
  var scrapTip = null;
  var dragState = null;

  function hideScrapTip() {
    if (!scrapTip) return;
    scrapTip.classList.remove('is-open');
  }

  function positionScrapTip() {
    if (!scrapTip || !scrapTip.dataset.anchorId) return;
    var trigger = document.getElementById(scrapTip.dataset.anchorId);
    if (!trigger) return;
    var rect = trigger.getBoundingClientRect();
    var tipRect = scrapTip.getBoundingClientRect();
    var left = rect.left + rect.width / 2 - tipRect.width / 2;
    left = Math.min(Math.max(left, 12), window.innerWidth - tipRect.width - 12);
    var top = rect.top - tipRect.height - 12;
    if (top < 12) top = rect.bottom + 12;
    top = Math.min(Math.max(top, 12), window.innerHeight - tipRect.height - 12);
    scrapTip.style.left = left + 'px';
    scrapTip.style.top = top + 'px';
  }

  function showScrapTip(trigger) {
    if (!scrapTip) {
      scrapTip = document.createElement('div');
      scrapTip.className = 'scrap-tip';
      scrapTip.setAttribute('role', 'status');
      document.body.appendChild(scrapTip);
    }
    scrapTip.textContent = '';
    if (trigger.dataset.scrapTitle) {
      var title = document.createElement('strong');
      title.textContent = trigger.dataset.scrapTitle;
      scrapTip.appendChild(title);
    }
    if (trigger.dataset.scrapTip) {
      var body = document.createElement('span');
      body.textContent = trigger.dataset.scrapTip;
      scrapTip.appendChild(body);
    }
    scrapTip.classList.toggle('is-ticket', trigger.hasAttribute('data-scrap-ticket'));
    scrapTip.dataset.anchorId = trigger.id || '';
    if (!trigger.id) {
      trigger.id = 'scrap-' + Math.random().toString(36).slice(2, 9);
      scrapTip.dataset.anchorId = trigger.id;
    }
    scrapTip.style.visibility = 'hidden';
    scrapTip.classList.add('is-open');
    positionScrapTip();
    scrapTip.style.visibility = '';
  }

  function popScrap(el) {
    el.classList.remove('is-pop');
    void el.offsetWidth;
    el.classList.add('is-pop');
    window.setTimeout(function () { el.classList.remove('is-pop'); }, 480);
  }

  function focusScrap(trigger) {
    var target = null;
    try {
      target = document.querySelector(trigger.dataset.scrapFocus);
    } catch (err) {
      return;
    }
    if (!target) return;
    target.classList.remove('is-scrap-flash');
    void target.offsetWidth;
    target.classList.add('is-scrap-flash');
    var paged = pageForTarget(target);
    if (paged) {
      applyPager(paged.spread, pagerStarts(paged.spread), paged.page);
    } else {
      try {
        target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
      } catch (err) {
        target.scrollIntoView();
      }
    }
    window.setTimeout(function () { target.classList.remove('is-scrap-flash'); }, 1500);
  }

  document.addEventListener('pointerdown', function (event) {
    var el = event.target.closest('[data-scrap-drag]');
    if (!el || event.button !== 0) return;
    var parent = el.closest('.journal-page, .map-page');
    if (!parent) return;
    var elRect = el.getBoundingClientRect();
    var parentRect = parent.getBoundingClientRect();
    dragState = {
      el: el,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      baseLeft: parseFloat(el.style.left || '0'),
      baseTop: parseFloat(el.style.top || '0'),
      minX: parentRect.left - elRect.left + 4,
      maxX: parentRect.right - elRect.right - 4,
      minY: parentRect.top - elRect.top + 4,
      maxY: parentRect.bottom - elRect.bottom - 4,
      moved: false
    };
    el.classList.add('is-dragging');
    try { el.setPointerCapture(event.pointerId); } catch (err) { /* 忽略 */ }
    hideScrapTip();
  });

  document.addEventListener('pointermove', function (event) {
    if (!dragState || event.pointerId !== dragState.pointerId) return;
    var dx = event.clientX - dragState.startX;
    var dy = event.clientY - dragState.startY;
    if (!dragState.moved && Math.abs(dx) + Math.abs(dy) < 5) return;
    dragState.moved = true;
    var x = Math.min(Math.max(dragState.baseLeft + dx, dragState.minX), dragState.maxX);
    var y = Math.min(Math.max(dragState.baseTop + dy, dragState.minY), dragState.maxY);
    dragState.el.style.position = 'relative';
    dragState.el.style.left = x + 'px';
    dragState.el.style.top = y + 'px';
    hideScrapTip();
  });

  function endScrapDrag(event) {
    if (!dragState) return;
    if (event && event.pointerId !== undefined && event.pointerId !== dragState.pointerId) return;
    var el = dragState.el;
    if (dragState.moved) {
      el.dataset.dragMoved = '1';
      window.setTimeout(function () { delete el.dataset.dragMoved; }, 0);
    }
    el.classList.remove('is-dragging');
    try { el.releasePointerCapture(dragState.pointerId); } catch (err) { /* 忽略 */ }
    dragState = null;
  }

  document.addEventListener('pointerup', endScrapDrag);
  document.addEventListener('pointercancel', endScrapDrag);

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-scrap-tip], [data-scrap-focus]');
    if (trigger) {
      if (trigger.dataset.dragMoved === '1') {
        delete trigger.dataset.dragMoved;
        return;
      }
      event.preventDefault();
      popScrap(trigger);
      if (trigger.dataset.scrapFocus) focusScrap(trigger);
      if (trigger.dataset.scrapTip) showScrapTip(trigger);
      return;
    }
    if (event.target.closest('.scrap-tip')) return;
    hideScrapTip();
  });

  window.addEventListener('resize', hideScrapTip);

  /* ---------- 事件绑定 ---------- */
  document.addEventListener('click', function (event) {
    if (event.target.closest('#travel-nav-toggle')) {
      setNavOpen(!document.body.classList.contains('nav-open'));
      return;
    }
    if (event.target.closest('#travel-nav-scrim')) {
      setNavOpen(false);
      return;
    }
    var pageBtn = event.target.closest('[data-journal-page-prev], [data-journal-page-next]');
    if (pageBtn) {
      var spread = pageBtn.closest('[data-journal-spread]');
      if (spread) {
        event.preventDefault();
        flipJourneyPage(spread, pageBtn.hasAttribute('data-journal-page-prev') ? -1 : 1);
      }
      return;
    }
    var yearTab = event.target.closest('[data-journal-year]');
    if (yearTab) {
      event.preventDefault();
      var key = yearTab.dataset.journalYear;
      rememberYear(key);
      activateYear(key, true);
      return;
    }
    var journeyTrigger = event.target.closest('[data-journey-book-url]');
    if (journeyTrigger) {
      event.preventDefault();
      openJourney(journeyTrigger.dataset.journeyBookUrl, journeyTrigger.dataset.journeyTitle);
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && document.body.classList.contains('nav-open')) {
      setNavOpen(false);
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    var target = event.target;
    if (target && target.closest && target.closest('input, textarea, select, [contenteditable="true"]')) {
      return;
    }
    var activeSpread = qs('#journey-list .journal-spread.is-active');
    if (!activeSpread || !activeSpread.classList.contains('has-pages')) return;
    flipJourneyPage(activeSpread, event.key === 'ArrowRight' ? 1 : -1);
  });

  window.addEventListener('load', function () {
    refreshActivePager();
  });

  window.addEventListener('resize', function () {
    if (pagerResizeTimer) window.clearTimeout(pagerResizeTimer);
    pagerResizeTimer = window.setTimeout(refreshActivePager, 180);
  });

  /* 书本弹窗关闭时先合上，再关闭对话框 */
  document.addEventListener(
    'click',
    function (event) {
      if (!state.book) return;
      if (event.target.closest('[data-modal-close]')) {
        event.preventDefault();
        event.stopPropagation();
        requestClose();
      }
    },
    true
  );

  document.addEventListener('DOMContentLoaded', function () {
    dialog = document.getElementById('app-modal');
    initSpreads();
    observeReveals(document);
    refreshScrawl();
    if (!dialog) return;
    dialog.addEventListener(
      'click',
      function (event) {
        if (event.target !== dialog || !state.book) return;
        event.preventDefault();
        event.stopPropagation();
        requestClose();
      },
      true
    );
    dialog.addEventListener('cancel', function (event) {
      if (!state.book) return;
      event.preventDefault();
      requestClose();
    });
    dialog.addEventListener('close', function () {
      if (!state.book) return;
      finishClose();
    });
  });

  document.body.addEventListener('list:refresh', function () {
    if (!window.htmx) return;
    /* 各自指定 source，避免 htmx 2 把并发请求丢进 body 的同一队列 */
    var stats = document.getElementById('journal-stats');
    if (stats) {
      window.htmx.ajax('GET', '/travel/journal/stats', {
        source: stats,
        target: '#journal-stats',
        swap: 'innerHTML'
      });
    }
    var years = document.getElementById('journal-years');
    if (years) {
      var url = '/travel/journal/years';
      var status = new URLSearchParams(window.location.search).get('journey_status') || '';
      if (status) url += '?journey_status=' + encodeURIComponent(status);
      window.htmx.ajax('GET', url, { source: years, target: '#journal-years', swap: 'outerHTML' });
    }
  });

  document.body.addEventListener('htmx:afterSwap', function (event) {
    var target = event.target;
    if (!target) return;
    var bookRoot = target.querySelector ? target.querySelector('.journey-book') : null;
    if (bookRoot) buildBook(bookRoot);
    if (target.id === 'journal-stats') {
      refreshScrawl();
      return;
    }
    if (target.id === 'journal-years') {
      initSpreads();
      return;
    }
    var list = target.id === 'journey-list'
      ? target
      : target.querySelector && target.querySelector('#journey-list');
    if (list) {
      initSpreads();
      refreshScrawl();
    }
  });
})();
