/* Progress polling shared by every AI path (spec §7.5).
 *
 * Poll at 2s, back off to 5s after 30s, stop on is_terminal, and pause while
 * the tab is hidden so a backgrounded page never keeps hammering the server.
 */
function aiProgress(taskId, terminal, initial) {
  return {
    taskId: taskId,
    isTerminal: terminal,
    data: initial,
    visible: true,
    timer: null,
    startedAt: Date.now(),

    label() {
      return {
        queued: window.AI_LABELS.queued,
        running: window.AI_LABELS.running,
        done: window.AI_LABELS.done,
        failed: window.AI_LABELS.failed,
        canceled: window.AI_LABELS.canceled,
      }[this.data.state] || this.data.state;
    },

    interval() {
      return Date.now() - this.startedAt > 30000 ? 5000 : 2000;
    },

    start() {
      if (this.isTerminal) {
        // A finished task stays on screen only if it failed.
        this.visible = this.data.state === "failed";
        return;
      }
      this.schedule();
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
          this.stop();
        } else if (!this.isTerminal) {
          this.schedule();
        }
      });
    },

    stop() {
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }
    },

    schedule() {
      this.stop();
      this.timer = setTimeout(() => this.poll(), this.interval());
    },

    async poll() {
      if (document.visibilityState === "hidden") return;
      try {
        const res = await fetch(`/tasks/${this.taskId}/status/`, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!res.ok) {
          this.stop();
          return;
        }
        const payload = await res.json();
        this.data = payload;
        if (payload.is_terminal) {
          this.isTerminal = true;
          this.stop();
          this.$dispatch("ai-task-finished", payload);
          if (payload.redirect_url) {
            window.location.assign(payload.redirect_url);
            return;
          }
          if (payload.state === "done") {
            setTimeout(() => { this.visible = false; }, 1200);
          }
          return;
        }
        this.schedule();
      } catch (err) {
        this.stop();
      }
    },
  };
}
