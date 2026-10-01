"""Per-campus branding tags (package-cis #61). Tags, not a context variable, so
templates rendered without a request (no context processors) still resolve."""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from cis.branding import current_brand

register = template.Library()


@register.simple_tag
def brand():
    """{% brand as b %} -- the current campus's Brand (emails use b.absolute_logo_url)."""
    return current_brand()


@register.simple_tag
def brand_logo_url():
    return current_brand().logo_url


@register.simple_tag
def brand_background_url():
    return current_brand().background_url


@register.simple_tag
def brand_css():
    """The campus's colour overrides and favicon; nothing when it has neither."""
    b = current_brand()
    out = ''
    if b.css:
        # Brand.css only contains entries that passed safe_colors().
        out += f'<style>{b.css}</style>'
    if b.favicon:
        out += format_html('<link rel="icon" href="{}">', b.favicon_url)
    return mark_safe(out)
