/* Interactive Enterprise Experience — safe enhancements only. */
(() => {
  "use strict";
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nav = document.querySelector(".subnav");
  if (nav) {
    const links = Array.from(nav.querySelectorAll("[data-jump]"));
    const sections = links.map(a => document.getElementById(a.dataset.jump)).filter(Boolean);
    const activate = id => links.forEach(a => {
      const current = a.dataset.jump === id;
      if (current) a.setAttribute("aria-current","location");
      else a.removeAttribute("aria-current");
    });
    if ("IntersectionObserver" in window && sections.length) {
      const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(e => e.isIntersecting).sort((a,b) => b.intersectionRatio-a.intersectionRatio)[0];
        if (visible) activate(visible.target.id);
      }, {rootMargin:"-18% 0px -68% 0px",threshold:[0,.15,.4,.7]});
      sections.forEach(section => observer.observe(section));
    }
    links.forEach(link => link.addEventListener("click", () => activate(link.dataset.jump)));
  }
  if (!reduced && "IntersectionObserver" in window) {
    const candidates = document.querySelectorAll(".page > .panel,.page > .grid > .panel");
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("ux-reveal");
        observer.unobserve(entry.target);
      }
    }), {threshold:.04});
    candidates.forEach(el => observer.observe(el));
  }
  // Referral inbox: local text/status/due filters over the currently selected tab only.
  const referralRoot = document.querySelector("[data-tabs-root]");
  if (referralRoot) {
    const search = document.querySelector("[data-referral-search]");
    const statusFilter = document.querySelector("[data-referral-status]");
    const dueFilter = document.querySelector("[data-referral-due]");
    const count = document.querySelector("[data-referral-count]");
    const clear = document.querySelector("[data-referral-clear]");
    const normalizeReferralText = value => String(value || "").normalize("NFD")
      .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه").toLocaleLowerCase("ar");
    const applyReferralFilters = () => {
      const pane = referralRoot.querySelector("[data-pane].on") || referralRoot.querySelector("[data-pane]");
      if (!pane) return;
      const tokens = normalizeReferralText(search?.value).split(/\s+/).filter(Boolean);
      const status = statusFilter?.value || "";
      const due = dueFilter?.value || "";
      const items = [...pane.querySelectorAll("[data-referral-item]")];
      let shown = 0;
      items.forEach(item => {
        const haystack = normalizeReferralText(item.textContent);
        const matchesText = tokens.every(token => haystack.includes(token));
        const matchesStatus = !status || item.dataset.referralStatus === status;
        const isOverdue = item.dataset.referralOverdue === "1";
        const isUndated = item.dataset.referralUndated === "1";
        const matchesDue = !due || (due === "overdue" ? isOverdue : due === "upcoming" ? !isOverdue && !isUndated : isUndated);
        item.hidden = !(matchesText && matchesStatus && matchesDue);
        if (!item.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + items.length.toLocaleString("ar") + " إحالة في هذا التبويب";
    };
    const populateReferralStatuses = () => {
      if (!statusFilter) return;
      const values = new Map();
      referralRoot.querySelectorAll("[data-referral-item]").forEach(item => {
        if (item.dataset.referralStatus) values.set(item.dataset.referralStatus,item.dataset.referralStatusLabel || item.dataset.referralStatus);
      });
      [...values.entries()].sort((x,y)=>x[1].localeCompare(y[1],"ar")).forEach(([value,label])=>{
        const option=document.createElement("option");option.value=value;option.textContent=label;statusFilter.appendChild(option);
      });
    };
    search?.addEventListener("input",applyReferralFilters);
    statusFilter?.addEventListener("change",applyReferralFilters);
    dueFilter?.addEventListener("change",applyReferralFilters);
    clear?.addEventListener("click",()=>{
      if(search)search.value="";
      if(statusFilter)statusFilter.value="";
      if(dueFilter)dueFilter.value="";
      applyReferralFilters();search?.focus();
    });
    referralRoot.querySelectorAll("[data-tab]").forEach(tab=>tab.addEventListener("click",()=>requestAnimationFrame(applyReferralFilters)));
    populateReferralStatuses();
    applyReferralFilters();
  }
  // Notification center: local search and unread-only filter.
  const notificationRoot = document.querySelector("[data-notification-search]")?.closest(".page");
  if (notificationRoot) {
    const search = notificationRoot.querySelector("[data-notification-search]");
    const unread = notificationRoot.querySelector("[data-notification-unread]");
    const count = notificationRoot.querySelector("[data-notification-count]");
    const clear = notificationRoot.querySelector("[data-notification-clear]");
    const items = Array.from(notificationRoot.querySelectorAll("[data-notification-item]"));
    const apply = () => {
      const q = (search?.value || "").trim().toLocaleLowerCase("ar");
      let shown = 0;
      items.forEach(item => {
        const matchesText = !q || item.textContent.toLocaleLowerCase("ar").includes(q);
        const matchesUnread = !unread?.checked || item.dataset.unread === "1";
        item.hidden = !(matchesText && matchesUnread);
        if (!item.hidden) shown++;
      });
      if (count) count.textContent = shown + " من " + items.length + " إشعار";
    };
    search?.addEventListener("input", apply);
    unread?.addEventListener("change", apply);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      if (unread) unread.checked = false;
      apply();
      search?.focus();
    });
    apply();
  }
  // Make document preview cards usable from the keyboard as well as pointer input.
  document.addEventListener("keydown", event => {
    const card = event.target.closest(".dcard[data-pv]");
    if (!card || (event.key !== "Enter" && event.key !== " ")) return;
    if (event.target.closest("a,button,input,select,textarea")) return;
    event.preventDefault();
    card.click();
  });
  document.querySelectorAll("[data-pv]:not(a):not(button):not(input):not(select):not(textarea)").forEach(el => {
    if (el.classList.contains("dcard") || el.matches(".row")) {
      if (!el.hasAttribute("tabindex")) el.tabIndex = 0;
    }
  });
  // Activity log: filter only the latest events already rendered by Django.
  const activityRoot = document.querySelector("[data-activity-root]");
  if (activityRoot) {
    const search = activityRoot.querySelector("[data-activity-search]");
    const typeFilter = activityRoot.querySelector("[data-activity-type]");
    const periodFilter = activityRoot.querySelector("[data-activity-period]");
    const count = activityRoot.querySelector("[data-activity-count]");
    const clear = activityRoot.querySelector("[data-activity-clear]");
    const noResults = activityRoot.querySelector("[data-activity-no-results]");
    const items = Array.from(activityRoot.querySelectorAll("[data-activity-item]"));
    const timestampOf = item => {
      const raw = (item.dataset.logTimestamp || "").trim();
      const numeric = Number(raw);
      if (raw && Number.isFinite(numeric) && numeric > 1000000000) return numeric * 1000;
      const parsed = Date.parse(raw.replace(" ", "T"));
      return Number.isFinite(parsed) ? parsed : 0;
    };
    // Combine workflow milestones and operational log entries in one chronological stream.
    items.sort((a,b) => timestampOf(b) - timestampOf(a));
    const chronology = activityRoot.querySelector("[data-activity-list]");
    if (chronology) items.forEach(item => chronology.appendChild(item));
    const types = [...new Set(items.map(item => item.dataset.actionType).filter(Boolean))].sort((a,b) => a.localeCompare(b,"ar"));
    types.forEach(type => {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type;
      typeFilter?.appendChild(option);
    });
    const apply = () => {
      const query = (search?.value || "").trim().toLocaleLowerCase("ar");
      const selectedType = typeFilter?.value || "";
      const days = periodFilter?.value || "all";
      const cutoff = days === "all" ? null : Date.now() - Number(days) * 24 * 60 * 60 * 1000;
      let shown = 0;
      items.forEach(item => {
        const matchesText = !query || item.textContent.toLocaleLowerCase("ar").includes(query);
        const matchesType = !selectedType || item.dataset.actionType === selectedType;
        const timestamp = timestampOf(item);
        const matchesPeriod = cutoff === null || (Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= Date.now());
        item.hidden = !(matchesText && matchesType && matchesPeriod);
        if (!item.hidden) shown++;
      });
      if (count) count.textContent = shown + " من " + items.length + " عنصر زمني";
      if (noResults) noResults.hidden = shown !== 0 || items.length === 0;
    };
    search?.addEventListener("input", apply);
    typeFilter?.addEventListener("change", apply);
    periodFilter?.addEventListener("change", apply);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      if (typeFilter) typeFilter.value = "";
      if (periodFilter) periodFilter.value = "all";
      apply();
      search?.focus();
    });
    apply();
  }
  // Contextual shortcuts open the existing server-rendered forms; no new workflow is introduced.
  document.addEventListener("click", event => {
    const shortcut = event.target.closest("[data-open-details]");
    if (!shortcut) return;
    const target = document.querySelector(shortcut.getAttribute("href"));
    if (!target || target.tagName !== "DETAILS") return;
    event.preventDefault();
    target.open = true;
    target.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
    const firstField = target.querySelector("input:not([type=hidden]),select,textarea,button");
    if (firstField) window.setTimeout(() => firstField.focus({ preventScroll: true }), reduced ? 0 : 180);
    if (history.replaceState) history.replaceState(null, "", "#" + target.id);
  });
  // Task workbench: filters only the tasks already rendered on the current page.
  const taskRoot = document.querySelector("[data-task-item]")?.closest("[data-table]");
  if (taskRoot) {
    const search = taskRoot.querySelector("[data-task-filter]");
    const statusFilter = taskRoot.querySelector("[data-task-status-filter]");
    const dueFilter = taskRoot.querySelector("[data-task-due-filter]");
    const count = taskRoot.querySelector("[data-task-count]");
    const clear = taskRoot.querySelector("[data-task-clear]");
    const rows = Array.from(taskRoot.querySelectorAll("[data-task-item]"));
    const normalizeTaskText = value => String(value || "").toLocaleLowerCase("ar")
      .normalize("NFD").replace(/[\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").trim();
    const statusMap = new Map();
    rows.forEach(row => {
      const value = row.dataset.taskStatus || "";
      const label = row.dataset.taskStatusLabel || value;
      if (value && !statusMap.has(value)) statusMap.set(value, label);
    });
    [...statusMap.entries()].sort((a,b) => a[1].localeCompare(b[1],"ar")).forEach(([value,label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      statusFilter?.appendChild(option);
    });
    const applyTaskFilters = () => {
      const tokens = normalizeTaskText(search?.value).split(/\s+/).filter(Boolean);
      const status = statusFilter?.value || "";
      const due = dueFilter?.value || "";
      let visible = 0;
      rows.forEach(row => {
        const haystack = normalizeTaskText(row.textContent);
        const matchesText = tokens.every(token => haystack.includes(token));
        const matchesStatus = !status || row.dataset.taskStatus === status;
        const isOverdue = row.dataset.taskOverdue === "1";
        const hasDue = row.dataset.taskHasDue === "1";
        const matchesDue = !due || (due === "overdue" ? isOverdue : due === "dated" ? hasDue : !hasDue);
        row.hidden = !(matchesText && matchesStatus && matchesDue);
        if (!row.hidden) visible++;
      });
      if (count) count.textContent = visible + " من " + rows.length + " مهمة في الصفحة";
    };
    search?.addEventListener("input", applyTaskFilters);
    statusFilter?.addEventListener("change", applyTaskFilters);
    dueFilter?.addEventListener("change", applyTaskFilters);
    clear?.addEventListener("click", () => { if (search) search.value = ""; if (statusFilter) statusFilter.value = ""; if (dueFilter) dueFilter.value = ""; applyTaskFilters(); search?.focus(); });
    applyTaskFilters();
  }
  // Decision list workbench: filter only rows supplied by the current Django response.
  const decisionRoot = document.querySelector("[data-decision-root]");
  if (decisionRoot) {
    const search = decisionRoot.querySelector("[data-decision-search]");
    const typeFilter = decisionRoot.querySelector("[data-decision-type]");
    const statusFilter = decisionRoot.querySelector("[data-decision-status]");
    const count = decisionRoot.querySelector("[data-decision-count]");
    const empty = decisionRoot.querySelector("[data-decision-empty]");
    const clear = decisionRoot.querySelector("[data-decision-clear]");
    const rows = Array.from(decisionRoot.querySelectorAll("[data-decision-item]"));
    const normalizeDecisionText = value => String(value || "").toLocaleLowerCase("ar")
      .normalize("NFD").replace(/[\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").trim();
    const populate = (filter, valueKey, labelKey) => {
      const values = new Map();
      rows.forEach(row => {
        const value = row.dataset[valueKey] || "";
        const label = row.dataset[labelKey] || value;
        if (value && !values.has(value)) values.set(value, label);
      });
      [...values.entries()].sort((a,b) => a[1].localeCompare(b[1],"ar")).forEach(([value,label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        filter?.appendChild(option);
      });
    };
    populate(typeFilter, "decisionType", "decisionTypeLabel");
    populate(statusFilter, "decisionStatus", "decisionStatusLabel");
    const applyDecisionFilters = () => {
      const tokens = normalizeDecisionText(search?.value).split(/\s+/).filter(Boolean);
      const type = typeFilter?.value || "";
      const status = statusFilter?.value || "";
      let shown = 0;
      rows.forEach(row => {
        const haystack = normalizeDecisionText(row.textContent);
        const matchesText = tokens.every(token => haystack.includes(token));
        const matchesType = !type || row.dataset.decisionType === type;
        const matchesStatus = !status || row.dataset.decisionStatus === status;
        row.hidden = !(matchesText && matchesType && matchesStatus);
        if (!row.hidden) shown++;
      });
      if (count) count.textContent = shown + " من " + rows.length + " قرار";
      if (empty) empty.hidden = shown !== 0 || rows.length === 0;
    };
    search?.addEventListener("input", applyDecisionFilters);
    typeFilter?.addEventListener("change", applyDecisionFilters);
    statusFilter?.addEventListener("change", applyDecisionFilters);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      if (typeFilter) typeFilter.value = "";
      if (statusFilter) statusFilter.value = "";
      applyDecisionFilters();
      search?.focus();
    });
    applyDecisionFilters();
  }
  // Decision form: show a live character count without imposing a new length rule.
  const decisionBody = document.querySelector("[data-decision-body]");
  const decisionBodyCount = document.querySelector("[data-decision-body-count]");
  if (decisionBody && decisionBodyCount) {
    const updateDecisionBodyCount = () => {
      const length = decisionBody.value.length;
      decisionBodyCount.textContent = length.toLocaleString("ar") + " حرف";
    };
    decisionBody.addEventListener("input", updateDecisionBodyCount);
    updateDecisionBodyCount();
  }

  // Subject list workbench: local search is intentionally limited to rows on this page.
  window.__slInit = () => {
  const subjectList = document.querySelector("[data-subject-list]");
  if (subjectList) {
    const search = subjectList.querySelector("[data-subject-search]");
    const rows = [...subjectList.querySelectorAll("[data-subject-row]")];
    const count = subjectList.querySelector("[data-subject-count]");
    const clear = subjectList.querySelector("[data-subject-clear]");
    const total = rows.length;
    const normalizeSubjectText = value => String(value || "")
      .normalize("NFD").replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
      .toLocaleLowerCase("ar");
    const applySubjectSearch = () => {
      const tokens = normalizeSubjectText(search?.value).split(/\s+/).filter(Boolean);
      let visible = 0;
      rows.forEach(row => {
        const haystack = normalizeSubjectText(row.textContent);
        row.hidden = !tokens.every(token => haystack.includes(token));
        if (!row.hidden) visible++;
      });
      if (count) count.textContent = visible.toLocaleString("ar") + " من " + total.toLocaleString("ar") + " موضوع معروض";
    };
    search?.addEventListener("input", applySubjectSearch);
    clear?.addEventListener("click", () => {
      if (search) search.value = "";
      applySubjectSearch();
      search?.focus();
    });
    applySubjectSearch();
  }

  // Subject list: footer totals and selected-row side panel (display only).
  if (subjectList) {
    const wrap = subjectList.querySelector(".sl-wrap");
    const side = subjectList.querySelector("[data-sl-side]");
    const foot = subjectList.querySelector("[data-sl-foot]");
    const trs = [...subjectList.querySelectorAll("[data-subject-row]")];
    const setF = (k, v) => { const e = foot?.querySelector("[data-f-" + k + "]"); if (e) e.textContent = Number(v).toLocaleString("ar"); };
    const totals = () => {
      const vis = trs.filter(r => !r.hidden);
      setF("total", vis.length);
      setF("late", vis.filter(r => r.dataset.odOverdue).length);
      setF("secret", vis.filter(r => r.dataset.odSecret).length);
      setF("sel", subjectList.querySelectorAll(".row-chk:checked").length);
    };
    const esc = s => String(s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const openSide = row => {
      trs.forEach(r => r.classList.toggle("is-sel", r === row));
      const d = row.dataset;
      side.innerHTML = '<div class="sl-side-h"><b>' + esc(d.odNum) + '</b><button type="button" class="btn sm ghost" data-sl-close aria-label="إغلاق">×</button></div>' +
        '<h3>' + esc(d.odTitle) + '</h3><div class="sl-side-tags"><span class="pill ' + esc(d.odTone) + '">' + esc(d.odStatus) + '</span><span class="sd-tag" data-prio="' + esc(d.odPrio) + '">' + esc(d.odPrio) + '</span>' + (d.odSecret || d.odConf !== "عادي" ? '<span class="sd-tag ' + (d.odSecret ? "sd-tag-secret" : "sd-tag-conf") + '">' + esc(d.odConf) + '</span>' : '') + '</div>' +
        '<a class="btn primary sm" href="' + esc(d.odHref) + '">فتح الموضوع</a>' +
        '<dl><dt>النوع</dt><dd>' + esc(d.odType) + '</dd><dt>القطاع / الوحدة</dt><dd>' + esc(d.odSector) + '</dd><dt>المسؤول</dt><dd>' + esc(d.odOwner) + '</dd><dt>الاستحقاق</dt><dd>' + esc(d.odDue) + '</dd></dl>';
      if (d.odRec) {
        const act = document.createElement("div");
        act.className = "sl-act";
        act.innerHTML = d.odRecPending
          ? '<span>وصلك هذا الموضوع. اضغط استلام ليعرف المُحيل أنك اطلعت عليه.</span><button type="button" class="btn ok" data-af-receive data-af-id="' + esc(d.odId) + '">استلام</button>'
          : '<span>استلمته. اضغط إجراء لتوجّهه أو تنفّذه.</span><button type="button" class="btn primary" data-af-action data-af-id="' + esc(d.odId) + '">إجراء</button>';
        side.querySelector(".sl-side-tags").after(act);
      }
      side.hidden = false; wrap.classList.add("has-side");
      trs.forEach(r => r.dataset.sel = r === row ? "1" : "");
      document.querySelectorAll("[data-sl-card]").forEach(c => c.classList.toggle("is-sel", c.dataset.slCard === d.odId));
      loadSummary(row);
      const tl = document.createElement("section"); tl.className = "sl-sec sl-tl"; side.appendChild(tl);
      if (window.__slTimeline) window.__slTimeline(d.odId, tl);
    };
    const secEl = (title, count, body) => '<section class="sl-sec"><h4>' + title + (count != null ? ' <span class="sl-cnt">' + Number(count).toLocaleString("ar") + '</span>' : '') + '</h4>' + (body || '<p class="sl-none">لا يوجد</p>') + '</section>';
    const items = (arr, f) => arr && arr.length ? '<ul>' + arr.map(f).join("") + '</ul>' : "";
    const loadSummary = row => {
      const box = document.createElement("div");
      box.className = "sl-sum"; box.innerHTML = '<p class="sl-none">جارٍ تحميل الملخص…</p>';
      side.querySelector("dl").after(box);
      const url = row.dataset.odPreview;
      if (!url) return;
      fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" }).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(d => {
        if (!row.classList.contains("is-sel")) return;
        const c = d.summary_counts || {};
        const docs = d.attachments || [];
        box.innerHTML =
          secEl("الوصف", null, d.description ? '<p class="sl-desc">' + esc(d.description) + '</p>' : "") +
          secEl("المستندات", docs.length, items(docs.slice(0, 3), a => '<li>' + esc(a.doc_title) + ' <span class="sl-m">' + esc(a.doc_type) + '</span></li>')) +
          secEl("المذكرات", d.memos_count, items(d.summary_memos, m => '<li>' + esc(m.title) + ' <span class="sl-m">' + esc(m.status) + '</span></li>')) +
          secEl("الإحالات", c.referrals, items(d.recent_referrals, r => '<li>' + esc(r.referred_by) + ' ← ' + esc(r.targets) + ' <span class="sl-m">' + esc(r.created_at) + '</span></li>')) +
          secEl("المهام", c.tasks, items(d.summary_tasks, t => '<li>' + esc(t.title) + ' <span class="sl-m">' + esc(t.who) + ' · ' + esc(t.status) + '</span></li>')) +
          secEl("القرارات", c.decisions, items(d.summary_decisions, x => '<li>' + esc(x.number) + ' ' + esc(x.title) + ' <span class="sl-m">' + esc(x.status) + '</span></li>')) +
          secEl("آخر النشاط", null, items(d.summary_activity, a => '<li>' + esc(a.text) + ' <span class="sl-m">' + esc(a.who) + ' · ' + esc(a.at) + '</span></li>'));
      }).catch(() => { box.innerHTML = '<p class="sl-none">تعذّر عرض الملخص لهذا الموضوع.</p>'; });
    };
    const closeSide = () => { side.hidden = true; wrap.classList.remove("has-side"); trs.forEach(r => r.classList.remove("is-sel")); document.querySelectorAll("[data-sl-card]").forEach(c => c.classList.remove("is-sel")); };
    const byId = id => trs.find(r => r.dataset.odId === String(id));
    subjectList.querySelectorAll("[data-sl-card]").forEach(c => {
    });
    const tbl = subjectList.querySelector("[data-sl-table]"), cardsEl = subjectList.querySelector("[data-sl-cards]");
    subjectList.querySelectorAll("[data-sl-view]").forEach(b => b.addEventListener("click", () => {
      const cards = b.dataset.slView === "cards";
      cardsEl.hidden = !cards; tbl.hidden = cards;
      subjectList.querySelectorAll("[data-sl-view]").forEach(x => x.classList.toggle("on", x === b));
      try { localStorage.setItem("sl-view", b.dataset.slView); } catch (e) {}
    }));
    try { if (localStorage.getItem("sl-view") === "list") subjectList.querySelector('[data-sl-view="list"]').click(); else tbl.hidden = true; } catch (e) { tbl.hidden = true; }
    window.__slOpen = id => { const r = byId(id); if (r) openSide(r); };
    const openParam = new URLSearchParams(location.search).get("open");
    if (openParam) setTimeout(() => window.__slOpen(openParam), 0);
    subjectList.addEventListener("click", e => { const b = e.target.closest("[data-af-details]"); if (b) { e.stopPropagation(); window.__slOpen(b.dataset.afId); } });
    side?.addEventListener("click", e => { if (e.target.closest("[data-sl-close]")) closeSide(); });
    window.__slEsc = () => { if (!side.hidden) closeSide(); };
    subjectList.addEventListener("change", () => setTimeout(totals, 0));
    subjectList.addEventListener("input", () => setTimeout(totals, 0));
    subjectList.addEventListener("click", e => { if (e.target.closest("[data-subject-clear],[data-clear]")) setTimeout(totals, 0); });
    totals();
  }
  };
  window.__slInit();
  document.addEventListener("keydown", e => { if (e.key === "Escape" && window.__slEsc) window.__slEsc(); });

  // Subject registration: informational preview, section navigation, and file count.
  const subjectForm = document.querySelector("[data-subject-form]");
  if (subjectForm) {
    const title = subjectForm.querySelector("[data-subject-title]");
    const titlePreview = document.querySelector("[data-subject-title-preview]");
    const titleCount = subjectForm.querySelector("[data-subject-title-count]");
    const fileInput = subjectForm.querySelector("[data-subject-files]");
    const fileCount = subjectForm.querySelector("[data-subject-file-count]");
    const steps = [...subjectForm.querySelectorAll("[data-subject-step]")];
    const progress = document.querySelector("[data-subject-form-progress]");
    const navLinks = [...document.querySelectorAll(".subject-form-nav a")];
    const updateTitle = () => {
      const value = title?.value.trim() || "";
      if (titlePreview) titlePreview.textContent = value || "موضوع جديد بدون عنوان";
      if (titleCount) titleCount.textContent = (title?.value.length || 0).toLocaleString("ar") + " حرف";
    };
    const updateFiles = () => {
      if (!fileCount) return;
      const files = [...(fileInput?.files || [])];
      fileCount.textContent = files.length
        ? files.length.toLocaleString("ar") + " ملف: " + files.slice(0,3).map(file => file.name).join("، ") + (files.length > 3 ? "…" : "")
        : "لم يتم اختيار ملفات";
    };
    const updateProgress = () => {
      const completed = steps.filter(section => {
        const fields = [...section.querySelectorAll("input:not([type=hidden]):not([type=file]),select,textarea")];
        return fields.some(field => field.value.trim());
      }).length;
      if (progress) progress.textContent = completed.toLocaleString("ar") + " من " + steps.length.toLocaleString("ar") + " أقسام بها بيانات";
    };
    title?.addEventListener("input", updateTitle);
    subjectForm.addEventListener("input", updateProgress);
    subjectForm.addEventListener("change", updateProgress);
    fileInput?.addEventListener("change", updateFiles);
    navLinks.forEach(link => link.addEventListener("click", () => {
      const target = document.querySelector(link.getAttribute("href"));
      target?.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"start"});
    }));
    updateTitle();
    updateFiles();
    updateProgress();
  }


  // Document archive: local filters apply only to document cards on the current page.
  const documentRoot = document.querySelector("[data-docs]");
  if (documentRoot) {
    const cards = [...documentRoot.querySelectorAll("[data-document-card]")];
    const typeFilter = documentRoot.querySelector("[data-document-type-filter]");
    const confidentialityFilter = documentRoot.querySelector("[data-document-conf-filter]");
    const count = documentRoot.querySelector("[data-document-count]");
    const clear = documentRoot.querySelector("[data-document-clear]");
    const normalizeDocumentText = value => String(value || "").normalize("NFD")
      .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه").toLocaleLowerCase("ar");
    const fillFilter = (filter, key) => {
      const values = [...new Set(cards.map(card => card.dataset[key]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ar"));
      values.forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        filter?.appendChild(option);
      });
    };
    fillFilter(typeFilter,"docType");
    fillFilter(confidentialityFilter,"docConf");
    const applyDocumentFilters = () => {
      const type = typeFilter?.value || "";
      const confidentiality = confidentialityFilter?.value || "";
      let shown = 0;
      cards.forEach(card => {
        const matchesType = !type || card.dataset.docType === type;
        const matchesConfidentiality = !confidentiality || card.dataset.docConf === confidentiality;
        card.hidden = !(matchesType && matchesConfidentiality);
        if (!card.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + cards.length.toLocaleString("ar") + " مستند في الصفحة";
    };
    typeFilter?.addEventListener("change",applyDocumentFilters);
    confidentialityFilter?.addEventListener("change",applyDocumentFilters);
    clear?.addEventListener("click",()=>{
      if(typeFilter) typeFilter.value="";
      if(confidentialityFilter) confidentialityFilter.value="";
      applyDocumentFilters();
    });
    applyDocumentFilters();
  }

  // Document registration: title/file preview and section progress are informational only.
  const documentForm = document.querySelector("[data-document-form]");
  if (documentForm) {
    const title = documentForm.querySelector("[data-document-title]");
    const titlePreview = document.querySelector("[data-document-title-preview]");
    const titleCount = documentForm.querySelector("[data-document-title-count]");
    const file = documentForm.querySelector("[data-document-file]");
    const status = document.querySelector("[data-document-form-status]");
    const fileName = documentForm.querySelector("[data-document-file-name]");
    const steps = [...documentForm.querySelectorAll("[data-document-step]")];
    const navLinks = [...document.querySelectorAll(".document-form-nav a")];
    const updateTitle = () => {
      const value = title?.value.trim() || "";
      if(titlePreview) titlePreview.textContent = value || "مستند جديد بدون عنوان";
      if(titleCount) titleCount.textContent = (title?.value.length || 0).toLocaleString("ar") + " حرف";
    };
    const updateFile = () => {
      const selected = file?.files?.[0];
      if(fileName) fileName.textContent = selected ? selected.name : "لم يتم اختيار ملف";
      if(status) status.textContent = selected ? "تم اختيار المرفق الأولي: " + selected.name : "لم يتم اختيار المرفق بعد";
    };
    const updateProgress = () => {
      const completed = steps.filter(section => [...section.querySelectorAll("input:not([type=hidden]):not([type=file]),select,textarea")].some(field => String(field.value || "").trim())).length;
      if(status && !file?.files?.length) status.textContent = completed.toLocaleString("ar") + " من " + steps.length.toLocaleString("ar") + " أقسام بها بيانات";
    };
    title?.addEventListener("input",updateTitle);
    file?.addEventListener("change",updateFile);
    documentForm.addEventListener("input",updateProgress);
    documentForm.addEventListener("change",updateProgress);
    navLinks.forEach(link=>link.addEventListener("click",()=>{
      document.querySelector(link.getAttribute("href"))?.scrollIntoView({behavior:reduced?"auto":"smooth",block:"start"});
    }));
    updateTitle(); updateFile(); updateProgress();
  }

  // Attachment rows are keyboard reachable; don't intercept clicks on nested download links.
  document.addEventListener("keydown", event => {
    const row = event.target.closest("[data-doc-attachment][data-pv]");
    if (!row || event.target !== row || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    row.click();
  });


  // Referral creation: live recipient count, routing summary and notes length.
  const referralForm = document.querySelector("[data-referral-form]");
  if (referralForm) {
    const users = referralForm.querySelector("[data-referral-users]");
    const units = referralForm.querySelector("[data-referral-units]");
    const selectedCount = document.querySelector("[data-referral-selected-count]");
    const routingPreview = document.querySelector("[data-referral-routing-preview]");
    const notes = referralForm.querySelector("[data-referral-notes]");
    const notesCount = referralForm.querySelector("[data-referral-notes-count]");
    const routingLabels = new Map([...referralForm.querySelectorAll('input[name="routing_mode"]')].map(input=>[input.value,input.closest("label")?.querySelector("b")?.textContent.trim() || input.value]));
    const updateRecipients = () => {
      const userCount = [...(users?.selectedOptions || [])].length;
      const unitCount = [...(units?.selectedOptions || [])].length;
      const total = userCount + unitCount;
      if(selectedCount) selectedCount.textContent = total ? total.toLocaleString("ar") + " مستلم (" + userCount.toLocaleString("ar") + " موظف، " + unitCount.toLocaleString("ar") + " وحدة)" : "لم يتم اختيار مستلمين";
    };
    const updateRouting = () => {
      const selected = referralForm.querySelector('input[name="routing_mode"]:checked');
      if(routingPreview) routingPreview.textContent = selected ? (routingLabels.get(selected.value) || selected.value) : "لم تُحدد بعد";
    };
    const updateNotes = () => { if(notesCount) notesCount.textContent = (notes?.value.length || 0).toLocaleString("ar") + " حرف"; };
    users?.addEventListener("change",updateRecipients);
    units?.addEventListener("change",updateRecipients);
    referralForm.querySelectorAll('input[name="routing_mode"]').forEach(input=>input.addEventListener("change",updateRouting));
    notes?.addEventListener("input",updateNotes);
    referralForm.querySelectorAll(".referral-form-nav a").forEach(link=>link.addEventListener("click",()=>{
      document.querySelector(link.getAttribute("href"))?.scrollIntoView({behavior:reduced?"auto":"smooth",block:"start"});
    }));
    updateRecipients();updateRouting();updateNotes();
  }

  // Memo workspace: local search over the memos rendered for this subject only.
  const memoRoot = document.querySelector("#sec-memos");
  if(memoRoot) {
    const search=memoRoot.querySelector("[data-memo-search]");
    const clear=memoRoot.querySelector("[data-memo-clear]");
    const count=memoRoot.querySelector("[data-memo-count]");
    const items=[...memoRoot.querySelectorAll("[data-memo-item]")];
    const apply=()=>{
      const q=(search?.value || "").trim().toLocaleLowerCase("ar");
      let shown=0;
      items.forEach(item=>{item.hidden=!!q&&!item.textContent.toLocaleLowerCase("ar").includes(q);if(!item.hidden)shown++;});
      if(count)count.textContent=shown.toLocaleString("ar")+" من "+items.length.toLocaleString("ar")+" مذكرة";
    };
    search?.addEventListener("input",apply);
    clear?.addEventListener("click",()=>{if(search)search.value="";apply();search?.focus();});
    apply();
  }

  // Memo drafting: live preview, character count and attachment feedback; no new validation rules.
  const memoForm=document.querySelector("#action-memo form");
  if(memoForm) {
    const title=memoForm.querySelector("[data-memo-title]");
    const body=memoForm.querySelector("[data-memo-body]");
    const target=memoForm.querySelector("[data-memo-directed]");
    const customTarget=memoForm.querySelector("[data-memo-directed-custom]");
    const file=memoForm.querySelector("[data-memo-file]");
    const bodyCount=memoForm.querySelector("[data-memo-body-count]");
    const fileName=memoForm.querySelector("[data-memo-file-name]");
    const updateBody=()=>{if(bodyCount)bodyCount.textContent=(body?.value.length||0).toLocaleString("ar")+" حرف";};
    const updateFile=()=>{if(fileName)fileName.textContent=file?.files?.[0]?.name||"لم يتم اختيار مرفق";};
    const updateTitle=()=>{const preview=memoForm.querySelector("[data-memo-title-preview]");if(preview)preview.textContent=title?.value.trim()||"مذكرة جديدة";};
    const updateTarget=()=>{const preview=memoForm.querySelector("[data-memo-target-preview]");if(preview)preview.textContent=customTarget?.value.trim()||target?.value||"لم تُحدد جهة بعد";};
    title?.addEventListener("input",updateTitle);
    target?.addEventListener("change",()=>{if(customTarget&&!customTarget.value.trim())customTarget.placeholder=target.value?"يمكنك اختيار جهة أخرى بدلاً من "+target.value:"اكتب الجهة يدوياً";updateTarget();});
    customTarget?.addEventListener("input",updateTarget);
    body?.addEventListener("input",updateBody);
    file?.addEventListener("change",updateFile);
    updateTitle();updateTarget();updateBody();updateFile();
  }


  // Phase 16: local account and organization workbench enhancements.
  const accountUsers = document.querySelector("[data-account-users]");
  if (accountUsers) {
    const search = accountUsers.querySelector("[data-filter]");
    const rows = [...accountUsers.querySelectorAll("[data-account-user-row]")];
    const count = accountUsers.querySelector("[data-account-user-count]");
    const update = () => {
      const q = (search?.value || "").trim().toLocaleLowerCase("ar");
      let shown = 0;
      rows.forEach(row => { row.hidden = !!q && !row.textContent.toLocaleLowerCase("ar").includes(q); if (!row.hidden) shown++; });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " مستخدم في الصفحة";
    };
    search?.addEventListener("input", update);
    update();
  }

  const permissionMatrix = document.querySelector("[data-permission-matrix]");
  if (permissionMatrix) {
    const search = permissionMatrix.querySelector("[data-permission-search]");
    const rows = [...permissionMatrix.querySelectorAll("[data-permission-row]")];
    const categories = [...permissionMatrix.querySelectorAll("[data-permission-category]")];
    const count = permissionMatrix.querySelector("[data-permission-count]");
    const update = () => {
      const q = (search?.value || "").trim().toLocaleLowerCase("ar");
      let shown = 0;
      rows.forEach(row => { row.hidden = !!q && !row.textContent.toLocaleLowerCase("ar").includes(q); if (!row.hidden) shown++; });
      categories.forEach(category => {
        let next = category.nextElementSibling, hasVisible = false;
        while (next && !next.hasAttribute("data-permission-category")) {
          if (next.matches("[data-permission-row]") && !next.hidden) hasVisible = true;
          next = next.nextElementSibling;
        }
        category.hidden = !!q && !hasVisible;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " صلاحية معروضة";
    };
    search?.addEventListener("input", update);
    update();
  }

  const delegationRoot = document.querySelector("[data-delegations]");
  if (delegationRoot) {
    const search = delegationRoot.querySelector("[data-delegation-search]");
    const rows = [...delegationRoot.querySelectorAll("[data-delegation-row]")];
    const count = delegationRoot.querySelector("[data-delegation-count]");
    const update = () => {
      const q = (search?.value || "").trim().toLocaleLowerCase("ar");
      let shown = 0;
      rows.forEach(row => { row.hidden = !!q && !row.textContent.toLocaleLowerCase("ar").includes(q); if (!row.hidden) shown++; });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " تفويض في السجل المعروض";
    };
    search?.addEventListener("input", update);
    update();
  }

  const orgSearch = document.querySelector("[data-org-search]");
  const orgRoot = document.querySelector("#org-root");
  if (orgSearch && orgRoot) {
    const count = document.querySelector("[data-org-count]");
    const normalizeOrg = value => String(value || "").toLocaleLowerCase("ar").normalize("NFD")
      .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه");
    const update = () => {
      const q = normalizeOrg(orgSearch.value.trim());
      orgSearch.closest(".org-tools")?.classList.toggle("searching", !!q);
      let matched = 0, total = 0;
      const filterBranch = branch => {
        total++;
        const ownText = normalizeOrg(branch.dataset.orgSearchText);
        const ownMatch = !q || ownText.includes(q);
        const children = [...branch.querySelectorAll(":scope > .org-kids > .org-branch")];
        const childMatch = children.map(filterBranch).some(Boolean);
        const visible = ownMatch || childMatch;
        branch.hidden = !visible;
        if (q && ownMatch) matched++;
        return visible;
      };
      [...orgRoot.children].filter(child => child.classList.contains("org-branch")).forEach(filterBranch);
      if (count) count.textContent = q ? matched.toLocaleString("ar") + " وحدة مطابقة ضمن " + total.toLocaleString("ar") + " وحدة" : "عرض " + total.toLocaleString("ar") + " وحدة";
    };
    orgSearch.addEventListener("input", update);
    const observer = new MutationObserver(update);
    observer.observe(orgRoot, {childList:true,subtree:true});
    update();
  }


  // Phase 17 — local reading tools for audit and committee screens.
  const normalizePhase17 = value => String(value || "").normalize("NFD")
    .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
    .toLocaleLowerCase("ar");

  const auditWorkspace = document.querySelector("[data-audit-workspace]");
  if (auditWorkspace) {
    const search = auditWorkspace.querySelector("[data-audit-search]");
    const count = auditWorkspace.querySelector("[data-audit-count]");
    const rows = [...auditWorkspace.querySelectorAll("[data-audit-table] tbody tr")]
      .filter(row => row.hasAttribute("data-audit-row"));
    const update = () => {
      const tokens = normalizePhase17(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach(row => {
        const haystack = normalizePhase17(row.textContent);
        row.hidden = !tokens.every(token => haystack.includes(token));
        if (!row.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " سجل معروض";
    };
    search?.addEventListener("input", update);
    update();
  }

  const committeeWorkspace = document.querySelector("[data-committee-workspace]");
  if (committeeWorkspace) {
    const search = committeeWorkspace.querySelector("[data-committee-search]");
    const count = committeeWorkspace.querySelector("[data-committee-count]");
    const meetings = [...document.querySelectorAll("[data-committee-meeting]")];
    const committees = [...document.querySelectorAll("[data-committee-search-item]")];
    const topicGroups = [...document.querySelectorAll("[data-committee-topic-group]")];
    const update = () => {
      const tokens = normalizePhase17(search?.value).split(/\s+/).filter(Boolean);
      let shownMeetings = 0, shownCommittees = 0;
      meetings.forEach(item => {
        const haystack = normalizePhase17(item.textContent);
        const match = tokens.every(token => haystack.includes(token));
        item.classList.toggle("ux-local-hidden", !match);
        if (match) shownMeetings++;
      });
      committees.forEach(item => {
        const haystack = normalizePhase17(item.textContent);
        const match = tokens.every(token => haystack.includes(token));
        item.classList.toggle("ux-local-hidden", !match);
        if (match) shownCommittees++;
      });
      topicGroups.forEach(group => {
        const nameHit = tokens.every(token => normalizePhase17(group.querySelector("[data-committee-topic-name]")?.textContent).includes(token));
        let any = false;
        group.querySelectorAll("[data-committee-topic]").forEach(row => {
          const hit = nameHit || tokens.every(token => normalizePhase17(row.textContent + " " + (group.querySelector("[data-committee-topic-name]")?.textContent || "")).includes(token));
          row.classList.toggle("ux-local-hidden", !hit);
          if (hit) any = true;
        });
        group.classList.toggle("ux-local-hidden", !any);
      });
      if (count) count.textContent = shownMeetings.toLocaleString("ar") + " اجتماع · " + shownCommittees.toLocaleString("ar") + " لجنة";
    };
    search?.addEventListener("input", update);
    update();
  }

  const agendaRoot = document.querySelector("[data-committee-agenda]");
  if (agendaRoot) {
    const search = document.querySelector("[data-agenda-search]");
    const count = document.querySelector("[data-agenda-count]");
    const items = [...agendaRoot.querySelectorAll("[data-agenda-item]")];
    const update = () => {
      const tokens = normalizePhase17(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      items.forEach(item => {
        const haystack = normalizePhase17(item.textContent);
        item.hidden = !tokens.every(token => haystack.includes(token));
        if (!item.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + items.length.toLocaleString("ar") + " بند";
    };
    search?.addEventListener("input", update);
    update();
  }


  // Phase 18 — report catalog and result-table reading tools.
  const normalizeReportText = value => String(value || "").normalize("NFD")
    .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
    .toLocaleLowerCase("ar");

  const reportCatalog = document.querySelector("[data-report-catalog]");
  if (reportCatalog) {
    const search = reportCatalog.querySelector("[data-report-catalog-search]");
    const count = reportCatalog.querySelector("[data-report-catalog-count]");
    const cards = [...reportCatalog.querySelectorAll("[data-report-card]")];
    const update = () => {
      const tokens = normalizeReportText(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      cards.forEach(card => {
        const haystack = normalizeReportText(card.textContent);
        card.hidden = !tokens.every(token => haystack.includes(token));
        if (!card.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + cards.length.toLocaleString("ar") + " تقرير متاح";
    };
    search?.addEventListener("input", update);
    update();
  }

  const reportTable = document.querySelector("[data-report-table]");
  if (reportTable) {
    const search = reportTable.querySelector("[data-report-row-search]");
    const count = reportTable.querySelector("[data-report-row-count]");
    const rows = [...reportTable.querySelectorAll("[data-report-row]")];
    const update = () => {
      const tokens = normalizeReportText(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach(row => {
        const haystack = normalizeReportText(row.textContent);
        row.hidden = !tokens.every(token => haystack.includes(token));
        if (!row.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " صف معروض";
    };
    search?.addEventListener("input", update);
    update();
  }


  // Phase 19 — settings and workflow-template browsing; local to rendered records.
  const normalizePhase19 = value => String(value || "").normalize("NFD")
    .replace(/[\u0300-\u036f\u064B-\u065F\u0670\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
    .toLocaleLowerCase("ar");

  const settingsWorkspace = document.querySelector("[data-settings-workspace]");
  if (settingsWorkspace) {
    const search = settingsWorkspace.querySelector("[data-settings-search]");
    const count = settingsWorkspace.querySelector("[data-settings-count]");
    const rows = [...settingsWorkspace.querySelectorAll("[data-settings-row]")];
    const empty = settingsWorkspace.querySelector("[data-settings-empty]");
    const update = () => {
      const tokens = normalizePhase19(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      rows.forEach(row => {
        const haystack = normalizePhase19(row.textContent);
        row.hidden = !tokens.every(token => haystack.includes(token));
        if (!row.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + rows.length.toLocaleString("ar") + " عنصر";
      if (empty) empty.hidden = shown !== 0 || rows.length === 0;
    };
    search?.addEventListener("input", update);
    update();
  }

  const templateWorkspace = document.querySelector("[data-workflow-template-workspace]");
  if (templateWorkspace) {
    const search = document.querySelector("[data-workflow-template-search]");
    const count = document.querySelector("[data-workflow-template-count]");
    const cards = [...templateWorkspace.querySelectorAll("[data-workflow-template-card]")];
    const empty = document.querySelector("[data-workflow-template-empty]");
    const update = () => {
      const tokens = normalizePhase19(search?.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      cards.forEach(card => {
        const haystack = normalizePhase19(card.textContent);
        card.hidden = !tokens.every(token => haystack.includes(token));
        if (!card.hidden) shown++;
      });
      if (count) count.textContent = shown.toLocaleString("ar") + " من " + cards.length.toLocaleString("ar") + " قالب";
      if (empty) empty.hidden = shown !== 0 || cards.length === 0;
    };
    search?.addEventListener("input", update);
    update();
  }



  // Shared active-filter chips for list workspaces; resets the existing controls only.
  document.querySelectorAll("[data-filter-chip-root]").forEach(root => {
    const holder = root.querySelector("[data-filter-chips]");
    const controls = [...root.querySelectorAll("[data-filter-chip]")];
    if (!holder || !controls.length) return;
    const update = () => {
      holder.textContent = "";
      controls.forEach(control => {
        const raw = control.type === "checkbox" ? (control.checked ? "1" : "") : String(control.value || "").trim();
        if (!raw) return;
        const selected = control.tagName === "SELECT" ? control.options[control.selectedIndex]?.textContent?.trim() : raw;
        const chip = document.createElement("button");
        chip.type = "button"; chip.className = "chip";
        chip.textContent = (control.dataset.filterChip || "تصفية") + ": " + selected + " ×";
        chip.setAttribute("aria-label", "إزالة فلتر " + (control.dataset.filterChip || "التصفية"));
        chip.addEventListener("click", () => {
          if (control.type === "checkbox") control.checked = false; else control.value = "";
          control.dispatchEvent(new Event("input", { bubbles: true }));
          control.dispatchEvent(new Event("change", { bubbles: true }));
          if (control.hasAttribute("data-filter-chip-submit") && control.form && control.form.method.toLowerCase() === "get") control.form.requestSubmit();
          update();
        });
        holder.append(chip);
      });
      holder.hidden = holder.childElementCount === 0;
    };
    controls.forEach(control => { control.addEventListener("input", update); control.addEventListener("change", update); });
    root.querySelectorAll("[data-subject-clear],[data-document-clear],[data-decision-clear],[data-task-clear],[data-referral-clear],[data-notification-clear]").forEach(button => button.addEventListener("click", () => window.setTimeout(update, 0)));
    update();
  });

  // Phase 20 — accessible global navigation state and collapsed-rail labels.
  const railElement = document.querySelector("#main-rail");
  const railToggle = document.querySelector("[data-rail-toggle]");
  const syncRailState = () => {
    if (!railElement || !railToggle) return;
    const mobile = window.innerWidth <= 1000;
    const shell = railElement.closest(".shell");
    const expanded = mobile ? railElement.classList.contains("open") : !(shell && shell.classList.contains("collapsed"));
    railToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    railElement.querySelectorAll(".nav").forEach(link => {
      if (link.classList.contains("on")) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
      if (!mobile && shell?.classList.contains("collapsed")) {
        if (link.dataset.label) link.setAttribute("title", link.dataset.label);
      } else if (link.dataset.label) {
        link.removeAttribute("title");
      }
    });
  };
  syncRailState();
  document.addEventListener("click", event => {
    if (event.target.closest("[data-rail-toggle],#scrim,.rail .nav")) {
      window.setTimeout(syncRailState, 0);
    }
  });
  window.addEventListener("resize", syncRailState, { passive: true });

  document.documentElement.classList.add("ux-ready");
})();
