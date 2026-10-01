"""Per-campus branding (package-cis #61).

A campus's logo, names, colours, login background and favicon come from the
tenant's optional ``myce_tenant_configs.services.branding.campus_brand(campus)``,
keyed however the tenant likes (by convention ``Campus.code``), and merged one
field at a time over today's defaults. No campus, no tenant module, or no entry
gives exactly today's branding, so single-campus tenants are unchanged.
"""
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.templatetags.static import static

from cis.services.tenant_services import get_tenant_override

logger = logging.getLogger(__name__)

NAME_KEYS = ('site_name', 'cep_name', 'cep_full_name', 'college_name')
BRAND_KEYS = frozenset(NAME_KEYS + ('logo', 'background', 'favicon', 'colors'))

_COLOR_NAME = re.compile(r'^[a-z0-9-]+$')
_COLOR_UNSAFE = re.compile(r'[;{}<>"\'\\]')


def _color_ok(name, value):
    return (isinstance(name, str) and bool(_COLOR_NAME.match(name))
            and isinstance(value, str) and not _COLOR_UNSAFE.search(value))


def safe_colors(colors):
    """The colour entries that are safe to put in a <style> block."""
    return {name: value for name, value in (colors or {}).items() if _color_ok(name, value)}


def brand_problems(entry):
    """Validation problems in one tenant brand entry, as (check code, message)."""
    problems = []
    for key in sorted(set(entry) - BRAND_KEYS):
        problems.append(('E002', f'unknown key {key!r}'))
    for name, value in (entry.get('colors') or {}).items():
        if not _color_ok(name, value):
            problems.append(('E003', f'unsafe colour {name!r}: {value!r}'))
    return problems


@dataclass(frozen=True)
class Brand:
    campus: object = None
    site_name: str = ''
    cep_name: str = ''
    cep_full_name: str = ''
    college_name: str = ''
    logo: str = 'images/logo.png'
    background: str = 'images/bg.jpg'
    favicon: str = None
    colors: dict = field(default_factory=dict)

    @property
    def logo_url(self):
        return static(self.logo)

    @property
    def background_url(self):
        return static(self.background)

    @property
    def favicon_url(self):
        return static(self.favicon) if self.favicon else ''

    @property
    def absolute_logo_url(self):
        """The logo on the campus's own host, for emails; '' when there is no
        campus, it has no Site, or the deployment is single-campus -- the
        email template then keeps its own URL, so single-campus email is
        unchanged even when a Site was set up ahead of MULTI_CAMPUS."""
        from cis.campus_context import campus_url, is_multi_campus
        if (not is_multi_campus() or self.campus is None
                or not getattr(self.campus, 'site_id', None)):
            return ''
        try:
            return campus_url(self.campus, self.logo_url)
        except Exception:
            logger.exception('No absolute logo URL for campus %s', self.campus)
            return ''

    @property
    def css(self):
        colors = safe_colors(self.colors)
        if not colors:
            return ''
        return ':root{' + ''.join(f'--{n}:{v};' for n, v in colors.items()) + '}'

    def names(self):
        return {key: getattr(self, key) for key in NAME_KEYS}


def _tenant_entry(campus):
    hook = get_tenant_override('branding', 'campus_brand')
    if hook is None:
        return {}
    try:
        return hook(campus) or {}
    except Exception:
        # Branding must never take a page down; fall back to the defaults.
        logger.exception('branding.campus_brand failed for campus %s', campus)
        return {}


def brand_for(campus):
    """The Brand for ``campus`` (may be None)."""
    entry = _tenant_entry(campus) if campus is not None else {}
    values = {key: entry.get(key) or settings.MY_CE.get(key, '') for key in NAME_KEYS}
    for key in ('logo', 'background', 'favicon'):
        if entry.get(key):
            values[key] = entry[key]
    if entry.get('colors'):
        values['colors'] = dict(entry['colors'])
    return Brand(campus=campus, **values)


def current_brand():
    """The Brand for the campus being served (or set by campus_context())."""
    from cis.campus_context import current_campus_or_none
    return brand_for(current_campus_or_none())


def branded_my_ce():
    """A copy of settings.MY_CE with the current campus's names -- what pages
    get as MYCE_SETTINGS and the login views pass as ``portal``."""
    return {**settings.MY_CE, **current_brand().names()}
