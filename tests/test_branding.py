"""Per-campus branding (package-cis #61)."""
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.sites.models import Site
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus


def _campus(code=None, domain=None):
    code = code or f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}'
    site = Site.objects.create(domain=domain, name=domain) if domain else None
    return Campus.objects.create(name=f'C-{uuid.uuid4().hex[:6]}', code=code, site=site)


def _tenant(brands):
    """Patch the tenant seam to serve ``brands`` keyed by campus code."""
    def campus_brand(campus):
        return brands.get(getattr(campus, 'code', None))
    return mock.patch('cis.branding.get_tenant_override',
                      side_effect=lambda module, attr: campus_brand
                      if (module, attr) == ('branding', 'campus_brand') else None)


class BrandResolutionTests(TestCase):
    def test_no_campus_gives_todays_defaults(self):
        from cis.branding import current_brand
        brand = current_brand()
        self.assertEqual(brand.site_name, settings.MY_CE['site_name'])
        self.assertEqual(brand.college_name, settings.MY_CE['college_name'])
        self.assertEqual(brand.logo, 'images/logo.png')
        self.assertEqual(brand.background, 'images/bg.jpg')
        self.assertIsNone(brand.favicon)
        self.assertEqual(brand.colors, {})
        self.assertEqual(brand.css, '')

    def test_no_tenant_module_gives_defaults(self):
        from cis.branding import current_brand
        campus = _campus()
        with mock.patch('cis.branding.get_tenant_override', return_value=None), \
                campus_context(campus):
            self.assertEqual(current_brand().logo, 'images/logo.png')

    def test_fields_fall_back_one_at_a_time(self):
        from cis.branding import current_brand
        campus = _campus()
        with _tenant({campus.code: {'logo': 'brand/x/logo.png', 'site_name': 'X Site'}}), \
                campus_context(campus):
            brand = current_brand()
        self.assertEqual(brand.logo, 'brand/x/logo.png')
        self.assertEqual(brand.site_name, 'X Site')
        self.assertEqual(brand.cep_name, settings.MY_CE['cep_name'])
        self.assertEqual(brand.background, 'images/bg.jpg')

    def test_tenant_returning_none_gives_defaults(self):
        from cis.branding import current_brand
        campus = _campus()
        with _tenant({}), campus_context(campus):
            self.assertEqual(current_brand().site_name, settings.MY_CE['site_name'])

    def test_tenant_hook_that_raises_falls_back_to_defaults(self):
        from cis.branding import current_brand
        campus = _campus()
        def boom(campus):
            raise RuntimeError('tenant bug')
        with mock.patch('cis.branding.get_tenant_override', return_value=boom), \
                campus_context(campus), self.assertLogs('cis.branding', 'ERROR'):
            self.assertEqual(current_brand().logo, 'images/logo.png')

    def test_css_emits_only_safe_colors(self):
        from cis.branding import current_brand
        campus = _campus()
        colors = {'color-primary': '#29348f', 'Bad Name': '#000',
                  'sidebar-bg': 'red;}</style><script>alert(1)</script>'}
        with _tenant({campus.code: {'colors': colors}}), campus_context(campus):
            brand = current_brand()
        self.assertEqual(brand.css, ':root{--color-primary:#29348f;}')

    def test_names_overlay(self):
        from cis.branding import current_brand
        campus = _campus()
        with _tenant({campus.code: {'cep_name': 'LIT DC'}}), campus_context(campus):
            names = current_brand().names()
        self.assertEqual(names['cep_name'], 'LIT DC')
        self.assertEqual(names['site_name'], settings.MY_CE['site_name'])


class AbsoluteLogoUrlTests(TestCase):
    def test_campus_with_site_gets_its_own_domain(self):
        from cis.branding import current_brand
        campus = _campus(domain='lit.example.edu')
        with _tenant({campus.code: {'logo': 'images/logo.png'}}), campus_context(campus):
            url = current_brand().absolute_logo_url
        self.assertTrue(url.startswith('https://lit.example.edu/'), url)
        self.assertTrue(url.endswith('images/logo.png'), url)

    def test_no_campus_is_empty(self):
        from cis.branding import current_brand
        self.assertEqual(current_brand().absolute_logo_url, '')

    @override_settings(MULTI_CAMPUS=True)
    def test_campus_without_site_is_empty_not_an_error(self):
        from cis.branding import current_brand
        campus = _campus()
        with _tenant({}), campus_context(campus):
            self.assertEqual(current_brand().absolute_logo_url, '')


class BrandProblemsTests(TestCase):
    def test_unknown_key_and_unsafe_colors_are_reported(self):
        from cis.branding import brand_problems
        problems = brand_problems({'bakground': 'x', 'colors': {'ok-name': '#fff', 'Bad': '#000',
                                                              'x': 'a;b'}})
        codes = sorted(code for code, _ in problems)
        self.assertEqual(codes, ['E002', 'E003', 'E003'])

    def test_valid_entry_has_no_problems(self):
        from cis.branding import brand_problems
        self.assertEqual(brand_problems({'logo': 'images/logo.png',
                                         'colors': {'color-primary': '#29348f'}}), [])
