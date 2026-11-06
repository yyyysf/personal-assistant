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
    Alpine.data('tagPicker', function (initial, existing, colors) {
      return {
        tags: (initial || '').split(',').map(function (tag) { return tag.trim(); }).filter(Boolean),
        draft: '',
        open: false,
        existing: existing || [],
        colors: colors || {},
        colorFor: function (tag) {
          return this.colors[(tag || '').toLowerCase()] || '#A9C7E8';
        },
        get suggestions() {
          var self = this;
          var query = this.draft.trim().toLowerCase();
          return this.existing.filter(function (tag) {
            if (self.tags.indexOf(tag) !== -1) return false;
            return !query || tag.toLowerCase().indexOf(query) !== -1;
          });
        },
        add: function () {
          var tag = this.draft.trim();
          if (tag) this.tags = [tag];
          this.draft = '';
          this.open = false;
        },
        remove: function (tag) {
          this.tags = this.tags.filter(function (item) { return item !== tag; });
        },
        pick: function (tag) {
          this.tags = [tag];
          this.draft = '';
          this.open = false;
        }
      };
    });

    Alpine.data('tagFilter', function (selected, options, colors) {
      return {
        selected: Array.isArray(selected) ? selected.slice() : [],
        options: options || [],
        colors: colors || {},
        open: false,
        colorFor: function (tag) {
          return this.colors[(tag || '').toLowerCase()] || '#A9C7E8';
        },
        isSelected: function (tag) {
          return this.selected.indexOf(tag) !== -1;
        },
        toggle: function (tag) {
          var index = this.selected.indexOf(tag);
          if (index === -1) this.selected.push(tag);
          else this.selected.splice(index, 1);
        }
      };
    });

    function pad(value) {
      return value < 10 ? '0' + value : String(value);
    }

    function dateString(year, month, day) {
      return year + '-' + pad(month + 1) + '-' + pad(day);
    }

    Alpine.data('calendarField', function (initial, withTime) {
      var raw = initial || '';
      var datePart = raw.length >= 10 ? raw.slice(0, 10) : '';
      var timePart = raw.indexOf('T') > -1 ? raw.slice(11, 16) : '09:00';
      var base = datePart ? new Date(datePart + 'T00:00:00') : new Date();
      var weekdays = ['日', '一', '二', '三', '四', '五', '六'];
      return {
        value: datePart,
        time: timePart,
        withTime: !!withTime,
        open: false,
        viewYear: base.getFullYear(),
        viewMonth: base.getMonth(),
        get hiddenValue() {
          if (!this.value) return '';
          return this.withTime ? this.value + 'T' + this.time : this.value;
        },
        get display() {
          if (!this.value) return '';
          var parts = this.value.split('-');
          var date = new Date(this.value + 'T00:00:00');
          var text = parts[0] + '年' + parseInt(parts[1], 10) + '月' +
            parseInt(parts[2], 10) + '日 周' + weekdays[date.getDay()];
          return this.withTime ? text + ' ' + this.time : text;
        },
        get monthLabel() {
          return this.viewYear + '年' + (this.viewMonth + 1) + '月';
        },
        get weeks() {
          var first = new Date(this.viewYear, this.viewMonth, 1);
          var offset = (first.getDay() + 6) % 7;
          var start = new Date(this.viewYear, this.viewMonth, 1 - offset);
          var now = new Date();
          var today = dateString(now.getFullYear(), now.getMonth(), now.getDate());
          var cells = [];
          for (var i = 0; i < 42; i++) {
            var current = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
            var iso = dateString(current.getFullYear(), current.getMonth(), current.getDate());
            cells.push({
              day: current.getDate(),
              date: iso,
              inMonth: current.getMonth() === this.viewMonth,
              isToday: iso === today,
              isSelected: iso === this.value
            });
          }
          return cells;
        },
        toggle: function () {
          if (!this.open && this.value) {
            var parts = this.value.split('-');
            this.viewYear = parseInt(parts[0], 10);
            this.viewMonth = parseInt(parts[1], 10) - 1;
          }
          this.open = !this.open;
        },
        prevMonth: function () {
          if (this.viewMonth === 0) {
            this.viewMonth = 11;
            this.viewYear -= 1;
          } else {
            this.viewMonth -= 1;
          }
        },
        nextMonth: function () {
          if (this.viewMonth === 11) {
            this.viewMonth = 0;
            this.viewYear += 1;
          } else {
            this.viewMonth += 1;
          }
        },
        select: function (iso) {
          this.value = iso;
          if (!this.withTime) this.open = false;
        },
        pickToday: function () {
          var now = new Date();
          this.value = dateString(now.getFullYear(), now.getMonth(), now.getDate());
          this.viewYear = now.getFullYear();
          this.viewMonth = now.getMonth();
          this.open = false;
        },
        clear: function () {
          this.value = '';
          this.open = false;
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
