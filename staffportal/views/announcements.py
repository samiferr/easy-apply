"""In-product announcements: maintenance windows, incidents, release notes (UC-08.8,
in `staffportal.services`)."""

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView

from .. import services
from ..domain import access
from ..forms import AnnouncementForm
from ..models import Announcement
from .base import PortalActionView, PortalListView, StaffPortalMixin


class AnnouncementListView(PortalListView):
    template_name = "staffportal/announcement_list.html"
    context_object_name = "announcements"
    required_capability = access.VIEW_PORTAL
    section = "announcements"
    page_title = "Announcements"
    page_subtitle = "Banners shown inside the product, without a deploy."

    def get_queryset(self):
        return services.list_announcements()


class _AnnouncementFormView(StaffPortalMixin):
    model = Announcement
    form_class = AnnouncementForm
    template_name = "staffportal/announcement_form.html"
    required_capability = access.MANAGE_ANNOUNCEMENTS
    section = "announcements"
    success_url = reverse_lazy("staffportal:announcement_list")

    def form_valid(self, form):
        self.object = services.save_announcement(self.request, form, created=self.is_create)
        messages.success(self.request, "Announcement saved.")
        return HttpResponseRedirect(self.get_success_url())


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
        title = services.delete_announcement(request, pk)
        if title is not None:
            messages.success(request, f"Deleted “{title}”.")
        return redirect("staffportal:announcement_list")
