"""MC-02 (#26) host -> campus, and MC-03 (#27) the staff campus boundary.

CampusMiddleware resolves the request host to a django.contrib.sites Site and
from there to the Campus linked by Campus.site, sets request.site and
request.campus, and serves the request inside campus_context(). In
multi-campus mode an unknown host is a 400 -- never a default campus -- and a
CE staff member whose campuses don't include the host's campus gets a 403.
Single-campus deployments pass through untouched.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sites.models import Site
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from cis.campus_context import current_campus_or_none
from cis.middleware import CampusMiddleware
from cis.models.course import Campus
from cis.models.customuser import CustomUser


def _campus(name, domain=None):
    site = Site.objects.create(domain=domain, name=domain) if domain else None
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}', site=site)


class _Base(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.seen = {}

        def view(request):
            self.seen['campus'] = request.campus
            self.seen['context'] = current_campus_or_none()
            self.seen['site'] = getattr(request, 'site', None)
            return HttpResponse('ok')

        self.middleware = CampusMiddleware(view)

    def request(self, host, user=None):
        request = RequestFactory().get('/', HTTP_HOST=host)
        request.user = user or AnonymousUser()
        return self.middleware(request)

    def ce_user(self, *campuses):
        user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
        user.campus = {'process_campus': [str(c.id) for c in campuses]}
        user.save()
        return user


class SingleCampusTests(_Base):
    def test_two_prefixed_campuses_still_pass_through(self):
        """A second prefixed campus must not switch on host routing."""
        _campus('A', 'a.link.edu')
        _campus('B', 'b.link.edu')
        self.assertEqual(self.request('testserver').status_code, 200)

    def test_passes_through_with_the_only_campus(self):
        only = _campus('Only')
        response = self.request('anything.example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen['campus'], only)
        self.assertEqual(self.seen['context'], only)

    def test_ce_user_without_campuses_is_not_blocked(self):
        _campus('Only')
        response = self.request('anything.example.com', self.ce_user())
        self.assertEqual(response.status_code, 200)


@override_settings(ALLOWED_HOSTS=['*'], MULTI_CAMPUS=True)
class MultiCampusHostTests(_Base):
    def setUp(self):
        super().setUp()
        self.c1 = _campus('C1', 'c1.link.edu')
        self.c2 = _campus('C2', 'c2.link.edu')

    def test_each_host_resolves_to_its_campus(self):
        for host, campus in (('c1.link.edu', self.c1), ('c2.link.edu', self.c2)):
            with self.subTest(host=host):
                self.assertEqual(self.request(host).status_code, 200)
                self.assertEqual(self.seen['campus'], campus)
                self.assertEqual(self.seen['site'], campus.site)
                self.assertEqual(self.seen['context'], campus)

    def test_port_and_case_are_ignored(self):
        self.assertEqual(self.request('C1.Link.edu:8003').status_code, 200)
        self.assertEqual(self.seen['campus'], self.c1)

    def test_unknown_host_is_400_not_a_default_campus(self):
        response = self.request('elsewhere.link.edu')
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('campus', self.seen)

    def test_context_is_cleared_after_the_request(self):
        self.request('c1.link.edu')
        self.assertIsNone(current_campus_or_none())

    def test_domain_change_takes_effect(self):
        self.c1.site.domain = 'new-c1.link.edu'
        self.c1.site.save()
        self.assertEqual(self.request('new-c1.link.edu').status_code, 200)
        self.assertEqual(self.seen['campus'], self.c1)
        self.assertEqual(self.request('c1.link.edu').status_code, 400)


@override_settings(ALLOWED_HOSTS=['*'], MULTI_CAMPUS=True)
class StaffCampusBoundaryTests(_Base):
    """MC-03: the host's campus must be one of a CE staff member's campuses."""

    def setUp(self):
        super().setUp()
        self.c1 = _campus('C1', 'c1.link.edu')
        self.c2 = _campus('C2', 'c2.link.edu')

    def test_single_campus_staff_refused_on_the_other_host(self):
        s1 = self.ce_user(self.c1)
        self.assertEqual(self.request('c1.link.edu', s1).status_code, 200)
        self.assertEqual(self.request('c2.link.edu', s1).status_code, 403)

    def test_dual_campus_staff_can_use_both_hosts(self):
        both = self.ce_user(self.c1, self.c2)
        self.assertEqual(self.request('c1.link.edu', both).status_code, 200)
        self.assertEqual(self.request('c2.link.edu', both).status_code, 200)

    def test_staff_with_no_campus_are_refused(self):
        self.assertEqual(self.request('c1.link.edu', self.ce_user()).status_code, 403)

    def test_superuser_is_not_refused(self):
        su = CustomUser.objects.create_superuser(
            username=f'su{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.assertEqual(self.request('c2.link.edu', su).status_code, 200)

    def test_non_staff_roles_are_not_checked_here(self):
        """Students, instructors and HS admins carry no process_campus; their
        records scope them (MC-13), so the host check leaves them alone."""
        student = CustomUser.objects.create_user(
            username=f'st{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        student.groups.add(Group.objects.get_or_create(name='student')[0])
        self.assertEqual(self.request('c2.link.edu', student).status_code, 200)

    def test_anonymous_can_reach_the_login_page(self):
        self.assertEqual(self.request('c2.link.edu').status_code, 200)
