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
    const search = referralRoot.querySelector("[data-referral-search]");
    const statusFilter = referralRoot.querySelector("[data-referral-status]");
    const dueFilter = referralRoot.querySelector("[data-referral-due]");
    const count = referralRoot.querySelector("[data-referral-count]");
    const clear = referralRoot.querySelector("[data-referral-clear]");
    const normalizeReferralText = value => String(value || "").normalize("NFD")
      .replace(/[\\u0300-\\u036f\\u064B-\\u065F\\u0670\\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه").toLocaleLowerCase("ar");
    const applyReferralFilters = () => {
      const pane = referralRoot.querySelector("[data-pane].on") || referralRoot.querySelector("[data-pane]");
      if (!pane) return;
      const tokens = normalizeReferralText(search?.value).split(/\\s+/).filter(Boolean);
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
  const subjectList = document.querySelector("[data-subject-list]");
  if (subjectList) {
    const search = subjectList.querySelector("[data-subject-search]");
    const rows = [...subjectList.querySelectorAll("[data-subject-row]")];
    const count = subjectList.querySelector("[data-subject-count]");
    const clear = subjectList.querySelector("[data-subject-clear]");
    const total = rows.length;
    const normalizeSubjectText = value => String(value || "")
      .normalize("NFD").replace(/[\\u0300-\\u036f\\u064B-\\u065F\\u0670\\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
      .toLocaleLowerCase("ar");
    const applySubjectSearch = () => {
      const tokens = normalizeSubjectText(search?.value).split(/\\s+/).filter(Boolean);
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
      .replace(/[\\u0300-\\u036f\\u064B-\\u065F\\u0670\\u0640]/g, "")
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
      .replace(/[\\u0300-\\u036f\\u064B-\\u065F\\u0670\\u0640]/g, "")
      .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه");
    const update = () => {
      const q = normalizeOrg(orgSearch.value.trim());
      let matched = 0, total = 0;
      const filterBranch = branch => {
        total++;
        const ownText = normalizeOrg(branch.dataset.orgSearchText);
        const ownMatch = !q || ownText.includes(q);
        const children = [...branch.children].filter(child => child.classList.contains("org-branch"));
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
    .replace(/[\\u0300-\\u036f\\u064B-\\u065F\\u0670\\u0640]/g, "")
    .replace(/[أإآٱ]/g, "ا").replace(/[ىئ]/g, "ي").replace(/ة/g, "ه")
    .toLocaleLowerCase("ar");

  const auditWorkspace = document.querySelector("[data-audit-workspace]");
  if (auditWorkspace) {
    const search = auditWorkspace.querySelector("[data-audit-search]");
    const count = auditWorkspace.querySelector("[data-audit-count]");
    const rows = [...auditWorkspace.querySelectorAll("[data-audit-table] tbody tr")]
      .filter(row => row.hasAttribute("data-audit-row"));
    const update = () => {
      const tokens = normalizePhase17(search?.value).split(/\\s+/).filter(Boolean);
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
    const meetings = [...committeeWorkspace.querySelectorAll("[data-committee-meeting]")];
    const committees = [...committeeWorkspace.querySelectorAll("[data-committee-search-item]")];
    const update = () => {
      const tokens = normalizePhase17(search?.value).split(/\\s+/).filter(Boolean);
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
      const tokens = normalizePhase17(search?.value).split(/\\s+/).filter(Boolean);
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

  document.documentElement.classList.add("ux-ready");
})();
