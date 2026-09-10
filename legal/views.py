from django.views.generic import TemplateView


class LegalPageView(TemplateView):
    """A static, translated policy page.

    Entity-specific details (legal name, address, jurisdiction, hosting
    provider, DPO contact) come from settings.LEGAL_ENTITY so they are filled
    in one place — see config/settings.py.
    """

    page_title = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        return ctx


class PrivacyView(LegalPageView):
    template_name = "legal/privacy.html"


class TermsView(LegalPageView):
    template_name = "legal/terms.html"


class CookiesView(LegalPageView):
    template_name = "legal/cookies.html"


class NoticeView(LegalPageView):
    template_name = "legal/notice.html"


class ContactView(LegalPageView):
    template_name = "legal/contact.html"
