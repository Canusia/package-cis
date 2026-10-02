"""CE high school pages are scoped to the host campus."""
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.reports.highschool_export import highschool_export
from cis.views import highschool as views

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f'C-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}_{_sfx()}')


def _hs(name, campus=None, status='Active', code='', **kw):
    hs = HighSchool.objects.create(name=name, code=_sfx(), **kw)
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus:
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, status=status, building_code=code)
    return hs


class _Base(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='ce')
        User.objects.get_or_create(username='cron', defaults={'email': 'cron@x.com'})
        self.a, self.b = _campus(), _campus()
        self.staff = User.objects.create_user(
            username=f'ce-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.staff.groups.add(Group.objects.get(name='ce'))
        self.su = User.objects.create_superuser(
            username=f'su-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.su.groups.add(Group.objects.get(name='ce'))
        self.alpha = _hs('Alpha', self.a, code='AA', latitude=1, longitude=1)
        self.bravo = _hs('Bravo', self.a, status='Inactive', code='BB',
                         latitude=1, longitude=1)
        self.charlie = _hs('Charlie', self.b, latitude=1, longitude=1)
        self.delta = _hs('Delta', latitude=1, longitude=1)

    def _list(self, user, campus, query=''):
        req = APIRequestFactory().get('/ce/api/highschool' + query)
        force_authenticate(req, user=user)
        with campus_context(campus):
            resp = views.HighSchoolViewSet.as_view({'get': 'list'})(req)
        return {r['name'] for r in resp.data['results']} \
            if 'results' in resp.data else {r['name'] for r in resp.data}


@override_settings(MULTI_CAMPUS=True)
class ListTests(_Base):
    def test_list_only_campus_linked(self):
        self.assertEqual(self._list(self.staff, self.a), {'Alpha', 'Bravo'})

    def test_active_filter_uses_link_status(self):
        self.assertEqual(
            self._list(self.staff, self.a, '?status=Active'), {'Alpha'})
        self.assertEqual(
            self._list(self.staff, self.a, '?status=Inactive'), {'Bravo'})

    def test_active_filter_ignores_global_status_of_other_campus(self):
        # Charlie is Active at b only; at a it is not linked at all.
        self.assertEqual(
            self._list(self.staff, self.b, '?status=Active'), {'Charlie'})

    def test_superuser_sees_all(self):
        self.assertEqual(
            self._list(self.su, self.a),
            {'Alpha', 'Bravo', 'Charlie', 'Delta'})

    def test_linked_filter_superuser(self):
        self.assertEqual(self._list(self.su, self.a, '?linked=yes'),
                         {'Alpha', 'Bravo'})
        self.assertEqual(self._list(self.su, self.a, '?linked=no'),
                         {'Charlie', 'Delta'})
        self.assertEqual(self._list(self.su, self.a, '?linked=bogus'),
                         {'Alpha', 'Bravo', 'Charlie', 'Delta'})

    def test_linked_filter_ignored_for_non_superuser(self):
        for v in ('yes', 'no'):
            self.assertEqual(self._list(self.staff, self.a, '?linked=' + v),
                             {'Alpha', 'Bravo'})

    def test_serializes_campus_building_code_and_status(self):
        req = APIRequestFactory().get('/ce/api/highschool')
        force_authenticate(req, user=self.staff)
        with campus_context(self.a):
            resp = views.HighSchoolViewSet.as_view({'get': 'list'})(req)
        rows = {r['name']: r for r in
                (resp.data['results'] if 'results' in resp.data else resp.data)}
        self.assertEqual(rows['Alpha']['campus_building_code'], 'AA')
        self.assertEqual(rows['Bravo']['campus_status'], 'Inactive')


@override_settings(MULTI_CAMPUS=False)
class SingleCampusListTests(_Base):
    def test_single_campus_uses_deployment_campus(self):
        dep = Campus.objects.filter(
            code__startswith=settings.CAMPUS_CODE_PREFIX).order_by('name').first()
        link = HighSchoolCampus.objects.filter(campus=dep).first()
        if link is None:
            self.skipTest('no deployment links')
        names = self._list(self.staff, None)
        self.assertIn(link.highschool.name, names)


@override_settings(MULTI_CAMPUS=True)
class DetailTests(_Base):
    def _detail(self, user, hs, campus):
        req = RequestFactory().get(f'/ce/highschool/{hs.pk}')
        req.user = user
        with campus_context(campus):
            return views.detail(req, hs.pk)

    def test_unlinked_is_404(self):
        with self.assertRaises(Http404):
            self._detail(self.staff, self.charlie, self.a)

    def test_unlinked_tab_is_404(self):
        req = RequestFactory().get('/x')
        req.user = self.staff
        with campus_context(self.a):
            with self.assertRaises(Http404):
                views.tab(req, self.charlie.pk, 'campuses')

    def test_superuser_not_404(self):
        try:
            self._detail(self.su, self.charlie, self.a)
        except Http404:
            self.fail('superuser got 404')
        except Exception:
            pass  # rendering needs a full request stack


@override_settings(MULTI_CAMPUS=True)
class MapTests(_Base):
    def _map(self, user, campus):
        req = RequestFactory().get('/ce/highschool/map')
        req.user = user
        with campus_context(campus):
            resp = views.highschool_map_data(req)
        return {s['name'] for s in json.loads(resp.content)['schools']}

    def test_map_scoped_to_active_links(self):
        self.assertEqual(self._map(self.staff, self.a), {'Alpha'})
        self.assertEqual(self._map(self.staff, self.b), {'Charlie'})


@override_settings(MULTI_CAMPUS=True)
class ExportTests(_Base):
    def _export(self, user, campus, statuses):
        req = RequestFactory().get('/x', {'report_id': 'x'})
        req.user = user
        form = highschool_export(
            req, data={'highschool_status': statuses})
        self.assertTrue(form.is_valid(), form.errors)
        with campus_context(campus):
            resp = form.run_report()
        return resp.content.decode()

    def test_export_scoped_and_link_status(self):
        out = self._export(self.staff, self.a, ['Active'])
        self.assertIn('Alpha', out)
        self.assertNotIn('Bravo', out)
        self.assertNotIn('Charlie', out)
        out = self._export(self.staff, self.a, ['Active', 'Inactive'])
        self.assertIn('Bravo', out)

    def test_export_status_is_link_status(self):
        out = self._export(self.staff, self.a, ['Active', 'Inactive'])
        rows = {l.split(',')[0]: l.strip().split(',')[-1]
                for l in out.splitlines()[1:]}
        self.assertEqual(rows['Alpha'], 'Active')
        self.assertEqual(rows['Bravo'], 'Inactive')

    def test_export_superuser_status_filter_is_link_status_here(self):
        # Same as the list: a status filter means link status on this campus,
        # so schools not linked here never appear (and never show a status).
        out = self._export(self.su, self.a, ['Active', 'Inactive'])
        self.assertNotIn('Charlie', out)
        self.assertNotIn('Delta', out)
