"""Consortium / ConsortiumMembership and CourseType / HighSchoolCourseType.

Phase 1 of docs/plans/highschool-consortium-and-course-types.md (ewu):
models only, no behavior. Nothing reads these yet.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from cis.forms.highschool import HSModelForm
from cis.models import (
    Consortium, ConsortiumMembership, CourseType, HighSchoolCourseType)
from cis.models.course import Campus
from cis.models.highschool import HighSchool
from cis.serializers.highschool import HighSchoolSerializer

PREFIX = settings.CAMPUS_CODE_PREFIX


def _sfx():
    return uuid.uuid4().hex[:8]


def _hs(name=None):
    return HighSchool.objects.create(name=name or f'HS-{_sfx()}', code=_sfx())


def _campus():
    return Campus.objects.create(name=f'C-{_sfx()}', code=f'{PREFIX}_{_sfx()}')


def _course_type(**kw):
    kw.setdefault('code', f'ct_{_sfx()}')
    kw.setdefault('name', kw['code'])
    return CourseType.objects.create(**kw)


class ConsortiumModelTests(TestCase):

    def test_membership_defaults(self):
        member = ConsortiumMembership.objects.create(
            consortium=Consortium.objects.create(name=f'Co-{_sfx()}'), highschool=_hs())
        self.assertEqual(member.status, 'Active')
        self.assertEqual(member.billing_basis, ConsortiumMembership.BILLING_HOST_SCHOOL)
        self.assertIsNone(member.joined_on)

    def test_school_joins_a_consortium_once(self):
        consortium, hs = Consortium.objects.create(name=f'Co-{_sfx()}'), _hs()
        ConsortiumMembership.objects.create(consortium=consortium, highschool=hs)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConsortiumMembership.objects.create(consortium=consortium, highschool=hs)

    def test_consortium_name_is_unique(self):
        name = f'Co-{_sfx()}'
        Consortium.objects.create(name=name)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Consortium.objects.create(name=name)

    def test_m2m_reaches_members_both_ways(self):
        consortium, a, b = Consortium.objects.create(name=f'Co-{_sfx()}'), _hs(), _hs()
        for hs in (a, b):
            ConsortiumMembership.objects.create(consortium=consortium, highschool=hs)
        self.assertEqual(set(consortium.highschools.all()), {a, b})
        self.assertEqual(list(a.consortiums.all()), [consortium])

    def test_membership_writes_history(self):
        member = ConsortiumMembership.objects.create(
            consortium=Consortium.objects.create(name=f'Co-{_sfx()}'), highschool=_hs())
        member.billing_basis = ConsortiumMembership.BILLING_HOME_SCHOOL
        member.save()
        self.assertEqual(member.history.count(), 2)


class CourseTypeModelTests(TestCase):

    def test_defaults(self):
        course_type = _course_type()
        self.assertTrue(course_type.approvable)
        self.assertEqual(course_type.status, 'Active')

    def test_code_is_unique(self):
        _course_type(code='online')
        with self.assertRaises(IntegrityError), transaction.atomic():
            _course_type(code='online')

    def test_in_use_course_type_cannot_be_deleted(self):
        course_type = _course_type()
        HighSchoolCourseType.objects.create(highschool=_hs(), course_type=course_type)
        with self.assertRaises(ProtectedError):
            course_type.delete()

    def test_all_campus_approval_once(self):
        hs, course_type = _hs(), _course_type()
        HighSchoolCourseType.objects.create(highschool=hs, course_type=course_type)
        with self.assertRaises(IntegrityError), transaction.atomic():
            HighSchoolCourseType.objects.create(highschool=hs, course_type=course_type)

    def test_campus_approval_once_per_campus(self):
        hs, course_type, campus = _hs(), _course_type(), _campus()
        HighSchoolCourseType.objects.create(
            highschool=hs, course_type=course_type, campus=campus)
        HighSchoolCourseType.objects.create(
            highschool=hs, course_type=course_type, campus=_campus())
        with self.assertRaises(IntegrityError), transaction.atomic():
            HighSchoolCourseType.objects.create(
                highschool=hs, course_type=course_type, campus=campus)

    def test_clean_rejects_all_campus_and_campus_overlap(self):
        hs, course_type = _hs(), _course_type()
        HighSchoolCourseType.objects.create(highschool=hs, course_type=course_type)
        overlapping = HighSchoolCourseType(
            highschool=hs, course_type=course_type, campus=_campus())
        with self.assertRaises(ValidationError):
            overlapping.clean()

    def test_clean_rejects_campus_then_all_campus_overlap(self):
        hs, course_type = _hs(), _course_type()
        HighSchoolCourseType.objects.create(
            highschool=hs, course_type=course_type, campus=_campus())
        with self.assertRaises(ValidationError):
            HighSchoolCourseType(highschool=hs, course_type=course_type).clean()

    def test_approved_course_types_m2m(self):
        hs, course_type = _hs(), _course_type()
        HighSchoolCourseType.objects.create(highschool=hs, course_type=course_type)
        self.assertEqual(list(hs.approved_course_types.all()), [course_type])


class EditSurfacesUnchangedTests(TestCase):
    """The tabs are the only edit path; existing forms and payloads don't change."""

    def test_details_form_does_not_expose_the_m2ms(self):
        fields = HSModelForm().fields
        self.assertNotIn('consortiums', fields)
        self.assertNotIn('approved_course_types', fields)

    def test_highschool_serializer_does_not_expose_the_m2ms(self):
        data = HighSchoolSerializer(_hs()).data
        self.assertNotIn('consortiums', data)
        self.assertNotIn('approved_course_types', data)
