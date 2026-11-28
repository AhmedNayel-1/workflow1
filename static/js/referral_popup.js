/* نافذة إحالة مدمجة: الضغط على رابط الإحالة يفتح نموذجاً مختصراً بدل صفحة كاملة. */
(function () {
  var re = /\/workflow\/referrals\/create\/(\d+)\/?$/;
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || a.hasAttribute("data-rf-cancel")) return;
    var path = a.getAttribute("href").split("?")[0];
    if (!re.test(path) || typeof HTMLDialogElement === "undefined") return;
    e.preventDefault();
    fetch(path + "?partial=1", { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (html) {
      var d = document.createElement("dialog");
      d.className = "rf-dlg";
      d.innerHTML = '<div class="rf-dlg-h"><b>إحالة الموضوع</b><a href="' + path + '" data-rf-cancel>فتح الصفحة الكاملة</a></div><div data-rf-body></div>';
      var body = d.querySelector("[data-rf-body]");
      body.innerHTML = html;
      body.querySelectorAll("script").forEach(function (s) { var n = document.createElement("script"); n.textContent = s.textContent; s.replaceWith(n); });
      var cancel = body.querySelector(".rf-act [data-rf-cancel]");
      if (cancel) cancel.addEventListener("click", function (ev) { ev.preventDefault(); d.close(); });
      d.addEventListener("close", function () { d.remove(); });
      document.body.appendChild(d);
      d.showModal();
    }).catch(function () { window.location.href = a.href; });
  });
})();
