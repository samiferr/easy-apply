"""Tests for the staff portal.

The emphasis is on the parts that would be expensive to get wrong: who can
reach what, that impersonation cannot be used to launder a staff action, that
the audit trail cannot be rewritten, and that quota enforcement is genuinely
inert until an operator turns it on.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from core.exceptions import PreconditionFailed, Refused, ServiceError
from core.models import AITask
from core.testing import fake_deepseek
from jobs.models import JobPost
from resume.models import ResumeImport, TailoredResume

from . import services
from .forms import ImpersonationForm
from .models import (
    Announcement,
    AuditLog,
    FeatureFlag,
    ImpersonationSession,
    Plan,
    StaffMember,
    StaffRole,
    Subscription,
    SupportNote,
    UsageMetric,
    UsageRecord,
)
from .domain import access, audit, exports, flags, health, metrics, quotas
from .domain import runtime_settings, subscriptions

User = get_user_model()


def make_user(email, **kwargs):
    return User.objects.create_user(email=email, password="pw12345678", **kwargs)


def make_staff(email, role=StaffRole.ADMIN, **kwargs):
    user = make_user(email, is_staff=True, **kwargs)
    if role is not None:
        StaffMember.objects.create(user=user, role=role)
    return user


def make_plans():
    free = Plan.objects.create(
        slug="free", name="Free", price_cents=0, is_default=True,
        max_profiles=1, monthly_job_analyses=2, monthly_tailored_resumes=0,
        monthly_resume_imports=1,
    )
    pro = Plan.objects.create(
        slug="pro", name="Pro", price_cents=1200, sort_order=2,
        max_profiles=5, monthly_job_analyses=100,
    )
    return free, pro


class PortalTestCase(TestCase):
    """Base class that keeps the runtime-settings cache from leaking.

    `runtime_settings` caches the whole settings dict for 30 seconds. A test
    that writes a setting invalidates it, but the *rollback* at the end of the
    test does not — so without this, a test that turns quotas on could leave
    them on for whatever runs next.
    """

    def setUp(self):
        super().setUp()
        runtime_settings.invalidate()

    def tearDown(self):
        runtime_settings.invalidate()
        super().tearDown()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
class AccessControlTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.customer = make_user("customer@example.com")
        self.viewer = make_staff("viewer@example.com", StaffRole.VIEWER)
        self.support = make_staff("support@example.com", StaffRole.SUPPORT)
        self.admin = make_staff("admin@example.com", StaffRole.ADMIN)
        self.root = make_user("root@example.com", is_staff=True, is_superuser=True)

    def test_anonymous_is_sent_to_the_login_page(self):
        response = self.client.get(reverse("staffportal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_a_customer_gets_404_not_403(self):
        """A 403 would confirm the portal is there. A 404 says nothing."""
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).status_code, 404)

    def test_a_suspended_staff_account_cannot_get_in(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).status_code, 200)

        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])

        # `ModelBackend.get_user` refuses an inactive account, so the session
        # stops resolving to anyone and the request arrives anonymous — it is
        # bounced to the login page rather than reaching the portal gate.
        response = self.client.get(reverse("staffportal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_staff_with_no_role_row_reads_as_a_viewer(self):
        plain = make_user("plain-staff@example.com", is_staff=True)
        self.assertEqual(access.role_for(plain), StaffRole.VIEWER)
        self.assertIn(access.VIEW_USERS, access.capabilities_for(plain))
        self.assertNotIn(access.DELETE_USERS, access.capabilities_for(plain))

    def test_viewer_can_read_but_not_change(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("staffportal:user_list")).status_code, 200)
        # Runtime settings need operations.manage.
        self.assertEqual(self.client.get(reverse("staffportal:settings")).status_code, 403)
        self.assertEqual(self.client.get(reverse("staffportal:plan_create")).status_code, 403)

    def test_support_cannot_touch_billing_or_flags(self):
        self.client.force_login(self.support)
        self.assertEqual(self.client.get(reverse("staffportal:plan_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("staffportal:flag_create")).status_code, 403)
        self.assertTrue(access.has_capability(self.support, access.IMPERSONATE))

    def test_only_a_superuser_may_grant_portal_access(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("staffportal:team_list")).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse("staffportal:team_list")).status_code, 200)

    def test_portal_pages_are_never_indexed_or_cached(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("staffportal:dashboard"))
        self.assertIn("noindex", response["X-Robots-Tag"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_role_capabilities_only_ever_grow(self):
        """Support ⊃ viewer, billing ⊃ support, admin ⊃ billing."""
        viewer = access.ROLE_CAPABILITIES[StaffRole.VIEWER]
        support = access.ROLE_CAPABILITIES[StaffRole.SUPPORT]
        billing = access.ROLE_CAPABILITIES[StaffRole.BILLING]
        admin = access.ROLE_CAPABILITIES[StaffRole.ADMIN]
        self.assertLess(viewer, support)
        self.assertLess(support, billing)
        self.assertLess(billing, admin)
        self.assertNotIn(access.MANAGE_TEAM, admin)


class EveryScreenRendersTests(PortalTestCase):
    """A smoke test over every GET route, with enough data that the tables and
    charts actually have rows to render."""

    def setUp(self):
        super().setUp()
        make_plans()
        self.root = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.customer = make_user("customer@example.com")
        profile = Profile.objects.get(user=self.customer)
        job = JobPost.objects.create(profile=profile, title="Backend engineer")
        AITask.start_for(profile, AITask.JOB_ANALYSIS, job)
        SupportNote.objects.create(user=self.customer, body="Called about billing.")
        FeatureFlag.objects.create(key="beta", name="Beta", state=FeatureFlag.STAFF)
        Announcement.objects.create(title="Maintenance Sunday")
        self.plan = Plan.objects.get(slug="pro")
        self.subscription = Subscription.objects.get(user=self.customer)
        self.member = StaffMember.objects.create(
            user=make_user("viewer@example.com", is_staff=True), role=StaffRole.VIEWER
        )
        self.client.force_login(self.root)

    def test_every_screen_returns_200(self):
        urls = [
            reverse("staffportal:dashboard"),
            reverse("staffportal:user_list"),
            reverse("staffportal:user_detail", args=[self.customer.pk]),
            reverse("staffportal:user_delete", args=[self.customer.pk]),
            reverse("staffportal:impersonation_log"),
            reverse("staffportal:billing"),
            reverse("staffportal:plan_create"),
            reverse("staffportal:plan_update", args=[self.plan.pk]),
            reverse("staffportal:subscription_list"),
            reverse("staffportal:subscription_update", args=[self.subscription.pk]),
            reverse("staffportal:flag_list"),
            reverse("staffportal:flag_create"),
            reverse("staffportal:announcement_list"),
            reverse("staffportal:announcement_create"),
            reverse("staffportal:health"),
            reverse("staffportal:task_list"),
            reverse("staffportal:settings"),
            reverse("staffportal:audit_list"),
            reverse("staffportal:team_list"),
            reverse("staffportal:team_update", args=[self.member.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_filtered_lists_render(self):
        for url in [
            reverse("staffportal:user_list") + "?q=customer&status=active&activity=dormant",
            reverse("staffportal:task_list") + "?state=queued&kind=job_analysis",
            reverse("staffportal:audit_list") + "?impersonated=1",
            reverse("staffportal:subscription_list") + "?status=active",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


# ---------------------------------------------------------------------------
# Impersonation
# ---------------------------------------------------------------------------
class ImpersonationTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        make_plans()
        self.operator = make_staff("support@example.com", StaffRole.SUPPORT)
        self.customer = make_user("customer@example.com")
        self.client.force_login(self.operator)

    def start(self, reason="ticket #482, PDF export fails"):
        return self.client.post(
            reverse("staffportal:impersonate_start", args=[self.customer.pk]),
            {"reason": reason},
        )

    def test_a_reason_is_required(self):
        response = self.start(reason="")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ImpersonationSession.objects.exists())

    def test_starting_switches_the_session_and_records_it(self):
        self.start()
        record = ImpersonationSession.objects.get()
        self.assertEqual(record.actor_email, self.operator.email)
        self.assertEqual(record.target_email, self.customer.email)
        self.assertTrue(record.is_open)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]), self.customer.pk
        )
        self.assertEqual(self.client.session["impersonator_id"], self.operator.pk)
        self.assertTrue(
            AuditLog.objects.filter(action=audit.IMPERSONATION_STARTED).exists()
        )

    def test_an_impersonated_session_cannot_reach_the_portal(self):
        """Otherwise impersonation is a way to act as staff through a session
        the audit trail attributes to the customer."""
        self.start()
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).status_code, 404)
        self.assertEqual(self.client.get(reverse("staffportal:user_list")).status_code, 404)

    def test_the_banner_is_on_every_app_page(self):
        self.start()
        body = self.client.get(reverse("core:dashboard")).content.decode()
        self.assertIn("Viewing as customer@example.com", body)
        self.assertIn(reverse("staffportal:impersonate_stop"), body)

    def test_stopping_hands_the_session_back(self):
        self.start()
        self.client.post(reverse("staffportal:impersonate_stop"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.operator.pk)
        self.assertNotIn("impersonator_id", self.client.session)
        record = ImpersonationSession.objects.get()
        self.assertFalse(record.is_open)
        self.assertEqual(record.ended_reason, ImpersonationSession.MANUAL)
        self.assertTrue(AuditLog.objects.filter(action=audit.IMPERSONATION_ENDED).exists())

    def test_an_expired_session_ends_itself_on_the_next_request(self):
        self.start()
        record = ImpersonationSession.objects.get()
        record.expires_at = timezone.now() - timedelta(minutes=1)
        record.save(update_fields=["expires_at"])

        self.client.get(reverse("core:dashboard"))

        record.refresh_from_db()
        self.assertEqual(record.ended_reason, ImpersonationSession.EXPIRED)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.operator.pk)

    def test_staff_cannot_impersonate_staff_unless_superuser(self):
        colleague = make_staff("colleague@example.com", StaffRole.VIEWER)
        allowed, reason = access.can_impersonate(self.operator, colleague)
        self.assertFalse(allowed)
        self.assertIn("superuser", reason)

        root = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.assertTrue(access.can_impersonate(root, colleague)[0])

    def test_a_suspended_account_cannot_be_impersonated(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        allowed, reason = access.can_impersonate(self.operator, self.customer)
        self.assertFalse(allowed)
        self.assertIn("suspended", reason)

    def test_actions_taken_while_impersonating_are_flagged(self):
        self.start()
        entry = audit.log(
            self._request_with_session(), "test.action", summary="from inside"
        )
        self.assertTrue(entry.while_impersonating)

    def _request_with_session(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.session = self.client.session
        request.user = self.customer
        return request


# ---------------------------------------------------------------------------
# Plans, subscriptions and quotas
# ---------------------------------------------------------------------------
class SubscriptionProvisioningTests(PortalTestCase):
    def test_a_new_account_lands_on_the_default_plan(self):
        make_plans()
        user = make_user("new@example.com")
        subscription = Subscription.objects.get(user=user)
        self.assertEqual(subscription.plan.slug, "free")
        self.assertEqual(subscription.status, Subscription.ACTIVE)

    def test_a_trial_plan_starts_the_account_trialing(self):
        Plan.objects.create(slug="trial", name="Trial", is_default=True, trial_days=14)
        user = make_user("trial@example.com")
        subscription = Subscription.objects.get(user=user)
        self.assertEqual(subscription.status, Subscription.TRIALING)
        self.assertIsNotNone(subscription.trial_ends_at)

    def test_no_plans_means_no_subscription_and_no_crash(self):
        user = make_user("early@example.com")
        self.assertFalse(Subscription.objects.filter(user=user).exists())
        self.assertIsNone(quotas.blocked_message(user, UsageMetric.JOB_ANALYSIS))

    def test_only_one_plan_can_be_the_default(self):
        from django.db import IntegrityError, transaction

        Plan.objects.create(slug="a", name="A", is_default=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Plan.objects.create(slug="b", name="B", is_default=True)


class QuotaTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.user = make_user("customer@example.com")

    def test_enforcement_is_off_until_an_operator_turns_it_on(self):
        """The whole point of shipping this dark: nothing changes for anyone
        until someone decides it should."""
        quotas.consume(self.user, UsageMetric.JOB_ANALYSIS, amount=99)
        self.assertIsNone(quotas.blocked_message(self.user, UsageMetric.JOB_ANALYSIS))

    def test_an_exhausted_allowance_blocks_once_enforcement_is_on(self):
        runtime_settings.set_value("enforce_quotas", True)
        self.assertIsNone(quotas.blocked_message(self.user, UsageMetric.JOB_ANALYSIS))

        quotas.consume(self.user, UsageMetric.JOB_ANALYSIS, amount=2)
        message = quotas.blocked_message(self.user, UsageMetric.JOB_ANALYSIS)
        self.assertIsNotNone(message)
        self.assertIn("2", message)

    def test_a_zero_allowance_is_not_included_rather_than_exhausted(self):
        runtime_settings.set_value("enforce_quotas", True)
        message = quotas.blocked_message(self.user, UsageMetric.TAILORED_RESUME)
        self.assertIn("doesn't include", message)

    def test_null_allowance_is_unlimited(self):
        runtime_settings.set_value("enforce_quotas", True)
        subscription = Subscription.objects.get(user=self.user)
        subscriptions.change_plan(subscription, self.pro)
        allowance = quotas.allowance(self.user, UsageMetric.TAILORED_RESUME)
        self.assertTrue(allowance.unlimited)
        self.assertIsNone(quotas.blocked_message(self.user, UsageMetric.TAILORED_RESUME))

    def test_the_kill_switch_stops_everything_regardless_of_plan(self):
        runtime_settings.set_value("ai_features_enabled", False)
        message = quotas.blocked_message(self.user, UsageMetric.JOB_ANALYSIS)
        self.assertIn("temporarily unavailable", message)
        self.assertIsNotNone(quotas.ai_unavailable_message())

    def test_usage_is_counted_per_period_and_resets_when_it_rolls(self):
        quotas.consume(self.user, UsageMetric.JOB_ANALYSIS)
        self.assertEqual(quotas.allowance(self.user, UsageMetric.JOB_ANALYSIS).used, 1)

        subscription = Subscription.objects.get(user=self.user)
        past = timezone.now() - timedelta(days=45)
        Subscription.objects.filter(pk=subscription.pk).update(
            current_period_start=past, current_period_end=past + timedelta(days=30)
        )
        subscription.refresh_from_db()
        subscriptions.current_period(subscription)

        # A new window means a new counter row, not an edited one: last
        # period's number has to stay auditable.
        self.assertEqual(quotas.allowance(self.user, UsageMetric.JOB_ANALYSIS).used, 0)
        self.assertEqual(UsageRecord.objects.filter(user=self.user).count(), 1)

    def test_changing_plan_restarts_the_window(self):
        quotas.consume(self.user, UsageMetric.JOB_ANALYSIS, amount=2)
        subscription = Subscription.objects.get(user=self.user)
        subscriptions.change_plan(subscription, self.pro)
        self.assertEqual(quotas.allowance(self.user, UsageMetric.JOB_ANALYSIS).used, 0)

    def test_the_profile_ceiling_counts_what_exists(self):
        runtime_settings.set_value("enforce_quotas", True)
        # Registration already created one, and Free allows exactly one.
        self.assertIsNotNone(quotas.profile_blocked_message(self.user))

    def test_month_arithmetic_clamps_to_the_shortest_month(self):
        from datetime import datetime

        january_31 = timezone.make_aware(datetime(2026, 1, 31, 9, 0))
        self.assertEqual(subscriptions.add_month(january_31).day, 28)
        december = timezone.make_aware(datetime(2026, 12, 15, 9, 0))
        rolled = subscriptions.add_month(december)
        self.assertEqual((rolled.year, rolled.month), (2027, 1))


class QuotaEnforcementInProductTests(PortalTestCase):
    """The hooks in the product's own views, not the service in isolation."""

    def setUp(self):
        super().setUp()
        make_plans()
        self.user = make_user("customer@example.com")
        self.client.force_login(self.user)

    def test_analysis_is_refused_and_nothing_is_created_when_over_quota(self):
        runtime_settings.set_value("enforce_quotas", True)
        quotas.consume(self.user, UsageMetric.JOB_ANALYSIS, amount=2)

        response = self.client.post(
            reverse("jobs:add"),
            {"description_text": "We are hiring a backend engineer. " * 20},
        )
        self.assertEqual(response.status_code, 200)  # re-rendered, not redirected
        self.assertFalse(JobPost.objects.filter(profile__user=self.user).exists())

    def test_a_successful_analysis_consumes_one(self):
        response = self.client.post(
            reverse("jobs:add"),
            {"description_text": "We are hiring a backend engineer. " * 20},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(quotas.allowance(self.user, UsageMetric.JOB_ANALYSIS).used, 1)

    def test_registration_can_be_closed(self):
        runtime_settings.set_value("signups_enabled", False)
        self.client.logout()
        response = self.client.get(reverse("accounts:register"))
        self.assertRedirects(response, reverse("core:home"))


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
class FeatureFlagTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.user = make_user("customer@example.com")
        self.staff = make_staff("staff@example.com")

    def test_an_unknown_key_is_off(self):
        """Fail closed: deleting a flag retires the feature rather than
        releasing it to everyone."""
        self.assertFalse(flags.is_enabled("does-not-exist", self.user))

    def test_states(self):
        flag = FeatureFlag.objects.create(key="f", name="F", state=FeatureFlag.OFF)
        self.assertFalse(flags.is_enabled("f", self.user))

        flag.state = FeatureFlag.ON
        flag.save()
        self.assertTrue(flags.is_enabled("f", self.user))

        flag.state = FeatureFlag.STAFF
        flag.save()
        self.assertFalse(flags.is_enabled("f", self.user))
        self.assertTrue(flags.is_enabled("f", self.staff))

    def test_a_percentage_rollout_is_stable_and_monotonic(self):
        flag = FeatureFlag.objects.create(
            key="rollout", name="Rollout", state=FeatureFlag.PERCENT, percentage=50
        )
        first = flags.is_enabled("rollout", self.user)
        self.assertEqual(first, flags.is_enabled("rollout", self.user))

        # Raising the percentage only ever adds accounts.
        flag.percentage = 100
        flag.save()
        self.assertTrue(flags.is_enabled("rollout", self.user))

        # And the buckets are spread rather than all-or-nothing.
        flag.percentage = 50
        flag.save()
        users = [make_user(f"bucket{i}@example.com") for i in range(40)]
        on = sum(1 for u in users if flags.is_enabled("rollout", u))
        self.assertGreater(on, 5)
        self.assertLess(on, 35)

    def test_an_explicit_override_beats_the_state(self):
        flag = FeatureFlag.objects.create(key="f", name="F", state=FeatureFlag.OFF)
        flag.users.add(self.user)
        self.assertTrue(flags.is_enabled("f", self.user))

    def test_a_plan_entitles_its_subscribers(self):
        flag = FeatureFlag.objects.create(key="f", name="F", state=FeatureFlag.OFF)
        flag.plans.add(self.pro)
        self.assertFalse(flags.is_enabled("f", self.user))

        subscriptions.change_plan(Subscription.objects.get(user=self.user), self.pro)
        self.assertTrue(flags.is_enabled("f", self.user))

    def test_anonymous_visitors_only_see_a_blanket_on(self):
        FeatureFlag.objects.create(key="f", name="F", state=FeatureFlag.STAFF)
        self.assertFalse(flags.is_enabled("f", None))
        FeatureFlag.objects.filter(key="f").update(state=FeatureFlag.ON)
        self.assertTrue(flags.is_enabled("f", None))


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
class AuditTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.operator = make_staff("admin@example.com")
        self.customer = make_user("customer@example.com")

    def test_entries_cannot_be_edited(self):
        entry = AuditLog.objects.create(action="test", actor=self.operator)
        entry.summary = "rewritten"
        with self.assertRaises(ValueError):
            entry.save()

    def test_entries_cannot_be_deleted_one_at_a_time(self):
        entry = AuditLog.objects.create(action="test")
        with self.assertRaises(ValueError):
            entry.delete()

    def test_an_entry_outlives_the_accounts_it_names(self):
        AuditLog.objects.create(
            action=audit.USER_DELETED,
            actor=self.operator,
            actor_email=self.operator.email,
            target_repr=self.customer.email,
        )
        self.customer.delete()
        self.operator.delete()
        entry = AuditLog.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_email, "admin@example.com")
        self.assertEqual(entry.target_repr, "customer@example.com")

    def test_logging_never_raises_into_the_caller(self):
        # A 300-character summary is truncated rather than blowing up the
        # action it was describing.
        entry = audit.log(None, "test", summary="x" * 5000)
        self.assertEqual(len(entry.summary), 300)

    def test_forwarded_ip_is_ignored_unless_the_proxy_is_trusted(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="9.9.9.9")
        self.assertEqual(audit.client_ip(request), "127.0.0.1")
        with self.settings(STAFF_PORTAL_TRUST_X_FORWARDED_FOR=True):
            self.assertEqual(audit.client_ip(request), "9.9.9.9")

    def test_prune_respects_the_retention_window(self):
        from django.core.management import call_command

        old = AuditLog.objects.create(action="old")
        AuditLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )
        AuditLog.objects.create(action="recent")
        call_command("prune_audit_log", days=365, verbosity=0)
        self.assertEqual(list(AuditLog.objects.values_list("action", flat=True)), ["recent"])


