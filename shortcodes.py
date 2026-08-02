import logging
import re

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

# [name attr1="v1" attr2="v2"] — self-closing tokens only, double-quoted attrs.
_SHORTCODE_RE = re.compile(r'\[(\w+)((?:\s+\w+="[^"]*")*)\s*\]')
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')

# Populated by register() calls at the bottom of this module (Task 2).
SHORTCODES = {}


def _parse_attrs(raw):
    return {key: val for key, val in _ATTR_RE.findall(raw or "")}


def render_shortcodes(content, request, context, registry=None):
    reg = SHORTCODES if registry is None else registry

    def _replace(match):
        name = match.group(1)
        handler = reg.get(name)
        if handler is None:
            logger.warning("Unknown shortcode: %s", name)
            return f"<!-- unknown shortcode: {name} -->"
        attrs = _parse_attrs(match.group(2))
        try:
            return handler(request, context, **attrs)
        except Exception:
            logger.exception("Shortcode %s failed to render", name)
            return f"<!-- shortcode error: {name} -->"

    return mark_safe(_SHORTCODE_RE.sub(_replace, content or ""))


START_APP = {
    "student": {"flag": "registration_is_open", "url": "student:start_app",
                "label": "Start New Application", "closed_key": "window_close_notice"},
    "instructor": {"flag": "accepting_applications", "url": "applicant_app:start_app",
                   "label": "Start New Application", "closed_key": "closed_message"},
    "counselor": {"flag": None, "url": "hs_admin_access_request",
                  "label": "Submit Access Request", "closed_key": None},
}


def _render(request, template, extra):
    return render_to_string(template, extra, request=request)


def sc_breadcrumb(request, context, label=None, **attrs):
    if label is None:
        label = context.get("label", "")
    return _render(request, "cis/shortcodes/breadcrumb.html", {"label": label})


def sc_messages(request, context, **attrs):
    return _render(request, "cis/shortcodes/messages.html", {})


def sc_login_form(request, context, button_label="Login", forgot_label="Forgot Password", **attrs):
    return _render(request, "cis/shortcodes/login_form.html", {
        "form": context.get("form"),
        "button_label": button_label,
        "forgot_label": forgot_label,
    })


def sc_sso_login(request, context, label="Login Now", **attrs):
    return _render(request, "cis/shortcodes/sso_login.html", {
        "portal": context.get("portal"),
        "label": label,
    })


def sc_start_app(request, context, label=None, **attrs):
    cfg = START_APP.get(context.get("role"))
    if cfg is None:
        return ""
    flag = cfg["flag"]
    is_open = context.get(flag, True) if flag else True
    if not is_open:
        return mark_safe(context.get(cfg["closed_key"]) or "")
    return _render(request, "cis/shortcodes/start_app.html", {
        "url_name": cfg["url"],
        "label": label or cfg["label"],
    })


def sc_forgot_password(request, context, label="Forgot Password", **attrs):
    return _render(request, "cis/shortcodes/forgot_password.html", {"label": label})


SHORTCODES.update({
    "breadcrumb": sc_breadcrumb,
    "messages": sc_messages,
    "login_form": sc_login_form,
    "sso_login": sc_sso_login,
    "start_app": sc_start_app,
    "forgot_password": sc_forgot_password,
})
