/* odoo.js — سلوك التنقل والتفاعل فقط. بلا مكتبات. RTL-aware.
   يعتمد على data-attributes ولا يمس أي id/name/hook موجود في المشروع.

   العقود (HTML):
   - قائمة: .ox-menu > button.ox-menu-btn + .ox-dropdown > .ox-dropdown-item
   - tooltip: [data-ox-tip="نص"]
   - تبويبات: [data-ox-notebook] > [role=tab][aria-controls] + [role=tabpanel]
   - نافذة: [data-ox-dialog-open="id"] / .ox-overlay#id / [data-ox-dialog-close]
   - قائمة سجلات: <table data-ox-list="subjects"> و <tr data-ox-row data-id="5" data-href="/subjects/5/">
   - سجل: <main data-ox-record data-ox-list-key="subjects" data-id="5">
        [data-ox-back] رابط الرجوع، [data-ox-prev] [data-ox-next] أزرار، [data-ox-pager-text] النص
   - API: OxUI.notify({type,title,message,sticky}), OxUI.openDialog(id), OxUI.closeDialog(id)
*/
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var isRtl = function () { return getComputedStyle(document.documentElement).direction === 'rtl'; };
  var store = {
    get: function (k) { try { return JSON.parse(sessionStorage.getItem(k)); } catch (e) { return null; } },
    set: function (k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };

  /* ---------- القوائم المنسدلة ---------- */
  function setOpen(menu, open) {
    menu.classList.toggle('open', open);
    var b = $('.ox-menu-btn', menu);
    if (b) b.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function closeMenus(except) {
    $$('.ox-menu.open').forEach(function (m) { if (m !== except) setOpen(m, false); });
  }
  function openMenu(menu) { closeMenus(menu); setOpen(menu, true); }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.ox-menu-btn');
    if (btn) {
      var m = btn.closest('.ox-menu');
      if (m.classList.contains('open')) closeMenus(); else openMenu(m);
      return;
    }
    if (!e.target.closest('.ox-dropdown')) closeMenus();
    else if (e.target.closest('.ox-dropdown-item')) closeMenus();
  });
  /* عند وجود قائمة مفتوحة: المرور على قائمة مجاورة يفتحها */
  document.addEventListener('mouseover', function (e) {
    var btn = e.target.closest('.ox-menu-btn');
    if (!btn || !$('.ox-menu.open')) return;
    var m = btn.closest('.ox-menu');
    if (!m.classList.contains('open')) openMenu(m);
  });
  document.addEventListener('keydown', function (e) {
    var openM = $('.ox-menu.open');
    var btn = e.target.closest && e.target.closest('.ox-menu-btn');
    if (e.key === 'Escape' && openM) {
      var b = $('.ox-menu-btn', openM); closeMenus(); if (b) b.focus(); return;
    }
    if (btn) {
      var menus = $$('.ox-menu'), idx = menus.indexOf(btn.closest('.ox-menu'));
      var next = isRtl() ? 'ArrowLeft' : 'ArrowRight', prev = isRtl() ? 'ArrowRight' : 'ArrowLeft';
      var target = null;
      if (e.key === next) target = menus[(idx + 1) % menus.length];
      if (e.key === prev) target = menus[(idx - 1 + menus.length) % menus.length];
      if (target) { e.preventDefault(); var wasOpen = !!openM; if (wasOpen) openMenu(target); $('.ox-menu-btn', target).focus(); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); openMenu(btn.closest('.ox-menu')); var f = $('.ox-dropdown-item', btn.closest('.ox-menu')); if (f) f.focus(); return; }
    }
    if (openM && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && e.target.closest('.ox-dropdown')) {
      e.preventDefault();
      var items = $$('.ox-dropdown-item', openM), i = items.indexOf(document.activeElement);
      i = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
      items[i].focus();
    }
  });

  /* ---------- Tooltip ---------- */
  var tip = null;
  function showTip(el) {
    hideTip();
    var text = el.getAttribute('data-ox-tip'); if (!text) return;
    tip = document.createElement('div'); tip.className = 'ox-tooltip'; tip.setAttribute('role', 'tooltip'); tip.textContent = text;
    document.body.appendChild(tip);
    var r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    var left = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8);
    var top = r.top - t.height - 8; if (top < 8) top = r.bottom + 8;
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  function hideTip() { if (tip) { tip.remove(); tip = null; } }
  document.addEventListener('mouseover', function (e) { var el = e.target.closest('[data-ox-tip]'); if (el) showTip(el); });
  document.addEventListener('mouseout', function (e) { if (e.target.closest('[data-ox-tip]')) hideTip(); });
  document.addEventListener('focusin', function (e) { var el = e.target.closest('[data-ox-tip]'); if (el) showTip(el); });
  document.addEventListener('focusout', hideTip);

  /* ---------- Toast ---------- */
  function notify(o) {
    o = o || {};
    var box = $('.ox-toasts');
    if (!box) { box = document.createElement('div'); box.className = 'ox-toasts'; box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
    var t = document.createElement('div');
    t.className = 'ox-toast ' + (o.type || 'warning'); t.setAttribute('role', 'alert');
    var b = document.createElement('b'); b.textContent = o.title || '';
    var p = document.createElement('span'); p.textContent = o.message || '';
    var x = document.createElement('button'); x.type = 'button'; x.className = 'ox-toast-close'; x.setAttribute('aria-label', 'إغلاق'); x.textContent = '×';
    x.addEventListener('click', function () { t.remove(); });
    t.appendChild(b); t.appendChild(p); t.appendChild(x); box.appendChild(t);
    if (!o.sticky) setTimeout(function () { t.remove(); }, o.timeout || 5000);
    return t;
  }

  /* ---------- Dialog ---------- */
  var lastFocus = null;
  function focusables(root) { return $$('a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])', root); }
  function openDialog(id) {
    var ov = document.getElementById(id); if (!ov) return;
    lastFocus = document.activeElement; ov.hidden = false;
    var f = focusables(ov); if (f.length) f[0].focus();
  }
  function closeDialog(id) {
    var ov = id ? document.getElementById(id) : $('.ox-overlay:not([hidden])');
    if (!ov) return; ov.hidden = true; if (lastFocus) lastFocus.focus();
  }
  document.addEventListener('click', function (e) {
    var o = e.target.closest('[data-ox-dialog-open]'); if (o) { openDialog(o.getAttribute('data-ox-dialog-open')); return; }
    if (e.target.closest('[data-ox-dialog-close]')) { var ov = e.target.closest('.ox-overlay'); closeDialog(ov && ov.id); return; }
    if (e.target.classList && e.target.classList.contains('ox-overlay') && !e.target.hasAttribute('data-ox-static')) closeDialog(e.target.id);
  });
  document.addEventListener('keydown', function (e) {
    var ov = $('.ox-overlay:not([hidden])'); if (!ov) return;
    if (e.key === 'Escape') { closeDialog(ov.id); return; }
    if (e.key === 'Tab') {
      var f = focusables(ov); if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  /* ---------- Notebook ---------- */
  $$('[data-ox-notebook]').forEach(function (nb) {
    var tabs = $$('[role=tab]', nb);
    function select(tab) {
      tabs.forEach(function (t) {
        var on = t === tab; t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1;
        var p = document.getElementById(t.getAttribute('aria-controls')); if (p) p.hidden = !on;
      });
    }
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { select(t); });
      t.addEventListener('keydown', function (e) {
        var n = isRtl() ? 'ArrowLeft' : 'ArrowRight', p = isRtl() ? 'ArrowRight' : 'ArrowLeft', j = null;
        if (e.key === n) j = (i + 1) % tabs.length; if (e.key === p) j = (i - 1 + tabs.length) % tabs.length;
        if (j !== null) { e.preventDefault(); select(tabs[j]); tabs[j].focus(); }
      });
    });
    select(tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0]);
  });

  /* ---------- حفظ حالة القائمة + تنقل السجلات ---------- */
  var KEY = 'ox:list:';
  var list = $('[data-ox-list]');
  if (list) {
    var key = list.getAttribute('data-ox-list');
    var saved = store.get(KEY + key);
    if (saved && saved.url === location.pathname + location.search && typeof saved.y === 'number') {
      requestAnimationFrame(function () { window.scrollTo(0, saved.y); });
    }
    list.addEventListener('click', function (e) {
      var row = e.target.closest('[data-ox-row]'); if (!row) return;
      if (e.target.closest('input,button,select,textarea,label')) return;
      store.set(KEY + key, {
        url: location.pathname + location.search, y: window.scrollY,
        rows: $$('[data-ox-row]', list).map(function (r) { return { id: r.getAttribute('data-id'), href: r.getAttribute('data-href') }; })
      });
      var a = e.target.closest('a[href]');
      if (!a && row.getAttribute('data-href')) location.href = row.getAttribute('data-href');
    });
  }
  var rec = $('[data-ox-record]');
  if (rec) {
    var st = store.get(KEY + rec.getAttribute('data-ox-list-key'));
    var id = rec.getAttribute('data-id');
    var back = $('[data-ox-back]'); if (back && st && st.url) back.setAttribute('href', st.url);
    var idx = st && st.rows ? st.rows.findIndex(function (r) { return r.id === id; }) : -1;
    var txt = $('[data-ox-pager-text]'), prev = $('[data-ox-prev]'), next = $('[data-ox-next]');
    if (idx > -1) {
      if (txt) txt.textContent = (idx + 1) + ' / ' + st.rows.length;
      var setBtn = function (el, row) {
        if (!el) return;
        if (row) { el.setAttribute('href', row.href); el.removeAttribute('aria-disabled'); }
        else { el.removeAttribute('href'); el.setAttribute('aria-disabled', 'true'); }
      };
      /* في RTL: "السابق" هو السجل الأسبق في الترتيب، بغض النظر عن اتجاه السهم */
      setBtn(prev, st.rows[idx - 1]); setBtn(next, st.rows[idx + 1]);
    } else {
      if (txt) txt.textContent = '1 / 1';
      [prev, next].forEach(function (el) { if (el) { el.removeAttribute('href'); el.setAttribute('aria-disabled', 'true'); } });
    }
  }

  window.OxUI = { notify: notify, openDialog: openDialog, closeDialog: closeDialog };
})();
