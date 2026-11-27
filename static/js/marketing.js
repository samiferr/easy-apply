// Marketing page: the mobile menu and dismissible announcements. Everything
// else on the page works without JavaScript, so this only enhances the header
// (the menu button is hidden behind the `.js` class set in base_marketing.html).
(function () {
  "use strict";

  // Announcements: dismissed per browser, under the key the app uses too.
  // Storage can be blocked (private windows, strict settings); then the notice
  // simply stays visible.
  document.querySelectorAll("[data-announcement][data-dismissible]").forEach(function (banner) {
    var key = banner.getAttribute("data-announcement");
    try {
      if (localStorage.getItem(key) === "dismissed") banner.hidden = true;
    } catch (e) {}
    var close = banner.querySelector("[data-dismiss]");
    if (close) {
      close.addEventListener("click", function () {
        banner.hidden = true;
        try { localStorage.setItem(key, "dismissed"); } catch (e) {}
      });
    }
  });

  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.getElementById("primary-nav");
  if (!toggle || !nav) return;

  function setOpen(open) {
    toggle.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("is-open", open);
  }

  toggle.addEventListener("click", function () {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  // Choosing an in-page link closes the menu so the section is visible.
  nav.addEventListener("click", function (event) {
    if (event.target.closest('a[href^="#"]')) setOpen(false);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
      setOpen(false);
      toggle.focus();
    }
  });
})();
