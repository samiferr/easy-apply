"""In-product announcements: maintenance windows, incidents, release notes."""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from ..forms import AnnouncementForm
from ..models import Announcement
from ..services import access, audit
from .base import PortalActionView, PortalListView, StaffPortalMixin


class AnnouncementListView(PortalListView):
    template_name = "staffportal/announcement_list.html"
    context_object_name = "announcements"
    required_capability = access.VIEW_PORTAL
    section = "announcements"
    page_title = "Announcements"
    page_subtitle = "Banners shown inside the product, without a deploy."

    def get_queryset(self):
        return Announcement.objects.select_related("created_by")


class _AnnouncementFormView(StaffPortalMixin):
    model = Announcement
    form_class = AnnouncementForm
    template_name = "staffportal/announcement_form.html"
    required_capability = access.MANAGE_ANNOUNCEMENTS
    section = "announcements"
    success_url = reverse_lazy("staffportal:announcement_list")

    def form_valid(self, form):
        if form.instance.pk is None:
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        audit.log(
            self.request,
            audit.ANNOUNCEMENT_CREATED if self.is_create else audit.ANNOUNCEMENT_UPDATED,
            target=self.object,
            summary=f"{self.object.title} ({self.object.level}, {self.object.audience}).",
            live=self.object.is_live,
        )
        messages.success(self.request, "Announcement saved.")
        return response


class AnnouncementCreateView(_AnnouncementFormView, CreateView):
    page_title = "New announcement"
    is_create = True


class AnnouncementUpdateView(_AnnouncementFormView, UpdateView):
    is_create = False

    def get_page_title(self):
        return self.object.title


class AnnouncementDeleteView(PortalActionView):
    required_capability = access.MANAGE_ANNOUNCEMENTS
    section = "announcements"

    def post(self, request, pk):
        announcement = Announcement.objects.filter(pk=pk).first()
        if announcement is not None:
            title = announcement.title
            audit.log(
                request, audit.ANNOUNCEMENT_DELETED, target=announcement,
                summary=f"Announcement “{title}” deleted.",
            )
            announcement.delete()
            messages.success(request, f"Deleted “{title}”.")
        return redirect("staffportal:announcement_list")
