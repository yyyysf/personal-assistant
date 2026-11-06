(function () {
  'use strict';

  var dragging = null;

  function clearTargets() {
    document.querySelectorAll('.kanban-body.is-drop-target').forEach(function (zone) {
      zone.classList.remove('is-drop-target');
    });
  }

  function refreshBoard() {
    var content = document.getElementById('todo-content');
    if (!content || !window.htmx) return;
    window.htmx.ajax('GET', content.dataset.refreshUrl, {
      target: '#todo-content',
      swap: 'outerHTML'
    });
  }

  document.addEventListener('dragstart', function (event) {
    if (event.target.closest('button, a, input, select, textarea')) {
      event.preventDefault();
      return;
    }
    var card = event.target.closest('.task-card[data-task-id]');
    if (!card) return;
    dragging = { id: card.dataset.taskId, status: card.dataset.taskStatus };
    card.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', dragging.id);
    }
  });

  document.addEventListener('dragend', function (event) {
    var card = event.target.closest('.task-card');
    if (card) card.classList.remove('is-dragging');
    clearTargets();
  });

  document.addEventListener('dragover', function (event) {
    var zone = event.target.closest('.kanban-body[data-drop-status]');
    if (!zone || !dragging) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    clearTargets();
    if (zone.dataset.dropStatus !== dragging.status) zone.classList.add('is-drop-target');
  });

  document.addEventListener('dragleave', function (event) {
    var zone = event.target.closest('.kanban-body[data-drop-status]');
    if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drop-target');
  });

  document.addEventListener('drop', function (event) {
    var zone = event.target.closest('.kanban-body[data-drop-status]');
    if (!zone || !dragging) return;
    event.preventDefault();
    var status = zone.dataset.dropStatus;
    var current = dragging;
    dragging = null;
    clearTargets();
    if (!status || status === current.status) return;
    fetch('/todo/tasks/' + current.id + '/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'status=' + encodeURIComponent(status)
    }).then(function (response) {
      if (response.ok) refreshBoard();
    });
  });
})();
