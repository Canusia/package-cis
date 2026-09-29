"""MC-15 (#39): SAML IdP -> campus.

Each IdP maps to its campuses (Campus.saml_idps). In multi-campus mode an IdP
signs users in only on its own campuses' hosts, and a user with no campus
gets the IdP's campuses (default: the campus signed in on), so nobody who
signs in through SAML is left without a campus. Single-campus is unchanged.
"""
import uuid
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sites.models import Site
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from sp.models import IdP

from cis.middleware import CampusMiddleware
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.saml_backend import MyCE_SAMLAuthenticationBackend


def _campus(name, domain):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}',
        site=Site.objects.create(domain=domain, name=domain))


class _FakeIdP(SimpleNamespace):
    """Stands in for sp.IdP's SAML parsing; campuses come from the real row."""

    def get_nameid(self, saml):
        return saml

    def mapped_attributes(self, saml):
        return {}


class _Base(TestCase):
    def setUp(self):
        self.c1 = _campus('C1', 'c1.link.edu')
        self.c2 = _campus('C2', 'c2.link.edu')
        self.idp_row = IdP.objects.create(
            name=f'idp-{uuid.uuid4().hex[:6]}', contact_name='x',
            contact_email='x@x.com')
        self.c1.saml_idps.add(self.idp_row)
        self.idp = _FakeIdP(auth_case_sensitive=False,
                            campuses=self.idp_row.campuses)
        self.user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])

    def sign_in(self, host):
        """Run the SAML backend inside CampusMiddleware for ``host``."""
        seen = {}

        def view(request):
            seen['user'] = MyCE_SAMLAuthenticationBackend().authenticate(
                request, idp=self.idp, saml=self.user.username)
            return HttpResponse('ok')

        request = RequestFactory().get('/', HTTP_HOST=host)
        request.user = AnonymousUser()
        CampusMiddleware(view)(request)
        return seen.get('user')


class SingleCampusUnchangedTests(_Base):
    def test_signs_in_without_touching_campus(self):
        self.assertEqual(self.sign_in('c2.link.edu'), self.user)
        self.user.refresh_from_db()
        self.assertFalse((self.user.campus or {}).get('process_campus'))


@override_settings(ALLOWED_HOSTS=['*'], MULTI_CAMPUS=True)
class MultiCampusTests(_Base):
    def test_user_without_campus_gets_the_idp_campus(self):
        self.assertEqual(self.sign_in('c1.link.edu'), self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.campus['process_campus'], [str(self.c1.id)])
        self.assertEqual(self.user.campus['default_campus'], str(self.c1.id))

    def test_idp_refused_on_another_campus_host(self):
        self.assertIsNone(self.sign_in('c2.link.edu'))

    def test_unmapped_idp_is_refused(self):
        self.c1.saml_idps.clear()
        self.assertIsNone(self.sign_in('c1.link.edu'))

    def test_existing_campuses_are_kept(self):
        self.user.campus = {'process_campus': [str(self.c1.id), str(self.c2.id)],
                            'default_campus': str(self.c2.id)}
        self.user.save()
        self.sign_in('c1.link.edu')
        self.user.refresh_from_db()
        self.assertEqual(self.user.campus['default_campus'], str(self.c2.id))

    def test_signed_in_user_is_refused_on_the_other_campus(self):
        """Acceptance: a user from c1's IdP can use c1 and gets 403 on c2."""
        self.sign_in('c1.link.edu')
        self.user.refresh_from_db()

        def request(host):
            r = RequestFactory().get('/', HTTP_HOST=host)
            r.user = self.user
            return CampusMiddleware(lambda _: HttpResponse('ok'))(r).status_code

        self.assertEqual(request('c1.link.edu'), 200)
        self.assertEqual(request('c2.link.edu'), 403)


class CampusFormFieldsTests(TestCase):
    def test_single_campus_form_shows_routing_fields(self):
        from cis.forms.course import CampusForm
        self.assertIn('site', CampusForm().fields)
        self.assertIn('saml_idps', CampusForm().fields)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_form_maps_host_and_idps(self):
        from cis.forms.course import CampusForm
        self.assertIn('site', CampusForm().fields)
        self.assertIn('saml_idps', CampusForm().fields)


class CampusFormSavesTests(TestCase):
    """v0.1.1a: site and saml_idps are always on the form, and saved."""

    @classmethod
    def setUpClass(cls):
        # force_login's bare request crashes django_login_history's receiver.
        from django.contrib.auth.signals import user_logged_in
        try:
            from django_login_history.models import post_login
        except Exception:  # pragma: no cover
            post_login = None
        cls._post_login = post_login
        if post_login is not None:
            user_logged_in.disconnect(post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        from django.contrib.auth.signals import user_logged_in
        if cls._post_login is not None:
            user_logged_in.connect(cls._post_login)

    def test_add_saves_site_idps_and_locations(self):
        from django.test import Client
        from cis.models.course import Location
        su = CustomUser.objects.create_superuser(
            username=f'su{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        su.groups.add(Group.objects.get_or_create(name='ce')[0])
        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(su)
        site = Site.objects.create(domain='new.link.edu', name='new')
        idp = IdP.objects.create(name='idp', contact_name='x', contact_email='x@x.com')
        code = f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}'
        data = {'name': f'N-{code}', 'code': code, 'site': site.id, 'saml_idps': [idp.id]}
        location = Location.objects.first()
        if location:
            data['locations'] = [location.id]
        from django.urls import reverse
        client.post(reverse('cis:campus_add_new'), data)
        campus = Campus.objects.get(code=code)
        self.assertEqual(campus.site, site)
        self.assertEqual(list(campus.saml_idps.all()), [idp])
        if location:
            self.assertEqual(list(campus.locations.all()), [location])
