(function () {
  'use strict';

  function modalEl() {
    return document.getElementById('app-modal');
  }

  function openModal(url, title) {
    var dialog = modalEl();
    if (!dialog) return;
    var titleEl = document.getElementById('modal-title');
    var body = document.getElementById('modal-body');
    if (titleEl) titleEl.textContent = title || '详情';
    if (body) body.innerHTML = '<div class="modal-loading">加载中…</div>';
    if (!dialog.open) dialog.showModal();
    if (url && window.htmx) {
      window.htmx.ajax('GET', url, { target: '#modal-body', swap: 'innerHTML' });
    }
  }

  function closeModal() {
    var dialog = modalEl();
    if (dialog && dialog.open) dialog.close();
  }

  window.AppModal = { open: openModal, close: closeModal };

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-modal-url]');
    if (trigger) {
      event.preventDefault();
      openModal(trigger.dataset.modalUrl, trigger.dataset.modalTitle);
      return;
    }
    var card = event.target.closest('[data-detail-url]');
    if (card && !event.target.closest('a, button, form, input, select, textarea, label')) {
      event.preventDefault();
      openModal(card.dataset.detailUrl, card.dataset.detailTitle || '详情');
      return;
    }
    if (event.target.closest('[data-modal-close]')) closeModal();
  });

  document.addEventListener('DOMContentLoaded', function () {
    var dialog = modalEl();
    if (!dialog) return;
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) closeModal();
    });
    dialog.addEventListener('close', function () {
      var body = document.getElementById('modal-body');
      if (body) body.innerHTML = '';
    });
  });

  document.body.addEventListener('modal:close', closeModal);

  document.body.addEventListener('list:refresh', function () {
    var el = document.querySelector('[data-refresh-url]');
    if (el && window.htmx) {
      window.htmx.ajax('GET', el.dataset.refreshUrl, { target: '#' + el.id, swap: 'outerHTML' });
    }
  });

  document.addEventListener('change', function (event) {
    var input = event.target.closest('[data-image-input]');
    if (!input) return;
    var preview = document.querySelector(input.dataset.imageInput);
    if (!preview) return;
    preview.innerHTML = '';
    Array.prototype.slice.call(input.files || []).forEach(function (file) {
      if (!file.type || file.type.indexOf('image/') !== 0) return;
      var reader = new FileReader();
      reader.onload = function () {
        var img = document.createElement('img');
        img.className = 'image-thumb';
        img.src = reader.result;
        preview.appendChild(img);
      };
      reader.readAsDataURL(file);
    });
  });

  document.addEventListener('alpine:init', function () {
    Alpine.data('tagPicker', function (initial, existing) {
      return {
        tags: (initial || '').split(',').map(function (tag) { return tag.trim(); }).filter(Boolean),
        draft: '',
        existing: existing || [],
        get suggestions() {
          var self = this;
          return this.existing.filter(function (tag) { return self.tags.indexOf(tag) === -1; });
        },
        add: function () {
          var tag = this.draft.trim();
          if (tag && this.tags.indexOf(tag) === -1) this.tags.push(tag);
          this.draft = '';
        },
        remove: function (tag) {
          this.tags = this.tags.filter(function (item) { return item !== tag; });
        },
        toggle: function (tag) {
          if (this.tags.indexOf(tag) === -1) this.tags.push(tag);
        }
      };
    });

    Alpine.data('datePicker', function (mode, modes) {
      return {
        mode: mode || 'deadline',
        modes: modes || ['deadline', 'single', 'range']
      };
    });

    Alpine.data('urlList', function (initial) {
      var urls = Array.isArray(initial) ? initial.slice() : [];
      if (!urls.length) urls = [''];
      return {
        urls: urls,
        add: function () { this.urls.push(''); },
        remove: function (index) {
          this.urls.splice(index, 1);
          if (!this.urls.length) this.urls.push('');
        }
      };
    });
  });
})();
