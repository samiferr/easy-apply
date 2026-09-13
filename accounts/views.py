from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from .forms import (
    AccountDeleteForm,
    EmailAuthenticationForm,
    ProfileCreateForm,
    ProfileForm,
    ProfileRenameForm,
    RegisterForm,
)
from .models import Profile
from .services import set_active_profile


class RegisterView(CreateView):
    form_class = RegisterForm
    template_name = "accounts/register.html"
    success_url = reverse_lazy("core:dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        # The signal already made this account's first profile; the form asked
        # which language it should speak, so stamp it before anything is written.
        language = form.cleaned_data["profile_language"]
        Profile.objects.filter(user=self.object).update(language=language)
        login(self.request, self.object)
        messages.success(
            self.request,
            f"Welcome to Easy Apply, {self.object.get_short_name()}! Let's build your recap.",
        )
        return response


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)
        return response


@login_required
def logout_confirm_view(request):
    """Simple GET confirmation page; the actual logout happens via POST."""
    return render(request, "accounts/logout_confirm.html")


class ProfileView(LoginRequiredMixin, UpdateView):
    """Personal info — of the *active* profile, not of the account."""

    model = Profile
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.profile

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, "Your profile has been updated.")
        return super().form_valid(form)


class SecurityView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/security.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["password_form"] = kwargs.get("password_form") or PasswordChangeForm(self.request.user)
        ctx["delete_form"] = kwargs.get("delete_form") or AccountDeleteForm(user=self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if "change_password" in request.POST:
            return self._handle_password_change(request)
        if "delete_account" in request.POST:
            return self._handle_account_delete(request)
        return redirect("accounts:security")

    def _handle_password_change(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        for field in form.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "block w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 "
                "text-sm text-slate-900 shadow-sm focus:border-brand-500 focus:outline-none "
                "focus:ring-2 focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900 "
                "dark:text-slate-100",
            )
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Your password has been changed successfully.")
            return redirect("accounts:security")
        return render(request, self.template_name, self.get_context_data(password_form=form))

    def _handle_account_delete(self, request):
        form = AccountDeleteForm(request.POST, user=request.user)
        if form.is_valid():
            user = request.user
            from django.contrib.auth import logout

            logout(request)
            user.delete()
            messages.info(request, "Your account and all associated data have been deleted.")
            return redirect("core:home")
        return render(request, self.template_name, self.get_context_data(delete_form=form))


# --- Profiles (workspaces) ----------------------------------------------------
# A profile owns everything: skills, experience, education, preferences, the
# jobs analyzed under it and the resumes written from it. Switching profiles
# switches the whole app; deleting one takes its content with it.

class ProfileListView(LoginRequiredMixin, ListView):
    """Manage workspaces: see them all, switch, rename, add, delete."""

    template_name = "accounts/profile_list.html"
    context_object_name = "profiles"
    extra_context = {"active_tab": "profiles"}

    def get_queryset(self):
        return Profile.objects.filter(user=self.request.user)


class ProfileCreateView(LoginRequiredMixin, CreateView):
    model = Profile
    form_class = ProfileCreateForm
    template_name = "accounts/profile_form.html"
    extra_context = {"active_tab": "profiles"}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        # A profile you just created is the one you meant to work in.
        set_active_profile(self.request, self.object)
        messages.success(
            self.request,
            _("Created “%(name)s” (%(language)s). You're now working in it.")
            % {"name": self.object.name, "language": self.object.language_label},
        )
        return response

    def get_success_url(self):
        return reverse("accounts:profile")


class ProfileRenameView(LoginRequiredMixin, UpdateView):
    model = Profile
    form_class = ProfileRenameForm
    template_name = "accounts/profile_form.html"
    extra_context = {"active_tab": "profiles"}
    success_url = reverse_lazy("accounts:profile_list")

    def get_queryset(self):
        return Profile.objects.filter(user=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Profile renamed."))
        return super().form_valid(form)


class ProfileSwitchView(LoginRequiredMixin, View):
    """Make another profile the active one, and follow it into its language."""

    def post(self, request, pk):
        profile = get_object_or_404(Profile, pk=pk, user=request.user)
        set_active_profile(request, profile)
        messages.info(
            request, _("Switched to “%(name)s”.") % {"name": profile.name}
        )

        next_url = request.POST.get("next") or reverse("core:dashboard")
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = reverse("core:dashboard")

        response = redirect(next_url)
        # The interface follows the workspace: reading a French profile in an
        # English UI would show its content and its labels in two languages.
        translation.activate(profile.language)
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            profile.language,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
        return response


class ProfileDeleteView(LoginRequiredMixin, View):
    """Delete a profile and everything recorded in it.

    Refused for the last one: with no profile there is nowhere to put anything,
    and the account-level "delete my account" button is the real way out.
    """

    def post(self, request, pk):
        profile = get_object_or_404(Profile, pk=pk, user=request.user)
        remaining = Profile.objects.filter(user=request.user).exclude(pk=profile.pk)
        if not remaining.exists():
            messages.error(
                request,
                _("You can't delete your only profile — create another one first."),
            )
            return redirect("accounts:profile_list")

        name = profile.name
        was_active = request.profile and request.profile.pk == profile.pk
        profile.delete()
        if was_active:
            set_active_profile(request, remaining.first())
        messages.info(
            request, _("Deleted “%(name)s” and everything in it.") % {"name": name}
        )
        return redirect("accounts:profile_list")


# --- Password reset / recovery flow -------------------------------------------------
# Django's token-based email reset covers both "reset" and "recover" password needs:
# a signed-out user who forgot (or wants to recover access to) their password lands here.

class EasyApplyPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/emails/password_reset_email.txt"
    html_email_template_name = "accounts/emails/password_reset_email.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_email_context = {"site_name": settings.SITE_NAME}


class EasyApplyPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class EasyApplyPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class EasyApplyPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
