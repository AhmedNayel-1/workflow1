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
  // Search the currently selected referrals tab without changing server-side results.
  const referralRoot = document.querySelector("[data-tabs-root] .tabs")?.parentElement;
  if (referralRoot) {
    const search = referralRoot.querySelector("[data-referral-search]");
    const count = referralRoot.querySelector("[data-referral-count]");
    const clear = referralRoot.querySelector("[data-referral-clear]");
    const apply = () => {
      const pane = referralRoot.querySelector("[data-pane].on") || referralRoot.querySelector("[data-pane]");
      if (!pane) return;
      const q = (search?.value || "").trim().toLocaleLowerCase("ar");
      const items = Array.from(pane.querySelectorAll("[data-referral-item]"));
      let shown = 0;
      items.forEach(item => {
        const match = !q || item.textContent.toLocaleLowerCase("ar").includes(q);
        item.hidden = !match;
        if (match) shown++;
      });
      if (count) count.textContent = shown + " من " + items.length + " إحالة";
    };
    search?.addEventListener("input", apply);
    clear?.addEventListener("click", () => { if (search) search.value = ""; apply(); search?.focus(); });
    referralRoot.querySelectorAll("[data-tab]").forEach(tab => tab.addEventListener("click", () => requestAnimationFrame(apply)));
    apply();
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
      .normalize("NFD").replace(/[\\u064B-\\u065F\\u0670\\u0640]/g, "")
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
      const tokens = normalizeDecisionText(search?.value).split(/\\s+/).filter(Boolean);
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
  document.documentElement.classList.add("ux-ready");
})();
