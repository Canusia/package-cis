import datetime

from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.course import Course
from cis.views.credentials import CredentialExpiryViewSet, CredentialSummaryViewSet


class _Req:
    def __init__(self, params, user):
        self.GET = params
        self.user = user


class CredentialViewSetTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='instructor')
        self.staff = CustomUser.objects.create(username='staff', email='s@x.com')
        self.staff.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.user = CustomUser.objects.create(
            username='i', email='i@x.com', first_name='Pat', last_name='Lee')
        self.teacher = Teacher.objects.create(user=self.user, status='active')
        self.hs = HighSchool.objects.create(name='HS', status='Active')
        self.ths = TeacherHighSchool.objects.create(
            teacher=self.teacher, highschool=self.hs, status='In the Program')
        self.course = Course.objects.create(
            name='ENGL& 101', status='active', cohort=self._cohort(),
            title='English Composition', catalog_number='101')

    def _cohort(self):
        from cis.models.course import Cohort
        return Cohort.objects.create(name='English', designator='ENGL&')

    def _cert(self, days, course=None):
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=self.ths, course=course or self.course,
            status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=days))

    def test_default_all_includes_far_future(self):
        # Default (no days param) shows ALL certificates, including far-future.
        near = self._cert(30)
        far_course = Course.objects.create(
            name='MATH& 141', status='active', cohort=self._cohort2(),
            title='Calculus', catalog_number='141')
        far = self._cert(200, course=far_course)
        vs = CredentialExpiryViewSet()
        vs.request = _Req({}, self.staff)
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(near.id, ids)
        self.assertIn(far.id, ids)

    def test_instructor_sees_only_own_certificates(self):
        # The instructor portal reuses CredentialExpiryViewSet; a non-CE caller
        # is scoped to their own certificates.
        mine = self._cert(30)  # self.ths (teacher=self.user)
        u2 = CustomUser.objects.create(
            username='i2', email='i2@x.com', first_name='Sam', last_name='Roe')
        t2 = Teacher.objects.create(user=u2, status='active')
        ths2 = TeacherHighSchool.objects.create(
            teacher=t2, highschool=self.hs, status='In the Program')
        c2 = Course.objects.create(
            name='MATH& 141', status='active', cohort=self._cohort2(),
            title='Calculus', catalog_number='141')
        theirs = TeacherCourseCertificate.objects.create(
            teacher_highschool=ths2, course=c2, status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=30))
        vs = CredentialExpiryViewSet()
        vs.request = _Req({}, self.user)  # self.user is the instructor
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(mine.id, ids)
        self.assertNotIn(theirs.id, ids)

    def test_highschool_admin_sees_only_their_schools_certificates(self):
        # The HS-admin portal reuses CredentialExpiryViewSet; an HS admin sees
        # every instructor's certificates at their high school(s), but not
        # certificates from a high school they don't administer.
        from django.contrib.auth.models import Group
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition, HSPosition,
        )
        # Cert at the admin's school (self.hs), for a different instructor.
        mine = self._cert(30)  # self.ths lives at self.hs
        # Cert at a school the admin does NOT administer.
        other_hs = HighSchool.objects.create(name='Other HS', status='Active')
        u2 = CustomUser.objects.create(
            username='i2', email='i2@x.com', first_name='Sam', last_name='Roe')
        t2 = Teacher.objects.create(user=u2, status='active')
        ths2 = TeacherHighSchool.objects.create(
            teacher=t2, highschool=other_hs, status='In the Program')
        c2 = Course.objects.create(
            name='MATH& 141', status='active', cohort=self._cohort2(),
            title='Calculus', catalog_number='141')
        theirs = TeacherCourseCertificate.objects.create(
            teacher_highschool=ths2, course=c2, status='Teaching',
            expires_on=timezone.localdate() + datetime.timedelta(days=30))

        admin = CustomUser.objects.create(
            username='hsa', email='hsa@x.com', first_name='Dana', last_name='Kim')
        admin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])
        hsadmin = HSAdministrator.objects.create(user=admin)
        position = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=self.hs, position=position, status='Active')

        vs = CredentialExpiryViewSet()
        vs.request = _Req({}, admin)
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(mine.id, ids)
        self.assertNotIn(theirs.id, ids)

    def test_days_param_90_excludes_far_future(self):
        near = self._cert(30)
        far_course = Course.objects.create(
            name='MATH& 141', status='active', cohort=self._cohort2(),
            title='Calculus', catalog_number='141')
        far = self._cert(200, course=far_course)
        vs = CredentialExpiryViewSet()
        vs.request = _Req({'days': '90'}, self.staff)
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(near.id, ids)
        self.assertNotIn(far.id, ids)

    def _cohort2(self):
        from cis.models.course import Cohort
        return Cohort.objects.create(name='Math', designator='MATH&')

    def test_days_param_30_excludes_60(self):
        d30 = self._cert(20)
        c2 = Course.objects.create(
            name='HIST& 146', status='active', cohort=self._cohort2(),
            title='History', catalog_number='146')
        d60 = self._cert(50, course=c2)
        vs = CredentialExpiryViewSet()
        vs.request = _Req({'days': '30'}, self.staff)
        ids = set(vs.get_queryset().values_list('id', flat=True))
        self.assertIn(d30.id, ids)
        self.assertNotIn(d60.id, ids)

    def test_summary_by_course_groups_and_counts(self):
        self._cert(30)
        c2 = Course.objects.create(
            name='BIOL& 160', status='active', cohort=self._cohort2(),
            title='Biology', catalog_number='160')
        self._cert(40, course=c2)
        vs = CredentialSummaryViewSet()
        vs.request = _Req({'group_by': 'course'}, self.staff)
        rows = list(vs.get_queryset())
        total = sum(r['count'] for r in rows)
        self.assertEqual(total, 2)

    def test_expiry_queryset_orderable_by_computed_columns(self):
        # Regression: the rest_framework_datatables backend orders/searches by
        # the column NAME. instructor_name / highschool_name / course_name must
        # be real annotations or order_by/filter raise FieldError.
        self._cert(30)
        vs = CredentialExpiryViewSet()
        vs.request = _Req({}, self.staff)
        qs = vs.get_queryset()
        for col in ('instructor_name', 'highschool_name', 'course_name'):
            rows = list(qs.order_by(col))                          # must not raise
            self.assertTrue(hasattr(rows[0], col))
            self.assertEqual(                                     # search path
                qs.filter(**{col + '__icontains': ''}).count(), len(rows))
        first = list(qs)[0]
        self.assertEqual(first.instructor_name, 'Lee, Pat')
        self.assertEqual(first.highschool_name, 'HS')
        self.assertEqual(first.course_name, 'ENGL& 101')

    def test_summary_by_course_breaks_down_by_status(self):
        # By-course summary groups by (course, status): one row per status.
        self._cert(30)  # self.course, status 'Teaching'
        u2 = CustomUser.objects.create(
            username='i2', email='i2@x.com', first_name='Sam', last_name='Roe')
        t2 = Teacher.objects.create(user=u2, status='active')
        ths2 = TeacherHighSchool.objects.create(
            teacher=t2, highschool=self.hs, status='In the Program')
        TeacherCourseCertificate.objects.create(
            teacher_highschool=ths2, course=self.course, status='Expired',
            expires_on=timezone.localdate() + datetime.timedelta(days=10))
        vs = CredentialSummaryViewSet()
        vs.request = _Req({'group_by': 'course'}, self.staff)
        rows = [r for r in vs.get_queryset() if r['group'] == self.course.name]
        self.assertTrue(all('status' in r for r in rows))
        by_status = {r['status']: r['count'] for r in rows}
        self.assertEqual(by_status.get('Teaching'), 1)
        self.assertEqual(by_status.get('Expired'), 1)

    def test_summary_by_highschool_not_grouped_by_status(self):
        self._cert(30)
        vs = CredentialSummaryViewSet()
        vs.request = _Req({'group_by': 'highschool'}, self.staff)
        rows = list(vs.get_queryset())
        self.assertTrue(all('status' not in r for r in rows))

    def test_summary_queryset_orderable_and_searchable_by_group(self):
        # Regression: the rest_framework_datatables backend orders/filters by
        # the column's `data` name ('group'). The summary queryset must expose
        # `group` as a real annotation so order_by/filter don't raise FieldError.
        self._cert(30)
        for group_by in ('course', 'highschool'):
            vs = CredentialSummaryViewSet()
            vs.request = _Req({'group_by': group_by}, self.staff)
            qs = vs.get_queryset()
            ordered = list(qs.order_by('group'))          # must not raise
            self.assertIn('group', ordered[0])
            self.assertEqual(
                qs.filter(group__icontains='').count(),   # search path
                len(ordered),
            )


class CredentialBulkFormTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from cis.models.course import Cohort
        Group.objects.get_or_create(name='instructor')
        user = CustomUser.objects.create(username='i2', email='i2@x.com',
                                         first_name='A', last_name='B')
        teacher = Teacher.objects.create(user=user, status='active')
        hs = HighSchool.objects.create(name='HS2', status='Active')
        ths = TeacherHighSchool.objects.create(
            teacher=teacher, highschool=hs, status='In the Program')
        course = Course.objects.create(
            name='ENGL& 101', status='active',
            cohort=Cohort.objects.create(name='Eng', designator='ENGL&'),
            title='Eng', catalog_number='101')
        self.cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=course, status='Teaching')

    def test_apply_updates_only_provided_fields(self):
        from cis.forms.credential_bulk import CredentialBulkUpdateForm
        form = CredentialBulkUpdateForm(data={
            'ids': str(self.cert.id),
            'action': 'bulk_update',
            'status': 'Inactive',
            'expires_on': '06/30/2026',
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        count = form.apply()
        self.assertEqual(count, 1)
        self.cert.refresh_from_db()
        self.assertEqual(self.cert.status, 'Inactive')
        self.assertEqual(self.cert.expires_on, datetime.date(2026, 6, 30))
        self.assertIsNone(self.cert.renewal_required_by)  # left untouched
