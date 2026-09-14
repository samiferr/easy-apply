from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView


class LegalPageView(TemplateView):
    """A static, translated policy page.

    Entity-specific details (legal name, address, jurisdiction, hosting
    provider, DPO contact) come from settings.LEGAL_ENTITY so they are filled
    in one place — see config/settings.py.
    """

    #: Shown as the page's `<h1>` and as its breadcrumb — see
    #: `templates/legal/_legal_base.html`.
    page_title = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        return ctx


class PrivacyView(LegalPageView):
    template_name = "legal/privacy.html"
    page_title = _("Privacy Policy")


class TermsView(LegalPageView):
    template_name = "legal/terms.html"
    page_title = _("Terms of Service")


class CookiesView(LegalPageView):
    template_name = "legal/cookies.html"
    page_title = _("Cookie Policy")


class NoticeView(LegalPageView):
    template_name = "legal/notice.html"
    page_title = _("Legal notice")


class ContactView(LegalPageView):
    template_name = "legal/contact.html"
    page_title = _("Contact")
