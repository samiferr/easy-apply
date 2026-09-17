"""Portal forms.

Every one of these edits operator-owned configuration rather than customer
content, so they reuse the app's `StyledFormMixin` for look but never its
translation machinery — the portal is English-only by design (see
`templates/staffportal/base.html`).
"""

from django import forms
from django.contrib.auth import get_user_model

from core.forms import StyledForm, StyledFormMixin, StyledModelForm

from .models import (
    Announcement,
    FeatureFlag,
    Plan,
    StaffMember,
    StaffRole,
    Subscription,
    SupportNote,
)
from .services import runtime_settings

User = get_user_model()


class PlanForm(StyledModelForm):
    class Meta:
        model = Plan
        fields = [
            "name", "slug", "tagline", "description", "price_cents", "currency",
            "interval", "trial_days", "is_active", "is_public", "is_default",
            "sort_order", "max_profiles", "monthly_job_analyses",
            "monthly_tailored_resumes", "monthly_resume_imports", "features",
        ]
        help_texts = {
            "price_cents": "In minor units: 1900 = 19.00. Never a decimal.",
            "max_profiles": "Leave empty for unlimited. 0 means not included at all.",
            "monthly_job_analyses": "Leave empty for unlimited, 0 for not included.",
            "monthly_tailored_resumes": "Leave empty for unlimited, 0 for not included.",
            "monthly_resume_imports": "Leave empty for unlimited, 0 for not included.",
        }

    def clean_is_default(self):
        is_default = self.cleaned_data["is_default"]
        if is_default:
            # The database constraint would raise an IntegrityError here; catch
            # it as a form error so the operator gets a sentence, not a 500.
            clash = Plan.objects.filter(is_default=True).exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(
                    f"“{clash.first().name}” is already the default plan. "
                    "Clear it there first."
                )
        return is_default


class SubscriptionForm(StyledModelForm):
    class Meta:
        model = Subscription
        fields = [
            "plan", "status", "trial_ends_at", "cancel_at_period_end",
            "external_customer_id", "external_subscription_id", "notes",
        ]
        widgets = {
            "trial_ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # An inactive plan keeps its existing subscribers but takes no new ones;
        # the one this subscription is already on stays selectable so saving an
        # unrelated field does not silently migrate the customer.
        self.fields["plan"].queryset = Plan.objects.filter(
            is_active=True
        ) | Plan.objects.filter(pk=self.instance.plan_id)


class FeatureFlagForm(StyledModelForm):
    class Meta:
        model = FeatureFlag
        fields = ["key", "name", "description", "state", "percentage", "plans"]
        help_texts = {
            "key": "What the code checks: {% feature \"key\" %} / flags.is_enabled(\"key\").",
            "percentage": "Only used by the percentage rollout state.",
            "plans": "Entitled subscribers of these plans always get the feature.",
        }

    def clean(self):
        data = super().clean()
        if data.get("state") == FeatureFlag.PERCENT and not data.get("percentage"):
            self.add_error("percentage", "A percentage rollout at 0% is just 'off'.")
        return data


class AnnouncementForm(StyledModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title", "body", "level", "audience", "link_url", "link_label",
            "is_active", "dismissible", "starts_at", "ends_at",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        help_texts = {
            "ends_at": "Leave empty to run until it is switched off.",
            "dismissible": "Uncheck for incidents the customer must keep seeing.",
        }

    def clean(self):
        data = super().clean()
        starts, ends = data.get("starts_at"), data.get("ends_at")
        if starts and ends and ends <= starts:
            self.add_error("ends_at", "The end has to come after the start.")
        return data


class SupportNoteForm(StyledModelForm):
    class Meta:
        model = SupportNote
        fields = ["body", "pinned"]
        labels = {"body": "Internal note"}
        help_texts = {"body": "Never shown to the customer. Visible to every staff member."}


class ImpersonationForm(StyledForm):
    reason = forms.CharField(
        max_length=200,
        label="Why do you need to sign in as this account?",
        help_text="Recorded in the audit trail. Be specific — 'ticket #482, PDF export fails'.",
    )


class PlanChangeForm(StyledForm):
    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(is_active=True))
    status = forms.ChoiceField(choices=Subscription.STATUS_CHOICES)
    note = forms.CharField(max_length=200, required=False, label="Reason (audited)")


class StaffAccessForm(StyledForm):
    """Grants portal access by email.

    By email rather than a dropdown of every account: a select box of the whole
    user table is both unusable and a way to click the wrong person.
    """

    email = forms.EmailField(label="Account email")
    role = forms.ChoiceField(choices=StaffRole.choices, initial=StaffRole.VIEWER)
    note = forms.CharField(max_length=200, required=False, label="Why they need access")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise forms.ValidationError("No account with this email address.")
        if not user.is_active:
            raise forms.ValidationError("This account is suspended.")
        self.user = user
        return email


class StaffRoleForm(StyledModelForm):
    class Meta:
        model = StaffMember
        fields = ["role", "note"]


class SystemSettingsForm(StyledFormMixin, forms.Form):
    """Built from the registry in `services.runtime_settings`.

    Generated rather than hand-written so a new setting is one entry in one
    list: declare it, and it appears here, typed and labelled, with nothing to
    keep in sync.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        values = runtime_settings.all_values()
        for spec in runtime_settings.REGISTRY:
            if spec.kind == runtime_settings.BOOL:
                field = forms.BooleanField(required=False)
            elif spec.kind == runtime_settings.INT:
                field = forms.IntegerField(min_value=0)
            else:
                field = forms.CharField(required=False, max_length=500)
            field.label = spec.label
            field.help_text = spec.help_text
            field.initial = values[spec.key]
            self.fields[spec.key] = field
        self._style_fields()

    def grouped_fields(self):
        """[(group, [bound fields])] so the template can render sections."""
        grouped = {}
        for spec in runtime_settings.REGISTRY:
            grouped.setdefault(spec.group, []).append(self[spec.key])
        return list(grouped.items())

    def save(self, user=None) -> list[str]:
        """Writes only what changed, and says what that was — the audit entry
        should read "maintenance_mode: off → on", not "settings saved"."""
        changed = []
        current = runtime_settings.all_values()
        for spec in runtime_settings.REGISTRY:
            new = self.cleaned_data[spec.key]
            if new != current[spec.key]:
                runtime_settings.set_value(spec.key, new, user=user)
                changed.append(f"{spec.key}: {current[spec.key]!r} → {new!r}")
        return changed
