/* استلام ثم إجراء من سطر الجدول، وملخص الأحداث عند المرور أو اللمس. */
(function () {
  var csrf = function () { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ""; };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var post = function (url, fd) { return fetch(url, { method: "POST", body: fd, credentials: "same-origin", headers: { "X-CSRFToken": csrf() } }).then(function (r) { return r.json().catch(function () { return { ok: false, error: "تعذّر التنفيذ" }; }); }); };
  var rowOf = function (id) { return document.querySelector('[data-subject-row][data-od-id="' + id + '"]'); };
  var back = function () { location.reload(); };

  function receive(id) {
    var row = rowOf(id); if (!row) return;
    var fd = new FormData(); fd.append("action", "acknowledge"); 
    fetch(row.dataset.odRespond, { method: "POST", body: fd, credentials: "same-origin", headers: { "X-CSRFToken": csrf() }, redirect: "follow" })
      .then(function () { back(id); });
  }

  function action(id) {
    var row = rowOf(id); if (!row) return;
    var d = document.createElement("dialog"); d.className = "af-dlg";
    d.innerHTML = '<h3>إجراء على: ' + esc(row.dataset.odTitle) + '</h3>' +
      '<div class="af-opts"><label class="on" data-af-o="route"><input type="radio" name="af" checked> أوجّهه لشخص</label><label data-af-o="do"><input type="radio" name="af"> أنفّذه بنفسي</label></div>' +
      '<div data-af-route><p class="muted">جاري التحميل…</p></div>' +
      '<div data-af-do hidden><label class="af-f">ماذا نفّذت؟<select data-af-choice></select></label>' +
      '<label class="af-f">ملاحظات التنفيذ<textarea rows="3" data-af-notes></textarea></label>' +
      '<label class="af-f">مرفقات (اختياري)<input type="file" multiple data-af-files></label>' +
      '<div class="af-err" data-af-err></div><div class="af-row"><button type="button" class="btn" data-af-close>إلغاء</button><button type="button" class="btn primary" data-af-done>تأكيد التنفيذ</button></div></div>';
    document.body.appendChild(d); d.showModal();
    d.addEventListener("close", function () { d.remove(); });
    var rb = d.querySelector("[data-af-route]"), db = d.querySelector("[data-af-do]"), sel = d.querySelector("[data-af-choice]");
    fetch("/subjects/" + id + "/action-options/", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (o) {
      sel.innerHTML = o.choices.map(function (c) { return '<option value="' + c.id + '">' + esc(c.name) + '</option>'; }).join("");
    });
    fetch(row.dataset.odRefer + "?partial=1", { credentials: "same-origin" }).then(function (r) { return r.text(); }).then(function (html) {
      rb.innerHTML = html;
      rb.querySelectorAll("script").forEach(function (s) { var n = document.createElement("script"); n.textContent = s.textContent; s.replaceWith(n); });
      var form = rb.querySelector("form");
      if (form) form.addEventListener("submit", function (ev) {
        ev.preventDefault(); ev.stopImmediatePropagation();
        var fd = new FormData(form); fd.set("mode", "route");
        post("/subjects/" + id + "/action/", fd).then(function (j) { if (j.ok) back(); else showErr(rb, j.error); });
      }, true);
      var c = rb.querySelector("[data-rf-cancel]"); if (c) c.addEventListener("click", function (ev) { ev.preventDefault(); d.close(); });
    });
    function showErr(scope, msg) {
      var e = scope.querySelector(".af-err"); if (!e) { e = document.createElement("div"); e.className = "af-err"; scope.appendChild(e); }
      e.textContent = msg || "تعذّر التنفيذ";
    }
    d.addEventListener("click", function (ev) {
      var o = ev.target.closest("[data-af-o]");
      if (o) { var doit = o.dataset.afO === "do"; d.querySelectorAll("[data-af-o]").forEach(function (x) { x.classList.toggle("on", x === o); }); o.querySelector("input").checked = true; rb.hidden = doit; db.hidden = !doit; }
      if (ev.target.closest("[data-af-close]")) d.close();
      if (ev.target.closest("[data-af-done]")) {
        var fd = new FormData(); fd.append("choice_id", sel.value); fd.append("notes", d.querySelector("[data-af-notes]").value);
        Array.prototype.forEach.call(d.querySelector("[data-af-files]").files, function (f) { fd.append("files", f); });
        post("/subjects/" + id + "/action/", fd).then(function (j) { if (j.ok) back(); else showErr(db, j.error); });
      }
    });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-af-receive],[data-af-action]"); if (!b) return;
    e.stopPropagation();
    if (b.hasAttribute("data-af-receive")) receive(b.dataset.afId); else action(b.dataset.afId);
  }, true);

  // ملخص الإحالات والملاحظات: عند المرور بالماوس (وعلى اللمس يظهر في اللوحة الجانبية بالضغط)
  var fl = function (e) { return (e.files || []).map(function (f) { return '<p class="fl">📎 <a href="' + esc(f.url) + '">' + esc(f.name) + '</a></p>'; }).join(''); };
  var tip, cache = {}, timer;
  var show = function (id, x, y) {
    var render = function (j) {
      if (!tip) { tip = document.createElement("div"); tip.className = "sl-tip"; document.body.appendChild(tip); }
      tip.innerHTML = '<h5>ملخص الإجراءات</h5>' + (j.events.length ? j.events.map(function (e) { return '<div class="ev"><b>' + esc(e.what) + '</b><small>' + esc(e.who) + ' · ' + esc(e.at) + '</small>' + (e.notes ? '<p>' + esc(e.notes) + '</p>' : '') + fl(e) + '</div>'; }).join("") : '<p class="muted">لا توجد إجراءات بعد.</p>');
      tip.style.left = Math.max(8, Math.min(x, innerWidth - 360)) + "px"; var top = Math.min(y + 16, innerHeight - 220); tip.style.top = top + "px"; tip.style.maxHeight = (innerHeight - top - 12) + "px"; tip.style.overflowY = "auto"; tip.hidden = false;
    };
    if (cache[id]) return render(cache[id]);
    fetch("/subjects/" + id + "/timeline-json/", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { if (j) { cache[id] = j; render(j); } });
  };
  var hide = function () { clearTimeout(timer); if (tip) tip.hidden = true; };
  var target = function (e) { var t = e.target.closest && e.target.closest("[data-subject-row],[data-sl-card]"); return t; };
  document.addEventListener("mouseover", function (e) {
    var t = target(e); if (!t || (e.relatedTarget && t.contains(e.relatedTarget))) return;
    var id = t.dataset.odId || t.dataset.slCard; clearTimeout(timer);
    timer = setTimeout(function () { show(id, e.clientX, e.clientY); }, 450);
  });
  document.addEventListener("mouseout", function (e) { var t = target(e); if (t && !(e.relatedTarget && t.contains(e.relatedTarget))) hide(); });
  document.addEventListener("click", hide);
  // زر «تفاصيل» في السطر يفتح اللوحة الجانبية وفيها سجل الأحداث
  window.__slTimeline = function (id, box) {
    fetch("/subjects/" + id + "/timeline-json/", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (!j) return;
      box.innerHTML = '<h4>ملخص الإجراءات</h4>' + (j.events.length ? j.events.map(function (e) { return '<div class="ev"><b>' + esc(e.what) + '</b><small>' + esc(e.who) + ' · ' + esc(e.at) + '</small>' + (e.notes ? '<p>' + esc(e.notes) + '</p>' : '') + fl(e) + '</div>'; }).join("") : '<p class="sl-none">لا توجد إجراءات بعد.</p>');
    });
  };
})();
