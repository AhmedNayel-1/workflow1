/* ملء الشاشة: المتصفح يمنع الدخول التلقائي دون ضغطة من المستخدم، لذلك يبدأ عند أول ضغطة. */
(function () {
  var KEY = "fs-want", de = document.documentElement;
  var isFs = function () { return !!document.fullscreenElement; };
  var enter = function () { if (!isFs() && de.requestFullscreen) { var p = de.requestFullscreen(); if (p && p.catch) p.catch(function () {}); } };
  var leave = function () { if (isFs() && document.exitFullscreen) document.exitFullscreen(); };
  var want = function () { try { return localStorage.getItem(KEY) !== "0"; } catch (e) { return true; } };
  var set = function (v) { try { localStorage.setItem(KEY, v ? "1" : "0"); } catch (e) {} };
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-fs-toggle]");
    if (t) { e.preventDefault(); if (isFs()) { set(false); leave(); } else { set(true); enter(); } return; }
    if (want() && !isFs()) enter();
  }, true);
  document.addEventListener("keydown", function () { if (want() && !isFs()) enter(); }, true);
})();
