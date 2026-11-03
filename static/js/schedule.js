(function () {
  'use strict';

  var STORAGE_KEY = 'pa.schedule.timer.v1';
  var chartInstances = [];
  var tickHandle = null;
  var finishing = false;

  function pad(value) {
    return value < 10 ? '0' + value : String(value);
  }

  function loadState() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var state = JSON.parse(raw);
      return state && typeof state === 'object' ? state : null;
    } catch (error) {
      return null;
    }
  }

  function saveState(state) {
    try {
      if (state) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      /* 隐私模式下 localStorage 可能不可用，忽略即可 */
    }
  }

  function makeToken() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  function elapsedMs(state, at) {
    var total = state.accumulatedMs || 0;
    if (state.running && state.lastTickAt) {
      total += Math.max(0, at - state.lastTickAt);
    }
    return total;
  }

  function formatDuration(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    var seconds = total % 60;
    return pad(hours) + ':' + pad(minutes) + ':' + pad(seconds);
  }

  function localDateTime(value) {
    var date = value instanceof Date ? value : new Date(value);
    return (
      date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
      'T' + pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds())
    );
  }

  function renderBanner() {
    var banner = document.getElementById('timer-banner');
    if (!banner) return;
    var state = loadState();
    if (!state) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    banner.classList.toggle('is-paused', !state.running);
    var label = banner.querySelector('.timer-banner-label');
    if (label) label.textContent = state.running ? '专注中' : '已暂停';
    var timeEl = document.getElementById('timer-banner-time');
    if (timeEl) timeEl.textContent = formatDuration(elapsedMs(state, Date.now()));
    var titleEl = document.getElementById('timer-banner-title');
    if (titleEl) titleEl.textContent = state.title || '临时任务';
  }

  function renderTimerPanel() {
    var display = document.getElementById('timer-display');
    if (!display) return;
    var state = loadState();
    var status = document.getElementById('timer-status');
    var startButton = document.getElementById('timer-start');
    var pauseButton = document.getElementById('timer-pause');
    var finishButton = document.getElementById('timer-finish');

    if (!state) {
      display.textContent = '00:00:00';
      if (status) status.textContent = '准备开始';
      if (startButton) {
        startButton.textContent = '开始';
        startButton.disabled = false;
      }
      if (pauseButton) pauseButton.disabled = true;
      if (finishButton) finishButton.disabled = true;
      return;
    }

    display.textContent = formatDuration(elapsedMs(state, Date.now()));
    if (status) {
      status.textContent = (state.running ? '专注中 · ' : '已暂停 · ') + (state.title || '临时任务');
    }
    if (startButton) {
      startButton.textContent = state.running ? '进行中' : '继续';
      startButton.disabled = state.running || finishing;
    }
    if (pauseButton) pauseButton.disabled = !state.running || finishing;
    if (finishButton) finishButton.disabled = finishing;
  }

  function renderAll() {
    renderBanner();
    renderTimerPanel();
  }

  function startTicker() {
    if (tickHandle) return;
    tickHandle = window.setInterval(renderAll, 1000);
  }

  function readTimerInputs() {
    var select = document.getElementById('timer-task-select');
    if (!select) return null;
    var option = select.options[select.selectedIndex];
    var state = {
      taskId: null,
      title: '',
      projectId: null,
      projectName: '',
      subprojectId: null,
      subprojectName: '',
      note: '',
      startedAt: null,
      accumulatedMs: 0,
      running: false,
      lastTickAt: null,
      clientToken: ''
    };
    var noteInput = document.getElementById('timer-note');
    state.note = noteInput ? noteInput.value : '';

    if (select.value) {
      state.taskId = Number(select.value);
      state.title = option.dataset.title || option.textContent.trim();
      state.projectId = option.dataset.projectId ? Number(option.dataset.projectId) : null;
      state.projectName = option.dataset.projectName || '';
      state.subprojectId = option.dataset.subprojectId
        ? Number(option.dataset.subprojectId)
        : null;
      state.subprojectName = option.dataset.subprojectName || '';
      return state;
    }

    var titleInput = document.getElementById('timer-temp-title');
    var title = titleInput ? titleInput.value.trim() : '';
    if (!title) {
      if (window.showToast) window.showToast('请选择计划任务或填写临时任务名称', 'error');
      return null;
    }
    state.title = title;
    var projectSelect = document.getElementById('timer-temp-project');
    if (projectSelect && projectSelect.value) {
      state.projectId = Number(projectSelect.value);
      state.projectName = projectSelect.options[projectSelect.selectedIndex].textContent.trim();
    }
    return state;
  }

  function beginFromInputs() {
    if (finishing) return;
    var existing = loadState();
    if (existing) {
      existing.running = true;
      existing.lastTickAt = Date.now();
      existing.clientToken = existing.clientToken || makeToken();
      existing.startedAt = existing.startedAt || new Date().toISOString();
      saveState(existing);
      renderAll();
      return;
    }
    var state = readTimerInputs();
    if (!state) return;
    state.startedAt = new Date().toISOString();
    state.running = true;
    state.lastTickAt = Date.now();
    state.clientToken = makeToken();
    saveState(state);
    renderAll();
    if (window.showToast) window.showToast('开始专注', 'success');
  }

  function pauseTimer() {
    var state = loadState();
    if (!state || !state.running || finishing) return;
    state.accumulatedMs = elapsedMs(state, Date.now());
    state.running = false;
    state.lastTickAt = null;
    saveState(state);
    renderAll();
  }

  function refreshContent() {
    var content = document.getElementById('schedule-content');
    if (!content || !content.dataset.refreshUrl || !window.htmx) return;
    window.htmx.ajax('GET', content.dataset.refreshUrl, {
      target: '#' + content.id,
      swap: 'outerHTML'
    });
  }

  function finishTimer() {
    var state = loadState();
    if (!state || finishing) return;
    if (!window.confirm('结束本次专注并保存为 Done 记录？')) return;
    finishing = true;
    renderTimerPanel();

    var totalMs = elapsedMs(state, Date.now());
    var endedAt = new Date();
    var startedAt = state.startedAt ? new Date(state.startedAt) : null;
    if (!startedAt || isNaN(startedAt.getTime())) {
      startedAt = new Date(endedAt.getTime() - totalMs);
    }
    var payload = {
      task_id: state.taskId || null,
      title: state.title || '临时任务',
      project_id: state.projectId || null,
      subproject_id: state.subprojectId || null,
      started_at: localDateTime(startedAt),
      ended_at: localDateTime(endedAt),
      duration_seconds: Math.max(1, Math.round(totalMs / 1000)),
      note: state.note || '',
      client_token: state.clientToken || makeToken()
    };

    window.fetch('/schedule/timer/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, body: body };
      });
    }).then(function (result) {
      if (!result.ok || (result.body && result.body.ok === false)) {
        throw new Error((result.body && result.body.message) || '保存失败，请重试');
      }
      saveState(null);
      finishing = false;
      if (window.showToast) window.showToast('已保存 Done 记录', 'success');
      renderAll();
      refreshContent();
    }).catch(function (error) {
      finishing = false;
      if (window.showToast) window.showToast(error.message || '保存失败，请重试', 'error');
      renderAll();
    });
  }

  function startFromDetail(button) {
    var state = {
      taskId: button.dataset.taskId ? Number(button.dataset.taskId) : null,
      title: button.dataset.title || '计划任务',
      projectId: button.dataset.projectId ? Number(button.dataset.projectId) : null,
      projectName: button.dataset.projectName || '',
      subprojectId: button.dataset.subprojectId ? Number(button.dataset.subprojectId) : null,
      subprojectName: button.dataset.subprojectName || '',
      note: button.dataset.note || '',
      startedAt: new Date().toISOString(),
      accumulatedMs: 0,
      running: true,
      lastTickAt: Date.now(),
      clientToken: makeToken()
    };
    saveState(state);
    if (window.AppModal) window.AppModal.close();
    var content = document.getElementById('schedule-content');
    if (content && content.dataset.tab === 'timer') {
      renderAll();
      if (window.showToast) window.showToast('开始专注', 'success');
      return;
    }
    if (window.htmx) {
      window.htmx.ajax('GET', '/schedule/content?tab=timer', {
        target: '#schedule-content',
        swap: 'outerHTML'
      });
      try {
        window.history.replaceState(null, '', '/schedule?tab=timer');
      } catch (error) {
        /* 忽略浏览器历史限制 */
      }
    } else {
      window.location.href = '/schedule?tab=timer';
    }
    renderAll();
    if (window.showToast) window.showToast('开始专注', 'success');
  }

  function openTimerTab() {
    var content = document.getElementById('schedule-content');
    if (content && content.dataset.tab === 'timer') {
      renderAll();
      return;
    }
    if (window.htmx) {
      window.htmx.ajax('GET', '/schedule/content?tab=timer', {
        target: '#schedule-content',
        swap: 'outerHTML'
      });
      try {
        window.history.replaceState(null, '', '/schedule?tab=timer');
      } catch (error) {
        /* 忽略浏览器历史限制 */
      }
    } else {
      window.location.href = '/schedule?tab=timer';
    }
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function destroyCharts() {
    chartInstances.forEach(function (chart) {
      try {
        chart.destroy();
      } catch (error) {
        /* 图表可能已被 DOM 替换 */
      }
    });
    chartInstances = [];
  }

  function initStatsCharts() {
    var dataEl = document.getElementById('schedule-stats-data');
    if (!dataEl || typeof window.Chart === 'undefined') return;
    var data;
    try {
      data = JSON.parse(dataEl.textContent);
    } catch (error) {
      return;
    }
    destroyCharts();

    var pieEl = document.getElementById('schedule-pie');
    if (pieEl && data.projects && data.projects.length) {
      chartInstances.push(new window.Chart(pieEl, {
        type: 'doughnut',
        data: {
          labels: data.projects.map(function (item) { return item.name; }),
          datasets: [{
            data: data.projects.map(function (item) { return item.hours; }),
            backgroundColor: data.projects.map(function (item) { return item.color; }),
            borderWidth: 0
          }]
        },
        options: {
          maintainAspectRatio: false,
          cutout: '62%',
          plugins: {
            legend: {
              position: 'bottom',
              labels: { boxWidth: 10, usePointStyle: true, color: cssVar('--text') }
            }
          }
        }
      }));
    }

    var barEl = document.getElementById('schedule-bar');
    if (barEl) {
      chartInstances.push(new window.Chart(barEl, {
        type: 'bar',
        data: {
          labels: data.labels || [],
          datasets: [{
            label: '小时',
            data: data.daily || [],
            backgroundColor: cssVar('--accent') || '#0071e3',
            borderRadius: 6,
            maxBarThickness: 26
          }]
        },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { color: cssVar('--muted') } },
            y: {
              beginAtZero: true,
              grid: { color: cssVar('--line') },
              ticks: { color: cssVar('--muted') }
            }
          }
        }
      }));
    }
  }

  function maybeSwitchToDay() {
    var content = document.getElementById('schedule-content');
    if (!content || content.dataset.tab !== 'timeline' || content.dataset.view !== 'week') return;
    if (!window.matchMedia || !window.matchMedia('(max-width: 760px)').matches) return;
    var anchor = content.dataset.anchor;
    if (!anchor || !window.htmx) return;
    var url = '/schedule/content?tab=timeline&view=day&date=' + encodeURIComponent(anchor);
    window.htmx.ajax('GET', url, { target: '#schedule-content', swap: 'outerHTML' });
    try {
      window.history.replaceState(
        null, '',
        '/schedule?tab=timeline&view=day&date=' + encodeURIComponent(anchor)
      );
    } catch (error) {
      /* 忽略浏览器历史限制 */
    }
  }

  document.addEventListener('click', function (event) {
    var startButton = event.target.closest('#timer-start');
    if (startButton) {
      event.preventDefault();
      beginFromInputs();
      return;
    }
    var pauseButton = event.target.closest('#timer-pause');
    if (pauseButton) {
      event.preventDefault();
      pauseTimer();
      return;
    }
    var finishButton = event.target.closest('#timer-finish');
    if (finishButton) {
      event.preventDefault();
      finishTimer();
      return;
    }
    var bannerButton = event.target.closest('#timer-banner-open');
    if (bannerButton) {
      event.preventDefault();
      openTimerTab();
      return;
    }
    var timerTrigger = event.target.closest('[data-timer-start]');
    if (timerTrigger) {
      event.preventDefault();
      startFromDetail(timerTrigger);
      return;
    }
    var slot = event.target.closest('.cal-slot');
    if (slot) {
      event.preventDefault();
      var start = pad(Number(slot.dataset.hour || 9)) + ':00';
      if (window.AppModal) {
        window.AppModal.open(
          '/schedule/tasks/new?date=' + encodeURIComponent(slot.dataset.date) +
            '&start=' + encodeURIComponent(start),
          '新增时间任务'
        );
      }
    }
  });

  document.body.addEventListener('schedule:refresh', refreshContent);

  document.addEventListener('htmx:afterSwap', function (event) {
    renderAll();
    if (event.target && event.target.id === 'schedule-content') {
      initStatsCharts();
      maybeSwitchToDay();
    }
  });

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) renderAll();
  });

  document.addEventListener('DOMContentLoaded', function () {
    startTicker();
    renderAll();
    initStatsCharts();
    maybeSwitchToDay();
  });
})();
