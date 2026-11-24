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
  document.documentElement.classList.add("ux-ready");
})();
