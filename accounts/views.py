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
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView

from .forms import AccountDeleteForm, EmailAuthenticationForm, ProfileForm, RegisterForm
from .models import Profile


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
    model = Profile
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        return profile

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
