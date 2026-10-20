"""Template helpers for the Lumen design system (design/lumen/README.md)."""

from django import template
from django.utils.html import format_html, format_html_join, mark_safe

from core.icons import ICONS

register = template.Library()

#: Lumen's icon sizes, named the way the Icon component names them.
SIZES = {"xs": 14, "s": 16, "m": 20, "l": 22, "xl": 26}


@register.simple_tag
def icon(name, size="m", label="", **attrs):
    """Render a Lucide outline icon as inline SVG.

    ``{% icon "add" %}`` draws the 20px default; ``size`` takes a Lumen size
    name or a pixel count. Without ``label`` the icon is decorative and hidden
    from assistive technology — the text next to it carries the meaning. With a
    ``label`` it becomes an image with that accessible name. Extra keyword
    arguments are copied onto the ``<svg>``: underscores become hyphens
    (``x_show`` -> ``x-show``) and a ``bind_`` prefix becomes Alpine's ``:``
    (``bind_class`` -> ``:class``).
    """
    shapes = ICONS.get(name)
    if shapes is None:
        raise template.TemplateSyntaxError(f"Unknown icon {name!r}")
    px = SIZES.get(size, size)
    body = mark_safe(
        "".join(
            str(format_html("<{} {}/>", tag, format_html_join(" ", '{}="{}"', props.items())))
            for tag, props in shapes
        )
    )
    a11y = (
        format_html('role="img" aria-label="{}"', label)
        if label
        else mark_safe('aria-hidden="true" focusable="false"')
    )
    names = {key: (":" + key[5:] if key.startswith("bind_") else key).replace("_", "-") for key in attrs}
    extra = format_html_join(" ", '{}="{}"', ((names[key], value) for key, value in attrs.items()))
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" {1} {2}>{3}</svg>',
        px,
        a11y,
        extra,
        body,
    )


@register.inclusion_tag("partials/_nav_item.html", takes_context=True)
def nav_item(context, href, label, icon_name, views="", apps="", kind=""):
    """One side-navigation row, active when the current request matches.

    ``views`` and ``apps`` are comma-separated view names / app names; ``kind``
    matches the ``kind`` URL kwarg (the two skills pages share one view).
    """
    match = getattr(context.get("request"), "resolver_match", None)
    active = bool(match) and (
        (views and match.view_name in views.split(","))
        or (apps and match.app_name in apps.split(","))
        or (kind and match.kwargs.get("kind") == kind)
    )
    return {"href": href, "label": label, "icon_name": icon_name, "active": active}
