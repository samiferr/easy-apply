"""Runtime configuration an operator can change without a deploy.

The keys are a registry, not free text. A setting nothing reads is a lie in the
UI, and a typo in a key name is a silent behaviour change — so `get()` only
answers for keys declared here, and the settings screen renders itself from the
same list.

Values are cached for a short window because `maintenance_mode` is consulted on
every single request. Writing through `set_value()` invalidates immediately, so
the process that made the change sees it at once; other processes pick it up
within `CACHE_SECONDS`. That bound is the whole design: a kill switch that takes
half a minute to spread is fine, one that needs a deploy is not.
"""

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache

from ..models import SystemSetting

CACHE_KEY = "staffportal:system-settings"
CACHE_SECONDS = 30

BOOL = "bool"
INT = "int"
STR = "str"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    help_text: str
    kind: str
    default: Any
    group: str


REGISTRY: tuple[SettingSpec, ...] = (
    SettingSpec(
        "signups_enabled",
        "Accept new sign-ups",
        "Turn off to close registration — existing customers are unaffected.",
        BOOL,
        True,
        "Access",
    ),
    SettingSpec(
        "maintenance_mode",
        "Maintenance mode",
        "Everyone but staff gets a maintenance page. Staff keep full access so "
        "the fix can be verified before it is lifted.",
        BOOL,
        False,
        "Access",
    ),
    SettingSpec(
        "ai_features_enabled",
        "AI features enabled",
        "Kill switch for every call to the AI provider: job analysis, matching, "
        "resume import and resume generation. Use it when the provider is down "
        "or the bill is running away.",
        BOOL,
        True,
        "AI",
    ),
    SettingSpec(
        "enforce_quotas",
        "Enforce plan quotas",
        "Off by default so plans can be modelled and reviewed before they start "
        "refusing work. Turn it on once the allowances read correctly.",
        BOOL,
        False,
        "Billing",
    ),
    SettingSpec(
        "impersonation_minutes",
        "Impersonation session length (minutes)",
        "How long a 'sign in as' session stays open before it ends itself.",
        INT,
        30,
        "Security",
    ),
    SettingSpec(
        "audit_retention_days",
        "Audit log retention (days)",
        "Used by `manage.py prune_audit_log`. Keep it at or above whatever your "
        "compliance obligations require.",
        INT,
        365,
        "Security",
    ),
    SettingSpec(
        "support_email",
        "Support email",
        "Shown to customers on error and quota screens. Leave empty to hide it.",
        STR,
        "",
        "Support",
    ),
)

SPECS = {spec.key: spec for spec in REGISTRY}
GROUPS = list(dict.fromkeys(spec.group for spec in REGISTRY))


def _coerce(spec: SettingSpec, raw: str):
    if spec.kind == BOOL:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    if spec.kind == INT:
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return spec.default
    return str(raw)


def serialize(spec: SettingSpec, value) -> str:
    if spec.kind == BOOL:
        return "1" if value else "0"
    return str(value)


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def get(key: str):
    spec = SPECS.get(key)
    if spec is None:
        raise KeyError(f"Unknown system setting: {key}")
    return all_values()[key]


def set_value(key: str, value, *, user=None) -> None:
    spec = SPECS.get(key)
    if spec is None:
        raise KeyError(f"Unknown system setting: {key}")
    SystemSetting.objects.update_or_create(
        key=key,
        defaults={"value": serialize(spec, value), "updated_by": user},
    )
    invalidate()


def all_values() -> dict:
    """Every declared key with its effective value, in one query (then cached)."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    values = _load()
    cache.set(CACHE_KEY, values, CACHE_SECONDS)
    return values


def _load() -> dict:
    stored = {row.key: row for row in SystemSetting.objects.all()}
    values = {}
    for spec in REGISTRY:
        row = stored.get(spec.key)
        values[spec.key] = (
            spec.default if row is None or row.value == "" else _coerce(spec, row.value)
        )
    return values


def rows_for_display() -> list[dict]:
    """The settings screen's data: spec, current value, who touched it last.

    Reads straight through the cache — the screen you change settings on should
    never show you a stale copy of them.
    """
    stored = {row.key: row for row in SystemSetting.objects.select_related("updated_by")}
    values = _load()
    return [
        {
            "spec": spec,
            "value": values[spec.key],
            "is_default": spec.key not in stored,
            "row": stored.get(spec.key),
        }
        for spec in REGISTRY
    ]
