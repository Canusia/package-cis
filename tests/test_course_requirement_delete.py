"""Bulk Delete on the course requirement tables.

The thing that must not regress: ids are re-validated against the caller's
campus server-side. The rendered button list is not a permission check.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.course import (
    Campus, Cohort, Course, CourseAppRequirement, CourseDocumentRequirement,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _Base(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course_a = Course.objects.create(
            name='Course A', catalog_number=f'A{_sfx()}',
            cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            name='Course B', catalog_number=f'B{_sfx()}',
            cohort=self.cohort, campus=self.campus_b)

        Group.objects.get_or_create(name='ce')
        sfx = _sfx()
        self.user = User.objects.create_user(
            username=f'ce{sfx}', email=f'ce{sfx}@example.com', password='x')
        self.user.groups.add(Group.objects.get(name='ce'))
        self.user.campus = {'process_campus': [str(self.campus_a.id)]}
        self.user.save()

    def _post(self, ids):
        request = self.factory.post('/ce/courses/bulk/', {'ids[]': ids})
        request.user = self.user
        return request


class DeleteCourseDocRequirementsTests(_Base):
    def setUp(self):
        super().setUp()
        self.req_a = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='transcript')
        self.req_b = CourseDocumentRequirement.objects.create(
            course=self.course_b, document='transcript')

    def test_deletes_requirement_in_users_campus(self):
        from cis.views.course import delete_course_doc_requirements

        delete_course_doc_requirements(self._post([str(self.req_a.id)]))

        self.assertFalse(
            CourseDocumentRequirement.objects.filter(id=self.req_a.id).exists())

    def test_skips_requirement_outside_users_campus(self):
        from cis.views.course import delete_course_doc_requirements

        response = delete_course_doc_requirements(self._post([str(self.req_b.id)]))

        self.assertTrue(
            CourseDocumentRequirement.objects.filter(id=self.req_b.id).exists())
        self.assertIn(b'Skipped 1', response.content)

    def test_leaves_sibling_requirements_alone(self):
        from cis.views.course import delete_course_doc_requirements

        sibling = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='tsi')

        delete_course_doc_requirements(self._post([str(self.req_a.id)]))

        self.assertTrue(
            CourseDocumentRequirement.objects.filter(id=sibling.id).exists())
