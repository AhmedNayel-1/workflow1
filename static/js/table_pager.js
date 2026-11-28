/* ترقيم الصفحات لكل جدول: عدد الصفوف + السابق/التالي. الجداول المرقّمة من الخادم تحتفظ بمحدد الحجم فقط. */
(function () {
  var SIZES = [10, 25, 50, 100], KEY = "tbl-page-size";
  var size = function () { try { var n = parseInt(localStorage.getItem(KEY), 10); return SIZES.indexOf(n) >= 0 ? n : 25; } catch (e) { return 25; } };
  var save = function (n) { try { localStorage.setItem(KEY, String(n)); } catch (e) {} };

  // محدد الحجم في الترقيم القادم من الخادم
  document.addEventListener("change", function (e) {
    var s = e.target.closest && e.target.closest("[data-pg-size]"); if (!s) return;
    var u = new URL(location.href); u.searchParams.set("per_page", s.value); u.searchParams.delete("page"); location.href = u.toString();
  });

  var serverPaged = function (t) {
    var n = t;
    for (var i = 0; i < 5 && n; i++, n = n.parentElement) {
      if (n.parentElement && Array.prototype.some.call(n.parentElement.children, function (c) { return c.classList && c.classList.contains("pager"); })) return true;
    }
    return false;
  };

  function setup(table) {
    var body = table.tBodies[0]; if (!body) return;
    var rows = Array.prototype.filter.call(body.children, function (r) { return r.tagName === "TR" && !r.querySelector("td[colspan]"); });
    if (!rows.length) return;
    var page = 1, per = size();
    var bar = document.createElement("nav"); bar.className = "pager tp-bar"; bar.setAttribute("aria-label", "ترقيم صفحات الجدول");
    bar.innerHTML = '<span data-tp-info></span><label class="pg-size">عدد الصفوف <select data-tp-size aria-label="عدد الصفوف في الصفحة">' +
      SIZES.map(function (n) { return '<option value="' + n + '"' + (n === per ? " selected" : "") + ">" + n + "</option>"; }).join("") +
      '</select></label><div class="pages"><button type="button" class="pg" data-tp-prev aria-label="السابق">›</button><span class="pg on" data-tp-cur>1</span><button type="button" class="pg" data-tp-next aria-label="التالي">‹</button></div>';
    var host = table.closest(".tbl-wrap") || table;
    host.insertAdjacentElement("afterend", bar);
    var busy = false;
    function render() {
      busy = true;
      var vis = rows.filter(function (r) { return !r.hidden; });
      var pages = Math.max(1, Math.ceil(vis.length / per)); if (page > pages) page = pages;
      var from = (page - 1) * per, to = from + per;
      rows.forEach(function (r) { r.classList.remove("tp-off"); });
      vis.forEach(function (r, i) { r.classList.toggle("tp-off", i < from || i >= to); });
      bar.querySelector("[data-tp-info]").textContent = vis.length ? (from + 1) + "–" + Math.min(to, vis.length) + " من " + vis.length : "0";
      bar.querySelector("[data-tp-cur]").textContent = page + " / " + pages;
      bar.querySelector("[data-tp-prev]").disabled = page <= 1; bar.querySelector("[data-tp-next]").disabled = page >= pages;
      bar.hidden = vis.length === 0;
      busy = false;
    }
    bar.addEventListener("click", function (e) {
      if (e.target.closest("[data-tp-prev]")) { page--; render(); }
      if (e.target.closest("[data-tp-next]")) { page++; render(); }
    });
    bar.querySelector("[data-tp-size]").addEventListener("change", function (e) { per = parseInt(e.target.value, 10); save(per); page = 1; render(); });
    var mo = new MutationObserver(function () { if (!busy) { page = 1; render(); } });
    rows.forEach(function (r) { mo.observe(r, { attributes: true, attributeFilter: ["hidden"] }); });
    render();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("table").forEach(function (t) {
      if (t.hasAttribute("data-no-pg") || t.closest("[data-no-pg],dialog") || serverPaged(t)) return;
      setup(t);
    });
  });
})();
