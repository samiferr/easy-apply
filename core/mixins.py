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

    def get_heading(self):
        return str(self.object)

    def get_detail(self):
        return None

    def get_warning(self):
        return self.warning

    def get_cancel_url(self):
        return reverse(self.cancel_url_name)

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
                "confirm_label": self.confirm_label,
            }
        )
        return ctx
