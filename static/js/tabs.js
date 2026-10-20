/* Lumen Tabs behaviour that CSS alone cannot give (design/lumen/components/Tabs.md):

   1. One indicator that slides to the selected tab (130ms; reduced motion
      turns the slide off in CSS).
   2. Overflow: a horizontal `.tab-strip` that no longer fits its container
      collapses into a picker listing every tab, and expands again when there
      is room. Choosing from the picker clicks the real tab, so whatever the tab
      does (switch a panel, follow a link) happens exactly as before.

   Works on any `.tab-strip`; the selected tab is the one with
   `.tab-strip-item-active`, aria-selected="true" or aria-current="page".
   Selection changes made by Alpine are picked up with a MutationObserver.
   Without this script tabs still work: each selected tab draws its own
   indicator and the strip scrolls sideways. */
(function () {
  "use strict";

  var SELECTED = ".tab-strip-item-active, .tab-strip-item[aria-selected='true'], .tab-strip-item[aria-current='page']";
  var uid = 0;

  // A tab's name without its row count ("Databases", not "Databases3").
  function label(tab) {
    var inner = (tab.querySelector(".tab-label") || tab).cloneNode(true);
    inner.querySelectorAll(".tab-count").forEach(function (count) { count.remove(); });
    return inner.textContent.replace(/\s+/g, " ").trim();
  }

  function setup(strip) {
    var vertical = strip.classList.contains("tab-strip-vertical");
    var indicator = document.createElement("span");
    indicator.className = "tab-indicator";
    indicator.setAttribute("aria-hidden", "true");
    strip.appendChild(indicator);
    strip.setAttribute("data-tabs-ready", "");

    function place() {
      var tab = strip.querySelector(SELECTED);
      indicator.hidden = !tab;
      if (!tab) return;
      if (vertical) {
        indicator.style.transform = "translateY(" + tab.offsetTop + "px)";
        indicator.style.height = tab.offsetHeight + "px";
      } else {
        indicator.style.transform = "translateX(" + tab.offsetLeft + "px)";
        indicator.style.width = tab.offsetWidth + "px";
      }
      if (picker) picker.querySelector("[data-picker-label]").textContent = label(tab);
    }

    // --- Overflow picker (horizontal strips only) -------------------------
    var bar = null, picker = null, menu = null;
    if (!vertical) {
      bar = document.createElement("div");
      bar.className = "tabs-bar";
      strip.parentNode.insertBefore(bar, strip);
      bar.appendChild(strip);

      var id = "tabs-picker-" + (++uid);
      picker = document.createElement("button");
      picker.type = "button";
      picker.className = "tabs-picker";
      picker.hidden = true;
      picker.setAttribute("aria-expanded", "false");
      picker.setAttribute("aria-controls", id);
      // The picker says which tab is shown; the list's own name prefixes it
      // for screen readers ("Skill categories: Databases").
      var name = document.createElement("span");
      name.className = "sr-only";
      name.textContent = (strip.getAttribute("aria-label") || "") + ": ";
      picker.innerHTML =
        '<span data-picker-label></span>' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6"/></svg>';
      menu = document.createElement("ul");
      menu.id = id;
      menu.className = "surface-menu absolute left-0 top-full z-40 mt-spacing-100 min-w-[12rem]";
      menu.hidden = true;
      if (strip.getAttribute("aria-label")) picker.insertBefore(name, picker.firstChild);
      bar.appendChild(picker);
      bar.appendChild(menu);

      function close(focusPicker) {
        menu.hidden = true;
        picker.setAttribute("aria-expanded", "false");
        if (focusPicker) picker.focus();
      }
      function open() {
        menu.innerHTML = "";
        strip.querySelectorAll(".tab-strip-item").forEach(function (tab) {
          var li = document.createElement("li");
          var item = document.createElement("button");
          item.type = "button";
          item.className = "menu-item rounded-corner-radius-300";
          item.textContent = label(tab);
          if (tab.matches(SELECTED)) {
            item.setAttribute("aria-current", "true");
            item.classList.add("font-bold", "text-content-heading");
          }
          if (tab.disabled || tab.getAttribute("aria-disabled") === "true") item.disabled = true;
          item.addEventListener("click", function () {
            close(true);
            tab.click();
          });
          li.appendChild(item);
          menu.appendChild(li);
        });
        menu.hidden = false;
        picker.setAttribute("aria-expanded", "true");
        var current = menu.querySelector("[aria-current]") || menu.querySelector("button:not([disabled])");
        if (current) current.focus();
      }
      picker.addEventListener("click", function () {
        if (menu.hidden) open(); else close(false);
      });
      menu.addEventListener("keydown", function (event) {
        var items = Array.prototype.slice.call(menu.querySelectorAll("button:not([disabled])"));
        var i = items.indexOf(document.activeElement);
        if (event.key === "Escape") { event.preventDefault(); close(true); }
        else if (event.key === "ArrowDown") { event.preventDefault(); items[(i + 1) % items.length].focus(); }
        else if (event.key === "ArrowUp") { event.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
        else if (event.key === "Home") { event.preventDefault(); items[0].focus(); }
        else if (event.key === "End") { event.preventDefault(); items[items.length - 1].focus(); }
        else if (event.key === "Tab") { close(false); }
      });
      document.addEventListener("click", function (event) {
        if (!menu.hidden && !bar.contains(event.target)) close(false);
      });

      var fit = function () {
        // Measure with the strip in its expanded form, then decide.
        bar.classList.remove("tabs-bar-collapsed");
        var overflowing = strip.scrollWidth > bar.clientWidth + 1;
        bar.classList.toggle("tabs-bar-collapsed", overflowing);
        picker.hidden = !overflowing;
        if (!overflowing) close(false);
        place();
      };
      if (window.ResizeObserver) new ResizeObserver(fit).observe(bar);
      else window.addEventListener("resize", fit);
      fit();
    }

    new MutationObserver(place).observe(strip, {
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "aria-selected", "aria-current"],
    });
    window.addEventListener("resize", place);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(place);
    place();
  }

  function init() {
    document.querySelectorAll(".tab-strip").forEach(setup);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
