"""Unit tests for the CE campus-gate primitives (cis/campus_gate.py)."""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.course import Campus, Cohort, Course
from cis.campus_gate import (
    get_process_campus_ids,
    get_accessible_campuses,
    can_process_campus,
    scope_queryset_by_campus,
    processable_ids,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus(name=None):
    sfx = _sfx()
    return Campus.objects.create(
        name=name or f'Campus-{sfx}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{sfx}',
    )


def _ce_user(process_campus=None, default_campus=None):
    sfx = _sfx()
    user = User.objects.create_user(
        username=f'ce_{sfx}', email=f'ce_{sfx}@x.com', password='x',
    )
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.campus = {
        'process_campus': process_campus or [],
        'default_campus': default_campus or '',
    }
    user.save()
    return user


class CampusGatePrimitiveTests(TestCase):
    def setUp(self):
        self.campus_a = _campus('Alpha')
        self.campus_b = _campus('Beta')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')

    def _course(self, campus):
        return Course.objects.create(
            catalog_number='101', title='Intro',
            cohort=self.cohort, campus=campus,
        )

    def test_process_ids_reads_json(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        self.assertEqual(get_process_campus_ids(user), [str(self.campus_a.id)])

    def test_process_ids_empty_when_no_campus_data(self):
        user = _ce_user()
        self.assertEqual(get_process_campus_ids(user), [])

    def test_superuser_gets_all_prefixed_campuses(self):
        su = User.objects.create_superuser(
            username='su', email='su@x.com', password='x')
        ids = get_process_campus_ids(su)
        self.assertIn(str(self.campus_a.id), ids)
        self.assertIn(str(self.campus_b.id), ids)

    def test_accessible_campuses_intersects_process(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        got = list(get_accessible_campuses(user))
        self.assertEqual(got, [self.campus_a])

    def test_can_process_true_for_own_campus(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        self.assertTrue(can_process_campus(user, self.campus_a))

    def test_can_process_false_for_other_campus(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        self.assertFalse(can_process_campus(user, self.campus_b))

    def test_can_process_true_for_null_campus(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        self.assertTrue(can_process_campus(user, None))

    def test_scope_includes_own_and_null_excludes_other(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        c_a = self._course(self.campus_a)
        c_b = self._course(self.campus_b)
        c_none = self._course(None)
        scoped = scope_queryset_by_campus(Course.objects.all(), user)
        self.assertIn(c_a, scoped)
        self.assertIn(c_none, scoped)
        self.assertNotIn(c_b, scoped)

    def test_scope_superuser_unchanged(self):
        su = User.objects.create_superuser(
            username='su2', email='su2@x.com', password='x')
        c_b = self._course(self.campus_b)
        self.assertIn(c_b, scope_queryset_by_campus(Course.objects.all(), su))

    def test_scope_noop_for_non_ce_user(self):
        from django.contrib.auth.models import Group
        sfx = _sfx()
        instructor = User.objects.create_user(
            username=f'inst_{sfx}', email=f'inst_{sfx}@x.com', password='x')
        instructor.groups.add(Group.objects.get_or_create(name='instructor')[0])
        c_a = self._course(self.campus_a)
        c_b = self._course(self.campus_b)
        scoped = scope_queryset_by_campus(Course.objects.all(), instructor)
        # A non-ce user is NOT campus-filtered by this helper.
        self.assertIn(c_a, scoped)
        self.assertIn(c_b, scoped)

    def test_processable_ids_drops_out_of_scope_and_bad(self):
        user = _ce_user(process_campus=[str(self.campus_a.id)])
        c_a = self._course(self.campus_a)
        c_b = self._course(self.campus_b)
        c_none = self._course(None)
        result = processable_ids(
            Course, [str(c_a.id), str(c_b.id), str(c_none.id), 'not-a-uuid'], user)
        self.assertIn(str(c_a.id), result)      # own campus kept
        self.assertIn(str(c_none.id), result)   # null campus kept
        self.assertNotIn(str(c_b.id), result)   # other campus dropped
        self.assertNotIn('not-a-uuid', result)  # bad id dropped


from django.test import RequestFactory

from cis.campus_gate import campus_gate


class CampusGateDecoratorTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.campus_a = _campus('Alpha')
        self.campus_b = _campus('Beta')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)
        self.user = _ce_user(process_campus=[str(self.campus_a.id)])

    def _view(self, mode):
        @campus_gate(Course, mode=mode)
        def view(request, record_id):
            from django.http import HttpResponse
            return HttpResponse('OK')
        return view

    def test_page_mode_denies_with_403(self):
        req = self.rf.get('/x')
        req.user = self.user
        resp = self._view('page')(req, record_id=self.course_b.id)
        self.assertEqual(resp.status_code, 403)

    def test_json_mode_denies_with_403_json(self):
        req = self.rf.get('/x')
        req.user = self.user
        resp = self._view('json')(req, record_id=self.course_b.id)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp['Content-Type'], 'application/json')

    def test_allows_own_campus(self):
        course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        req = self.rf.get('/x')
        req.user = self.user
        resp = self._view('page')(req, record_id=course_a.id)
        self.assertEqual(resp.status_code, 200)

    def test_allows_null_campus(self):
        course_none = Course.objects.create(
            catalog_number='100', title='N', cohort=self.cohort, campus=None)
        req = self.rf.get('/x')
        req.user = self.user
        resp = self._view('json')(req, record_id=course_none.id)
        self.assertEqual(resp.status_code, 200)
