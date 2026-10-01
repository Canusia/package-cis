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


class BrandingCheckTests(TestCase):
    def _run(self, brands):
        from cis.checks import branding_check
        module = mock.Mock(BRANDS=brands)
        with mock.patch('cis.checks.get_tenant_service', return_value=module):
            return {m.id for m in branding_check(None)}

    def test_valid_map_passes(self):
        campus = _campus()
        self.assertEqual(self._run({campus.code: {
            'logo': 'images/logo.png', 'colors': {'color-primary': '#123456'}}}), set())

    def test_missing_asset_unknown_key_unsafe_color(self):
        campus = _campus()
        ids = self._run({campus.code: {'logo': 'brand/nope/missing.png', 'bakground': 'x',
                                       'colors': {'x': 'a;b'}}})
        self.assertEqual(ids, {'cis.E001', 'cis.E002', 'cis.E003'})

    def test_unknown_campus_code_warns(self):
        self.assertEqual(self._run({'NO_SUCH_CODE': {'logo': 'images/logo.png'}}), {'cis.W004'})

    def test_no_branding_module_passes(self):
        from cis.checks import branding_check
        with mock.patch('cis.checks.get_tenant_service', side_effect=ModuleNotFoundError):
            self.assertEqual(branding_check(None), [])


from django.template import Context, Template


class BrandTagTests(TestCase):
    def _render(self, source, campus=None, brands=None):
        with _tenant(brands or {}), campus_context(campus):
            return Template('{% load brand %}' + source).render(Context({}))

    def test_brand_css_is_empty_by_default(self):
        self.assertEqual(self._render('{% brand_css %}'), '')

    def test_brand_css_emits_root_block_and_favicon(self):
        campus = _campus()
        out = self._render('{% brand_css %}', campus, {campus.code: {
            'colors': {'color-primary': '#29348f'}, 'favicon': 'images/logo.png'}})
        self.assertIn('<style>:root{--color-primary:#29348f;}</style>', out)
        self.assertIn('<link rel="icon" href="/static/images/logo.png">', out)

    def test_brand_css_drops_injection(self):
        campus = _campus()
        out = self._render('{% brand_css %}', campus, {campus.code: {
            'colors': {'sidebar-bg': 'red;}</style><script>alert(1)</script>'}}})
        self.assertNotIn('<script>', out)

    def test_logo_url_matches_static_by_default_without_request(self):
        from django.templatetags.static import static
        self.assertEqual(self._render('{% brand_logo_url %}'), static('images/logo.png'))
        self.assertEqual(self._render('{% brand_background_url %}'), static('images/bg.jpg'))

    def test_logo_url_uses_campus_logo(self):
        campus = _campus()
        out = self._render('{% brand_logo_url %}', campus,
                           {campus.code: {'logo': 'brand/x/logo.png'}})
        self.assertEqual(out, '/static/brand/x/logo.png')


class ContextProcessorTests(TestCase):
    def test_names_swapped_and_settings_untouched(self):
        from django.test import RequestFactory
        from cis.context_processors import export_vars
        campus = _campus()
        before = dict(settings.MY_CE)
        with _tenant({campus.code: {'site_name': 'LIT Portal'}}), campus_context(campus):
            data = export_vars(RequestFactory().get('/'))
        self.assertEqual(data['MYCE_SETTINGS']['site_name'], 'LIT Portal')
        self.assertEqual(data['MYCE_SETTINGS']['DEBUG'], settings.MY_CE['DEBUG'])
        self.assertEqual(settings.MY_CE, before)


class EmailTemplateTests(TestCase):
    FALLBACK = 'https://rmu.prod.canusiaplatform.com/static/images/logo.png'

    def _email(self, campus=None, brands=None):
        import os
        from django.template import Engine
        import cis
        # cis's own copy: on a tenant with myce_theme the loader would pick the theme's.
        path = os.path.join(os.path.dirname(cis.__file__), 'templates', 'cis', 'email.html')
        with open(path) as fh:
            source = fh.read()
        with _tenant(brands or {}), campus_context(campus):
            return Engine.get_default().from_string(source).render(Context({'message': 'hi'}))

    def test_no_campus_keeps_the_fallback_url(self):
        out = self._email()
        self.assertIn(self.FALLBACK, out)
        self.assertTrue(out.startswith('<!DOCTYPE'), out[:40])

    def test_campus_with_site_uses_its_domain(self):
        campus = _campus(domain='lit.example.edu')
        out = self._email(campus, {campus.code: {'logo': 'images/logo.png'}})
        self.assertIn('https://lit.example.edu/static/images/logo.png', out)
        self.assertNotIn(self.FALLBACK, out)

    @override_settings(MULTI_CAMPUS=True)
    def test_campus_without_site_keeps_the_fallback(self):
        campus = _campus()
        self.assertIn(self.FALLBACK, self._email(campus, {}))


