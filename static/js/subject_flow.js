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
      '<div class="af-opts"><label class="on" data-af-o="route"><input type="radio" name="af" checked> أوجّهه لشخص</label><label data-af-o="do"><input type="radio" name="af"> أنفّذه بنفسي</label><label data-af-o="ret" hidden><input type="radio" name="af"> ليس من اختصاصي، أرفضه وأعيده للمحيل</label></div>' +
      '<div class="muted af-why" data-af-why hidden></div>' +
      '<div data-af-ret hidden><label class="af-f">سبب الرفض / الإرجاع (إجباري)<textarea rows="3" data-af-rnotes></textarea></label>' +
      '<div class="af-err" data-af-rerr></div><div class="af-row"><button type="button" class="btn" data-af-close>إلغاء</button><button type="button" class="btn primary" data-af-retdone>إرجاع للمحيل</button></div></div>' +
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
      if (o.can_return) d.querySelector('[data-af-o="ret"]').hidden = false;
    });
    fetch(row.dataset.odRefer + "?partial=1", { credentials: "same-origin" }).then(function (r) { return r.text(); }).then(function (html) {
      rb.innerHTML = html;
      if (!rb.querySelector(".rf-opt")) {
        var ro = d.querySelector('[data-af-o="route"]'); ro.hidden = true;
        var why = d.querySelector("[data-af-why]"); why.hidden = false; why.textContent = "التوجيه لشخص غير متاح لأنه لا يوجد مستلمون متاحون لك.";
        d.querySelector('[data-af-o="do"]').click();
        return;
      }
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
      if (o) { var doit = o.dataset.afO === "do"; d.querySelectorAll("[data-af-o]").forEach(function (x) { x.classList.toggle("on", x === o); }); o.querySelector("input").checked = true; var k = o.dataset.afO; rb.hidden = k !== "route"; db.hidden = k !== "do"; d.querySelector("[data-af-ret]").hidden = k !== "ret"; }
      if (ev.target.closest("[data-af-close]")) d.close();
      if (ev.target.closest("[data-af-retdone]")) {
        var rn = d.querySelector("[data-af-rnotes]").value.trim();
        if (!rn) { d.querySelector("[data-af-rerr]").textContent = "اكتب سبب الإرجاع."; return; }
        var rf = new FormData(); rf.append("mode", "return"); rf.append("notes", rn);
        post("/subjects/" + id + "/action/", rf).then(function (j) { if (j.ok) back(); else d.querySelector("[data-af-rerr]").textContent = j.error || "تعذّر الإرجاع"; });
      }
      if (ev.target.closest("[data-af-done]")) {
        var fd = new FormData(); fd.append("choice_id", sel.value); fd.append("notes", d.querySelector("[data-af-notes]").value);
        Array.prototype.forEach.call(d.querySelector("[data-af-files]").files, function (f) { fd.append("files", f); });
        post("/subjects/" + id + "/action/", fd).then(function (j) { if (j.ok) back(); else showErr(db, j.error); });
      }
    });
  }

  function manage(id) {
    var row = rowOf(id); var title = row ? row.dataset.odTitle : "";
    var d = document.createElement("dialog"); d.className = "af-dlg";
    d.innerHTML = '<h3>سحب / استبدال الإحالة: ' + esc(title) + '</h3><div data-mg-body><p class="muted">جاري التحميل…</p></div>';
    document.body.appendChild(d); d.showModal(); d.addEventListener("close", function () { d.remove(); });
    fetch("/subjects/" + id + "/referrals-manage/", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (o) {
      var b = d.querySelector("[data-mg-body]");
      if (!o.items.length) { b.innerHTML = '<p class="muted">لا توجد إحالات يمكن سحبها أو استبدالها.</p><div class="af-row"><button type="button" class="btn" data-af-close>إغلاق</button></div>'; return; }
      b.innerHTML = '<label class="af-f">الإحالة / المستلم<select data-mg-item>' + o.items.map(function (i) { return '<option value="' + i.recipient_id + '" data-ref="' + i.referral_id + '">' + esc(i.name) + ' (' + esc(i.status) + ')</option>'; }).join("") + '</select></label>' +
        '<div class="af-opts"><label class="on" data-mg-o="withdraw"><input type="radio" name="mg" checked> سحب الإحالة (يعود الموضوع لي)</label>' +
        (o.targets.length ? '<label data-mg-o="replace"><input type="radio" name="mg"> إحالة بديلة لشخص آخر</label>' : '') + '</div>' +
        '<label class="af-f" data-mg-p hidden>الشخص البديل<select data-mg-user>' + o.targets.map(function (t) { return '<option value="' + t.id + '">' + esc(t.name) + '</option>'; }).join("") + '</select></label>' +
        '<label class="af-f">السبب (إجباري)<textarea rows="3" data-mg-reason></textarea></label><div class="af-err" data-mg-err></div>' +
        '<div class="af-row"><button type="button" class="btn" data-af-close>إلغاء</button><button type="button" class="btn primary" data-mg-go>تنفيذ</button></div>';
      var mode = "withdraw";
      b.addEventListener("click", function (ev) {
        var m = ev.target.closest("[data-mg-o]");
        if (m) { mode = m.dataset.mgO; b.querySelectorAll("[data-mg-o]").forEach(function (x) { x.classList.toggle("on", x === m); }); m.querySelector("input").checked = true; b.querySelector("[data-mg-p]").hidden = mode !== "replace"; }
        if (ev.target.closest("[data-mg-go]")) {
          var opt = b.querySelector("[data-mg-item]").selectedOptions[0], reason = b.querySelector("[data-mg-reason]").value.trim();
          var err = b.querySelector("[data-mg-err]");
          if (!reason) { err.textContent = "اكتب السبب."; return; }
          var fd = new FormData(); fd.append("mode", mode); fd.append("reason", reason); fd.append("referral_id", opt.dataset.ref); fd.append("recipient_id", opt.value);
          if (mode === "replace") fd.append("new_user_id", b.querySelector("[data-mg-user]").value);
          post("/subjects/" + id + "/referrals-manage/", fd).then(function (j) { if (j.ok) back(); else err.textContent = j.error || "تعذّر التنفيذ"; });
        }
      });
    });
    d.addEventListener("click", function (ev) { if (ev.target.closest("[data-af-close]")) d.close(); });
  }

  document.addEventListener("click", function (e) {
    var mb = e.target.closest("[data-af-manage]"); if (!mb) return;
    e.stopPropagation(); manage(mb.dataset.afId);
  }, true);

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-af-receive],[data-af-action]"); if (!b) return;
    e.stopPropagation();
    if (b.hasAttribute("data-af-receive")) receive(b.dataset.afId); else action(b.dataset.afId);
  }, true);

  // ملخص الإحالات والملاحظات: عند المرور بالماوس (وعلى اللمس يظهر في اللوحة الجانبية بالضغط)
  var fl = function (e) { return (e.files || []).map(function (f) { return '<a class="fl" href="' + esc(f.url) + '">📎 ' + esc(f.name) + '</a> '; }).join(''); };
  var evTable = function (events) {
    return '<table class="evt"><thead><tr><th>ماذا نُفّذ</th><th>ملاحظات التنفيذ</th><th>من نفّذ</th><th>تاريخ التنفيذ</th></tr></thead><tbody>' +
      events.map(function (e) {
        return '<tr><td>' + esc(e.what) + '</td><td>' + (e.notes ? esc(e.notes) : '<span class="none">—</span>') + (e.files && e.files.length ? '<div>' + fl(e) + '</div>' : '') +
          '</td><td>' + esc(e.who) + (e.role ? '<small>' + esc(e.role) + '</small>' : '') + '</td><td class="dt">' + esc(e.at) + '</td></tr>';
      }).join("") + '</tbody></table>';
  };
  var tip, cache = {}, timer, hideTimer, curRow, shownRow;
  var place = function (row, x) {
    var r = row.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight, vh = innerHeight, gap = 6, m = 8;
    tip.style.maxHeight = ""; tip.style.overflowY = "";
    var below = vh - r.bottom - gap - m, above = r.top - gap - m, top;
    if (h <= below) top = r.bottom + gap;
    else if (h <= above) top = r.top - gap - h;
    else if (h <= vh - 2 * m) top = Math.max(m, Math.min(r.bottom + gap, vh - m - h));
    else { top = m; tip.style.maxHeight = (vh - 2 * m) + "px"; tip.style.overflowY = "auto"; }
    tip.style.top = top + "px";
    tip.style.left = Math.max(m, Math.min(x - w / 2, innerWidth - w - m)) + "px";
  };
  var show = function (id, row, x) {
    var render = function (j) {
      if (!tip) {
        tip = document.createElement("div"); tip.className = "sl-tip"; document.body.appendChild(tip);
        tip.addEventListener("mouseenter", function () { clearTimeout(hideTimer); clearTimeout(timer); curRow = shownRow; });
        tip.addEventListener("mouseleave", function () { hide(); });
      }
      tip.innerHTML = '<h5>ملخص الإجراءات (الأقدم أولاً)</h5>' + (j.events.length ? evTable(j.events) : '<p class="muted">لا توجد إجراءات بعد.</p>');
      shownRow = row; tip.hidden = false; tip.style.visibility = "hidden"; place(row, x); tip.style.visibility = "";
    };
    if (cache[id]) return render(cache[id]);
    fetch("/subjects/" + id + "/timeline-json/", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) { if (j) { cache[id] = j; if (curRow === row) render(j); } });
  };
  var hide = function () { clearTimeout(timer); clearTimeout(hideTimer); hideTimer = setTimeout(function () { if (tip) tip.hidden = true; curRow = null; }, 300); };
  var target = function (e) { return e.target.closest && e.target.closest("[data-subject-row],[data-sl-card]"); };
  document.addEventListener("mouseover", function (e) {
    var t = target(e); if (!t || (e.relatedTarget && t.contains(e.relatedTarget))) return;
    clearTimeout(hideTimer);
    var id = t.dataset.odId || t.dataset.slCard; clearTimeout(timer); curRow = t;
    timer = setTimeout(function () { show(id, t, e.clientX); }, 450);
  });
  document.addEventListener("mouseout", function (e) { var t = target(e); if (t && !(e.relatedTarget && (t.contains(e.relatedTarget) || (tip && tip.contains(e.relatedTarget))))) hide(); });
  document.addEventListener("click", function (e) { if (tip && tip.contains(e.target)) return; clearTimeout(timer); if (tip) tip.hidden = true; curRow = null; });
  // زر «تفاصيل» في السطر يفتح اللوحة الجانبية وفيها سجل الأحداث
  window.__slTimeline = function (id, box) {
    fetch("/subjects/" + id + "/timeline-json/", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (!j) return;
      box.innerHTML = '<h4>ملخص الإجراءات</h4>' + (j.events.length ? evTable(j.events) : '<p class="sl-none">لا توجد إجراءات بعد.</p>');
    });
  };
})();
