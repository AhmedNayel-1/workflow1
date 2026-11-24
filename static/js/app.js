/* app.js — منطق الواجهة الجديدة (مكتوب من الصفر). لا يعتمد على أي مكتبة. */
(() => {
  "use strict";
  window.UI_VERSION = 4;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const on = (el, ev, fn, opt) => el && el.addEventListener(ev, fn, opt);
  const cookie = (n) => (document.cookie.match(new RegExp("(?:^|; )" + n + "=([^;]*)")) || [])[1] || "";
  const csrf = () => { const m = document.querySelector('meta[name="csrf-token"]'); return (m && m.content) || decodeURIComponent(cookie("csrftoken")); };
  const store = { get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };

  /** بناء عناصر DOM آمنة (textContent فقط) */
  const h = (tag, attrs, ...kids) => {
    const el = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    kids.flat().forEach((c) => { if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : document.createTextNode(c)); });
    return el;
  };
  const api = async (url, opts = {}) => {
    const o = { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" }, ...opts };
    if (o.method && o.method !== "GET") o.headers["X-CSRFToken"] = csrf();
    const r = await fetch(url, o);
    if (!r.ok) { let m = "تعذّر تنفيذ الطلب."; try { m = (await r.json()).error || m; } catch (e) {} throw new Error(m); }
    return r.json();
  };
  const postJSON = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" }, body: JSON.stringify(body) });

  /* ---------------- الإشعارات المنبثقة ---------------- */
  window.toast = (text, type = "info") => {
    const box = $("#toasts"); if (!box) return;
    const t = h("div", { class: "toast " + type, role: type === "error" ? "alert" : "status" }, h("div", { text }), h("button", { class: "x", type: "button", "aria-label": "إغلاق", text: "×" }));
    box.append(t);
    const rm = () => { t.classList.add("out"); setTimeout(() => t.remove(), 260); };
    on($(".x", t), "click", rm);
    if (type !== "error") setTimeout(rm, 6500);
  };

  /* ---------------- النوافذ والأدراج ---------------- */
  const openOv = (id) => { const o = document.getElementById(id); if (!o) return; o.classList.add("open"); const f = $("[autofocus],input:not([type=hidden]):not([type=checkbox]),textarea", o); if (f && !o.dataset.nofocus) setTimeout(() => f.focus(), 40); document.dispatchEvent(new CustomEvent("ov:open", { detail: id })); };
  const closeOv = (o) => { o && o.classList.remove("open"); };
  const openDr = (id) => { $$(".drawer.open").forEach((d) => d.classList.remove("open")); const d = document.getElementById(id); if (!d) return; d.classList.add("open"); $("#scrim").classList.add("open"); document.dispatchEvent(new CustomEvent("dr:open", { detail: id })); };
  const closeDr = () => { $$(".drawer.open").forEach((d) => d.classList.remove("open")); $("#scrim") && $("#scrim").classList.remove("open"); document.dispatchEvent(new CustomEvent("dr:close")); };
  window.openOverlay = openOv;

  /* ---------------- تأكيد الإجراءات ---------------- */
  let confirmCb = null;
  const askConfirm = (msg, cb, danger) => {
    $("#confirm-msg").textContent = msg || "هل أنت متأكد؟";
    const ok = $("#confirm-ok"); ok.className = "btn " + (danger ? "bad" : "primary");
    confirmCb = cb; openOv("confirm");
  };

  /* ---------------- التفويض العام للنقرات ---------------- */
  document.addEventListener("click", (e) => {
    const t = e.target;
    let el;
    if ((el = t.closest("[data-open]"))) { e.preventDefault(); closeDr(); openOv(el.dataset.open); return; }
    if ((el = t.closest("[data-close]"))) { e.preventDefault(); closeOv(el.closest(".overlay")); if (el.closest(".drawer")) closeDr(); return; }
    if (t.classList.contains("overlay") && !t.dataset.sticky) closeOv(t);
    if ((el = t.closest("[data-drawer]"))) { e.preventDefault(); openDr(el.dataset.drawer); return; }
    if (t.id === "scrim") closeDr();
    if ((el = t.closest("[data-jump]"))) { e.preventDefault(); jump(el.dataset.jump); return; }
    if ((el = t.closest("[data-copy]"))) { navigator.clipboard && navigator.clipboard.writeText(el.dataset.copy); toast("تم النسخ", "success"); return; }
    if ((el = t.closest("[data-theme-toggle]"))) { const d = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = d; store.set("theme", d); return; }
    if ((el = t.closest("[data-rail-toggle]"))) { const s = $(".shell"); if (innerWidth <= 1000) { $(".rail").classList.toggle("open"); $("#scrim").classList.toggle("open", $(".rail").classList.contains("open")); } else { s.classList.toggle("collapsed"); store.set("rail", s.classList.contains("collapsed")); } return; }
    if ((el = t.closest("[data-pop]"))) { e.preventDefault(); e.stopPropagation(); const p = document.getElementById(el.dataset.pop); const was = !p.hidden; $$(".pop").forEach((x) => (x.hidden = true)); p.hidden = was; return; }
    if (!t.closest(".pop")) $$(".pop").forEach((x) => (x.hidden = true));
    if (t.closest("#scrim,.drawer [data-close]") && $(".rail.open")) { $(".rail").classList.remove("open"); }
    if ((el = t.closest("[data-confirm]")) && el.tagName !== "FORM") {
      if (el.dataset.ok === "1") { el.dataset.ok = ""; return; }
      if (el.closest("form") && el.closest("form").dataset.ok === "1") return;
      e.preventDefault(); e.stopImmediatePropagation();
      askConfirm(el.dataset.confirm, () => { const f = el.closest("form"); if (el.type === "submit" && f) { f.dataset.ok = "1"; f.requestSubmit ? f.requestSubmit(el) : f.submit(); } else { el.dataset.ok = "1"; el.click(); } }, el.dataset.danger !== undefined);
      return;
    }
    if (t.id === "confirm-ok") { const cb = confirmCb; confirmCb = null; closeOv($("#confirm")); cb && cb(); }
  }, true);
  on(document, "keydown", (e) => {
    if (e.key === "Escape") { const o = $$(".overlay.open").pop(); if (o) closeOv(o); else closeDr(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); toggleCmdk(); return; }
    const typing = /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.target.isContentEditable;
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); toggleCmdk(true); }
    else if (e.key.toLowerCase() === "n" && $("#compose")) { e.preventDefault(); wz.open("document"); }
  });

  on(document, "submit", (e) => {
    const f = e.target;
    if (f.dataset.ok === "1") { f.dataset.ok = ""; return; }
    if (f.dataset.confirm) { e.preventDefault(); askConfirm(f.dataset.confirm, () => { f.dataset.ok = "1"; f.requestSubmit ? f.requestSubmit() : f.submit(); }, f.dataset.danger !== undefined); }
  }, true);

  /* ---------------- القفز بين الأقسام ---------------- */
  function jump(id) {
    const el = document.getElementById(id); if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    const pane = el.closest("[data-pane]"); if (pane) activateTab(pane.closest("[data-tabs-root]") || document, pane.dataset.pane);
    const d = $("details", el); if (d && !d.open) d.open = true;
    const f = $("form input:not([type=hidden]):not([type=checkbox]),form select,form textarea", el);
    if (f) setTimeout(() => { try { f.focus({ preventScroll: true }); } catch (e) {} }, 450);
    $$(".subnav a").forEach((a) => a.classList.toggle("on", a.dataset.jump === id));
  }

  /* ---------------- التبويبات ---------------- */
  function activateTab(root, name) {
    $$("[data-tab]", root).forEach((b) => { const on_ = b.dataset.tab === name; b.classList.toggle("on", on_); b.setAttribute("aria-selected", on_); });
    $$("[data-pane]", root).forEach((p) => p.classList.toggle("on", p.dataset.pane === name));
  }
  function initTabs() {
    $$("[data-tabs-root]").forEach((root) => {
      const first = $("[data-tab]", root); if (!first) return;
      const hash = location.hash.replace("#", "");
      const names = $$("[data-tab]", root).map((b) => b.dataset.tab);
      activateTab(root, names.includes(hash) ? hash : (root.dataset.default || first.dataset.tab));
      on(root, "click", (e) => { const b = e.target.closest("[data-tab]"); if (!b || b.closest("[data-tabs-root]") !== root) return; e.preventDefault(); activateTab(root, b.dataset.tab); if (root.dataset.hash !== undefined) history.replaceState(null, "", "#" + b.dataset.tab); });
    });
  }

  /* ---------------- الجداول: تحديد جماعي + تصفية فورية + تصدير ---------------- */
  function initTables() {
    $$("[data-table]").forEach((wrap) => {
      const all = $("[data-all]", wrap), bulk = $(".bulk", wrap), cnt = $("[data-count]", wrap);
      const rows = () => $$("tbody tr", wrap).filter((r) => $(".row-chk", r));
      const refresh = () => {
        const sel = rows().filter((r) => $(".row-chk", r).checked);
        rows().forEach((r) => r.classList.toggle("sel", $(".row-chk", r).checked));
        if (bulk) bulk.classList.toggle("show", sel.length > 0);
        if (cnt) cnt.textContent = sel.length;
        if (all) all.checked = sel.length && sel.length === rows().filter((r) => !r.hidden).length;
      };
      on(wrap, "change", (e) => { if (e.target === all) rows().forEach((r) => { if (!r.hidden) $(".row-chk", r).checked = all.checked; }); if (e.target === all || e.target.classList.contains("row-chk")) refresh(); });
      on($("[data-clear]", wrap), "click", () => { rows().forEach((r) => ($(".row-chk", r).checked = false)); refresh(); });
      on($("[data-export]", wrap), "click", () => {
        const head = $$("thead th", wrap).slice(1).map((th) => th.textContent.trim());
        const data = rows().filter((r) => $(".row-chk", r).checked).map((r) => $$("td", r).slice(1).map((td) => '"' + td.textContent.replace(/\s+/g, " ").trim().replace(/"/g, '""') + '"').join(","));
        const blob = new Blob(["\ufeff" + head.join(",") + "\n" + data.join("\n")], { type: "text/csv;charset=utf-8" });
        const a = h("a", { href: URL.createObjectURL(blob), download: "export.csv" }); document.body.append(a); a.click(); a.remove();
      });
      const q = $("[data-filter]", wrap);
      on(q, "input", () => { const v = q.value.trim(); rows().concat($$("tbody tr", wrap).filter((r) => !$(".row-chk", r))).forEach((r) => (r.hidden = !!v && !r.textContent.includes(v))); refresh(); });
    });
    $$("form[data-auto]").forEach((f) => on(f, "change", (e) => { if (e.target.matches("select,input[type=date],input[type=checkbox]")) f.requestSubmit ? f.requestSubmit() : f.submit(); }));
  }

  /* ---------------- لوحة الأوامر Ctrl+K ---------------- */
  let cmd = { items: [], shown: [], sel: 0 };
  function toggleCmdk(force) {
    const o = $("#cmdk"); if (!o) return;
    if (o.classList.contains("open") && force !== true) { closeOv(o); return; }
    cmd.items = [{ g: "إجراءات", t: "إنشاء موضوع جديد", k: "N", run: () => wz.open("document") }, { g: "إجراءات", t: "إرسال مراسلة سريعة", run: () => wz.open("message") },
      { g: "إجراءات", t: "التنبيهات", run: () => openDr("dr-notif") }, { g: "إجراءات", t: "المحادثات", run: () => openDr("dr-chat") }, { g: "إجراءات", t: "تبديل المظهر (فاتح/داكن)", run: () => $("[data-theme-toggle]").click() }]
      .concat($$(".rail .nav").map((a) => ({ g: (a.closest("[data-cap]") || {}).dataset ? a.closest("[data-cap]").dataset.cap : "التنقل", t: a.dataset.label || a.textContent.trim(), href: a.getAttribute("href") })));
    openOv("cmdk"); const i = $("#cmdk-in"); i.value = ""; renderCmd(""); i.focus();
  }
  function renderCmd(q) {
    const L = $("#cmdk-l"); q = q.trim();
    cmd.shown = cmd.items.filter((x) => !q || x.t.includes(q));
    if (q) cmd.shown.push({ g: "بحث", t: "ابحث في الأرشيف عن «" + q + "»", href: $("#cmdk").dataset.search + "?q=" + encodeURIComponent(q) });
    cmd.sel = 0; L.textContent = "";
    if (!cmd.shown.length) { L.append(h("div", { class: "empty", text: "لا نتائج" })); return; }
    let last = null;
    cmd.shown.forEach((x, i) => { if (x.g !== last) { L.append(h("div", { class: "cmdk-g", text: x.g })); last = x.g; } L.append(h("div", { class: "cmdk-i" + (i === 0 ? " sel" : ""), role: "option", onclick: () => runCmd(x) }, h("span", { text: x.t }), x.k ? h("span", { class: "kbd", text: x.k }) : null)); });
  }
  function runCmd(x) { closeOv($("#cmdk")); x.run ? x.run() : (location.href = x.href); }
  function initCmdk() {
    const i = $("#cmdk-in"); if (!i) return;
    on(i, "input", () => renderCmd(i.value));
    on(i, "keydown", (e) => {
      const rows = $$(".cmdk-i"); if (!rows.length) return;
      const mv = (d) => { rows[cmd.sel].classList.remove("sel"); cmd.sel = (cmd.sel + d + rows.length) % rows.length; rows[cmd.sel].classList.add("sel"); rows[cmd.sel].scrollIntoView({ block: "nearest" }); };
      if (e.key === "ArrowDown") { e.preventDefault(); mv(1); } else if (e.key === "ArrowUp") { e.preventDefault(); mv(-1); } else if (e.key === "Enter") { e.preventDefault(); runCmd(cmd.shown[cmd.sel]); }
    });
    $$("[data-cmdk]").forEach((b) => on(b, "click", () => toggleCmdk(true)));
  }

  /* ---------------- معالج الإنشاء ---------------- */
  const wz = {
    step: 1, mode: "document", last() { return this.mode === "message" ? 2 : 3; },
    open(mode) { openOv("compose"); this.mode = mode === "message" ? "message" : "document"; this.step = 1; const b = $("#wz-submit"); if (b) { b.disabled = false; } this.render(); },
    sel(id) { const s = document.getElementById(id); return s && s.selectedOptions[0] ? s.selectedOptions[0].textContent.trim() : "—"; },
    render() {
      const m = this.mode === "message";
      $$("#compose [data-wz-pane]").forEach((p) => p.classList.toggle("on", +p.dataset.wzPane === this.step));
      $$("#compose .wz-s").forEach((s) => { const n = +s.dataset.s; s.classList.toggle("on", n === this.step); s.classList.toggle("done", n < this.step); s.hidden = m && n === 3; });
      $$("#compose [data-mode]").forEach((t) => t.classList.toggle("on", t.dataset.mode === this.mode));
      $("#wz-tx").hidden = m; $("#wz-to").hidden = !m;
      ["wz-tx-sel", "wz-sector", "wz-unit", "wz-conf", "wz-prio"].forEach((id) => { const e = document.getElementById(id); if (e) e.required = !m; });
      $("#wz-mode").value = this.mode;
      const last = this.step >= this.last();
      $("#wz-back").hidden = this.step === 1; $("#wz-next").hidden = last; $("#wz-submit").hidden = !last;
      $("#wz-submit").textContent = m ? "إرسال المراسلة" : "حفظ وإنشاء الموضوع";
      $("#wz-title").textContent = m ? "مراسلة سريعة" : "موضوع جديد";
      if (this.step === 2) setTimeout(() => $("#wz-ttl").focus(), 50);
      if (this.step === 3) this.review();
    },
    review() {
      const f = $("#wz-ttl").value || "—", dl = $("#wz-review"); dl.textContent = "";
      const rows = [["النوع", this.mode === "message" ? "مراسلة سريعة" : "موضوع رسمي"], ["نوع المعاملة", this.sel("wz-tx-sel")], ["العنوان", f], ["القطاع / الوحدة", this.sel("wz-sector") + " — " + this.sel("wz-unit")], ["السرية / الأولوية", this.sel("wz-conf") + " — " + this.sel("wz-prio")], ["المسؤول", this.sel("wz-owner")]];
      const fl = $("#wz-file"); if (fl && fl.files.length) rows.push(["المرفقات", fl.files.length + " ملف"]);
      rows.forEach(([a, b]) => dl.append(h("dt", { text: a }), h("dd", { text: b })));
    },
    valid() {
      if (this.step === 2) {
        if (!$("#wz-ttl").value.trim()) { $("#wz-ttl").focus(); toast("اكتب عنواناً أولاً.", "warning"); return false; }
        if (this.mode === "message" && !$("#wz-to-sel").selectedOptions.length) { toast("اختر مستلماً واحداً على الأقل.", "warning"); return false; }
      }
      return true;
    },
    filterUnits() {
      const s = $("#wz-sector").value, u = $("#wz-unit"); let first = null;
      $$("option", u).forEach((o) => { const sec = o.dataset.sector; o.hidden = !!(s && sec && sec !== s); if (!o.hidden && !first && o.value) first = o; });
      if (u.selectedOptions[0] && u.selectedOptions[0].hidden && first) u.value = first.value;
    },
    init() {
      const c = $("#compose"); if (!c) return;
      $$("[data-compose]").forEach((b) => on(b, "click", (e) => { e.preventDefault(); this.open(b.dataset.compose); }));
      $$("[data-mode]", c).forEach((t) => on(t, "click", () => { this.mode = t.dataset.mode; this.render(); }));
      $$("[data-txid]", c).forEach((t) => on(t, "click", () => { $("#wz-tx-sel").value = t.dataset.txid; $$("[data-txid]", c).forEach((x) => x.classList.toggle("on", x === t)); }));
      on($("#wz-next"), "click", () => { if (this.valid()) { this.step = Math.min(this.step + 1, this.last()); this.render(); } });
      on($("#wz-back"), "click", () => { this.step = Math.max(1, this.step - 1); this.render(); });
      on($("#wz-sector"), "change", () => this.filterUnits());
      on($("#wz-adv"), "click", () => ($("#wz-advbox").hidden = !$("#wz-advbox").hidden));
      on(c, "keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "submit" && this.step < this.last()) { e.preventDefault(); $("#wz-next").click(); } });
      on($("#wz-form"), "submit", () => { const b = $("#wz-submit"); b.disabled = true; b.textContent = "جارٍ الحفظ…"; });
      on($("#wz-file"), "change", (e) => { $("#wz-file-l").textContent = e.target.files.length ? Array.from(e.target.files).map((f) => f.name).join("، ") : "لم يتم اختيار مرفق"; });
      this.filterUnits(); this.render();
    },
  };

  /* ---------------- معاينة المرفقات ---------------- */
  let subjectPreviewItems = [];
  let subjectPreviewIndex = -1;
  function previewAtt(d, sourceEl = null) {
    const body = $("#pv-body"); if (!body) return;
    body.textContent = "";
    $("#pv-name").textContent = d.name || "مرفق";
    $("#pv-dl").href = d.dl || "#"; $("#pv-page").href = d.page || "#";
    const meta = $("#pv-meta");
    const details = [
      d.version ? "الإصدار " + d.version : "",
      d.size ? "الحجم " + d.size : "",
      d.uploaded ? "تاريخ الإضافة " + d.uploaded : "",
      d.uploader ? "أضيف بواسطة " + d.uploader : "",
      d.approved ? "حالة الإصدار: " + d.approved : ""
    ].filter(Boolean);
    if (meta) { meta.textContent = details.join(" · "); meta.hidden = details.length === 0; }
    const subjectSection = sourceEl && sourceEl.closest("#sec-documents");
    subjectPreviewItems = subjectSection ? Array.from(subjectSection.querySelectorAll("[data-pv]")) : [];
    subjectPreviewIndex = subjectPreviewItems.indexOf(sourceEl);
    const prev = $("#pv-prev"), next = $("#pv-next");
    if (prev) prev.hidden = subjectPreviewIndex <= 0;
    if (next) next.hidden = subjectPreviewIndex < 0 || subjectPreviewIndex >= subjectPreviewItems.length - 1;
    const kind = (d.kind || "").toLowerCase();
    if (/image|img/.test(kind)) body.append(h("img", { class: "pv-media-image", src: d.url, alt: d.name || "صورة مرفقة" }));
    else if (/pdf|text|txt/.test(kind)) body.append(h("iframe", { class: "pv-media-frame", src: d.url, title: d.name || "معاينة المرفق" }));
    else body.append(h("div", { class: "empty" }, h("div", { class: "ico", text: "📄" }), h("h4", { text: "لا تتوفر معاينة مباشرة لهذا النوع" }), h("p", { text: "يمكنك فتح صفحة المعاينة الكاملة أو تنزيل الملف." })));
    openOv("pv");
  }
  on(document, "click", (e) => {
    const step = e.target.closest("[data-pv-step]");
    if (step) {
      const target = subjectPreviewItems[subjectPreviewIndex + Number(step.dataset.pvStep)];
      if (target) target.click();
      return;
    }
    const previewButton = e.target.closest("[data-pv-btn]");
    if (previewButton) {
      const row = previewButton.closest("[data-pv]");
      if (row) { e.preventDefault(); previewAtt({
        name: row.dataset.pvName, url: row.dataset.pvUrl, dl: row.dataset.pvDl, page: row.dataset.pvPage, kind: row.dataset.pvKind,
        version: row.dataset.pvVersion, size: row.dataset.pvSize, uploaded: row.dataset.pvUploaded, uploader: row.dataset.pvUploader, approved: row.dataset.pvApproved
      }, row); }
      return;
    }
    const el = e.target.closest("[data-pv]"); if (!el) return;
    const inner = e.target.closest("a[href],button,form,input,select,textarea");
    if (inner && el.contains(inner) && inner !== el) return;
    e.preventDefault(); const d = el.dataset;
    if (el.closest("[data-docs]") && (el.classList.contains("dcard") || el.hasAttribute("data-split"))) { splitPreview(el); return; }
    previewAtt({ name: d.pvName, url: d.pvUrl, dl: d.pvDl, page: d.pvPage, kind: d.pvKind,
      version: d.pvVersion, size: d.pvSize, uploaded: d.pvUploaded, uploader: d.pvUploader, approved: d.pvApproved }, el);
  });
  on(document, "keydown", (e) => {
    const row = e.target.closest("#sec-documents [data-pv][role=button]");
    if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); row.click(); return; }
  });
  on(document, "keydown", (e) => {
    if (!$("#pv")?.classList.contains("open") || !subjectPreviewItems.length) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const direction = e.key === "ArrowLeft" ? 1 : -1;
      const target = subjectPreviewItems[subjectPreviewIndex + direction];
      if (target) { e.preventDefault(); target.click(); }
    }
  });
  function splitPreview(card) {
    const root = card.closest("[data-docs]"), pv = $(".pv-b", root), d = card.dataset;
    $$("[data-pv].on", root).forEach((c) => c.classList.remove("on")); card.classList.add("on");
    root.classList.remove("no-preview"); pv.textContent = "";
    $("#pvs-name", root).textContent = d.pvName || "";
    $("#pvs-dl", root).href = d.pvDl || "#"; $("#pvs-page", root).href = d.pvPage || "#";
    const kind = (d.pvKind || "").toLowerCase();
    if (/image|img/.test(kind)) pv.append(h("img", { src: d.pvUrl, alt: d.pvName }));
    else if (/pdf|text|txt/.test(kind)) pv.append(h("iframe", { src: d.pvUrl, title: d.pvName }));
    else pv.append(h("div", { class: "detail-empty" }, h("div", { text: "لا تتوفر معاينة مباشرة — افتح صفحة المعاينة الكاملة." })));
    if (innerWidth <= 1000) previewAtt({ name: d.pvName, url: d.pvUrl, dl: d.pvDl, page: d.pvPage, kind: d.pvKind });
  }

  /* ---------------- معاينة الموضوع في الوارد ---------------- */
  const pill = (t, tone) => h("span", { class: "pill " + (tone || ""), text: t });
  let previewRequestId = 0;
  async function loadSubject(id, row) {
    const requestId = ++previewRequestId;
    const box = $("#detail-box"), inbox = $(".inbox");
    box.setAttribute("aria-busy", "true");
    $$(".mail.on").forEach((r) => r.classList.remove("on")); row && row.classList.add("on");
    if (row) row.classList.remove("unread");
    box.textContent = ""; box.append(h("div", { class: "detail-empty", text: "جارٍ التحميل…" }));
    inbox.classList.add("show-detail");
    try {
      const d = await api(row.dataset.preview);
      if (requestId !== previewRequestId) return;
      box.textContent = "";
      const kv = (k, v) => [h("dt", { text: k }), h("dd", {}, v)];
      const overviewPane = h("section", { class: "preview-pane is-active", "data-preview-pane": "overview" },
        h("dl", { class: "kv" }, ...kv("نوع المعاملة", d.transaction_type), ...kv("القطاع / الوحدة", d.sector + " — " + d.org_unit), ...kv("المسؤول الحالي", d.current_owner), ...kv("الاستحقاق", h("span", { class: d.is_overdue ? "bold" : "", style: d.is_overdue ? "color:var(--bad)" : null, text: d.due_date + (d.is_overdue ? " (متأخر)" : "") })), ...kv("المذكرات المسجلة", String(d.memos_count || 0))),
        d.description ? h("div", { class: "sect" }, h("h4", { text: "ملخص الموضوع" }), h("p", { class: "muted preview-description", text: d.description })) : h("div", { class: "note info mt-s", text: "لا يوجد وصف إضافي مسجل لهذا الموضوع." }),
        h("div", { class: "preview-facts" },
          h("div", {}, h("small", { text: "درجة السرية" }), h("b", { text: d.confidentiality })),
          h("div", {}, h("small", { text: "الأولوية" }), h("b", { text: d.priority })),
          h("div", {}, h("small", { text: "المذكرات" }), h("b", { text: String(d.memos_count || 0) }))));
      const attachmentsPane = h("section", { class: "preview-pane", "data-preview-pane": "attachments", hidden: true },
        (d.attachments || []).length ? h("div", { class: "preview-attachment-list" }, ...d.attachments.map((a) => h("div", { class: "item preview-attachment", role: "button", tabindex: "0", "aria-label": "معاينة " + a.filename, "data-pv": "", "data-pv-name": a.filename, "data-pv-url": a.preview_url, "data-pv-dl": a.download_url, "data-pv-page": a.full_page_url, "data-pv-kind": a.preview_kind },
          h("div", { class: "ficon", text: (a.filename.split(".").pop() || "").slice(0, 4).toUpperCase() }),
          h("div", { class: "grow" }, h("h5", { text: a.filename }), h("small", { class: "muted", text: a.doc_type + " · " + a.doc_title })),
          h("span", { class: "preview-open-label", text: "معاينة" })))) : h("div", { class: "detail-empty preview-tab-empty", text: "لا توجد مرفقات متاحة للمعاينة." }));
      const referralsPane = h("section", { class: "preview-pane", "data-preview-pane": "referrals", hidden: true },
        (d.recent_referrals || []).length ? h("div", { class: "tl preview-referral-list" }, ...d.recent_referrals.map((r) => h("div", { class: "tl-i" }, h("b", { text: r.referred_by + " ← " + r.targets }), h("small", { text: r.purpose + " · " + r.created_at }), r.notes ? h("p", { text: r.notes }) : null))) : h("div", { class: "detail-empty preview-tab-empty", text: "لا توجد إحالات سابقة مسجلة." }));
      const panes = h("div", { class: "preview-panes" }, overviewPane, attachmentsPane, referralsPane);
      let tabs;
      const selectPreviewPane = (key) => {
        $$(".preview-tab", tabs).forEach((button) => {
          const active = button.dataset.previewTab === key;
          button.classList.toggle("on", active);
          button.setAttribute("aria-pressed", active ? "true" : "false");
        });
        $$("[data-preview-pane]", panes).forEach((pane) => { pane.hidden = pane.dataset.previewPane !== key; });
      };
      const makeTab = (label, count, key, active) => h("button", { type: "button", class: "preview-tab" + (active ? " on" : ""), "data-preview-tab": key, "aria-pressed": active ? "true" : "false", onclick: () => selectPreviewPane(key) },
        h("span", { text: label }), h("span", { class: "preview-tab-count", text: String(count) }));
      tabs = h("div", { class: "preview-tabs", role: "group", "aria-label": "أقسام المعاينة" },
        makeTab("الملخص", 1, "overview", true),
        makeTab("المرفقات", (d.attachments || []).length, "attachments", false),
        makeTab("الإحالات", (d.recent_referrals || []).length, "referrals", false));
      const acts = h("div", { class: "detail-foot" },
        h("a", { class: "btn primary", href: d.detail_url, text: "فتح الموضوع بالكامل" }),
        d.pending_ref_id && d.ack_url ? h("form", { class: "inline", method: "post", action: d.ack_url }, h("input", { type: "hidden", name: "csrfmiddlewaretoken", value: csrf() }), h("input", { type: "hidden", name: "action", value: "acknowledge" }), h("input", { type: "hidden", name: "next", value: location.pathname + location.search }), h("button", { class: "btn ok", type: "submit", text: "تأكيد الاستلام" })) : null,
        h("button", { class: "btn ghost menu-back", type: "button", onclick: () => inbox.classList.remove("show-detail"), text: "رجوع للقائمة" }));
      box.append(h("div", { class: "detail-scroll" },
        h("div", { class: "row wrap gap-s" }, h("span", { class: "tag code", text: d.internal_number }), pill(d.status_label, d.is_overdue ? "bad" : "brand"), pill(d.priority, "warn"), d.is_top_secret ? pill("سري للغاية", "bad") : pill(d.confidentiality, "info")),
        h("h2", { class: "mt-s", text: d.title }),
        h("section", { class: "preview-guidance " + (d.is_overdue ? "is-overdue" : d.pending_ref_id ? "needs-action" : d.can_act ? "can-act" : "readonly"), "aria-live": "polite" },
          h("span", { class: "preview-guidance-mark", text: d.is_overdue ? "!" : d.pending_ref_id ? "↳" : d.can_act ? "✓" : "i", "aria-hidden": "true" }),
          h("div", {}, h("b", { text: d.is_overdue ? "هذا الموضوع تجاوز موعد استحقاقه" : d.pending_ref_id ? "الخطوة المطلوبة: تأكيد استلام الإحالة" : d.can_act ? "الموضوع ضمن نطاق عملك" : "للاطلاع والمتابعة فقط" }),
            h("p", { text: d.is_overdue ? "راجع الموضوع وحدد الإجراء المناسب وفق مرحلته وصلاحياتك." : d.pending_ref_id ? "بعد تأكيد الاستلام، افتح الموضوع لمراجعة التفاصيل واستكمال الإجراء." : d.can_act ? "افتح الموضوع لمراجعة الإجراءات المتاحة لك والخطوة التالية." : "يمكنك مراجعة البيانات والمرفقات دون تنفيذ إجراء على الموضوع." }))),
        tabs, panes),
        acts);
    } catch (err) { if (requestId !== previewRequestId) return; box.textContent = ""; box.append(h("div", { class: "detail-empty", role: "alert", text: err.message })); }
    finally { if (requestId === previewRequestId) box.setAttribute("aria-busy", "false"); }
  }
  on(document, "click", (e) => { const r = e.target.closest(".mail[data-preview]"); if (!r) return; if (e.target.closest("a.open-link")) return; e.preventDefault(); loadSubject(r.dataset.id, r); });
  on(document, "keydown", (e) => {
    const attachment = e.target.closest(".preview-attachment[data-pv]");
    if (attachment && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); attachment.click(); return; }
    const current = e.target.closest(".inbox-scroll .mail[data-preview]");
    if (current && ["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      const rows = $(".inbox-scroll .mail[data-preview]"); if (!rows.length) return;
      e.preventDefault(); const index = rows.indexOf(current);
      const next = e.key === "Home" ? rows[0] : e.key === "End" ? rows[rows.length - 1] : rows[Math.max(0, Math.min(rows.length - 1, index + (e.key === "ArrowDown" ? 1 : -1)))];
      next.focus(); next.click();
    } else if (e.key === "Escape" && $(".inbox.show-detail")) {
      e.preventDefault(); $(".inbox").classList.remove("show-detail"); const selected = $(".mail.on"); if (selected) selected.focus();
    }
  });

  /* ---------------- الإشعارات ---------------- */
  const notif = { items: [], cat: "" };
  async function loadNotif() {
    const L = $("#notif-list"); if (!L) return;
    try { const d = await api(L.dataset.url); notif.items = d.notifications || []; renderNotif(); setBadge("#notif-badge", d.unread_count); } catch (e) { L.textContent = ""; L.append(h("div", { class: "empty", text: e.message })); }
  }
  function renderNotif() {
    const L = $("#notif-list"), C = $("#notif-cats"); L.textContent = ""; C.textContent = "";
    const cats = Array.from(new Set(notif.items.map((n) => n.category_label)));
    [["", "الكل"]].concat(cats.map((c) => [c, c])).forEach(([v, t]) => C.append(h("button", { type: "button", class: "chip" + (notif.cat === v ? " on" : ""), text: t, onclick: () => { notif.cat = v; renderNotif(); } })));
    const list = notif.items.filter((n) => !notif.cat || n.category_label === notif.cat);
    if (!list.length) { L.append(h("div", { class: "empty" }, h("div", { class: "ico", text: "🔔" }), h("h4", { text: "لا توجد إشعارات" }), h("p", { text: "ستظهر هنا الإحالات الجديدة والمواعيد المتأخرة." }))); return; }
    list.forEach((n) => L.append(h("a", { class: "item", href: n.link_url || "#", onclick: () => { if (!n.is_read && /^\d+$/.test(String(n.id))) postJSON($("#notif-list").dataset.mark, { notification_id: n.id }).catch(() => {}); } },
      h("span", { class: "dot " + (n.priority === "URGENT" ? "bad" : n.is_read ? "" : "brand"), style: "margin-top:8px" }),
      h("div", { class: "grow" }, h("h5", { text: n.title, style: n.is_read ? "font-weight:500" : "" }), h("p", { class: "sm muted", text: n.message }), h("small", { class: "soft", text: n.category_label + " · " + n.created_at })))));
  }
  const setBadge = (sel, n) => $$(sel).forEach((b) => { b.textContent = n; b.hidden = !n; });
  on(document, "dr:open", (e) => { if (e.detail === "dr-notif") loadNotif(); if (e.detail === "dr-chat") chat.open(); });
  on(document, "dr:close", () => chat.stop());
  on($("#notif-all"), "click", async () => { try { await postJSON($("#notif-list").dataset.mark, { mark_all: true }); loadNotif(); } catch (e) { toast(e.message, "error"); } });

  /* ---------------- المحادثات ---------------- */
  const chat = {
    st: null, cur: null, timer: null, view: "list",
    open() { this.view = "list"; this.cur = null; this.load(); this.timer = setInterval(() => this.load(true), 6000); },
    stop() { clearInterval(this.timer); this.timer = null; },
    async load(silent) {
      const root = $("#chat-body"); if (!root) return;
      try {
        const u = root.dataset.url + (this.cur ? "?conversation_id=" + this.cur : "");
        this.st = await api(u); setBadge("#chat-badge", this.st.total_unread); this.render();
        if (this.cur && this.st.messages.length) { const last = this.st.conversations.find((c) => c.id === this.cur); if (last && last.unread_count) postJSON(root.dataset.read, { conversation_id: this.cur }).catch(() => {}); }
      } catch (e) { if (!silent) { root.textContent = ""; root.append(h("div", { class: "empty", text: e.message })); } }
    },
    render() {
      const root = $("#chat-body"), s = this.st; root.textContent = ""; const foot = $("#chat-foot"); foot.hidden = !this.cur;
      $("#chat-title").textContent = this.view === "dir" ? "بدء محادثة" : this.cur ? ((s.conversations.find((c) => c.id === this.cur) || {}).display_title || "محادثة") : "المحادثات";
      $("#chat-back").hidden = !(this.cur || this.view !== "list");
      if (this.view === "dir") return this.renderDir();
      if (this.cur) {
        const box = h("div", { class: "msgs" }, ...s.messages.map((m) => h("div", { class: "bubble" + (m.sender_id === s.current_user_id ? " me" : "") }, m.sender_id === s.current_user_id ? null : h("b", { class: "xs", text: m.sender_name + " " }), m.text || null, m.attachment ? h("div", {}, h("a", { href: m.attachment.download_url, style: m.sender_id === s.current_user_id ? "color:inherit;text-decoration:underline" : "", text: "📎 " + m.attachment.name })) : null, h("small", { text: m.time_short }))));
        root.append(box); root.scrollTop = root.scrollHeight; return;
      }
      root.append(h("div", { class: "row between mb" }, h("b", { text: "المحادثات" }), h("button", { class: "btn sm primary", type: "button", onclick: () => { this.view = "dir"; this.render(); }, text: "+ جديدة" })));
      if (!s.conversations.length) root.append(h("div", { class: "empty" }, h("div", { class: "ico", text: "💬" }), h("h4", { text: "لا توجد محادثات" }), h("p", { text: "ابدأ محادثة مع زميل أو أنشئ مجموعة." })));
      s.conversations.forEach((c) => root.append(h("div", { class: "item", style: "cursor:pointer", onclick: () => { this.cur = c.id; this.load(); } }, h("div", { class: "avatar", text: (c.display_title || "؟").slice(0, 2) }), h("div", { class: "grow" }, h("h5", { text: c.display_title }), h("p", { class: "sm muted trunc", text: c.last_message ? (c.last_message.text || (c.last_message.attachment ? "📎 " + c.last_message.attachment.name : "—")) : "—" })), c.unread_count ? h("span", { class: "cnt bad", text: c.unread_count }) : null)));
    },
    renderDir() {
      const root = $("#chat-body"), s = this.st; const picked = new Set();
      const gname = h("input", { class: "in sm", placeholder: "اسم المجموعة (اختياري للمجموعات)" });
      const mk = h("button", { class: "btn sm primary", type: "button", text: "إنشاء مجموعة", onclick: async () => { if (!gname.value.trim() || !picked.size) return toast("أدخل اسم المجموعة واختر أعضاء.", "warning"); try { const r = await postJSON($("#chat-body").dataset.groups, { name: gname.value.trim(), member_ids: Array.from(picked) }); this.cur = r.conversation.id; this.view = "list"; this.load(); } catch (e) { toast(e.message, "error"); } } });
      root.append(h("div", { class: "col mb" }, gname, mk));
      s.chat_users.filter((u) => u.id !== s.current_user_id).forEach((u) => root.append(h("div", { class: "item" }, h("input", { type: "checkbox", onchange: (e) => (e.target.checked ? picked.add(u.id) : picked.delete(u.id)), "aria-label": "تحديد" }), h("div", { class: "avatar", text: (u.full_name || "؟").slice(0, 2) }), h("div", { class: "grow" }, h("h5", {}, u.full_name, " ", h("span", { class: "dot " + (u.is_online ? "ok" : "") })), h("small", { class: "muted", text: (u.job_title || u.unit) })), h("button", { class: "btn sm", type: "button", text: "محادثة", onclick: async () => { try { const r = await postJSON(root.dataset.direct, { target_user_id: u.id }); this.cur = r.conversation.id; this.view = "list"; this.load(); } catch (e) { toast(e.message, "error"); } } }))));
    },
  };
  function initChat() {
    on($("#chat-back"), "click", () => { if (chat.cur) chat.cur = null; else chat.view = "list"; chat.load(); });
    on($("#chat-form"), "submit", async (e) => {
      e.preventDefault(); const f = e.target, t = $("textarea", f), file = $("input[type=file]", f);
      if (!t.value.trim() && !file.files.length) return;
      const fd = new FormData(); fd.append("conversation_id", chat.cur); fd.append("text", t.value); if (file.files[0]) fd.append("attachment", file.files[0]);
      try { await api($("#chat-body").dataset.send, { method: "POST", body: fd }); t.value = ""; file.value = ""; $("#chat-file-l").textContent = ""; chat.load(); } catch (err) { toast(err.message, "error"); }
    });
    on($("#chat-form textarea"), "keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chat-form").requestSubmit(); } });
    on($("#chat-form input[type=file]"), "change", (e) => ($("#chat-file-l").textContent = e.target.files[0] ? e.target.files[0].name : ""));
  }

  /* ---------------- التقويم (اللجان) ---------------- */
  function initCalendar() {
    const box = $("#cal"), data = $("#meet-data"); if (!box || !data) return;
    const meets = JSON.parse(data.textContent || "[]"); const has = new Set(meets.map((m) => m.date));
    const names = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"], mn = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"];
    let cur = new Date(); cur.setDate(1); let picked = "";
    const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    const draw = () => {
      box.textContent = "";
      box.append(h("div", { class: "cal-h" }, h("button", { class: "iconbtn", type: "button", "aria-label": "الشهر التالي", onclick: () => { cur.setMonth(cur.getMonth() + 1); draw(); }, text: "›" }), h("span", { text: mn[cur.getMonth()] + " " + cur.getFullYear() }), h("button", { class: "iconbtn", type: "button", "aria-label": "الشهر السابق", onclick: () => { cur.setMonth(cur.getMonth() - 1); draw(); }, text: "‹" })));
      const g = h("div", { class: "cal-g" }, ...names.map((n) => h("b", { text: n.slice(0, 3) })));
      const start = new Date(cur); start.setDate(1 - cur.getDay());
      for (let i = 0; i < 42; i++) { const d = new Date(start); d.setDate(start.getDate() + i); const k = iso(d); g.append(h("button", { type: "button", class: "cal-d" + (d.getMonth() !== cur.getMonth() ? " out" : "") + (k === iso(new Date()) ? " today" : "") + (has.has(k) ? " has" : ""), onclick: () => { picked = picked === k ? "" : k; filter(); }, text: d.getDate() })); }
      box.append(g);
    };
    const filter = () => { $$(".meet[data-date]").forEach((m) => (m.hidden = !!picked && m.dataset.date !== picked)); $("#cal-clear").hidden = !picked; };
    on($("#cal-clear"), "click", () => { picked = ""; filter(); }); draw();
  }

  /* ---------------- الهيكل التنظيمي (سحب وإفلات) ---------------- */
  function renderOrg(root) {
    const el = $("#org-data"); if (!el) return;
    let d; try { d = JSON.parse(JSON.parse(el.textContent)); } catch (e) { root.textContent = "تعذّر قراءة بيانات الهيكل."; return; }
    const manage = root.dataset.manage === "1", units = d.units || [], by = {};
    units.forEach((u) => (by[u.id] = Object.assign({ kids: [] }, u)));
    const top = [];
    units.forEach((u) => { const n = by[u.id]; if (u.parent_id && by[u.parent_id]) by[u.parent_id].kids.push(n); else top.push(n); });
    const node = (n) => {
      const users = (n.users || []).map((x) => h("span", { class: "chipuser", draggable: manage ? "true" : null, "data-emp-id": x.employee_id, title: x.job_title || "" }, h("span", { class: "avatar sm", text: (x.full_name || "؟").slice(0, 2) }), x.full_name, x.is_secretariat ? h("span", { class: "pill nodot", text: "سكرتارية" }) : null));
      return h("div", {}, h("div", { class: "org-node", draggable: manage ? "true" : null, "data-unit-id": n.id, "data-drop": n.id },
        h("div", { class: "row between wrap" }, h("div", { class: "row gap-s" }, h("b", { text: n.name }), h("span", { class: "tag code", text: n.code }), n.unit_type ? h("span", { class: "pill info nodot", text: n.unit_type }) : null), h("span", { class: "muted xs", text: (n.sector_name || "") + " · " + (n.users_count || 0) + " موظف" })),
        users.length ? h("div", { class: "chips mt-s" }, ...users) : null),
        n.kids.length ? h("div", { class: "org-kids" }, ...n.kids.sort((a, b) => a.level_order - b.level_order).map(node)) : null);
    };
    root.textContent = "";
    if (!top.length) { root.append(h("div", { class: "empty", text: "لا توجد وحدات ضمن النطاق." })); return; }
    top.sort((a, b) => a.level_order - b.level_order).forEach((n) => root.append(node(n)));
  }
  function initOrg() {
    const root = $("#org-root"); if (!root) return;
    renderOrg(root);
    if (root.dataset.manage !== "1") return;
    let drag = null;
    on(root, "dragstart", (e) => { const u = e.target.closest("[data-unit-id]"), p = e.target.closest("[data-emp-id]"); if (p) drag = { t: "emp", id: p.dataset.empId }; else if (u) drag = { t: "unit", id: u.dataset.unitId }; if (drag) e.dataTransfer.setData("text/plain", drag.t + drag.id); });
    on(root, "dragover", (e) => { const n = e.target.closest("[data-drop]"); if (n && drag) { e.preventDefault(); $$(".org-node.over").forEach((x) => x.classList.remove("over")); n.classList.add("over"); } });
    on(root, "drop", async (e) => {
      const n = e.target.closest("[data-drop]"); if (!n || !drag) return; e.preventDefault(); n.classList.remove("over");
      try {
        const r = drag.t === "unit" ? await postJSON(root.dataset.moveUnit, { unit_id: drag.id, new_parent_id: n.dataset.drop }) : await postJSON(root.dataset.moveUser, { employee_id: drag.id, target_unit_id: n.dataset.drop });
        toast(r.message || "تم النقل", "success"); setTimeout(() => location.reload(), 700);
      } catch (err) { toast(err.message, "error"); } drag = null;
    });
  }

  /* ---------------- مفتاح الـ idempotency وإرسال مزدوج ---------------- */
  on(document, "submit", (e) => { const f = e.target; if (f.method !== "post" || f.dataset.multi !== undefined) return; const b = $("button[type=submit]:not([data-nolock])", f); if (!b || f.id === "wz-form") return; setTimeout(() => { b.disabled = true; setTimeout(() => (b.disabled = false), 8000); }, 0); }, false);

  window.addEventListener("error", (e) => { try { toast("خطأ في الواجهة: " + e.message, "error"); } catch (x) {} });
  /* ---------------- تهيئة ---------------- */
  document.addEventListener("DOMContentLoaded", () => {
    const rail = store.get("rail", false); if (rail && innerWidth > 1000) $(".shell") && $(".shell").classList.add("collapsed");
    $$("#server-msgs [data-t]").forEach((m, i) => setTimeout(() => toast(m.textContent.trim(), m.dataset.t), i * 160));
    on(window, "scroll", () => $(".top") && $(".top").classList.toggle("scrolled", scrollY > 4), { passive: true });
    [initTabs, initTables, initCmdk, () => wz.init(), initChat, initCalendar, initOrg].forEach((fn) => { try { fn(); } catch (e) { console.error("init failed:", fn.name, e); toast("خطأ في تهيئة الواجهة: " + e.message, "error"); } });
    const ib = $(".inbox[data-autoload]"); const first = ib && $(".mail[data-preview]", ib);
    if (first && innerWidth > 1000) { loadSubject(first.dataset.id, first); ib.classList.remove("show-detail"); }
    if (location.hash.startsWith("#sec-")) setTimeout(() => jump(location.hash.slice(1)), 300);
    const nb = $("#notif-badge"); if (nb && nb.dataset.poll) setInterval(async () => { try { const d = await api($("#notif-list").dataset.url); setBadge("#notif-badge", d.unread_count); } catch (e) {} }, 60000);
  });
})();