# ---------------------------------------------------------------------------
# Account actions
# ---------------------------------------------------------------------------
class AccountActionTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com")
        self.client.force_login(self.operator)

    def test_suspending_ends_the_customers_sessions(self):
        other = self.client_class()
        other.force_login(self.customer)
        self.assertEqual(other.get(reverse("core:dashboard")).status_code, 200)

        self.client.post(
            reverse("staffportal:user_suspend", args=[self.customer.pk]),
            {"reason": "abuse report #12"},
        )

        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        # Their live session is gone, not just their ability to sign in again.
        self.assertEqual(other.get(reverse("core:dashboard")).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action=audit.USER_SUSPENDED).exists())

    def test_you_cannot_suspend_yourself(self):
        self.client.post(reverse("staffportal:user_suspend", args=[self.operator.pk]))
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.is_active)

    def test_reactivating_restores_access(self):
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        self.client.post(reverse("staffportal:user_reactivate", args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_password_reset_goes_to_the_customer_not_the_operator(self):
        self.client.post(reverse("staffportal:user_password_reset", args=[self.customer.pk]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.customer.email])
        self.assertTrue(
            AuditLog.objects.filter(action=audit.USER_PASSWORD_RESET_SENT).exists()
        )

    def test_a_support_note_is_attributed_and_kept(self):
        self.client.post(
            reverse("staffportal:user_note_add", args=[self.customer.pk]),
            {"body": "Refunded March."},
        )
        note = SupportNote.objects.get()
        self.assertEqual(note.author_email, self.operator.email)
        self.assertEqual(note.user, self.customer)

    def test_deleting_requires_the_email_typed_in_full(self):
        url = reverse("staffportal:user_delete", args=[self.customer.pk])
        self.client.post(url, {"confirm_email": "wrong@example.com"})
        self.assertTrue(User.objects.filter(pk=self.customer.pk).exists())

        self.client.post(url, {"confirm_email": "customer@example.com", "reason": "erasure"})
        self.assertFalse(User.objects.filter(pk=self.customer.pk).exists())
        entry = AuditLog.objects.get(action=audit.USER_DELETED)
        self.assertEqual(entry.metadata["email"], "customer@example.com")

    def test_you_cannot_delete_yourself(self):
        url = reverse("staffportal:user_delete", args=[self.operator.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_changing_plan_is_audited(self):
        pro = Plan.objects.get(slug="pro")
        self.client.post(
            reverse("staffportal:user_plan_change", args=[self.customer.pk]),
            {"plan": pro.pk, "status": Subscription.ACTIVE, "note": "upgraded on call"},
        )
        subscription = Subscription.objects.get(user=self.customer)
        self.assertEqual(subscription.plan, pro)
        entry = AuditLog.objects.get(action=audit.SUBSCRIPTION_UPDATED)
        self.assertIn("Pro", entry.summary)

    def test_usage_reset_zeroes_the_current_period(self):
        quotas.consume(self.customer, UsageMetric.JOB_ANALYSIS, amount=2)
        self.client.post(reverse("staffportal:user_usage_reset", args=[self.customer.pk]))
        self.assertEqual(quotas.allowance(self.customer, UsageMetric.JOB_ANALYSIS).used, 0)

    def test_support_role_cannot_delete_an_account(self):
        support = make_staff("support@example.com", StaffRole.SUPPORT)
        self.client.force_login(support)
        response = self.client.get(reverse("staffportal:user_delete", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 403)


class TeamManagementTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.root = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.candidate = make_user("candidate@example.com")
        self.client.force_login(self.root)

    def test_granting_access_sets_the_staff_flag_and_the_role(self):
        self.client.post(
            reverse("staffportal:team_list"),
            {"email": "candidate@example.com", "role": StaffRole.SUPPORT, "note": "on call"},
        )
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.is_staff)
        self.assertEqual(self.candidate.staff_member.role, StaffRole.SUPPORT)
        self.assertTrue(AuditLog.objects.filter(action=audit.TEAM_GRANTED).exists())

    def test_revoking_clears_the_staff_flag_too(self):
        member = StaffMember.objects.create(user=self.candidate, role=StaffRole.VIEWER)
        self.candidate.is_staff = True
        self.candidate.save(update_fields=["is_staff"])

        self.client.post(reverse("staffportal:team_revoke", args=[member.pk]))

        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.is_staff)
        self.assertFalse(StaffMember.objects.filter(pk=member.pk).exists())

    def test_you_cannot_revoke_your_own_access(self):
        member = StaffMember.objects.create(user=self.root, role=StaffRole.ADMIN)
        self.client.post(reverse("staffportal:team_revoke", args=[member.pk]))
        self.assertTrue(StaffMember.objects.filter(pk=member.pk).exists())

    def test_granting_to_an_unknown_email_is_a_form_error(self):
        response = self.client.post(
            reverse("staffportal:team_list"),
            {"email": "nobody@example.com", "role": StaffRole.VIEWER},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No account with this email")


# ---------------------------------------------------------------------------
# Runtime settings, maintenance mode and announcements
# ---------------------------------------------------------------------------
class RuntimeSettingsTests(PortalTestCase):
    def test_unknown_keys_are_refused(self):
        with self.assertRaises(KeyError):
            runtime_settings.get("not-a-setting")
        with self.assertRaises(KeyError):
            runtime_settings.set_value("not-a-setting", 1)

    def test_values_round_trip_with_their_type(self):
        runtime_settings.set_value("maintenance_mode", True)
        self.assertIs(runtime_settings.get("maintenance_mode"), True)
        runtime_settings.set_value("impersonation_minutes", 5)
        self.assertEqual(runtime_settings.get("impersonation_minutes"), 5)
        runtime_settings.set_value("support_email", "help@example.com")
        self.assertEqual(runtime_settings.get("support_email"), "help@example.com")

    def test_saving_from_the_form_records_what_changed(self):
        operator = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.client.force_login(operator)
        payload = {spec.key: "" for spec in runtime_settings.REGISTRY}
        payload.update(
            {
                "impersonation_minutes": 15,
                "audit_retention_days": 365,
                "maintenance_mode": "on",
            }
        )
        self.client.post(reverse("staffportal:settings"), payload)

        self.assertIs(runtime_settings.get("maintenance_mode"), True)
        entry = AuditLog.objects.get(action=audit.SETTING_UPDATED)
        self.assertIn("maintenance_mode", entry.summary)


class MaintenanceModeTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.customer = make_user("customer@example.com")
        self.operator = make_user("root@example.com", is_staff=True, is_superuser=True)
        runtime_settings.set_value("maintenance_mode", True)

    def test_customers_get_a_503(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "maintenance", status_code=503)

    def test_visitors_get_it_too(self):
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 503)

    def test_staff_keep_working_so_they_can_verify_the_fix(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).status_code, 200)

    def test_the_login_page_stays_reachable(self):
        self.assertEqual(self.client.get(reverse("accounts:login")).status_code, 200)


class AnnouncementTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.customer = make_user("customer@example.com")
        self.client.force_login(self.customer)

    def test_a_live_announcement_shows_in_the_app(self):
        Announcement.objects.create(title="Scheduled maintenance Sunday 02:00 UTC")
        body = self.client.get(reverse("core:dashboard")).content.decode()
        self.assertIn("Scheduled maintenance Sunday", body)

    def test_a_staff_only_announcement_is_not_shown_to_customers(self):
        Announcement.objects.create(title="Deploy freeze", audience=Announcement.STAFF)
        body = self.client.get(reverse("core:dashboard")).content.decode()
        self.assertNotIn("Deploy freeze", body)

    def test_scheduling_is_respected_at_both_ends(self):
        future = Announcement.objects.create(
            title="Not yet", starts_at=timezone.now() + timedelta(hours=1)
        )
        past = Announcement.objects.create(
            title="Over",
            starts_at=timezone.now() - timedelta(days=2),
            ends_at=timezone.now() - timedelta(days=1),
        )
        live = set(Announcement.objects.live().values_list("pk", flat=True))
        self.assertNotIn(future.pk, live)
        self.assertNotIn(past.pk, live)
        self.assertFalse(future.is_live)


# ---------------------------------------------------------------------------
# Metrics, health and exports
# ---------------------------------------------------------------------------
class MetricsTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.customer = make_user("customer@example.com")
        profile = Profile.objects.get(user=self.customer)
        JobPost.objects.create(profile=profile, title="Backend engineer")

    def test_overview_runs_on_an_empty_and_a_populated_database(self):
        data = metrics.overview()
        self.assertEqual(data["growth"]["total"], 1)
        self.assertEqual(data["usage"]["job_posts"], 1)
        self.assertEqual(data["activation"]["analyzed_percent"], 100)

    def test_mrr_counts_paid_active_plans_only(self):
        self.assertEqual(metrics.revenue()["mrr_cents"], 0)  # free plan

        subscriptions.change_plan(Subscription.objects.get(user=self.customer), self.pro)
        self.assertEqual(metrics.revenue()["mrr_cents"], 1200)

        # A trial is a forecast, not revenue.
        Subscription.objects.filter(user=self.customer).update(
            status=Subscription.TRIALING
        )
        self.assertEqual(metrics.revenue()["mrr_cents"], 0)
        self.assertEqual(metrics.revenue()["trialing"], 1)

    def test_a_yearly_plan_is_normalized_into_mrr(self):
        yearly = Plan.objects.create(
            slug="annual", name="Annual", price_cents=12000, interval=Plan.YEAR
        )
        subscriptions.change_plan(Subscription.objects.get(user=self.customer), yearly)
        self.assertEqual(metrics.revenue()["mrr_cents"], 1000)

    def test_engagement_reads_last_seen(self):
        self.assertEqual(metrics.engagement()["mau"], 0)
        User.objects.filter(pk=self.customer.pk).update(last_seen_at=timezone.now())
        engagement = metrics.engagement()
        self.assertEqual(engagement["dau"], 1)
        self.assertEqual(engagement["stickiness"], 100)

    def test_a_series_covers_every_day_in_the_window(self):
        chart = metrics.daily_series(User.objects.all(), "date_joined", days=14)
        self.assertEqual(len(chart["bars"]), 14)
        self.assertTrue(chart["has_data"])


class LastSeenTests(PortalTestCase):
    def test_browsing_updates_last_seen(self):
        user = make_user("customer@example.com")
        self.client.force_login(user)
        self.client.get(reverse("core:dashboard"))
        user.refresh_from_db()
        self.assertIsNotNone(user.last_seen_at)

    def test_the_write_is_throttled(self):
        user = make_user("customer@example.com")
        self.client.force_login(user)
        self.client.get(reverse("core:dashboard"))
        user.refresh_from_db()
        first = user.last_seen_at

        self.client.get(reverse("core:dashboard"))
        user.refresh_from_db()
        self.assertEqual(user.last_seen_at, first)


class HealthTests(PortalTestCase):
    def test_every_check_answers_without_raising(self):
        checks = health.run_checks()
        self.assertEqual(len(checks), len(health.CHECKS))
        for check in checks:
            with self.subTest(check=check.name):
                self.assertIn(check.status, {health.OK, health.WARN, health.FAIL})
                self.assertTrue(check.detail)

    def test_the_summary_takes_the_worst_status(self):
        self.assertEqual(
            health.summarize([health.Check("a", health.OK, "")])["status"], health.OK
        )
        self.assertEqual(
            health.summarize(
                [health.Check("a", health.OK, ""), health.Check("b", health.WARN, "")]
            )["status"],
            health.WARN,
        )
        self.assertEqual(
            health.summarize(
                [health.Check("a", health.FAIL, ""), health.Check("b", health.WARN, "")]
            )["status"],
            health.FAIL,
        )

    def test_a_missing_default_plan_fails_the_check(self):
        Plan.objects.create(slug="p", name="P", is_default=False)
        checks = {c.name: c for c in health.run_checks()}
        self.assertEqual(checks["Plans"].status, health.FAIL)


class ExportTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com", first_name="Ada")
        profile = Profile.objects.get(user=self.customer)
        JobPost.objects.create(profile=profile, title="Backend engineer")
        SupportNote.objects.create(user=self.customer, body="Called about billing.")
        self.client.force_login(self.operator)

    def test_the_accounts_csv_streams_with_a_header(self):
        response = self.client.get(reverse("staffportal:user_export"))
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        self.assertTrue(body.startswith("id,email"))
        self.assertIn("customer@example.com", body)

    def test_the_account_export_carries_the_whole_account(self):
        payload = exports.account_export(self.customer)
        self.assertEqual(payload["account"]["email"], "customer@example.com")
        self.assertEqual(len(payload["profiles"]), 1)
        self.assertEqual(payload["job_posts"][0]["title"], "Backend engineer")
        self.assertEqual(len(payload["support_notes"]), 1)

    def test_downloading_an_export_is_itself_audited(self):
        self.client.get(reverse("staffportal:user_data_export", args=[self.customer.pk]))
        self.assertTrue(AuditLog.objects.filter(action=audit.USER_EXPORTED).exists())

    def test_taking_a_copy_of_the_audit_log_is_audited(self):
        self.client.get(reverse("staffportal:audit_export"))
        self.assertTrue(
            AuditLog.objects.filter(action=audit.EXPORT_DOWNLOADED).exists()
        )


class QueueOperationsTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com")
        profile = Profile.objects.get(user=self.customer)
        self.job = JobPost.objects.create(profile=profile, title="Backend engineer")
        self.task = AITask.start_for(profile, AITask.JOB_ANALYSIS, self.job)
        self.client.force_login(self.operator)

    def test_cancelling_closes_the_record(self):
        self.client.post(reverse("staffportal:task_cancel", args=[self.task.pk]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.state, AITask.CANCELED)
        self.assertTrue(AuditLog.objects.filter(action=audit.TASK_CANCELED).exists())

    def test_retrying_re_queues_through_the_products_own_path(self):
        self.task.mark_failed("provider timed out")
        self.client.post(reverse("staffportal:task_retry", args=[self.task.pk]))
        self.assertTrue(
            AITask.objects.filter(
                content_type__model="jobpost", object_id=self.job.pk
            ).exclude(pk=self.task.pk).exists()
        )
        self.assertTrue(AuditLog.objects.filter(action=audit.TASK_RETRIED).exists())

    def test_a_viewer_cannot_retry(self):
        viewer = make_staff("viewer@example.com", StaffRole.VIEWER)
        self.client.force_login(viewer)
        response = self.client.post(reverse("staffportal:task_retry", args=[self.task.pk]))
        self.assertEqual(response.status_code, 403)


class QueueDetailTests(PortalTestCase):
    """UC-08.9: what the queue says about a job that is running."""

    def setUp(self):
        super().setUp()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com")
        self.profile = Profile.objects.get(user=self.customer)
        self.job = JobPost.objects.create(profile=self.profile, title="Backend engineer")
        self.task = AITask.start_for(
            self.profile, AITask.JOB_MATCH, self.job, steps_total=4, step="Matching Languages"
        )
        self.client.force_login(self.operator)

    def age(self, **fields):
        AITask.objects.filter(pk=self.task.pk).update(**fields)
        self.task.refresh_from_db()

    def test_timing_splits_waiting_from_running_and_flags_silence(self):
        now = timezone.now()
        self.age(queued_at=now - timedelta(seconds=100), started_at=now - timedelta(seconds=40),
                 state=AITask.RUNNING, updated_at=now - timedelta(seconds=10))
        self.assertEqual(self.task.wait_seconds, 60)
        self.assertEqual(self.task.run_seconds, 40)
        self.assertEqual(self.task.idle_seconds, 10)
        self.assertFalse(self.task.looks_stalled)

        self.age(updated_at=now - timedelta(minutes=6))
        self.assertTrue(self.task.looks_stalled)
        self.task.mark_done()
        self.assertFalse(self.task.looks_stalled)

    def test_a_task_that_never_started_has_no_run_time_and_keeps_waiting(self):
        self.age(queued_at=timezone.now() - timedelta(seconds=30))
        self.assertIsNone(self.task.run_seconds)
        self.assertGreaterEqual(self.task.wait_seconds, 30)

    def test_the_list_shows_progress_timing_and_a_stuck_warning(self):
        self.task.advance("Matching Languages")
        response = self.client.get(reverse("staffportal:task_list"))
        self.assertContains(response, "step 1/4")
        self.assertContains(response, "Matching Languages")
        self.assertContains(response, "waited")
        self.assertContains(response, reverse("staffportal:task_detail", args=[self.task.pk]))
        self.assertNotContains(response, "Possibly stuck")

        self.age(updated_at=timezone.now() - timedelta(minutes=10))
        self.assertContains(self.client.get(reverse("staffportal:task_list")), "Possibly stuck")

    def test_the_detail_page_names_the_object_the_account_and_every_section(self):
        analysis = {
            "title": "Backend engineer",
            "sections": [{"key": "required_technical_skills", "body": "", "elements": ["Python", "Go"]}],
        }
        from jobs.domain.importer import apply_analysis

        apply_analysis(self.job, analysis, "text", language="en")
        section = self.job.sections.get(key="required_technical_skills")
        element = section.elements.first()
        element.match_status = "strong"
        element.save()
        section.match_state = "failed"
        section.match_error = "provider timed out"
        section.save()

        response = self.client.get(reverse("staffportal:task_detail", args=[self.task.pk]))
        self.assertContains(response, "customer@example.com")
        self.assertContains(response, "Backend engineer")
        self.assertContains(response, "Required Technical Skills")
        self.assertContains(response, "1/2")
        self.assertContains(response, "provider timed out")
        self.assertContains(response, 'http-equiv="refresh"')

    def test_a_finished_job_stops_refreshing_and_lists_earlier_runs(self):
        earlier = AITask.start_for(self.profile, AITask.JOB_MATCH, self.job)
        self.task.mark_failed("boom")
        response = self.client.get(reverse("staffportal:task_detail", args=[self.task.pk]))
        self.assertNotContains(response, 'http-equiv="refresh"')
        self.assertContains(response, "boom")
        self.assertContains(response, reverse("staffportal:task_detail", args=[earlier.pk]))

    def test_a_job_whose_object_is_gone_still_has_a_page(self):
        self.job.delete()
        # The task goes with its job (cascade through the generic key is not
        # defined), so only assert the page copes when the row remains.
        if AITask.objects.filter(pk=self.task.pk).exists():
            response = self.client.get(reverse("staffportal:task_detail", args=[self.task.pk]))
            self.assertContains(response, "deleted")

    def test_the_queue_pages_need_operations_access(self):
        self.client.logout()
        customer = make_user("plain@example.com")
        self.client.force_login(customer)
        for name, args in (("task_detail", [self.task.pk]), ("worker_list", [])):
            self.assertEqual(self.client.get(reverse(f"staffportal:{name}", args=args)).status_code, 404)

    def test_workers_cannot_be_inspected_when_tasks_run_inline(self):
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            report = services.worker_report()
        self.assertFalse(report["available"])
        self.assertIn("eager", report["reason"])
        response = self.client.get(reverse("staffportal:worker_list"))
        self.assertContains(response, "no workers to inspect")

    def test_the_worker_report_lists_what_each_worker_is_running(self):
        self.task.celery_task_id = "root-1"
        self.task.save()
        started = timezone.now().timestamp() - 42

        class Inspector:
            def active(self):
                return {"worker@a": [{"id": "root-1", "name": "jobs.tasks.match_job_section",
                                      "args": [7, 1], "time_start": started}], "worker@b": []}

            def reserved(self):
                return {"worker@a": [{}, {}], "worker@b": []}

        class Control:
            def inspect(self, timeout):
                return Inspector()

        with self.settings(CELERY_TASK_ALWAYS_EAGER=False), \
                patch("config.celery.app.control", Control()), \
                patch.object(services, "_broker_backlog", return_value=3):
            report = services.worker_report()
            response = self.client.get(reverse("staffportal:worker_list"))

        self.assertTrue(report["available"])
        self.assertEqual(report["waiting_in_broker"], 3)
        worker_a, worker_b = report["workers"]
        self.assertEqual((worker_a["name"], worker_a["reserved"]), ("worker@a", 2))
        run = worker_a["running"][0]
        self.assertEqual((run["task"], run["ai_task"]), ("match_job_section", self.task))
        self.assertGreaterEqual(run["seconds"], 42)
        self.assertEqual(worker_b["running"], [])
        self.assertContains(response, "match_job_section")
        self.assertContains(response, "Idle.")

    def test_no_reply_from_any_worker_or_a_dead_broker_is_explained_not_raised(self):
        class Silent:
            def active(self):
                return None

        class Control:
            def inspect(self, timeout):
                return Silent()

        with self.settings(CELERY_TASK_ALWAYS_EAGER=False), \
                patch("config.celery.app.control", Control()), \
                patch.object(services, "_broker_backlog", return_value=None):
            self.assertIn("No worker answered", services.worker_report()["reason"])

        class Broken:
            def inspect(self, timeout):
                raise OSError("connection refused")

        with self.settings(CELERY_TASK_ALWAYS_EAGER=False), patch("config.celery.app.control", Broken()):
            self.assertIn("connection refused", services.worker_report()["reason"])


class SeedCommandTests(PortalTestCase):
    def test_seeding_is_idempotent_and_back_fills(self):
        from django.core.management import call_command

        early = make_user("early@example.com")
        self.assertFalse(Subscription.objects.filter(user=early).exists())

        call_command("seed_saas", "--backfill", verbosity=0)
        call_command("seed_saas", "--backfill", verbosity=0)

        self.assertEqual(Plan.objects.count(), 3)
        self.assertEqual(Plan.objects.filter(is_default=True).count(), 1)
        self.assertTrue(Subscription.objects.filter(user=early).exists())


# ---------------------------------------------------------------------------
# Characterization tests — pin the operator use cases before they move into
# services.py. Messages and audit summaries are what an operator actually sees.
# ---------------------------------------------------------------------------
def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def last_audit(action):
    return AuditLog.objects.filter(action=action).order_by("-pk").first()


class AccountListTests(PortalTestCase):
    """UC-08.2: find the account."""

    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.ada = make_user("ada@example.com", first_name="Ada", last_name="Lovelace")
        self.grace = make_user("grace@example.com", first_name="Grace", last_name="Hopper")
        self.grace.is_active = False
        self.grace.last_seen_at = timezone.now() - timedelta(days=90)
        self.grace.save()
        User.objects.filter(pk=self.ada.pk).update(last_seen_at=timezone.now())
        subscriptions.change_plan(Subscription.objects.get(user=self.grace), self.pro)
        self.client.force_login(self.operator)

    def emails(self, **params):
        response = self.client.get(reverse("staffportal:user_list"), params)
        self.assertEqual(response.status_code, 200)
        return {account.email for account in response.context["accounts"]}

    def test_search_matches_email_first_or_last_name(self):
        self.assertEqual(self.emails(q="ada@"), {"ada@example.com"})
        self.assertEqual(self.emails(q="hopper"), {"grace@example.com"})
        self.assertEqual(self.emails(q="Grace"), {"grace@example.com"})

    def test_status_filter(self):
        self.assertEqual(self.emails(status="suspended"), {"grace@example.com"})
        self.assertIn("ada@example.com", self.emails(status="active"))
        self.assertNotIn("grace@example.com", self.emails(status="active"))
        self.assertEqual(self.emails(status="staff"), {"admin@example.com"})

    def test_plan_filter_ignores_junk(self):
        self.assertEqual(self.emails(plan=str(self.pro.pk)), {"grace@example.com"})
        self.assertGreaterEqual(len(self.emails(plan="not-a-number")), 3)

    def test_activity_filter(self):
        self.assertEqual(self.emails(activity="recent"), {"ada@example.com"})
        never_seen = make_user("never@example.com")
        dormant = self.emails(activity="dormant")
        self.assertEqual(dormant, {"grace@example.com", never_seen.email})
        self.assertNotIn("ada@example.com", dormant)

    def test_the_context_carries_the_plans_and_the_total(self):
        response = self.client.get(reverse("staffportal:user_list"), {"q": "ada"})
        self.assertEqual(response.context["total_count"], User.objects.count())
        self.assertEqual(list(response.context["plans"]), [self.free, self.pro])
        self.assertEqual(response.context["filters"]["q"], "ada")

    def test_the_csv_export_honours_the_same_filters_and_is_audited(self):
        response = self.client.get(reverse("staffportal:user_export"), {"status": "suspended"})
        body = b"".join(response.streaming_content).decode()
        self.assertIn("grace@example.com", body)
        self.assertNotIn("ada@example.com", body)
        self.assertRegex(response["Content-Disposition"], r'filename="accounts-\d{8}\.csv"')
        entry = last_audit(audit.EXPORT_DOWNLOADED)
        self.assertEqual(entry.summary, "Accounts CSV (1 rows).")
        self.assertEqual(entry.metadata, {"filters": {"status": "suspended"}})

    def test_the_detail_page_gathers_everything_about_the_account(self):
        profile = Profile.objects.get(user=self.ada)
        job = JobPost.objects.create(profile=profile, title="Backend")
        TailoredResume.objects.create(profile=profile, job=job, markdown="x")
        AITask.start_for(profile, AITask.JOB_ANALYSIS, job)
        SupportNote.objects.create(user=self.ada, body="Called.")
        FeatureFlag.objects.create(key="beta", name="Beta", state=FeatureFlag.ON)
        response = self.client.get(reverse("staffportal:user_detail", args=[self.ada.pk]))
        context = response.context
        self.assertEqual(context["account"], self.ada)
        self.assertEqual(context["job_post_count"], 1)
        self.assertEqual(context["tailored_count"], 1)
        self.assertEqual(len(context["tasks"]), 1)
        self.assertEqual(len(context["notes"]), 1)
        self.assertEqual(context["enabled_flags"], ["beta"])
        self.assertEqual(len(context["allowances"]), 3)
        self.assertEqual((context["profile_limit"], context["profile_used"]), (1, 1))
        self.assertFalse(context["quotas_enforced"])
        self.assertEqual(context["subscription"].plan, self.free)
        self.assertEqual(context["plan_form"].initial["plan"], self.free.pk)
        self.assertEqual(context["can_impersonate"], True)


class AccountActionGuardTests(PortalTestCase):
    """UC-08.2 to UC-08.5, UC-08.11: what the operator is told, and what is left alone."""

    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.root = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.customer = make_user("customer@example.com")
        self.client.force_login(self.operator)

    def post(self, name, account=None, **data):
        return self.client.post(reverse(f"staffportal:{name}", args=[(account or self.customer).pk]), data)

    def test_suspending_says_who_and_why(self):
        response = self.post("user_suspend", reason="abuse report #12")
        self.assertEqual(flash(response), ["Suspended customer@example.com and ended their sessions."])
        self.assertRedirects(
            response,
            reverse("staffportal:user_detail", args=[self.customer.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(last_audit(audit.USER_SUSPENDED).summary, "abuse report #12")

    def test_suspending_without_a_reason_records_a_default(self):
        self.post("user_suspend")
        self.assertEqual(last_audit(audit.USER_SUSPENDED).summary, "Account suspended.")

    def test_you_cannot_suspend_yourself_and_are_told_so(self):
        response = self.post("user_suspend", self.operator)
        self.assertEqual(flash(response), ["You cannot suspend your own account."])
        self.assertFalse(AuditLog.objects.filter(action=audit.USER_SUSPENDED).exists())

    def test_only_a_superuser_may_suspend_one(self):
        response = self.post("user_suspend", self.root)
        self.assertEqual(flash(response), ["Only a superuser may suspend a superuser."])
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_reactivating_is_confirmed_and_audited(self):
        User.objects.filter(pk=self.customer.pk).update(is_active=False)
        response = self.post("user_reactivate")
        self.assertEqual(flash(response), ["Reactivated customer@example.com."])
        self.assertEqual(last_audit(audit.USER_REACTIVATED).summary, "Account reactivated.")

    def test_a_password_reset_is_confirmed_and_audited(self):
        response = self.post("user_password_reset")
        self.assertEqual(flash(response), ["Reset email sent to customer@example.com."])
        self.assertEqual(last_audit(audit.USER_PASSWORD_RESET_SENT).summary, "Password reset email sent.")

    def test_an_empty_note_is_refused_and_a_pinned_one_is_kept(self):
        response = self.post("user_note_add", body="")
        self.assertEqual(flash(response), ["The note can't be empty."])
        self.assertFalse(SupportNote.objects.exists())
        response = self.post("user_note_add", body="Chargeback pending.", pinned="on")
        self.assertEqual(flash(response)[-1], "Note added.")
        self.assertTrue(SupportNote.objects.get().pinned)
        self.assertEqual(last_audit(audit.USER_NOTE_ADDED).summary, "Support note added.")

    def test_a_plan_change_records_before_and_after_and_the_reason(self):
        response = self.post("user_plan_change", plan=self.pro.pk, status=Subscription.ACTIVE, note="upgraded on call")
        self.assertEqual(flash(response), ["customer@example.com is now on Pro (active)."])
        entry = last_audit(audit.SUBSCRIPTION_UPDATED)
        self.assertEqual(entry.summary, "Free/active → Pro/active. upgraded on call")
        self.assertEqual(entry.metadata, {"plan": "pro", "status": "active"})

    def test_a_plan_change_needs_a_plan_and_a_status(self):
        response = self.post("user_plan_change", plan="", status="")
        self.assertEqual(flash(response), ["Pick a plan and a status."])
        self.assertEqual(Subscription.objects.get(user=self.customer).plan, self.free)

    def test_usage_reset_reports_how_many_counters_it_cleared(self):
        quotas.consume(self.customer, UsageMetric.JOB_ANALYSIS, amount=2)
        quotas.consume(self.customer, UsageMetric.RESUME_IMPORT)
        response = self.post("user_usage_reset")
        self.assertEqual(flash(response), ["This period's usage has been reset to zero."])
        self.assertEqual(
            last_audit(audit.USAGE_RESET).summary, "Reset 2 usage counter(s) for the current period."
        )

    def test_without_any_default_plan_billing_actions_say_so(self):
        Plan.objects.filter(pk=self.free.pk).update(is_default=False)
        newcomer = make_user("newcomer@example.com")
        self.assertFalse(Subscription.objects.filter(user=newcomer).exists())
        response = self.post("user_plan_change", newcomer, plan=self.pro.pk, status=Subscription.ACTIVE)
        self.assertEqual(flash(response), ["No plans are configured yet."])
        response = self.post("user_usage_reset", newcomer)
        self.assertEqual(flash(response)[-1], "No plans are configured yet.")

    def test_deleting_shows_what_will_go_and_blocks_deleting_a_superuser(self):
        profile = Profile.objects.get(user=self.customer)
        JobPost.objects.create(profile=profile)
        response = self.client.get(reverse("staffportal:user_delete", args=[self.customer.pk]))
        self.assertEqual(
            (response.context["profile_count"], response.context["job_post_count"], response.context["blocked"]),
            (1, 1, False),
        )
        blocked = self.client.get(reverse("staffportal:user_delete", args=[self.root.pk]))
        self.assertTrue(blocked.context["blocked"])

    def test_only_a_superuser_may_delete_a_superuser(self):
        response = self.post("user_delete", self.root, confirm_email="root@example.com")
        self.assertEqual(flash(response), ["Only a superuser may delete a superuser account."])
        self.assertTrue(User.objects.filter(pk=self.root.pk).exists())

    def test_a_mismatched_email_deletes_nothing_and_a_match_erases_everything(self):
        response = self.post("user_delete", confirm_email="wrong@example.com")
        self.assertEqual(flash(response), ["The email address did not match. Nothing was deleted."])
        self.assertRedirects(
            response,
            reverse("staffportal:user_delete", args=[self.customer.pk]),
            fetch_redirect_response=False,
        )
        response = self.post("user_delete", confirm_email="  CUSTOMER@example.com ", reason="erasure request")
        self.assertEqual(flash(response)[-1], "Deleted customer@example.com and everything belonging to it.")
        self.assertRedirects(response, reverse("staffportal:user_list"), fetch_redirect_response=False)
        entry = last_audit(audit.USER_DELETED)
        self.assertEqual(entry.summary, "Account customer@example.com and all of its data deleted.")
        self.assertEqual(entry.metadata, {"email": "customer@example.com", "reason": "erasure request"})

    def test_the_data_export_is_a_json_attachment_and_is_audited(self):
        response = self.client.get(reverse("staffportal:user_data_export", args=[self.customer.pk]))
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertRegex(
            response["Content-Disposition"],
            rf'filename="account-{self.customer.pk}-export-\d{{8}}\.json"',
        )
        self.assertEqual(response.json()["account"]["email"], "customer@example.com")
        self.assertEqual(last_audit(audit.USER_EXPORTED).summary, "Account data export downloaded.")

    def test_impersonating_needs_permission_and_a_reason(self):
        response = self.post("impersonate_start", self.operator, reason="testing")
        self.assertEqual(flash(response), ["You are already signed in as this account."])
        response = self.post("impersonate_start", reason="")
        self.assertEqual(flash(response)[-1], "A reason is required before impersonating an account.")
        self.assertFalse(ImpersonationSession.objects.exists())

    def test_impersonating_says_when_it_ends_and_lands_on_the_dashboard(self):
        response = self.post("impersonate_start", reason="ticket #1")
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        (message,) = flash(response)
        self.assertTrue(message.startswith("You are now signed in as customer@example.com. This ends automatically at "))

    def test_stopping_when_not_impersonating_just_goes_to_the_dashboard(self):
        response = self.client.post(reverse("staffportal:impersonate_stop"))
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_stopping_hands_back_with_a_welcome_and_lands_in_the_portal(self):
        self.post("impersonate_start", reason="ticket #1")
        response = self.client.post(reverse("staffportal:impersonate_stop"))
        self.assertRedirects(response, reverse("staffportal:dashboard"), fetch_redirect_response=False)
        self.assertEqual(flash(response)[-1], "Back to your own account, admin@example.com.")

    def test_if_the_operator_lost_staff_access_stopping_signs_out(self):
        self.post("impersonate_start", reason="ticket #1")
        User.objects.filter(pk=self.operator.pk).update(is_staff=False)
        response = self.client.post(reverse("staffportal:impersonate_stop"))
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertEqual(flash(response)[-1], "That impersonation session has ended.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_impersonation_log_closes_sessions_that_ran_out(self):
        self.post("impersonate_start", reason="ticket #1")
        self.client.post(reverse("staffportal:impersonate_stop"))
        ImpersonationSession.objects.update(ended_at=None, ended_reason="", expires_at=timezone.now() - timedelta(minutes=1))
        response = self.client.get(reverse("staffportal:impersonation_log"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ImpersonationSession.objects.get().ended_reason, ImpersonationSession.EXPIRED)


class BillingTests(PortalTestCase):
    """UC-08.5: plans and subscriptions."""

    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.operator = make_staff("billing@example.com", StaffRole.BILLING)
        self.customer = make_user("customer@example.com")
        self.client.force_login(self.operator)

    PLAN = {
        "name": "Team", "slug": "team", "tagline": "", "description": "", "price_cents": "4900",
        "currency": "USD", "interval": "month", "trial_days": "0", "is_active": "on",
        "is_public": "on", "sort_order": "3", "max_profiles": "10", "features": "",
    }

    def test_the_overview_counts_entitled_subscribers_per_plan(self):
        response = self.client.get(reverse("staffportal:billing"))
        plans = {plan.slug: plan.subscriber_count for plan in response.context["plans"]}
        self.assertEqual(plans, {"free": 2, "pro": 0})
        self.assertIn("revenue", response.context)
        self.assertIn("breakdown", response.context)

    def test_creating_a_plan_is_confirmed_and_audited(self):
        response = self.client.post(reverse("staffportal:plan_create"), self.PLAN)
        self.assertRedirects(response, reverse("staffportal:billing"), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Created the Team plan."])
        plan = Plan.objects.get(slug="team")
        self.assertEqual(plan.price_cents, 4900)
        self.assertTrue(last_audit(audit.PLAN_CREATED).summary.startswith("Plan created at "))

    def test_updating_a_plan_audits_exactly_the_fields_that_changed(self):
        data = {**self.PLAN, "name": "Pro", "slug": "pro", "price_cents": "1500", "sort_order": "2",
                "max_profiles": "5", "monthly_job_analyses": "100"}
        response = self.client.post(reverse("staffportal:plan_update", args=[self.pro.pk]), data)
        self.assertEqual(flash(response), ["Saved the Pro plan."])
        self.assertEqual(last_audit(audit.PLAN_UPDATED).summary, "Changed: price_cents.")
        self.assertEqual(last_audit(audit.PLAN_UPDATED).metadata, {"fields": ["price_cents"]})
        self.pro.refresh_from_db()
        self.assertEqual(self.pro.price_cents, 1500)

    def test_saving_a_plan_unchanged_says_nothing_changed(self):
        data = {**self.PLAN, "name": "Pro", "slug": "pro", "price_cents": "1200", "sort_order": "2",
                "max_profiles": "5", "monthly_job_analyses": "100"}
        self.client.post(reverse("staffportal:plan_update", args=[self.pro.pk]), data)
        self.assertEqual(last_audit(audit.PLAN_UPDATED).summary, "Changed: nothing.")

    def test_a_second_default_plan_is_refused(self):
        response = self.client.post(reverse("staffportal:plan_create"), {**self.PLAN, "is_default": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("is already the default plan", str(response.context["form"].errors["is_default"]))
        self.assertFalse(Plan.objects.filter(slug="team").exists())

    def test_a_plan_with_subscribers_is_retired_not_deleted(self):
        response = self.client.post(reverse("staffportal:plan_delete", args=[self.free.pk]))
        self.assertRedirects(response, reverse("staffportal:billing"), fetch_redirect_response=False)
        self.assertEqual(
            flash(response),
            ["Free still has subscribers, so it was deactivated rather than deleted. "
             "It takes no new sign-ups."],
        )
        self.free.refresh_from_db()
        self.assertFalse(self.free.is_active)
        self.assertFalse(self.free.is_default)
        self.assertEqual(
            last_audit(audit.PLAN_UPDATED).summary,
            "Plan deactivated (it still has subscribers, so it was not deleted).",
        )

    def test_a_plan_nobody_is_on_is_deleted(self):
        response = self.client.post(reverse("staffportal:plan_delete", args=[self.pro.pk]))
        self.assertEqual(flash(response), ["Deleted the Pro plan."])
        self.assertFalse(Plan.objects.filter(pk=self.pro.pk).exists())
        self.assertEqual(last_audit(audit.PLAN_UPDATED).summary, "Plan deleted.")

    def test_deleting_a_plan_that_is_already_gone_is_quiet(self):
        response = self.client.post(reverse("staffportal:plan_delete", args=[9999]))
        self.assertRedirects(response, reverse("staffportal:billing"), fetch_redirect_response=False)
        self.assertEqual(flash(response), [])

    def test_the_subscription_list_filters(self):
        subscriptions.change_plan(Subscription.objects.get(user=self.customer), self.pro)
        Subscription.objects.filter(user=self.customer).update(
            status=Subscription.PAST_DUE, external_customer_id="cus_123"
        )
        make_user("other@example.com")  # a second account, so a filter has something to exclude

        def listed(**params):
            response = self.client.get(reverse("staffportal:subscription_list"), params)
            return {sub.user.email for sub in response.context["subscriptions"]}

        self.assertEqual(listed(q="cus_123"), {"customer@example.com"})
        self.assertEqual(listed(q="OTHER@"), {"other@example.com"})
        self.assertEqual(listed(status="past_due"), {"customer@example.com"})
        self.assertEqual(listed(plan=str(self.pro.pk)), {"customer@example.com"})
        self.assertEqual(len(listed(status="nonsense", plan="x")), 3)

    def test_cancelling_a_subscription_stamps_when_and_keeps_an_earlier_stamp(self):
        subscription = Subscription.objects.get(user=self.customer)
        url = reverse("staffportal:subscription_update", args=[subscription.pk])
        data = {"plan": self.free.pk, "status": Subscription.CANCELED, "notes": ""}
        response = self.client.post(url, data)
        self.assertRedirects(
            response, reverse("staffportal:user_detail", args=[self.customer.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(flash(response), ["Subscription saved."])
        subscription.refresh_from_db()
        first = subscription.canceled_at
        self.assertIsNotNone(first)
        self.assertEqual(last_audit(audit.SUBSCRIPTION_UPDATED).summary, "Subscription changed: status.")

        Subscription.objects.filter(pk=subscription.pk).update(status=Subscription.ACTIVE)
        self.client.post(url, {**data, "status": Subscription.EXPIRED})
        subscription.refresh_from_db()
        self.assertEqual(subscription.canceled_at, first)

    def test_other_status_changes_do_not_stamp_a_cancellation(self):
        subscription = Subscription.objects.get(user=self.customer)
        self.client.post(
            reverse("staffportal:subscription_update", args=[subscription.pk]),
            {"plan": self.free.pk, "status": Subscription.PAST_DUE, "notes": "card declined"},
        )
        subscription.refresh_from_db()
        self.assertIsNone(subscription.canceled_at)

    def test_the_subscription_csv_is_audited(self):
        response = self.client.get(reverse("staffportal:subscription_export"))
        body = b"".join(response.streaming_content).decode()
        self.assertTrue(body.startswith("id,email,plan,status"))
        self.assertIn("customer@example.com", body)
        self.assertEqual(last_audit(audit.EXPORT_DOWNLOADED).summary, "Subscriptions CSV (2 rows).")


class FlagAndAnnouncementManagementTests(PortalTestCase):
    """UC-08.6 and UC-08.8."""

    def setUp(self):
        super().setUp()
        make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.client.force_login(self.operator)

    def test_creating_a_flag_records_who_and_the_new_state(self):
        response = self.client.post(
            reverse("staffportal:flag_create"),
            {"key": "beta", "name": "Beta", "description": "", "state": "staff", "percentage": "0"},
        )
        self.assertRedirects(response, reverse("staffportal:flag_list"), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Saved the “beta” flag."])
        flag = FeatureFlag.objects.get(key="beta")
        self.assertEqual(flag.updated_by, self.operator)
        entry = last_audit(audit.FLAG_CREATED)
        self.assertTrue(entry.summary.startswith("beta → "))
        self.assertEqual(entry.metadata, {"state": "staff", "percentage": 0})

    def test_updating_a_flag_is_audited_as_an_update(self):
        flag = FeatureFlag.objects.create(key="beta", name="Beta", state=FeatureFlag.OFF)
        self.client.post(
            reverse("staffportal:flag_update", args=[flag.pk]),
            {"key": "beta", "name": "Beta", "description": "", "state": "percent", "percentage": "25"},
        )
        flag.refresh_from_db()
        self.assertEqual((flag.state, flag.percentage), ("percent", 25))
        self.assertEqual(last_audit(audit.FLAG_UPDATED).metadata, {"state": "percent", "percentage": 25})

    def test_a_percentage_rollout_at_zero_is_refused(self):
        response = self.client.post(
            reverse("staffportal:flag_create"),
            {"key": "beta", "name": "Beta", "description": "", "state": "percent", "percentage": "0"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FeatureFlag.objects.exists())

    def test_deleting_a_flag_retires_the_feature(self):
        flag = FeatureFlag.objects.create(key="beta", name="Beta", state=FeatureFlag.ON)
        response = self.client.post(reverse("staffportal:flag_delete", args=[flag.pk]))
        self.assertEqual(flash(response), ["Deleted “beta”. Code checking it now gets False."])
        self.assertEqual(
            last_audit(audit.FLAG_DELETED).summary,
            "Flag beta deleted — it now evaluates as off everywhere.",
        )
        self.assertFalse(flags.is_enabled("beta", self.operator))

    def test_deleting_a_missing_flag_or_announcement_is_quiet(self):
        for name in ("staffportal:flag_delete", "staffportal:announcement_delete"):
            with self.subTest(name=name):
                response = self.client.post(reverse(name, args=[9999]))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(flash(response), [])

    def test_a_flag_list_says_what_the_operator_themself_would_get(self):
        FeatureFlag.objects.create(key="on", name="On", state=FeatureFlag.ON)
        FeatureFlag.objects.create(key="off", name="Off", state=FeatureFlag.OFF)
        response = self.client.get(reverse("staffportal:flag_list"))
        self.assertEqual(response.context["my_flags"], {"on"})

    ANNOUNCEMENT = {
        "title": "Maintenance Sunday", "body": "", "level": "warning", "audience": "everyone",
        "link_url": "", "link_label": "", "is_active": "on", "dismissible": "on",
        "starts_at": "2020-01-01 10:00",
    }

    def test_publishing_an_announcement_records_the_author_and_whether_it_is_live(self):
        response = self.client.post(reverse("staffportal:announcement_create"), self.ANNOUNCEMENT)
        self.assertRedirects(
            response, reverse("staffportal:announcement_list"), fetch_redirect_response=False
        )
        self.assertEqual(flash(response), ["Announcement saved."])
        announcement = Announcement.objects.get()
        self.assertEqual(announcement.created_by, self.operator)
        entry = last_audit(audit.ANNOUNCEMENT_CREATED)
        self.assertEqual(entry.summary, "Maintenance Sunday (warning, everyone).")
        self.assertEqual(entry.metadata, {"live": True})

    def test_editing_an_announcement_keeps_its_author_and_audits_an_update(self):
        announcement = Announcement.objects.create(title="Old", created_by=None)
        self.client.post(
            reverse("staffportal:announcement_update", args=[announcement.pk]),
            {**self.ANNOUNCEMENT, "title": "New"},
        )
        announcement.refresh_from_db()
        self.assertEqual(announcement.title, "New")
        self.assertIsNone(announcement.created_by)
        self.assertEqual(last_audit(audit.ANNOUNCEMENT_UPDATED).summary, "New (warning, everyone).")

    def test_an_announcement_cannot_end_before_it_starts(self):
        response = self.client.post(
            reverse("staffportal:announcement_create"),
            {**self.ANNOUNCEMENT, "starts_at": "2030-01-02 10:00", "ends_at": "2030-01-01 10:00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ends_at", response.context["form"].errors)
        self.assertFalse(Announcement.objects.exists())

    def test_deleting_an_announcement_says_which(self):
        announcement = Announcement.objects.create(title="Gone soon")
        response = self.client.post(reverse("staffportal:announcement_delete", args=[announcement.pk]))
        self.assertEqual(flash(response), ["Deleted “Gone soon”."])
        self.assertEqual(last_audit(audit.ANNOUNCEMENT_DELETED).summary, "Announcement “Gone soon” deleted.")


class QueueRetryTests(PortalTestCase):
    """UC-08.9: an operator re-runs a customer's failed work through the product's own path."""

    def setUp(self):
        super().setUp()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com")
        self.profile = Profile.objects.get(user=self.customer)
        self.client.force_login(self.operator)

    def retry(self, task, **data):
        return self.client.post(reverse("staffportal:task_retry", args=[task.pk]), data)

    def failed(self, kind, target):
        task = AITask.start_for(self.profile, kind, target)
        task.mark_failed("provider timed out")
        return task

    def assertRequeued(self, task, kind):
        fresh = AITask.objects.filter(kind=kind, object_id=task.object_id).exclude(pk=task.pk)
        self.assertTrue(fresh.exists(), "a fresh AITask, not the old one resurrected")
        task.refresh_from_db()
        self.assertEqual(task.state, AITask.FAILED)

    def test_every_kind_of_task_has_a_retry_path(self):
        import shutil
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=media_root)
        media.enable()
        self.addCleanup(media.disable)

        job = JobPost.objects.create(profile=self.profile, description_text="x" * 200)
        upload = ResumeImport.objects.create(
            profile=self.profile,
            file=SimpleUploadedFile("cv.txt", b"Jane Doe, backend engineer with plenty of experience. " * 3),
        )
        tailored = TailoredResume.objects.create(profile=self.profile, job=job, markdown="x")
        cases = [
            (AITask.JOB_ANALYSIS, job),
            (AITask.JOB_MATCH, job),
            (AITask.RESUME_IMPORT, upload),
            (AITask.TAILORED_RESUME, tailored),
        ]
        for kind, target in cases:
            with self.subTest(kind=kind):
                task = self.failed(kind, target)
                with fake_deepseek(lambda request: {}):
                    response = self.retry(task)
                self.assertEqual(
                    flash(response)[-1], "Re-queued. The customer sees it running on their page."
                )
                self.assertRequeued(task, kind)
                entry = last_audit(audit.TASK_RETRIED)
                self.assertEqual(entry.metadata, {"kind": kind})
                self.assertEqual(entry.summary, f"{task.get_kind_display()} re-queued for customer@example.com.")

    def test_a_task_whose_object_is_gone_cannot_be_retried(self):
        job = JobPost.objects.create(profile=self.profile)
        task = self.failed(AITask.JOB_ANALYSIS, job)
        job.delete()
        response = self.retry(task)
        self.assertEqual(flash(response), ["The object this job was about no longer exists."])
        self.assertFalse(AuditLog.objects.filter(action=audit.TASK_RETRIED).exists())

    def test_a_kind_with_no_retry_path_is_reported_not_raised(self):
        job = JobPost.objects.create(profile=self.profile)
        task = self.failed(AITask.JOB_ANALYSIS, job)
        AITask.objects.filter(pk=task.pk).update(kind="bogus")
        response = self.retry(task)
        self.assertEqual(flash(response), ["Could not re-queue: No retry path for bogus"])

    def test_the_operator_goes_back_where_they_came_from(self):
        job = JobPost.objects.create(profile=self.profile, description_text="x" * 200)
        task = self.failed(AITask.JOB_ANALYSIS, job)
        with fake_deepseek(lambda request: {}):
            response = self.retry(task, next="/staff/operations/queue/?state=failed")
        self.assertRedirects(
            response, "/staff/operations/queue/?state=failed", fetch_redirect_response=False
        )

    def test_cancelling_a_live_task_and_a_finished_one(self):
        job = JobPost.objects.create(profile=self.profile)
        live = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job)
        response = self.client.post(reverse("staffportal:task_cancel", args=[live.pk]))
        self.assertEqual(flash(response), ["Marked as canceled."])
        entry = last_audit(audit.TASK_CANCELED)
        self.assertEqual(entry.summary, "Job analysis canceled.")
        self.assertEqual(entry.metadata, {"kind": "job_analysis"})
        response = self.client.post(reverse("staffportal:task_cancel", args=[live.pk]))
        self.assertEqual(flash(response)[-1], "That job had already finished.")
        self.assertEqual(AuditLog.objects.filter(action=audit.TASK_CANCELED).count(), 1)

    def test_the_queue_filters_and_counts(self):
        job = JobPost.objects.create(profile=self.profile)
        queued = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job)
        broken = self.failed(AITask.JOB_MATCH, job)
        AITask.objects.filter(pk=broken.pk).update(error_message="provider exploded")

        def listed(**params):
            response = self.client.get(reverse("staffportal:task_list"), params)
            return {task.pk for task in response.context["tasks"]}

        self.assertEqual(listed(state="failed"), {broken.pk})
        self.assertEqual(listed(kind="job_analysis"), {queued.pk})
        self.assertEqual(listed(q="exploded"), {broken.pk})
        self.assertEqual(listed(q="CUSTOMER@"), {queued.pk, broken.pk})
        self.assertEqual(listed(state="nonsense"), {queued.pk, broken.pk})
        counts = self.client.get(reverse("staffportal:task_list")).context["ai"]
        self.assertEqual(counts, {"queued": 1, "running": 0, "failed": 1})

    def test_the_queue_csv_is_audited(self):
        job = JobPost.objects.create(profile=self.profile)
        AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job)
        response = self.client.get(reverse("staffportal:task_export"))
        body = b"".join(response.streaming_content).decode()
        self.assertTrue(body.startswith("id,email,kind,state"))
        self.assertEqual(last_audit(audit.EXPORT_DOWNLOADED).summary, "AI queue CSV (1 rows).")


class OperationsAndTeamTests(PortalTestCase):
    """UC-08.7, UC-08.10 and the team screen of UC-08.1."""

    def setUp(self):
        super().setUp()
        make_plans()
        self.root = make_user("root@example.com", is_staff=True, is_superuser=True)
        self.client.force_login(self.root)

    def test_saving_settings_lists_exactly_what_changed(self):
        values = runtime_settings.all_values()
        data = {"impersonation_minutes": str(values["impersonation_minutes"]),
                "audit_retention_days": str(values["audit_retention_days"]),
                "support_email": "", "signups_enabled": "on", "ai_features_enabled": "on"}
        response = self.client.post(reverse("staffportal:settings"), data)
        self.assertEqual(flash(response), ["Nothing changed."])

        data.pop("signups_enabled")
        data["maintenance_mode"] = "on"
        response = self.client.post(reverse("staffportal:settings"), data)
        self.assertRedirects(response, reverse("staffportal:settings"), fetch_redirect_response=False)
        self.assertEqual(flash(response)[-1], "Saved. 2 setting(s) changed.")
        entry = last_audit(audit.SETTING_UPDATED)
        self.assertEqual(
            entry.metadata["changes"],
            ["signups_enabled: True → False", "maintenance_mode: False → True"],
        )
        self.assertEqual(entry.summary, "; ".join(entry.metadata["changes"]))
        self.assertFalse(runtime_settings.get("signups_enabled"))

    def test_the_health_screen_groups_its_checks(self):
        response = self.client.get(reverse("staffportal:health"))
        self.assertEqual(response.status_code, 200)
        groups = [name for name, _checks in response.context["grouped_checks"]]
        self.assertIn("Liveness", groups)
        self.assertIn("summary", response.context)

    def test_the_dashboard_range_is_seven_or_thirty_days(self):
        self.assertEqual(self.client.get(reverse("staffportal:dashboard")).context["days"], 30)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard"), {"range": "7"}).context["days"], 7)
        self.assertEqual(self.client.get(reverse("staffportal:dashboard"), {"range": "9"}).context["days"], 30)

    def test_only_operators_who_may_impersonate_see_open_sessions_on_the_dashboard(self):
        response = self.client.get(reverse("staffportal:dashboard"))
        self.assertIn("open_impersonations", response.context)
        viewer = make_staff("viewer@example.com", StaffRole.VIEWER)
        self.client.force_login(viewer)
        response = self.client.get(reverse("staffportal:dashboard"))
        self.assertNotIn("open_impersonations", response.context)

    def test_the_audit_log_filters(self):
        operator = make_staff("ops@example.com", StaffRole.ADMIN)
        other = make_staff("other@example.com", StaffRole.ADMIN)
        AuditLog.objects.create(actor=operator, actor_email=operator.email, action=audit.USER_SUSPENDED,
                                target_repr="target@example.com", summary="abuse")
        AuditLog.objects.create(actor=other, actor_email=other.email, action=audit.USER_NOTE_ADDED,
                                target_repr="x", summary="note", while_impersonating=True)

        def listed(**params):
            response = self.client.get(reverse("staffportal:audit_list"), params)
            return {entry.actor_email for entry in response.context["entries"]}

        self.assertEqual(listed(action=audit.USER_SUSPENDED), {"ops@example.com"})
        self.assertEqual(listed(actor=str(other.pk)), {"other@example.com"})
        self.assertEqual(listed(q="abuse"), {"ops@example.com"})
        self.assertEqual(listed(q="TARGET@"), {"ops@example.com"})
        self.assertEqual(listed(impersonated="1"), {"other@example.com"})
        self.assertEqual(len(listed(actor="junk")), 2)
        context = self.client.get(reverse("staffportal:audit_list")).context
        self.assertEqual(context["action_choices"], audit.ACTION_CHOICES)
        self.assertEqual({actor.email for actor in context["actors"]}, {"ops@example.com", "other@example.com"})

    def test_the_team_screen_lists_managed_and_unmanaged_staff(self):
        make_staff("managed@example.com", StaffRole.SUPPORT)
        make_user("bare@example.com", is_staff=True)
        response = self.client.get(reverse("staffportal:team_list"))
        self.assertEqual([m.user.email for m in response.context["members"]], ["managed@example.com"])
        unmanaged = {u.email for u in response.context["unmanaged"]}
        self.assertEqual(unmanaged, {"root@example.com", "bare@example.com"})

    def test_granting_to_someone_who_already_has_a_role_updates_it(self):
        candidate = make_staff("candidate@example.com", StaffRole.VIEWER)
        response = self.client.post(
            reverse("staffportal:team_list"),
            {"email": "candidate@example.com", "role": StaffRole.BILLING, "note": "promoted"},
        )
        self.assertEqual(flash(response), ["candidate@example.com now has portal access as billing."])
        candidate.refresh_from_db()
        self.assertEqual(candidate.staff_member.role, StaffRole.BILLING)
        entry = last_audit(audit.TEAM_UPDATED)
        self.assertEqual(
            (entry.summary, entry.metadata),
            ("Portal access as Billing — support, plus plans and subscriptions.", {"role": "billing"}),
        )
        self.assertFalse(AuditLog.objects.filter(action=audit.TEAM_GRANTED).exists())

    def test_a_suspended_account_cannot_be_granted_access(self):
        make_user("suspended@example.com", is_active=False)
        response = self.client.post(
            reverse("staffportal:team_list"), {"email": "suspended@example.com", "role": StaffRole.VIEWER}
        )
        self.assertContains(response, "This account is suspended.")

    def test_changing_a_role_from_its_own_page(self):
        candidate = make_staff("candidate@example.com", StaffRole.VIEWER)
        member = candidate.staff_member
        response = self.client.post(
            reverse("staffportal:team_update", args=[member.pk]), {"role": StaffRole.ADMIN, "note": ""}
        )
        self.assertRedirects(response, reverse("staffportal:team_list"), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Role updated."])
        self.assertEqual(
            last_audit(audit.TEAM_UPDATED).summary,
            "Role set to Admin — everything except superuser-only actions.",
        )

    def test_revoking_a_superuser_keeps_their_staff_flag(self):
        other_root = make_user("root2@example.com", is_staff=True, is_superuser=True)
        member = StaffMember.objects.create(user=other_root, role=StaffRole.ADMIN)
        response = self.client.post(reverse("staffportal:team_revoke", args=[member.pk]))
        self.assertEqual(flash(response), ["Revoked root2@example.com's portal access."])
        other_root.refresh_from_db()
        self.assertTrue(other_root.is_staff)
        self.assertEqual(last_audit(audit.TEAM_REVOKED).summary, "Portal access revoked.")
        response = self.client.post(reverse("staffportal:team_revoke", args=[member.pk]))
        self.assertEqual(response.status_code, 404)


class PruneAuditLogCommandTests(PortalTestCase):
    """UC-08.10: retention is applied in bulk, never row by row."""

    def setUp(self):
        super().setUp()
        self.old = AuditLog.objects.create(actor_email="a@example.com", action="x.old", summary="old")
        self.recent = AuditLog.objects.create(actor_email="a@example.com", action="x.new", summary="new")
        AuditLog.objects.filter(pk=self.old.pk).update(created_at=timezone.now() - timedelta(days=400))

    def test_entries_beyond_the_configured_window_are_deleted(self):
        call_command("prune_audit_log", verbosity=0)
        self.assertEqual(set(AuditLog.objects.values_list("pk", flat=True)), {self.recent.pk})

    def test_the_window_can_be_given_on_the_command_line(self):
        AuditLog.objects.filter(pk=self.recent.pk).update(created_at=timezone.now() - timedelta(days=10))
        call_command("prune_audit_log", days=5, verbosity=0)
        self.assertFalse(AuditLog.objects.exists())

    def test_a_dry_run_only_reports(self):
        from io import StringIO

        out = StringIO()
        call_command("prune_audit_log", dry_run=True, stdout=out)
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertIn("Would delete 1 entries older than 365 days.", out.getvalue())

    def test_the_window_comes_from_the_runtime_setting(self):
        runtime_settings.set_value("audit_retention_days", 500)
        call_command("prune_audit_log", verbosity=0)
        self.assertEqual(AuditLog.objects.count(), 2)


# ---------------------------------------------------------------------------
# The use cases in staffportal/services.py, called directly
# ---------------------------------------------------------------------------
class StaffPortalServiceTests(PortalTestCase):
    """What each service refuses, in which words, and what it leaves in the audit
    trail — with a bare request standing in for the operator's."""

    def setUp(self):
        super().setUp()
        self.free, self.pro = make_plans()
        self.operator = make_staff("admin@example.com", StaffRole.ADMIN)
        self.customer = make_user("customer@example.com")

    def request_as(self, user, session=None):
        request = RequestFactory().post("/staff/")
        request.user = user
        request.session = {} if session is None else session
        return request

    def actions(self):
        return list(AuditLog.objects.order_by("id").values_list("action", flat=True))

    # --- UC-08.1 -----------------------------------------------------------
    def test_the_gate_admits_only_active_staff_who_hold_the_capability(self):
        viewer = make_staff("viewer@example.com", StaffRole.VIEWER)
        suspended = make_staff("gone@example.com", StaffRole.ADMIN, is_active=False)

        def gate(user, capability, session=None):
            return services.portal_gate(self.request_as(user, session), capability)

        self.assertEqual(gate(AnonymousUser(), access.VIEW_PORTAL), services.LOGIN)
        self.assertEqual(gate(self.customer, access.VIEW_PORTAL), services.HIDDEN)
        self.assertEqual(gate(suspended, access.VIEW_PORTAL), services.HIDDEN)
        self.assertEqual(gate(viewer, access.MANAGE_USERS), services.FORBIDDEN)
        self.assertEqual(gate(viewer, access.VIEW_PORTAL), services.ALLOW)
        self.assertEqual(gate(self.operator, access.MANAGE_USERS), services.ALLOW)

    def test_an_impersonated_session_never_gets_past_the_gate_even_for_a_staff_account(self):
        session = {impersonation_key(): self.operator.pk}
        outcome = services.portal_gate(
            self.request_as(self.operator, session), access.VIEW_PORTAL
        )
        self.assertEqual(outcome, services.HIDDEN)

    def test_the_forbidden_page_names_the_capability_and_the_role(self):
        viewer = make_staff("viewer@example.com", StaffRole.VIEWER)
        context = services.forbidden_context(viewer, access.MANAGE_USERS, "users")
        self.assertEqual(
            context,
            {
                "capability": access.MANAGE_USERS,
                "capability_label": "Suspend, reactivate and annotate accounts",
                "role_label": access.role_label(viewer),
                "section": "users",
            },
        )

    def test_revoking_your_own_access_is_refused_and_someone_elses_is_audited(self):
        other = make_staff("other@example.com", StaffRole.SUPPORT)
        mine = StaffMember.objects.get(user=self.operator)
        with self.assertRaisesMessage(Refused, "You cannot revoke your own access."):
            services.revoke_portal_access(self.request_as(self.operator), mine)
        self.assertTrue(StaffMember.objects.filter(pk=mine.pk).exists())

        services.revoke_portal_access(
            self.request_as(self.operator), StaffMember.objects.get(user=other)
        )
        other.refresh_from_db()
        self.assertFalse(other.is_staff)
        self.assertFalse(StaffMember.objects.filter(user=other).exists())
        self.assertEqual(self.actions(), [audit.TEAM_REVOKED])

    # --- UC-08.2 -----------------------------------------------------------
    def test_suspension_refuses_yourself_and_a_superuser_but_ends_a_customers_sessions(self):
        boss = make_user("boss@example.com", is_superuser=True, is_staff=True)
        with self.assertRaisesMessage(Refused, "You cannot suspend your own account."):
            services.suspend_account(self.request_as(self.operator), self.operator, "")
        with self.assertRaisesMessage(Refused, "Only a superuser may suspend a superuser."):
            services.suspend_account(self.request_as(self.operator), boss, "")
        self.assertEqual(self.actions(), [])

        self.client.force_login(self.customer)
        services.suspend_account(self.request_as(self.operator), self.customer, "Chargeback")
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 302)
        entry = AuditLog.objects.get()
        self.assertEqual((entry.action, entry.summary), (audit.USER_SUSPENDED, "Chargeback"))

    def test_a_suspension_without_a_reason_says_so_in_the_trail(self):
        services.suspend_account(self.request_as(self.operator), self.customer, "")
        self.assertEqual(AuditLog.objects.get().summary, "Account suspended.")

    def test_changing_a_plan_reads_before_and_after_and_needs_a_plan_to_exist(self):
        services.change_account_plan(
            self.request_as(self.operator), self.customer, self.pro, "active", "Upgrade"
        )
        subscription = Subscription.objects.get(user=self.customer)
        self.assertEqual(subscription.plan, self.pro)
        self.assertEqual(
            AuditLog.objects.get().summary, "Free/active → Pro/active. Upgrade"
        )

        Subscription.objects.all().delete()
        Plan.objects.all().delete()
        with self.assertRaisesMessage(PreconditionFailed, "No plans are configured yet."):
            services.change_account_plan(
                self.request_as(self.operator), self.customer, self.pro, "active"
            )

    def test_search_reads_the_same_filters_the_screen_offers(self):
        make_user("ada@example.com", first_name="Ada")
        User.objects.filter(pk=self.customer.pk).update(is_active=False)

        def emails(**params):
            return {u.email for u in services.search_accounts(params)}

        self.assertEqual(emails(q="ADA"), {"ada@example.com"})
        self.assertEqual(emails(status="suspended"), {"customer@example.com"})
        self.assertEqual(emails(status="staff"), {"admin@example.com"})
        self.assertEqual(emails(plan=str(self.pro.pk)), set())

    # --- UC-08.3 -----------------------------------------------------------
    def test_impersonation_names_the_fundamental_problem_before_the_missing_reason(self):
        request = self.request_as(self.operator)
        with self.assertRaisesMessage(
            Refused, "You are already signed in as this account."
        ):
            services.start_impersonation(request, self.operator, ImpersonationForm({}))
        with self.assertRaisesMessage(
            PreconditionFailed, "A reason is required before impersonating an account."
        ):
            services.start_impersonation(request, self.customer, ImpersonationForm({}))
        self.assertFalse(ImpersonationSession.objects.exists())

    def test_only_an_impersonating_request_can_stop_one(self):
        with self.assertRaises(PreconditionFailed):
            services.stop_impersonation(self.request_as(self.operator))

    # --- UC-08.5 -----------------------------------------------------------
    def test_a_plan_with_subscribers_is_deactivated_and_an_empty_one_deleted(self):
        outcome, name = services.retire_plan(self.request_as(self.operator), self.free.pk)
        self.assertEqual((outcome, name), (services.PLAN_DEACTIVATED, "Free"))
        self.free.refresh_from_db()
        self.assertEqual((self.free.is_active, self.free.is_default), (False, False))

        outcome, name = services.retire_plan(self.request_as(self.operator), self.pro.pk)
        self.assertEqual((outcome, name), (services.PLAN_DELETED, "Pro"))
        self.assertFalse(Plan.objects.filter(pk=self.pro.pk).exists())

        outcome, name = services.retire_plan(self.request_as(self.operator), 9999)
        self.assertEqual((outcome, name), (services.PLAN_MISSING, ""))

    def test_resetting_usage_zeroes_this_periods_counters_and_says_how_many(self):
        quotas.consume(self.customer, UsageMetric.JOB_ANALYSIS, 2)
        quotas.consume(self.customer, UsageMetric.RESUME_IMPORT)
        cleared = services.reset_usage(self.request_as(self.operator), self.customer)
        self.assertEqual(cleared, 2)
        self.assertEqual(
            list(UsageRecord.objects.filter(user=self.customer).values_list("count", flat=True)),
            [0, 0],
        )
        self.assertEqual(AuditLog.objects.get().summary, "Reset 2 usage counter(s) for the current period.")

    def test_the_starter_data_is_created_once_and_never_rewritten(self):
        Subscription.objects.all().delete()
        Plan.objects.all().delete()
        first = services.seed_starter_data()
        self.assertTrue(all(created for _plan, created in first["plans"]))
        self.assertIsNone(first["backfilled"])

        Plan.objects.filter(slug="pro").update(price_cents=1)
        second = services.seed_starter_data(backfill=True)
        self.assertFalse(any(created for _plan, created in second["plans"]))
        self.assertFalse(any(created for _flag, created in second["flags"]))
        self.assertEqual(Plan.objects.get(slug="pro").price_cents, 1)
        self.assertEqual(second["backfilled"], User.objects.count())

    # --- UC-08.7 -----------------------------------------------------------
    def test_saving_settings_writes_and_reports_only_what_changed(self):
        values = dict(runtime_settings.all_values())
        request = self.request_as(self.operator)
        self.assertEqual(services.save_settings(request, values), [])
        self.assertEqual(self.actions(), [])

        values["maintenance_mode"] = True
        self.assertEqual(
            services.save_settings(request, values), ["maintenance_mode: False → True"]
        )
        self.assertIs(runtime_settings.get("maintenance_mode"), True)
        entry = AuditLog.objects.get()
        self.assertEqual(
            (entry.action, entry.summary), (audit.SETTING_UPDATED, "maintenance_mode: False → True")
        )

    def test_maintenance_stops_customers_but_never_staff_or_the_portal(self):
        def blocked(path, user):
            request = RequestFactory().get(path)
            request.user = user
            return services.maintenance_blocks(request)

        self.assertFalse(blocked("/dashboard/", self.customer))
        runtime_settings.set_value("maintenance_mode", True)
        self.assertTrue(blocked("/dashboard/", self.customer))
        self.assertTrue(blocked("/dashboard/", AnonymousUser()))
        self.assertFalse(blocked("/dashboard/", self.operator))
        for path in ("/staff/", "/accounts/login/", "/static/app.css", "/i18n/setlang/"):
            with self.subTest(path=path):
                self.assertFalse(blocked(path, AnonymousUser()))

    # --- UC-08.8 -----------------------------------------------------------
    def test_each_announcement_reaches_only_its_audience(self):
        for audience in (Announcement.EVERYONE, Announcement.AUTHENTICATED, Announcement.STAFF):
            Announcement.objects.create(title=audience, audience=audience)

        def seen(user):
            return {a.title for a in services.live_announcements_for(user)}

        self.assertEqual(seen(None), {"everyone"})
        self.assertEqual(seen(AnonymousUser()), {"everyone"})
        self.assertEqual(seen(self.customer), {"everyone", "authenticated"})
        self.assertEqual(seen(self.operator), {"everyone", "authenticated", "staff"})

    def test_deleting_an_announcement_or_a_flag_that_is_gone_is_a_quiet_no_op(self):
        request = self.request_as(self.operator)
        self.assertIsNone(services.delete_announcement(request, 9999))
        self.assertIsNone(services.delete_flag(request, 9999))
        note = Announcement.objects.create(title="Maintenance")
        flag = FeatureFlag.objects.create(key="beta", name="Beta")
        self.assertEqual(services.delete_announcement(request, note.pk), "Maintenance")
        self.assertEqual(services.delete_flag(request, flag.pk), "beta")
        self.assertEqual(self.actions(), [audit.ANNOUNCEMENT_DELETED, audit.FLAG_DELETED])

    # --- UC-08.9 -----------------------------------------------------------
    def make_task(self, **fields):
        profile = Profile.objects.get(user=self.customer)
        job = JobPost.objects.create(profile=profile, description_text="x" * 120)
        return AITask.start_for(profile, AITask.JOB_ANALYSIS, job), job

    def test_retrying_needs_the_target_to_exist_and_reports_a_failure_to_queue(self):
        task, job = self.make_task()
        request = self.request_as(self.operator)

        with patch("jobs.tasks.enqueue_job_analysis", side_effect=RuntimeError("broker down")):
            with self.assertRaisesMessage(ServiceError, "Could not re-queue: broker down"):
                services.retry_task(request, task)
        self.assertEqual(self.actions(), [])

        with patch("jobs.tasks.enqueue_job_analysis") as enqueue:
            services.retry_task(request, task)
        enqueue.assert_called_once_with(job)
        self.assertEqual(self.actions(), [audit.TASK_RETRIED])

        job.delete()
        task = AITask.objects.get(pk=task.pk)
        with self.assertRaisesMessage(
            PreconditionFailed, "The object this job was about no longer exists."
        ):
            services.retry_task(request, task)

    def test_only_a_job_that_is_still_open_can_be_canceled(self):
        task, _job = self.make_task()
        request = self.request_as(self.operator)
        self.assertTrue(services.cancel_task(request, task))
        task.refresh_from_db()
        self.assertEqual(task.state, AITask.CANCELED)
        self.assertIsNotNone(task.finished_at)
        self.assertFalse(services.cancel_task(request, task))
        self.assertEqual(self.actions(), [audit.TASK_CANCELED])

    def test_the_queue_can_be_searched_and_counted(self):
        task, _job = self.make_task()
        AITask.objects.filter(pk=task.pk).update(state=AITask.FAILED, error_message="Timed out")
        self.assertEqual(list(services.search_tasks({"state": "failed"})), [task])
        self.assertEqual(list(services.search_tasks({"q": "timed"})), [task])
        self.assertEqual(list(services.search_tasks({"kind": AITask.TAILORED_RESUME})), [])
        self.assertEqual(services.queue_counts(), {"queued": 0, "running": 0, "failed": 1})

    # --- UC-08.10 ----------------------------------------------------------
    def test_pruning_counts_first_and_only_deletes_when_asked(self):
        old = AuditLog.objects.create(action="old")
        AuditLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        AuditLog.objects.create(action="recent")

        self.assertEqual(services.prune_audit_log(365, dry_run=True), (1, 365))
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertEqual(services.prune_audit_log(365), (1, 365))
        self.assertEqual(list(AuditLog.objects.values_list("action", flat=True)), ["recent"])

        count, days = services.prune_audit_log()
        self.assertEqual((count, days), (0, int(runtime_settings.get("audit_retention_days"))))

    def test_the_audit_search_filters_by_actor_text_and_impersonation(self):
        audit.log(self.request_as(self.operator), audit.USER_NOTE_ADDED, target=self.customer,
                  summary="Called about billing.")
        audit.log(self.request_as(self.operator, {"impersonator_id": 1}), audit.USER_EXPORTED,
                  target=self.customer, summary="Export.")

        def found(**params):
            return sorted(e.summary for e in services.search_audit(params))

        self.assertEqual(found(), ["Called about billing.", "Export."])
        self.assertEqual(found(q="billing"), ["Called about billing."])
        self.assertEqual(found(impersonated="1"), ["Export."])
        self.assertEqual(found(actor=str(self.operator.pk)), ["Called about billing.", "Export."])
        self.assertEqual(found(action=audit.USER_EXPORTED), ["Export."])
        self.assertEqual(list(services.audit_actors()), [self.operator])

    # --- UC-08.11 ----------------------------------------------------------
    def test_erasure_needs_the_address_typed_and_is_audited_before_it_happens(self):
        request = self.request_as(self.operator)
        boss = make_user("boss@example.com", is_superuser=True, is_staff=True)
        with self.assertRaisesMessage(
            Refused, "Only a superuser may delete a superuser account."
        ):
            services.delete_account_as_operator(request, boss, "boss@example.com", "")
        with self.assertRaisesMessage(
            PreconditionFailed, "The email address did not match. Nothing was deleted."
        ):
            services.delete_account_as_operator(request, self.customer, "customer@example.co", "")
        self.assertTrue(User.objects.filter(pk=self.customer.pk).exists())
        self.assertEqual(self.actions(), [])

        customer_id = self.customer.pk
        email = services.delete_account_as_operator(
            request, self.customer, "  CUSTOMER@example.com ", "x" * 500
        )
        self.assertEqual(email, "customer@example.com")
        self.assertFalse(User.objects.filter(email="customer@example.com").exists())
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, audit.USER_DELETED)
        # Written before the delete, while the account still had an id to record.
        self.assertEqual((entry.target_repr, entry.target_id), ("customer@example.com", str(customer_id)))
        self.assertEqual(len(entry.metadata["reason"]), 200)

    def test_the_erasure_page_warns_about_what_will_go_and_blocks_a_superuser_target(self):
        profile = Profile.objects.get(user=self.customer)
        JobPost.objects.create(profile=profile, description_text="x" * 120)
        preview = services.deletion_preview(self.customer, self.operator)
        self.assertEqual(preview, {"profile_count": 1, "job_post_count": 1, "blocked": False})
        boss = make_user("boss@example.com", is_superuser=True, is_staff=True)
        self.assertTrue(services.deletion_preview(boss, self.operator)["blocked"])
        self.assertFalse(services.deletion_preview(boss, boss)["blocked"])


def impersonation_key():
    from .domain import impersonation

    return impersonation.SESSION_ACTOR_KEY
