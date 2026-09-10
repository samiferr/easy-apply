/* Job analysis page: section rail, add-to-profile modal, per-element
 * re-evaluation. Alpine + fetch (no HTMX), per the refactor spec §4 and §7.5.
 */
function jobAnalysis(jobId, firstKey) {
  return {
    jobId: jobId,
    active: window.location.hash ? window.location.hash.slice(1) : firstKey,
    sections: {},
    summary: { score_percent: 0, strong: 0, partial: 0, none: 0, total: 0 },
    modalOpen: false,
    modalHtml: "",
    modalElementId: null,
    modalSubmitting: false,
    pendingElements: [],
    statePoll: null,
    stateStartedAt: Date.now(),

    init() {
      this.refreshState();
      window.addEventListener("hashchange", () => {
        const key = window.location.hash.slice(1);
        if (key) this.active = key;
      });
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
          this.stopStatePoll();
        } else {
          this.refreshState();
        }
      });
    },

    select(key) {
      this.active = key;
      history.replaceState(null, "", "#" + key);
    },

    stateOf(key) {
      const s = this.sections[key];
      return s ? s.state : "idle";
    },

    countOf(key, bucket) {
      const s = this.sections[key];
      return s ? s[bucket] : 0;
    },

    stopStatePoll() {
      if (this.statePoll) {
        clearTimeout(this.statePoll);
        this.statePoll = null;
      }
    },

    stateInterval() {
      return Date.now() - this.stateStartedAt > 30000 ? 5000 : 2000;
    },

    /* One call returns every section's state — no 13 separate requests. */
    async refreshState() {
      if (document.visibilityState === "hidden") return;
      try {
        const res = await fetch(`/jobs/${this.jobId}/analysis-state/`, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!res.ok) return;
        const data = await res.json();
        const next = {};
        data.sections.forEach((s) => { next[s.key] = s; });
        this.sections = next;
        this.summary = data.summary;

        if (data.is_running) {
          this.stopStatePoll();
          this.statePoll = setTimeout(() => this.refreshState(), this.stateInterval());
        } else {
          this.stopStatePoll();
          if (this.reloadWhenIdle) {
            this.reloadWhenIdle = false;
            window.location.reload();
          }
        }
      } catch (err) {
        this.stopStatePoll();
      }
    },

    csrf() {
      const el = document.querySelector("[name=csrfmiddlewaretoken]");
      return el ? el.value : "";
    },

    /* --- Add to my profile ------------------------------------------- */
    async openAdd(elementId) {
      try {
        const res = await fetch(`/jobs/${this.jobId}/elements/${elementId}/add/`, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await res.json();
        if (!data.ok) return;
        this.modalHtml = data.modal_html;
        this.modalElementId = elementId;
        this.modalOpen = true;
      } catch (err) { /* leave the page as-is */ }
    },

    closeAdd() {
      this.modalOpen = false;
      this.modalHtml = "";
      this.modalElementId = null;
      this.modalSubmitting = false;
    },

    async submitAdd(event, elementId) {
      this.modalSubmitting = true;
      const form = event.target;
      try {
        const res = await fetch(form.action, {
          method: "POST",
          headers: { "X-Requested-With": "XMLHttpRequest" },
          body: new FormData(form),
        });
        const data = await res.json();

        if (!data.ok) {
          /* A duplicate or validation error comes back in the modal. */
          if (data.modal_html) this.modalHtml = data.modal_html;
          this.modalSubmitting = false;
          return;
        }

        this.closeAdd();
        this.swapRow(elementId, data.row_html);
        this.trackElement(elementId, data.task_id);
      } catch (err) {
        this.modalSubmitting = false;
      }
    },

    /* --- Single-element re-evaluation --------------------------------- */
    async rematchElement(elementId) {
      if (this.pendingElements.includes(elementId)) return;
      try {
        const res = await fetch(`/jobs/${this.jobId}/elements/${elementId}/rematch/`, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": this.csrf(),
          },
        });
        const data = await res.json();
        if (!data.ok) return;
        this.swapRow(elementId, data.row_html);
        this.trackElement(elementId, data.task_id);
      } catch (err) { /* ignore */ }
    },

    swapRow(elementId, html) {
      const row = document.getElementById("element-" + elementId);
      if (row && html) row.outerHTML = html;
    },

    /* Poll the element's task; when it finishes, fetch the finished row.
     * Nothing else on the page is re-evaluated. */
    trackElement(elementId, taskId) {
      if (!taskId) return;
      this.pendingElements.push(elementId);
      const startedAt = Date.now();

      const tick = async () => {
        if (document.visibilityState === "hidden") {
          setTimeout(tick, 3000);
          return;
        }
        try {
          const res = await fetch(`/tasks/${taskId}/status/`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          if (!res.ok) { this.untrack(elementId); return; }
          const task = await res.json();
          if (!task.is_terminal) {
            setTimeout(tick, Date.now() - startedAt > 30000 ? 5000 : 2000);
            return;
          }
          const rowRes = await fetch(`/jobs/${this.jobId}/elements/${elementId}/row/`, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          if (rowRes.ok) {
            const rowData = await rowRes.json();
            this.swapRow(elementId, rowData.row_html);
            this.summary = rowData.summary;
            const key = this.active;
            if (this.sections[key]) {
              this.sections[key] = { ...this.sections[key], ...rowData.section_summary };
            }
          }
        } catch (err) { /* ignore */ }
        this.untrack(elementId);
      };

      setTimeout(tick, 1200);
    },

    untrack(elementId) {
      this.pendingElements = this.pendingElements.filter((id) => id !== elementId);
    },
  };
}
