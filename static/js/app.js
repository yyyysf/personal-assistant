(function () {
  'use strict';

  var toastEl = null;
  var toastTimer = null;

  function showToast(message, type) {
    if (!toastEl) toastEl = document.getElementById('toast');
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.className = 'toast show' + (type === 'error' ? ' toast-error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.className = 'toast';
    }, 3200);
  }

  window.showToast = showToast;

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form && form.dataset && form.dataset.confirm) {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }
  }, true);

  document.body.addEventListener('htmx:responseError', function (event) {
    var message = '请求失败，请稍后重试';
    try {
      var payload = JSON.parse(event.detail.xhr.responseText);
      if (payload && payload.message) message = payload.message;
    } catch (err) {
      message = '请求失败（HTTP ' + event.detail.xhr.status + '）';
    }
    showToast(message, 'error');
  });

  document.body.addEventListener('htmx:sendError', function () {
    showToast('网络连接失败，请检查本地服务是否正常', 'error');
  });

  document.body.addEventListener('htmx:timeout', function () {
    showToast('请求超时，任务可能仍在后台执行', 'error');
  });
})();