class PageTemplateTests(TestCase):
    def test_header_includes_carries_brand_css_after_the_stylesheet(self):
        from django.template.loader import render_to_string
        campus = _campus()
        with _tenant({campus.code: {'colors': {'color-primary': '#29348f'}}}), \
                campus_context(campus):
            out = render_to_string('cis/header-includes.html')
        self.assertIn('--color-primary:#29348f', out)
        self.assertLess(out.index('css/style.css'), out.index('--color-primary'))

    def test_base_uses_campus_logo_and_background(self):
        from django.template.loader import render_to_string
        campus = _campus()
        with _tenant({campus.code: {'logo': 'brand/x/logo.png', 'background': 'brand/x/bg.jpg'}}), \
                campus_context(campus), override_settings(MY_CE={**settings.MY_CE, 'show_logo': 'True'}):
            out = render_to_string('cis/base.html', {'MYCE_SETTINGS': {**settings.MY_CE, 'show_logo': 'True'}})
        self.assertIn('/static/brand/x/logo.png', out)
        self.assertIn('/static/brand/x/bg.jpg', out)


class CampusCodeReadOnlyTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.staff = User.objects.create(username=f's-{uuid.uuid4().hex[:6]}',
                                         email=f'{uuid.uuid4().hex[:6]}@example.com')
        self.root = User.objects.create(username=f'r-{uuid.uuid4().hex[:6]}', is_superuser=True,
                                        email=f'{uuid.uuid4().hex[:6]}@example.com')
        self.campus = _campus(code='ORIG_CODE')

    def _data(self, code):
        return {'name': self.campus.name, 'code': code}

    def test_staff_cannot_change_an_existing_code(self):
        from cis.forms.course import CampusForm
        form = CampusForm(self._data('HIJACK'), instance=self.campus, user=self.staff)
        self.assertTrue(form.fields['code'].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().code, 'ORIG_CODE')

    def test_superuser_can_change_it(self):
        from cis.forms.course import CampusForm
        form = CampusForm(self._data('NEW_CODE'), instance=self.campus, user=self.root)
        self.assertFalse(form.fields['code'].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().code, 'NEW_CODE')

    def test_code_is_editable_on_add(self):
        from cis.forms.course import CampusForm
        self.assertFalse(CampusForm(user=self.staff).fields['code'].disabled)

    def test_campus_page_passes_the_user(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from cis.views import campus as campus_views
        request = RequestFactory().get('/')
        request.user = self.staff
        with mock.patch.object(campus_views, 'render', return_value=HttpResponse()) as render, \
                mock.patch.object(campus_views, 'draw_menu', return_value=''):
            campus_views.detail(request, self.campus.id)
        self.assertTrue(render.call_args.args[2]['form'].fields['code'].disabled)


class PortalNamesTests(TestCase):
    """Login views pass `portal` (their titles and headers use portal.site_name
    and portal.college_name); it must carry the campus's names too."""

    def test_branded_my_ce_overlays_names_on_a_copy(self):
        from cis.branding import branded_my_ce
        campus = _campus()
        before = dict(settings.MY_CE)
        with _tenant({campus.code: {'college_name': 'Lamar Institute of Technology'}}), \
                campus_context(campus):
            portal = branded_my_ce()
        self.assertEqual(portal['college_name'], 'Lamar Institute of Technology')
        self.assertEqual(portal['roles'], settings.MY_CE['roles'])
        self.assertEqual(settings.MY_CE, before)

    def test_login_page_portal_carries_campus_names(self):
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.http import HttpResponse
        from django.test import RequestFactory
        from cis.views import home
        campus = _campus()
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        SessionMiddleware(lambda r: None).process_request(request)
        with _tenant({campus.code: {'site_name': 'LIT Dual Credit'}}), campus_context(campus), \
                mock.patch.object(home, 'render', return_value=HttpResponse()) as render:
            home.index(request)
        self.assertEqual(render.call_args.args[2]['portal']['site_name'], 'LIT Dual Credit')
