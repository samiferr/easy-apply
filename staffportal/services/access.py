"""Who may do what inside the portal.

`is_staff` opens the door; the role behind it decides what is reachable once
inside. Least privilege is the point: reading the dashboard and deleting a
customer account are not the same grant, and most of the people who need the
former never need the latter.

Superusers are the one bypass — they hold every capability, including the ones
no role carries.
"""

from django.core.exceptions import PermissionDenied

from ..models import StaffMember, StaffRole

# --- Capabilities ----------------------------------------------------------
VIEW_PORTAL = "portal.view"
VIEW_USERS = "users.view"
MANAGE_USERS = "users.manage"
IMPERSONATE = "users.impersonate"
EXPORT_USER_DATA = "users.export"
DELETE_USERS = "users.delete"
VIEW_BILLING = "billing.view"
MANAGE_BILLING = "billing.manage"
MANAGE_FLAGS = "flags.manage"
MANAGE_ANNOUNCEMENTS = "announcements.manage"
VIEW_OPERATIONS = "operations.view"
MANAGE_OPERATIONS = "operations.manage"
VIEW_AUDIT = "audit.view"
MANAGE_TEAM = "team.manage"

CAPABILITY_LABELS = {
    VIEW_PORTAL: "Open the portal",
    VIEW_USERS: "Read customer accounts",
    MANAGE_USERS: "Suspend, reactivate and annotate accounts",
    IMPERSONATE: "Sign in as a customer",
    EXPORT_USER_DATA: "Export an account's personal data",
    DELETE_USERS: "Delete an account and its data",
    VIEW_BILLING: "Read plans and subscriptions",
    MANAGE_BILLING: "Change plans and subscriptions",
    MANAGE_FLAGS: "Change feature flags",
    MANAGE_ANNOUNCEMENTS: "Publish announcements",
    VIEW_OPERATIONS: "Read the queue and health checks",
    MANAGE_OPERATIONS: "Retry work and change runtime settings",
    VIEW_AUDIT: "Read the audit log",
    MANAGE_TEAM: "Grant and revoke portal access",
}

_VIEWER = {VIEW_PORTAL, VIEW_USERS, VIEW_BILLING, VIEW_OPERATIONS, VIEW_AUDIT}
_SUPPORT = _VIEWER | {MANAGE_USERS, IMPERSONATE, EXPORT_USER_DATA}
_BILLING = _SUPPORT | {MANAGE_BILLING}
_ADMIN = _BILLING | {
    MANAGE_FLAGS,
    MANAGE_ANNOUNCEMENTS,
    MANAGE_OPERATIONS,
    DELETE_USERS,
}

ROLE_CAPABILITIES = {
    StaffRole.VIEWER: frozenset(_VIEWER),
    StaffRole.SUPPORT: frozenset(_SUPPORT),
    StaffRole.BILLING: frozenset(_BILLING),
    StaffRole.ADMIN: frozenset(_ADMIN),
}

#: Only a superuser may hand out portal access — otherwise the portal is a
#: privilege-escalation ladder anyone who reaches `admin` can climb.
SUPERUSER_ONLY = frozenset({MANAGE_TEAM})

ALL_CAPABILITIES = frozenset(_ADMIN) | SUPERUSER_ONLY


def role_for(user) -> str | None:
    """The role string for a staff account, or None when it has no portal access.

    A staff account with no `StaffMember` row reads as `viewer`: turning on
    `is_staff` should never be the same as handing over the delete button.
    """
    if user is None or not user.is_authenticated or not user.is_staff:
        return None
    if user.is_superuser:
        return "superuser"
    member = StaffMember.objects.filter(user=user).first()
    return member.role if member else StaffRole.VIEWER


def role_label(user) -> str:
    role = role_for(user)
    if role is None:
        return "No access"
    if role == "superuser":
        return "Superuser — full access"
    return StaffRole(role).label


def capabilities_for(user) -> frozenset:
    role = role_for(user)
    if role is None:
        return frozenset()
    if role == "superuser":
        return ALL_CAPABILITIES
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(user, capability: str) -> bool:
    return capability in capabilities_for(user)


def require(user, capability: str) -> None:
    """Raise `PermissionDenied` unless `user` holds `capability`."""
    if not has_capability(user, capability):
        raise PermissionDenied(f"Missing capability: {capability}")


def can_impersonate(actor, target) -> tuple[bool, str]:
    """Whether `actor` may sign in as `target`, and why not when they may not.

    The rules that matter: never yourself (pointless, and it strands the
    session), never a deactivated account, and never another staff account
    unless you are a superuser — otherwise impersonation is a way to borrow
    someone else's permissions.
    """
    if not has_capability(actor, IMPERSONATE):
        return False, "Your role does not allow impersonation."
    if target.pk == actor.pk:
        return False, "You are already signed in as this account."
    if not target.is_active:
        return False, "This account is suspended. Reactivate it first."
    if (target.is_staff or target.is_superuser) and not actor.is_superuser:
        return False, "Only a superuser may impersonate another staff account."
    return True, ""
