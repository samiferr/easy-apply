"""Tests for the staff portal.

The emphasis is on the parts that would be expensive to get wrong: who can
reach what, that impersonation cannot be used to launder a staff action, that
the audit trail cannot be rewritten, and that quota enforcement is genuinely
inert until an operator turns it on.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile
from core.models import AITask
from jobs.models import JobPost

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
from .services import access, audit, exports, flags, health, metrics, quotas
from .services import runtime_settings, subscriptions

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
