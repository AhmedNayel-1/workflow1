/* اختيار الخط: يُحفظ في localStorage فقط (المفتاح ox-font). التطبيق قبل الرسم يتم بسكربت صغير في head. */
(function () {
  'use strict';
  var sel = document.querySelector('[data-ox-font-select]');
  if (!sel) return;
  var cur = '';
  try { cur = localStorage.getItem('ox-font') || ''; } catch (e) {}
  sel.value = cur;
  sel.addEventListener('change', function () {
    var v = sel.value;
    if (v) document.documentElement.setAttribute('data-ox-font', v);
    else document.documentElement.removeAttribute('data-ox-font');
    try { if (v) localStorage.setItem('ox-font', v); else localStorage.removeItem('ox-font'); } catch (e) {}
  });
})();
