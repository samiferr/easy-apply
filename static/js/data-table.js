/* Data tables: live search and column sorting for the app's lists.

   Markup contract (templates/partials/_table_search.html renders the toolbar):

     <div data-table>
       <input type="search" data-table-search aria-controls="...">
       <p data-table-status aria-live="polite"></p>
       <table> ... <th aria-sort="none"><button data-sort>Name</button></th> ...
         <tbody> <tr data-row data-search="extra words"> <td data-sort-value="...">
       <p data-table-empty hidden>No match</p>
       <span data-count-for="panel-id"></span>   (optional: a tab's row count)
     </div>

   Rows match when every word of the query appears in the row's text (or its
   data-search), ignoring case and accents. Sorting toggles ascending /
   descending and is reflected in aria-sort on the header. Without JavaScript
   the table is simply complete and unsorted: the search box is hidden until
   this script runs. */
(function () {
  "use strict";

  var fold = function (text) {
    return (text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  };

  function setup(root) {
    var input = root.querySelector("[data-table-search]");
    var status = root.querySelector("[data-table-status]");
    var rows = Array.prototype.slice.call(root.querySelectorAll("tr[data-row]"));
    var haystacks = rows.map(function (row) {
      return fold(row.textContent + " " + (row.getAttribute("data-search") || ""));
    });
    var template = status ? status.getAttribute("data-template") || "{shown} / {total}" : "";

    function filter() {
      var words = fold(input ? input.value : "").split(/\s+/).filter(Boolean);
      var shown = 0;
      rows.forEach(function (row, i) {
        var match = words.every(function (word) { return haystacks[i].indexOf(word) !== -1; });
        row.hidden = !match;
        if (match) shown += 1;
      });
      root.querySelectorAll("[data-count-for]").forEach(function (counter) {
        var panel = document.getElementById(counter.getAttribute("data-count-for"));
        if (panel) counter.textContent = panel.querySelectorAll("tr[data-row]:not([hidden])").length;
      });
      // Each "nothing matches" note watches the rows of its own container, so a
      // page with one table per tab panel says it per panel.
      root.querySelectorAll("[data-table-empty]").forEach(function (empty) {
        var own = empty.parentElement.querySelectorAll("tr[data-row]");
        var visible = empty.parentElement.querySelectorAll("tr[data-row]:not([hidden])");
        empty.hidden = visible.length !== 0 || own.length === 0;
      });
      if (status) {
        status.textContent = words.length
          ? template.replace("{shown}", shown).replace("{total}", rows.length)
          : "";
      }
    }

    if (input) {
      input.closest("[data-table-toolbar]").hidden = false;
      input.addEventListener("input", filter);
      // Escape clears the search, the way a native search field does.
      input.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && input.value) {
          input.value = "";
          filter();
        }
      });
    }

    root.querySelectorAll("th [data-sort]").forEach(function (button) {
      button.addEventListener("click", function () {
        var th = button.closest("th");
        var table = th.closest("table");
        var index = Array.prototype.indexOf.call(th.parentNode.children, th);
        var ascending = th.getAttribute("aria-sort") !== "ascending";
        table.querySelectorAll("th[aria-sort]").forEach(function (other) {
          other.setAttribute("aria-sort", "none");
        });
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        var body = table.tBodies[0];
        var sorted = Array.prototype.slice.call(body.rows).sort(function (a, b) {
          var x = key(a.cells[index]);
          var y = key(b.cells[index]);
          var order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" });
          return ascending ? order : -order;
        });
        sorted.forEach(function (row) { body.appendChild(row); });
      });
    });

    function key(cell) {
      if (!cell) return "";
      var raw = cell.getAttribute("data-sort-value");
      if (raw === null) return cell.textContent.trim();
      var number = Number(raw);
      return raw !== "" && !isNaN(number) ? number : raw;
    }
  }

  function init() {
    document.querySelectorAll("[data-table]").forEach(setup);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
