"""Shared view-layer mixins used across apps."""

from django.urls import reverse


class ConfirmDeleteMixin:
    """Renders `core/confirm_delete.html` for a `DeleteView`'s GET instead of
    Django's default `<app>/<model>_confirm_delete.html` — which none of our
    apps define, so without this every delete URL 500s on GET — or skipping
    the confirmation step entirely.

    Mix in *before* `DeleteView`. Subclasses normally only need to set
    `cancel_url_name` and optionally override `get_heading`/`get_detail`; the
    object being deleted is `self.object`, already set by `DeleteView.get()`
    before `get_context_data` runs.
    """

    template_name = "core/confirm_delete.html"
    confirm_label = None
    warning = None
    cancel_url_name = None
    #: Breadcrumb label for `cancel_url` — the screen this delete was reached
    #: from, so the confirmation page carries the same header as every other.
    #: Override `get_parent_crumbs` instead when the trail is deeper than one.
    parent_label = None

    def get_heading(self):
        return str(self.object)

    def get_detail(self):
        return None

    def get_warning(self):
        return self.warning

    def get_cancel_url(self):
        return reverse(self.cancel_url_name)

    def get_parent_label(self):
        return self.parent_label

    def get_parent_crumbs(self):
        """The breadcrumb trail between "Dashboard" and this page's "Delete".

        Each entry is a ``{"label": ..., "url": ...}`` mapping. The default is
        the single screen Cancel returns to; override for a deeper trail.
        """
        label = self.get_parent_label()
        if not label:
            return []
        return [{"label": label, "url": self.get_cancel_url()}]

    def get_page_title(self):
        return self.get_heading()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "page_title": self.get_page_title(),
                "heading": self.get_heading(),
                "detail": self.get_detail(),
                "warning": self.get_warning(),
                "cancel_url": self.get_cancel_url(),
                "parent_crumbs": self.get_parent_crumbs(),
                "confirm_label": self.confirm_label,
            }
        )
        return ctx
